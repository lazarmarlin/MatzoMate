import os
import sys
import time
import asyncio

from dotenv import load_dotenv
load_dotenv()

from openfoodfacts import API, APIVersion, Country, Environment
import database
import internetsearch
import aisearch
import namesearch

logger = __import__('logging').getLogger(__name__)

# ---------------------------------------------------------------------------
# Ingredient rules
# ---------------------------------------------------------------------------

# Hard chametz — universally not kosher for Passover
CHAMETZ = [
    "wheat", "wheat flour", "whole wheat", "enriched flour", "bleached flour",
    "unbleached flour", "all-purpose flour", "bread flour", "semolina",
    "durum", "spelt", "rye", "barley", "oats", "triticale",
    "malt", "barley malt", "malt extract", "malt syrup", "malt vinegar",
    "maltodextrin", "modified food starch", "food starch",
    "wheat starch", "barley starch", "rye starch",
    "yeast", "yeast extract", "autolyzed yeast", "brewers yeast",
    "baking soda", "sodium bicarbonate", "baking powder", "leaven",
    "leavening", "cream of tartar",
    "vanilla extract", "natural flavor", "artificial flavor",
    "riboflavin", "folic acid", "niacin", "thiamine",
]



def _chametz_match(banned: str, full_text: str) -> bool:
    """Use word-boundary matching for short tokens to avoid false positives.
    e.g. 'rye' must not match 'turkey'; 'wheat' must not match 'buckwheat'."""
    import re as _re
    if len(banned) <= 6:
        return bool(_re.search(r'\b' + _re.escape(banned) + r'\b', full_text))
    return banned in full_text


def checkIngredients(ingredients):
    """
    Returns a dict with one key:
      - "chametz": list of non-kosher-for-Passover ingredients found
    Uses the AI fallback (aisearch) for anything not caught by the local list.
    """
    found_chametz = []
    full_text = ", ".join(ingredients).lower()

    for banned in CHAMETZ:
        if _chametz_match(banned, full_text):
            found_chametz.append(banned)

    # Only call AI when the ingredient list is too short to trust
    # (empty or a single token means the data is probably incomplete)
    if not found_chametz and len(ingredients) <= 1:
        logger.info("Ingredient list too short — asking AI to check")
        try:
            ai_result = aisearch.aiSearch(full_text)
            if ai_result and ai_result.strip().lower() not in ("", "kosher", "kosher for passover", "unknown"):
                found_chametz.append(f"[AI flagged]: {ai_result.strip()}")
        except Exception as e:
            logger.warning(f"AI check error: {e}")

    found_chametz = list(set(found_chametz))
    return {"chametz": found_chametz}


# ---------------------------------------------------------------------------
# Database helpers
# ---------------------------------------------------------------------------

def databaseSearch(barcode):
    product = database.findProduct(barcode)
    if product:
        # Respect cache expiry if the DB layer supports it
        if hasattr(database, "isExpired") and database.isExpired(barcode):
            database.deleteProduct(barcode)
            return None
        return product
    return None


# ---------------------------------------------------------------------------
# Async parallel lookup across free sources
# ---------------------------------------------------------------------------

async def fetchOpenFoodFacts(barcode):
    """Wraps the synchronous OFF call so it can run in a thread."""
    loop = asyncio.get_running_loop()
    return await loop.run_in_executor(None, _offSync, barcode)


