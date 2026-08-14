from __future__ import annotations

import json
import mimetypes
import os
import re
import shutil
import uuid
import zipfile
from dataclasses import dataclass
from io import BytesIO
from pathlib import Path, PurePosixPath
from typing import Any
from urllib.parse import unquote

from invoice_hub.domain.models import utc_now_text
from invoice_hub.storage import atomic_write_json, read_json_object
from invoice_hub.targets.paths import Layout


MAX_SKIN_ZIP_BYTES = 10 * 1024 * 1024
MAX_SKIN_FILE_BYTES = 2 * 1024 * 1024
MAX_SKIN_TOTAL_BYTES = 8 * 1024 * 1024
MAX_SKIN_FILES = 64

STATE_FILE_NAME = "skin_state.json"
MANIFEST_FILE_NAME = "skin.json"
BUILTIN_ENTRYPOINT = "skin.css"
SKIN_ID_RE = re.compile(r"^[a-z0-9][a-z0-9-]{0,63}$")
CSS_IMPORT_RE = re.compile(r"@import\b", re.IGNORECASE)
CSS_URL_RE = re.compile(r"url\(\s*([^)]*?)\s*\)", re.IGNORECASE | re.DOTALL)

ALLOWED_ASSET_EXTENSIONS = {
    ".css",
    ".png",
    ".jpg",
    ".jpeg",
    ".webp",
    ".gif",
    ".woff",
    ".woff2",
}
ALLOWED_METADATA_BASENAMES = {
    "asset-sources.json",
    "license",
    "license.txt",
    "license.md",
    "copying",
    "copying.txt",
    "copying.md",
    "copyright",
    "copyright.txt",
    "copyright.md",
}
BLOCKED_EXTENSIONS = {
    ".bat",
    ".cmd",
    ".com",
    ".cpl",
    ".dll",
    ".exe",
    ".hta",
    ".htm",
    ".html",
    ".jar",
    ".js",
    ".jse",
    ".mjs",
    ".msi",
    ".ps1",
    ".py",
    ".pyc",
    ".pyo",
    ".pyw",
    ".scr",
    ".sh",
    ".vbs",
    ".wsf",
}


class SkinServiceError(ValueError):
    def __init__(self, message: str, status_code: int = 400):
        super().__init__(message)
        self.status_code = status_code


@dataclass(frozen=True)
class SkinFile:
    path: Path | None
    content: bytes | None
    media_type: str


@dataclass(frozen=True)
class SkinPackage:
    manifest: dict[str, Any]
    files: dict[str, bytes]


PROJECT_ROOT = Path(__file__).resolve().parents[3]
BUILTIN_SKINS: dict[str, dict[str, Any]] = {
    "animal-island": {
        "id": "animal-island",
        "name": "Animal Island",
        "description": "动森风格的可选内置皮肤，使用本地开源字体子集、原创纸纹与柔和 3D 控件。",
        "version": "2.0.8",
        "entry": BUILTIN_ENTRYPOINT,
        "entrypoint": BUILTIN_ENTRYPOINT,
    },
    "ink-pulse": {
        "id": "ink-pulse",
        "name": "Ink Pulse 墨潮电波",
        "description": "原创喷墨街头风内置皮肤：栅格喷溅、印刷拼贴纹理、趣味展示字体与硬阴影。",
        "version": "1.3.0",
        "entry": BUILTIN_ENTRYPOINT,
        "entrypoint": BUILTIN_ENTRYPOINT,
    },
}


def _safe_package_path(raw: str) -> str:
    text = str(raw or "").replace("\\", "/").strip()
    if not text or text.endswith("/"):
        raise SkinServiceError("Skin file path is empty.")
    pure = PurePosixPath(text)
    if pure.is_absolute() or text.startswith(("/", "\\")):
        raise SkinServiceError(f"Absolute skin paths are not allowed: {raw}")
    if any(part in {"", ".", ".."} for part in pure.parts):
        raise SkinServiceError(f"Unsafe skin path is not allowed: {raw}")
    if any(":" in part for part in pure.parts):
        raise SkinServiceError(f"Drive or scheme-like skin paths are not allowed: {raw}")
    return pure.as_posix()


