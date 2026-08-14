from __future__ import annotations

import argparse
import json
import re
from pathlib import Path, PurePosixPath
from typing import Literal, Sequence


TEXT_SUFFIXES = {
    ".bat",
    ".cfg",
    ".css",
    ".csv",
    ".html",
    ".in",
    ".ini",
    ".js",
    ".json",
    ".lock",
    ".md",
    ".plist",
    ".ps1",
    ".psm1",
    ".py",
    ".pyi",
    ".resolved",
    ".rst",
    ".sh",
    ".swift",
    ".toml",
    ".txt",
    ".xml",
    ".yaml",
    ".yml",
}
TEXT_FILENAMES = {"dockerfile", "license", "makefile"}
HIGH_CONFIDENCE_SECRET_PATTERNS = (
    re.compile(rb"gh[pousr]_[A-Za-z0-9_]{20,}"),
    re.compile(rb"-----BEGIN " + rb"(?:RSA |EC |OPENSSH )?" + rb"PRIVATE KEY-----"),
)
PROJECT_SECRET_PATTERNS = (
    *HIGH_CONFIDENCE_SECRET_PATTERNS,
    re.compile(rb"(?i)(?:password|passwd|api[_-]?key|access[_-]?token)\s*[:=]\s*['\"][^'\"\r\n]{8,}"),
)
LOCAL_PATH_PATTERNS = (
    re.compile(rb"[A-Za-z]:\\Users\\[A-Za-z0-9._-]{1,80}\\"),
    re.compile(rb"/" + rb"Users/[A-Za-z0-9._-]{1,80}/"),
    re.compile(rb"/" + rb"home/[A-Za-z0-9._-]{1,80}/"),
)


class ReleaseContentError(ValueError):
    pass


ScanScope = Literal["project", "dependency"]


def _is_scannable_text(name: str) -> bool:
    path = PurePosixPath(name)
    return path.suffix.casefold() in TEXT_SUFFIXES or path.name.casefold() in TEXT_FILENAMES


def scan_release_text(name: str, content: bytes, *, scope: ScanScope = "project") -> None:
    if scope not in {"project", "dependency"}:
        raise ValueError(f"unknown release content scan scope: {scope}")
    if not _is_scannable_text(name):
        return
    secret_patterns = PROJECT_SECRET_PATTERNS if scope == "project" else HIGH_CONFIDENCE_SECRET_PATTERNS
    for pattern in secret_patterns:
        if pattern.search(content):
            raise ReleaseContentError(f"possible secret found in {name}")
    if scope == "project":
        for pattern in LOCAL_PATH_PATTERNS:
            if pattern.search(content):
                raise ReleaseContentError(f"possible local absolute path found in {name}")


def _normalize_dependency_prefix(value: str) -> PurePosixPath:
    normalized = value.strip().strip("/")
    path = PurePosixPath(normalized)
    if not normalized or "\\" in normalized or any(part in {"", ".", ".."} for part in path.parts):
        raise ValueError(f"invalid dependency prefix: {value!r}")
    return path


def scan_release_tree(root: Path, *, dependency_prefixes: Sequence[str] = ()) -> int:
    root = Path(root).resolve()
    if not root.is_dir():
        raise ReleaseContentError(f"release scan root is not a directory: {root}")
    prefixes = tuple(_normalize_dependency_prefix(value) for value in dependency_prefixes)
    scanned = 0
    for path in sorted(root.rglob("*")):
        if path.is_symlink() or not path.is_file():
            continue
        relative = PurePosixPath(path.relative_to(root).as_posix())
        dependency = any(relative == prefix or relative.is_relative_to(prefix) for prefix in prefixes)
        if _is_scannable_text(relative.as_posix()):
            scanned += 1
        scan_release_text(relative.as_posix(), path.read_bytes(), scope="dependency" if dependency else "project")
    return scanned


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Scan release content for credentials and local machine paths")
    parser.add_argument("--root", type=Path, required=True)
    parser.add_argument("--dependency-prefix", action="append", default=[])
    args = parser.parse_args(argv)
    try:
        scanned = scan_release_tree(args.root, dependency_prefixes=args.dependency_prefix)
    except (ReleaseContentError, ValueError) as exc:
        parser.exit(1, f"release content scan failed: {exc}\n")
    print(json.dumps({"ok": True, "root": str(args.root.resolve()), "scanned_text_files": scanned}, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
