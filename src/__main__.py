import json
import logging
import re
import os
from sys import exit
from pathlib import Path
from os import getenv
import subprocess
import shutil
from src import (
    r2,
    utils,
    release,
    downloader
)

def _normalize_build_arch(arch: str | None) -> str:
    """Keep the produced APK architecture fixed to arm64-v8a."""
    return "arm64-v8a"


def _normalize_source_arch(arch: str | None) -> str:
    """Normalize the requested stock APK variant independently of output ABI."""
    normalized = (arch or "arm64-v8a").strip().lower()
    aliases = {
        "arm64": "arm64-v8a",
        "arm64-v8a": "arm64-v8a",
        "arm64v8a": "arm64-v8a",
        "arm-v7a": "armeabi-v7a",
        "armeabi-v7a": "armeabi-v7a",
        "armeabi": "armeabi-v7a",
        "armv7": "armeabi-v7a",
        "armv7a": "armeabi-v7a",
        "armv7-abi": "armeabi-v7a",
        "universal": "universal",
        "noarch": "universal",
        "all": "universal",
    }
    if normalized not in aliases:
        raise ValueError(f"Unsupported source APK architecture: {arch}")
    return aliases[normalized]


_APPLYING_ZERO_PATCHES = re.compile(r"applying\s+0\s+patches\b", re.IGNORECASE)
_FILTERING_PATCHES = re.compile(
    r"Filtering patches for\s+(\S+)\s+v(\S+(?:\s+build\s+\d+|\s*\(\d+\))?)",
    re.IGNORECASE,
)
_BUILD_SUFFIX = re.compile(r"(?:\s+build\s+\d+|\s*\(\d+\))\s*$", re.IGNORECASE)


def _version_without_build(version: str) -> str:
    """Drop a trailing build number from a version string."""
    return _BUILD_SUFFIX.sub("", version).strip()


def _unpatched_build_reason(output: str | None, downloaded_version: str) -> str | None:
    """Reject a zero-exit patch run that applied no patches or used another version."""
    if not output:
        return None

    if _APPLYING_ZERO_PATCHES.search(output):
        return (
            f"Patch CLI applied 0 patches to v{downloaded_version}; "
            "refusing to sign an unpatched APK"
        )

    downloaded = utils.normalize_version(_version_without_build(downloaded_version))
    for match in _FILTERING_PATCHES.finditer(output):
        package, filtered = match.group(1), match.group(2).strip().rstrip(".")
        if utils.normalize_version(_version_without_build(filtered)) != downloaded:
            return (
                f"Patch CLI filtered {package} v{filtered}, "
                f"which is not the downloaded v{downloaded_version}"
            )
    return None


def _telegram_api_credential_options(app_name: str, source: str) -> list[str]:
    if app_name.lower() != "telegram" or source.lower() != "hushtelegram":
        return []

    api_id = getenv("TELEGRAM_API_ID", "").strip()
    api_hash = getenv("TELEGRAM_API_HASH", "").strip()
    if not api_id and not api_hash:
        return []
    if not api_id or not api_hash:
        raise ValueError("Both TELEGRAM_API_ID and TELEGRAM_API_HASH must be set")

    return [
        "-e",
        "Use registered Telegram API credentials",
        f"-OapiId={api_id}",
        f"-OapiHash={api_hash}",
    ]


