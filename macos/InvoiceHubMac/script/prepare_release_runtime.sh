#!/usr/bin/env bash
set -euo pipefail

PYTHON_VERSION="3.14.6"
PBS_RELEASE="20260623"
PBS_ASSET="cpython-${PYTHON_VERSION}+${PBS_RELEASE}-aarch64-apple-darwin-install_only_stripped.tar.gz"
PBS_URL="https://github.com/astral-sh/python-build-standalone/releases/download/${PBS_RELEASE}/cpython-${PYTHON_VERSION}%2B${PBS_RELEASE}-aarch64-apple-darwin-install_only_stripped.tar.gz"
PBS_SHA256="35d774f61d63c1fd4f1bc9495a7ada92e500dc4382a0df8a9910eb87ea48e8cf"

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
REPO_ROOT="$(cd "$ROOT_DIR/../.." && pwd)"
OUTPUT_ROOT="$REPO_ROOT/release-staging/macos-runtime-${PYTHON_VERSION}-arm64"
CLEAN="false"
OFFLINE="false"

while [[ $# -gt 0 ]]; do
  case "$1" in
    --output-root)
      OUTPUT_ROOT="$2"
      shift 2
      ;;
    --clean)
      CLEAN="true"
      shift
      ;;
    --offline)
      OFFLINE="true"
      shift
      ;;
    *)
      echo "Unknown argument: $1" >&2
      exit 2
      ;;
  esac
done

case "$OUTPUT_ROOT" in
  ""|"/"|"$HOME"|"$REPO_ROOT")
    echo "Refusing unsafe output root: $OUTPUT_ROOT" >&2
    exit 2
    ;;
esac

[[ "$(uname -s)" == "Darwin" ]] || { echo "macOS is required." >&2; exit 1; }
[[ "$(uname -m)" == "arm64" ]] || { echo "Apple Silicon arm64 is required." >&2; exit 1; }

RUNTIME_DIR="$OUTPUT_ROOT/python"
WHEELHOUSE="$OUTPUT_ROOT/wheelhouse"
DOWNLOAD_DIR="$OUTPUT_ROOT/downloads"
ARCHIVE="$DOWNLOAD_DIR/$PBS_ASSET"
LOCK="$REPO_ROOT/requirements/macos-arm64-py314.lock"

if [[ "$CLEAN" == "true" ]]; then
  rm -rf "$OUTPUT_ROOT"
fi
mkdir -p "$OUTPUT_ROOT" "$WHEELHOUSE" "$DOWNLOAD_DIR"

if [[ ! -f "$ARCHIVE" ]]; then
  [[ "$OFFLINE" == "false" ]] || { echo "Pinned runtime archive is missing in offline mode: $ARCHIVE" >&2; exit 1; }
  /usr/bin/curl --fail --location --proto '=https' --tlsv1.2 "$PBS_URL" --output "$ARCHIVE"
fi
ACTUAL_ARCHIVE_SHA="$(LC_ALL=C LANG=C /usr/bin/shasum -a 256 "$ARCHIVE" | /usr/bin/awk '{print $1}')"
[[ "$ACTUAL_ARCHIVE_SHA" == "$PBS_SHA256" ]] || {
  echo "Pinned runtime SHA-256 mismatch: expected=$PBS_SHA256 actual=$ACTUAL_ARCHIVE_SHA" >&2
  exit 1
}

if [[ ! -x "$RUNTIME_DIR/bin/python3" ]]; then
  rm -rf "$RUNTIME_DIR"
  /usr/bin/tar -xzf "$ARCHIVE" -C "$OUTPUT_ROOT"
fi
PYTHON="$RUNTIME_DIR/bin/python3"
[[ -x "$PYTHON" ]] || { echo "Extracted runtime Python is missing: $PYTHON" >&2; exit 1; }
[[ "$("$PYTHON" -I -c 'import platform; print(platform.python_version())')" == "$PYTHON_VERSION" ]] || {
  echo "Embedded Python version mismatch." >&2
  exit 1
}
[[ "$("$PYTHON" -I -c 'import platform; print(platform.machine())')" == "arm64" ]] || {
  echo "Embedded Python architecture mismatch." >&2
  exit 1
}

