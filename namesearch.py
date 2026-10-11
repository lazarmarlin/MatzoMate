"""
namesearch.py — fallback ingredient search when structured APIs return nothing.

Flow:
  1. Search the barcode. The product name is accepted only when independent
     websites AGREE on it (consensus), then the AI just phrases it cleanly.
     No agreement -> no name (a wrong name is worse than none).
  2. Fetch the agreeing pages (in parallel). Ingredients are accepted only from
     a page that (a) has a title matching the product and (b) either contains
     the barcode or surfaced in the consensus cluster with a real
     "Ingredients:" block. Barcode alone is not enough.
  3. If nothing verifies, search Amazon and scrape (UPC-on-page or name match).
"""

import logging
import math
import re
import threading
from collections import defaultdict
from concurrent.futures import ThreadPoolExecutor
from urllib.parse import urlparse

import httpx
from bs4 import BeautifulSoup
from ddgs import DDGS
from dotenv import load_dotenv
from openai import OpenAI

logger = logging.getLogger(__name__)

load_dotenv()
_client = None
_client_lock = threading.Lock()


def _get_client():
    global _client
    with _client_lock:
        if _client is None:
            _client = OpenAI()
    return _client


AI_MODEL         = "gpt-4o-mini"
MAX_RESULTS      = 10
MIN_INGREDIENTS  = 2
MAX_PAGE_FETCHES = 6
FETCH_TIMEOUT    = 8

QUERY_TEMPLATES = ("{b}", "{b} product", "upc {b}", "ean {b}")

_INGREDIENT_SECTION = re.compile(
    r"[Ii]ngredients?\s*[:\-]\s*(.{20,1500}?)(?=\n\n|\Z|(?:[A-Z][a-z]+:))",
    re.DOTALL,
)

_HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/124.0.0.0 Safari/537.36"
    ),
    "Accept-Language": "en-US,en;q=0.9",
}

# Words that say nothing about WHICH product this is. Stored in stemmed form
# (see _stem). Two pages both saying "hard candy" is not agreement.
GENERIC = {
    "the", "and", "for", "with", "from", "bag", "pack", "pcs", "piece", "count",
    "size", "ounce", "gram", "pound", "kilogram", "candy", "hard", "soft",
    "flavor", "flavour", "flavored", "flavoured", "product", "item", "buy",
    "shop", "online", "price", "sale", "new", "free", "shipping", "store",
    "amazon", "ebay", "walmart", "target", "upc", "ean", "gtin", "isbn",
    "barcode", "lookup", "search", "brand", "food", "grocery", "each", "per",
    "bulk", "wholesale", "best", "pure", "delivery", "review", "description",
    "detail", "itm", "html", "htm", "php", "aspx", "collection", "category",
    "catalog", "page", "www", "com",
}

# Sites that never carry usable ingredient data for a product lookup.
JUNK_DOMAINS = {
    "youtube.com", "youtu.be", "pinterest.com", "facebook.com", "instagram.com",
    "tiktok.com", "reddit.com", "x.com", "twitter.com", "wikipedia.org",
    "grokipedia.com", "linkedin.com", "quora.com",
}


# ---------------------------------------------------------------------------
# AI helpers
# ---------------------------------------------------------------------------

def _ai(system, user):
    try:
        resp = _get_client().chat.completions.create(
            model=AI_MODEL,
            temperature=0,
            messages=[
                {"role": "system", "content": system},
                {"role": "user",   "content": user},
            ],
        )
        return resp.choices[0].message.content.strip()
    except Exception as e:
        logger.warning(f"AI error: {e}")
        return ""


_SYS_NAME = (
    "You are a product identifier. "
    "These search results all describe the SAME product. "
    "Return ONLY its product name (brand + product, e.g. 'Boba Tea Milk Tea'). "
    "No explanation. If unknown, reply: unknown"
)

_SYS_INGREDIENTS = (
    "You are a food label parser. "
    "Extract the ingredients list from the given text. "
    "Return ONLY a comma-separated list of ingredients, copied as written. "
    "If no ingredients are present, reply: none"
)


