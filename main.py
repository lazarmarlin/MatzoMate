import sys
import time

from openfoodfacts import API, APIVersion, Country, Environment

import internetsearch


def checkIngredients(ingredients):
    nonKosherForPassover = [
        "yeast",
        "barley malt",
        "vanilla extract",
        "sodium bicarbonate",
        "riboflavin",
        "baking soda",
        "leaven",
        "baking powder",
        "baking soda",
    ]

    badIngredients = []

    for ingredient in ingredients:
        ingredient_lower = ingredient.lower()
        print(f"Checking ingredient: {ingredient_lower}")

        for banned in nonKosherForPassover:
            if banned in ingredient_lower:
                badIngredients.append(banned)
    badIngredients = list(set(badIngredients))
    return badIngredients


def productSearch(barcode):
    # Try product API
    try:
        product = openFoodFacts.product.get(barcode, fields=["ingredients_text_en"])
        if product and product.get("ingredients_text_en"):
            product["ingredients_text_en"] = product["ingredients_text_en"].split(",")
            ingredients = {"ingredients": product["ingredients_text_en"]}
            return ingredients
    except Exception:
        pass  # API failed, move on

    # Try internet search
    try:
        ingredients = internetsearch.Search(barcode)
        if ingredients:
            return ingredients
    except Exception:
        pass  # Internet search failed

    # Nothing worked
    return None


openFoodFacts = API(
    user_agent="<application name>",
    username=None,
    password=None,
    country=Country.world,
    version=APIVersion.v2,
    environment=Environment.net,
)


def main(upc):
    productData = []
    # input = "034000003129"
    # input = "029000356733"
    startTime = time.time()
    productData = productSearch(upc)
    productData["ingredients"] = productData["ingredients"][0].split(",")  # pyright: ignore
    endTime = time.time()
    print(f"Time taken: {endTime - startTime} seconds")

    if productData:
        print("\n")
        badIngredients = checkIngredients(productData["ingredients"])
        if badIngredients:
            print("\n")
            print("-" * 60)
            print("Product is not kosher for Passover")
            for badIngredient in badIngredients:
                print(f"Non-kosher ingredient found: {badIngredient}")
        else:
            print("\n")
            print("-" * 60)
            print("Product is probably kosher for Passover")
    return


main(sys.argv[1])
