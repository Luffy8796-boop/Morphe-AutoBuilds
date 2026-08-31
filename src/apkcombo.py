"""APKCombo fallback downloader, based on its public download pages.

APKCombo is intentionally last in the provider cascade.  It is used only when
the primary stores decline GitHub-hosted traffic or do not carry the app.
"""

from __future__ import annotations

import logging
import re
from urllib.parse import parse_qs, unquote, urljoin, urlparse

from bs4 import BeautifulSoup

from src import session, utils

BASE_URL = "https://apkcombo.com"
HEADERS = {"User-Agent": "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 Chrome/131 Safari/537.36"}


def _page(package: str, suffix: str = ""):
    return session.get(f"{BASE_URL}/search/{package}/download{suffix}", headers=HEADERS, timeout=25)


def get_latest_version(app_name: str, config: dict) -> str | None:
    package = (config.get("package") or "").strip()
    if not package:
        return None
    try:
        response = _page(package)
        response.raise_for_status()
        versions = re.findall(r"phone-([0-9][^-]*)-(?:apk|xapk|apks)", response.text)
        versions = [value for value in versions if value and value[0].isdigit()]
        if versions:
            return utils.get_highest_version(versions)
    except Exception as exc:
        logging.debug("APKCombo latest-version lookup failed for %s: %s", app_name, exc)
    return None


def _unwrap_redirect(url: str) -> str:
    parsed = urlparse(url)
    if parsed.path == "/r2":
        target = parse_qs(parsed.query).get("u", [""])[0]
        if target:
            return unquote(target)
    return url


def get_download_link(version: str, app_name: str, config: dict) -> str | None:
    package = (config.get("package") or "").strip()
    if not package or not version:
        return None
    for extension in ("apk", "xapk", "apks"):
        try:
            response = _page(package, f"/phone-{version}-{extension}")
            response.raise_for_status()
            soup = BeautifulSoup(response.content, "html.parser")
            # The public page puts signed assets behind /r2?u=… redirects.
            # Select an actual variant link, never advertising/navigation links.
            for anchor in soup.select("a.variant[href]"):
                href = anchor.get("href")
                if href:
                    return _unwrap_redirect(urljoin(response.url, href))
        except Exception as exc:
            logging.debug("APKCombo download-link lookup failed for %s %s: %s", app_name, version, exc)
    return None
