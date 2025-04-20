# lotto_tracker.py – Discord‑py 2.x extension that adds a lotto‑trade competition tracker
# ---------------------------------------------------------------------------
# Commands
#   • !trade open       <ticker> <strike><C/P> <expiry YYYY‑MM‑DD> <entryPrice> [qty]
#   • !trade close      <id> <exitPrice>  |  !trade close <exitPrice>
#   • !trade list       – show caller’s open trades
#   • !trade history    – paginated closed‑trade log  (add “all” for mods)
#   • !trade leaderboard – ranks by average % gain
#   • !trade export     – DM a CSV of your history
#   • !trade purge      – purge own trade, or mods purge another user’s trade
#   • !trade reset      – mods wipe ALL trades & stats
#
# 🛢  Storage: TinyDB (JSON) – path from env var LOTTO_DB_PATH (default trades.json)
# ---------------------------------------------------------------------------

import asyncio
import csv
import io
import os
from datetime import datetime
from typing import Dict, List

import discord
from discord import Embed, Colour, ui, Interaction
from discord.ext import commands
from tinydb import TinyDB, Query

DB_PATH_DEFAULT = os.getenv("LOTTO_DB_PATH", "trades.json")

# ────────── helpers ────────────────────────────────────────────────────────


def _simple_embed(title: str, desc: str, success: bool | None = None) -> Embed:
    """Return a coloured embed with optional green/red status."""
    if success is None:
        color = Colour.blue()
    else:
        color = Colour.green() if success else Colour.red()
    return Embed(title=title, description=desc, color=color)


# ────────── paginator view ─────────────────────────────────────────────────


class ListPaginator(ui.View):
    """Button paginator that works for both Context.send and Interaction.response."""

    def __init__(self, pages: List[str], title: str):
        super().__init__(timeout=180)
        self.pages = pages
        self.title = title
        self.page = 0

        self.prev_button.disabled = True
        if len(pages) == 1:
            self.next_button.disabled = True

    async def send(self, target):
        """Show first page via ctx.send or interaction.response.send_message."""
        embed = _simple_embed(self.title, self.pages[self.page])
        if hasattr(target, "send"):           # commands.Context
            await target.send(embed=embed, view=self)
        else:                                 # Interaction
            await target.response.send_message(embed=embed, view=self, ephemeral=True)

    # buttons --------------------------------------------------------------
    @ui.button(label="« Prev", style=discord.ButtonStyle.grey)
    async def prev_button(self, interaction: Interaction, _):
        self.page -= 1
        self.next_button.disabled = False
        self.prev_button.disabled = self.page == 0
        await self._update(interaction)

    @ui.button(label="Next »", style=discord.ButtonStyle.grey)
    async def next_button(self, interaction: Interaction, _):
        self.page += 1
        self.prev_button.disabled = False
        self.next_button.disabled = self.page == len(self.pages) - 1
        await self._update(interaction)

    async def _update(self, interaction: Interaction):
        embed = _simple_embed(self.title, self.pages[self.page])
        await interaction.response.edit_message(embed=embed, view=self)


# ────────── main Cog ───────────────────────────────────────────────────────


