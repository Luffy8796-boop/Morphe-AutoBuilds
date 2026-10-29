"""Offline regression for apps that opt into latest-version update tracking."""
import sys
import unittest
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))
import check_app_updates


class LatestAppUpdateTests(unittest.TestCase):
    def setUp(self):
        config, platform = check_app_updates.load_app_config("brave-nightly")
        self.assertEqual(platform, "apkmirror")
        self.assertTrue(config["track_latest"])
        self.assertEqual(config["version"], "")
        self.entry = {
            "app_name": "brave-nightly",
            "source": "dh6k",
            "arch": "arm64-v8a",
        }
        self.apk = "brave-nightly-arm64-v8a-dh6k-v1.100.5.apk"
        self.manifest = {
            "entries": {
                check_app_updates.make_manifest_key(
                    "brave-nightly", "dh6k", "arm64-v8a"
                ): {
                    "config_version": "",
                    "source_sig": "same-source",
                    "apk": self.apk,
                    "built_version": "1.100.5",
                }
            }
        }

    def plan(self, latest):
        with (
            patch.object(check_app_updates, "get_source_signature", return_value="same-source"),
            patch.object(check_app_updates, "fetch_latest_app_version", return_value=latest) as fetch_latest,
            patch.object(check_app_updates, "fetch_recommended_version", return_value="") as fetch_recommended,
        ):
            result = check_app_updates.plan_incremental(
                [self.entry], self.manifest, [self.apk]
            )
        return result, fetch_latest, fetch_recommended

    def test_newer_apkmirror_version_triggers_rebuild(self):
        (build_matrix, _, _), fetch_latest, fetch_recommended = self.plan("1.101.0")
        self.assertEqual(build_matrix, [{"app_name": "brave-nightly", "source": "dh6k"}])
        fetch_latest.assert_called_once_with("brave-nightly")
        fetch_recommended.assert_not_called()

    def test_same_apkmirror_version_is_carried_over(self):
        (build_matrix, carry_over, _), fetch_latest, _ = self.plan("1.100.5")
        self.assertEqual(build_matrix, [])
        self.assertEqual(carry_over, [self.apk])
        fetch_latest.assert_called_once_with("brave-nightly")

    def test_unavailable_apkmirror_version_does_not_force_rebuild(self):
        (build_matrix, carry_over, _), fetch_latest, _ = self.plan("")
        self.assertEqual(build_matrix, [])
        self.assertEqual(carry_over, [self.apk])
        fetch_latest.assert_called_once_with("brave-nightly")


if __name__ == "__main__":
    unittest.main()
