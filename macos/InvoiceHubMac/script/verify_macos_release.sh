#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
APP_BUNDLE=""
DMG_PATH=""
UPDATE_ZIP=""
SPARKLE_SIGNATURE_FILE=""
TRUSTED_SPARKLE_PUBLIC_KEY=""
EXPECTED_DEVELOPER_ID_IDENTITY=""
EXPECTED_DEVELOPER_TEAM_ID=""
EXPECTED_SOURCE_COMMIT=""
EXPECTED_CORE_BUILD_ID=""
EXPECT_NOTARIZED="false"
EXPECT_INTERNAL_ADHOC="false"
ARTIFACT_ONLY="false"

die() {
  echo "$1" >&2
  exit 1
}

while [[ $# -gt 0 ]]; do
  case "$1" in
    --app) APP_BUNDLE="$2"; shift 2 ;;
    --dmg) DMG_PATH="$2"; shift 2 ;;
    --update-zip) UPDATE_ZIP="$2"; shift 2 ;;
    --sparkle-signature-file) SPARKLE_SIGNATURE_FILE="$2"; shift 2 ;;
    --trusted-sparkle-public-key) TRUSTED_SPARKLE_PUBLIC_KEY="$2"; shift 2 ;;
    --expected-developer-id-identity) EXPECTED_DEVELOPER_ID_IDENTITY="$2"; shift 2 ;;
    --expected-developer-team-id) EXPECTED_DEVELOPER_TEAM_ID="$2"; shift 2 ;;
    --expected-source-commit) EXPECTED_SOURCE_COMMIT="$2"; shift 2 ;;
    --expected-core-build-id) EXPECTED_CORE_BUILD_ID="$2"; shift 2 ;;
    --artifact-only) ARTIFACT_ONLY="true"; shift ;;
    --expect-notarized) EXPECT_NOTARIZED="true"; shift ;;
    --expect-internal-adhoc) EXPECT_INTERNAL_ADHOC="true"; shift ;;
    *) echo "Unknown argument: $1" >&2; exit 2 ;;
  esac
done

if [[ "$EXPECT_NOTARIZED" == "$EXPECT_INTERNAL_ADHOC" ]]; then
  die "Exactly one of --expect-notarized or --expect-internal-adhoc is required."
fi
[[ -f "$DMG_PATH" ]] || die "DMG is missing: $DMG_PATH"
[[ -f "$UPDATE_ZIP" ]] || die "Sparkle update ZIP is missing: $UPDATE_ZIP"
[[ -f "$SPARKLE_SIGNATURE_FILE" ]] || die "Sparkle signature file is missing: $SPARKLE_SIGNATURE_FILE"
[[ -n "$TRUSTED_SPARKLE_PUBLIC_KEY" ]] || die "A trusted Sparkle public key is required."
[[ "$EXPECTED_SOURCE_COMMIT" =~ ^[0-9a-f]{40}$ ]] || die "Expected source commit must be a lowercase 40-character Git SHA."
[[ "$EXPECTED_CORE_BUILD_ID" =~ ^[0-9a-f]{64}$ ]] || die "Expected core build ID must be a lowercase SHA-256."
if [[ "$ARTIFACT_ONLY" == "true" ]]; then
  [[ -z "$APP_BUNDLE" ]] || die "--artifact-only must not accept a staging --app."
else
  [[ -d "$APP_BUNDLE" ]] || die "App bundle is missing: $APP_BUNDLE"
fi
if [[ "$EXPECT_NOTARIZED" == "true" ]]; then
  [[ "$EXPECTED_DEVELOPER_TEAM_ID" =~ ^[A-Z0-9]{10}$ ]] || die "Expected Developer ID team must be a 10-character identifier."
  if [[ "$EXPECTED_DEVELOPER_ID_IDENTITY" =~ ^Developer\ ID\ Application:\ .+\ \(([A-Z0-9]{10})\)$ ]]; then
    IDENTITY_TEAM_ID="${BASH_REMATCH[1]}"
  else
    die "Expected Developer ID identity has an invalid format."
  fi
  [[ "$IDENTITY_TEAM_ID" == "$EXPECTED_DEVELOPER_TEAM_ID" ]] || die "Developer ID identity and Team ID disagree."
elif [[ -n "$EXPECTED_DEVELOPER_ID_IDENTITY$EXPECTED_DEVELOPER_TEAM_ID" ]]; then
  die "Developer ID identity and Team ID are only valid with --expect-notarized."
