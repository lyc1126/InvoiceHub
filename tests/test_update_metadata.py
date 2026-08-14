from __future__ import annotations

import base64
import hashlib
import json
from pathlib import Path

import pytest

from invoice_hub.release.update_metadata import (
    INVOICEHUB_NAMESPACE,
    UpdateMetadataError,
    _build_appcast,
    _build_update_feed,
    _write_update_metadata,
    generate_release_metadata,
    main,
    validate_appcast_parity,
    validate_update_feed,
)
from invoice_hub.release.provenance import MacOSReleaseTrust, ReleaseArtifact, ReleaseProvenance, ReleaseProvenanceError
from invoice_hub.version import MACOS_SPARKLE_PACKAGE_ID, PRODUCT_VERSION, WINDOWS_PACKAGE_ID


CORE_BUILD_ID = "a" * 64
SOURCE_COMMIT = "b" * 40
SIGNATURE = base64.b64encode(b"s" * 64).decode("ascii")
TRUSTED_SPARKLE_PUBLIC_KEY = base64.b64encode(b"p" * 32).decode("ascii")
DEVELOPER_TEAM_ID = "ABCDE12345"
DEVELOPER_ID_IDENTITY = f"Developer ID Application: InvoiceHub Test ({DEVELOPER_TEAM_ID})"


def _artifacts(tmp_path: Path) -> dict[str, Path]:
    paths = {
        "windows_zip": tmp_path / f"InvoiceHub-v{PRODUCT_VERSION}-windows-x64-portable.zip",
        "macos_dmg": tmp_path / f"InvoiceHub-v{PRODUCT_VERSION}-macos-arm64.dmg",
        "sparkle_zip": tmp_path / f"InvoiceHub-v{PRODUCT_VERSION}-macos-arm64-update.zip",
        "source_archive": tmp_path / f"InvoiceHub-v{PRODUCT_VERSION}-source.tar.gz",
    }
    for index, path in enumerate(paths.values(), 1):
        path.write_bytes((path.name.encode("utf-8") + b"\0") * index)
    return paths


def _provenance(paths: dict[str, Path], *, signature: str = SIGNATURE) -> ReleaseProvenance:
    def artifact(key: str, package_id: str) -> ReleaseArtifact:
        path = paths[key]
        return ReleaseArtifact(
            key=key,
            path=path,
            package_id=package_id,
            size_bytes=path.stat().st_size,
            sha256=hashlib.sha256(path.read_bytes()).hexdigest(),
            source_commit=SOURCE_COMMIT,
            core_build_id=CORE_BUILD_ID,
        )

    return ReleaseProvenance(
        product_version=PRODUCT_VERSION,
        release_tag=f"v{PRODUCT_VERSION}",
        source_commit=SOURCE_COMMIT,
        core_build_id=CORE_BUILD_ID,
        source_archive=artifact("source_archive", "source"),
        windows_portable=artifact("windows_zip", WINDOWS_PACKAGE_ID),
        macos_dmg=artifact("macos_dmg", "com.invoicehub.macos.arm64.dmg"),
        macos_sparkle=artifact("sparkle_zip", MACOS_SPARKLE_PACKAGE_ID),
        sparkle_signature=signature,
        sparkle_public_key_sha256="c" * 64,
    )


def _finalizer_inputs(paths: dict[str, Path]) -> dict[str, Path]:
    return {
        "windows_zip": paths["windows_zip"],
        "windows_receipt": paths["windows_zip"].with_name("windows-receipt.json"),
        "macos_dmg": paths["macos_dmg"],
        "sparkle_zip": paths["sparkle_zip"],
        "macos_receipt": paths["macos_dmg"].with_name("macos-receipt.json"),
        "source_archive": paths["source_archive"],
        "source_checkout": paths["source_archive"].parent / "source-checkout",
        "sparkle_signature_file": paths["sparkle_zip"].with_suffix(".sparkle-signature.txt"),
        "macos_trusted_sparkle_public_key": TRUSTED_SPARKLE_PUBLIC_KEY,
        "macos_expected_developer_id_identity": DEVELOPER_ID_IDENTITY,
        "macos_expected_developer_team_id": DEVELOPER_TEAM_ID,
    }