def _is_zip_symlink(info: zipfile.ZipInfo) -> bool:
    return ((info.external_attr >> 16) & 0o170000) == 0o120000


def _should_ignore_zip_entry(raw: str) -> bool:
    text = str(raw or "").replace("\\", "/").strip()
    if not text:
        return True
    parts = [part for part in PurePosixPath(text).parts if part not in {"", "."}]
    if not parts:
        return True
    lowered = [part.casefold() for part in parts]
    if lowered[0] == "__macosx":
        return True
    if any(part.startswith("._") for part in parts):
        return True
    return lowered[-1] in {".ds_store", "thumbs.db"}


def _common_wrapper_prefix(paths: list[str]) -> str:
    if not paths:
        return ""
    first_parts = [PurePosixPath(path).parts for path in paths]
    if any(len(parts) < 2 for parts in first_parts):
        return ""
    root = first_parts[0][0]
    if all(parts[0] == root for parts in first_parts):
        return f"{root}/"
    return ""


def _normalize_skin_id(value: object) -> str:
    skin_id = str(value or "").strip().casefold()
    if not SKIN_ID_RE.fullmatch(skin_id):
        raise SkinServiceError("skin.json must contain id using lowercase letters, numbers, or '-'.")
    return skin_id


def _validate_css(path: str, data: bytes, files: set[str] | None = None) -> None:
    try:
        text = data.decode("utf-8-sig")
    except UnicodeDecodeError as exc:
        raise SkinServiceError(f"CSS file must be UTF-8 text: {path}") from exc
    if CSS_IMPORT_RE.search(text):
        raise SkinServiceError(f"CSS @import is not allowed: {path}")
    for match in CSS_URL_RE.finditer(text):
        raw = match.group(1).strip().strip("\"'")
        decoded = unquote(raw).strip()
        lowered = decoded.casefold()
        if not decoded or lowered.startswith("#"):
            continue
        if "\\" in decoded:
            raise SkinServiceError(f"CSS url() must use package-relative paths: {path}")
        if lowered.startswith(("//", "/", "data:", "javascript:")):
            raise SkinServiceError(f"CSS url() cannot reference external or executable content: {path}")
        if re.match(r"^[a-z][a-z0-9+.-]*:", lowered):
            raise SkinServiceError(f"CSS url() schemes are not allowed: {path}")
        pure = PurePosixPath(decoded)
        if pure.is_absolute() or any(part in {"", ".", ".."} for part in pure.parts):
            raise SkinServiceError(f"CSS url() must stay inside the skin package: {path}")
        package_path = _safe_package_path(decoded)
        if files is not None and package_path not in files:
            raise SkinServiceError(f"CSS url() target is missing from skin package: {path}")


def _validate_manifest(payload: bytes, files: dict[str, bytes]) -> dict[str, Any]:
    try:
        raw = json.loads(payload.decode("utf-8-sig"))
    except Exception as exc:
        raise SkinServiceError("skin.json must be valid UTF-8 JSON.") from exc
    if not isinstance(raw, dict):
        raise SkinServiceError("skin.json must be a JSON object.")
    for key in ("id", "name", "version", "entry"):
        if not str(raw.get(key) or "").strip():
            raise SkinServiceError(f"skin.json must contain {key}.")
    skin_id = _normalize_skin_id(raw.get("id"))
    if skin_id in BUILTIN_SKINS:
        raise SkinServiceError("Imported skin id conflicts with a built-in skin.", status_code=409)
    css_files = sorted(path for path in files if Path(path).suffix.casefold() == ".css")
    if not css_files:
        raise SkinServiceError("Skin ZIP must include at least one CSS file.")
    entrypoint = _safe_package_path(str(raw.get("entry") or "").strip().replace("\\", "/"))
    if entrypoint not in files or Path(entrypoint).suffix.casefold() != ".css":
        raise SkinServiceError("skin.json entry must reference a CSS file in the ZIP.")
    return {
        "id": skin_id,
        "name": str(raw.get("name") or skin_id).strip()[:80],
        "description": str(raw.get("description") or "").strip()[:240],
        "version": str(raw.get("version") or "").strip()[:40],
        "entry": entrypoint,
        "entrypoint": entrypoint,
    }


