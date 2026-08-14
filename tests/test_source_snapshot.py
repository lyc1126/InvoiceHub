from __future__ import annotations

import json
import shutil
import subprocess
import tarfile
from pathlib import Path

import pytest

from invoice_hub.release.build_manifest import deterministic_build_id
from invoice_hub.release.source_snapshot import (
    REQUIRED_PATHS,
    SourceSnapshotError,
    export_source_snapshot,
    inspect_source_snapshot,
    inspect_tagged_source_tree,
)
from invoice_hub.version import RELEASE_TAG


def _git(root: Path, *args: str) -> str:
    completed = subprocess.run(["git", "-C", str(root), *args], check=True, capture_output=True, text=True)
    return completed.stdout.strip()


def test_source_snapshot_requires_public_release_handoff_files() -> None:
    assert {
        "docs/release/WINDOWS_REPACKAGE_CONFIG.json",
        "docs/release/HISTORY_SANITIZATION_EXECUTION.md",
        "scripts/dev/windows_release_config.ps1",
        "scripts/dev/initialize_windows_repackage.ps1",
        "scripts/dev/prepare_windows_test_environment.ps1",
    } <= REQUIRED_PATHS


def _repository(tmp_path: Path) -> tuple[Path, str]:
    if shutil.which("git") is None:
        pytest.skip("git is required")
    root = tmp_path / "source"
    root.mkdir()
    _git(root, "init")
    _git(root, "config", "user.name", "InvoiceHub Test")
    _git(root, "config", "user.email", "invoicehub-test@example.invalid")
    for name in REQUIRED_PATHS | {
        "src/invoice_hub/__init__.py",
        "web/index.html",
        "scripts/tools/jierui_voucher_import.py",
        "docs/jierui/facts.json",
        "tests/test_sample.py",
    }:
        path = root / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(f"fixture: {name}\n", encoding="utf-8")
    _git(root, "add", ".")
    _git(root, "commit", "-m", "fixture")
    return root, _git(root, "rev-parse", "HEAD")


def test_source_snapshot_is_deterministic_complete_and_ignores_untracked_files(tmp_path: Path) -> None:
    root, commit = _repository(tmp_path)
    (root / "untracked-private-file.txt").write_text("do not package\n", encoding="utf-8")
    first = export_source_snapshot(root, tmp_path / "one", source_commit=commit, core_build_id="a" * 64)
    second = export_source_snapshot(root, tmp_path / "two", source_commit=commit, core_build_id="a" * 64)

    assert first.archive_sha256 == second.archive_sha256
    with tarfile.open(first.archive_path, "r:gz") as archive:
        names = set(archive.getnames())
        manifest = json.load(archive.extractfile("invoice-hub-source.json"))
    assert REQUIRED_PATHS <= names
    assert "untracked-private-file.txt" not in names
    assert manifest["source_commit"] == commit
    assert manifest["core_build_id"] == "a" * 64
    assert manifest["source_tree_sha256"] == first.source_tree_sha256


def test_source_snapshot_rejects_tracked_machine_path(tmp_path: Path) -> None:
    root, _commit = _repository(tmp_path)
    leak = root / "docs" / "leak.md"
    leak.parent.mkdir(exist_ok=True)
    local_path = "/" + "Users/alice/private/invoice.pdf"
    leak.write_text(f"local={local_path}\n", encoding="utf-8")
    _git(root, "add", ".")
    _git(root, "commit", "-m", "add leak")
    commit = _git(root, "rev-parse", "HEAD")
    with pytest.raises(SourceSnapshotError, match="absolute path"):
        export_source_snapshot(root, tmp_path / "out", source_commit=commit, core_build_id="b" * 64)


def test_source_snapshot_inspection_recomputes_the_archived_core_identity(tmp_path: Path) -> None:
    root, commit = _repository(tmp_path)
    core_build_id = deterministic_build_id(root)
    snapshot = export_source_snapshot(root, tmp_path / "out", source_commit=commit, core_build_id=core_build_id)

    inspected = inspect_source_snapshot(snapshot.archive_path)

    assert inspected.source_commit == commit
    assert inspected.core_build_id == core_build_id
    assert inspected.archive_sha256 == snapshot.archive_sha256


def test_tagged_source_tree_uses_the_tagged_git_object_not_checkout_files(tmp_path: Path) -> None:
    root, commit = _repository(tmp_path)
    _git(root, "tag", RELEASE_TAG)
    core_build_id = deterministic_build_id(root)
    snapshot = export_source_snapshot(root, tmp_path / "out", source_commit=commit, core_build_id=core_build_id)

    (root / "untracked-private-file.txt").write_text("must not affect the tag tree\n", encoding="utf-8")
    (root / "src" / "invoice_hub" / "__init__.py").write_text("dirty checkout content\n", encoding="utf-8")
    tagged = inspect_tagged_source_tree(root, RELEASE_TAG)

    assert tagged.source_commit == commit
    assert tagged.core_build_id == core_build_id
    assert tagged.source_tree_sha256 == snapshot.source_tree_sha256
    assert tagged.tracked_file_count == len(REQUIRED_PATHS | {
        "src/invoice_hub/__init__.py",
        "web/index.html",
        "scripts/tools/jierui_voucher_import.py",
        "docs/jierui/facts.json",
        "tests/test_sample.py",
    })
