"""APKPure scraper with tolerant markup handling."""

import logging
import re
from urllib.parse import urljoin

from bs4 import BeautifulSoup

from src import session

BASE_URL = "https://apkpure.net"
HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 Chrome/120 Safari/537.36",
    "Accept-Language": "en-US,en;q=0.9",
    "Referer": f"{BASE_URL}/",
}


def _app_url(config: dict, suffix: str = "") -> str:
    slug = (config.get("slug") or config.get("name") or "").strip("/")
    package = (config.get("package") or "").strip("/")
    if not slug or not package:
        raise ValueError("APKPure config requires name/slug and package")
    return f"{BASE_URL}/{slug}/{package}{suffix}"


def get_latest_version(app_name: str, config: dict) -> str | None:
    try:
        response = session.get(_app_url(config, "/versions"), headers=HEADERS, timeout=25)
        response.raise_for_status()
        soup = BeautifulSoup(response.content, "html.parser")
        for selector in (".ver-top-down[data-dt-version]", "[data-dt-version]", "[data-version]"):
            element = soup.select_one(selector)
            if element and element.get("data-dt-version", element.get("data-version")):
                return element.get("data-dt-version", element.get("data-version")).strip()
        # Current APKPure markup still includes the version in each release row.
        text = soup.get_text(" ", strip=True)
        match = re.search(r"\b\d+(?:\.\d+){1,}\b", text)
        return match.group(0) if match else None
    except Exception as exc:
        logging.warning("APKPure latest-version lookup failed for %s: %s", app_name, exc)
        return None


def get_download_link(version: str, app_name: str, config: dict) -> str | None:
    if not version:
        return None
    try:
        response = session.get(_app_url(config, f"/download/{version}"), headers=HEADERS, timeout=25)
        response.raise_for_status()
        soup = BeautifulSoup(response.content, "html.parser")
        selectors = (
            "#download_link[href]",
            "a.fast-download[href]",
            "a[data-dt-url][href]",
            "a[href*='download'][href]",
        )
        for selector in selectors:
            for anchor in soup.select(selector):
                href = anchor.get("data-dt-url") or anchor.get("href")
                if href and not href.startswith("javascript:"):
                    return urljoin(response.url, href)
    except Exception as exc:
        logging.warning("APKPure download-link lookup failed for %s %s: %s", app_name, version, exc)
    return None
