import re
import logging
import time
import random
import cloudscraper
from bs4 import BeautifulSoup

# Base URL for APKMirror
APKMIRROR_BASE = "https://www.apkmirror.com"

# Configure logging
logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s: %(message)s")

def get_download_link(version: str, app_name: str, config: dict, arch: str = None) -> str:
    scraper = cloudscraper.create_scraper()
    target_arch = arch if arch else config.get('arch', 'universal')

    # Step 1: Construct and load the release page
    release_name = config.get('release_prefix', config['name'])
    version_dash = version.replace('.', '-')
    release_url = f"{APKMIRROR_BASE}/apk/{config['org']}/{config['name']}/{release_name}-{version_dash}-release/"
    logging.info(f"Checking release URL: {release_url}")
    time.sleep(2 + random.random())
    response = scraper.get(release_url)
    response.encoding = 'utf-8'
    if response.status_code != 200:
        logging.error(f"Release URL failed: {response.status_code}")
        return None
    soup = BeautifulSoup(response.text, "html.parser")

    # Step 2: Find variant link for arch (new approach from project)
    variant_url = None
    variant_map = {
        "arm64-v8a": "3",
        "armeabi-v7a": "4",
        "universal": "3"
    }
    suffix = variant_map.get(target_arch, "3")
    variant_href = f"{release_name}-{version_dash}-{suffix}-android-apk-download/"
    for a in soup.find_all('a', href=True):
        if variant_href in a['href']:
            variant_url = APKMIRROR_BASE + a['href']
            logging.info(f"Found variant URL: {variant_url}")
            break
    if not variant_url:
        logging.error("No variant found")
        return None

    # Step 3: Load variant page and extract final download link with key (adapted from project)
    time.sleep(2 + random.random())
    response = scraper.get(variant_url)
    response.encoding = 'utf-8'
    if response.status_code != 200:
        logging.error(f"Variant URL failed: {response.status_code}")
        return None
    soup = BeautifulSoup(response.text, "html.parser")

    final_url = None
    for a in soup.find_all('a', href=True):
        href = a['href']
        if 'forcebaseapk=true' in href and 'key=' in href:
            final_url = APKMIRROR_BASE + href
            logging.info(f"Found final download URL: {final_url}")
            break
    if not final_url:
        logging.error("No final download link found")
        return None

    return final_url

def get_architecture_criteria(arch: str) -> dict:
    arch_mapping = {
        "arm64-v8a": "arm64-v8a",
        "armeabi-v7a": "armeabi-v7a",
        "universal": "universal"
    }
    return arch_mapping.get(arch, "universal")

def get_latest_version(app_name: str, config: dict) -> str:
    scraper = cloudscraper.create_scraper()
    url = f"{APKMIRROR_BASE}/uploads/?appcategory={config['name']}"
    time.sleep(2 + random.random())
    response = scraper.get(url)
    response.encoding = 'utf-8'
    if response.status_code != 200:
        logging.error(f"Latest version URL failed: {response.status_code}")
        return None
    soup = BeautifulSoup(response.text, "html.parser")
    app_rows = soup.find_all("div", class_="appRow")
    version_pattern = re.compile(r'\d+(\.\d+)+')
    for row in app_rows:
        title = row.find("h5", class_="appRowTitle").a.text.strip()
        if "alpha" not in title.lower() and "beta" not in title.lower():
            match = version_pattern.search(title)
            if match:
                return match.group()
    return None
