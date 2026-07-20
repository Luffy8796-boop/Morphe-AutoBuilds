import logging
import re
from urllib.parse import urljoin

from src import session
from bs4 import BeautifulSoup

HEADERS = {
    'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36',
    'Accept-Language': 'en-US,en;q=0.9',
    'Referer': 'https://apkpure.net/'
}


def _parse_download_links(html: str) -> list[str]:
    soup = BeautifulSoup(html, "html.parser")
    links = []

    for tag in soup.find_all(['a', 'button', 'link']):
        href = tag.get('href') or tag.get('data-url') or tag.get('data-href')
        if href:
            links.append(href)

    for attr in ['data-dt-apkid', 'data-apkid', 'data-package-name', 'data-dt-package-name']:
        for tag in soup.find_all(attrs={attr: True}):
            value = tag.get(attr)
            if value and isinstance(value, str):
                links.append(value)

    return links


def _extract_direct_download_url(html: str) -> str | None:
    patterns = [
        r'https://d\.apkpure\.net/[^\s"\']+',
        r'https://download\.apkpure\.com/[^\s"\']+',
        r'https://[^\s"\']+\.apkpure\.net/[^\s"\']+',
        r'https://[^\s"\']+/apk-downloader[^\s"\']*',
    ]

    for pattern in patterns:
        match = re.search(pattern, html, re.IGNORECASE)
        if match:
            return match.group(0)

    return None


def get_latest_version(app_name: str, config: str) -> str:
    url = f"https://apkpure.net/{config['name']}/{config['package']}/versions"

    try:
        response = session.get(url, headers=HEADERS)
        response.raise_for_status()

        content_size = len(response.content)
        logging.info(f"URL:{response.url} [{content_size}/{content_size}] -> \"-\" [1]")

        soup = BeautifulSoup(response.content, "html.parser")
        version_info = soup.find('div', class_='ver-top-down')
        if version_info and 'data-dt-version' in version_info.attrs:
            return version_info['data-dt-version']

    except Exception as e:
        logging.error(f"Failed to fetch latest version for {app_name}: {e}")

    return None


def get_download_link(version: str, app_name: str, config: str) -> str:
    url = f"https://apkpure.net/{config['name']}/{config['package']}/download/{version}"

    try:
        response = session.get(url, headers=HEADERS)
        response.raise_for_status()

        content_size = len(response.content)
        logging.info(f"URL:{response.url} [{content_size}/{content_size}] -> \"-\" [1]")

        html = response.text
        direct_url = _extract_direct_download_url(html)
        if direct_url:
            return direct_url

        for href in _parse_download_links(html):
            if href.startswith('http'):
                if 'apkpure' in href.lower() and ('download' in href.lower() or 'd.apkpure' in href.lower()):
                    return href
            elif href.startswith('/'):
                return urljoin(response.url, href)

    except Exception as e:
        logging.error(f"Failed to fetch download link for {app_name} v{version}: {e}")

    return None
