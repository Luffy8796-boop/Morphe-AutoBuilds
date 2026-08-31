"""Small, optional real-browser cookie bootstrap for store pages.

This does not solve or click verification widgets. It only gives a browser the
same normal opportunity a user has to complete an automatic managed challenge,
then reuses any cookie the site issued for the HTTP scraper.
"""

import logging
import os
import time


def get_cookies(url: str, domain: str, timeout: int = 30) -> dict[str, str]:
    try:
        from selenium import webdriver
        from selenium.webdriver.chrome.options import Options
    except ImportError:
        logging.warning("Browser fallback unavailable: selenium is not installed")
        return {}

    options = Options()
    options.add_argument("--headless=new")
    options.add_argument("--disable-gpu")
    options.add_argument("--no-sandbox")
    options.add_argument("--window-size=1280,900")
    chrome_path = os.getenv("CHROME_BINARY")
    if chrome_path:
        options.binary_location = chrome_path

    driver = None
    try:
        driver = webdriver.Chrome(options=options)
        driver.set_page_load_timeout(timeout)
        driver.get(url)
        deadline = time.monotonic() + timeout
        while time.monotonic() < deadline:
            title = (driver.title or "").lower()
            if title and not any(marker in title for marker in ("just a moment", "attention required", "cloudflare")):
                break
            time.sleep(1)
        cookies = {
            cookie["name"]: cookie["value"]
            for cookie in driver.get_cookies()
            if domain.lstrip(".") in cookie.get("domain", "")
        }
        if cookies:
            logging.info("Browser fallback received %d %s cookie(s)", len(cookies), domain)
        return cookies
    except Exception as exc:
        logging.warning("Browser fallback failed for %s: %s", url, exc)
        return {}
    finally:
        if driver:
            driver.quit()
