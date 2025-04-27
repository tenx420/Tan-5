# lotto_tracker.py – complete, patched version
# ---------------------------------------------------------------------------
# Commands
#   • !trade open       <ticker> <strike><C/P> <expiry YYYY-MM-DD> <entryPrice> [qty]
#   • !trade edit       <id> <field> <newValue>
#   • !trade close      <id> <exitPrice>  |  !trade close <exitPrice>
#   • !trade list
#   • !trade history    [all]
#   • !trade leaderboard
#   • !trade export
#   • !trade purge      ...
#   • !trade reset
#
# Storage: TinyDB mirrored to Postgres via PostgresBackedStorage
# ---------------------------------------------------------------------------

import asyncio
import csv
import io
import os
from datetime import datetime, date, timedelta, time as dtime

import discord
from discord import Embed, Colour, ui, Interaction
from discord.ext import commands, tasks
from tinydb import TinyDB, Query
import json, pg_storage
from storage_postgres import PostgresBackedStorage

DB_PATH_DEFAULT = os.getenv("LOTTO_DB_PATH", "trades.json")
LOG_CHANNEL_ID  = int(os.getenv("LOTTO_LOG_CHANNEL_ID", "0"))   # 0 → disable

# ────────── helpers ────────────────────────────────────────────────────────

def _simple_embed(title: str, desc: str, success: bool | None = None) -> Embed:
    color = Colour.green() if success else Colour.red() if success is not None else Colour.blue()
    return Embed(title=title, description=desc, color=color)


class ListPaginator(ui.View):
    def __init__(self, pages, title):
        super().__init__(timeout=180)
        self.pages, self.title, self.page = pages, title, 0
        self.prev_button.disabled = True
        if len(pages) == 1:
            self.next_button.disabled = True

    async def send(self, target):
        embed = _simple_embed(self.title, self.pages[self.page])
        if hasattr(target, "send"):
            await target.send(embed=embed, view=self)
        else:
            await target.response.send_message(embed=embed, view=self, ephemeral=True)

    @ui.button(label="« Prev", style=discord.ButtonStyle.grey)
    async def prev_button(self, interaction, _):
        self.page -= 1
        self.prev_button.disabled = self.page == 0
        self.next_button.disabled = False
        await self._update(interaction)

    @ui.button(label="Next »", style=discord.ButtonStyle.grey)
    async def next_button(self, interaction, _):
        self.page += 1
        self.next_button.disabled = self.page == len(self.pages) - 1
        self.prev_button.disabled = False
        await self._update(interaction)

    async def _update(self, interaction):
        embed = _simple_embed(self.title, self.pages[self.page])
        await interaction.response.edit_message(embed=embed, view=self)

# ────────── main Cog ───────────────────────────────────────────────────────

