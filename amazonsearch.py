import random
import re
import time

import httpx
from bs4 import BeautifulSoup
from fake_useragent import FakeUserAgentError, UserAgent

logger = __import__('logging').getLogger(__name__)


# ---------------------------------------------------------------------------
# User-agent helpers
# ---------------------------------------------------------------------------

_ua_instance = None
_ua_lock = __import__('threading').Lock()

def _get_ua_instance():
    global _ua_instance
    with _ua_lock:
        if _ua_instance is None:
            try:
                _ua_instance = UserAgent()
            except FakeUserAgentError:
                pass
    return _ua_instance


def get_desktop_user_agent():
    ua = _get_ua_instance()
    if ua is None:
        return _fallback_ua()
    try:
        candidates = []
        for browser in (ua.chrome, ua.firefox, ua.edge, ua.safari):
            if isinstance(browser, list):
                candidates.extend(browser)
            elif isinstance(browser, str):
                candidates.append(browser)
        candidates = [
            u for u in candidates
            if not any(m in u.lower() for m in ["mobile", "android", "iphone", "ipad"])
        ]
        return random.choice(candidates) if candidates else _fallback_ua()
    except (IndexError, Exception):
        return _fallback_ua()


def _fallback_ua():
    return (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/124.0.0.0 Safari/537.36"
    )


# ---------------------------------------------------------------------------
# Fast path: httpx + BeautifulSoup (no browser needed)
# ---------------------------------------------------------------------------

def _scrape_with_httpx(url):
    headers = {
        "User-Agent": get_desktop_user_agent(),
        "Accept-Language": "en-US,en;q=0.9",
        "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
    }
    try:
        with httpx.Client(timeout=12, follow_redirects=True, headers=headers) as client:
            r = client.get(url)
            if r.status_code != 200:
                logger.info(f"httpx got status {r.status_code}")
                return None
    except Exception as e:
        logger.warning(f"httpx request failed: {e}")
        return None

    soup = BeautifulSoup(r.text, "html.parser")

    # Product name
    title_tag = soup.find(id="productTitle")
    product_name = title_tag.get_text(strip=True) if title_tag else "Unknown Product"

    # Ingredients — collect ALL matching blocks, not just the first
    ingredients_text = _extract_ingredients_bs4(soup)
    if not ingredients_text:
        return None

    return {
        "product_name": product_name,
        "url": url,
        "raw_ingredients": ingredients_text,
        "page_text": r.text,   # kept for UPC verification; not stored in DB
    }


def _extract_ingredients_bs4(soup):
    """
    Search the Important Information section for all ingredient blocks
    and return them joined as one string.
    """
    blocks = []
    container_ids = ["important-information", "importantInformation", "important_information"]

    for cid in container_ids:
        container = soup.find(id=cid)
        if not container:
            continue
        text = container.get_text(" ", strip=True)
        # Find everything after "Ingredients" or "INGREDIENTS"
        match = re.search(r"[Ii]ngredients[:\s]+(.+)", text, re.DOTALL)
        if match:
            blocks.append(match.group(1).strip())

    # Also check product description area as a fallback
    if not blocks:
        for tag in soup.find_all(["p", "div", "span"]):
            txt = tag.get_text(" ", strip=True)
            if re.match(r"[Ii]ngredients[:\s]", txt) and len(txt) > 20:
                blocks.append(re.sub(r"^[Ii]ngredients[:\s]+", "", txt).strip())
                break

    return " ".join(blocks) if blocks else ""


# ---------------------------------------------------------------------------
# Slow path: Selenium (only if httpx fails / Amazon blocks)
# ---------------------------------------------------------------------------

