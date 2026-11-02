# Repository Rules for Morphe-AutoBuilds

## Branch and Merge Strategy
- Always fetch updates from `upstream` (`https://github.com/RookieEnough/Morphe-AutoBuilds.git`) and merge directly into `main` for this repository.
- Do not create detached or separate sync branches unless explicitly requested.

## Personal Customizations to Always Preserve
When resolving merge conflicts, always preserve our custom pipeline additions:
1. **Target Architecture & Optimization**: Keep builds focused on `arm64-v8a` and retain `utils.strip_non_arm64_libraries()`.
2. **Locale Slimming**: Retain `utils.slim_apk_locales()` and `KEEP_LOCALES` configuration.
3. **No Silent Downgrades**: Retain strict version matching (`versions_to_try = [version]`).
4. **Play Store Update Protection**: Retain binary `AndroidManifest.xml` manipulation (`src/play_updates.py`) setting `versionCode` to `2147483647`.
5. **Signature Bypasses**: Retain source signature preservation for Proton Mail and TeraBox.
6. **Custom Apps & Patches**: Preserve all custom apps in `apps/`, patch configs in `patches/`, and sources in `sources/`.

## Verification Steps
- Always verify Python syntax with `python -m py_compile` on modified files.
- Always run the offline test suite: `python tests/test_play_updates.py`.
