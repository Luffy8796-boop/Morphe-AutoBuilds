import re
import logging
import time
import random
import cloudscraper
from bs4 import BeautifulSoup

APKMIRROR_BASE = "https://www.apkmirror.com"

logging.basicConfig(level=logging.DEBUG, format="%(asctime)s %(levelname)s: %(message)s")

def create_scraper_session(proxy_url=None):
    scraper = cloudscraper.create_scraper(browser={'browser': 'chrome', 'platform': 'windows', 'mobile': False})
    scraper.headers.update({
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/122.0.0.0 Safari/537.36",
        "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,image/avif,image/webp,image/apng,*/*;q=0.8,application/signed-exchange;v=b3;q=0.7",
        "Accept-Language": "en-US,en;q=0.9",
        "Accept-Encoding": "gzip, deflate, br",
        "Referer": "https://www.apkmirror.com/",
        "Connection": "keep-alive",
        "Upgrade-Insecure-Requests": "1",
        "Sec-Fetch-Dest": "document",
        "Sec-Fetch-Mode": "navigate",
        "Sec-Fetch-Site": "same-origin",
        "Sec-Fetch-User": "?1",
    })
    if proxy_url:
        scraper.proxies = {"http": proxy_url, "https": proxy_url}
    return scraper

def get_download_link(version: str, app_name: str, config: dict, arch: str = None, scraper=None) -> str:
    if scraper is None:
        scraper = create_scraper_session()

    target_arch = arch if arch else config.get('arch', 'universal')
    criteria = [target_arch.lower(), config['dpi'].lower()]
    if 'type' in config and config['type']:
        criteria.append(config['type'].lower())

    found_soup = None
    correct_version_page = False

    # === 1. DIRECT EXACT RELEASE PAGE (fastest & most reliable) ===
    release_name = config.get('release_prefix', config['name'])
    direct_url = f"{APKMIRROR_BASE}/apk/{config['org']}/{config['name']}/{release_name}-{version.replace('.', '-')}-release/"
    logging.info(f"Trying direct specific release URL: {direct_url}")
    time.sleep(2 + random.random())

    try:
        response = scraper.get(direct_url)
        response.encoding = 'utf-8'
        if response.status_code == 200:
            soup = BeautifulSoup(response.text, "html.parser")
            title_text = soup.find('title').get_text().lower() if soup.find('title') else ""
            if version.lower() in title_text or version.replace('.', '-').lower() in title_text:
                logging.info(f"✓ Loaded exact release page directly: {direct_url}")
                found_soup = soup
                correct_version_page = True
    except Exception as e:
        logging.warning(f"Direct URL attempt failed: {e}")

    # === 2. FALLBACK: Original pattern loop (with fixed scoping) ===
    if not correct_version_page:
        logging.info("Direct URL failed, falling back to pattern search")
        version_parts = version.split('.')
        release_name = config.get('release_prefix', config['name'])
        
        for i in range(len(version_parts), 0, -1):
            current_ver_str = "-".join(version_parts[:i])
            
            url_patterns = [
                f"{APKMIRROR_BASE}/apk/{config['org']}/{config['name']}/{release_name}-{current_ver_str}-release/",
                f"{APKMIRROR_BASE}/apk/{config['org']}/{config['name']}/{config['name']}-{current_ver_str}-release/" if release_name != config['name'] else None,
                f"{APKMIRROR_BASE}/apk/{config['org']}/{config['name']}/{release_name}-{current_ver_str}/",
                f"{APKMIRROR_BASE}/apk/{config['org']}/{config['name']}/{config['name']}-{current_ver_str}/" if release_name != config['name'] else None,
            ]
            url_patterns = [u for u in url_patterns if u]
            url_patterns = list(dict.fromkeys(url_patterns))
            
            for url in url_patterns:
                logging.info(f"Checking potential release URL: {url}")
                time.sleep(2 + random.random())
                
                try:
                    response = scraper.get(url)
                    response.encoding = 'utf-8'
                    if response.status_code == 200:
                        soup = BeautifulSoup(response.text, "html.parser")
                        page_text = soup.get_text().lower()
                        title_text = soup.find('title').get_text().lower() if soup.find('title') else ""
                        heading_texts = [h.get_text().lower() for h in soup.find_all(['h1', 'h2', 'h3'])]
                        
                        full_checks = [version.lower(), version.replace('.', '-').lower()]
                        sources = [page_text, title_text] + heading_texts
                        
                        is_correct_page = any(check in src for src in sources for check in full_checks)
                        
                        # Force accept if URL itself contains the full version (very reliable)
                        if not is_correct_page and version.replace('.', '-').lower() in url.lower():
                            is_correct_page = True
                            logging.info(f"Forcing acceptance based on URL containing exact version: {url}")
                        
                        partial_checks = [current_ver_str.lower(), ".".join(version_parts[:i]).lower()]  # ALWAYS defined
                        
                        if is_correct_page:
                            logging.info(f"✓ Correct version page found: {response.url}")
                            found_soup = soup
                            correct_version_page = True
                            break
                        else:
                            logging.warning(f"Page found but not for version {version}: {url}")
                            if found_soup is None:
                                found_soup = soup
                except Exception as e:
                    logging.warning(f"Error checking {url}: {e}")
            
            if correct_version_page:
                break

    if not found_soup:
        logging.error(f"Could not find any release page for {app_name} {version}")
        return None

    # === VARIANT FINDER - Extremely robust (table + link search) ===
    rows = found_soup.find_all('div', class_='table-row')
    download_page_url = None

    logging.info(f"Scanning {len(rows)} variant rows for {target_arch} / {config['dpi']}")

    for row in rows:
        row_text = row.get_text().lower()
        if (version.lower() in row_text or version.replace('.', '-').lower() in row_text):
            if all(c in row_text for c in criteria):
                link = row.find('a', class_='accent_color') or row.find('a', href=True)
                if link and 'apk-download' in link.get('href', ''):
                    download_page_url = APKMIRROR_BASE + link['href']
                    logging.info(f"Found matching variant: {download_page_url}")
                    break

    # Super-fallback: search every link on the page
    if not download_page_url:
        for link in found_soup.find_all('a', href=True):
            href = link['href'].lower()
            if 'apk-download' in href and (target_arch.lower() in href or config['dpi'].lower() in href):
                if version.replace('.', '-').lower() in href:
                    download_page_url = APKMIRROR_BASE + link['href']
                    logging.info(f"Found variant via full link search: {download_page_url}")
                    break

    if not download_page_url:
        logging.error(f"No variant found for {app_name} {version} with criteria {criteria}")
        for idx, row in enumerate(rows[:10]):
            logging.debug(f"Row {idx}: {row.get_text()[:200]}...")
        return None

    # === FINAL DOWNLOAD FLOW ===
    try:
        time.sleep(2 + random.random())
        response = scraper.get(download_page_url)
        response.encoding = 'utf-8'
        response.raise_for_status()
        soup = BeautifulSoup(response.text, "html.parser")
        btn = soup.find('a', class_='downloadButton') or soup.find('a', href=lambda h: h and 'forcebaseapk' in h)
        if btn:
            final_url = APKMIRROR_BASE + btn['href']
            logging.info(f"Final APK URL: {final_url}")
            return final_url
    except Exception as e:
        logging.error(f"Download flow error: {e}")

    return None

def get_architecture_criteria(arch: str) -> dict:
    return {
        "arm64-v8a": "arm64-v8a",
        "armeabi-v7a": "armeabi-v7a",
        "universal": "universal"
    }.get(arch, "universal")

def get_latest_version(app_name: str, config: dict, scraper=None) -> str:
    if scraper is None:
        scraper = create_scraper_session()
    url = f"{APKMIRROR_BASE}/uploads/?appcategory={config['name']}"
    time.sleep(2 + random.random())
    response = scraper.get(url)
    response.encoding = 'utf-8'
    response.raise_for_status()
    soup = BeautifulSoup(response.text, "html.parser")
    for row in soup.find_all("div", class_="appRow"):
        version_text = row.find("h5", class_="appRowTitle").a.text.strip()
        if "alpha" not in version_text.lower() and "beta" not in version_text.lower():
            match = re.search(r'\d+(\.\d+)+', version_text)
            if match:
                return match.group()
    return None