def _offSync(barcode):
    try:
        productData = openFoodFacts.product.get(
            barcode,
            fields=[
                "ingredients_text_en",
                "abbreviated_product_name",
                "product_name_en",
                "product_name",
                "brands",
                "brand_owner",
                "manufacturer",
            ],
        )
        if not productData:
            return None

        name = (
            productData.get("abbreviated_product_name")
            or productData.get("product_name_en")
            or productData.get("product_name")
        )
        manufacturer = (
            productData.get("brand_owner")
            or productData.get("brands", "").split(",")[0].strip()
            or productData.get("manufacturer")
            or None
        ) or None
        url = f"https://world.openfoodfacts.org/product/{barcode}"

        ingredients_raw = productData.get("ingredients_text_en", "")
        if ingredients_raw:
            ingredients = [i.strip() for i in ingredients_raw.split(",") if i.strip()]
            return {
                "ingredients":  ingredients,
                "product_name": name,
                "manufacturer": manufacturer,
                "url":          url,
                "source":       "OpenFoodFacts",
                "partial":      False,
            }

        # Name found but no ingredients — return partial so the name
        # can guide the internet search fallback
        if name:
            logger.info(f"OpenFoodFacts: name found ({name!r}) but no ingredients")
            return {
                "ingredients":  [],
                "product_name": name,
                "manufacturer": manufacturer,
                "url":          url,
                "source":       "OpenFoodFacts",
                "partial":      True,
            }

    except Exception as e:
        logger.warning(f"OpenFoodFacts error: {e}")
    return None


async def fetchUSDA(barcode):
    """Query the USDA FoodData Central API."""
    import httpx
    api_key = os.getenv("USDA_API_KEY", "DEMO_KEY")
    try:
        async with httpx.AsyncClient(timeout=8) as client:
            r = await client.get(
                "https://api.nal.usda.gov/fdc/v1/foods/search",
                params={"query": barcode, "pageSize": 1, "api_key": api_key},
            )
            if r.status_code != 200:
                return None
            data = r.json()
            foods = data.get("foods", [])
            if not foods:
                return None
            food = foods[0]
            ingredients_raw = food.get("ingredients", "")
            if not ingredients_raw:
                return None
            ingredients = [i.strip() for i in ingredients_raw.split(",") if i.strip()]
            return {
                "ingredients":  ingredients,
                "product_name": food.get("description", "Unknown"),
                "manufacturer": food.get("brandOwner") or food.get("brandName") or None,
                "url":          f"https://fdc.nal.usda.gov/fdc-app.html#/?fdcId={food.get('fdcId','')}",
                "source":       "USDA FoodData",
            }
    except Exception as e:
        logger.warning(f"USDA error: {e}")
    return None


async def fetchOpenBeautyFacts(barcode):
    """Open Beauty Facts — useful for cosmetics / non-food UPCs."""
    import httpx
    try:
        async with httpx.AsyncClient(timeout=8) as client:
            r = await client.get(
                f"https://world.openbeautyfacts.org/api/v0/product/{barcode}.json"
            )
            if r.status_code != 200:
                return None
            data = r.json()
            product = data.get("product", {})
            ingredients_raw = product.get("ingredients_text_en") or product.get("ingredients_text", "")
            if not ingredients_raw:
                return None
            ingredients = [i.strip() for i in ingredients_raw.split(",") if i.strip()]
            name = product.get("product_name_en") or product.get("product_name", "Unknown")
            return {
                "ingredients":  ingredients,
                "product_name": name,
                "manufacturer": product.get("brands", "").split(",")[0].strip() or None,
                "url":          f"https://world.openbeautyfacts.org/product/{barcode}",
                "source":       "Open Beauty Facts",
            }
    except Exception as e:
        logger.warning(f"Open Beauty Facts error: {e}")
    return None


