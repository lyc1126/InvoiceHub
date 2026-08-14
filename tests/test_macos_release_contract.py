from __future__ import annotations

import json
import subprocess
from pathlib import Path

import pytest


ROOT = Path(__file__).resolve().parents[1]


def _text(relative: str) -> str:
    return (ROOT / relative).read_text(encoding="utf-8")


def _stripped_lines(block: str) -> list[str]:
    return [line.strip() for line in block.splitlines() if line.strip()]


def test_sparkle_dependency_and_resolved_revision_are_exact() -> None:
    package = _text("macos/InvoiceHubMac/Package.swift")
    resolved = json.loads(_text("macos/InvoiceHubMac/Package.resolved"))
    sparkle = next(pin for pin in resolved["pins"] if pin["identity"] == "sparkle")

    assert 'exact: "2.9.2"' in package
    assert sparkle["state"] == {
        "revision": "6276ba2b404829d139c45ff98427cf90e2efc59b",
        "version": "2.9.2",
    }


def test_macos_runtime_is_pinned_hash_locked_and_offline_installable() -> None:
    prepare = _text("macos/InvoiceHubMac/script/prepare_release_runtime.sh")
    assert 'PYTHON_VERSION="3.14.6"' in prepare
    assert 'PBS_RELEASE="20260623"' in prepare
    assert 'PBS_SHA256="35d774f61d63c1fd4f1bc9495a7ada92e500dc4382a0df8a9910eb87ea48e8cf"' in prepare
    assert "--require-hashes" in prepare
    assert "--only-binary=:all:" in prepare
    assert "--no-index" in prepare
    assert "import tkinter, ssl, sqlite3, fitz, PIL" in prepare
    assert "watchdog" not in prepare
    assert "invoice_hub.release.runtime_manifest write" in prepare
    assert 'LC_ALL=C LANG=C /usr/bin/shasum -a 256 "$ARCHIVE"' in prepare
    for relative_path in (
        "lib/python3.14/ctypes/macholib/fetch_macholib.bat",
        "lib/python3.14/idlelib/idle.bat",
        "lib/python3.14/venv/scripts/common/Activate.ps1",
    ):
        assert f'"$RUNTIME_DIR/{relative_path}"' in prepare
    assert 'rm -f -- "${WINDOWS_SHELL_FILES[@]}"' in prepare
    assert "macOS runtime still contains Windows shell files" in prepare
    for launcher_name in (
        "t32.exe",
        "t64.exe",
        "t64-arm.exe",
        "w32.exe",
        "w64.exe",
        "w64-arm.exe",
    ):
        assert f'pip/_vendor/distlib/{launcher_name}"' in prepare
    assert 'rm -f -- "${WINDOWS_BINARY_FILES[@]}"' in prepare
    assert "macOS runtime still contains Windows binaries" in prepare
    for binary_pattern in ("*.exe", "*.dll", "*.pyd", "*.msi", "*.msix"):
        assert f"-iname '{binary_pattern}'" in prepare
    assert prepare.index("WINDOWS_SHELL_FILES=(") < prepare.index(
        "invoice_hub.release.runtime_manifest write"
    )
    assert prepare.index("WINDOWS_BINARY_FILES=(") < prepare.index(
        "invoice_hub.release.runtime_manifest write"
    )