def test_update_metadata_is_generated_from_artifacts_and_appcast_is_in_lockstep(tmp_path: Path) -> None:
    feed = _build_update_feed(provenance=_provenance(_artifacts(tmp_path)), published_at="2026-08-02T00:00:00Z")
    appcast = _build_appcast(feed)
    parity = validate_appcast_parity(feed, appcast)
    latest_path, appcast_path = _write_update_metadata(tmp_path / "updates", feed)

    assert feed["latest_version"] == PRODUCT_VERSION
    assert feed["artifacts"]["windows-x86_64-portable"]["package_id"] == WINDOWS_PACKAGE_ID
    assert feed["artifacts"]["macos-arm64-sparkle"]["package_id"] == MACOS_SPARKLE_PACKAGE_ID
    assert feed["source"]["source_commit"] == SOURCE_COMMIT
    assert parity["core_build_id"] == CORE_BUILD_ID
    assert json.loads(latest_path.read_text(encoding="utf-8")) == feed
    assert appcast_path.read_bytes() == appcast
    assert INVOICEHUB_NAMESPACE == "https://lyc1126.github.io/InvoiceHub/ns/update/1"
    assert b"invoicehub.example" not in appcast


def test_update_metadata_rejects_appcast_drift_and_invalid_signature(tmp_path: Path) -> None:
    files = _artifacts(tmp_path)
    feed = _build_update_feed(provenance=_provenance(files), published_at="2026-08-02T00:00:00Z")
    appcast = _build_appcast(feed).replace(CORE_BUILD_ID.encode(), ("b" * 64).encode())
    with pytest.raises(UpdateMetadataError, match="不一致"):
        validate_appcast_parity(feed, appcast)
    with pytest.raises(UpdateMetadataError, match="64 字节"):
        _build_update_feed(
            provenance=_provenance(files, signature=base64.b64encode(b"too short").decode()),
            published_at="2026-08-02T00:00:00Z",
        )


def test_update_feed_requires_all_artifacts_and_exact_cross_platform_identity(tmp_path: Path) -> None:
    feed = _build_update_feed(provenance=_provenance(_artifacts(tmp_path)), published_at="2026-08-02T00:00:00Z")
    del feed["artifacts"]["macos-arm64-dmg"]
    with pytest.raises(UpdateMetadataError) as caught:
        validate_update_feed(feed)
    assert caught.value.code == "UPDATE_ARTIFACT_NOT_FOUND"


def test_update_feed_rejects_source_commit_drift_even_when_core_build_id_matches(tmp_path: Path) -> None:
    feed = _build_update_feed(provenance=_provenance(_artifacts(tmp_path)), published_at="2026-08-02T00:00:00Z")
    feed["artifacts"]["macos-arm64-dmg"]["source_commit"] = "d" * 40

    with pytest.raises(UpdateMetadataError, match="source_commit"):
        validate_update_feed(feed)


def test_update_feed_rejects_wrong_prerelease_kind_for_current_channel(tmp_path: Path) -> None:
    feed = _build_update_feed(provenance=_provenance(_artifacts(tmp_path)), published_at="2026-08-02T00:00:00Z")
    feed["latest_version"] = "0.3.0b1"
    feed["source"]["tag"] = "v0.3.0b1"

    with pytest.raises(UpdateMetadataError, match="alpha 更新通道") as caught:
        validate_update_feed(feed)

    assert caught.value.code == "UPDATE_VERSION_INVALID"


def test_generate_release_metadata_finalizes_before_formatting_or_writing(tmp_path: Path, monkeypatch) -> None:
    inputs = _finalizer_inputs(_artifacts(tmp_path))
    output_dir = tmp_path / "updates"
    expected_provenance = object()
    expected_feed = {"trusted": "feed"}
    expected_paths = (output_dir / "latest.json", output_dir / "appcast.xml")
    calls: list[tuple[str, object]] = []

    expected_finalizer_inputs = dict(inputs)
    del expected_finalizer_inputs["macos_trusted_sparkle_public_key"]
    del expected_finalizer_inputs["macos_expected_developer_id_identity"]
    del expected_finalizer_inputs["macos_expected_developer_team_id"]
    expected_finalizer_inputs["macos_release_trust"] = MacOSReleaseTrust(
        trusted_sparkle_public_key=TRUSTED_SPARKLE_PUBLIC_KEY,
        expected_developer_id_identity=DEVELOPER_ID_IDENTITY,
        expected_developer_team_id=DEVELOPER_TEAM_ID,
    )

    def fake_finalize(**kwargs: object) -> object:
        assert not output_dir.exists()
        calls.append(("finalize", kwargs))
        return expected_provenance

    def fake_build(*, provenance: object, published_at: str) -> dict[str, str]:
        calls.append(("build", (provenance, published_at)))
        assert provenance is expected_provenance
        return expected_feed

    def fake_write(actual_output_dir: Path, feed: dict[str, str]) -> tuple[Path, Path]:
        calls.append(("write", (actual_output_dir, feed)))
        assert feed is expected_feed
        return expected_paths

    monkeypatch.setattr("invoice_hub.release.update_metadata.finalize_release_provenance", fake_finalize)
    monkeypatch.setattr("invoice_hub.release.update_metadata._build_update_feed", fake_build)
    monkeypatch.setattr("invoice_hub.release.update_metadata._write_update_metadata", fake_write)

    result = generate_release_metadata(
        **inputs,
        published_at="2026-08-02T00:00:00Z",
        output_dir=output_dir,
    )

    assert result == expected_paths
    assert calls == [
        ("finalize", expected_finalizer_inputs),
        ("build", (expected_provenance, "2026-08-02T00:00:00Z")),
        ("write", (output_dir, expected_feed)),
    ]


