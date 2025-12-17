# Product Ingredient Finder - SMS Service

## Overview
A Python Flask application that receives barcode lookups via SMS and responds with ingredient information and kosher-for-Passover status.

## How It Works
1. User sends a barcode number via SMS to the Twilio phone number
2. Server looks up the product in OpenFoodFacts database
3. Checks ingredients against non-kosher-for-Passover list
4. Sends back product name and kosher status via SMS

## Project Structure
- `main.py` - Flask web server with Twilio SMS webhook handler
- `aisearch.py` - OpenAI integration for AI-powered ingredient search
- `amazonsearch.py` - Selenium-based Amazon product scraper
- `amazonsearch2.py` - Alternative Amazon scraper implementation
- `internetsearch.py` - DuckDuckGo search for Amazon product links
- `offsearch.py` - OpenFoodFacts search by product name

## Dependencies
- Python 3.11
- Flask - Web framework
- Twilio - SMS integration
- openfoodfacts - Product database API
- openai - AI search (optional)

## Environment Variables (Secrets)
- `TWILIO_ACCOUNT_SID` - Twilio account identifier
- `TWILIO_AUTH_TOKEN` - Twilio authentication token
- `TWILIO_PHONE_NUMBER` - Twilio phone number for SMS

## Twilio Webhook Setup
After deploying, configure your Twilio phone number's webhook:
1. Go to Twilio Console > Phone Numbers > Your Number
2. Under "Messaging", set "A Message Comes In" webhook to:
   `https://YOUR-REPLIT-URL/sms` (POST method)
3. Save changes

## Running Locally
```bash
python main.py
```
Server runs on port 5000.

## Endpoints
- `GET /` - Health check / info page
- `GET /health` - API health check
- `POST /sms` - Twilio webhook for incoming SMS