def _ai_extract_name(barcode, snippets):
    joined = "\n".join(f"[{i+1}] {s}" for i, s in enumerate(snippets[:10]))
    result = _ai(_SYS_NAME, f"Barcode: {barcode}\n\n{joined}")
    logger.info(f"  AI name reply: {result!r}")
    if not result or result.lower() in ("unknown", ""):
        return None
    return result.strip()


def _ai_extract_ingredients(text):
    result = _ai(_SYS_INGREDIENTS, text[:3000])
    if not result or result.strip().lower() == "none":
        return []
    return [i.strip() for i in result.split(",") if i.strip()]


# ---------------------------------------------------------------------------
# Text / URL helpers
# ---------------------------------------------------------------------------

_WORD = re.compile(r"[a-z]{3,}|\d+")


def _s(r, key):
    """Result field as a string (search backends sometimes return None)."""
    return r.get(key) or ""


def _stem(w):
    if w.isdigit():
        return w
    if w.endswith("ies") and len(w) > 4:
        return w[:-3] + "y"
    if w.endswith("s") and not w.endswith("ss") and len(w) > 3:
        return w[:-1]
    return w


def _tokens(text, extra_generic=()):
    """Distinctive tokens: lowercased, stemmed, minus generic words."""
    text = text.lower().replace("\u2019", "").replace("'", "")
    out = set()
    for w in _WORD.findall(text):
        w = _stem(w)
        if w in GENERIC or w in extra_generic:
            continue
        out.add(w)
    return out


def _domain(url):
    host = urlparse(url).netloc.lower().split(":")[0]
    if host.startswith("www."):
        host = host[4:]
    parts = host.split(".")
    if len(parts) >= 3 and len(parts[-1]) == 2 and parts[-2] in ("co", "com", "org", "net", "gov", "ac"):
        return ".".join(parts[-3:])
    return ".".join(parts[-2:]) if len(parts) >= 2 else host


def _is_junk(url):
    return _domain(url) in JUNK_DOMAINS


def _slug(url):
    return re.sub(r"[-_/.]+", " ", urlparse(url).path)


def _clean_title(title):
    return re.split(r"\s+[|\-\u2013\u2014]\s+", title)[0].strip()


def _agree(text, name, extra_generic=()):
    """
    Does `text` describe the product called `name`? At least 60% of the name's
    distinctive tokens (minimum 2) must appear. Generic words don't count.
    """
    need = _tokens(name)
    if not need:
        return False
    shared = need & _tokens(text, extra_generic)
    if len(need) == 1:
        return len(shared) == 1
    return len(shared) >= max(2, math.ceil(0.6 * len(need)))


# ---------------------------------------------------------------------------
# Barcode matching (digit boundaries; tolerant of leading zeros)
# ---------------------------------------------------------------------------

def _barcode_pattern(barcode):
    bare = re.sub(r"\D", "", str(barcode)).lstrip("0")
    if not bare:
        return None
    return re.compile(r"(?<!\d)0*" + re.escape(bare) + r"(?!\d)")


def _has_barcode(text, barcode):
    pat = _barcode_pattern(barcode)
    return bool(pat and pat.search(text))


def _barcode_context(text, barcode, width=60):
    pat = _barcode_pattern(barcode)
    m = pat.search(text) if pat else None
    if not m:
        return ""
    return text[max(0, m.start() - width): m.end() + width].replace("\n", " ")


# ---------------------------------------------------------------------------
# Search
# ---------------------------------------------------------------------------

def _ddg(query, max_results=MAX_RESULTS):
    try:
        return list(DDGS().text(query, max_results=max_results))
    except Exception as e:
        logger.warning(f"DDG error ({query!r}): {e}")
        return []


def _snippets(results):
    return [f"{_s(r,'title')} — {_s(r,'body')[:200]}" for r in results]


# ---------------------------------------------------------------------------
# Step 1 — consensus: which product do independent sites agree on?
# ---------------------------------------------------------------------------

