import os
import logging
import asyncio
import requests
import openai
import discord
from discord.ext import commands
from bs4 import BeautifulSoup
import yfinance as yf
from serpapi import GoogleSearch

# ---------------------------------------------------------------------------
# 1. Configuration & Setup
# ---------------------------------------------------------------------------
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s:%(levelname)s:%(name)s: %(message)s'
)
logger = logging.getLogger(__name__)

# Load keys from environment variables or hardcoded (not recommended)
DISCORD_BOT_TOKEN = "YOUR_DISCORD_BOT_TOKEN_HERE"
NEWSAPI_KEY = "YOUR_NEWSAPI_KEY_HERE"
OPENAI_API_KEY = "YOUR_OPENAI_API_KEY_HERE"
SERPAPI_KEY = "YOUR_SERPAPI_KEY_HERE"

# Check that all keys are set
if not DISCORD_BOT_TOKEN:
    logger.error("DISCORD_BOT_TOKEN not set. Exiting.")
    exit(1)
if not NEWSAPI_KEY:
    logger.error("NEWSAPI_KEY not set. Exiting.")
    exit(1)
if not OPENAI_API_KEY:
    logger.error("OPENAI_API_KEY not set. Exiting.")
    exit(1)
if not SERPAPI_KEY:
    logger.error("SERPAPI_KEY not set. Exiting.")
    exit(1)

openai.api_key = OPENAI_API_KEY

# Configure Discord Intents
intents = discord.Intents.default()
intents.message_content = True  # Needed to read messages
bot = commands.Bot(command_prefix="!", intents=intents)

# ---------------------------------------------------------------------------
# 2. NewsAPI: Fetch Articles by Keyword
# ---------------------------------------------------------------------------
def fetch_news_articles(query: str, max_articles: int = 5):
    url = "https://newsapi.org/v2/everything"
    params = {
        "q": query,
        "language": "en",
        "sortBy": "publishedAt",
        "pageSize": max_articles,
        "apiKey": NEWSAPI_KEY,
    }
    try:
        response = requests.get(url, params=params, timeout=10)
        response.raise_for_status()
        data = response.json()
        if data.get("status") != "ok":
            logger.warning(f"NewsAPI error response: {data}")
            return []
        articles = data.get("articles", [])
        results = []
        for article in articles:
            title = article.get("title", "No Title")
            link = article.get("url", "")
            results.append({"title": title, "url": link})
        logger.info(f"Fetched {len(results)} articles for query '{query}'.")
        return results
    except Exception as e:
        logger.error(f"Error fetching news articles: {e}")
        return []

# ---------------------------------------------------------------------------
# 3. OpenAI: Generate a News Summary
# ---------------------------------------------------------------------------
def generate_news_summary(articles: list, style="witty and concise") -> str:
    if not articles:
        return "No articles found for the given topic."
    prompt = "You are a news summarizer. Summarize the following articles in a " \
             f"{style} manner:\n\n"
    for idx, article in enumerate(articles, start=1):
        prompt += f"{idx}. {article['title']} (Link: {article['url']})\n"
    prompt += "\nProvide a concise summary."

    try:
        response = openai.ChatCompletion.create(
            model="gpt-3.5-turbo",
            messages=[
                {"role": "system", "content": "You are a helpful news summarizer."},
                {"role": "user", "content": prompt},
            ],
            temperature=0.7,
            max_tokens=200,
        )
        summary = response.choices[0].message["content"].strip()
        return summary
    except Exception as e:
        logger.error(f"OpenAI API error: {e}")
        return "Error generating news summary."

# ---------------------------------------------------------------------------
# 4. Web Scraping & Summarization Command
# ---------------------------------------------------------------------------
@bot.command(name="scrape")
async def scrape_command(ctx, url: str):
    await ctx.send("Scraping the webpage... please wait.")
    if not url.startswith("http"):
        await ctx.send("Please provide a valid URL starting with http:// or https://")
        return
    try:
        headers = {"User-Agent": "Mozilla/5.0"}
        response = requests.get(url, timeout=10, headers=headers)
        response.raise_for_status()
    except Exception as e:
        logger.error(f"Error fetching URL {url}: {e}")
        await ctx.send("Failed to fetch the webpage. Please check the URL and try again.")
        return

    soup = BeautifulSoup(response.text, "html.parser")
    title = soup.title.string.strip() if soup.title and soup.title.string else "No title found"
    paragraphs = soup.find_all("p")
    text_content = "\n".join(p.get_text().strip() for p in paragraphs[:5])
    if not text_content:
        text_content = "No textual content could be extracted from the page."

    prompt = (
        "Summarize the following webpage content in a concise, witty manner:\n\n"
        f"Title: {title}\n\nContent:\n{text_content}\n\nSummary:"
    )

    try:
        openai_response = openai.ChatCompletion.create(
            model="gpt-3.5-turbo",
            messages=[
                {"role": "system", "content": "You are a helpful summarizer."},
                {"role": "user", "content": prompt},
            ],
            temperature=0.7,
            max_tokens=200,
        )
        summary = openai_response.choices[0].message["content"].strip()
        await ctx.send(summary)
    except Exception as e:
        logger.error(f"OpenAI API error while summarizing scraped content: {e}")
        await ctx.send("Error generating summary using OpenAI.")

