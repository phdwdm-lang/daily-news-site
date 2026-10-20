"""Smoke tests for an unpacked release; no network or browser launches."""
import importlib.util
import json
from pathlib import Path
import sys
import tempfile
import unittest

PACKAGE = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location("daily_news_setup", PACKAGE / "scripts/setup.py")
setup = importlib.util.module_from_spec(spec)
spec.loader.exec_module(setup)


class InstallationTests(unittest.TestCase):
    def test_new_path_and_repeated_init_preserve_private_profile(self):
        with tempfile.TemporaryDirectory() as scratch:
            workspace = Path(scratch) / "测试 空间" / "每日信息站"
            self.assertEqual(setup.initialize(workspace, package=PACKAGE)["status"], "initialized")
            profile = workspace / ".daily-news/profile.json"
            profile.write_text('{"schema_version":1,"facts":[]}', encoding="utf-8")
            saved = profile.read_bytes()
            self.assertEqual(setup.initialize(workspace, package=PACKAGE)["status"], "unchanged")
            self.assertEqual(profile.read_bytes(), saved)
            config = json.loads((workspace / ".daily-news/config.json").read_text(encoding="utf-8"))
            self.assertEqual(config["context"]["mode"], "none")
            self.assertEqual(config["theme"], "light")
            self.assertEqual(list((workspace / "data/issues").iterdir()), [])
            self.assertTrue((workspace / "skills/daily-news-site/scripts/collect.mjs").is_file())
            self.assertFalse((workspace / "skills/daily-news-site/assets").exists())
            self.assertTrue((workspace / "resources/vendor/alpine.min.js").is_file())

    def test_unrelated_existing_directory_is_untouched(self):
        with tempfile.TemporaryDirectory() as scratch:
            target = Path(scratch)
            marker = target / "my-content.txt"
            marker.write_text("preserve", encoding="utf-8")
            with self.assertRaises(ValueError):
                setup.initialize(target, package=PACKAGE)
            self.assertEqual(marker.read_text(encoding="utf-8"), "preserve")
            self.assertEqual(len(list(target.iterdir())), 1)


if __name__ == "__main__":
    unittest.main()
