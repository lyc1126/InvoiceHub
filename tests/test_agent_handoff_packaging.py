"""Portable-package boundaries using synthetic runtimes, never local task data."""
import hashlib
import importlib.util
import io
import json
from pathlib import Path
import stat
import tarfile
import tempfile
import unittest
from unittest import mock
import zipfile

ROOT = Path(__file__).resolve().parents[1]
SPEC = importlib.util.spec_from_file_location("build_agent_handoff", ROOT / "scripts/dev/build_agent_handoff.py")
builder = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(builder)


class PackageTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix="handoff-package-test-")
        self.addCleanup(self.temp.cleanup)
        self.base = Path(self.temp.name)
        self.source = self.base / "source"
        for relative in builder.SOURCES:
            target = self.source / relative
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_bytes((ROOT / relative).read_bytes())
        (self.source / "CURRENT.md").write_text("SYNTHETIC-PRIVATE-NOT-PACKAGED")
        (self.source / "config").mkdir()
        (self.source / "config/private.json").write_text("SYNTHETIC-PRIVATE-NOT-PACKAGED")

    def runtime(self, platform, members=None):
        path = self.base / builder.RUNTIMES[platform]["archive"]
        if platform == "windows-x64":
            with zipfile.ZipFile(path, "w") as zf:
                for name, data in members or [("python.exe", b"synthetic-runtime"), ("LICENSE.txt", b"synthetic license")]:
                    zf.writestr(name, data)
        else:
            with tarfile.open(path, "w:gz") as tf:
                data = b"synthetic-runtime"
                member = tarfile.TarInfo("python/bin/python3.14")
                member.mode = 0o755; member.size = len(data)
                tf.addfile(member, io.BytesIO(data))
                link = tarfile.TarInfo("python/bin/python3")
                link.type = tarfile.SYMTYPE; link.linkname = "python3.14"
                tf.addfile(link)
        locked = {**builder.RUNTIMES[platform], "sha256": hashlib.sha256(path.read_bytes()).hexdigest()}
        return path, mock.patch.dict(builder.RUNTIMES, {platform: locked})

    def test_allowlist_reproducibility_and_platform_launcher(self):
        for platform in builder.RUNTIMES:
            with self.subTest(platform=platform):
                archive, patch = self.runtime(platform)
                with patch:
                    a = builder.package(self.source, platform, archive, self.base / "one")
                    b = builder.package(self.source, platform, archive, self.base / "two")
                    self.assertEqual(a["sha256"], b["sha256"])
                    self.assertTrue(builder.verify(Path(a["archive"]))["verified"])
                    with zipfile.ZipFile(a["archive"]) as zf:
                        self.assertFalse(any("CURRENT" in n or "config/" in n for n in zf.namelist()))
                        self.assertFalse(any(b"SYNTHETIC-PRIVATE-NOT-PACKAGED" in zf.read(n) for n in zf.namelist()))
                        if platform == "macos-arm64":
                            self.assertTrue(zf.getinfo("agent-handoff.command").external_attr >> 16 & 0o111)
                            self.assertTrue(stat.S_ISREG(zf.getinfo("python/bin/python3").external_attr >> 16))
                            self.assertEqual(zf.read("python/bin/python3"), zf.read("python/bin/python3.14"))
                        else:
                            self.assertIn(b"%~dp0python\\python.exe", zf.read("agent-handoff.cmd"))

    def test_wrong_runtime_hash_is_rejected(self):
        archive, unused_patch = self.runtime("windows-x64")
        with self.assertRaisesRegex(ValueError, "SHA-256"):
            builder.package(self.source, "windows-x64", archive, self.base / "out")

    def test_cached_runtime_requires_trusted_outer_hash_and_uses_new_source(self):
        archive, patch = self.runtime("windows-x64")
        with patch:
            original = builder.package(self.source, "windows-x64", archive, self.base / "old")
            cached = Path(original["archive"])
            source = self.source / "docs/AGENT_HANDOFF.md"
            source.write_text("new public documentation\n")
            for wrong in (None, "0" * 64):
                with self.assertRaisesRegex(ValueError, "trusted SHA"):
                    builder.package(self.source, "windows-x64", None, self.base / "new",
                                    runtime_package=cached, runtime_package_sha256=wrong)
            result = builder.package(self.source, "windows-x64", None, self.base / "new",
                                     runtime_package=cached, runtime_package_sha256=original["sha256"])
            with zipfile.ZipFile(result["archive"]) as zf:
                self.assertEqual(zf.read("README.md"), source.read_bytes())
                self.assertEqual(zf.read("python/python.exe"), b"synthetic-runtime")
                self.assertEqual(json.loads(zf.read("MANIFEST.json"))["runtime_package_sha256"], original["sha256"])

    def test_runtime_path_traversal_is_rejected_even_for_pinned_fixture(self):
        archive, patch = self.runtime("windows-x64", [("../escape", b"bad")])
        with patch, self.assertRaisesRegex(ValueError, "traversal"):
            builder.package(self.source, "windows-x64", archive, self.base / "out")
        self.assertFalse((self.base / "escape").exists())

    def test_modified_member_and_private_extra_are_rejected(self):
        archive, patch = self.runtime("windows-x64")
        with patch:
            result = builder.package(self.source, "windows-x64", archive, self.base / "out")
            with zipfile.ZipFile(result["archive"]) as zf:
                original = [(info, zf.read(info)) for info in zf.infolist()]
            for private in (False, True):
                broken = self.base / f"broken-{private}.zip"
                with zipfile.ZipFile(broken, "w") as zf:
                    for info, data in original:
                        if info.filename == "agent_handoff.py" and not private:
                            data += b"# modified\n"
                        zf.writestr(info, data)
                    if private:
                        info = zipfile.ZipInfo("CURRENT.md")
                        info.external_attr = (stat.S_IFREG | 0o600) << 16
                        zf.writestr(info, b"synthetic-private")
                with self.assertRaisesRegex(ValueError, "hash|membership"):
                    builder.verify(broken)

    def test_linked_public_source_is_rejected(self):
        path = self.source / "LICENSE"
        path.unlink()
        try:
            path.symlink_to(ROOT / "LICENSE")
        except OSError:
            self.skipTest("symlink creation unavailable")
        archive, patch = self.runtime("windows-x64")
        with patch, self.assertRaisesRegex(ValueError, "escapes"):
            builder.package(self.source, "windows-x64", archive, self.base / "out")

    def test_macos_known_helpers_removed_but_unknown_foreign_payload_rejected(self):
        for unknown in (False, True):
            with self.subTest(unknown=unknown):
                archive, _ = self.runtime("macos-arm64")
                with tarfile.open(archive, "r:gz") as tf:
                    members = [(m, tf.extractfile(m).read() if m.isfile() else None) for m in tf.getmembers()]
                foreign = "python/unexpected.exe" if unknown else builder.RUNTIMES["macos-arm64"]["excluded_auxiliaries"][0]
                with tarfile.open(archive, "w:gz") as tf:
                    for member, data in members:
                        tf.addfile(member, io.BytesIO(data) if data is not None else None)
                    member = tarfile.TarInfo(foreign)
                    member.size = 4
                    tf.addfile(member, io.BytesIO(b"test"))
                runtime = {**builder.RUNTIMES["macos-arm64"], "sha256": builder.sha(archive)}
                with mock.patch.dict(builder.RUNTIMES, {"macos-arm64": runtime}):
                    if unknown:
                        with self.assertRaisesRegex(ValueError, "Windows payload"):
                            builder.package(self.source, "macos-arm64", archive, self.base / "out")
                    else:
                        result = builder.package(self.source, "macos-arm64", archive, self.base / "out")
                        with zipfile.ZipFile(result["archive"]) as zf:
                            self.assertNotIn(foreign, zf.namelist())


if __name__ == "__main__":
    unittest.main()
