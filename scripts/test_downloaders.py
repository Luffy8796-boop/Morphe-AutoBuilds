#!/usr/bin/env python3
"""Exercise store scrapers without downloading patch tools or running a patch.

Examples:
    python scripts/test_downloaders.py --app pinterest
    python scripts/test_downloaders.py --app pinterest --download
    python scripts/test_downloaders.py --download --require-one

``--download`` downloads each resolved file into a temporary directory and
checks its ZIP/APK structure.  It can be bandwidth-heavy; start with one app.
"""

from __future__ import annotations

import argparse
import json
import logging
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from src import apkmirror, apkpure, aptoide, downloader, github, uptodown  # noqa: E402

PLATFORMS = {
    "apkmirror": apkmirror,
    "aptoide": aptoide,
    "github": github,
    "uptodown": uptodown,
    "apkpure": apkpure,
}


def app_names(requested: list[str]) -> list[str]:
    if requested:
        return requested
    config = json.loads((ROOT / "patch-config.json").read_text(encoding="utf-8"))
    return [entry["app_name"] for entry in config["patch_list"]]


def check_one(app: str, platform: str, download: bool, temp_dir: Path) -> bool | None:
    config_file = ROOT / "apps" / platform / f"{app}.json"
    if not config_file.exists():
        return None
    config = json.loads(config_file.read_text(encoding="utf-8"))
    module = PLATFORMS[platform]
    version = (config.get("version") or "").strip()
    try:
        version = version or module.get_latest_version(app, config)
        link = module.get_download_link(version, app, config) if version else None
    except Exception as exc:
        print(f"FAIL  {app:<22} {platform:<10} resolver error: {exc}")
        return False
    if not link or not link.startswith(("http://", "https://")):
        print(f"FAIL  {app:<22} {platform:<10} version={version!r} no direct URL")
        return False
    if not download:
        print(f"PASS  {app:<22} {platform:<10} version={version} {link}")
        return True
    try:
        target = temp_dir / f"{app}-{platform}.apk"
        artifact = downloader.download_resource(link, str(target), validate_apk=True)
        print(f"PASS  {app:<22} {platform:<10} version={version} {artifact.stat().st_size} bytes")
        return True
    except Exception as exc:
        print(f"FAIL  {app:<22} {platform:<10} download validation: {exc}")
        return False


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--app", action="append", default=[], help="app name; may be repeated")
    parser.add_argument("--platform", choices=PLATFORMS, action="append", default=[])
    parser.add_argument("--download", action="store_true", help="download and validate each resolved archive")
    parser.add_argument("--strict", action="store_true", help="fail if any configured provider has no direct URL")
    parser.add_argument("--require-one", action="store_true", help="fail only when an app has no working provider")
    args = parser.parse_args()
    logging.getLogger().setLevel(logging.WARNING)
    platforms = args.platform or list(PLATFORMS)
    failures = 0
    with tempfile.TemporaryDirectory(prefix="morphe-downloader-test-") as directory:
        temp_dir = Path(directory)
        for app in app_names(args.app):
            results = [check_one(app, platform, args.download, temp_dir) for platform in platforms]
            configured = [result for result in results if result is not None]
            if args.strict:
                failures += sum(result is False for result in configured)
            elif args.require_one and configured and not any(configured):
                failures += 1
    return 1 if failures else 0


if __name__ == "__main__":
    raise SystemExit(main())
