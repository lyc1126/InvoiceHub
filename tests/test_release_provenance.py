from __future__ import annotations

import base64
import hashlib
import io
import json
import shutil
import subprocess
import tarfile
from pathlib import Path
from zipfile import ZIP_DEFLATED, ZipFile

import pytest

from invoice_hub.release.build_manifest import build_manifest_payload, deterministic_build_id
from invoice_hub.release.package_manifest import build_package_manifest_payload
from invoice_hub.release.provenance import MacOSReleaseTrust, ReleaseProvenanceError, finalize_release_provenance
from invoice_hub.release.source_snapshot import REQUIRED_PATHS, export_source_snapshot, inspect_source_snapshot
from invoice_hub.version import (
    MACOS_DMG_PACKAGE_ID,
    MACOS_SPARKLE_PACKAGE_ID,
    PRODUCT_VERSION,
    RELEASE_TAG,
    WINDOWS_PACKAGE_ID,
)


TRUSTED_SPARKLE_PUBLIC_KEY = base64.b64encode(b"p" * 32).decode("ascii")
DEVELOPER_TEAM_ID = "ABCDE12345"
DEVELOPER_ID_IDENTITY = f"Developer ID Application: InvoiceHub Test ({DEVELOPER_TEAM_ID})"


@pytest.fixture(autouse=True)
def _mock_macos_distribution_verifier(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr("invoice_hub.release.provenance._verify_macos_distribution_artifacts", lambda **_kwargs: None)


def _git(root: Path, *args: str) -> str:
    completed = subprocess.run(["git", "-C", str(root), *args], check=True, capture_output=True, text=True)
    return completed.stdout.strip()


def _source_repository(tmp_path: Path) -> tuple[Path, str]:
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
    }:
        path = root / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(f"fixture: {name}\n", encoding="utf-8")
    _git(root, "add", ".")
    _git(root, "commit", "-m", "fixture")
    commit = _git(root, "rev-parse", "HEAD")
    _git(root, "tag", RELEASE_TAG)
    return root, commit


def _write_sparkle_zip(root: Path, destination: Path, *, source_commit: str, core_build_id: str) -> None:
    build = build_manifest_payload(root, source_commit=source_commit, built_at="2026-08-02T00:00:00Z")
    package = build_package_manifest_payload(
        package_id=MACOS_DMG_PACKAGE_ID,
        target_platform="macos",
        architecture="arm64",
        package_type="dmg",
        python_version="3.14.6",
        dependency_lock_sha256="c" * 64,
        core_build_id=core_build_id,
        source_commit=source_commit,
    )
    prefix = "InvoiceHub.app/Contents/Resources/invoice-hub-core/"
    with ZipFile(destination, "w", compression=ZIP_DEFLATED) as archive:
        for path in sorted(root.rglob("*")):
            if path.is_file() and ".git" not in path.parts:
                archive.write(path, prefix + path.relative_to(root).as_posix())
        archive.writestr(prefix + "invoice-hub-build.json", json.dumps(build, sort_keys=True))
        archive.writestr(prefix + "invoice-hub-package.json", json.dumps(package, sort_keys=True))


def _artifact(path: Path, package_id: str) -> dict[str, object]:
    return {
        "name": path.name,
        "size_bytes": path.stat().st_size,
        "sha256": hashlib.sha256(path.read_bytes()).hexdigest(),
        "package_id": package_id,
    }