fi

VERIFY_TEMP_ROOT="$(mktemp -d "${TMPDIR:-/tmp}/invoicehub-macos-release-verify.XXXXXX")"
DMG_MOUNT="$VERIFY_TEMP_ROOT/dmg"
UPDATE_ROOT="$VERIFY_TEMP_ROOT/update"
DMG_ATTACHED="false"
cleanup() {
  if [[ "$DMG_ATTACHED" == "true" ]]; then
    hdiutil detach "$DMG_MOUNT" >/dev/null 2>&1 || true
  fi
  rm -rf "$VERIFY_TEMP_ROOT"
}
trap cleanup EXIT
mkdir -p "$DMG_MOUNT" "$UPDATE_ROOT"

verify_macos_platform_boundary() {
  local app="$1"
  local label="$2"
  local resources="$app/Contents/Resources"

  if find "$resources" \( -type d -path '*/scripts/windows' -o -type f -iname 'windows-x64-py314.lock' \) -print -quit | grep -q .; then
    die "$label contains Windows launcher scripts or a Windows dependency lock."
  fi
  if find "$resources" -type f \( -iname '*.bat' -o -iname '*.cmd' -o -iname '*.ps1' -o -iname '*.psm1' \) -print -quit | grep -q .; then
    die "$label contains Windows shell files."
  fi
  if find "$resources" -type f \( -iname '*.exe' -o -iname '*.dll' -o -iname '*.pyd' -o -iname '*.msi' -o -iname '*.msix' \) -print -quit | grep -q .; then
    die "$label embedded runtime contains Windows binaries."
  fi
}

verify_app_layout() {
  local app="$1"
  local label="$2"
  local contents="$app/Contents"
  local resources="$contents/Resources"
  local core="$resources/invoice-hub-core"
  local plist="$contents/Info.plist"
  local python="$resources/python/bin/python3"

  [[ -x "$contents/MacOS/InvoiceHubMac" ]] || die "$label App executable is missing."
  [[ -x "$python" ]] || die "$label embedded Python is missing."
  [[ ! -e "$resources/dev-python-path.txt" ]] || die "$label contains a development Python marker."
  [[ ! -d "$core/.venv" ]] || die "$label contains a development virtualenv."
  [[ ! -e "$core/config/app.local.json" ]] || die "$label contains local config."
  [[ -f "$core/sbom/InvoiceHub-macos-arm64.cdx.json" ]] || die "$label macOS CycloneDX SBOM is missing."
  verify_macos_platform_boundary "$app" "$label"
  [[ "$(/usr/libexec/PlistBuddy -c 'Print :CFBundleShortVersionString' "$plist")" == "0.3.0-alpha.1" ]] || die "$label version is invalid."
  [[ "$(/usr/libexec/PlistBuddy -c 'Print :CFBundleVersion' "$plist")" == "1" ]] || die "$label build number is invalid."
  [[ "$(/usr/libexec/PlistBuddy -c 'Print :LSMinimumSystemVersion' "$plist")" == "13.0" ]] || die "$label minimum macOS version is invalid."
  [[ "$(/usr/libexec/PlistBuddy -c 'Print :InvoiceHubReleaseMode' "$plist")" == "true" ]] || die "$label is not in release mode."
  [[ "$(/usr/libexec/PlistBuddy -c 'Print :SUEnableAutomaticChecks' "$plist")" == "false" ]] || die "$label has invalid Sparkle automatic-check settings."
  [[ "$(/usr/libexec/PlistBuddy -c 'Print :SUFeedURL' "$plist")" == "https://lyc1126.github.io/InvoiceHub/updates/alpha/appcast.xml" ]] || die "$label has an invalid Sparkle feed URL."
  [[ -n "$(/usr/libexec/PlistBuddy -c 'Print :SUPublicEDKey' "$plist")" ]] || die "$label is missing SUPublicEDKey."
  file "$contents/MacOS/InvoiceHubMac" | grep -q 'arm64' || die "$label executable is not arm64."
  file "$python" | grep -q 'arm64' || die "$label embedded Python is not arm64."
}

