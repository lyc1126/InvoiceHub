from __future__ import annotations

import argparse
import gzip
import hashlib
import io
import json
import re
import subprocess
import tarfile
import tempfile
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path, PurePosixPath
from typing import Any

from invoice_hub.release.build_manifest import deterministic_build_id
from invoice_hub.release.content_scan import ReleaseContentError, scan_release_text
from invoice_hub.release.package_manifest import SHA256_PATTERN
from invoice_hub.release.runtime_manifest import sha256_file
from invoice_hub.version import PRODUCT_VERSION, RELEASE_TAG


SOURCE_MANIFEST_NAME = "invoice-hub-source.json"
SOURCE_ARCHIVE_NAME = f"InvoiceHub-v{PRODUCT_VERSION}-source.tar.gz"
COMMIT_PATTERN = re.compile(r"^[0-9a-f]{40}$")
FORBIDDEN_PATHS = {"config/app.local.json"}
FORBIDDEN_PARTS = {".git", ".venv", "dist", "release-staging", "runtime", "运行状态", "wheelhouse", "__pycache__"}
REQUIRED_PATHS = {
    "LICENSE",
    "THIRD_PARTY_NOTICES.md",
    "pyproject.toml",
    "requirements/windows-x64-py314.lock",
    "requirements/macos-arm64-py314.lock",
    "docs/release/WINDOWS_REPACKAGE_CONFIG.json",
    "docs/release/HISTORY_SANITIZATION_EXECUTION.md",
    "scripts/dev/build_windows_portable.ps1",
    "scripts/dev/windows_release_config.ps1",
    "scripts/dev/initialize_windows_repackage.ps1",
    "scripts/dev/prepare_windows_test_environment.ps1",
    "macos/InvoiceHubMac/script/build_release.sh",
    ".github/workflows/ci.yml",
}


class SourceSnapshotError(ValueError):
    pass


@dataclass(frozen=True)
class SourceSnapshotResult:
    archive_path: Path
    archive_sha256: str
    source_tree_sha256: str
    source_commit: str
    core_build_id: str


@dataclass(frozen=True)
class SourceSnapshotInspection:
    archive_path: Path
    archive_sha256: str
    product_version: str
    release_tag: str
    source_commit: str
    core_build_id: str
    source_tree_sha256: str
    tracked_file_count: int


@dataclass(frozen=True)
class TaggedSourceTreeInspection:
    release_tag: str
    source_commit: str
    core_build_id: str
    source_tree_sha256: str
    tracked_file_count: int


def _run_git(root: Path, arguments: list[str], *, binary: bool = False) -> bytes | str:
    try:
        completed = subprocess.run(
            ["git", "-C", str(root), *arguments],
            check=True,
            capture_output=True,
            text=not binary,
        )
    except (OSError, subprocess.CalledProcessError) as exc:
        stderr = getattr(exc, "stderr", b"" if binary else "")
        raise SourceSnapshotError(f"Git command failed: {' '.join(arguments)}: {stderr}") from exc
    return completed.stdout


def _safe_path(name: str) -> PurePosixPath:
    path = PurePosixPath(name)
    if not name or name.startswith("/") or "\\" in name or any(part in {"", ".", ".."} for part in path.parts):
        raise SourceSnapshotError(f"unsafe source archive path: {name!r}")
    if name in FORBIDDEN_PATHS or any(part in FORBIDDEN_PARTS for part in path.parts):
        raise SourceSnapshotError(f"forbidden source archive path: {name}")
    return path


def _read_git_archive(root: Path, source_commit: str) -> dict[str, tuple[bytes, int]]:
    archive_bytes = _run_git(root, ["archive", "--format=tar", source_commit], binary=True)
    assert isinstance(archive_bytes, bytes)
    result: dict[str, tuple[bytes, int]] = {}
    with tarfile.open(fileobj=io.BytesIO(archive_bytes), mode="r:") as archive:
        for member in archive.getmembers():
            if member.isdir():
                continue
            _safe_path(member.name)
            if not member.isfile():
                raise SourceSnapshotError(f"source snapshot forbids links and special files: {member.name}")
            handle = archive.extractfile(member)
            if handle is None:
                raise SourceSnapshotError(f"cannot read source archive member: {member.name}")
            content = handle.read()
            try:
                scan_release_text(member.name, content)
            except ReleaseContentError as exc:
                raise SourceSnapshotError(str(exc)) from exc
            result[member.name] = (content, 0o755 if member.mode & 0o111 else 0o644)
    missing = REQUIRED_PATHS - set(result)
    if missing:
        raise SourceSnapshotError("source snapshot is incomplete: " + ", ".join(sorted(missing)))
    return result


def _tree_sha256(files: dict[str, tuple[bytes, int]]) -> str:
    digest = hashlib.sha256()
    for name, (content, mode) in sorted(files.items()):
        digest.update(name.encode("utf-8"))
        digest.update(b"\0")
        digest.update(str(mode).encode("ascii"))
        digest.update(b"\0")
        digest.update(hashlib.sha256(content).digest())
        digest.update(b"\0")
    return digest.hexdigest()