async def parallelAPISearch(barcode):
    """
    Run all three free API sources concurrently.

    Returns a tuple: (full_result_or_None, best_name_or_None)
      - full_result: a complete result with ingredients (ready to return)
      - best_name:   product name rescued from a partial result (no ingredients)
                     used to guide the internet search fallback
    """
    tasks = [
        fetchOpenFoodFacts(barcode),
        fetchUSDA(barcode),
        fetchOpenBeautyFacts(barcode),
    ]
    results = await asyncio.gather(*tasks, return_exceptions=True)

    for label, r in zip(("OpenFoodFacts", "USDA", "OpenBeautyFacts"), results):
        if isinstance(r, Exception):
            logger.warning(f"{label}: raised {r!r}")
        elif not r:
            logger.info(f"{label}: no data for {barcode}")
        elif r.get("partial"):
            logger.info(f"{label}: name only ({r.get('product_name')!r}), no ingredients")
        else:
            logger.info(f"{label}: {len(r.get('ingredients', []))} ingredients")

    best_name = None
    best_manufacturer = None
    for r in results:
        if not r or isinstance(r, Exception):
            continue
        if r.get("partial"):
            # Name-only hit — save the name but keep looking for ingredients
            if not best_name and r.get("product_name"):
                best_name        = r["product_name"]
                best_manufacturer = r.get("manufacturer")
                logger.info(f"Rescued name from partial result: {best_name!r} / {best_manufacturer!r}")
        else:
            # Full result with ingredients
            return r, best_name, best_manufacturer

    return None, best_name, best_manufacturer


# ---------------------------------------------------------------------------
# Main product search (sync wrapper used by Flask / CLI)
# ---------------------------------------------------------------------------

def productSearch(barcode):
    barcode = str(barcode)
    partial_name         = None  # carry a product name forward for better search queries
    partial_manufacturer = None  # carry manufacturer/brand forward too

    # 1. Database cache
    try:
        product = databaseSearch(barcode)
        if product:
            logger.info("Found in cache")
            return product
    except Exception as e:
        logger.warning(f"Database error: {e}")

    # 2. Parallel free APIs
    try:
        result, partial_name, partial_manufacturer = asyncio.run(parallelAPISearch(barcode))
        if result:
            logger.info(f"Found via {result.get('source', 'API')}")
            database.addProduct(barcode, result["product_name"], result["ingredients"], result["url"], result.get("source", ""))
            return result
        if partial_name:
            logger.info(f"No ingredients from APIs, will use name hint for search: {partial_name!r} / {partial_manufacturer!r}")
    except Exception as e:
        logger.warning(f"Parallel API error: {e}")

    # 3. namesearch — DDG name resolution → targeted search → Amazon fallback
    #    partial_name / partial_manufacturer flow straight through as hints.
    try:
        productData = namesearch.searchByBarcode(
            barcode,
            hint=partial_name,
            manufacturer=partial_manufacturer,
        )
        if productData:
            database.addProduct(
                barcode,
                productData["product_name"],
                productData["ingredients"],
                productData["url"],
                productData.get("source", "namesearch"),
            )
            return productData
    except Exception as e:
        logger.warning(f"Name search error: {e}")

    return None


# ---------------------------------------------------------------------------
# OpenFoodFacts client (module-level so it's reused)
# ---------------------------------------------------------------------------

openFoodFacts = API(
    user_agent=os.getenv("OFF_USER_AGENT", "MatzoMate/1.0"),
    username=None,
    password=None,
    country=Country.world,
    version=APIVersion.v2,
    environment=Environment.net,
)


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------

def main(upc):
    startTime = time.time()
    productData = productSearch(upc)
    elapsed = time.time() - startTime
    logger.info(f"Time taken: {elapsed:.2f}s")

    if not productData:
        print("Product not found.")
        return

    print(f"\n{productData['product_name']}")
    print("-" * 60)
    print(f"Source: {productData.get('source', 'cache')}")
    print(f"URL: {productData.get('url', 'N/A')}")
    print()

    results = checkIngredients(productData["ingredients"])

    if results["chametz"]:
        print("❌  NOT kosher for Passover")
        for item in results["chametz"]:
            print(f"  [chametz]   {item}")
    else:
        print("✅  Probably kosher for Passover")

    if len(productData["ingredients"]) <= 1:
        print("\n⚠  Ingredient data looks incomplete.")
        print("   Consider contributing via the UI.")


if __name__ == "__main__":
    from logconfig import setup_logging
    setup_logging()
    upc = next((a for a in sys.argv[1:] if not a.startswith("--")), None)
    if not upc:
        print("Usage: python main.py <UPC> [--debug]")
        sys.exit(1)
    main(upc)