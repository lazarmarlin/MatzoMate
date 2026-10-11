"""
search.py — unified web search module for Matzo Mate.

Tries Google Custom Search first (better product coverage, reliable results).
Falls back to DuckDuckGo if Google is unavailable, rate-limited, or not
configured.

Setup:
  GOOGLE_API_KEY  — from https://console.cloud.google.com/apis/credentials
  GOOGLE_CSE_ID   — from https://programmablesearchengine.google.com
  (Both must be set for Google to be used; missing either falls back to DDG.)

Google Custom Search free tier: 100 queries/day.
"""

import os

import httpx
from dotenv import load_dotenv

load_dotenv()

_GOOGLE_API_KEY = os.getenv("GOOGLE_API_KEY")
_GOOGLE_CSE_ID  = os.getenv("GOOGLE_CSE_ID")
_GOOGLE_URL     = "https://www.googleapis.com/customsearch/v1"


# ---------------------------------------------------------------------------
# Normalise results to a common shape:
#   {"title": str, "href": str, "body": str}
# ---------------------------------------------------------------------------

def _normalise_google(item):
    return {
        "title": item.get("title", ""),
        "href":  item.get("link",  ""),
        "body":  item.get("snippet", ""),
    }


def _normalise_ddg(item):
    return {
        "title": item.get("title", ""),
        "href":  item.get("href",  ""),
        "body":  item.get("body",  ""),
    }


# ---------------------------------------------------------------------------
# Google Custom Search
# ---------------------------------------------------------------------------

def _google_search(query, max_results=10):
    """
    Query Google Custom Search API.
    Returns list of normalised result dicts, or [] on any error.
    """
    if not _GOOGLE_API_KEY or not _GOOGLE_CSE_ID:
        return []

    results = []
    # Google returns max 10 per page; page through if more needed
    for start in range(1, max_results + 1, 10):
        num = min(10, max_results - start + 1)
        try:
            with httpx.Client(timeout=8) as client:
                r = client.get(_GOOGLE_URL, params={
                    "key":   _GOOGLE_API_KEY,
                    "cx":    _GOOGLE_CSE_ID,
                    "q":     query,
                    "num":   num,
                    "start": start,
                })
            if r.status_code == 429:
                print("Google CSE: rate limited")
                break
            if r.status_code != 200:
                print(f"Google CSE: HTTP {r.status_code}")
                break
            items = r.json().get("items", [])
            results.extend(_normalise_google(i) for i in items)
            if len(items) < num:
                break  # no more pages
        except Exception as e:
            print(f"Google CSE error: {e}")
            break

    return results


# ---------------------------------------------------------------------------
# DuckDuckGo fallback
# ---------------------------------------------------------------------------

def _ddg_search(query, max_results=10):
    """
    Query DuckDuckGo. Returns list of normalised result dicts, or [].
    """
    try:
        from ddgs import DDGS
        return [_normalise_ddg(r) for r in DDGS().text(query, max_results=max_results)]
    except Exception as e:
        print(f"DDG error: {e}")
        return []


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

def webSearch(query, max_results=10):
    """
    Search the web. Uses Google if configured, falls back to DDG.
    Returns a list of {"title", "href", "body"} dicts.
    """
    if _GOOGLE_API_KEY and _GOOGLE_CSE_ID:
        results = _google_search(query, max_results=max_results)
        if results:
            return results
        print(f"Google returned no results for {query!r}, falling back to DDG")

    return _ddg_search(query, max_results=max_results)


def multiSearch(queries, max_results_per_query=10):
    """
    Run multiple queries, deduplicate by href, return combined list.
    Results from earlier queries appear first.
    """
    seen = set()
    combined = []
    for query in queries:
        for r in webSearch(query, max_results=max_results_per_query):
            href = r.get("href", "")
            if href and href not in seen:
                seen.add(href)
                combined.append(r)
    return combined