class Lotto(commands.Cog):
    """Lotto‑trade tracker cog."""

    def __init__(self, bot: commands.Bot, db_path: str = DB_PATH_DEFAULT):
        self.bot = bot
        self.db = TinyDB(db_path)
        self.trades = self.db.table("trades")
        self.users = self.db.table("users")

    # ── user‑stat helper ──────────────────────────────────────────────────
    def _update_stats(self, user_id: str, pl: float, pct: float) -> None:
        User = Query()
        stats: Dict = self.users.get(User.user_id == user_id) or {"user_id": user_id}

        # ensure all keys exist
        stats.setdefault("pl", 0.0)
        stats.setdefault("pct_sum", 0.0)
        stats.setdefault("closed", 0)
        stats.setdefault("wins", 0)
        stats.setdefault("losses", 0)
        stats.setdefault("ctr", 0)

        stats["pl"] += pl
        stats["pct_sum"] += pct
        stats["closed"] += 1
        stats["wins" if pl >= 0 else "losses"] += 1
        self.users.upsert(stats, User.user_id == user_id)

    # ── ID generator per user ───────────────────────────────────────────
    def _next_id(self, user_id: str) -> str:
        User = Query()
        stats = self.users.get(User.user_id == user_id) or {"user_id": user_id, "ctr": 0}
        stats["ctr"] = stats.get("ctr", 0) + 1
        self.users.upsert(stats, User.user_id == user_id)
        return f"{stats['ctr']:03d}"

    # ─────────── commands ───────────────────────────────────────────────
    @commands.group(name="trade", invoke_without_command=True)
    async def trade_group(self, ctx: commands.Context):
        await ctx.send(
            "📜 **Trade Commands**\n"
            "‣ `!trade open <ticker> <strike><C/P> <expiry> <price> [qty]`\n"
            "   🪙 *price is per share (0.80 → $80/contract)*\n"
            "‣ `!trade close <id> <price>`  or  `!trade close <price>`\n"
            "‣ `!trade list`, `history`, `leaderboard`, `export`, `purge`, `reset`"
        )

    # ---- open -----------------------------------------------------------------
    @trade_group.command(name="open")
    async def trade_open(
        self,
        ctx: commands.Context,
        ticker: str,
        strike: str,
        expiry: str,
        entry_price: float,
        qty: int = 1,
    ):
        expiry = expiry.replace("–", "-").replace("—", "-")
        try:
            datetime.strptime(expiry, "%Y-%m-%d")
        except ValueError:
            return await ctx.send("Expiry must be YYYY‑MM‑DD.")
        if not 0 < entry_price <= 100:
            return await ctx.send("Entry price must be $0.01 – $100 per share.")
        if qty <= 0:
            return await ctx.send("Qty must be a positive integer.")

        tid = self._next_id(str(ctx.author.id))
        self.trades.insert(
            {
                "id": tid,
                "user_id": str(ctx.author.id),
                "ticker": ticker.upper(),
                "strike_type": strike.upper(),
                "expiry": expiry,
                "entry_price": entry_price,
                "qty": qty,
                "status": "open",
                "open_time": ctx.message.created_at.isoformat(),
            }
        )
        await ctx.send(
            embed=_simple_embed(
                "➕ Trade Logged",
                f"ID **{tid}** • {ticker.upper()} {strike.upper()} "
                f"@ ${entry_price:.2f} ×{qty}\n"
                f"💵 ≈ **${entry_price*100:.0f} per contract**",
                True,
            )
        )

    # ---- close ----------------------------------------------------------------
    @trade_group.command(name="close")
    async def trade_close(self, ctx: commands.Context, *args):
        if len(args) == 1:
            tid = None
            exit_price_arg = args[0]
        elif len(args) == 2:
            tid, exit_price_arg = args
        else:
            return await ctx.send("Usage: `!trade close <id> <price>` or `!trade close <price>`")

        try:
            exit_price = float(exit_price_arg)
            if exit_price <= 0:
                raise ValueError
        except ValueError:
            return await ctx.send("Exit price must be a positive number.")

        Trade = Query()
        if tid is None:
            open_trades = self.trades.search(
                (Trade.user_id == str(ctx.author.id)) & (Trade.status == "open")
            )
            if not open_trades:
                return await ctx.send("You have no open trades to close.")
            trade = open_trades[-1]
        else:
            trade = self.trades.get((Trade.id == tid) & (Trade.status == "open"))
            if not trade:
                return await ctx.send("Trade not found or already closed.")

        if trade["user_id"] != str(ctx.author.id):
            return await ctx.send("You can only close your own trades.")

        pl = (exit_price - trade["entry_price"]) * trade["qty"]
        pct = ((exit_price - trade["entry_price"]) / trade["entry_price"]) * 100
        trade.update(
            {
                "exit_price": exit_price,
                "exit_time": ctx.message.created_at.isoformat(),
                "status": "closed",
                "pl": pl,
                "pct": pct,
            }
        )
        self.trades.update(trade, doc_ids=[trade.doc_id])
        self._update_stats(trade["user_id"], pl, pct)
        await ctx.send(
            embed=_simple_embed(
                "✅ Trade Closed",
                f"ID **{trade['id']}** — ${pl:+.2f} ({pct:+.1f}%)",
                pl >= 0,
            )
        )

    # ---- list -----------------------------------------------------------------
    @trade_group.command(name="list")
    async def trade_list(self, ctx: commands.Context):
        Trade = Query()
        opens = self.trades.search(
            (Trade.user_id == str(ctx.author.id)) & (Trade.status == "open")
        )
        if not opens:
            return await ctx.send("You have no open trades.")
        desc = "\n".join(
            f"• **{t['id']}** — {t['ticker']} {t['strike_type']} @ ${t['entry_price']}"
            for t in opens
        )
        await ctx.send(embed=_simple_embed("📂 Your Open Trades", desc))

    # ---- history ----------------------------------------------------------------
    @trade_group.command(name="history")
    async def trade_history(self, ctx: commands.Context, scope: str = "me"):
        Trade = Query()
        if scope.lower() == "all":
            if not ctx.author.guild_permissions.manage_guild:
                return await ctx.send("Only mods can view the full history.")
            closed = self.trades.search(Trade.status == "closed")
            title = "🕑 All Closed Trades"
        else:
            closed = self.trades.search(
                (Trade.user_id == str(ctx.author.id)) & (Trade.status == "closed")
            )
            title = "🕑 Your Closed Trades"

        if not closed:
            return await ctx.send("No closed trades yet.")

        closed.sort(key=lambda t: t["exit_time"])
        pages = [
            "\n".join(
                f"• **{t['id']}** — {t['ticker']} {t['strike_type']} "
                f"{t['expiry']}  →  {t['pct']:+.1f}%"
                for t in closed[i : i + 15]
            )
            for i in range(0, len(closed), 15)
        ]
        await ListPaginator(pages, title).send(ctx)

    # ---- export ----------------------------------------------------------------
    @trade_group.command(name="export")
    async def trade_export(self, ctx: commands.Context):
        Trade = Query()
        trades = self.trades.search(Trade.user_id == str(ctx.author.id))
        if not trades:
            return await ctx.send("You have no trades logged yet.")

        csv_buffer = io.StringIO()
        writer = csv.DictWriter(csv_buffer, fieldnames=list(trades[0].keys()))
        writer.writeheader()
        writer.writerows(trades)
        csv_buffer.seek(0)

        await ctx.author.send(
            "📄 Here’s your CSV export.",
            file=discord.File(
                io.BytesIO(csv_buffer.getvalue().encode()), "trade_history.csv"
            ),
        )
        await ctx.reply("Check your DMs for the export 📬", mention_author=False)

    # ---- leaderboard -----------------------------------------------------------
    @trade_group.command(name="leaderboard")
    async def trade_leaderboard(self, ctx: commands.Context):
        if not self.users:
            return await ctx.send("No closed trades yet.")

        ranked = sorted(
            self.users.all(),
            key=lambda u: (
                u.get("pct_sum", 0) / max(u.get("closed", 1), 1)
            )
            if u.get("closed")
            else -9999,
            reverse=True,
        )[:10]

        lines = []
        for i, s in enumerate(ranked, 1):
            user = await self.bot.fetch_user(int(s["user_id"]))
            avg_pct = s.get("pct_sum", 0) / max(s.get("closed", 1), 1)
            lines.append(
                f"{i}. {user.mention} — {avg_pct:+.1f}% "
                f"| 💰 ${s.get('pl', 0):+,.2f} "
                f"({s.get('wins', 0)}✅/{s.get('losses', 0)}❌)"
            )

        await ctx.send(embed=_simple_embed("🏆 % Gain Leaderboard", "\n".join(lines)))

     # ---- purge (self or mods) --------------------------------------------------
    @trade_group.command(name="purge")
    async def trade_purge(self, ctx: commands.Context, *args):
        """
        • !trade purge <ID>          – delete YOUR trade
        • !trade purge @user <ID>    – mods delete another user’s trade
        """
        if not args:
            return await ctx.send(
                "Usage: !trade purge <ID>  |  !trade purge @user <ID>"
            )

        # ── caller purges own trade ───────────────────────────────────────
        if len(args) == 1:
            target_id = str(ctx.author.id)
            tid = args[0]

        # ── moderator purges another user’s trade ─────────────────────────
        elif len(args) == 2:
            if not ctx.author.guild_permissions.manage_guild:
                return await ctx.send(
                    "🚫 Only moderators can purge another user’s trade."
                )

            first, tid = args  # first = mention or ID
            try:
                member = await commands.MemberConverter().convert(ctx, first)
            except commands.BadArgument:
                return await ctx.send(
                    "First argument must be a user mention or numeric user ID."
                )

            target_id = str(member.id)

        # ── wrong arg count ───────────────────────────────────────────────
        else:
            return await ctx.send(
                "Usage: !trade purge <ID>  |  !trade purge @user <ID>"
            )

        # ── locate the trade ──────────────────────────────────────────────
        Trade = Query()
        trade = self.trades.get((Trade.user_id == target_id) & (Trade.id == tid))
        if not trade:
            return await ctx.send("❌ Trade not found for that user/ID.")

        # ── roll back stats if the trade was closed ───────────────────────
        if trade.get("status") == "closed":
            User = Query()
            stats = self.users.get(User.user_id == target_id) or {"user_id": target_id}
            for k in ("pl", "pct_sum", "closed", "wins", "losses"):
                stats.setdefault(k, 0)

            stats["pl"] -= trade.get("pl", 0.0)
            stats["pct_sum"] -= trade.get("pct", 0.0)
            stats["closed"] = max(stats["closed"] - 1, 0)

            if trade["pl"] >= 0:
                stats["wins"] = max(stats["wins"] - 1, 0)
            else:
                stats["losses"] = max(stats["losses"] - 1, 0)

            self.users.upsert(stats, User.user_id == target_id)

        # ── delete the trade row ──────────────────────────────────────────
        self.trades.remove((Trade.user_id == target_id) & (Trade.id == tid))

        owner = await self.bot.fetch_user(int(target_id))
        await ctx.send(
            embed=_simple_embed(
                "🗑️ Trade Purged",
                f"ID **{tid}** from {owner.mention} removed.",
                True,
            )
        )

    # ---- reset (mods) ---------------------------------------------------------
    @trade_group.command(name="reset")
    @commands.has_permissions(manage_guild=True)
    async def trade_reset(self, ctx: commands.Context):
        """Delete ALL trades & stats (testing)."""
        msg = await ctx.send(
            "⚠️ This will DELETE **all** trades & stats.\n"
            "Type `confirm` within 15 s to proceed."
        )

        def check(m: discord.Message):
            return (
                m.author == ctx.author
                and m.channel == ctx.channel
                and m.content.lower() == "confirm"
            )

        try:
            await self.bot.wait_for("message", timeout=15, check=check)
        except asyncio.TimeoutError:
            return await msg.edit(content="Reset cancelled (timeout).")

        self.trades.truncate()
        self.users.truncate()
        await msg.edit(content="🧨 All trades & stats wiped. Fresh start!")

# ────────── extension entry point ───────────────────────────────────────────


async def setup(bot: commands.Bot):
    """discord.py loads this cog via `await bot.load_extension()`."""
    await bot.add_cog(Lotto(bot))
