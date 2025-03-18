import os
import logging
import random
import asyncio
import requests
from bs4 import BeautifulSoup
from discord.ext import commands, tasks
import discord

# Configure logging
logging.basicConfig(level=logging.INFO,
                    format='%(asctime)s:%(levelname)s:%(name)s: %(message)s')
logger = logging.getLogger(__name__)

# Set up Discord bot intents and command prefix
intents = discord.Intents.default()
intents.messages = True
intents.message_content = True  # Required for reading message content

discord = commands.Bot(command_prefix="!", intents=intents)

# Global variable to store fetched news headlines
news_headlines = []


def fetch_news_headlines() -> list:
    """
    Fetches news headlines from Hacker News.
    Returns a list of headlines or an empty list if fetching fails.
    """
    url = "https://news.ycombinator.com"
    try:
        response = requests.get(url, timeout=10)
        response.raise_for_status()
    except requests.RequestException as e:
        logger.error(f"Error fetching news from {url}: {e}")
        return []

    soup = BeautifulSoup(response.text, "html.parser")
    headlines = []
    # Hacker News headlines are in <a> elements with class "storylink"
    for a in soup.find_all("a", class_="storylink"):
        headline = a.get_text(strip=True)
        if headline:
            headlines.append(headline)

    if not headlines:
        logger.warning("No headlines were found on the page.")
    else:
        logger.info(f"Fetched {len(headlines)} headlines.")
    return headlines


@tasks.loop(minutes=10)
async def update_news():
    """
    Background task that updates the global news_headlines list every 10 minutes.
    """
    global news_headlines
    logger.info("Starting news update task...")
    headlines = await asyncio.to_thread(fetch_news_headlines)
    if headlines:
        news_headlines = headlines
        logger.info("News headlines updated successfully.")
    else:
        logger.warning("Failed to update news headlines.")


@discord.event
async def on_ready():
    """
    Event triggered when the bot is ready.
    """
    logger.info(f"Logged in as {discord.user} (ID: {discord.user.id})")
    update_news.start()
    logger.info("News update background task started.")


@discord.event
async def on_message(message):
    """
    Event triggered for every message.
    Checks for bot mentions and responds with a sarcastic message.
    """
    # Ignore messages from the bot itself
    if message.author == discord.user:
        return

    # Check if the bot is mentioned in the message
    if discord.user in message.mentions:
        response = generate_sarcastic_response()
        try:
            await message.channel.send(response)
        except Exception as e:
            logger.error(f"Failed to send message: {e}")

    # Allow commands (e.g., !refreshnews) to be processed as well
    await discord.process_commands(message)


def generate_sarcastic_response() -> str:
    """
    Returns a funny and sarcastic response, optionally including a news headline.
    """
    sarcastic_comments = [
        "Oh, you summoned me? I hope you're ready for some top-notch news and sarcasm.",
        "Really? Another ping? I'm blushing—if bots could blush.",
        "At your service, because apparently you can't live without my witty insights.",
        "Alert the media—I'm here, and I bring sarcasm and headlines!",
        "I'm here to save you from boredom. Look, here's a headline for you:"
    ]

    comment = random.choice(sarcastic_comments)
    news_line = ""
    if news_headlines:
        news_headline = random.choice(news_headlines)
        news_line = f" Also, check this out: '{news_headline}'."
    return comment + news_line


@discord.command(name="refreshnews")
async def refresh_news_command(ctx):
    """
    A command to manually refresh the news headlines.
    Usage: !refreshnews
    """
    await ctx.send("Refreshing news headlines...")
    headlines = await asyncio.to_thread(fetch_news_headlines)
    if headlines:
        global news_headlines
        news_headlines = headlines
        await ctx.send(f"Updated news with {len(headlines)} headlines.")
    else:
        await ctx.send("Failed to fetch news headlines. Please try again later.")


def main():
    TOKEN = ""
    if not TOKEN:
        logger.error("DISCORD_BOT_TOKEN environment variable not set. Exiting.")
        return
    try:
        discord.run(TOKEN)
    except Exception as e:
        logger.error(f"Error running the bot: {e}")


if __name__ == "__main__":
    main()
