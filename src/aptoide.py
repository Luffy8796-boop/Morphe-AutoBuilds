import base64
import logging
import re
from typing import Optional

from src import session, utils

BASE_URL = "https://ws75.aptoide.com/api/7/"


def _safe_get_json(url: str) -> Optional[dict]:
    try:
        response = session.get(url, timeout=20)
        response.raise_for_status()
        return response.json()
    except Exception as exc:
        logging.debug("Aptoide request failed (%s): %s", url, exc)
        return None


def _items(payload: dict | None) -> list[dict]:
    if not payload:
        return []
    return payload.get("list") or (payload.get("datalist") or {}).get("list") or []


def _versions(package: str, query: str) -> list[dict]:
    payload = _safe_get_json(f"{BASE_URL}listAppVersions?package_name={package}&limit=100{query}")
    return [item for item in _items(payload) if item.get("package") == package]


def _same_version(left: str, right: str) -> bool:
    clean = lambda value: re.sub(r"[\(\[].*?[\)\]]", "", value or "").strip()
    return left == right or clean(left) == clean(right) or utils.normalize_version(left) == utils.normalize_version(right)


def get_latest_version(app_name: str, config: dict) -> str | None:
    package = (config.get("package") or "").strip()
    if not package:
        return None
    query = _get_q_param(config.get("arch", "universal"))
    versions = _versions(package, query)
    if versions:
        return versions[0].get("file", {}).get("vername")

    # search is fuzzy: never use its first result unless the package is exact.
    payload = _safe_get_json(f"{BASE_URL}apps/search?query={package}&limit=25&trusted=true{query}")
    for item in _items(payload):
        if item.get("package") == package:
            return item.get("file", {}).get("vername")
    logging.warning("Aptoide: no exact result for %s", package)
    return None


def get_download_link(version: str, app_name: str, config: dict) -> str | None:
    package = (config.get("package") or "").strip()
    if not package:
        return None
    query = _get_q_param(config.get("arch", "universal"))
    versions = _versions(package, query)
    selected = None
    for item in versions:
        candidate = item.get("file", {}).get("vername", "")
        if version and version.lower() != "latest" and _same_version(candidate, version):
            selected = item
            break
    if selected is None and version and version.lower() != "latest":
        logging.warning("Aptoide: %s is not available for %s", version, package)
        return None
    if selected is None and versions:
        selected = versions[0]
    if selected is None:
        return None

    file_info = selected.get("file") or {}
    vercode = file_info.get("vercode")
    if not vercode:
        return None
    metadata = _safe_get_json(f"{BASE_URL}getAppMeta?package_name={package}&vercode={vercode}{query}")
    path = ((metadata or {}).get("data") or {}).get("file", {}).get("path")
    if path and path.startswith("https://"):
        return path
    logging.warning("Aptoide metadata has no downloadable file for %s@%s", package, vercode)
    return None


def _get_q_param(arch: str) -> str:
    if arch == "universal":
        return ""
    cpu = {
        "arm64-v8a": "arm64-v8a,armeabi-v7a,armeabi",
        "armeabi-v7a": "armeabi-v7a,armeabi",
    }.get(arch, "")
    if not cpu:
        return ""
    encoded = base64.b64encode(f"myCPU={cpu}&leanback=0".encode()).decode()
    return f"&q={encoded}"