def run_build(
    app_name: str,
    source: str,
    arch: str = "arm64-v8a",
    source_arch: str | None = None,
) -> str:
    """Build APK for the optimized arm64-v8a target."""
    arch = _normalize_build_arch(arch)
    source_arch = _normalize_source_arch(source_arch or arch)
    telegram_api_options = _telegram_api_credential_options(app_name, source)
    download_files, name = downloader.download_required(source)

    # Log downloaded files for debugging
    logging.info(f"📦 Downloaded {len(download_files)} files for {source}:")
    for file in download_files:
        logging.info(f"  - {file.name} ({file.stat().st_size} bytes)")

    # DETECT SOURCE TYPE BASED ON DOWNLOADED FILES
    is_morphe = False
    is_revanced = False

    # Check file contents to determine source type
    for file in download_files:
        if "morphe-cli" in file.name.lower():
            is_morphe = True
            break
        elif "revanced-cli" in file.name.lower():
            is_revanced = True
            break

    # If not detected by CLI name, check patch file extension
    if not is_morphe and not is_revanced:
        for file in download_files:
            if file.suffix == ".mpp":
                is_morphe = True
                break
            elif file.suffix in [".rvp", ".jar"] and "patches" in file.name.lower():
                is_revanced = True
                break

    # If still not detected, fallback to source name
    if not is_morphe and not is_revanced:
        is_morphe = "morphe" in source.lower() or "custom" in source.lower()
        is_revanced = not is_morphe  # Default to ReVanced if not Morphe

    logging.info(f"🔍 Detected: {'Morphe' if is_morphe else 'ReVanced'} source type")

    # TeraBox's signature-dependent patches need the signed base APK from the
    # original bundle, so let Morphe Desktop merge and extract it itself.
    preserve_bundle_signature = (
        app_name == "terabox" and input_apk.suffix.lower() in {".apkm", ".xapk", ".apks"}
    )

    # FIND FILES BASED ON DETECTED TYPE
    if is_morphe:
        # Find Morphe files - prefer non-dev version
        cli = utils.find_file(download_files, contains="morphe-cli", suffix=".jar", exclude=["dev"])
        if not cli:
            # Fallback to any Morphe CLI
            cli = utils.find_file(download_files, contains="morphe", suffix=".jar")
        
        if not cli:
            cli = utils.find_file(download_files, suffix=".jar")
        patch_bundles = [file for file in download_files if file.suffix.lower() == ".mpp"]
        patches = utils.find_file(download_files, contains="patches", suffix=".mpp")
        if not patches:
            patches = patch_bundles[0] if patch_bundles else None
    else:
        # Find ReVanced files
        cli = utils.find_file(download_files, contains="revanced-cli", suffix=".jar")
        patches = utils.find_file(download_files, contains="patches", suffix=".rvp")
        
        if not patches:
            # Try .jar extension for patches
            patches = utils.find_file(download_files, contains="patches", suffix=".jar")

    # Validate tools
    if not cli:
        logging.error(f"❌ CLI not found for source: {source}")
        logging.error(f"Available files: {[f.name for f in download_files]}")
        return None
    if not patches:
        logging.error(f"❌ Patches not found for source: {source}")
        logging.error(f"Available files: {[f.name for f in download_files]}")
        return None

    logging.info(f"✅ Using CLI: {cli.name}")
    logging.info(f"✅ Using patches: {', '.join(file.name for file in (patch_bundles if is_morphe else [patches]))}")

    download_methods = [
        downloader.download_apkmirror,
        downloader.download_apkpure,
        downloader.download_aptoide,
        downloader.download_uptodown,
        downloader.download_apkfab,
        downloader.download_github,
        downloader.download_codeberg,
        downloader.download_apkcombo,
    ]

    # HushTelegram supports telegram.org's package, provided here by Uptodown.
    # Do not fall back to APKMirror's Google Play package.
    if app_name == "telegram" and source.lower() == "hushtelegram":
        download_methods = [downloader.download_uptodown]
        logging.info("Telegram with HushTelegram: using Uptodown only")
    elif app_name == "proton-mail":
        download_methods = [downloader.download_uptodown]
        logging.info("Proton Mail: using Uptodown only")
    # The Devanced Facebook source is Codeberg-only; HushFacebook uses mirrors.
    elif app_name == "facebook" and source.lower() == "devanced":
        download_methods = [downloader.download_codeberg]
        logging.info("Devanced Facebook: using Codeberg only (no mirror fallbacks)")

    input_apk = None
    version = None
    used_method = None
    for method in download_methods:
        apk_path, ver, _ = method(app_name, str(cli), str(patches), source_arch)
        if not apk_path:
            continue
        # A corrupt download must never reach the patcher: repair it, and if
        # it is still unusable, discard it and try the next source.
        apk_path = utils.ensure_usable_apk(apk_path, app_name, ver or "")
        if apk_path is None:
            logging.warning(f"Discarding unusable download from {method.__name__}; trying next source")
            continue
        input_apk, version = apk_path, ver
        used_method = method
        break

    if input_apk is None or not used_method or not version:
        logging.error(f"❌ Failed to download APK for {app_name}")
        logging.error("All download sources failed. Skipping this app.")
        return None

    # Build only the selected compatible version; never silently downgrade.
    versions_to_try = [version]

    exclude_patches = []
    include_patches = []

    patches_path = Path("patches") / f"{app_name}-{source}.txt"
    if patches_path.exists():
        with patches_path.open('r') as patches_file:
            for line in patches_file:
                line = line.strip()
                if line.startswith('-'):
                    exclude_patches.extend(["-d", line[1:].strip()])
                elif line.startswith('+'):
                    # Inline patch options: + Patch name {key=value, key2=value2}
                    # become: -e "Patch name" -Okey=value -Okey2=value2
                    name_opts = line[1:].strip()
                    opts: list[str] = []
                    if "{" in name_opts and name_opts.rstrip().endswith("}"):
                        name_part, opts_part = name_opts.split("{", 1)
                        name_opts = name_part.strip()
                        for opt in opts_part.rstrip("}").split(","):
                            opt = opt.strip()
                            if opt:
                                opts.append(f"-O{opt}")
                    include_patches.extend(["-e", name_opts, *opts])

    include_patches.extend(telegram_api_options)

    for ver in versions_to_try:
        # --- Normalize/merge input into .apk when needed ---
        if input_apk.suffix != ".apk" and not preserve_bundle_signature:
            # Check if it is a split bundle (contains multiple .apk files or is .apkm/.xapk/.apks)
            is_bundle = False
            try:
                import zipfile
                if zipfile.is_zipfile(input_apk):
                    with zipfile.ZipFile(input_apk, "r") as z:
                        namelist = z.namelist()
                        has_split_apks = any(n.endswith(".apk") for n in namelist)
                        is_bundle = has_split_apks or input_apk.suffix.lower() in [".apkm", ".xapk", ".apks", ".zip"]
            except Exception as e:
                logging.debug(f"Zip inspection failed for {input_apk}: {e}")

            target_apk = input_apk.with_name(f"{input_apk.stem}.apk" if not input_apk.name.endswith(".apk") else input_apk.name)

            if is_bundle:
                logging.info(f"Input file is a bundle ({input_apk.name}), using APKEditor to merge")
                apk_editor = downloader.download_apkeditor()
                merged_apk = input_apk.with_suffix(".apk")
                merged_apk.unlink(missing_ok=True)

                try:
                    utils.run_process([
                        "java", "-jar", str(apk_editor), "m",
                        "-f",
                        "-i", str(input_apk),
                        "-o", str(merged_apk)
                    ], silent=True, check=True)
                    input_apk.unlink(missing_ok=True)
                    input_apk = merged_apk
                except Exception as e:
                    logging.warning(f"APKEditor merge failed ({e}); checking if file can be used as standalone APK")
                    if input_apk.exists():
                        target_apk.unlink(missing_ok=True)
                        os.replace(input_apk, target_apk)
                        input_apk = target_apk
            else:
                logging.info(f"Normalizing standalone APK filename to {target_apk.name}")
                if input_apk != target_apk:
                    target_apk.unlink(missing_ok=True)
                    os.replace(input_apk, target_apk)
                    input_apk = target_apk

            if not input_apk.exists():
                logging.error("Processed APK file not found")
                raise RuntimeError("Processed APK file not found")

            # Clean up filename: remove build number like (1575420) and -1575420.
            # Only strip 6+ digit build-number tokens so legitimate short version
            # segments (e.g. "app-2_0") are not mangled.
            clean_name = re.sub(r'\(\d+\)', '', input_apk.name)  # Remove (1575420)
            clean_name = re.sub(r'-\d{6,}_', '_', clean_name)  # Remove -1575420_ -> _
            if clean_name != input_apk.name:
                clean_apk = input_apk.with_name(clean_name)
                clean_apk.unlink(missing_ok=True)
                os.replace(input_apk, clean_apk)
                input_apk = clean_apk

            logging.info(f"Normalized APK file: {input_apk}")
        elif preserve_bundle_signature:
            logging.info("Passing the untouched TeraBox bundle to Morphe to preserve its base APK signature")

        preserve_source_signature = app_name == "proton-mail" or preserve_bundle_signature
        skip_locale_slimming = getenv("SKIP_LOCALE_SLIMMING", "").strip().lower() in {
            "1", "true", "yes", "on"
        }
        if preserve_source_signature:
            logging.info("Skipping locale slimming for Proton Mail to preserve its source signature")
        elif skip_locale_slimming:
            logging.info("Skipping locale slimming as requested")
        else:
            # Slim translated resources before applying the arm64 CPU filter.
            apk_editor = downloader.download_apkeditor()
            keep_locales = [
                locale.strip()
                for locale in getenv("KEEP_LOCALES", "en").split(",")
                if locale.strip()
            ]
            try:
                utils.slim_apk_locales(input_apk, apk_editor, keep_locales)
            except Exception:
                input_apk.unlink(missing_ok=True)
                raise

        # --- ARCHITECTURE-SPECIFIC PROCESSING ---
        logging.info(f"Optimizing APK for arm64-v8a CPU target...")
        if preserve_source_signature:
            logging.info("Skipping pre-patch ABI stripping for Proton Mail to preserve its source signature")
        else:
            utils.strip_non_arm64_libraries(input_apk)

        # Validate APK integrity (safety net: downloads were already validated,
        # but bundle merging / arch stripping can corrupt the file).
        # Note: Only check integrity here, NOT signature. Merged bundles are
        # unsigned (APKEditor doesn't sign); the APK gets signed after patching.
        logging.info("Checking APK integrity...")
        input_apk = utils.ensure_usable_apk(
            input_apk,
            app_name,
            version or "",
            require_signature=False,
        )
        if input_apk is None:
            logging.error(f"APK for {app_name} v{version} is corrupt and could not be repaired; skipping this app")
            continue

        # Include architecture in output filename
        output_apk = Path(f"{app_name}-{arch}-patch-v{version}.apk")

        cli_output = None
        try:
            # USE DIFFERENT COMMANDS BASED ON SOURCE TYPE
            if is_morphe:
                logging.info("🔧 Using Morphe patching system...")
                morphe_cmd = [
                    "java", "-jar", str(cli),
                    "patch",
                ]
                for patch_bundle in patch_bundles:
                    morphe_cmd.extend(["--patches", str(patch_bundle)])
                morphe_cmd.extend([
                    "--out", str(output_apk), str(input_apk),
                    *exclude_patches, *include_patches
                ])
                cli_output = utils.run_process(morphe_cmd, capture=True, stream=True)
            else:
                logging.info("🔧 Using ReVanced patching system...")
                cli_name = Path(cli).name.lower()
                is_revanced_v6_or_newer = (
                    'revanced-cli-6' in cli_name or 'revanced-cli-7' in cli_name or 'revanced-cli-8' in cli_name
                )

                if is_revanced_v6_or_newer:
                    cli_output = utils.run_process([
                        "java", "-jar", str(cli),
                        "patch", "-p", str(patches), "-b",
                        "--out", str(output_apk), str(input_apk),
                        *exclude_patches, *include_patches
                    ], capture=True, stream=True)
                else:
                    cli_output = utils.run_process([
                        "java", "-jar", str(cli),
                        "patch", "--patches", str(patches),
                        "--out", str(output_apk), str(input_apk),
                        *exclude_patches, *include_patches
                    ], capture=True, stream=True)

        except subprocess.CalledProcessError as e:
            # Remove temp input apk; we'll re-download if retrying.
            input_apk.unlink(missing_ok=True)
            output_apk.unlink(missing_ok=True)

            raise

        try:
            utils.strip_non_arm64_libraries(output_apk)
            if not utils.check_apk_integrity(output_apk):
                raise RuntimeError("Patched APK failed integrity validation after ABI filtering")
        except Exception:
            output_apk.unlink(missing_ok=True)
            raise

        rejection = _unpatched_build_reason(cli_output, version)
        if rejection:
            logging.error(f"❌ {rejection}")
            input_apk.unlink(missing_ok=True)
            output_apk.unlink(missing_ok=True)
            return None

        # Patch succeeded -> cleanup input and sign.
        input_apk.unlink(missing_ok=True)

        signed_apk = Path(f"{app_name}-{arch}-{name}-v{version}.apk")

        apksigner = utils.find_apksigner()
        if not apksigner:
            raise RuntimeError("apksigner not found")

        if app_name in ("tiktok", "twitter", "x-new"):
            from src.play_updates import disable_play_store_updates
            disable_play_store_updates(output_apk)
            zipalign = shutil.which("zipalign") or str(Path(apksigner).with_name("zipalign"))
            aligned_apk = output_apk.with_suffix(".aligned.apk")
            utils.run_process([zipalign, "-f", "-P", "16", "4", str(output_apk), str(aligned_apk)])
            aligned_apk.replace(output_apk)

        try:
            utils.run_process([
                str(apksigner), "sign", "--verbose",
                "--ks", "keystore/public.jks",
                "--ks-pass", "pass:public",
                "--key-pass", "pass:public",
                "--ks-key-alias", "public",
                "--in", str(output_apk), "--out", str(signed_apk)
            ], capture=True, stream=True)
        except Exception as e:
            logging.warning(f"Standard signing failed: {e}")
            logging.info("Trying alternative signing method...")

            utils.run_process([
                str(apksigner), "sign", "--verbose",
                "--min-sdk-version", "21",
                "--ks", "keystore/public.jks",
                "--ks-pass", "pass:public",
                "--key-pass", "pass:public",
                "--ks-key-alias", "public",
                "--in", str(output_apk), "--out", str(signed_apk)
            ], capture=True, stream=True)

        output_apk.unlink(missing_ok=True)
        print(f"✅ APK built: {signed_apk.name}")
        return str(signed_apk)

    # The selected version could not be built.
    return None

def main():
    app_name = getenv("APP_NAME")
    source = getenv("SOURCE")

    if not app_name or not source:
        logging.error("APP_NAME and SOURCE environment variables must be set")
        exit(1)

    requested_arch = _normalize_build_arch(getenv("ARCH"))
    source_arch = _normalize_source_arch(getenv("APK_ARCH") or getenv("ARCH"))
    arches = [requested_arch]

    # Always prefer a single optimized arm64-v8a build. The previous multi-arch
    # config is intentionally ignored to keep output size and compatibility
    # focused on the target device ABI.
    built_apks = []
    for arch in arches:
        logging.info(
            f"🔨 Building {app_name} for {arch}; downloading {source_arch} source APK..."
        )
        apk_path = run_build(app_name, source, arch, source_arch)
        if apk_path:
            built_apks.append(apk_path)
            print(f"✅ Built {arch} version: {Path(apk_path).name}")

    print(f"\n🎯 Built {len(built_apks)} APK(s) for {app_name}:")
    for apk in built_apks:
        print(f"  📱 {Path(apk).name}")
    if not built_apks:
        logging.error(f"❌ No APKs built for {app_name}; failing the job.")
        exit(1)


if __name__ == "__main__":
    main()
