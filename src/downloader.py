import json
import logging
from pathlib import Path
from src import (
    utils,
    apkpure,
    session,
    uptodown,
    aptoide,
    apkmirror
)

def download_resource(url: str, name: str = None) -> Path:
    res = session.get(url, stream=True)
    res.raise_for_status()
    final_url = res.url

    if not name:
        name = utils.extract_filename(res, fallback_url=final_url)

    filepath = Path(name)
    total_size = int(res.headers.get('content-length', 0))
    downloaded_size = 0

    with filepath.open("wb") as file:
        for chunk in res.iter_content(chunk_size=8192):
            if chunk:
                file.write(chunk)
                downloaded_size += len(chunk)

    logging.info(
        f"URL: {final_url} [{downloaded_size}/{total_size}] -> \"{filepath}\" [1]"
    )

    return filepath

def download_required(source: str) -> tuple[list[Path], str]:
    source_path = Path("sources") / f"{source}.json"
    with source_path.open() as json_file:
        repos_info = json.load(json_file)

    # Handle bundle format
    if isinstance(repos_info, dict) and "bundle_url" in repos_info:
        return download_from_bundle(repos_info)    
    
    # Handle old list format
    name = repos_info[0]["name"]
    downloaded_files = []

    for repo_info in repos_info[1:]:

        if "bundle" in repo_info:
            logging.info(f"Downloading bundled patch from: {repo_info['bundle']}")
            bundle_file = download_resource(repo_info["bundle"])
            downloaded_files.append(bundle_file)
            continue
        
        user = repo_info['user']
        repo = repo_info['repo']
        tag = repo_info['tag']

        release = utils.detect_github_release(user, repo, tag)
        
        # Special handling for Morphe files
        if repo == "morphe-patches" or repo == "morphe-cli":
            for asset in release["assets"]:
                if asset["name"].endswith(".asc"):
                    continue
                # Download .mpp patches or morphe-cli.jar
                if asset["name"].endswith(".mpp") or ("morphe-cli" in asset["name"] and asset["name"].endswith(".jar")):
                    filepath = download_resource(asset["browser_download_url"])
                    downloaded_files.append(filepath)
        else:
            # Original logic for ReVanced files
            for asset in release["assets"]:
                if asset["name"].endswith(".asc"):
                    continue
                filepath = download_resource(asset["browser_download_url"])
                downloaded_files.append(filepath)

    return downloaded_files, name

def download_from_bundle(bundle_info: dict) -> tuple[list[Path], str]:
    """Download resources from a bundle URL"""
    bundle_url = bundle_info["bundle_url"]
    name = bundle_info.get("name", "bundle-patches")
    
    logging.info(f"Downloading bundle from {bundle_url}")
    
    # Download the bundle JSON
    with session.get(bundle_url) as res:
        res.raise_for_status()
        bundle_data = res.json()
    
    downloaded_files = []
    
    # Check API version and structure
    if "patches" in bundle_data:
        # API v4 format
        patches = bundle_data.get("patches", [])
        integrations = bundle_data.get("integrations", [])
        
        # Download patches (JAR files)
        for patch in patches:
            if "url" in patch:
                filepath = download_resource(patch["url"])
                downloaded_files.append(filepath)
                logging.info(f"Downloaded patch: {patch.get('name', 'unknown')}")
        
        # Download integrations (APK files)
        for integration in integrations:
            if "url" in integration:
                filepath = download_resource(integration["url"])
                downloaded_files.append(filepath)
                logging.info(f"Downloaded integration: {integration.get('name', 'unknown')}")
    
    # Also download CLI (still needed) - try ReVanced CLI first
    try:
        cli_release = utils.detect_github_release("revanced", "revanced-cli", "latest")
        for asset in cli_release["assets"]:
            if asset["name"].endswith(".asc"):
                continue
            if asset["name"].endswith(".jar") and "cli" in asset["name"].lower():
                filepath = download_resource(asset["browser_download_url"])
                downloaded_files.append(filepath)
                logging.info("Downloaded ReVanced CLI")
                break
    except Exception as e:
        logging.warning(f"Could not download ReVanced CLI: {e}")
    
    return downloaded_files, name