# ---------------------------------------------------------------------------
# 5. Stock Price Command Using yfinance
# ---------------------------------------------------------------------------
@bot.command(name="stock")
async def stock_command(ctx, symbol: str):
    await ctx.send(f"Fetching stock data for {symbol.upper()}...")
    try:
        ticker = yf.Ticker(symbol)
        data = ticker.history(period="1d")
        if data.empty:
            await ctx.send(f"Could not fetch data for {symbol.upper()}.")
            return
        current_price = data['Close'].iloc[-1]
        await ctx.send(f"The current price of {symbol.upper()} is ${current_price:.2f}.")
    except Exception as e:
        logger.error(f"Error fetching stock data: {e}")
        await ctx.send("Error fetching stock data.")

# ---------------------------------------------------------------------------
# 6. Google Search Command Using SerpAPI
# ---------------------------------------------------------------------------
def google_search(query: str, num_results: int = 5):
    params = {
        "engine": "google",
        "q": query,
        "num": num_results,
        "api_key": SERPAPI_KEY,
    }
    search = GoogleSearch(params)
    results = search.get_dict()
    organic_results = results.get("organic_results", [])
    return organic_results

@bot.command(name="google")
async def google_command(ctx, *, query: str):
    await ctx.send(f"Searching Google for '{query}'...")
    try:
        results = await asyncio.to_thread(google_search, query)
        if not results:
            await ctx.send("No results found.")
            return
        message = "Top Google results:\n"
        for result in results[:3]:
            title = result.get("title", "No Title")
            link = result.get("link", "")
            snippet = result.get("snippet", "")
            message += f"**{title}**\n{snippet}\n{link}\n\n"
        await ctx.send(message)
    except Exception as e:
        logger.error(f"Error performing Google search: {e}")
        await ctx.send("Error performing Google search.")

# ---------------------------------------------------------------------------
# 7. News Command Using NewsAPI & OpenAI
# ---------------------------------------------------------------------------
@bot.command(name="news")
async def news_command(ctx, *, topic: str = "latest"):
    await ctx.send(f"Fetching news for **{topic}**...")
    articles = await asyncio.to_thread(fetch_news_articles, topic)
    if not articles:
        await ctx.send("Sorry, I couldn't fetch any news articles at the moment.")
        return
    summary = await asyncio.to_thread(generate_news_summary, articles)
    await ctx.send(summary)

# ---------------------------------------------------------------------------
# 8. Respond to Mentions with GPT-based Witty Chat
# ---------------------------------------------------------------------------
@bot.event
async def on_message(message):
    # Avoid responding to the bot's own messages
    if message.author == bot.user:
        return

    # If the bot is mentioned (e.g., @BotName Hello)
    if bot.user in message.mentions:
        # Extract the text after the mention
        mention_str = f"<@{bot.user.id}>"
        user_input = message.content.replace(mention_str, "").strip()
        if not user_input:
            user_input = "Hello!"

        try:
            response = openai.ChatCompletion.create(
                model="gpt-3.5-turbo",
                messages=[
                    {
                        "role": "system",
                        "content": (
                            "You are a witty, sarcastic, and entertaining assistant, but also helpful. "
                            "Always respond with clever banter and humor, while providing useful info."
                        )
                    },
                    {"role": "user", "content": user_input}
                ],
                temperature=0.8,
                max_tokens=200
            )
            bot_reply = response.choices[0].message["content"].strip()
            await message.channel.send(bot_reply)
        except Exception as e:
            logger.error(f"OpenAI API error: {e}")
            await message.channel.send("Oops, something went wrong with GPT!")

    # Ensure other commands (e.g., !news, !stock) are still processed
    await bot.process_commands(message)

# ---------------------------------------------------------------------------
# 9. Bot Startup
# ---------------------------------------------------------------------------
@bot.event
async def on_ready():
    logger.info(f"Logged in as {bot.user} (ID: {bot.user.id})")

def main():
    try:
        bot.run(DISCORD_BOT_TOKEN)
    except Exception as e:
        logger.error(f"Error running the bot: {e}")

if __name__ == "__main__":
    main()