def _find_consensus(results):
    """
    Return the largest group of results that (a) share >=2 distinctive
    alphabetic tokens with each other and (b) span >=2 independent domains.
    Returns [] if no such group exists.
    """
    nodes = []
    for r in results:
        url = _s(r, "href")
        if not url or _is_junk(url):
            continue
        dom   = _domain(url)
        toks  = {t for t in _tokens(f"{_s(r,'title')} {_slug(url)}", {dom.split('.')[0]})
                 if t.isalpha()}
        if len(toks) >= 2:
            nodes.append((r, dom, toks))

    parent = list(range(len(nodes)))

    def find(i):
        while parent[i] != i:
            parent[i] = parent[parent[i]]
            i = parent[i]
        return i

    for i in range(len(nodes)):
        for j in range(i + 1, len(nodes)):
            if len(nodes[i][2] & nodes[j][2]) >= 2:
                parent[find(i)] = find(j)

    groups = defaultdict(list)
    for i in range(len(nodes)):
        groups[find(i)].append(i)

    best = None
    for members in groups.values():
        doms = {nodes[i][1] for i in members}
        if len(doms) < 2:
            continue
        key = (len(doms), len(members))
        if best is None or key > best[0]:
            best = (key, members)
    return [nodes[i][0] for i in best[1]] if best else []


def _resolve_name(barcode):
    """Returns (name_or_None, all_results, consensus_cluster)."""
    results, seen, cluster = [], set(), []
    for tpl in QUERY_TEMPLATES:
        q = tpl.format(b=barcode)
        for r in _ddg(q):
            href = _s(r, "href")
            if href and href not in seen:
                seen.add(href)
                results.append(r)
        cluster = _find_consensus(results)
        if cluster:
            logger.info(f"  consensus reached after query {q!r}")
            break

    cluster_urls = {_s(r, "href") for r in cluster}
    logger.info(f"  {len(results)} results; consensus cluster: {len(cluster)} "
                f"result(s) on {len({_domain(_s(r,'href')) for r in cluster})} site(s)")
    for r in results[:12]:
        snippet = f"{_s(r,'href')} {_s(r,'title')} {_s(r,'body')}"
        in_c = "*" if _s(r, "href") in cluster_urls else " "
        code = "+" if _has_barcode(snippet, barcode) else "-"
        logger.info(f"    {in_c}{code} {_domain(_s(r,'href'))} | {_s(r,'title')[:60]}")
        if code == "+":
            logger.info(f"         barcode in snippet: ...{_barcode_context(snippet, barcode)}...")

    # --- barcode-confirmed single-site path ---
    # If no cross-site consensus but at least one result mentions the barcode
    # in its snippet, that single hit is strong enough to resolve the name.
    # Ingredient acceptance still requires page-level barcode verification.
    if not cluster:
        barcode_hits = [
            r for r in results
            if not _is_junk(_s(r, "href"))
            and _has_barcode(
                f"{_s(r,'href')} {_s(r,'title')} {_s(r,'body')}", barcode
            )
        ]
        if barcode_hits:
            best = barcode_hits[0]
            name = _clean_title(_s(best, "title"))
            logger.info(
                f"  no cross-site consensus, but barcode in snippet from "
                f"{_domain(_s(best,'href'))!r} — using {name!r} as name hint"
            )
            # Return it as a single-item cluster so step 2 fetches it first.
            # _evaluate_page will still require the barcode on the full page.
            return name, results, [best]
        logger.info("  no agreement across independent sites; not guessing a name")
        return None, results, []

    cluster_text = " ".join(f"{_s(r,'title')} {_slug(_s(r,'href'))}" for r in cluster)
    ai_name = _ai_extract_name(barcode, _snippets(cluster))
    if ai_name and _agree(cluster_text, ai_name):
        return ai_name, results, cluster
    if ai_name:
        logger.info(f"  AI name {ai_name!r} not supported by the agreeing titles; using a title instead")
    return _clean_title(_s(cluster[0], "title")), results, cluster


# ---------------------------------------------------------------------------
# Step 2 — fetch pages, verify, extract ingredients
# ---------------------------------------------------------------------------

def _result_matches(result, barcode, name):
    """Worth fetching? Barcode in the snippet, or the text describes the product."""
    text = f"{_s(result,'href')} {_s(result,'title')} {_s(result,'body')}"
    if _has_barcode(text, barcode):
        return True
    return _agree(f"{_s(result,'title')} {_slug(_s(result,'href'))} {_s(result,'body')}", name)


