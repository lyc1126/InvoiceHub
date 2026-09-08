"""Local OFDRW PNG adapter. This module never participates in invoice extraction."""
from __future__ import annotations

import hashlib
import io
import json
import os
import platform
import re
import stat
import struct
import subprocess
import sys
import tempfile
import threading
import zipfile
import xml.etree.ElementTree as ET
from pathlib import Path, PurePosixPath

from invoice_hub.services.document_rendering import MuPDFPageImage

MAX_SOURCE_BYTES = 64 * 1024 * 1024
MAX_EXPANDED_BYTES = 128 * 1024 * 1024
MAX_MEMBER_BYTES = 32 * 1024 * 1024
MAX_XML_BYTES = 8 * 1024 * 1024
MAX_PNG_BYTES = 32 * 1024 * 1024
MAX_FILES = 2048
MAX_PAGES = 200
MAX_PIXELS = 30_000_000
RENDER_TIMEOUT = 25
# Binds the Java adapter/build locks to the Python core build identity. Refresh
# only together with those inputs; the source contract checks the exact digest.
COMPONENT_SOURCE_FINGERPRINT = "43438691e41bdbf7d613de2d0248bdefb9ce5ddb99c55113a4cab03955fe9993"
_RENDER_SLOT = threading.BoundedSemaphore(1)
_DECLARATION = re.compile(r"<!\s*(?:DOCTYPE|ENTITY)\b", re.I)


class OFDPreviewError(Exception):
    def __init__(self, code: str):
        super().__init__(code)
        self.code = code


def _xml(content: bytes) -> ET.Element:
    if len(content) > MAX_XML_BYTES:
        raise OFDPreviewError("ofd_source_too_large")
    # Removing NUL also catches UTF-16/32 declarations before any XML parser runs.
    if _DECLARATION.search(content.replace(b"\x00", b"").decode("latin1")):
        raise OFDPreviewError("ofd_unsafe_document")
    try:
        return ET.fromstring(content)
    except (ET.ParseError, ValueError) as exc:
        raise OFDPreviewError("ofd_invalid_document") from exc


def _member_name(value: str) -> str:
    path = PurePosixPath(value)
    if (not value or "\\" in value or ":" in value or "\x00" in value
            or path.is_absolute() or any(p in {"", ".", ".."} for p in value.rstrip("/").split("/"))):
        raise OFDPreviewError("ofd_unsafe_document")
    return path.as_posix()


def _read_package(path: Path) -> tuple[dict[str, bytes], int]:
    try:
        with path.open("rb") as source:
            raw = source.read(MAX_SOURCE_BYTES + 1)
        if len(raw) > MAX_SOURCE_BYTES:
            raise OFDPreviewError("ofd_source_too_large")
        members: dict[str, bytes] = {}
        names: set[str] = set()
        expanded = 0
        with zipfile.ZipFile(io.BytesIO(raw)) as archive:
            if len(archive.infolist()) > MAX_FILES:
                raise OFDPreviewError("ofd_source_too_large")
            for info in archive.infolist():
                name = _member_name(info.filename)
                mode = info.external_attr >> 16
                if name.casefold() in names or stat.S_ISLNK(mode) or info.flag_bits & 1:
                    raise OFDPreviewError("ofd_unsafe_document")
                names.add(name.casefold())
                if info.is_dir():
                    continue
                expanded += info.file_size
                if info.file_size > MAX_MEMBER_BYTES or expanded > MAX_EXPANDED_BYTES:
                    raise OFDPreviewError("ofd_source_too_large")
                content = archive.read(info)
                if name.lower().endswith((".xml", ".svg")):
                    _xml(content)
                members[name] = content
        root = _xml(members["OFD.xml"])
        ns = {"o": "http://www.ofdspec.org/2016"}
        bodies = root.findall("o:DocBody", ns)
        if root.tag != "{http://www.ofdspec.org/2016}OFD" or len(bodies) != 1:
            raise OFDPreviewError("ofd_unsupported_document")
        doc_ref = bodies[0].findtext("o:DocRoot", namespaces=ns)
        document = _xml(members[_member_name((doc_ref or "").strip().lstrip("/"))])
        pages = document.findall("o:Pages/o:Page", ns)
        if not pages or len(pages) > MAX_PAGES:
            raise OFDPreviewError("ofd_invalid_document")
        for name in members:
            if any(parent.as_posix() in members for parent in PurePosixPath(name).parents):
                raise OFDPreviewError("ofd_unsafe_document")
        return members, len(pages)
    except OFDPreviewError:
        raise
    except (OSError, ValueError, KeyError, RuntimeError, zipfile.BadZipFile) as exc:
        raise OFDPreviewError("ofd_invalid_document") from exc