def _is_allowed_metadata_path(path: str) -> bool:
    pure = PurePosixPath(path)
    name = pure.name.casefold()
    if name in ALLOWED_METADATA_BASENAMES:
        return True
    if name.startswith("ofl-") and pure.suffix.casefold() in {".txt", ".md"}:
        return True
    return False


def validate_skin_zip(payload: bytes) -> SkinPackage:
    if not payload:
        raise SkinServiceError("Skin ZIP body is empty.")
    if len(payload) > MAX_SKIN_ZIP_BYTES:
        raise SkinServiceError("Skin ZIP is too large.")
    try:
        archive = zipfile.ZipFile(BytesIO(payload))
    except zipfile.BadZipFile as exc:
        raise SkinServiceError("Uploaded skin is not a valid ZIP file.") from exc
    with archive:
        files: dict[str, bytes] = {}
        total_size = 0
        entries = [
            (info, str(info.filename or "").replace("\\", "/").strip())
            for info in archive.infolist()
            if not info.is_dir() and not _should_ignore_zip_entry(info.filename)
        ]
        wrapper_prefix = _common_wrapper_prefix([name for _info, name in entries])
        for info, raw_name in entries:
            if _is_zip_symlink(info):
                raise SkinServiceError(f"Symlinks are not allowed in skin ZIP: {info.filename}")
            if info.flag_bits & 0x1:
                raise SkinServiceError("Encrypted ZIP entries are not allowed.")
            candidate = raw_name[len(wrapper_prefix):] if wrapper_prefix and raw_name.startswith(wrapper_prefix) else raw_name
            path = _safe_package_path(candidate)
            if path in files:
                raise SkinServiceError(f"Duplicate skin file path is not allowed: {path}")
            suffix = Path(path).suffix.casefold()
            if path == MANIFEST_FILE_NAME:
                pass
            elif suffix in BLOCKED_EXTENSIONS:
                raise SkinServiceError(f"Executable or script files are not allowed in skins: {path}")
            elif _is_allowed_metadata_path(path):
                pass
            elif suffix not in ALLOWED_ASSET_EXTENSIONS:
                raise SkinServiceError(f"Unsupported skin asset type: {path}")
            if info.file_size > MAX_SKIN_FILE_BYTES:
                raise SkinServiceError(f"Skin file is too large: {path}")
            total_size += int(info.file_size)
            if total_size > MAX_SKIN_TOTAL_BYTES:
                raise SkinServiceError("Skin ZIP uncompressed content is too large.")
            if len(files) + 1 > MAX_SKIN_FILES:
                raise SkinServiceError("Skin ZIP contains too many files.")
            data = archive.read(info)
            if len(data) != info.file_size:
                raise SkinServiceError(f"Skin ZIP entry size mismatch: {path}")
            files[path] = data
        if MANIFEST_FILE_NAME not in files:
            raise SkinServiceError("Skin ZIP must include skin.json at the package root.")
        package_paths = set(files.keys())
        for path, data in files.items():
            if Path(path).suffix.casefold() == ".css":
                _validate_css(path, data, package_paths)
        manifest = _validate_manifest(files[MANIFEST_FILE_NAME], files)
        return SkinPackage(manifest=manifest, files=files)


