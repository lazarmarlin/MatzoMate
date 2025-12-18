import re

from ddgs import DDGS

import amazonsearch


def clean_amazon_url(url, domain="amazon.com", language="en_US"):
    match = re.search(r"/([A-Z0-9]{10})(?:[/?]|$)", url)
    if not match:
        raise ValueError("ASIN not found")

    asin = match.group(1)
    return f"https://www.{domain}/dp/{asin}?language={language}&th=1"


def Search(upcCode):
    amazonLink = None
    amazonLinkNotFound = True
    maxResults = 5
    attempts = 1
    while amazonLinkNotFound:
        results = DDGS().text(upcCode, max_results=maxResults)
        for result in results:
            if "www.amazon.com/" in result["href"]:
                if upcCode in result["body"] or result["title"]:
                    print("Amazon link found")
                    amazonLink = clean_amazon_url(result["href"])
                    print(amazonLink)
                    amazonLinkNotFound = False
                    break
                else:
                    print("Amazon link found but not the right product")
                    print(result["title"])
                    continue
            else:
                attempts += 1
                maxResults += 5
                print("Amazon link not found yet trying again \n")
                print(f"Attempt number {attempts} with {maxResults} results \n")

    return amazonsearch.search(amazonLink)