def test_macos_formal_build_has_release_identity_signing_notary_and_fixed_outputs() -> None:
    build = _text("macos/InvoiceHubMac/script/build_release.sh")
    verify = _text("macos/InvoiceHubMac/script/verify_macos_release.sh")
    sparkle_verifier = _text("macos/InvoiceHubMac/script/verify_sparkle_update.swift")
    for marker in (
        'VERSION="0.3.0-alpha.1"',
        'BUILD_NUMBER="1"',
        'PACKAGE_ID="com.invoicehub.macos.arm64.dmg"',
        "git -C \"$REPO_ROOT\" archive",
        "swift build --package-path \"$SWIFT_ROOT\" --configuration release --arch arm64",
        "InvoiceHubReleaseMode</key><true/>",
        "SUFeedURL",
        "SUPublicEDKey",
        "SUEnableAutomaticChecks</key><false/>",
        "codesign --verify --deep --strict",
        "notarytool submit",
        "stapler staple",
        "sign_update",
        "verify_sparkle_update.swift",
        "sparkle_signature_verified",
        "sparkle_public_key_sha256",
        "verification_complete",
        'SPARKLE_KEYCHAIN_ACCOUNT="com.invoicehub.release"',
        '"schema_version": 4',
        '"signature_mode"',
        '"sparkle_keychain_account"',
        '"distribution_verifier": "verify_macos_release.sh/v4"',
        "INVOICE_HUB_APPLE_TEAM_ID",
        "MACOS_SPARKLE_PACKAGE_ID",
        "InvoiceHub-v$VERSION-macos-arm64.dmg",
        "InvoiceHub-v$VERSION-macos-arm64-update.zip",
        "invoice_hub.release.sbom",
        'SIGN_IDENTITY="-"',
        'MACOS_DMG_PACKAGE_ID = \\"$PACKAGE_ID\\"',
    ):
        assert marker in build
    assert '"$SIGN_UPDATE" --account "$SPARKLE_KEYCHAIN_ACCOUNT" "$UPDATE_ZIP"' in build
    dmg_signing_block = build.split(
        'hdiutil create -volname "InvoiceHub $VERSION" -srcfolder "$DMG_STAGE" -format UDZO -ov "$DMG_PATH"',
        1,
    )[1].split("VERIFY_ARGS=(", 1)[0]
    signing_modes = dmg_signing_block.split('if [[ "$INTERNAL_UNSIGNED" == "true" ]]; then', 1)[1]
    internal_signing, formal_and_common_signing = signing_modes.split("\nelse\n", 1)
    formal_signing, common_signing = formal_and_common_signing.split("\nfi\n", 1)
    assert _stripped_lines(internal_signing) == ['codesign --force --sign - "$DMG_PATH"']
    assert _stripped_lines(formal_signing) == [
        'codesign --force --timestamp --sign "$SIGN_IDENTITY" "$DMG_PATH"',
        'xcrun notarytool submit "$DMG_PATH" --keychain-profile "$INVOICE_HUB_NOTARY_PROFILE" --wait',
        'xcrun stapler staple "$DMG_PATH"',
    ]
    assert _stripped_lines(common_signing) == ['codesign --verify --verbose=2 "$DMG_PATH"']

    verify_args_block = build.split("VERIFY_ARGS=(", 1)[1].split(
        '"$ROOT_DIR/script/verify_macos_release.sh" "${VERIFY_ARGS[@]}"',
        1,
    )[0]
    verify_modes = verify_args_block.split('if [[ "$INTERNAL_UNSIGNED" == "false" ]]; then', 1)[1]
    formal_verify, internal_and_end = verify_modes.split("\nelse\n", 1)
    internal_verify = internal_and_end.split("\nfi", 1)[0]
    assert _stripped_lines(formal_verify) == [
        "VERIFY_ARGS+=(",
        "--expect-notarized",
        '--expected-developer-id-identity "$SIGN_IDENTITY"',
        '--expected-developer-team-id "$INVOICE_HUB_APPLE_TEAM_ID"',
        ")",
    ]
    assert _stripped_lines(internal_verify) == ["VERIFY_ARGS+=(--expect-internal-adhoc)"]

    argument_cases = verify.split('case "$1" in', 1)[1].split("\n  esac", 1)[0]
    assert argument_cases.count("--expect-notarized)") == 1
    assert argument_cases.count("--expect-internal-adhoc)") == 1
    notarized_case = argument_cases.split("--expect-notarized)", 1)[1].split(";;", 1)[0]
    internal_case = argument_cases.split("--expect-internal-adhoc)", 1)[1].split(";;", 1)[0]
    assert notarized_case.strip() == 'EXPECT_NOTARIZED="true"; shift'
    assert internal_case.strip() == 'EXPECT_INTERNAL_ADHOC="true"; shift'

    app_function = verify.split("verify_signed_app() {", 1)[1].split("\n}\n\nverify_signed_dmg() {", 1)[0]
    app_common, app_modes = app_function.split('  if [[ "$EXPECT_NOTARIZED" == "true" ]]; then', 1)
    app_formal, app_internal_and_end = app_modes.split("\n  else\n", 1)
    app_internal = app_internal_and_end.rsplit("\n  fi", 1)[0]
    assert _stripped_lines(app_common) == [
        'local app="$1"',
        'local label="$2"',
        'codesign --verify --deep --strict --verbose=2 "$app"',
    ]
    assert _stripped_lines(app_formal) == [
        "local details",
        'details="$(codesign -dvvv "$app" 2>&1)"',
        (
            'grep -Fqx "Authority=$EXPECTED_DEVELOPER_ID_IDENTITY" <<<"$details" '
            '|| die "$label does not have the expected Developer ID authority."'
        ),
        (
            'grep -Fqx "TeamIdentifier=$EXPECTED_DEVELOPER_TEAM_ID" <<<"$details" '
            '|| die "$label does not have the expected Developer Team ID."'
        ),
        "grep -q '^Runtime Version=' <<<\"$details\" || die \"$label is missing the hardened runtime.\"",
        'xcrun stapler validate "$app"',
        'spctl --assess --type execute --verbose=2 "$app"',
    ]
    assert _stripped_lines(app_internal) == [
        "local details",
        'details="$(codesign -dvvv "$app" 2>&1)"',
        'grep -Fqx "Signature=adhoc" <<<"$details" || die "$label is not ad-hoc signed."',
        "if grep -q '^Authority=' <<<\"$details\"; then",
        'die "$label must not have a Developer ID authority in internal mode."',
        "fi",
        (
            "if grep -q '^TeamIdentifier=' <<<\"$details\" "
            '&& ! grep -Fqx "TeamIdentifier=not set" <<<"$details"; then'
        ),
        'die "$label must not have a Developer Team ID in internal mode."',
        "fi",
    ]

    dmg_function = verify.split("verify_signed_dmg() {", 1)[1].split("\n}\n\nscan_app_content() {", 1)[0]
    dmg_common, dmg_modes = dmg_function.split('  if [[ "$EXPECT_NOTARIZED" == "true" ]]; then', 1)
    dmg_formal, dmg_internal_and_end = dmg_modes.split("\n  else\n", 1)
    dmg_internal = dmg_internal_and_end.rsplit("\n  fi", 1)[0]
    assert _stripped_lines(dmg_common) == [
        'local dmg="$1"',
        'codesign --verify --verbose=2 "$dmg"',
    ]
    assert _stripped_lines(dmg_formal) == [
        "local details",
        'details="$(codesign -dvvv "$dmg" 2>&1)"',
        (
            'grep -Fqx "Authority=$EXPECTED_DEVELOPER_ID_IDENTITY" <<<"$details" '
            '|| die "DMG does not have the expected Developer ID authority."'
        ),
        (
            'grep -Fqx "TeamIdentifier=$EXPECTED_DEVELOPER_TEAM_ID" <<<"$details" '
            '|| die "DMG does not have the expected Developer Team ID."'
        ),
        'xcrun stapler validate "$dmg"',
        'spctl --assess --type open --context context:primary-signature --verbose=2 "$dmg"',
    ]
    assert _stripped_lines(dmg_internal) == [
        "local details",
        'details="$(codesign -dvvv "$dmg" 2>&1)"',
        'grep -Fqx "Signature=adhoc" <<<"$details" || die "DMG is not ad-hoc signed."',
        "if grep -q '^Authority=' <<<\"$details\"; then",
        'die "DMG must not have a Developer ID authority in internal mode."',
        "fi",
        (
            "if grep -q '^TeamIdentifier=' <<<\"$details\" "
            '&& ! grep -Fqx "TeamIdentifier=not set" <<<"$details"; then'
        ),
        'die "DMG must not have a Developer Team ID in internal mode."',
        "fi",
    ]
    assert "dev-python-path.txt" in verify
    assert "--artifact-only" in verify
    assert "Exactly one of --expect-notarized or --expect-internal-adhoc is required." in verify
    assert "--sparkle-signature-file" in verify
    assert "--trusted-sparkle-public-key" in verify
    assert "--expected-developer-id-identity" in verify
    assert "--expected-developer-team-id" in verify
    assert "--expected-source-commit" in verify
    assert "--expected-core-build-id" in verify
    for invocation in (
        'verify_signed_app "$APP_BUNDLE" "Staging App"',
        'verify_signed_app "$UPDATE_APP" "Sparkle update ZIP"',
        'verify_signed_app "$DMG_APP" "DMG"',
        'verify_signed_dmg "$DMG_PATH"',
    ):
        assert invocation in verify
    assert "invoice_hub.release.runtime_manifest" in verify
    assert "InvoiceHub-macos-arm64.cdx.json" in verify
    assert 'package["package_id"] == "com.invoicehub.macos.arm64.dmg"' in verify
    assert 'expected_source_commit=build["source_commit"]' in verify
    assert "deterministic_build_id(root) == expected_core_build_id" in verify
    assert verify.count("| grep -q 'arm64'") >= 2
    assert "invoice_hub.release.content_scan" in verify
    assert "Contents/Resources/python" in verify
    assert 'verify_macos_platform_boundary "$app" "$label"' in verify
    boundary = verify.split("verify_macos_platform_boundary()", 1)[1].split("verify_app_layout()", 1)[0]
    assert boundary.count('find "$resources"') == 3
    assert "*/scripts/windows" in boundary
    assert "windows-x64-py314.lock" in boundary
    for windows_suffix in (
        "*.bat",
        "*.cmd",
        "*.ps1",
        "*.psm1",
        "*.exe",
        "*.dll",
        "*.pyd",
        "*.msi",
        "*.msix",
    ):
        assert windows_suffix in verify
    assert "contains Windows launcher scripts or a Windows dependency lock" in boundary
    assert "contains Windows shell files" in boundary
    assert "embedded runtime contains Windows binaries" in boundary
    assert 'ditto "$SOURCE_ROOT/src" "$CORE/src"' in build
    assert 'ditto "$SOURCE_ROOT/web" "$CORE/web"' in build
    assert 'cp "$SOURCE_ROOT/requirements/macos-arm64-py314.lock"' in build
    assert 'SOURCE_ROOT/scripts/windows' not in build
    assert 'SOURCE_ROOT/requirements/windows-x64-py314.lock' not in build
    assert 'ditto -x -k "$UPDATE_ZIP"' in verify
    assert 'hdiutil attach "$DMG_PATH" -readonly -nobrowse' in verify
    assert verify.count("cmp -s") >= 6
    assert verify.count("verify_embedded_core_identity") >= 3
    assert "Curve25519.Signing.PublicKey" in sparkle_verifier
    assert "SUPublicEDKey" in sparkle_verifier
    assert "isValidSignature" in sparkle_verifier
    assert "--trusted-public-key" in sparkle_verifier
    assert "--signature-file" in sparkle_verifier
    assert build.count("LC_ALL=C LANG=C /usr/bin/shasum -a 256") == 2

    provenance = _text("src/invoice_hub/release/provenance.py")
    artifact_only = provenance.index('"--artifact-only"')
    expect_notarized = provenance.index('"--expect-notarized"', artifact_only)
    assert artifact_only < expect_notarized