verify_embedded_core_identity() {
  local app="$1"
  local label="$2"
  local core="$app/Contents/Resources/invoice-hub-core"
  local python="$app/Contents/Resources/python/bin/python3"
  PYTHONDONTWRITEBYTECODE=1 PYTHONPATH="$core/src" INVOICE_HUB_RELEASE_MODE=1 "$python" -B -c '
import json, pathlib, platform, sys
from invoice_hub.release.build_manifest import deterministic_build_id, load_build_manifest
from invoice_hub.release.package_manifest import load_package_manifest
from invoice_hub.release.runtime_manifest import validate_runtime_manifest
root = pathlib.Path(sys.argv[1])
expected_source_commit = sys.argv[2]
expected_core_build_id = sys.argv[3]
build = load_build_manifest(root, required=True)
package = load_package_manifest(
    root,
    expected_core_build_id=build["build_id"],
    expected_source_commit=build["source_commit"],
    required=True,
)
validate_runtime_manifest(
    pathlib.Path(sys.argv[4]),
    root / "requirements" / "macos-arm64-py314.lock",
    expected_platform="macos",
    expected_architecture="arm64",
    expected_python_version="3.14.6",
    execute_probe=False,
)
assert build["source_commit"] == expected_source_commit
assert build["build_id"] == expected_core_build_id
assert package["source_commit"] == expected_source_commit
assert package["core_build_id"] == expected_core_build_id
assert package["platform"] == "macos"
assert package["architecture"] == "arm64"
assert package["package_type"] == "dmg"
assert package["package_id"] == "com.invoicehub.macos.arm64.dmg"
assert deterministic_build_id(root) == expected_core_build_id
assert package["python_version"] == platform.python_version() == "3.14.6"
sbom = json.loads((root / "sbom" / "InvoiceHub-macos-arm64.cdx.json").read_text(encoding="utf-8"))
properties = {item["name"]: item["value"] for item in sbom["metadata"]["properties"]}
assert sbom["bomFormat"] == "CycloneDX" and sbom["specVersion"] == "1.6"
assert properties["invoicehub:dependency-lock-sha256"] == package["dependency_lock_sha256"]
' "$core" "$EXPECTED_SOURCE_COMMIT" "$EXPECTED_CORE_BUILD_ID" "$app/Contents/Resources/python"
  PYTHONDONTWRITEBYTECODE=1 "$python" -I -B -m pip check
  PYTHONDONTWRITEBYTECODE=1 "$python" -I -B -c 'import tkinter, ssl, sqlite3, fitz, PIL; print("embedded-runtime-ok")'
  echo "$label core identity verified."
}

verify_signed_app() {
  local app="$1"
  local label="$2"
  codesign --verify --deep --strict --verbose=2 "$app"
  if [[ "$EXPECT_NOTARIZED" == "true" ]]; then
    local details
    details="$(codesign -dvvv "$app" 2>&1)"
    grep -Fqx "Authority=$EXPECTED_DEVELOPER_ID_IDENTITY" <<<"$details" || die "$label does not have the expected Developer ID authority."
    grep -Fqx "TeamIdentifier=$EXPECTED_DEVELOPER_TEAM_ID" <<<"$details" || die "$label does not have the expected Developer Team ID."
    grep -q '^Runtime Version=' <<<"$details" || die "$label is missing the hardened runtime."
    xcrun stapler validate "$app"
    spctl --assess --type execute --verbose=2 "$app"
  else
    local details
    details="$(codesign -dvvv "$app" 2>&1)"
    grep -Fqx "Signature=adhoc" <<<"$details" || die "$label is not ad-hoc signed."
    if grep -q '^Authority=' <<<"$details"; then
      die "$label must not have a Developer ID authority in internal mode."
    fi
    if grep -q '^TeamIdentifier=' <<<"$details" && ! grep -Fqx "TeamIdentifier=not set" <<<"$details"; then
      die "$label must not have a Developer Team ID in internal mode."
    fi
  fi
}

verify_signed_dmg() {
  local dmg="$1"
  codesign --verify --verbose=2 "$dmg"
  if [[ "$EXPECT_NOTARIZED" == "true" ]]; then
    local details
    details="$(codesign -dvvv "$dmg" 2>&1)"
    grep -Fqx "Authority=$EXPECTED_DEVELOPER_ID_IDENTITY" <<<"$details" || die "DMG does not have the expected Developer ID authority."
    grep -Fqx "TeamIdentifier=$EXPECTED_DEVELOPER_TEAM_ID" <<<"$details" || die "DMG does not have the expected Developer Team ID."
    xcrun stapler validate "$dmg"
    spctl --assess --type open --context context:primary-signature --verbose=2 "$dmg"
  else
    local details
    details="$(codesign -dvvv "$dmg" 2>&1)"
    grep -Fqx "Signature=adhoc" <<<"$details" || die "DMG is not ad-hoc signed."
    if grep -q '^Authority=' <<<"$details"; then
      die "DMG must not have a Developer ID authority in internal mode."
    fi
    if grep -q '^TeamIdentifier=' <<<"$details" && ! grep -Fqx "TeamIdentifier=not set" <<<"$details"; then
      die "DMG must not have a Developer Team ID in internal mode."
    fi
  fi
}