def _scrape_with_selenium(url):
    from selenium import webdriver
    from selenium.common.exceptions import NoSuchElementException, TimeoutException
    from selenium.webdriver.chrome.options import Options
    from selenium.webdriver.chrome.service import Service
    from selenium.webdriver.common.by import By
    from selenium.webdriver.support import expected_conditions as EC
    from selenium.webdriver.support.ui import WebDriverWait
    from selenium_stealth import stealth

    options = Options()
    options.add_argument("--headless=new")
    options.add_argument("--no-sandbox")
    options.add_argument("--disable-dev-shm-usage")
    options.add_argument("--disable-blink-features=AutomationControlled")
    options.add_argument("--disable-extensions")
    options.add_argument("--disable-gpu")
    options.add_argument("--window-size=1920,1080")

    ua = get_desktop_user_agent()
    options.add_argument(f"--user-agent={ua}")
    options.add_experimental_option("excludeSwitches", ["enable-automation"])
    options.add_experimental_option("useAutomationExtension", False)

    driver = webdriver.Chrome(service=Service(), options=options)
    stealth(
        driver,
        languages=["en-US", "en"],
        vendor="Google Inc.",
        platform="Win32",
        webgl_vendor="Intel Inc.",
        renderer="Intel Iris OpenGL Engine",
        fix_hairline=True,
    )
    driver.execute_script(
        "Object.defineProperty(navigator,'webdriver',{get:()=>undefined})"
    )

    try:
        driver.get(url)
        time.sleep(random.uniform(1.5, 3.0))
        try:
            WebDriverWait(driver, 10).until(
                EC.presence_of_element_located((By.ID, "productTitle"))
            )
        except TimeoutException:
            logger.warning("Warning: productTitle not found within timeout")

        # Scroll to trigger lazy-loaded content
        driver.execute_script("window.scrollTo(0, document.body.scrollHeight/2);")
        time.sleep(random.uniform(0.5, 1.0))

        product_name = "Unknown Product"
        try:
            product_name = driver.find_element(By.ID, "productTitle").text.strip()
        except NoSuchElementException:
            pass

        raw = _extract_ingredients_selenium(driver)
        if not raw:
            return None
        return {"product_name": product_name, "url": url, "raw_ingredients": raw, "page_text": ""}
    finally:
        driver.quit()


def _extract_ingredients_selenium(driver):
    from selenium.common.exceptions import NoSuchElementException
    from selenium.webdriver.common.by import By

    container_ids = ["important-information", "importantInformation", "important_information"]
    blocks = []

    for cid in container_ids:
        try:
            container = driver.find_element(By.ID, cid)
            labels = container.find_elements(
                By.XPATH,
                ".//*[contains(translate(text(),'INGREDIENTS','ingredients'),'ingredients')]",
            )
            for label in labels:
                try:
                    parent = label.find_element(By.XPATH, "./ancestor::div[1]")
                    text = parent.text.strip()
                    cleaned = re.sub(r"[Ii]ngredients[:\s]*", "", text).strip()
                    if cleaned and len(cleaned) > 10:
                        blocks.append(cleaned)
                except Exception:
                    pass
            if blocks:
                break
        except NoSuchElementException:
            continue

    return " ".join(blocks)


# ---------------------------------------------------------------------------
# Shared ingredient cleaning
# ---------------------------------------------------------------------------

def clean_ingredients(raw_text):
    """
    Split on commas, clean each token, deduplicate — applied to the FULL
    joined ingredient string (fixes the old [0].split bug).
    """
    # Normalize whitespace
    text = re.sub(r"\s+", " ", raw_text).strip().lower()

    # Remove content in parentheses that's usually sub-ingredient lists
    # e.g. "enriched flour (wheat, niacin, ...)" → keep the parent token
    text = re.sub(r"\([^)]*\)", "", text)

    parts = [p.strip(" .;") for p in text.split(",")]
    cleaned = [p for p in parts if p and len(p) > 2]
    return list(dict.fromkeys(cleaned))  # deduplicate, preserve order


# ---------------------------------------------------------------------------
# Public entry point
# ---------------------------------------------------------------------------

def search(link, upcCode=None):
    logger.info("Trying fast path (httpx)...")
    result = _scrape_with_httpx(link)

    if not result:
        logger.warning("Fast path failed, falling back to Selenium...")
        result = _scrape_with_selenium(link)

    if not result:
        logger.info("Failed to scrape ingredients from Amazon.")
        return None

    ingredients = clean_ingredients(result["raw_ingredients"])
    if not ingredients:
        logger.info("Ingredient block found but empty after cleaning.")
        return None

    # Check if the UPC appears anywhere in the page source (definitive match)
    upc_verified = False
    if upcCode:
        page_text = result.get("page_text", "")
        upc_clean = re.sub(r"\D", "", str(upcCode))   # digits only
        if upc_clean and upc_clean in re.sub(r"\D", "", page_text):
            upc_verified = True
            logger.info(f"  UPC {upc_clean} found in page source ✓")

    logger.info(f"Scraped {len(ingredients)} ingredients.")
    return {
        "product_name": result["product_name"],
        "url":          result["url"],
        "ingredients":  ingredients,
        "source":       "Amazon",
        "upc_verified": upc_verified,
    }