@pytest.mark.skipif(
    not Path("/bin/bash").is_file(),
    reason="dynamic macOS verifier contract requires POSIX /bin/bash; static contracts still run",
)
def test_macos_release_verifier_requires_exactly_one_signature_expectation() -> None:
    verifier = ROOT / "macos/InvoiceHubMac/script/verify_macos_release.sh"
    common = [
        "/bin/bash",
        str(verifier),
        "--dmg",
        "/does-not-exist/InvoiceHub.dmg",
        "--update-zip",
        "/does-not-exist/InvoiceHub.zip",
        "--sparkle-signature-file",
        "/does-not-exist/InvoiceHub.signature",
        "--trusted-sparkle-public-key",
        "test-public-key",
        "--expected-source-commit",
        "a" * 40,
        "--expected-core-build-id",
        "b" * 64,
    ]

    for mode_args in ([], ["--expect-notarized", "--expect-internal-adhoc"]):
        completed = subprocess.run(common + mode_args, check=False, capture_output=True, text=True)
        assert completed.returncode == 1
        assert "Exactly one of --expect-notarized or --expect-internal-adhoc is required." in completed.stderr

    accepted_modes = (
        ["--expect-internal-adhoc"],
        [
            "--expect-notarized",
            "--expected-developer-id-identity",
            "Developer ID Application: InvoiceHub Test (ABCDE12345)",
            "--expected-developer-team-id",
            "ABCDE12345",
        ],
    )
    for mode_args in accepted_modes:
        completed = subprocess.run(common + mode_args, check=False, capture_output=True, text=True)
        assert completed.returncode == 1
        assert "DMG is missing: /does-not-exist/InvoiceHub.dmg" in completed.stderr
        assert "Exactly one of --expect-notarized or --expect-internal-adhoc is required." not in completed.stderr