def _fetch_page(url):
    try:
        with httpx.Client(timeout=FETCH_TIMEOUT, follow_redirects=True, headers=_HEADERS) as c:
            r = c.get(url)
    except Exception as e:
        logger.warning(f"Fetch error ({url[:60]}): {e}")
        return None
    if r.status_code != 200:
        logger.info(f"    HTTP {r.status_code}: {url[:70]}")
        return None
    ctype = r.headers.get("content-type", "").lower()
    if ctype and "html" not in ctype:
        return None

    html = r.text[:2_000_000]
    soup = BeautifulSoup(html, "lxml")
    text = soup.get_text(" ", strip=True)
    tag  = soup.select_one("h1") or soup.select_one("title")
    title = tag.get_text(" ", strip=True)[:200] if tag else ""
    return {"url": url, "html": html, "text": text, "title": title}


def _fetch_many(urls):
    if not urls:
        return []
    with ThreadPoolExecutor(max_workers=min(len(urls), MAX_PAGE_FETCHES)) as ex:
        return list(ex.map(_fetch_page, urls))


def _parse_ingredients(page_text):
    m = _INGREDIENT_SECTION.search(page_text)
    if not m:
        return []
    items = [i.strip(" .*\n\t") for i in re.split(r",|;", m.group(1)) if i.strip()]
    items = [i for i in items if 2 < len(i) < 80]
    return items if len(items) >= MIN_INGREDIENTS else []


def _ingredient_window(text, before=100, after=1500):
    """Text around the 'ingredient' mention most likely to be the real list."""
    lower = text.lower()
    best_i, best_score = None, -1
    for k, m in enumerate(re.finditer("ingredient", lower)):
        if k >= 20:
            break
        score = lower[m.end(): m.end() + 400].count(",")
        if score > best_score:
            best_i, best_score = m.start(), score
    if best_i is None:
        return text[:3000]
    return text[max(0, best_i - before): best_i + after]


def _grounded(items, page_text, frac=0.8):
    """AI-extracted items must actually appear on the page (no invention)."""
    if not items:
        return False
    lower = page_text.lower()
    hits = sum(1 for i in items if i.lower() in lower)
    return hits / len(items) >= frac


def _evaluate_page(page, barcode, name, in_cluster):
    """Returns (ingredients, how_verified) or ([], reason).

    Verification priority:
      1. Barcode on page — always authoritative; name check is skipped.
         The barcode IS the product; a mismatched consensus name is irrelevant.
      2. In consensus cluster + ingredient block — accepted without barcode.
      3. Everything else — rejected.
    """
    url    = page["url"]
    label  = _domain(url).split(".")[0]
    agrees = _agree(f"{page['title']} {_slug(url)}", name, {label})
    code   = _has_barcode(page["html"], barcode)
    logger.info(f"    barcode on page: {code} | title matches product: {agrees} "
                f"| in consensus: {in_cluster} | title: {page['title'][:60]!r}")

    # ── Path 1: barcode confirmed ────────────────────────────────────────
    # The barcode is ground truth. If it is on the page we accept the result
    # regardless of whether the consensus name matches the page title.
    # (A wrong consensus name must not discard a correct barcode hit.)
    if code:
        parsed = _parse_ingredients(page["text"])
        if parsed:
            how = "barcode" if not agrees else "barcode+name"
            return parsed, how
        ai = _ai_extract_ingredients(_ingredient_window(page["text"]))
        if len(ai) >= MIN_INGREDIENTS and _grounded(ai, page["text"]):
            how = "barcode (AI-read)" if not agrees else "barcode+name (AI-read)"
            return ai, how
        return [], "barcode on page but no ingredient list found"

    # ── Path 2: no barcode — name match required ─────────────────────────
    if not agrees:
        return [], "page title does not match the product"

    parsed = _parse_ingredients(page["text"])
    if in_cluster and parsed:
        return parsed, "consensus+name"
    if in_cluster:
        return [], "no ingredient list found on page"
    return [], "barcode not on page and page not in consensus"