class Lotto(commands.Cog):
    """Lotto-trade tracker cog."""

    def __init__(self, bot: commands.Bot, db_path: str = DB_PATH_DEFAULT):
        self.bot = bot

        # 1️⃣  pull last-saved JSON blob from Postgres
        initial = pg_storage.load_db_json()
        with open("trades.json", "w") as f:
            f.write(json.dumps(initial))

        # 2️⃣  open TinyDB using Postgres-mirrored storage
        self.db     = TinyDB("trades.json", storage=PostgresBackedStorage)
        self.trades = self.db.table("trades")
        self.users  = self.db.table("users")

        # start auto-expiry loop
        self._expire_trades.start()

    # ── user-stat helper ──────────────────────────────────────────────────
    def _update_stats(self, user_id: str, pl: float, pct: float) -> None:
        User = Query()
        s = self.users.get(User.user_id == user_id) or {"user_id": user_id}
        s.setdefault("pl", 0.0)
        s.setdefault("pct_sum", 0.0)
        s.setdefault("closed", 0)
        s.setdefault("wins", 0)
        s.setdefault("losses", 0)
        s.setdefault("ctr", 0)
        s["pl"]      += pl
        s["pct_sum"] += pct
        s["closed"]  += 1
        s["wins" if pl >= 0 else "losses"] += 1
        self.users.upsert(s, User.user_id == user_id)

    # ── ID generator per user ───────────────────────────────────────────
    def _next_id(self, user_id: str) -> str:
        User = Query()
        stats = self.users.get(User.user_id == user_id) or {"user_id": user_id, "ctr": 0}
        stats["ctr"] = stats.get("ctr", 0) + 1
        self.users.upsert(stats, User.user_id == user_id)
        return f"{user_id}-{stats['ctr']:03d}"

    # ─────────── commands ───────────────────────────────────────────────
    @commands.group(name="trade", invoke_without_command=True)
    async def trade_group(self, ctx):
        await ctx.send(
            "📜 **Trade Commands**\n"
            "‣ `!trade open <ticker> <strike><C/P> <expiry> <price> [qty]`\n"
            "‣ `!trade edit <id> <field> <value>`  (open trades)\n"
            "‣ `!trade close <id> <price>`  or  `!trade close <price>`\n"
            "‣ `!trade list`, `history`, `leaderboard`, `export`, `purge`, `reset`"
        )

    # ---- open -----------------------------------------------------------------
    @trade_group.command(name="open")
    async def trade_open(self, ctx, ticker, strike, expiry, entry_price: float, qty: int = 1):
        expiry = expiry.replace("–", "-").replace("—", "-")
        try:
            datetime.strptime(expiry, "%Y-%m-%d")
        except ValueError:
            return await ctx.send("Expiry must be YYYY-MM-DD.")
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

        # ---- edit -----------------------------------------------------------------
    @trade_group.command(name="edit")
    async def trade_edit(self, ctx, tid: str, field: str, *, new_value: str):
        # 1️⃣  normalise fancy Unicode dashes to ASCII hyphen
        tid = tid.replace("–", "-").replace("—", "-")

        Trade = Query()

        # first try an exact-match lookup on the full ID
        trade = self.trades.get(
            (Trade.user_id == str(ctx.author.id))
            & (Trade.id == tid)
            & (Trade.status == "open")
        )

        # 2️⃣  allow the user to pass just the 3-digit tail, e.g. “006”
        if trade is None and len(tid) == 3:
            trade = self.trades.get(
                (Trade.user_id == str(ctx.author.id))
                & (Trade.id.test(lambda x: x.endswith(f"-{tid}")))
                & (Trade.status == "open")
            )

        if trade is None:
            return await ctx.send("Trade not found or already closed.")

        # block edits on/after expiry
        if date.fromisoformat(trade["expiry"]) <= date.today():
            return await ctx.send("Cannot edit – trade already at/after expiry.")

        field = field.lower()
        if field not in {"entry_price", "qty", "strike_type", "expiry"}:
            return await ctx.send(
                "You can only edit: entry_price, qty, strike_type, expiry."
            )

        # --- validate & cast ----------------------------------------------------
        try:
            if field == "entry_price":
                val = float(new_value)
                if not 0 < val <= 100:
                    raise ValueError
            elif field == "qty":
                val = int(new_value)
                if val <= 0:
                    raise ValueError
            elif field == "expiry":
                datetime.strptime(new_value, "%Y-%m-%d")  # validates format
                val = new_value
            else:  # strike_type
                val = new_value.upper()
        except ValueError:
            return await ctx.send(f"Invalid value for **{field}**.")

        # --- save ----------------------------------------------------------------
        trade[field] = val
        self.trades.update(trade, doc_ids=[trade.doc_id])
        await ctx.send(f"✏️  **{field}** updated to `{val}` for trade **{trade['id']}**.")


    # ---- close ----------------------------------------------------------------
    @trade_group.command(name="close")
    async def trade_close(self, ctx, *args):
        """
        Close an open trade.

        • !trade close <EXIT>                 – closes your most-recent open trade
        • !trade close <ID/tail> <EXIT>       – closes the specified trade
        """
        # ── parse args ──────────────────────────────────────────────────────
        if len(args) == 1:                              # no ID given
            tid, exit_price_arg = None, args[0]
        elif len(args) == 2:                            # ID + price
            tid, exit_price_arg = args
        else:
            return await ctx.send(
                "Usage: `!trade close <price>`  or  `!trade close <id> <price>`"
            )

        # price validation
        try:
            exit_price = float(exit_price_arg)
            if exit_price <= 0:
                raise ValueError
        except ValueError:
            return await ctx.send("Exit price must be a positive number.")

        Trade = Query()

        # ── 1) choose which trade to close ─────────────────────────────────
        if tid is None:                                 # latest open
            open_trades = self.trades.search(
                (Trade.user_id == str(ctx.author.id)) & (Trade.status == "open")
            )
            if not open_trades:
                return await ctx.send("You have no open trades to close.")
            trade = open_trades[-1]

        else:                                           # specific ID
            tid = tid.replace("–", "-").replace("—", "-")
            # exact match first
            trade = self.trades.get(
                (Trade.user_id == str(ctx.author.id))
                & (Trade.id == tid)
                & (Trade.status == "open")
            )
            # 3-digit tail fallback
            if trade is None and len(tid) == 3:
                trade = self.trades.get(
                    (Trade.user_id == str(ctx.author.id))
                    & (Trade.id.test(lambda x: x.endswith(f"-{tid}")))
                    & (Trade.status == "open")
                )

            if trade is None:
                return await ctx.send("Trade not found or already closed.")

        # ── 2) calculate P/L and close it ──────────────────────────────────
        pl  = (exit_price - trade["entry_price"]) * trade["qty"]
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

        # update user stats
        self._update_stats(trade["user_id"], pl, pct)

        # ── 3) confirmation embed ──────────────────────────────────────────
        await ctx.send(
            embed=_simple_embed(
                "✅ Trade Closed",
                f"ID **{trade['id']}** — ${pl*100:+.2f} ({pct:+.1f}%)",
                pl >= 0,
            )
        )


    # ---- list -----------------------------------------------------------------
    @trade_group.command(name="list")
    async def trade_list(self, ctx):
        Trade = Query()
        opens = self.trades.search(
            (Trade.user_id == str(ctx.author.id)) & (Trade.status == "open")
        )
        if not opens:
            return await ctx.send("You have no open trades.")
        desc = "\n".join(
            f"• **{t['id'].split('-')[-1]}** — {t['ticker']} {t['strike_type']} @ ${t['entry_price']}"
            for t in opens
        )
        await ctx.send(embed=_simple_embed("📂 Your Open Trades", desc))
    
    # ---- paper-hands tag -----------------------------------------------------
    @trade_group.command(name="paper")
    async def trade_paper(self, ctx, *args):
        """
        Toggle 📄🤚 on a CLOSED trade.
        • !trade paper <ID> [off]          – your own
        • !trade paper @user <ID> [off]    – mods on anyone
        """
        # --- parse target --------------------------------------------------
        if len(args) in (1, 2):  # self
            target_id, tid, turn_off = str(ctx.author.id), args[0], len(args) == 2
        elif len(args) in (2, 3):  # mod
            if not ctx.author.guild_permissions.manage_guild:
                return await ctx.send("🚫 Only mods can tag another user.")
            member_arg, tid, *rest = args
            try:
                member = await commands.MemberConverter().convert(ctx, member_arg)
            except commands.BadArgument:
                return await ctx.send("First arg must be a mention or user ID.")
            target_id, turn_off = str(member.id), len(rest) == 1
        else:
            return await ctx.send("Usage: !trade paper [@user] <ID> [off]")

        tid = tid.replace("–", "-").replace("—", "-")
        Trade = Query()

        # exact then 3-digit tail lookup (closed only)
        row = self.trades.get(
            (Trade.user_id == target_id) & (Trade.id == tid) & (Trade.status == "closed")
        )
        if row is None and len(tid) == 3:
            row = self.trades.get(
                (Trade.user_id == target_id)
                & (Trade.id.test(lambda x: x.endswith(f"-{tid}")))
                & (Trade.status == "closed")
            )
        if row is None:
            return await ctx.send("Closed trade not found.")

        row["paper"] = not turn_off
        self.trades.update(row, doc_ids=[row.doc_id])
        tag_msg = "removed" if turn_off else "added"
        await ctx.send(f"📄🤚 tag {tag_msg} for trade **{row['id']}**.")

       # ---- history -------------------------------------------------------------
    @trade_group.command(name="history")
    async def trade_history(self, ctx, scope: str = "me"):
        """
        Show closed trades.

        ▸ !trade history                – your trades
        ▸ !trade history all            – everyone (mods only)
        ▸ !trade history @user          – specific user
        """
        Trade = Query()

        # 1️⃣  whose rows?
        if scope.lower() == "all":
            if not ctx.author.guild_permissions.manage_guild:
                return await ctx.send("Only moderators can view all history.")
            closed = self.trades.search(Trade.status == "closed")
            title  = "🕑  All Closed Trades"
        else:
            if scope.startswith("<@") and scope.endswith(">"):
                uid = scope.strip("<@!>")
            else:
                uid = str(ctx.author.id)
            closed = self.trades.search(
                (Trade.user_id == uid) & (Trade.status == "closed")
            )
            who   = "Your" if uid == str(ctx.author.id) else f"<@{uid}>'s"
            title = f"🕑  {who} Closed Trades"

        if not closed:
            return await ctx.send("No closed trades found.")

        # 2️⃣  newest → oldest
        closed.sort(key=lambda t: t["exit_time"], reverse=True)

        # 3️⃣  paginate 15 per page
        pages = [
            "\n".join(
                f"• **{t['id'].split('-')[-1]}**"
                f"{' 📄🤚' if t.get('paper') else ''} — "
                f"{t['ticker']} {t['strike_type']} {t['expiry']}  →  "
                f"{t['pct']:+.1f}%"
                for t in closed[i : i + 15]
            )
            for i in range(0, len(closed), 15)
        ]

        await ListPaginator(pages, title).send(ctx)


    # ---- export ----------------------------------------------------------------
    @trade_group.command(name="export")
    async def trade_export(self, ctx):
        Trade = Query()
        trades = self.trades.search(Trade.user_id == str(ctx.author.id))
        if not trades:
            return await ctx.send("You have no trades logged yet.")

        buf = io.StringIO()
        writer = csv.DictWriter(buf, fieldnames=list(trades[0].keys()))
        writer.writeheader()
        writer.writerows(trades)
        buf.seek(0)

        await ctx.author.send(
            "📄 Here’s your CSV export.",
            file=discord.File(io.BytesIO(buf.getvalue().encode()), "trade_history.csv"),
        )
        await ctx.reply("Check your DMs for the export 📬", mention_author=False)

    # ---- leaderboard -----------------------------------------------------------
    @trade_group.command(name="leaderboard")
    async def trade_leaderboard(self, ctx):
        if not self.users:
            return await ctx.send("No closed trades yet.")

        ranked = sorted(
            self.users.all(),
            key=lambda u: (u.get("pct_sum", 0) / max(u.get("closed", 1), 1)),
            reverse=True,
        )[:10]

        lines = []
        for i, s in enumerate(ranked, 1):
            user      = await self.bot.fetch_user(int(s["user_id"]))
            closed    = max(s.get("closed", 0), 1)
            avg_pct   = s.get("pct_sum", 0) / closed
            wins     = s.get("wins", 0)
            losses   = s.get("losses", 0)
            win_rate  = (wins / closed) * 100
            profit    = s.get("pl", 0) * 100
            lines.append(
                f"{i}. {user.mention} — {avg_pct:+.1f}% | 💰${profit:+,.0f} "
                f"| 🎯{win_rate:.0f}% ({wins}✅/{losses}❌)"
            )

        await ctx.send(embed=_simple_embed("🏆 Leaderboard (avg% | P/L | win-rate)", "\n".join(lines)))

        # ---- purge ---------------------------------------------------------------
    @trade_group.command(name="purge")
    async def trade_purge(self, ctx, *args):
        """
        Delete a trade row.
          • !trade purge <ID>          – delete YOUR trade
          • !trade purge @user <ID>    – mods delete another user’s trade
        """
        # ── parse args ───────────────────────────────────────────────
        if len(args) == 1:                  # self-purge
            target_id, tid = str(ctx.author.id), args[0]
        elif len(args) == 2:                # mod purge
            if not ctx.author.guild_permissions.manage_guild:
                return await ctx.send("🚫 Only moderators can purge another user’s trade.")
            member_arg, tid = args
            try:
                member = await commands.MemberConverter().convert(ctx, member_arg)
            except commands.BadArgument:
                return await ctx.send("First arg must be a mention or numeric user ID.")
            target_id = str(member.id)
        else:
            return await ctx.send("Usage: !trade purge <ID>  |  !trade purge @user <ID>")

        tid = tid.replace("–", "-").replace("—", "-")
        Trade = Query()

        # exact match then 3-digit tail fallback
        row = self.trades.get((Trade.user_id == target_id) & (Trade.id == tid))
        if row is None and len(tid) == 3:
            row = self.trades.get(
                (Trade.user_id == target_id)
                & (Trade.id.test(lambda x: x.endswith(f"-{tid}")))
            )
        if row is None:
            return await ctx.send("Trade not found.")

        # roll back stats if closed
        if row.get("status") == "closed":
            User = Query()
            s = self.users.get(User.user_id == target_id) or {"user_id": target_id}
            for k in ("pl", "pct_sum", "closed", "wins", "losses"):
                s[k] = s.get(k, 0)
            s["pl"]      -= row.get("pl", 0)
            s["pct_sum"] -= row.get("pct", 0)
            s["closed"]   = max(s["closed"] - 1, 0)
            if row.get("pl", 0) >= 0:
                s["wins"]  = max(s["wins"]  - 1, 0)
            else:
                s["losses"]= max(s["losses"]- 1, 0)
            self.users.upsert(s, User.user_id == target_id)

        self.trades.remove(doc_ids=[row.doc_id])
        owner = await self.bot.fetch_user(int(target_id))
        await ctx.send(
            embed=_simple_embed(
                "🗑️  Trade Purged",
                f"ID **{row['id']}** from {owner.mention} removed.",
                True,
            )
        )

    # ---- reset (mods) ---------------------------------------------------------
    @trade_group.command(name="reset")
    @commands.has_permissions(manage_guild=True)
    async def trade_reset(self, ctx):
        """Delete ALL trades & stats.  Use for a fresh start / testing."""
        msg = await ctx.send(
            "⚠️  This will DELETE **all** trades & stats.\n"
            "Type `confirm` within 15 s to proceed."
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
        await msg.edit(content="🧨 All trades & stats wiped. Fresh slate!")


    # ────────── background expiry checker ─────────────────────────────────
    @tasks.loop(time=dtime(hour=0, minute=5))   # runs daily at 00:05 UTC
    async def _expire_trades(self):
        today = date.today()
        Trade = Query()
        due = self.trades.search(
            (Trade.status == "open") & (Trade.expiry.test(lambda d: date.fromisoformat(d) < today))
        )
        if not due:
            return

        for t in due:
            t.update(
                {
                    "exit_price": 0.0,
                    "exit_time": discord.utils.utcnow().isoformat(),
                    "status": "closed",
                    "pl": -t["entry_price"] * t["qty"],
                    "pct": -100.0,
                }
            )
            self.trades.update(t, doc_ids=[t.doc_id])
            self._update_stats(t["user_id"], t["pl"], t["pct"])

        if LOG_CHANNEL_ID:
            ch = self.bot.get_channel(LOG_CHANNEL_ID)
            if ch:
                await ch.send(f"🕛 Auto-closed {len(due)} expired trades.")

    @_expire_trades.before_loop
    async def _wait_for_ready(self):
        await self.bot.wait_until_ready()

# ────────── extension entry point ───────────────────────────────────────────

async def setup(bot: commands.Bot):
    await bot.add_cog(Lotto(bot))