def _release_inputs(tmp_path: Path) -> tuple[dict[str, Path], dict[str, object]]:
    root, commit = _source_repository(tmp_path)
    core_build_id = deterministic_build_id(root)
    source = export_source_snapshot(root, tmp_path, source_commit=commit, core_build_id=core_build_id).archive_path
    windows_zip = tmp_path / f"InvoiceHub-v{PRODUCT_VERSION}-windows-x64-portable.zip"
    windows_zip.write_bytes(b"windows-zip")
    dmg = tmp_path / f"InvoiceHub-v{PRODUCT_VERSION}-macos-arm64.dmg"
    dmg.write_bytes(b"dmg")
    sparkle = tmp_path / f"InvoiceHub-v{PRODUCT_VERSION}-macos-arm64-update.zip"
    _write_sparkle_zip(root, sparkle, source_commit=commit, core_build_id=core_build_id)
    signature = base64.b64encode(b"s" * 64).decode("ascii")
    signature_path = sparkle.with_suffix(".zip.sparkle-signature.txt")
    signature_path.write_text(f'sparkle:edSignature="{signature}" length="{sparkle.stat().st_size}"\n', encoding="utf-8")

    windows_receipt = tmp_path / "windows-receipt.json"
    windows_receipt.write_text(
        json.dumps(
            {
                "schema_version": 1,
                "product_version": PRODUCT_VERSION,
                "python_version": "3.14.6",
                "architecture": "x86_64",
                "source_commit": commit,
                "artifact_name": windows_zip.name,
                "artifact_size": windows_zip.stat().st_size,
                "artifact_sha256": hashlib.sha256(windows_zip.read_bytes()).hexdigest(),
                "build_id": core_build_id,
                "package_id": WINDOWS_PACKAGE_ID,
                "dependency_lock_sha256": "d" * 64,
                "reproducibility_checked": True,
            }
        ),
        encoding="utf-8",
    )
    macos_receipt = tmp_path / "macos-receipt.json"
    macos_receipt.write_text(
        json.dumps(
            {
                "schema_version": 4,
                "product_version": PRODUCT_VERSION,
                "python_version": "3.14.6",
                "source_commit": commit,
                "core_build_id": core_build_id,
                "dmg": _artifact(dmg, MACOS_DMG_PACKAGE_ID),
                "sparkle_zip": _artifact(sparkle, MACOS_SPARKLE_PACKAGE_ID),
                "internal_unsigned": False,
                "notarized": True,
                "signature_mode": "developer-id-notarized",
                "sparkle_keychain_account": "com.invoicehub.release",
                "verification_complete": True,
                "sparkle_signature_verified": True,
                "sparkle_public_key_sha256": hashlib.sha256(
                    base64.b64decode(TRUSTED_SPARKLE_PUBLIC_KEY, validate=True)
                ).hexdigest(),
                "package_ids": {"dmg": MACOS_DMG_PACKAGE_ID, "sparkle": MACOS_SPARKLE_PACKAGE_ID},
                "sparkle_signature_output": signature_path.read_text(encoding="utf-8").strip(),
                "observed_developer_id_identity": DEVELOPER_ID_IDENTITY,
                "observed_developer_team_id": DEVELOPER_TEAM_ID,
                "distribution_verifier": "verify_macos_release.sh/v4",
            }
        ),
        encoding="utf-8",
    )
    paths = {
        "windows_zip": windows_zip,
        "windows_receipt": windows_receipt,
        "macos_dmg": dmg,
        "sparkle_zip": sparkle,
        "macos_receipt": macos_receipt,
        "source_archive": source,
        "source_checkout": root,
        "sparkle_signature_file": signature_path,
        "macos_release_trust": MacOSReleaseTrust(
            trusted_sparkle_public_key=TRUSTED_SPARKLE_PUBLIC_KEY,
            expected_developer_id_identity=DEVELOPER_ID_IDENTITY,
            expected_developer_team_id=DEVELOPER_TEAM_ID,
        ),
    }
    verification = {
        "ok": True,
        "product_version": PRODUCT_VERSION,
        "platform": "windows",
        "architecture": "x86_64",
        "package_type": "portable",
        "python_version": "3.14.6",
        "source_commit": commit,
        "build_id": core_build_id,
        "package_id": WINDOWS_PACKAGE_ID,
        "dependency_lock_sha256": "d" * 64,
    }
    return paths, verification


def _refresh_sparkle_receipt(paths: dict[str, Path]) -> None:
    receipt = json.loads(paths["macos_receipt"].read_text(encoding="utf-8"))
    receipt["sparkle_zip"] = _artifact(paths["sparkle_zip"], MACOS_SPARKLE_PACKAGE_ID)
    paths["macos_receipt"].write_text(json.dumps(receipt), encoding="utf-8")