def test_generate_release_metadata_does_not_write_when_provenance_fails(tmp_path: Path, monkeypatch) -> None:
    inputs = _finalizer_inputs(_artifacts(tmp_path))
    output_dir = tmp_path / "updates"

    def fail_finalize(**_kwargs: Path) -> object:
        raise ReleaseProvenanceError("untrusted artifact")

    monkeypatch.setattr("invoice_hub.release.update_metadata.finalize_release_provenance", fail_finalize)

    with pytest.raises(UpdateMetadataError, match="可信来源") as caught:
        generate_release_metadata(
            **inputs,
            published_at="2026-08-02T00:00:00Z",
            output_dir=output_dir,
        )

    assert caught.value.code == "UPDATE_RELEASE_PROVENANCE_INVALID"
    assert not output_dir.exists()


def test_generate_command_routes_only_through_high_level_entrypoint(tmp_path: Path, monkeypatch) -> None:
    inputs = _finalizer_inputs(_artifacts(tmp_path))
    output_dir = tmp_path / "updates"
    expected_paths = (output_dir / "latest.json", output_dir / "appcast.xml")
    calls: list[dict[str, object]] = []

    def fake_generate(**kwargs: object) -> tuple[Path, Path]:
        calls.append(kwargs)
        return expected_paths

    monkeypatch.setattr("invoice_hub.release.update_metadata.generate_release_metadata", fake_generate)
    result = main(_generate_command(inputs, output_dir))

    assert result == 0
    assert calls == [{**inputs, "published_at": "2026-08-02T00:00:00Z", "output_dir": output_dir}]


@pytest.mark.parametrize(
    "missing_option",
    (
        "--macos-trusted-sparkle-public-key",
        "--macos-expected-developer-id-identity",
        "--macos-expected-developer-team-id",
    ),
)
def test_generate_command_requires_each_macos_trust_argument(tmp_path: Path, missing_option: str) -> None:
    arguments = _generate_command(_finalizer_inputs(_artifacts(tmp_path)), tmp_path / "updates")
    option_index = arguments.index(missing_option)
    del arguments[option_index : option_index + 2]

    with pytest.raises(SystemExit) as caught:
        main(arguments)

    assert caught.value.code == 2


def _generate_command(inputs: dict[str, Path], output_dir: Path) -> list[str]:
    return [
        "generate",
        "--windows-zip",
        str(inputs["windows_zip"]),
        "--windows-receipt",
        str(inputs["windows_receipt"]),
        "--macos-dmg",
        str(inputs["macos_dmg"]),
        "--sparkle-zip",
        str(inputs["sparkle_zip"]),
        "--macos-receipt",
        str(inputs["macos_receipt"]),
        "--source-archive",
        str(inputs["source_archive"]),
        "--source-checkout",
        str(inputs["source_checkout"]),
        "--sparkle-signature-file",
        str(inputs["sparkle_signature_file"]),
        "--macos-trusted-sparkle-public-key",
        str(inputs["macos_trusted_sparkle_public_key"]),
        "--macos-expected-developer-id-identity",
        str(inputs["macos_expected_developer_id_identity"]),
        "--macos-expected-developer-team-id",
        str(inputs["macos_expected_developer_team_id"]),
        "--published-at",
        "2026-08-02T00:00:00Z",
        "--output-dir",
        str(output_dir),
    ]
