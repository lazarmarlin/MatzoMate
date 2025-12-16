import requests


def search_openfoodfacts(product_name):
    url = "https://world.openfoodfacts.org/cgi/search.pl"
    params = {
        "search_terms": product_name,
        "search_simple": 1,
        "action": "process",
        "json": 1,
    }
    r = requests.get(url, params=params)
    data = r.json()
    return data["products"]


products = search_openfoodfacts(input(": "))
print(products[0]["ingredients_text"])