def _rebuild_core_build_id(files: dict[str, tuple[bytes, int]], *, label: str) -> str:
    """Calculate the shared-core identity from an already validated file tree."""

    with tempfile.TemporaryDirectory(prefix="invoicehub-source-inspect-") as temporary:
        root = Path(temporary)
        for name, (content, mode) in files.items():
            path = root / name
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_bytes(content)
            path.chmod(mode)
        try:
            return deterministic_build_id(root)
        except (OSError, ValueError, FileNotFoundError) as exc:
            raise SourceSnapshotError(f"{label} cannot reproduce the shared core: {exc}") from exc


def inspect_tagged_source_tree(source_checkout: Path, release_tag: str) -> TaggedSourceTreeInspection:
    """Rebuild release identity from a tag object, never from the checkout worktree."""

    source_checkout = Path(source_checkout).resolve()
    release_tag = str(release_tag or "").strip()
    if not source_checkout.is_dir():
        raise SourceSnapshotError(f"source checkout is not a directory: {source_checkout}")
    if not release_tag:
        raise SourceSnapshotError("release tag is required")
    tagged_commit = str(
        _run_git(source_checkout, ["rev-parse", "--verify", f"refs/tags/{release_tag}^{{commit}}"])
    ).strip().casefold()
    if not COMMIT_PATTERN.fullmatch(tagged_commit):
        raise SourceSnapshotError(f"release tag does not resolve to a 40-character commit: {release_tag}")
    files = _read_git_archive(source_checkout, tagged_commit)
    return TaggedSourceTreeInspection(
        release_tag=release_tag,
        source_commit=tagged_commit,
        core_build_id=_rebuild_core_build_id(files, label="tagged source tree"),
        source_tree_sha256=_tree_sha256(files),
        tracked_file_count=len(files),
    )