class SkinService:
    def __init__(self, layout: Layout):
        self.layout = layout
        self.storage_root = layout.runtime_dir / "local_state" / "skins"
        self.imported_root = self.storage_root / "imported"
        self.state_path = self.storage_root / STATE_FILE_NAME
        packaged_builtin_root = layout.root_dir / "web" / "static" / "skins"
        self.builtin_root = packaged_builtin_root if packaged_builtin_root.exists() else PROJECT_ROOT / "web" / "static" / "skins"

    def ensure_storage(self) -> None:
        self.imported_root.mkdir(parents=True, exist_ok=True)

    def storage_paths(self) -> dict[str, str]:
        return {
            "root": str(self.storage_root),
            "imported": str(self.imported_root),
            "state": str(self.state_path),
        }

    def list_skins(self) -> dict[str, Any]:
        self.ensure_storage()
        skins = [self._skin_payload(manifest, builtin=True) for manifest in BUILTIN_SKINS.values()]
        skins.extend(self._skin_payload(manifest, builtin=False) for manifest in self._imported_manifests())
        enabled_skin_id = self._enabled_skin_id()
        if enabled_skin_id and not any(item["id"] == enabled_skin_id for item in skins):
            enabled_skin_id = ""
        active_skin = None
        for item in skins:
            item["enabled"] = item["id"] == enabled_skin_id
            if item["enabled"]:
                active_skin = dict(item)
        return {
            "ok": True,
            "default_skin_id": None,
            "enabled_skin_id": enabled_skin_id or None,
            "active_skin": active_skin,
            "skins": skins,
            "storage": self.storage_paths(),
        }

    def import_skin(self, payload: bytes, replace: bool = False, expected_skin_id: str | None = None) -> dict[str, Any]:
        package = validate_skin_zip(payload)
        skin_id = package.manifest["id"]
        if expected_skin_id:
            expected = _normalize_skin_id(expected_skin_id)
            if expected != skin_id:
                raise SkinServiceError("Replacement ZIP skin id must match the selected skin.")
        self.ensure_storage()
        destination = self._imported_dir(skin_id)
        if destination.exists() and not replace:
            raise SkinServiceError("Imported skin already exists. Use replace to overwrite it.", status_code=409)
        temp_dir = self.storage_root / f".import-{uuid.uuid4().hex}"
        try:
            temp_dir.mkdir(parents=True)
            for path, data in package.files.items():
                target = temp_dir / path
                self._assert_child(target, temp_dir)
                target.parent.mkdir(parents=True, exist_ok=True)
                if path == MANIFEST_FILE_NAME:
                    continue
                target.write_bytes(data)
            (temp_dir / MANIFEST_FILE_NAME).write_text(json.dumps(package.manifest, ensure_ascii=False, indent=2), encoding="utf-8")
            if destination.exists():
                shutil.rmtree(destination)
            os.replace(temp_dir, destination)
        finally:
            if temp_dir.exists():
                shutil.rmtree(temp_dir, ignore_errors=True)
        return {"ok": True, "skin": self._skin_payload(package.manifest, builtin=False), "replaced": bool(replace)}

    def enable_skin(self, skin_id: str) -> dict[str, Any]:
        skin_id = _normalize_skin_id(skin_id)
        if not self._find_manifest(skin_id):
            raise SkinServiceError("Skin not found.", status_code=404)
        self._write_state({"enabled_skin_id": skin_id, "updated_at": utc_now_text()})
        payload = self.list_skins()
        payload["enabled"] = True
        return payload

    def reset_skin(self) -> dict[str, Any]:
        self._write_state({"enabled_skin_id": "", "updated_at": utc_now_text()})
        payload = self.list_skins()
        payload["reset"] = True
        return payload

    def get_file(self, skin_id: str, path: str) -> SkinFile:
        skin_id = _normalize_skin_id(skin_id)
        package_path = _safe_package_path(path)
        manifest = self._find_manifest(skin_id)
        if not manifest:
            raise SkinServiceError("Skin not found.", status_code=404)
        suffix = Path(package_path).suffix.casefold()
        if suffix != ".css" and suffix not in ALLOWED_ASSET_EXTENSIONS:
            raise SkinServiceError("Unsupported skin file type.", status_code=404)
        media_type = _media_type(package_path)
        if skin_id in BUILTIN_SKINS:
            target = self._builtin_file_path(skin_id, package_path)
            if not target.exists() or not target.is_file():
                raise SkinServiceError("Skin file not found.", status_code=404)
            data = target.read_bytes()
            return SkinFile(path=None, content=data, media_type=media_type)
        root = self._imported_dir(skin_id)
        target = root / package_path
        self._assert_child(target, root)
        if not target.exists() or not target.is_file():
            raise SkinServiceError("Skin file not found.", status_code=404)
        return SkinFile(path=target, content=None, media_type=media_type)

    def _enabled_skin_id(self) -> str:
        state = read_json_object(self.state_path, {})
        return str(state.get("enabled_skin_id") or "").strip()

    def _write_state(self, payload: dict[str, Any]) -> None:
        atomic_write_json(self.state_path, payload)

    def _imported_dir(self, skin_id: str) -> Path:
        path = self.imported_root / skin_id
        self._assert_child(path, self.imported_root)
        return path

    def _builtin_file_path(self, skin_id: str, package_path: str) -> Path:
        root = self.builtin_root / skin_id
        target = root / package_path
        self._assert_child(target, root)
        return target

    @staticmethod
    def _assert_child(path: Path, parent: Path) -> None:
        resolved_parent = parent.resolve()
        resolved_path = path.resolve()
        if resolved_path != resolved_parent and not resolved_path.is_relative_to(resolved_parent):
            raise SkinServiceError("Skin path escapes the storage directory.")

    def _find_manifest(self, skin_id: str) -> dict[str, Any] | None:
        if skin_id in BUILTIN_SKINS:
            return dict(BUILTIN_SKINS[skin_id])
        path = self._imported_dir(skin_id) / MANIFEST_FILE_NAME
        if not path.exists():
            return None
        payload = read_json_object(path, {})
        if not isinstance(payload, dict):
            return None
        try:
            payload["id"] = _normalize_skin_id(payload.get("id"))
        except SkinServiceError:
            return None
        return payload

    def _imported_manifests(self) -> list[dict[str, Any]]:
        self.ensure_storage()
        manifests: list[dict[str, Any]] = []
        for child in sorted(self.imported_root.iterdir(), key=lambda item: item.name.casefold()):
            if not child.is_dir():
                continue
            manifest = self._find_manifest(child.name)
            if manifest:
                manifests.append(manifest)
        return manifests

    def _skin_payload(self, manifest: dict[str, Any], builtin: bool) -> dict[str, Any]:
        skin_id = str(manifest.get("id") or "")
        entrypoint = str(manifest.get("entry") or manifest.get("entrypoint") or BUILTIN_ENTRYPOINT)
        version_token = self._version_token(skin_id, entrypoint, builtin)
        stylesheet_url = f"/api/v1/skins/{skin_id}/files/{entrypoint}"
        if version_token:
            stylesheet_url = f"{stylesheet_url}?v={version_token}"
        payload = {
            "id": skin_id,
            "name": str(manifest.get("name") or skin_id),
            "description": str(manifest.get("description") or ""),
            "version": str(manifest.get("version") or ""),
            "entry": entrypoint,
            "entrypoint": entrypoint,
            "stylesheet_url": stylesheet_url,
            "asset_base_url": f"/api/v1/skins/{skin_id}/files/",
            "version_token": version_token,
            "builtin": builtin,
            "imported": not builtin,
            "read_only": builtin,
            "enabled": False,
        }
        if not builtin:
            payload["storage_dir"] = str(self._imported_dir(skin_id))
        return payload

    def _version_token(self, skin_id: str, entrypoint: str, builtin: bool) -> str:
        try:
            path = self._builtin_file_path(skin_id, entrypoint) if builtin else self._imported_dir(skin_id) / entrypoint
            stat = path.stat()
            return f"{stat.st_mtime_ns:x}-{stat.st_size:x}"
        except OSError:
            return str(BUILTIN_SKINS.get(skin_id, {}).get("version") or "")


def _media_type(path: str) -> str:
    if Path(path).suffix.casefold() == ".css":
        return "text/css"
    guessed, _encoding = mimetypes.guess_type(path)
    return guessed or "application/octet-stream"