def _try_pages(candidates, barcode, name, cluster_urls):
    candidates = candidates[:MAX_PAGE_FETCHES]
    urls  = [_s(c, "href") for c in candidates]
    for u in urls:
        logger.info(f"  Fetching: {u[:80]}")
    pages = _fetch_many(urls)

    for u, page in zip(urls, pages):
        if not page:
            continue
        logger.info(f"  Checking: {u[:80]}")
        ingredients, how = _evaluate_page(page, barcode, name, u in cluster_urls)
        if ingredients:
            pname = page["title"] if 0 < len(page["title"]) <= 100 else name
            logger.info(f"  → {len(ingredients)} ingredients ✓ ({how})")
            return {
                "product_name": pname,
                "ingredients":  ingredients,
                "url":          u,
                "source":       "web search",
                "verification": how,
            }
        logger.info(f"  → rejected: {how}")
    return None


# ---------------------------------------------------------------------------
# Step 3 — Amazon fallback
# ---------------------------------------------------------------------------

def _amazon_fallback(barcode, name):
    import amazonsearch

    query   = f"amazon {barcode}" + (f' "{name}"' if name else "")
    results = _ddg(query)
    logger.info(f"Amazon fallback search: {query!r} → {len(results)} results")
    for r in results[:10]:
        logger.info(f"    {_s(r,'href')[:90]}")

    seen = set()
    for r in results:
        href = _s(r, "href")
        if "www.amazon.com/" not in href:
            continue
        if "/dp/" not in href and "/gp/product/" not in href:
            continue
        m = re.search(r"/([A-Z0-9]{10})(?:[/?]|$)", href)
        if not m:
            continue
        asin = m.group(1)
        if asin in seen:
            continue
        seen.add(asin)

        link = f"https://www.amazon.com/dp/{asin}?language=en_US&th=1"
        logger.info(f"  Trying Amazon: {link}")
        data = amazonsearch.search(link, upcCode=barcode)
        if not data:
            continue

        if data.get("upc_verified"):
            logger.info("  → UPC verified on page ✓")
            return data

        scraped = data.get("product_name", "")
        if not name:
            # Without a reference name, the UPC must be on the page. Accepting
            # an unverified first hit is how a soap bar got returned earlier.
            logger.info(f"  → no reference name and UPC not on page, skipping ({scraped[:60]})")
            continue
        if _agree(scraped, name):
            logger.info(f"  → name match ✓ ({scraped[:60]})")
            return data
        logger.info(f"  → name mismatch, skipping ({scraped[:60]})")

    logger.info("Amazon fallback: no valid product found.")
    return None


# ---------------------------------------------------------------------------
# Public entry point
# ---------------------------------------------------------------------------

def searchByBarcode(barcode, hint=None, manufacturer=None):
    barcode = str(barcode)
    label   = " / ".join(filter(None, [hint, manufacturer]))
    logger.info(f"namesearch: {barcode}" + (f" ({label})" if label else ""))

    # ── Step 1: product name (API hint, else cross-site consensus) ────────
    name, cluster = hint, []
    if not name:
        logger.info("Step 1: search barcode, look for agreement between sites")
        name, _, cluster = _resolve_name(barcode)
        if name:
            logger.info(f"  resolved name: {name!r}")

    if manufacturer and name and manufacturer.lower() not in name.lower():
        name = f"{manufacturer} {name}"

    # ── Step 2: verified ingredient pages ─────────────────────────────────
    if name:
        cluster_urls = {_s(r, "href") for r in cluster}
        tried = set()

        first = [r for r in cluster if not _is_junk(_s(r, "href"))]
        if first:
            logger.info("Step 2a: fetching the pages that agreed")
            tried |= {_s(r, "href") for r in first[:MAX_PAGE_FETCHES]}
            hit = _try_pages(first, barcode, name, cluster_urls)
            if hit:
                return hit

        query = f"{barcode} {name} ingredients"
        logger.info(f"Step 2b: targeted search: {query!r}")
        targeted = [
            r for r in _ddg(query)
            if _s(r, "href") and _s(r, "href") not in tried
            and not _is_junk(_s(r, "href"))
            and _result_matches(r, barcode, name)
        ]
        logger.info(f"  {len(targeted)} new result(s) worth fetching")
        if targeted:
            hit = _try_pages(targeted, barcode, name, cluster_urls)
            if hit:
                return hit

    # ── Step 3: Amazon fallback ───────────────────────────────────────────
    logger.info("Step 3: Amazon fallback")
    return _amazon_fallback(barcode, name)