def test_macos_release_verifier_does_not_write_bytecode_into_signed_apps() -> None:
    verify = _text("macos/InvoiceHubMac/script/verify_macos_release.sh")
    identity = verify.split("verify_embedded_core_identity() {", 1)[1].split(
        "\n}\n\nverify_signed_app() {", 1
    )[0]
    content_scan = verify.split("scan_app_content() {", 1)[1].split(
        "\n}\n\nditto -x -k", 1
    )[0]

    assert identity.count("PYTHONDONTWRITEBYTECODE=1") == 3
    assert (
        'PYTHONDONTWRITEBYTECODE=1 PYTHONPATH="$core/src" '
        'INVOICE_HUB_RELEASE_MODE=1 "$python" -B -c'
        in identity
    )
    assert 'PYTHONDONTWRITEBYTECODE=1 "$python" -I -B -m pip check' in identity
    assert (
        'PYTHONDONTWRITEBYTECODE=1 "$python" -I -B -c '
        "'import tkinter, ssl, sqlite3, fitz, PIL; print(\"embedded-runtime-ok\")'"
        in identity
    )
    assert (
        'PYTHONDONTWRITEBYTECODE=1 PYTHONPATH="$core/src" "$python" '
        "-B -m invoice_hub.release.content_scan"
        in content_scan
    )


