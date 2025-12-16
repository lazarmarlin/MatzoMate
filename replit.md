# Product Ingredient Finder

## Overview
A Python application for finding product ingredients using barcode/UPC lookups. It searches multiple sources including OpenFoodFacts API and Amazon product pages.

## Project Structure
- `main.py` - Main entry point, handles barcode lookup via OpenFoodFacts API
- `aisearch.py` - OpenAI integration for AI-powered ingredient search
- `amazonsearch.py` - Selenium-based Amazon product scraper for ingredients
- `amazonsearch2.py` - Alternative Amazon scraper implementation
- `internetsearch.py` - DuckDuckGo search to find Amazon product links
- `offsearch.py` - OpenFoodFacts search by product name

## Dependencies
- Python 3.11
- openfoodfacts - OpenFoodFacts API client
- openai - OpenAI API for AI search
- selenium/selenium-stealth - Web scraping
- ddgs - DuckDuckGo search
- requests - HTTP requests
- fake-useragent - User agent rotation

## Running the Application
```bash
python main.py
```

The application currently uses a hardcoded barcode for testing. Modify the `input` variable in `main.py` to search for different products.

## Configuration
- OpenAI features require an `OPENAI_API_KEY` environment variable
- Amazon scraping uses Selenium with Chrome in headless mode
