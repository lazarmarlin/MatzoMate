import random
import re
import sys
import time

from fake_useragent import FakeUserAgentError, UserAgent
from selenium import webdriver
from selenium.common.exceptions import NoSuchElementException, TimeoutException
from selenium.webdriver.chrome.options import Options
from selenium.webdriver.chrome.service import Service
from selenium.webdriver.common.by import By
from selenium.webdriver.support import expected_conditions as EC
from selenium.webdriver.support.ui import WebDriverWait
from selenium_stealth import stealth


def get_desktop_user_agent():
    try:
        ua = UserAgent()

        desktop_uas = []
        desktop_uas.extend(ua.chrome)
        desktop_uas.extend(ua.firefox)
        desktop_uas.extend(ua.edge)
        desktop_uas.extend(ua.safari)

        # Hard filter mobile/tablet identifiers
        desktop_uas = [
            ua for ua in desktop_uas
            if not any(m in ua.lower()
                       for m in ["mobile", "android", "iphone", "ipad"])
        ]

        return random.choice(desktop_uas)

    except (FakeUserAgentError, IndexError):
        return ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                "AppleWebKit/537.36 (KHTML, like Gecko) "
                "Chrome/120.0.0.0 Safari/537.36")


def get_stealth_driver():
    options = Options()
    options.add_argument("--headless=new")
    options.add_argument("--no-sandbox")
    options.add_argument("--disable-dev-shm-usage")
    options.add_argument("--disable-blink-features=AutomationControlled")
    options.add_argument("--disable-extensions")
    options.add_argument("--disable-gpu")
    options.add_argument("--disable-infobars")
    options.add_argument("--window-size=1920,1080")
    options.add_argument("--start-maximized")

    user_agent = get_desktop_user_agent()
    options.add_argument(f"--user-agent={user_agent}")

    options.add_experimental_option("excludeSwitches", ["enable-automation"])
    options.add_experimental_option("useAutomationExtension", False)

    options.set_capability("goog:loggingPrefs", {
        "performance": "OFF",
        "browser": "OFF"
    })

    service = Service()
    driver = webdriver.Chrome(service=service, options=options)

    stealth(
        driver,
        languages=["en-US", "en"],
        vendor="Google Inc.",
        platform="Win32",
        webgl_vendor="Intel Inc.",
        renderer="Intel Iris OpenGL Engine",
        fix_hairline=True,
    )

    driver.execute_cdp_cmd(
        "Network.setUserAgentOverride",
        {
            "userAgent": user_agent,
            "platform": "Windows",
        },
    )

    driver.execute_script(
        "Object.defineProperty(navigator, 'webdriver', {get: () => undefined})"
    )
    return driver


def random_delay(min_sec=1.0, max_sec=3.0):
    time.sleep(random.uniform(min_sec, max_sec))


def extract_product_name(driver):
    try:
        title_elem = driver.find_element(By.ID, "productTitle")
        return title_elem.text.strip()
    except NoSuchElementException:
        return "Unknown Product"


def scroll_page(driver):
    driver.execute_script(
        "window.scrollTo(0, document.body.scrollHeight / 3);")
    random_delay(0.25, 0.5)
    driver.execute_script(
        "window.scrollTo(0, document.body.scrollHeight / 2);")
    random_delay(0.5, 0.75)


def extract_ingredients(driver):
    ingredients = []

    important_info_ids = [
        "important-information",
        "importantInformation",
        "important_information",
    ]

    for info_id in important_info_ids:
        try:
            container = driver.find_element(By.ID, info_id)

            # Find elements that contain the word "Ingredients"
            ingredient_labels = container.find_elements(
                By.XPATH,
                ".//*[contains(translate(text(),'INGREDIENTS','ingredients'),'ingredients')]",
            )

            for label in ingredient_labels:
                # Go up to a reasonable parent block
                parent = label.find_element(By.XPATH, "./ancestor::div[1]")
                text = parent.text.strip()

                # Clean label if duplicated
                cleaned = (text.replace("Ingredients",
                                        "").replace("INGREDIENTS",
                                                    "").strip(": \n"))

                if cleaned:
                    ingredients.append(cleaned)

            if ingredients:
                break

        except NoSuchElementException:
            continue

    return ingredients


def clean_ingredients(raw_ingredients):
    cleaned = []
    for item in raw_ingredients:
        text = re.sub(r"\s+", " ", item)
        text = text.strip()
        text = text.lower()
        if text and len(text) > 10:
            cleaned.append(text)

    unique = list(dict.fromkeys(cleaned))
    return unique


def scrape_amazon_ingredients(url):
    driver = None
    try:
        print("Initializing stealth browser...")
        driver = get_stealth_driver()

        random_delay(1, 2)

        print("Loading page...")
        driver.get(url)

        random_delay(1, 2)

        try:
            WebDriverWait(driver, 10).until(
                EC.presence_of_element_located((By.ID, "productTitle")))
        except TimeoutException:
            print("Warning: Page took too long to load")

        scroll_page(driver)

        product_name = extract_product_name(driver)
        raw_ingredients = extract_ingredients(driver)

        if not raw_ingredients:
            print("No ingredients found in the Important Information section.")
            print("This could mean:")
            print("  - The product doesn't list ingredients")
            print("  - The page structure is different than expected")
            print("  - Amazon may have detected automated access")
            return None

        cleaned = clean_ingredients(raw_ingredients)

        return {
            "product_name": product_name,
            "url": url,
            "ingredients": cleaned
        }

    except Exception as e:
        print(f"Error during scraping: {e}")
        return None

    finally:
        if driver:
            print("Closing browser...")
            driver.quit()


def search(link):
    result = scrape_amazon_ingredients(link)
    if result:
        print("Scraping completed successfully!")
        return result
    else:
        print("Failed to scrape ingredients.")
        return None
