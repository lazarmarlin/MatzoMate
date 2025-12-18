import sys
import time

from openfoodfacts import API, APIVersion, Country, Environment
import database
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

def databaseSearch(barcode):
    product = database.findProduct(barcode)
    if product:
        return product
    else:
        return None

def productSearch(barcode):
    barcode = str(barcode)

    # 1️⃣ Try database
    try:
        product = databaseSearch(barcode)
        if product:
            return product
    except Exception as e:
        print("Database error:", e)

    # 2️⃣ Try OpenFoodFacts
    try:
        productData = openFoodFacts.product.get(
            barcode,
            fields=[
                "ingredients_text_en",
                "abbreviated_product_name",
                "product_name_en",
                "product_name"
            ]
        )

        if productData and productData.get("ingredients_text_en"):
            ingredients = [
                i.strip()
                for i in productData["ingredients_text_en"].split(",")
                if i.strip()
            ]

            name = (
                productData.get("abbreviated_product_name")
                or productData.get("product_name_en")
                or productData.get("product_name")
            )

            result = {
                "ingredients": ingredients,
                "product_name": name,
                "url": f"https://world.openfoodfacts.org/product/{barcode}"
            }

            print("Adding product to database")
            database.addProduct(barcode, name, ingredients, result["url"])
            return result

    except Exception as e:
        print("OpenFoodFacts error:", e)

    # 3️⃣ Try internet search
    try:
        print(barcode)
        productData = internetsearch.Search(barcode)
        if productData:
            print("Adding product to database")
            database.addProduct(
                barcode,
                productData["product_name"],
                productData["ingredients"],
                productData["url"]
            )
            return productData
    except Exception as e:
        print("Internet search error:", e)

    # ❌ Nothing worked
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
    endTime = time.time()
    print(f"Time taken: {endTime - startTime} seconds")
    
    if productData:
        print("\n")
        print(productData["product_name"])
        print("-" * 60)
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
