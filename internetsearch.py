# def findProductName(userInput):
#    searchResults = search(str(userInput))
#    return searchResults
# testInput = input(":")
# test = findProductName(testInput)
# for url in test:
#    print(url)
from ddgs import DDGS  # pyright: ignore[reportMissingImports]

import amazonsearch


def Search(upcCode):
    amazonLink = None
    amazonLinkNotFound = True
    maxResults = 5
    while amazonLinkNotFound:
        results = DDGS().text(upcCode, max_results=maxResults)
        for result in results:
            if "amazon" in result["href"]:
                print(result["href"])
                amazonLink = result["href"]
                amazonLinkNotFound = False
            else:
                maxResults += 5

    amazonsearch.search(amazonLink)
