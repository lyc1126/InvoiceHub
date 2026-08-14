#!/usr/bin/env bash
set -euo pipefail

VERSION="0.3.0-alpha.1"
BUILD_NUMBER="1"
PYTHON_VERSION="3.14.6"
BUNDLE_ID="com.invoicehub.mac"
PACKAGE_ID="com.invoicehub.macos.arm64.dmg"
SPARKLE_PACKAGE_ID="com.invoicehub.macos.arm64.sparkle"
SPARKLE_KEYCHAIN_ACCOUNT="com.invoicehub.release"
FEED_URL="https://lyc1126.github.io/InvoiceHub/updates/alpha/appcast.xml"

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
REPO_ROOT="$(cd "$ROOT_DIR/../.." && pwd)"
DIST_DIR="$REPO_ROOT/dist"
STAGING="$REPO_ROOT/release-staging/macos-release-$VERSION"
SOURCE_ROOT="$STAGING/source"
RUNTIME_ROOT="$REPO_ROOT/release-staging/macos-runtime-$PYTHON_VERSION-arm64"
RUNTIME_DIR="$RUNTIME_ROOT/python"
LOCK="$REPO_ROOT/requirements/macos-arm64-py314.lock"
SOURCE_COMMIT=""
INTERNAL_UNSIGNED="false"
CLEAN="false"
OFFLINE="false"

while [[ $# -gt 0 ]]; do
  case "$1" in
    --source-commit) SOURCE_COMMIT="$2"; shift 2 ;;
    --internal-unsigned) INTERNAL_UNSIGNED="true"; shift ;;
    --clean) CLEAN="true"; shift ;;
    --offline) OFFLINE="true"; shift ;;
    *) echo "Unknown argument: $1" >&2; exit 2 ;;
  esac
done

[[ "$(uname -s)" == "Darwin" && "$(uname -m)" == "arm64" ]] || { echo "Apple Silicon macOS is required." >&2; exit 1; }
[[ "$SOURCE_COMMIT" =~ ^[0-9a-f]{40}$ ]] || { echo "--source-commit must be a lowercase 40-character Git SHA." >&2; exit 2; }
[[ "$(git -C "$REPO_ROOT" rev-parse HEAD)" == "$SOURCE_COMMIT" ]] || { echo "HEAD does not match --source-commit." >&2; exit 1; }
[[ -z "$(git -C "$REPO_ROOT" status --porcelain=v1 --untracked-files=no)" ]] || { echo "Tracked source changes are present." >&2; exit 1; }
grep -Fqx "PRODUCT_VERSION = \"$VERSION\"" "$REPO_ROOT/src/invoice_hub/version.py" || { echo "VERSION differs from invoice_hub.version." >&2; exit 1; }
grep -Fqx "MACOS_BUILD_NUMBER = \"$BUILD_NUMBER\"" "$REPO_ROOT/src/invoice_hub/version.py" || { echo "BUILD_NUMBER differs from invoice_hub.version." >&2; exit 1; }
grep -Fqx "MACOS_DMG_PACKAGE_ID = \"$PACKAGE_ID\"" "$REPO_ROOT/src/invoice_hub/version.py" || { echo "PACKAGE_ID differs from invoice_hub.version." >&2; exit 1; }
grep -Fqx "MACOS_SPARKLE_PACKAGE_ID = \"$SPARKLE_PACKAGE_ID\"" "$REPO_ROOT/src/invoice_hub/version.py" || { echo "SPARKLE_PACKAGE_ID differs from invoice_hub.version." >&2; exit 1; }
grep -Fqx "MACOS_SPARKLE_KEYCHAIN_ACCOUNT = \"$SPARKLE_KEYCHAIN_ACCOUNT\"" "$REPO_ROOT/src/invoice_hub/version.py" || { echo "SPARKLE_KEYCHAIN_ACCOUNT differs from invoice_hub.version." >&2; exit 1; }
[[ -n "${INVOICE_HUB_SPARKLE_PUBLIC_KEY:-}" ]] || { echo "INVOICE_HUB_SPARKLE_PUBLIC_KEY is required." >&2; exit 1; }
if [[ "$INTERNAL_UNSIGNED" == "false" ]]; then
  [[ -n "${INVOICE_HUB_APPLE_SIGNING_IDENTITY:-}" ]] || { echo "INVOICE_HUB_APPLE_SIGNING_IDENTITY is required." >&2; exit 1; }
  [[ -n "${INVOICE_HUB_APPLE_TEAM_ID:-}" ]] || { echo "INVOICE_HUB_APPLE_TEAM_ID is required." >&2; exit 1; }
  [[ -n "${INVOICE_HUB_NOTARY_PROFILE:-}" ]] || { echo "INVOICE_HUB_NOTARY_PROFILE is required." >&2; exit 1; }
  if [[ "$INVOICE_HUB_APPLE_SIGNING_IDENTITY" =~ ^Developer\ ID\ Application:\ .+\ \(([A-Z0-9]{10})\)$ ]]; then
    IDENTITY_TEAM_ID="${BASH_REMATCH[1]}"
  else
    echo "INVOICE_HUB_APPLE_SIGNING_IDENTITY must be a Developer ID Application identity." >&2
    exit 1
  fi
  [[ "$INVOICE_HUB_APPLE_TEAM_ID" =~ ^[A-Z0-9]{10}$ && "$INVOICE_HUB_APPLE_TEAM_ID" == "$IDENTITY_TEAM_ID" ]] || {
    echo "INVOICE_HUB_APPLE_TEAM_ID must exactly match the signing identity Team ID." >&2
    exit 1
  }
