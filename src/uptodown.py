"""Uptodown release and download-page scraper.

Uptodown's internal version API is stable, but its download button has had two
different shapes.  Keep both paths: older pages expose a direct ``data-url``;
newer pages may require an interactive Turnstile token.  The latter is reported
plainly so the downloader can continue with another provider.
"""

import logging
import re
from urllib.parse import urljoin

from bs4 import BeautifulSoup

from src import session, utils


def _normalise_version(value: str) -> tuple:
    return utils.normalize_version(value or "")


def _same_version(left: str, right: str) -> bool:
    clean = lambda value: re.sub(r"[\(\[].*?[\)\]]", "", value or "").strip()
    return left == right or clean(left) == clean(right) or _normalise_version(left) == _normalise_version(right)


def _page_is_app(response) -> bool:
    """Reject category/search redirects which otherwise look like valid pages."""
    return response.status_code == 200 and bool(
        BeautifulSoup(response.content, "html.parser").find("h1", id="detail-app-name")
    )


def get_latest_version(app_name: str, config: dict) -> str | None:
    for slug in generate_possible_uptodown_names(config):
        url = f"https://{slug}.en.uptodown.com/android/versions"
        try:
            response = session.get(url, timeout=20)
            if not _page_is_app(response):
                continue
            soup = BeautifulSoup(response.content, "html.parser")
            versions = [item.get_text(strip=True) for item in soup.select("#versions-items-list .version")]
            versions = [item for item in versions if item]
            if versions:
                # The API/page lists newest first. Do not use max() here: that
                # compares strings and incorrectly ranks 9.x above 10.x.
                logging.info("Uptodown: %s latest version is %s", app_name, versions[0])
                return versions[0]
        except Exception as exc:
            logging.debug("Uptodown latest-version probe failed for %s: %s", slug, exc)
    logging.warning("Uptodown: no app page found for %s", app_name)
    return None


def _direct_url_from_page(soup: BeautifulSoup, page_url: str) -> str | None:
    button = soup.find(id="detail-download-button")
    if not button:
        return None

    direct = button.get("data-url")
    if direct and direct != "apps":
        return urljoin("https://dw.uptodown.com/dwn/", direct)

    # Some older pages use an anchor rather than a button.
    for link in soup.select("a#detail-download-button[href], a.download[href]"):
        href = link.get("href")
        if href and ("dw.uptodown.com" in href or href.endswith((".apk", ".xapk"))):
            return urljoin(page_url, href)
    return None


def get_download_link(version: str, app_name: str, config: dict) -> str | None:
    if not version:
        return None

    for slug in generate_possible_uptodown_names(config):
        base_url = f"https://{slug}.en.uptodown.com/android"
        try:
            listing = session.get(f"{base_url}/versions", timeout=20)
            if not _page_is_app(listing):
                continue
            heading = BeautifulSoup(listing.content, "html.parser").find("h1", id="detail-app-name")
            data_code = heading.get("data-code") if heading else None
            if not data_code:
                continue

            for page in range(1, 11):
                response = session.get(f"{base_url}/apps/{data_code}/versions/{page}", timeout=20)
                response.raise_for_status()
                entries = (response.json() or {}).get("data") or []
                if not entries:
                    break

                for entry in entries:
                    if not _same_version(entry.get("version", ""), version):
                        continue
                    parts = entry.get("versionURL") or {}
                    version_url = "/".join(
                        str(parts.get(key, "")).strip("/")
                        for key in ("url", "extraURL", "versionID")
                    )
                    if not version_url.startswith("http"):
                        continue
                    page_response = session.get(version_url, timeout=20)
                    page_response.raise_for_status()
                    link = _direct_url_from_page(
                        BeautifulSoup(page_response.content, "html.parser"), page_response.url
                    )
                    if link:
                        return link

                    # This is a provider-side access requirement, not a bad slug
                    # or a parsing mismatch.  Do not pretend a URL exists.
                    logging.info(
                        "Uptodown requires an interactive download token for %s %s; trying next provider",
                        app_name,
                        version,
                    )
                    return None

                target = _normalise_version(version)
                if target and all(_normalise_version(item.get("version", "")) < target for item in entries):
                    break
        except Exception as exc:
            logging.debug("Uptodown download-link probe failed for %s: %s", slug, exc)
    logging.warning("Uptodown: version %s was not found for %s", version, app_name)
    return None


def generate_possible_uptodown_names(config: dict) -> list[str]:
    """Return deterministic candidate slugs; prefer an explicit platform slug."""
    name = (config.get("slug") or config.get("name") or "").strip().lower()
    package = (config.get("package") or "").strip().lower()
    candidates = [name]
    if name:
        candidates.extend([name.replace("-", ""), name.replace("-", "_")])
    if package:
        candidates.extend([package.replace(".", "-"), package.split(".")[-1]])
    return list(dict.fromkeys(candidate for candidate in candidates if len(candidate) > 1))
