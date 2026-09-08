"""Dependency-free checks for bundled website assets and package boundaries."""

import runpy
import tempfile
import unittest
from pathlib import Path, PurePosixPath

from invoice_hub.release.build_core import INCLUDE_FILES
from invoice_hub.release.build_manifest import BUILD_INPUTS, deterministic_build_id
from invoice_hub.release.source_snapshot import REQUIRED_PATHS as SOURCE_REQUIRED_PATHS
from invoice_hub.release.verify_portable import REQUIRED_PATHS, PortableVerificationError, _verify_windows_member
from invoice_hub.version import LOCAL_WEBSITE_PATH, UPDATE_FEED_URL, WEBSITE_URL
from invoice_hub.website import WEBSITE_ASSETS, WEBSITE_BUILD_INPUTS, copy_website, website_asset_path


ROOT = Path(__file__).resolve().parents[1]


class WebsiteTests(unittest.TestCase):
    def test_copy_includes_all_assets_and_licenses_only(self):
        with tempfile.TemporaryDirectory() as temporary:
            destination = Path(temporary)
            copy_website(ROOT, destination)
            actual = {path.relative_to(destination).as_posix() for path in destination.rglob("*") if path.is_file()}
            self.assertEqual(actual, set(WEBSITE_BUILD_INPUTS))
            for name in actual:
                self.assertEqual((destination / name).read_bytes(), (ROOT / name).read_bytes())

    def test_missing_asset_stops_copy_before_writing(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            source, destination = root / "source", root / "destination"
            copy_website(ROOT, source)
            (source / "website/assets/display.woff").unlink()
            with self.assertRaises(FileNotFoundError):
                copy_website(source, destination)
            self.assertFalse(destination.exists())

    def test_http_asset_lookup_rejects_non_public_paths(self):
        for name in ("README.md", "tests/demo.test.cjs", "assets/", "../config/app.local.json", "assets/../index.html", "/index.html", "C:/index.html"):
            with self.subTest(name=name), self.assertRaises(ValueError):
                website_asset_path(ROOT / "website", name)
        for name in WEBSITE_ASSETS:
            self.assertTrue(website_asset_path(ROOT / "website", name).is_relative_to(ROOT / "website"))

    def test_build_and_package_allowlists_share_the_offline_assets(self):
        for name in WEBSITE_BUILD_INPUTS:
            with self.subTest(name=name):
                self.assertIn(name, INCLUDE_FILES)
                self.assertIn(name, BUILD_INPUTS)
                self.assertIn(name, REQUIRED_PATHS)
                self.assertIn(name, SOURCE_REQUIRED_PATHS)
                _verify_windows_member(PurePosixPath(name), is_directory=False)
        for name in ("website/README.md", "website/scripts/preview.cjs", "website/assets/private.txt"):
            with self.subTest(name=name), self.assertRaises(PortableVerificationError):
                _verify_windows_member(PurePosixPath(name), is_directory=False)

    def test_alpha_staging_and_build_identity_include_the_same_site(self):
        module = runpy.run_path(str(ROOT / "scripts/dev/tauri_alpha_release.py"))
        with tempfile.TemporaryDirectory() as temporary:
            core = Path(temporary) / "core"
            module["_copy_allowlisted_snapshot"](ROOT, core)
            self.assertEqual(deterministic_build_id(core), deterministic_build_id(ROOT))
            self.assertFalse((core / "website/tests").exists())
            self.assertFalse((core / "website/README.md").exists())
            for name in WEBSITE_BUILD_INPUTS:
                self.assertEqual((core / name).read_bytes(), (ROOT / name).read_bytes())

    def test_local_navigation_does_not_move_the_update_feed(self):
        self.assertEqual(LOCAL_WEBSITE_PATH, "/website/")
        self.assertEqual(UPDATE_FEED_URL, WEBSITE_URL + "updates/alpha/latest.json")
        self.assertTrue(UPDATE_FEED_URL.startswith("https://"))


if __name__ == "__main__":
    unittest.main()
