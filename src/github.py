import os
import re
import logging
from src import session

def _get_headers():
    headers = {}
    if "GITHUB_TOKEN" in os.environ:
        headers["Authorization"] = f"Bearer {os.environ['GITHUB_TOKEN']}"
    return headers

def get_latest_version(app_name: str, config: dict) -> str | None:
    repo = config.get("repo")
    tag = config.get("tag")
    if not repo or not tag:
        logging.error(f"Missing 'repo' or 'tag' in github config for {app_name}")
        return None
    
    # Use /releases/latest for "latest" tag, otherwise use /releases/tags/{tag}
    if tag.lower() == "latest":
        url = f"https://api.github.com/repos/{repo}/releases/latest"
    else:
        url = f"https://api.github.com/repos/{repo}/releases/tags/{tag}"
    
    try:
        response = session.get(url, headers=_get_headers())
        if response.status_code == 200:
            data = response.json()
            versions = []
            for asset in data.get("assets", []):
                name = asset.get("name", "")
                # Extract version from something like com.instagram.android-426.0.0.37.68-arm64-v8a.apkm
                # Match digits and dots after hyphen
                m = re.search(r"-([\d\.]+)-", name)
                if m:
                    versions.append(m.group(1).strip("."))
                else:
                    # Fallback try generic version regex
                    m = re.search(r"([\d\.]+)", name)
                    if m:
                        versions.append(m.group(1).strip("."))
                        
            if versions:
                # Sort numerically
                versions.sort(key=lambda x: [int(p) for p in x.split('.') if p.isdigit()])
                logging.info(f"Latest version found on GitHub for {app_name}: {versions[-1]}")
                return versions[-1]
                
        elif response.status_code == 404:
            logging.debug(f"GitHub release not found for {url}")
        else:
            response.raise_for_status()
            
    except Exception as e:
        logging.error(f"Failed to fetch GitHub release for {app_name}: {e}")
    return None

def get_download_link(version: str, app_name: str, config: dict) -> str | None:
    repo = config.get("repo")
    tag = config.get("tag")
    if not repo or not tag:
        return None
    
    # Use /releases/latest for "latest" tag, otherwise use /releases/tags/{tag}
    if tag.lower() == "latest":
        url = f"https://api.github.com/repos/{repo}/releases/latest"
    else:
        url = f"https://api.github.com/repos/{repo}/releases/tags/{tag}"
        
    try:
        response = session.get(url, headers=_get_headers())
        if response.status_code == 200:
            data = response.json()
            arch = config.get("arch", "arm64-v8a").lower()
            
            # Normalize arch for filename matching
            arch_patterns = []
            if arch in ("all", "both", "universal"):
                arch_patterns = [""]  # Match any
            elif "arm64" in arch:
                arch_patterns = ["arm64"]
            elif "armeabi-v7a" in arch or "armv7" in arch:
                arch_patterns = ["armeabi", "v7", "32"]
            elif "x86_64" in arch:
                arch_patterns = ["x86_64", "x64"]
            elif "x86" in arch:
                arch_patterns = ["x86"]
            
            for asset in data.get("assets", []):
                name = asset.get("name", "").lower()
                # Check version and extension
                if version in name and name.endswith((".apk", ".apkm", ".xapk")):
                    # Check architecture match if arch is specified
                    if not arch_patterns or any(p in name for p in arch_patterns):
                        logging.info(f"Found GitHub download link for {app_name} {version}")
                        return asset.get("browser_download_url")
                        
            # If explicit arch failed, try to fallback to first matched version available
            for asset in data.get("assets", []):
                name = asset.get("name", "").lower()
                if version in name and name.endswith((".apk", ".apkm", ".xapk")):
                    logging.info(f"Fallback arch: Found GitHub download link for {app_name} {version}")
                    return asset.get("browser_download_url")
            
            # If version not found in filenames, try matching by architecture only
            # (for releases where version isn't in asset name, like Brave)
            # Prioritize: mono > bundle > universal
            if arch_patterns:  # Only if arch was specified
                preferred_assets = []
                for asset in data.get("assets", []):
                    name = asset.get("name", "").lower()
                    if name.endswith((".apk", ".apkm", ".xapk")) and any(p in name for p in arch_patterns):
                        # Score for preference: higher = better
                        score = 0
                        if "mono" in name:
                            score = 3
                        elif "bundle" in name:
                            score = 2
                        elif "universal" in name:
                            score = 1
                        preferred_assets.append((score, name, asset))
                
                if preferred_assets:
                    # Sort by score descending, then by name for consistency
                    preferred_assets.sort(key=lambda x: (-x[0], x[1]))
                    best_asset = preferred_assets[0][2]
                    logging.info(f"Matched GitHub asset by arch only for {app_name} {version}: {best_asset.get('name')}")
                    return best_asset.get("browser_download_url")
            
            # Last resort: just grab first APK-like asset
            for asset in data.get("assets", []):
                name = asset.get("name", "").lower()
                if name.endswith((".apk", ".apkm", ".xapk")):
                    logging.info(f"Using first available APK asset for {app_name} {version}: {name}")
                    return asset.get("browser_download_url")
                    
    except Exception as e:
        logging.error(f"Failed to get GitHub download link for {app_name}: {e}")
        
    return None
