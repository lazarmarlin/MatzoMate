import os
import time
from flask import Flask, request
from twilio.twiml.messaging_response import MessagingResponse
from openfoodfacts import API, APIVersion, Country, Environment

app = Flask(__name__)

openFoodFacts = API(
    user_agent="IngredientFinderSMS/1.0",
    username=None,
    password=None,
    country=Country.world,
    version=APIVersion.v2,
    environment=Environment.net,
)

NON_KOSHER_FOR_PASSOVER = [
    "yeast",
    "barley malt",
    "vanilla extract",
    "sodium bicarbonate",
    "riboflavin",
    "baking soda",
    "leaven",
    "baking powder",
]


def check_ingredients(ingredients):
    bad_ingredients = []
    for ingredient in ingredients:
        ingredient_lower = ingredient.lower()
        for banned in NON_KOSHER_FOR_PASSOVER:
            if banned in ingredient_lower:
                bad_ingredients.append(banned)
    return list(set(bad_ingredients))


def product_search(barcode):
    try:
        product = openFoodFacts.product.get(barcode, fields=["ingredients_text_en", "product_name"])
        if product and product.get("ingredients_text_en"):
            ingredients = product["ingredients_text_en"].split(",")
            ingredients = [i.strip() for i in ingredients]
            return {
                "name": product.get("product_name", "Unknown Product"),
                "ingredients": ingredients
            }
    except Exception as e:
        print(f"Error searching product: {e}")
    return None


def format_response(barcode, product_data):
    if not product_data:
        return f"Sorry, I couldn't find ingredients for barcode: {barcode}"
    
    name = product_data.get("name", "Unknown Product")
    ingredients = product_data.get("ingredients", [])
    bad_ingredients = check_ingredients(ingredients)
    
    response = f"Product: {name}\n\n"
    
    if bad_ingredients:
        response += "NOT Kosher for Passover\n"
        response += f"Contains: {', '.join(bad_ingredients)}"
    else:
        response += "Probably Kosher for Passover"
    
    return response


@app.route("/sms", methods=["POST"])
def sms_reply():
    incoming_msg = request.values.get("Body", "").strip()
    print(f"Received SMS: {incoming_msg}")
    
    resp = MessagingResponse()
    
    barcode = "".join(filter(str.isdigit, incoming_msg))
    
    if not barcode:
        resp.message("Please send a barcode number to look up ingredients.")
        return str(resp)
    
    print(f"Looking up barcode: {barcode}")
    product_data = product_search(barcode)
    response_text = format_response(barcode, product_data)
    
    print(f"Sending response: {response_text}")
    resp.message(response_text)
    
    return str(resp)


@app.route("/")
def index():
    return "Ingredient Finder SMS Service is running. Send a barcode via SMS to look up ingredients."


@app.route("/health")
def health():
    return {"status": "ok"}


if __name__ == "__main__":
    app.run(host="0.0.0.0", port=5000, debug=True)
