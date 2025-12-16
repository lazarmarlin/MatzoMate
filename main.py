import json
from pickle import EMPTY_DICT
from types import NoneType

import requests
from openfoodfacts import API, APIVersion, Country, Environment

import aisearch
import internetsearch


def barcodeSearch(barcode):
    ingredients = []
    ingredients = api.product.get(barcode, fields=["ingredients_text_en"])
    print(ingredients)
    if not ingredients:
        internetsearch.Search(barcode)
    else:
        print("=" * 60)
        print("INGREDIENTS FOUND:")
        print("=" * 60)
        return ingredients["ingredients_text_en"]


api = API(
    user_agent="<application name>",
    username=None,
    password=None,
    country=Country.world,
    version=APIVersion.v2,
    environment=Environment.net,
)
input = "041780351531"

print(barcodeSearch(input))
