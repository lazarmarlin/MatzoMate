"""
internetsearch.py — thin wrapper kept for compatibility.

When main.py already has a product name from the APIs, it calls
Search() directly to skip the name-resolution step and go straight
to the Amazon scrape.
"""

from namesearch import _amazon_fallback

logger = __import__('logging').getLogger(__name__)


def Search(barcode, productName=None):
    return _amazon_fallback(str(barcode), productName)