def _rewrite_source_archive_commit(archive_path: Path, source_commit: str) -> None:
    entries: list[tuple[tarfile.TarInfo, bytes]] = []
    with tarfile.open(archive_path, "r:gz") as source:
        for member in source.getmembers():
            assert member.isfile()
            handle = source.extractfile(member)
            assert handle is not None
            content = handle.read()
            if member.name == "invoice-hub-source.json":
                manifest = json.loads(content.decode("utf-8"))
                manifest["source_commit"] = source_commit
                content = (json.dumps(manifest, ensure_ascii=False, indent=2, sort_keys=True) + "\n").encode("utf-8")
            info = tarfile.TarInfo(member.name)
            info.mode = member.mode
            info.mtime = member.mtime
            info.uid = member.uid
            info.gid = member.gid
            info.uname = member.uname
            info.gname = member.gname
            info.size = len(content)
            entries.append((info, content))
    with tarfile.open(archive_path, "w:gz", format=tarfile.PAX_FORMAT) as target:
        for info, content in entries:
            target.addfile(info, io.BytesIO(content))


def test_finalizer_derives_cross_platform_identity_from_artifacts_and_receipts(tmp_path: Path, monkeypatch) -> None:
    paths, verification = _release_inputs(tmp_path)
    monkeypatch.setattr("invoice_hub.release.provenance.verify_windows_portable", lambda *_args, **_kwargs: verification)
    verifier_calls: list[dict[str, object]] = []

    def verify_distribution(**kwargs: object) -> None:
        verifier_calls.append(kwargs)

    monkeypatch.setattr("invoice_hub.release.provenance._verify_macos_distribution_artifacts", verify_distribution)

    provenance = finalize_release_provenance(**paths)

    assert provenance.source_commit == verification["source_commit"]
    assert provenance.core_build_id == verification["build_id"]
    assert provenance.macos_sparkle.package_id == MACOS_SPARKLE_PACKAGE_ID
    assert provenance.windows_portable.package_id == WINDOWS_PACKAGE_ID
    assert len(verifier_calls) == 1
    verifier_call = verifier_calls[0]
    assert verifier_call["source_checkout"] == paths["source_checkout"]
    assert verifier_call["source_commit"] == verification["source_commit"]
    assert verifier_call["macos_dmg"] == paths["macos_dmg"]
    assert verifier_call["sparkle_zip"] == paths["sparkle_zip"]
    assert verifier_call["sparkle_signature_file"] == paths["sparkle_signature_file"]
    assert verifier_call["core_build_id"] == verification["build_id"]
    assert verifier_call["trust"].trusted_sparkle_public_key == TRUSTED_SPARKLE_PUBLIC_KEY
    assert verifier_call["trust"].expected_developer_id_identity == DEVELOPER_ID_IDENTITY
    assert verifier_call["trust"].expected_developer_team_id == DEVELOPER_TEAM_ID