def _platform_id() -> str:
    machine = platform.machine().lower()
    if os.name == "nt" and machine in {"amd64", "x86_64"}:
        return "windows-x64"
    if platform.system() == "Darwin" and machine in {"arm64", "aarch64"}:
        return "macos-arm64"
    raise OFDPreviewError("ofd_renderer_unavailable")


def _policy_path(path: Path) -> str:
    return str(path.resolve()).replace("\\", "/").replace('"', '\\"')


class OFDRenderer:
    def __init__(self, component_dir: Path | None = None):
        root = Path(__file__).resolve().parents[3]
        packaged = Path(sys.prefix) / "components" / "ofd-preview"
        # Packaged applications never fall back to user executables or PATH Java.
        self.component_dir = component_dir or (
            packaged if (root / "invoice-hub-build.json").exists() or os.environ.get("INVOICE_HUB_RELEASE_MODE") == "1" or packaged.exists()
            else root / "runtime" / "components" / "ofd-preview"
        )

    def _component(self) -> tuple[Path, list[Path]]:
        root = self.component_dir.resolve()
        try:
            manifest = json.loads((root / "component.json").read_text(encoding="utf-8"))
            if (manifest["schema_version"] != 1 or manifest["engine"] != "ofdrw-2.4.0"
                    or manifest["java_major"] != 21 or manifest["platform"] != _platform_id()
                    or manifest["source_fingerprint"] != COMPONENT_SOURCE_FINGERPRINT):
                raise ValueError("component identity")
            files = manifest["files"]
            if not isinstance(files, dict) or not files:
                raise ValueError("empty component")
            for name, digest in files.items():
                item = root / _member_name(name)
                if item.is_symlink() or not item.resolve().is_relative_to(root):
                    raise ValueError("component path")
                if hashlib.sha256(item.read_bytes()).hexdigest() != digest:
                    raise ValueError("component hash")
            java_name = "java/bin/java.exe" if os.name == "nt" else "java/bin/java"
            jars = [root / name for name in sorted(files) if name.startswith("lib/") and name.endswith(".jar")]
            if java_name not in files or "lib/ofd-preview.jar" not in files or not jars:
                raise ValueError("component missing")
            return root / java_name, jars
        except (OSError, ValueError, KeyError, TypeError, OFDPreviewError) as exc:
            raise OFDPreviewError("ofd_renderer_unavailable") from exc

    def page_count(self, path: Path) -> int:
        if not _RENDER_SLOT.acquire(blocking=False):
            raise OFDPreviewError("ofd_renderer_busy")
        try:
            _, count = _read_package(path)
            self._component()
            return count
        finally:
            _RENDER_SLOT.release()

    def render(self, path: Path, page_number: int) -> MuPDFPageImage:
        if not _RENDER_SLOT.acquire(blocking=False):
            raise OFDPreviewError("ofd_renderer_busy")
        try:
            members, count = _read_package(path)
            if page_number < 1 or page_number > count:
                raise OFDPreviewError("page_not_found")
            java, jars = self._component()
            with tempfile.TemporaryDirectory(prefix="invoicehub-ofd-") as work:
                temp = Path(work).resolve()
                document = temp / "source"
                document.mkdir()
                try:
                    for name, content in members.items():
                        target = document / name
                        target.parent.mkdir(parents=True, exist_ok=True)
                        target.write_bytes(content)
                except OSError as exc:
                    raise OFDPreviewError("ofd_render_failed") from exc
                # OFDRW can follow resource references. Java 21's deny-by-default
                # policy confines reads to this copy/runtime/fonts, denies sockets
                # and process execution, and limits writes to this disposable dir.
                read_roots = [java.parent.parent, self.component_dir / "lib"]
                if os.name == "nt":
                    read_roots.append(Path(os.environ.get("SystemRoot", "C:/Windows")) / "Fonts")
                    read_roots.append(Path.home() / "AppData/Local/Microsoft/Windows/Fonts")
                else:
                    read_roots.extend([Path("/System/Library/Fonts"), Path("/Library/Fonts"), Path.home() / "Library/Fonts"])
                policy = ['grant {', 'permission java.util.PropertyPermission "*", "read,write";',
                          'permission java.lang.RuntimePermission "accessDeclaredMembers";',
                          'permission java.lang.RuntimePermission "setIO";',
                          'permission java.lang.RuntimePermission "getClassLoader";',
                          'permission java.lang.RuntimePermission "loadLibrary.*";',
                          'permission java.lang.reflect.ReflectPermission "suppressAccessChecks";']
                for base in read_roots:
                    policy.append(f'permission java.io.FilePermission "{_policy_path(base)}/-", "read";')
                    policy.append(f'permission java.io.FilePermission "{_policy_path(base)}", "read";')
                policy.extend([f'permission java.io.FilePermission "{_policy_path(temp)}/-", "read,write,delete";',
                               f'permission java.io.FilePermission "{_policy_path(temp)}", "read";', '};'])
                policy_file = temp / "preview.policy"
                policy_file.write_text("\n".join(policy), encoding="utf-8")
                command = [str(java), "-Xms16m", "-Xmx384m", "-XX:ActiveProcessorCount=2",
                           "-Djava.awt.headless=true", "-Djava.security.manager=default",
                           f"-Djava.security.policy=={policy_file}", f"-Djava.io.tmpdir={temp}",
                           f"-Duser.home={temp}", "-cp", os.pathsep.join(map(str, jars)),
                           "com.invoicehub.ofd.Preview", str(document), str(page_number)]
                # Never forward host RPC secrets, Java injection options or proxies.
                env = {key: os.environ[key] for key in ("SystemRoot", "WINDIR", "LANG") if key in os.environ}
                env.update({"TMP": str(temp), "TEMP": str(temp), "TMPDIR": str(temp)})
                try:
                    result = subprocess.run(command, cwd=temp, env=env, stdin=subprocess.DEVNULL,
                                            stdout=subprocess.PIPE, stderr=subprocess.DEVNULL,
                                            timeout=RENDER_TIMEOUT, check=False,
                                            creationflags=subprocess.CREATE_NO_WINDOW if os.name == "nt" else 0)
                except subprocess.TimeoutExpired as exc:
                    raise OFDPreviewError("ofd_render_timeout") from exc
                except OSError as exc:
                    raise OFDPreviewError("ofd_renderer_unavailable") from exc
                if result.returncode == 3:
                    raise OFDPreviewError("ofd_font_unavailable")
                if result.returncode or len(result.stdout) < 16:
                    raise OFDPreviewError("ofd_render_failed")
                magic, width, height, length = struct.unpack(">4I", result.stdout[:16])
                png = result.stdout[16:]
                if (magic != 0x49484F31 or not 0 < width * height <= MAX_PIXELS
                        or not width or not height or length != len(png) or length > MAX_PNG_BYTES
                        or not png.startswith(b"\x89PNG\r\n\x1a\n") or len(png) < 24
                        or struct.unpack(">2I", png[16:24]) != (width, height)):
                    raise OFDPreviewError("ofd_render_failed")
                return MuPDFPageImage(png, width, height, "landscape" if width > height else "portrait")
        finally:
            _RENDER_SLOT.release()