scan_app_content() {
  local app="$1"
  local core="$app/Contents/Resources/invoice-hub-core"
  local python="$app/Contents/Resources/python/bin/python3"
  PYTHONDONTWRITEBYTECODE=1 PYTHONPATH="$core/src" "$python" -B -m invoice_hub.release.content_scan \
    --root "$app" \
    --dependency-prefix Contents/Resources/python \
    --dependency-prefix Contents/Frameworks
}

ditto -x -k "$UPDATE_ZIP" "$UPDATE_ROOT"
UPDATE_APP="$UPDATE_ROOT/InvoiceHub.app"
[[ -d "$UPDATE_APP" ]] || die "Sparkle update ZIP does not contain InvoiceHub.app."

hdiutil attach "$DMG_PATH" -readonly -nobrowse -mountpoint "$DMG_MOUNT" >/dev/null
DMG_ATTACHED="true"
DMG_APP="$DMG_MOUNT/InvoiceHub.app"
[[ -d "$DMG_APP" ]] || die "DMG does not contain InvoiceHub.app."

verify_signed_dmg "$DMG_PATH"

verify_app_layout "$UPDATE_APP" "Sparkle update ZIP"
verify_signed_app "$UPDATE_APP" "Sparkle update ZIP"
swift "$SCRIPT_DIR/verify_sparkle_update.swift" \
  --archive "$UPDATE_ZIP" \
  --signature-file "$SPARKLE_SIGNATURE_FILE" \
  --trusted-public-key "$TRUSTED_SPARKLE_PUBLIC_KEY" \
  --app "$UPDATE_APP"
verify_embedded_core_identity "$UPDATE_APP" "Sparkle update ZIP"

verify_app_layout "$DMG_APP" "DMG"
verify_signed_app "$DMG_APP" "DMG"
verify_embedded_core_identity "$DMG_APP" "DMG"

cmp -s "$UPDATE_APP/Contents/Info.plist" "$DMG_APP/Contents/Info.plist" || die "DMG and Sparkle update Info.plist differ."
cmp -s "$UPDATE_APP/Contents/Resources/invoice-hub-core/invoice-hub-build.json" "$DMG_APP/Contents/Resources/invoice-hub-core/invoice-hub-build.json" || die "DMG and Sparkle build manifests differ."
cmp -s "$UPDATE_APP/Contents/Resources/invoice-hub-core/invoice-hub-package.json" "$DMG_APP/Contents/Resources/invoice-hub-core/invoice-hub-package.json" || die "DMG and Sparkle package manifests differ."
scan_app_content "$UPDATE_APP"
scan_app_content "$DMG_APP"

if [[ "$ARTIFACT_ONLY" == "false" ]]; then
  verify_app_layout "$APP_BUNDLE" "Staging App"
  verify_signed_app "$APP_BUNDLE" "Staging App"
  verify_embedded_core_identity "$APP_BUNDLE" "Staging App"
  cmp -s "$APP_BUNDLE/Contents/Info.plist" "$UPDATE_APP/Contents/Info.plist" || die "Staging App and Sparkle update Info.plist differ."
  cmp -s "$APP_BUNDLE/Contents/Resources/invoice-hub-core/invoice-hub-build.json" "$UPDATE_APP/Contents/Resources/invoice-hub-core/invoice-hub-build.json" || die "Staging App and Sparkle build manifests differ."
  cmp -s "$APP_BUNDLE/Contents/Resources/invoice-hub-core/invoice-hub-package.json" "$UPDATE_APP/Contents/Resources/invoice-hub-core/invoice-hub-package.json" || die "Staging App and Sparkle package manifests differ."
  scan_app_content "$APP_BUNDLE"
fi

echo "macOS release distribution artifacts verified: $DMG_PATH and $UPDATE_ZIP"