def download_platform(app_name: str, platform: str, cli: str, patches: str, arch: str = None) -> tuple[Path | None, str | None]:
    try:
        config_path = Path("apps") / platform / f"{app_name}.json"
        if not config_path.exists():
            raise FileNotFoundError(f"Config file not found: {config_path}")

        with config_path.open() as json_file:
            config = json.load(json_file)
        
        # Override arch if specified
        if arch:
            config['arch'] = arch

        version = config.get("version") or utils.get_supported_version(config['package'], cli, patches)
        platform_module = globals()[platform]
        version = version or platform_module.get_latest_version(app_name, config)
        
        download_link = platform_module.get_download_link(version, app_name, config)
        if not download_link:
            raise ValueError(f"No download link found for {app_name} version {version}")
            
        filepath = download_resource(download_link)
        return filepath, version 

    except Exception as e:
        logging.error(f"Unexpected error: {e}")
        return None, None

# Update the specific download functions
def download_apkmirror(app_name: str, cli: str, patches: str, arch: str = None) -> tuple[Path | None, str | None]:
    return download_platform(app_name, "apkmirror", cli, patches, arch)

def download_apkpure(app_name: str, cli: str, patches: str, arch: str = None) -> tuple[Path | None, str | None]:
    return download_platform(app_name, "apkpure", cli, patches, arch)

def download_aptoide(app_name: str, cli: str, patches: str, arch: str = None) -> tuple[Path | None, str | None]:
    return download_platform(app_name, "aptoide", cli, patches, arch)

def download_uptodown(app_name: str, cli: str, patches: str, arch: str = None) -> tuple[Path | None, str | None]:
    return download_platform(app_name, "uptodown", cli, patches, arch)

def download_apkeditor() -> Path:
    release = utils.detect_github_release("REAndroid", "APKEditor", "latest")

    for asset in release["assets"]:
        if asset["name"].startswith("APKEditor") and asset["name"].endswith(".jar"):
            return download_resource(asset["browser_download_url"])

    raise RuntimeError("APKEditor .jar file not found in the latest release")
# Add these functions inside src/downloader.py

def detect_gitlab_latest_release_asset(project_id: str, asset_pattern: str = ".mpp") -> str:
    """Get the direct download URL of the latest release asset from a GitLab project.
    
    Args:
        project_id: URL-encoded GitLab project ID (e.g., 'Paresh-Maheshwari%2Fparesh-patches')
        asset_pattern: File extension to look for in release assets
    
    Returns:
        Direct download URL of the matching asset
    """
    import requests
    
    api_url = f"https://gitlab.com/api/v4/projects/{project_id}/releases/permalink/latest"
    
    try:
        response = requests.get(api_url)
        response.raise_for_status()
        release_data = response.json()
        
        # Look for asset links
        assets = release_data.get('assets', {}).get('links', [])
        for asset in assets:
            if asset.get('name', '').endswith(asset_pattern):
                return asset.get('direct_asset_url')
        
        # If no matching asset found, raise error
        raise ValueError(f"No asset matching pattern '{asset_pattern}' found in latest release")
        
    except Exception as e:
        logging.error(f"Failed to get latest GitLab release for {project_id}: {e}")
        raise


def download_gitlab_release_asset(project_id: str, asset_pattern: str = ".mpp") -> Path:
    """Download a specific asset from the latest GitLab release.
    
    Args:
        project_id: URL-encoded GitLab project ID
        asset_pattern: File extension to look for
    Returns:
        Path object pointing to the downloaded file
    """
    direct_url = detect_gitlab_latest_release_asset(project_id, asset_pattern)
    logging.info(f"Downloading GitLab release asset from: {direct_url}")
    return download_resource(direct_url)