def test_macos_ci_uses_a_current_arm64_runner_and_preserves_source_imports() -> None:
    workflow = _text(".github/workflows/ci.yml")
    assert "runs-on: macos-15" in workflow
    assert 'PYTHONPATH="$PWD/src" python -m pytest' in workflow
    assert 'test "$(uname -m)" = "arm64"' in workflow


def test_sparkle_install_bridge_is_origin_restricted_and_monitor_safe() -> None:
    updater = _text("macos/InvoiceHubMac/Sources/InvoiceHubClient/Services/InvoiceHubSparkleUpdater.swift")
    controller = _text("macos/InvoiceHubMac/Sources/InvoiceHubClient/Services/LocalBackendController.swift")
    webview = _text("macos/InvoiceHubMac/Sources/InvoiceHubClient/Views/WebView.swift")
    commands = _text("macos/InvoiceHubMac/Sources/InvoiceHubClient/Commands/InvoiceHubCommands.swift")
    sidebar = _text("macos/InvoiceHubMac/Sources/InvoiceHubClient/Views/SidebarView.swift")

    assert "SPUStandardUpdaterController" in updater
    assert "allowedChannels" in updater and '["beta"]' in updater
    assert "shouldPostponeRelaunchForUpdate" in updater
    assert "prepareMonitorForUpdateInstall" in updater
    assert "restoreMonitorAfterUpdateIfNeeded" in updater
    assert "restore-monitor-after-update.json" in controller
    assert controller.index('"restore_monitor": true') < controller.index("apiClient.stopMonitor()")
    assert "releaseAfterVerifiedOwnedStartup" in controller
    assert "canRecoverMarkedMonitor" in controller
    assert 'await runOwnedControlAction("正在启动持续监听...")' in controller
    assert 'await runOwnedControlAction("正在停止持续监听...")' in controller
    assert commands.count(".disabled(!backend.canStopOrRestart)") >= 3
    assert sidebar.count(".disabled(!backend.canStopOrRestart)") >= 2
    assert 'case "installUpdate"' in webview
    assert "WebOriginPolicy.allowsScriptMessage" in webview
