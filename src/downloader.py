import json
import logging
import subprocess
import re
from pathlib import Path
from src import (
    utils,
    apkpure,
    session,
    uptodown,
    apkmirror
)

def download_resource(url: str, name: str = None) -> Path:
    with session.get(url, stream=True) as res:
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

    name = repos_info[0]["name"]
    downloaded_files = []

    for repo_info in repos_info[1:]:
        user = repo_info['user']
        repo = repo_info['repo']
        tag = repo_info['tag']

        release = utils.detect_github_release(user, repo, tag)
        for asset in release["assets"]:
            if asset["name"].endswith(".asc"):
                continue
            filepath = download_resource(asset["browser_download_url"])
            downloaded_files.append(filepath)

    return downloaded_files, name

def get_smart_version(package: str, cli: Path, patches: Path) -> str | None:
    """
    Locally determines the supported version, handling the syntax difference
    between ReVanced CLI v4 and v5.
    """
    try:
        # Detect if using CLI v5 based on filename (common convention)
        is_cli_v5 = "cli-5" in str(cli.name) or "cli-v5" in str(cli.name)
        
        cmd = ["java", "-jar", str(cli), "list-versions"]
        
        if is_cli_v5:
            # CLI v5: Patches file MUST come before flags
            cmd.extend([str(patches), "-f", package])
        else:
            # CLI v4: Flags can come before patches
            cmd.extend(["-f", package, str(patches)])

        # Run the command and capture output
        result = subprocess.run(
            cmd, 
            capture_output=True, 
            text=True, 
            check=True
        )
        
        # The output usually contains the version on the last non-empty line
        output_lines = [line.strip() for line in result.stdout.splitlines() if line.strip()]
        if output_lines:
            return output_lines[-1]
            
    except subprocess.CalledProcessError as e:
        logging.warning(f"Version detection failed: {e}")
        logging.debug(f"Command output: {e.stderr}")
    except Exception as e:
        logging.warning(f"Error checking version: {e}")
        
    return None

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

        # Priority: 
        # 1. Hardcoded in config
        # 2. Detected via CLI (using local smart function instead of utils.py)
        # 3. Latest from platform
        version = config.get("version")
        
        if not version:
            logging.info("Auto-detecting supported version...")
            version = get_smart_version(config['package'], cli, patches)
            if version:
                logging.info(f"Detected supported version: {version}")

        platform_module = globals()[platform]
        version = version or platform_module.get_latest_version(app_name, config)
        
        download_link = platform_module.get_download_link(version, app_name, config)
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

def download_uptodown(app_name: str, cli: str, patches: str, arch: str = None) -> tuple[Path | None, str | None]:
    return download_platform(app_name, "uptodown", cli, patches, arch)

def download_apkeditor() -> Path:
    release = utils.detect_github_release("REAndroid", "APKEditor", "latest")

    for asset in release["assets"]:
        if asset["name"].startswith("APKEditor") and asset["name"].endswith(".jar"):
            return download_resource(asset["browser_download_url"])

    raise RuntimeError("APKEditor .jar file not found in the latest release")