fi

if [[ "$CLEAN" == "true" ]]; then
  rm -rf "$STAGING"
fi
mkdir -p "$STAGING" "$DIST_DIR"
INTERNAL_MARKER="$DIST_DIR/InvoiceHub-v$VERSION-macos-arm64.INTERNAL-UNSIGNED.txt"
rm -f "$INTERNAL_MARKER"
RUNTIME_ARGS=(--output-root "$RUNTIME_ROOT")
[[ "$CLEAN" == "true" ]] && RUNTIME_ARGS+=(--clean)
[[ "$OFFLINE" == "true" ]] && RUNTIME_ARGS+=(--offline)
"$ROOT_DIR/script/prepare_release_runtime.sh" "${RUNTIME_ARGS[@]}"

rm -rf "$SOURCE_ROOT"
mkdir -p "$SOURCE_ROOT"
git -C "$REPO_ROOT" archive "$SOURCE_COMMIT" | /usr/bin/tar -x -C "$SOURCE_ROOT"
SOURCE_TIMESTAMP="$("$RUNTIME_DIR/bin/python3" -c '
from datetime import datetime, timezone
import sys
value = datetime.fromisoformat(sys.argv[1].replace("Z", "+00:00"))
print(value.astimezone(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z"))
' "$(git -C "$REPO_ROOT" show -s --format=%cI "$SOURCE_COMMIT")")"

SWIFT_ROOT="$SOURCE_ROOT/macos/InvoiceHubMac"
swift package --package-path "$SWIFT_ROOT" resolve
swift build --package-path "$SWIFT_ROOT" --configuration release --arch arm64
BIN_DIR="$(swift build --package-path "$SWIFT_ROOT" --configuration release --arch arm64 --show-bin-path)"
APP_BUNDLE="$STAGING/InvoiceHub.app"
CONTENTS="$APP_BUNDLE/Contents"
MACOS_DIR="$CONTENTS/MacOS"
RESOURCES="$CONTENTS/Resources"
FRAMEWORKS="$CONTENTS/Frameworks"
CORE="$RESOURCES/invoice-hub-core"
APP_BINARY="$MACOS_DIR/InvoiceHubMac"
INFO_PLIST="$CONTENTS/Info.plist"
rm -rf "$APP_BUNDLE"
mkdir -p "$MACOS_DIR" "$RESOURCES" "$FRAMEWORKS" "$CORE"
cp "$BIN_DIR/InvoiceHubMac" "$APP_BINARY"
chmod +x "$APP_BINARY"
ditto "$BIN_DIR/Sparkle.framework" "$FRAMEWORKS/Sparkle.framework"
if ! otool -l "$APP_BINARY" | grep -q '@executable_path/../Frameworks'; then
  install_name_tool -add_rpath '@executable_path/../Frameworks' "$APP_BINARY"
fi

ditto "$RUNTIME_DIR" "$RESOURCES/python"
ditto "$SOURCE_ROOT/src" "$CORE/src"
ditto "$SOURCE_ROOT/web" "$CORE/web"
ditto "$SOURCE_ROOT/docs/jierui" "$CORE/docs/jierui"
mkdir -p "$CORE/scripts/tools" "$CORE/requirements"
cp "$SOURCE_ROOT/scripts/tools/jierui_voucher_import.py" "$CORE/scripts/tools/jierui_voucher_import.py"
cp "$SOURCE_ROOT/requirements/macos-arm64-py314.lock" "$CORE/requirements/macos-arm64-py314.lock"
cp "$SOURCE_ROOT/pyproject.toml" "$SOURCE_ROOT/LICENSE" "$SOURCE_ROOT/THIRD_PARTY_NOTICES.md" "$CORE/"
find "$CORE" -type d -name '__pycache__' -prune -exec rm -rf {} +
find "$CORE" -type f \( -name '*.pyc' -o -name '*.pyo' -o -name '.DS_Store' \) -delete
[[ ! -e "$RESOURCES/dev-python-path.txt" && ! -d "$CORE/.venv" ]]

EMBEDDED_PYTHON="$RESOURCES/python/bin/python3"
PYTHONPATH="$SOURCE_ROOT/src" "$EMBEDDED_PYTHON" -m invoice_hub.release.build_manifest \
  --root "$CORE" \
  --output "$CORE/invoice-hub-build.json" \
  --source-commit "$SOURCE_COMMIT" \
  --built-at "$SOURCE_TIMESTAMP"
CORE_BUILD_ID="$("$EMBEDDED_PYTHON" -c 'import json,sys; print(json.load(open(sys.argv[1], encoding="utf-8"))["build_id"])' "$CORE/invoice-hub-build.json")"
PYTHONPATH="$SOURCE_ROOT/src" "$EMBEDDED_PYTHON" -m invoice_hub.release.package_manifest \
  --output "$CORE/invoice-hub-package.json" \
  --package-id "$PACKAGE_ID" \
  --platform macos \
  --architecture arm64 \
  --package-type dmg \
  --python-version "$PYTHON_VERSION" \
  --dependency-lock "$LOCK" \
  --core-build-id "$CORE_BUILD_ID" \
  --source-commit "$SOURCE_COMMIT"
PYTHONDONTWRITEBYTECODE=1 PYTHONPATH="$SOURCE_ROOT/src" "$EMBEDDED_PYTHON" -m invoice_hub.release.sbom \
  --dependency-lock "$LOCK" \
  --output "$CORE/sbom/InvoiceHub-macos-arm64.cdx.json" \
  --target macos-arm64-dmg

cat >"$INFO_PLIST" <<PLIST
<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0">
<dict>
  <key>CFBundleExecutable</key><string>InvoiceHubMac</string>
  <key>CFBundleIdentifier</key><string>$BUNDLE_ID</string>
  <key>CFBundleName</key><string>InvoiceHub</string>
  <key>CFBundleDisplayName</key><string>InvoiceHub</string>
  <key>CFBundlePackageType</key><string>APPL</string>
  <key>CFBundleShortVersionString</key><string>$VERSION</string>
  <key>CFBundleVersion</key><string>$BUILD_NUMBER</string>
  <key>LSMinimumSystemVersion</key><string>13.0</string>
  <key>NSPrincipalClass</key><string>NSApplication</string>
  <key>NSHighResolutionCapable</key><true/>
  <key>InvoiceHubReleaseMode</key><true/>
  <key>SUFeedURL</key><string>$FEED_URL</string>
  <key>SUPublicEDKey</key><string>$INVOICE_HUB_SPARKLE_PUBLIC_KEY</string>
  <key>SUEnableAutomaticChecks</key><false/>
</dict>
</plist>
PLIST
plutil -lint "$INFO_PLIST"

sign_macho_tree() {
  local identity="$1"
  while IFS= read -r -d '' candidate; do
    if file "$candidate" | grep -q 'Mach-O'; then
      if [[ "$identity" == "-" ]]; then
        codesign --force --sign - "$candidate"
      else
        codesign --force --options runtime --timestamp --sign "$identity" "$candidate"
      fi
    fi
  done < <(find "$RESOURCES/python" -type f -print0)
}

if [[ "$INTERNAL_UNSIGNED" == "true" ]]; then
  SIGN_IDENTITY="-"
  SIGNATURE_MODE="internal-adhoc"
else
  SIGN_IDENTITY="$INVOICE_HUB_APPLE_SIGNING_IDENTITY"
  SIGNATURE_MODE="developer-id-notarized"
fi
sign_macho_tree "$SIGN_IDENTITY"
PYTHONDONTWRITEBYTECODE=1 PYTHONPATH="$SOURCE_ROOT/src" "$EMBEDDED_PYTHON" -m invoice_hub.release.runtime_manifest write \
  --runtime-dir "$RESOURCES/python" \
  --dependency-lock "$LOCK" \
  --platform macos \
  --architecture arm64 \
  --python-version "$PYTHON_VERSION" \
  --python-executable bin/python3 \
  --source "python-build-standalone 20260623 signed bundle runtime" \
  --no-execute-probe
if [[ "$INTERNAL_UNSIGNED" == "true" ]]; then
  codesign --force --deep --sign - "$FRAMEWORKS/Sparkle.framework"
  codesign --force --sign - "$APP_BINARY"
  codesign --force --deep --sign - "$APP_BUNDLE"
else
  codesign --force --deep --options runtime --timestamp --sign "$SIGN_IDENTITY" "$FRAMEWORKS/Sparkle.framework"
  codesign --force --options runtime --timestamp --sign "$SIGN_IDENTITY" "$APP_BINARY"
  codesign --force --options runtime --timestamp --sign "$SIGN_IDENTITY" "$APP_BUNDLE"
fi
codesign --verify --deep --strict --verbose=2 "$APP_BUNDLE"

APP_NOTARY_ZIP="$STAGING/InvoiceHub-notary.zip"
if [[ "$INTERNAL_UNSIGNED" == "false" ]]; then
  rm -f "$APP_NOTARY_ZIP"
  ditto -c -k --sequesterRsrc --keepParent "$APP_BUNDLE" "$APP_NOTARY_ZIP"
  xcrun notarytool submit "$APP_NOTARY_ZIP" --keychain-profile "$INVOICE_HUB_NOTARY_PROFILE" --wait
  xcrun stapler staple "$APP_BUNDLE"
  xcrun stapler validate "$APP_BUNDLE"
  spctl --assess --type execute --verbose=2 "$APP_BUNDLE"
fi

UPDATE_ZIP="$DIST_DIR/InvoiceHub-v$VERSION-macos-arm64-update.zip"
DMG_PATH="$DIST_DIR/InvoiceHub-v$VERSION-macos-arm64.dmg"
rm -f "$UPDATE_ZIP" "$DMG_PATH"
ditto -c -k --sequesterRsrc --keepParent "$APP_BUNDLE" "$UPDATE_ZIP"
SIGN_UPDATE="$SWIFT_ROOT/.build/artifacts/sparkle/Sparkle/bin/sign_update"
[[ -x "$SIGN_UPDATE" ]] || { echo "Sparkle sign_update tool is missing." >&2; exit 1; }
"$SIGN_UPDATE" --account "$SPARKLE_KEYCHAIN_ACCOUNT" "$UPDATE_ZIP" >"$UPDATE_ZIP.sparkle-signature.txt"
SPARKLE_PUBLIC_KEY_SHA256="$("$EMBEDDED_PYTHON" -c '
import base64, hashlib, sys
key = base64.b64decode(sys.argv[1], validate=True)
if len(key) != 32:
    raise ValueError("Sparkle public key must decode to 32 bytes")
print(hashlib.sha256(key).hexdigest())
' "$INVOICE_HUB_SPARKLE_PUBLIC_KEY")"
swift "$ROOT_DIR/script/verify_sparkle_update.swift" \
  --archive "$UPDATE_ZIP" \
  --signature-file "$UPDATE_ZIP.sparkle-signature.txt" \
  --trusted-public-key "$INVOICE_HUB_SPARKLE_PUBLIC_KEY" \
  --app "$APP_BUNDLE"

DMG_STAGE="$STAGING/dmg"
rm -rf "$DMG_STAGE"
mkdir -p "$DMG_STAGE"
ditto "$APP_BUNDLE" "$DMG_STAGE/InvoiceHub.app"
ln -s /Applications "$DMG_STAGE/Applications"
hdiutil create -volname "InvoiceHub $VERSION" -srcfolder "$DMG_STAGE" -format UDZO -ov "$DMG_PATH"
if [[ "$INTERNAL_UNSIGNED" == "true" ]]; then
  codesign --force --sign - "$DMG_PATH"
else
  codesign --force --timestamp --sign "$SIGN_IDENTITY" "$DMG_PATH"
  xcrun notarytool submit "$DMG_PATH" --keychain-profile "$INVOICE_HUB_NOTARY_PROFILE" --wait
  xcrun stapler staple "$DMG_PATH"
fi
codesign --verify --verbose=2 "$DMG_PATH"

VERIFY_ARGS=(
  --app "$APP_BUNDLE"
  --dmg "$DMG_PATH"
  --update-zip "$UPDATE_ZIP"
  --sparkle-signature-file "$UPDATE_ZIP.sparkle-signature.txt"
  --trusted-sparkle-public-key "$INVOICE_HUB_SPARKLE_PUBLIC_KEY"
  --expected-source-commit "$SOURCE_COMMIT"
  --expected-core-build-id "$CORE_BUILD_ID"
)
if [[ "$INTERNAL_UNSIGNED" == "false" ]]; then
  VERIFY_ARGS+=(
    --expect-notarized
    --expected-developer-id-identity "$SIGN_IDENTITY"
    --expected-developer-team-id "$INVOICE_HUB_APPLE_TEAM_ID"
  )
else
  VERIFY_ARGS+=(--expect-internal-adhoc)
fi
"$ROOT_DIR/script/verify_macos_release.sh" "${VERIFY_ARGS[@]}"

DMG_SHA="$(LC_ALL=C LANG=C /usr/bin/shasum -a 256 "$DMG_PATH" | /usr/bin/awk '{print $1}')"
UPDATE_SHA="$(LC_ALL=C LANG=C /usr/bin/shasum -a 256 "$UPDATE_ZIP" | /usr/bin/awk '{print $1}')"
printf '%s  %s\n' "$DMG_SHA" "$(basename "$DMG_PATH")" >"$DMG_PATH.sha256"
printf '%s  %s\n' "$UPDATE_SHA" "$(basename "$UPDATE_ZIP")" >"$UPDATE_ZIP.sha256"
RECEIPT="$DIST_DIR/InvoiceHub-v$VERSION-macos-arm64.build-receipt.json"
"$EMBEDDED_PYTHON" -c '
import json, pathlib, sys
payload = {
    "schema_version": 4,
    "product_version": sys.argv[1],
    "python_version": sys.argv[2],
    "source_commit": sys.argv[3],
    "core_build_id": sys.argv[4],
    "dmg": {
        "name": pathlib.Path(sys.argv[5]).name,
        "size_bytes": pathlib.Path(sys.argv[5]).stat().st_size,
        "sha256": sys.argv[6],
        "package_id": sys.argv[12],
    },
    "sparkle_zip": {
        "name": pathlib.Path(sys.argv[7]).name,
        "size_bytes": pathlib.Path(sys.argv[7]).stat().st_size,
        "sha256": sys.argv[8],
        "package_id": sys.argv[13],
    },
    "internal_unsigned": sys.argv[9] == "true",
    "notarized": sys.argv[9] != "true",
    "signature_mode": sys.argv[17],
    "sparkle_keychain_account": sys.argv[18],
    "package_ids": {
        "dmg": sys.argv[12],
        "sparkle": sys.argv[13],
    },
    "sparkle_signature_output": pathlib.Path(sys.argv[11]).read_text(encoding="utf-8").strip(),
    "sparkle_signature_verified": True,
    "sparkle_public_key_sha256": sys.argv[14],
    "verification_complete": True,
    "observed_developer_id_identity": sys.argv[15],
    "observed_developer_team_id": sys.argv[16],
    "distribution_verifier": "verify_macos_release.sh/v4",
    "built_at": __import__("datetime").datetime.now(__import__("datetime").timezone.utc).isoformat(),
}
pathlib.Path(sys.argv[10]).write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")
' "$VERSION" "$PYTHON_VERSION" "$SOURCE_COMMIT" "$CORE_BUILD_ID" "$DMG_PATH" "$DMG_SHA" "$UPDATE_ZIP" "$UPDATE_SHA" "$INTERNAL_UNSIGNED" "$RECEIPT" "$UPDATE_ZIP.sparkle-signature.txt" "$PACKAGE_ID" "$SPARKLE_PACKAGE_ID" "$SPARKLE_PUBLIC_KEY_SHA256" "${INVOICE_HUB_APPLE_SIGNING_IDENTITY:-}" "${INVOICE_HUB_APPLE_TEAM_ID:-}" "$SIGNATURE_MODE" "$SPARKLE_KEYCHAIN_ACCOUNT"

if [[ "$INTERNAL_UNSIGNED" == "true" ]]; then
  printf '%s\n' "INTERNAL TEST ONLY: ad-hoc signed, not notarized, not approved for public appcast or distribution." >"$INTERNAL_MARKER"
fi
printf '%s\n%s\n' "$DMG_PATH" "$UPDATE_ZIP"
