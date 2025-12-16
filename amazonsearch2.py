import random
import re
import time

from fake_useragent import UserAgent
from selenium import webdriver
from selenium.common.exceptions import NoSuchElementException, TimeoutException
from selenium.webdriver.chrome.options import Options
from selenium.webdriver.chrome.service import Service
from selenium.webdriver.common.by import By
from selenium.webdriver.support import expected_conditions as EC
from selenium.webdriver.support.ui import WebDriverWait
from selenium_stealth import stealth


def get_stealth_driver():
    options = Options()
    #    options.add_argument("--headless=new")
    options.add_argument("--no-sandbox")
    options.add_argument("--disable-dev-shm-usage")
    options.add_argument("--disable-blink-features=AutomationControlled")
    options.add_argument("--disable-extensions")
    options.add_argument("--disable-gpu")
    options.add_argument("--disable-infobars")
    options.add_argument("--window-size=1920,1080")
    options.add_argument("--start-maximized")

    try:
        ua = UserAgent()
        user_agent = ua.random
    except:
        user_agent = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"

    options.add_argument(f"--user-agent={user_agent}")

    options.add_experimental_option("excludeSwitches", ["enable-automation"])
    options.add_experimental_option("useAutomationExtension", False)

    options.set_capability(
        "goog:loggingPrefs", {"performance": "OFF", "browser": "OFF"}
    )

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


if not ingredients:
    try:
        detail_bullets = driver.find_element(By.ID, "detailBullets_feature_div")
        items = detail_bullets.find_elements(By.TAG_NAME, "li")
        for item in items:
            text = item.text.strip().lower()
            if "ingredient" in text:
                ingredients.append(item.text.strip())
    except NoSuchElementException:
        pass

if not ingredients:
    try:
        prod_details = driver.find_element(By.ID, "prodDetails")
        rows = prod_details.find_elements(By.TAG_NAME, "tr")
        for row in rows:
            text = row.text.strip().lower()
            if "ingredient" in text:
                ingredients.append(row.text.strip())
    except NoSuchElementException:
        pass

if not ingredients:
    try:
        aplus = driver.find_element(By.ID, "aplus")
        all_text = aplus.text
        lines = all_text.split("\n")
        capture = False
        for line in lines:
            if "ingredient" in line.lower():
                capture = True
                ingredients.append(line)
            elif capture and line.strip():
                if any(
                    keyword in line.lower()
                    for keyword in ["warning", "directions", "storage", "allergen"]
                ):
                    capture = False
                else:
                    ingredients.append(line)
    except NoSuchElementException:
        pass

if not ingredients:
    try:
        all_divs = driver.find_elements(
            By.XPATH,
            "//div[contains(@class, 'content') or contains(@class, 'detail') or contains(@class, 'info')]",
        )
        for div in all_divs:
            text = div.text.strip().lower()
            if "ingredients:" in text or "ingredients list" in text:
                content = div.text.strip()
                if len(content) < 2000:
                    ingredients.append(content)
                break
    except:
        pass