def _source_manifest(files: dict[str, tuple[bytes, int]]) -> dict[str, Any]:
    manifest_entry = files.pop(SOURCE_MANIFEST_NAME, None)
    if manifest_entry is None:
        raise SourceSnapshotError(f"source snapshot is missing {SOURCE_MANIFEST_NAME}")
    try:
        payload = json.loads(manifest_entry[0].decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise SourceSnapshotError("source snapshot manifest is invalid") from exc
    if not isinstance(payload, dict) or payload.get("schema_version") != 1:
        raise SourceSnapshotError("source snapshot manifest schema_version is invalid")
    return payload


def _snapshot_text(payload: dict[str, Any], key: str) -> str:
    value = payload.get(key)
    if not isinstance(value, str) or not value.strip():
        raise SourceSnapshotError(f"source snapshot manifest field {key!r} is invalid")
    return value.strip()


def inspect_source_snapshot(archive_path: Path) -> SourceSnapshotInspection:
    """Verify a source archive before it is allowed to prove a release identity."""

    archive_path = Path(archive_path).resolve()
    if archive_path.name != SOURCE_ARCHIVE_NAME:
        raise SourceSnapshotError(
            f"source snapshot filename mismatch: expected {SOURCE_ARCHIVE_NAME}, got {archive_path.name}"
        )
    if not archive_path.is_file():
        raise SourceSnapshotError(f"source snapshot does not exist: {archive_path}")

    files: dict[str, tuple[bytes, int]] = {}
    try:
        with tarfile.open(archive_path, "r:gz") as archive:
            for member in archive.getmembers():
                if member.isdir():
                    continue
                _safe_path(member.name)
                if member.name in files:
                    raise SourceSnapshotError(f"duplicate source archive member: {member.name}")
                if not member.isfile():
                    raise SourceSnapshotError(f"source snapshot forbids links and special files: {member.name}")
                handle = archive.extractfile(member)
                if handle is None:
                    raise SourceSnapshotError(f"cannot read source archive member: {member.name}")
                content = handle.read()
                if member.name != SOURCE_MANIFEST_NAME:
                    try:
                        scan_release_text(member.name, content)
                    except ReleaseContentError as exc:
                        raise SourceSnapshotError(str(exc)) from exc
                files[member.name] = (content, 0o755 if member.mode & 0o111 else 0o644)
    except (OSError, tarfile.TarError) as exc:
        raise SourceSnapshotError(f"cannot read source snapshot: {exc}") from exc

    manifest = _source_manifest(files)
    missing = REQUIRED_PATHS - set(files)
    if missing:
        raise SourceSnapshotError("source snapshot is incomplete: " + ", ".join(sorted(missing)))
    product_version = _snapshot_text(manifest, "product_version")
    release_tag = _snapshot_text(manifest, "release_tag")
    source_commit = _snapshot_text(manifest, "source_commit").casefold()
    core_build_id = _snapshot_text(manifest, "core_build_id").casefold()
    source_tree_sha256 = _snapshot_text(manifest, "source_tree_sha256").casefold()
    tracked_file_count = manifest.get("tracked_file_count")
    if product_version != PRODUCT_VERSION or release_tag != RELEASE_TAG:
        raise SourceSnapshotError("source snapshot version or release tag does not match this release")
    if not COMMIT_PATTERN.fullmatch(source_commit):
        raise SourceSnapshotError("source snapshot source_commit is invalid")
    if not SHA256_PATTERN.fullmatch(core_build_id) or not SHA256_PATTERN.fullmatch(source_tree_sha256):
        raise SourceSnapshotError("source snapshot hash identity is invalid")
    if not isinstance(tracked_file_count, int) or isinstance(tracked_file_count, bool) or tracked_file_count != len(files):
        raise SourceSnapshotError("source snapshot tracked_file_count does not match its contents")
    if source_tree_sha256 != _tree_sha256(files):
        raise SourceSnapshotError("source snapshot source_tree_sha256 does not match its contents")

    # Recompute the shared core identity from the archived source, rather than
    # trusting the core_build_id embedded in the archive manifest.
    calculated_core_build_id = _rebuild_core_build_id(files, label="source snapshot")
    if calculated_core_build_id != core_build_id:
        raise SourceSnapshotError("source snapshot core_build_id does not match its archived source")

    return SourceSnapshotInspection(
        archive_path=archive_path,
        archive_sha256=sha256_file(archive_path),
        product_version=product_version,
        release_tag=release_tag,
        source_commit=source_commit,
        core_build_id=core_build_id,
        source_tree_sha256=source_tree_sha256,
        tracked_file_count=tracked_file_count,
    )


def export_source_snapshot(
    root: Path,
    output_dir: Path,
    *,
    source_commit: str,
    core_build_id: str,
) -> SourceSnapshotResult:
    root = Path(root).resolve()
    output_dir = Path(output_dir).resolve()
    source_commit = source_commit.strip().casefold()
    if not COMMIT_PATTERN.fullmatch(source_commit):
        raise SourceSnapshotError("source_commit must be a lowercase 40-character Git SHA")
    if not SHA256_PATTERN.fullmatch(core_build_id):
        raise SourceSnapshotError("core_build_id must be a lowercase SHA-256")
    head = str(_run_git(root, ["rev-parse", "HEAD"])).strip()
    if head != source_commit:
        raise SourceSnapshotError("HEAD does not match source_commit")
    tracked_status = str(_run_git(root, ["status", "--porcelain=v1", "--untracked-files=no"])).strip()
    if tracked_status:
        raise SourceSnapshotError("tracked source changes are present")
    timestamp = int(str(_run_git(root, ["show", "-s", "--format=%ct", source_commit])).strip())
    files = _read_git_archive(root, source_commit)
    tree_sha = _tree_sha256(files)
    manifest = {
        "schema_version": 1,
        "product_version": PRODUCT_VERSION,
        "release_tag": RELEASE_TAG,
        "source_commit": source_commit,
        "source_commit_time": datetime.fromtimestamp(timestamp, timezone.utc).isoformat().replace("+00:00", "Z"),
        "core_build_id": core_build_id,
        "source_tree_sha256": tree_sha,
        "tracked_file_count": len(files),
    }
    files[SOURCE_MANIFEST_NAME] = (
        (json.dumps(manifest, ensure_ascii=False, indent=2, sort_keys=True) + "\n").encode("utf-8"),
        0o644,
    )

    tar_buffer = io.BytesIO()
    with tarfile.open(fileobj=tar_buffer, mode="w", format=tarfile.PAX_FORMAT) as archive:
        for name, (content, mode) in sorted(files.items()):
            info = tarfile.TarInfo(name)
            info.size = len(content)
            info.mode = mode
            info.mtime = timestamp
            info.uid = 0
            info.gid = 0
            info.uname = ""
            info.gname = ""
            archive.addfile(info, io.BytesIO(content))
    output_dir.mkdir(parents=True, exist_ok=True)
    archive_path = output_dir / SOURCE_ARCHIVE_NAME
    with archive_path.open("wb") as raw_output:
        with gzip.GzipFile(filename="", mode="wb", compresslevel=9, fileobj=raw_output, mtime=timestamp) as compressed:
            compressed.write(tar_buffer.getvalue())
    digest = sha256_file(archive_path)
    archive_path.with_suffix(archive_path.suffix + ".sha256").write_text(
        f"{digest}  {archive_path.name}\n", encoding="ascii"
    )
    return SourceSnapshotResult(archive_path, digest, tree_sha, source_commit, core_build_id)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Export a deterministic, scanned, buildable InvoiceHub source snapshot")
    parser.add_argument("--root", type=Path, required=True)
    parser.add_argument("--output-dir", type=Path, required=True)
    parser.add_argument("--source-commit", required=True)
    parser.add_argument("--core-build-id", required=True)
    args = parser.parse_args(argv)
    result = export_source_snapshot(
        args.root,
        args.output_dir,
        source_commit=args.source_commit,
        core_build_id=args.core_build_id,
    )
    print(json.dumps(result.__dict__ | {"archive_path": str(result.archive_path)}, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