def test_finalizer_rejects_a_positive_receipt_when_independent_macos_verification_fails(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    paths, verification = _release_inputs(tmp_path)
    monkeypatch.setattr("invoice_hub.release.provenance.verify_windows_portable", lambda *_args, **_kwargs: verification)

    def fail_distribution_verification(**_kwargs: object) -> None:
        raise ReleaseProvenanceError("simulated macOS artifact verification failure")

    monkeypatch.setattr(
        "invoice_hub.release.provenance._verify_macos_distribution_artifacts", fail_distribution_verification
    )

    with pytest.raises(ReleaseProvenanceError, match="simulated macOS artifact verification failure"):
        finalize_release_provenance(**paths)


@pytest.mark.parametrize(
    "trust",
    (
        MacOSReleaseTrust("not-base64", DEVELOPER_ID_IDENTITY, DEVELOPER_TEAM_ID),
        MacOSReleaseTrust(TRUSTED_SPARKLE_PUBLIC_KEY, DEVELOPER_ID_IDENTITY, "ABCDE12346"),
    ),
)
def test_finalizer_rejects_invalid_macos_trust_before_running_external_verifier(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, trust: MacOSReleaseTrust
) -> None:
    paths, verification = _release_inputs(tmp_path)
    paths["macos_release_trust"] = trust
    monkeypatch.setattr("invoice_hub.release.provenance.verify_windows_portable", lambda *_args, **_kwargs: verification)
    verifier_calls: list[dict[str, object]] = []
    monkeypatch.setattr(
        "invoice_hub.release.provenance._verify_macos_distribution_artifacts",
        lambda **kwargs: verifier_calls.append(kwargs),
    )

    with pytest.raises(ReleaseProvenanceError, match="Sparkle 公钥|身份与 Team ID"):
        finalize_release_provenance(**paths)

    assert verifier_calls == []


def test_finalizer_rejects_internal_macos_receipt_before_feed_generation(tmp_path: Path, monkeypatch) -> None:
    paths, verification = _release_inputs(tmp_path)
    monkeypatch.setattr("invoice_hub.release.provenance.verify_windows_portable", lambda *_args, **_kwargs: verification)
    receipt = json.loads(paths["macos_receipt"].read_text(encoding="utf-8"))
    receipt["internal_unsigned"] = True
    paths["macos_receipt"].write_text(json.dumps(receipt), encoding="utf-8")

    with pytest.raises(ReleaseProvenanceError, match="internal_unsigned"):
        finalize_release_provenance(**paths)


@pytest.mark.parametrize(
    ("field", "value", "message"),
    (
        ("schema_version", 3, "schema_version"),
        ("signature_mode", "internal-adhoc", "signature_mode"),
        ("sparkle_keychain_account", "ed25519", "sparkle_keychain_account"),
        ("distribution_verifier", "verify_macos_release.sh/v3", "distribution_verifier"),
    ),
)
def test_finalizer_requires_formal_schema4_signature_and_dedicated_sparkle_account(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    field: str,
    value: object,
    message: str,
) -> None:
    paths, verification = _release_inputs(tmp_path)
    monkeypatch.setattr("invoice_hub.release.provenance.verify_windows_portable", lambda *_args, **_kwargs: verification)
    receipt = json.loads(paths["macos_receipt"].read_text(encoding="utf-8"))
    receipt[field] = value
    paths["macos_receipt"].write_text(json.dumps(receipt), encoding="utf-8")

    with pytest.raises(ReleaseProvenanceError, match=message):
        finalize_release_provenance(**paths)


def test_finalizer_rejects_source_archive_when_release_tag_is_missing(tmp_path: Path, monkeypatch) -> None:
    paths, verification = _release_inputs(tmp_path)
    monkeypatch.setattr("invoice_hub.release.provenance.verify_windows_portable", lambda *_args, **_kwargs: verification)
    _git(paths["source_checkout"], "tag", "-d", RELEASE_TAG)

    with pytest.raises(ReleaseProvenanceError, match=RELEASE_TAG):
        finalize_release_provenance(**paths)


def test_finalizer_rejects_source_archive_when_release_tag_resolves_to_another_commit(
    tmp_path: Path, monkeypatch
) -> None:
    paths, verification = _release_inputs(tmp_path)
    monkeypatch.setattr("invoice_hub.release.provenance.verify_windows_portable", lambda *_args, **_kwargs: verification)
    drift_marker = paths["source_checkout"] / "release-tag-drift.txt"
    drift_marker.write_text("not the archived release candidate\n", encoding="utf-8")
    _git(paths["source_checkout"], "add", drift_marker.name)
    _git(paths["source_checkout"], "commit", "-m", "move release tag")
    _git(paths["source_checkout"], "tag", "-f", RELEASE_TAG)

    with pytest.raises(ReleaseProvenanceError, match="source_commit"):
        finalize_release_provenance(**paths)


def test_finalizer_rejects_self_consistent_archive_that_is_not_the_tagged_tree(tmp_path: Path, monkeypatch) -> None:
    paths, verification = _release_inputs(tmp_path)
    monkeypatch.setattr("invoice_hub.release.provenance.verify_windows_portable", lambda *_args, **_kwargs: verification)
    tagged_commit = str(verification["source_commit"])
    source_checkout = paths["source_checkout"]
    malicious_core_file = source_checkout / "src" / "invoice_hub" / "__init__.py"
    malicious_core_file.write_text("malicious but internally consistent release core\n", encoding="utf-8")
    _git(source_checkout, "add", malicious_core_file.relative_to(source_checkout).as_posix())
    _git(source_checkout, "commit", "-m", "malicious post-tag source")
    malicious_commit = _git(source_checkout, "rev-parse", "HEAD")
    malicious_core_build_id = deterministic_build_id(source_checkout)
    malicious_source = export_source_snapshot(
        source_checkout,
        tmp_path / "malicious-source",
        source_commit=malicious_commit,
        core_build_id=malicious_core_build_id,
    ).archive_path
    _rewrite_source_archive_commit(malicious_source, tagged_commit)
    inspected = inspect_source_snapshot(malicious_source)
    assert inspected.source_commit == tagged_commit
    assert inspected.core_build_id == malicious_core_build_id
    paths["source_archive"] = malicious_source

    _write_sparkle_zip(
        source_checkout,
        paths["sparkle_zip"],
        source_commit=tagged_commit,
        core_build_id=malicious_core_build_id,
    )
    _refresh_sparkle_receipt(paths)
    macos_receipt = json.loads(paths["macos_receipt"].read_text(encoding="utf-8"))
    macos_receipt["source_commit"] = tagged_commit
    macos_receipt["core_build_id"] = malicious_core_build_id
    paths["macos_receipt"].write_text(json.dumps(macos_receipt), encoding="utf-8")
    windows_receipt = json.loads(paths["windows_receipt"].read_text(encoding="utf-8"))
    windows_receipt["source_commit"] = tagged_commit
    windows_receipt["build_id"] = malicious_core_build_id
    paths["windows_receipt"].write_text(json.dumps(windows_receipt), encoding="utf-8")
    verification["source_commit"] = tagged_commit
    verification["build_id"] = malicious_core_build_id

    with pytest.raises(ReleaseProvenanceError, match="source_tree_sha256"):
        finalize_release_provenance(**paths)


def test_finalizer_rejects_duplicate_sparkle_zip_entries(tmp_path: Path, monkeypatch) -> None:
    paths, verification = _release_inputs(tmp_path)
    monkeypatch.setattr("invoice_hub.release.provenance.verify_windows_portable", lambda *_args, **_kwargs: verification)
    prefix = "InvoiceHub.app/Contents/Resources/invoice-hub-core/"
    with pytest.warns(UserWarning, match="Duplicate name"):
        with ZipFile(paths["sparkle_zip"], "a", compression=ZIP_DEFLATED) as archive:
            archive.writestr(prefix + "invoice-hub-package.json", "{}")
    _refresh_sparkle_receipt(paths)

    with pytest.raises(ReleaseProvenanceError, match="重复条目"):
        finalize_release_provenance(**paths)


def test_finalizer_rejects_noncanonical_sparkle_zip_alias(tmp_path: Path, monkeypatch) -> None:
    paths, verification = _release_inputs(tmp_path)
    monkeypatch.setattr("invoice_hub.release.provenance.verify_windows_portable", lambda *_args, **_kwargs: verification)
    prefix = "InvoiceHub.app/Contents/Resources/invoice-hub-core/"
    package_manifest = prefix + "invoice-hub-package.json"
    with ZipFile(paths["sparkle_zip"]) as archive:
        package_content = archive.read(package_manifest)
    with ZipFile(paths["sparkle_zip"], "a", compression=ZIP_DEFLATED) as archive:
        archive.writestr(prefix + "./invoice-hub-package.json", package_content)
    _refresh_sparkle_receipt(paths)

    with pytest.raises(ReleaseProvenanceError, match="非规范 POSIX 路径"):
        finalize_release_provenance(**paths)


def test_finalizer_rejects_windows_drive_paths_in_sparkle_zip(tmp_path: Path, monkeypatch) -> None:
    paths, verification = _release_inputs(tmp_path)
    monkeypatch.setattr("invoice_hub.release.provenance.verify_windows_portable", lambda *_args, **_kwargs: verification)
    with ZipFile(paths["sparkle_zip"], "a", compression=ZIP_DEFLATED) as archive:
        archive.writestr("C:unsafe", "not allowed")
    _refresh_sparkle_receipt(paths)

    with pytest.raises(ReleaseProvenanceError, match="Windows 盘符"):
        finalize_release_provenance(**paths)
