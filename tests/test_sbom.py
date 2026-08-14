from __future__ import annotations

import json
from pathlib import Path

import pytest

from invoice_hub.release.sbom import SbomError, build_sbom_payload, parse_hash_lock, write_sbom
from invoice_hub.version import PRODUCT_VERSION


ROOT = Path(__file__).resolve().parents[1]


def test_runtime_locks_generate_deterministic_cyclonedx_and_match_notices(tmp_path: Path) -> None:
    notices = (ROOT / "THIRD_PARTY_NOTICES.md").read_text(encoding="utf-8").casefold()
    for target, lock_name in (
        ("windows-x86_64-portable", "windows-x64-py314.lock"),
        ("macos-arm64-dmg", "macos-arm64-py314.lock"),
    ):
        lock = ROOT / "requirements" / lock_name
        first = build_sbom_payload(lock, target=target)
        second_path = write_sbom(lock, tmp_path / f"{target}.cdx.json", target=target)
        second = json.loads(second_path.read_text(encoding="utf-8"))
        assert first == second
        assert first["bomFormat"] == "CycloneDX"
        assert first["specVersion"] == "1.6"
        assert first["metadata"]["component"]["version"] == PRODUCT_VERSION
        for component in parse_hash_lock(lock):
            assert component["name"].casefold() in notices


def test_sbom_parser_fails_closed_for_unhashed_or_unsupported_lock_syntax(tmp_path: Path) -> None:
    lock = tmp_path / "bad.lock"
    lock.write_text("sample==1.0\n", encoding="utf-8")
    with pytest.raises(SbomError, match="no SHA-256"):
        parse_hash_lock(lock)
    lock.write_text("-r other.lock\n", encoding="utf-8")
    with pytest.raises(SbomError, match="unsupported"):
        parse_hash_lock(lock)
