from __future__ import annotations

import hashlib
from pathlib import Path

import pytest

from invoice_hub.release.dependency_lock import DependencyLockError, build_lock_text


def test_build_lock_text_is_sorted_and_hashes_exact_wheels(tmp_path: Path) -> None:
    second = tmp_path / "zebra_pkg-2.0-py3-none-any.whl"
    first = tmp_path / "Alpha_Pkg-1.0-py3-none-any.whl"
    second.write_bytes(b"second")
    first.write_bytes(b"first")

    lock = build_lock_text(tmp_path)

    assert lock.index("alpha-pkg==1.0") < lock.index("zebra-pkg==2.0")
    assert hashlib.sha256(b"first").hexdigest() in lock
    assert hashlib.sha256(b"second").hexdigest() in lock
    assert lock.endswith("\n")


def test_build_lock_rejects_empty_or_duplicate_distributions(tmp_path: Path) -> None:
    with pytest.raises(DependencyLockError, match="no wheels"):
        build_lock_text(tmp_path)

    (tmp_path / "sample_pkg-1.0-py3-none-any.whl").write_bytes(b"one")
    (tmp_path / "sample_pkg-1.0-1-py3-none-any.whl").write_bytes(b"two")
    with pytest.raises(DependencyLockError, match="exactly one wheel"):
        build_lock_text(tmp_path)