if [[ "$OFFLINE" == "false" ]]; then
  "$PYTHON" -I -m pip download \
    --requirement "$LOCK" \
    --require-hashes \
    --only-binary=:all: \
    --dest "$WHEELHOUSE"
fi
compgen -G "$WHEELHOUSE/*.whl" >/dev/null || { echo "macOS wheelhouse is empty: $WHEELHOUSE" >&2; exit 1; }
"$PYTHON" -I -m pip install \
  --requirement "$LOCK" \
  --require-hashes \
  --only-binary=:all: \
  --no-index \
  --find-links "$WHEELHOUSE"
"$PYTHON" -I -m pip check
"$PYTHON" -I -c 'import tkinter, ssl, sqlite3, fitz, PIL; print("macos-runtime-smoke-ok")'

find "$RUNTIME_DIR" -type d -name '__pycache__' -prune -exec rm -rf {} +
find "$RUNTIME_DIR" -type f \( -name '*.pyc' -o -name '*.pyo' -o -name '.DS_Store' \) -delete
WINDOWS_SHELL_FILES=(
  "$RUNTIME_DIR/lib/python3.14/ctypes/macholib/fetch_macholib.bat"
  "$RUNTIME_DIR/lib/python3.14/idlelib/idle.bat"
  "$RUNTIME_DIR/lib/python3.14/venv/scripts/common/Activate.ps1"
)
rm -f -- "${WINDOWS_SHELL_FILES[@]}"
REMAINING_WINDOWS_SHELL_FILES="$(
  find "$RUNTIME_DIR" -type f \
    \( -iname '*.bat' -o -iname '*.cmd' -o -iname '*.ps1' -o -iname '*.psm1' \) \
    -print -quit
)"
[[ -z "$REMAINING_WINDOWS_SHELL_FILES" ]] || {
  echo "macOS runtime still contains Windows shell files: $REMAINING_WINDOWS_SHELL_FILES" >&2
  exit 1
}
WINDOWS_BINARY_FILES=(
  "$RUNTIME_DIR/lib/python3.14/site-packages/pip/_vendor/distlib/t32.exe"
  "$RUNTIME_DIR/lib/python3.14/site-packages/pip/_vendor/distlib/t64.exe"
  "$RUNTIME_DIR/lib/python3.14/site-packages/pip/_vendor/distlib/t64-arm.exe"
  "$RUNTIME_DIR/lib/python3.14/site-packages/pip/_vendor/distlib/w32.exe"
  "$RUNTIME_DIR/lib/python3.14/site-packages/pip/_vendor/distlib/w64.exe"
  "$RUNTIME_DIR/lib/python3.14/site-packages/pip/_vendor/distlib/w64-arm.exe"
)
rm -f -- "${WINDOWS_BINARY_FILES[@]}"
REMAINING_WINDOWS_BINARY_FILES="$(
  find "$RUNTIME_DIR" -type f \
    \( -iname '*.exe' -o -iname '*.dll' -o -iname '*.pyd' -o -iname '*.msi' -o -iname '*.msix' \) \
    -print -quit
)"
[[ -z "$REMAINING_WINDOWS_BINARY_FILES" ]] || {
  echo "macOS runtime still contains Windows binaries: $REMAINING_WINDOWS_BINARY_FILES" >&2
  exit 1
}
PYTHONPATH="$REPO_ROOT/src" "$PYTHON" -m invoice_hub.release.runtime_manifest write \
  --runtime-dir "$RUNTIME_DIR" \
  --dependency-lock "$LOCK" \
  --platform macos \
  --architecture arm64 \
  --python-version "$PYTHON_VERSION" \
  --python-executable bin/python3 \
  --source "python-build-standalone ${PBS_RELEASE} ${PBS_ASSET} sha256:${PBS_SHA256}"

echo "$RUNTIME_DIR"
