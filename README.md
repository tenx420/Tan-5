# Multi-Purpose Discord Bot

This Discord bot integrates multiple APIs to provide a range of features including:
- **News Summaries:** Fetches and summarizes news articles via NewsAPI and OpenAI.
- **Web Scraping:** Scrapes and summarizes webpage content.
- **Stock Prices:** Retrieves real-time stock data using yfinance.
- **Google Search:** Uses SerpAPI to perform Google searches.
- **Interactive GPT Chat:** Replies with witty, GPT-based responses when mentioned.

## Features

- **!news [topic]:**  
  Fetches news articles on a given topic from NewsAPI and generates a witty summary using OpenAI's ChatCompletion.

- **!scrape <url>:**  
  Scrapes a webpage, extracts key content, and provides a concise, witty summary.

- **!stock <symbol>:**  
  Retrieves the current stock price for a given symbol (e.g., AAPL) using yfinance.

- **!google <query>:**  
  Performs a Google search using SerpAPI and displays the top results.

- **Mention-Based GPT Chat:**  
  When the bot is mentioned (e.g., `@BotName Hello`), it responds with a witty, GPT-generated reply.

## Prerequisites

- **Python 3.8+**
- **Discord Bot Token:** Obtain from the [Discord Developer Portal](https://discord.com/developers/applications).
- **API Keys:**
  - [NewsAPI](https://newsapi.org/)
  - [OpenAI](https://platform.openai.com/)
  - [SerpAPI](https://serpapi.com/)
- **Required Python Libraries:**
  - `discord.py`
  - `requests`
  - `openai`
  - `beautifulsoup4`
  - `yfinance`
  - `google-search-results` (for SerpAPI)

## Installation

1. **Clone the Repository:**
   ```bash
   git clone <repository-url>
   cd <repository-directory>
