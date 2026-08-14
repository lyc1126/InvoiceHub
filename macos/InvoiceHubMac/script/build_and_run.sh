#!/usr/bin/env bash
set -euo pipefail

MODE="${1:-run}"
BUILD_ONLY="false"
case "$MODE" in
  build|build-only|--build-only)
    BUILD_ONLY="true"
    ;;
esac
APP_NAME="InvoiceHubMac"
BUNDLE_ID="com.invoicehub.mac"
MIN_SYSTEM_VERSION="13.0"

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
REPO_ROOT="$(cd "$ROOT_DIR/../.." && pwd)"
DIST_DIR="$ROOT_DIR/dist"
APP_BUNDLE="$DIST_DIR/$APP_NAME.app"
APP_CONTENTS="$APP_BUNDLE/Contents"
APP_MACOS="$APP_CONTENTS/MacOS"
APP_RESOURCES="$APP_CONTENTS/Resources"
APP_BINARY="$APP_MACOS/$APP_NAME"
INFO_PLIST="$APP_CONTENTS/Info.plist"
BACKEND_VENV="$ROOT_DIR/.backend-venv"
BACKEND_PYTHON="$BACKEND_VENV/bin/python"
BACKEND_IMPORT_CHECK="import fastapi, uvicorn, pydantic, openpyxl, fitz, PIL"
APP_SUPPORT_ROOT="$HOME/Library/Application Support/InvoiceHub"
CONFIG_PATH="$APP_SUPPORT_ROOT/config/app.local.json"
RUNTIME_DIR="$APP_SUPPORT_ROOT/runtime"
SERVER_PID_FILE="$RUNTIME_DIR/server.pid"
PORT="8766"

wait_for_process_exit() {
  local name="$1"
  local attempts="${2:-50}"
  local delay="${3:-0.1}"
  for _ in $(seq 1 "$attempts"); do
    if ! pgrep -x "$name" >/dev/null 2>&1; then
      return 0
    fi
    sleep "$delay"
  done
  return 1
}

read_server_pid_file() {
  local value=""
  [[ -f "$SERVER_PID_FILE" ]] || return 1
  value="$(< "$SERVER_PID_FILE")" || return 1
  value="${value%$'\r'}"
  [[ "$value" =~ ^[0-9]+$ ]] || return 1
  printf '%s\n' "$value"
}

wait_for_pid_exit() {
  local pid="$1"
  local attempts="${2:-50}"
  local delay="${3:-0.1}"
  if [[ -z "$pid" ]]; then
    return 0
  fi
  for _ in $(seq 1 "$attempts"); do
    if ! kill -0 "$pid" >/dev/null 2>&1; then
      return 0
    fi
    sleep "$delay"
  done
  return 1
}

server_command() {
  local pid="$1"
  ps -p "$pid" -ww -o command= 2>/dev/null || true
}

server_argv_matches_expected_identity() {
  local pid="$1"
  local expected_config="$2"
  [[ "$pid" =~ ^[0-9]+$ ]] || return 1
  [[ -x /usr/bin/python3 ]] || return 1
  /usr/bin/python3 -c '
import ctypes
import os
import struct
import sys

CTL_KERN = 1
KERN_ARGMAX = 8
KERN_PROCARGS2 = 49


def read_process_argv(pid):
    if pid <= 0 or pid > 2_147_483_647:
        return None
    libc = ctypes.CDLL(None, use_errno=True)
    libc.sysctl.argtypes = [
        ctypes.POINTER(ctypes.c_int),
        ctypes.c_uint,
        ctypes.c_void_p,
        ctypes.POINTER(ctypes.c_size_t),
        ctypes.c_void_p,
        ctypes.c_size_t,
    ]
    libc.sysctl.restype = ctypes.c_int

    argmax = ctypes.c_int()
    size = ctypes.c_size_t(ctypes.sizeof(argmax))
    mib = (ctypes.c_int * 2)(CTL_KERN, KERN_ARGMAX)
    if libc.sysctl(mib, 2, ctypes.byref(argmax), ctypes.byref(size), None, 0) != 0 or argmax.value <= 0:
        return None

    buffer = ctypes.create_string_buffer(argmax.value)
    size = ctypes.c_size_t(argmax.value)
    mib = (ctypes.c_int * 3)(CTL_KERN, KERN_PROCARGS2, pid)
    if libc.sysctl(mib, 3, buffer, ctypes.byref(size), None, 0) != 0:
        return None
    raw = buffer.raw[:size.value]
    if len(raw) < ctypes.sizeof(ctypes.c_int):
        return None

    argc = struct.unpack_from("i", raw)[0]
    offset = ctypes.sizeof(ctypes.c_int)
    executable_end = raw.find(b"\0", offset)
    if argc <= 0 or executable_end < 0:
        return None
    offset = executable_end + 1
    while offset < len(raw) and raw[offset] == 0:
        offset += 1

    arguments = []
    for _ in range(argc):
        argument_end = raw.find(b"\0", offset)
        if argument_end < 0:
            return None
        arguments.append(os.fsdecode(raw[offset:argument_end]))
        offset = argument_end + 1
    return arguments


def is_config_option_variant(argument):
    option, separator, _ = argument.partition("=")
    if option == "--config":
        return bool(separator)
    return len(option) > 2 and "--config".startswith(option)


def matches_expected_identity(arguments, expected_config):
    if arguments[1:3] != ["-m", "invoice_hub.api.main"]:
        return False
    remaining = arguments[3:]
    if any(is_config_option_variant(argument) for argument in remaining):
        return False
    config_indexes = [
        index
        for index, argument in enumerate(remaining, start=3)
        if argument == "--config"
    ]
    if len(config_indexes) != 1:
        return False
    config_index = config_indexes[0]
    return config_index + 1 < len(arguments) and arguments[config_index + 1] == expected_config


try:
    argv = read_process_argv(int(sys.argv[1]))
except (OSError, OverflowError, ValueError, struct.error):
    argv = None
if argv is None:
    raise SystemExit(1)
raise SystemExit(
    0
    if matches_expected_identity(argv, sys.argv[2])
    else 1
)
' "$pid" "$expected_config"
}

is_current_invoicehub_server() {
  local pid="$1"
  server_argv_matches_expected_identity "$pid" "$CONFIG_PATH"
}

stop_verified_server() {
  local pid="$1"
  if [[ -z "$pid" ]] || ! kill -0 "$pid" >/dev/null 2>&1; then
    return 0
  fi
  if ! is_current_invoicehub_server "$pid"; then
    return 1
  fi
  echo "Stopping verified InvoiceHub backend pid=$pid config=$CONFIG_PATH"
  kill -TERM "$pid"
  if wait_for_pid_exit "$pid" 80 0.1; then
    return 0
  fi
  if ! kill -0 "$pid" >/dev/null 2>&1; then
    return 0
  fi
  if ! is_current_invoicehub_server "$pid"; then
    echo "Backend pid=$pid changed identity after TERM; refusing to force stop it." >&2
    return 1
  fi
  echo "Verified backend pid=$pid did not exit after TERM; forcing it to stop." >&2
  kill -KILL "$pid"
  wait_for_pid_exit "$pid" 50 0.1
}

listener_pids() {
  /usr/sbin/lsof -nP -iTCP:"$PORT" -sTCP:LISTEN -t 2>/dev/null | sort -u || true
}

if [[ "$BUILD_ONLY" != "true" ]]; then
  if pgrep -x "$APP_NAME" >/dev/null 2>&1; then
    pkill -x "$APP_NAME" >/dev/null 2>&1 || true
    wait_for_process_exit "$APP_NAME" 80 0.1
  fi

  OLD_SERVER_PID=""
  OLD_SERVER_PID="$(read_server_pid_file || true)"
  if [[ -n "$OLD_SERVER_PID" ]] && kill -0 "$OLD_SERVER_PID" >/dev/null 2>&1 && is_current_invoicehub_server "$OLD_SERVER_PID"; then
    stop_verified_server "$OLD_SERVER_PID"
  fi

  while IFS= read -r listener_pid; do
    [[ -n "$listener_pid" ]] || continue
    if ! stop_verified_server "$listener_pid"; then
      echo "Port $PORT is occupied by an unverified process; refusing to kill it or switch ports." >&2
      echo "pid=$listener_pid command=$(server_command "$listener_pid")" >&2
      echo "Expected python argv to begin with -m invoice_hub.api.main and contain one exact --config $CONFIG_PATH" >&2
      exit 1
    fi
  done < <(listener_pids)

  if [[ -n "$(listener_pids)" ]]; then
    echo "Port $PORT is still occupied after stopping the verified old backend." >&2
    exit 1
  fi
  CURRENT_SERVER_PID="$(read_server_pid_file || true)"
  if [[ -n "$OLD_SERVER_PID" ]] && [[ "$CURRENT_SERVER_PID" == "$OLD_SERVER_PID" ]] && ! kill -0 "$OLD_SERVER_PID" >/dev/null 2>&1; then
    rm -f "$SERVER_PID_FILE"
  fi
fi

ensure_backend_python() {
  if [[ ! -x "$BACKEND_PYTHON" ]]; then
    if ! command -v python3 >/dev/null 2>&1; then
      echo "python3 not found. Install Python 3.11+ before running the macOS shell." >&2
      exit 1
    fi
    python3 -m venv "$BACKEND_VENV"
  fi

  if ! "$BACKEND_PYTHON" -c "$BACKEND_IMPORT_CHECK" >/dev/null 2>&1; then
    echo "Preparing InvoiceHub backend Python environment at $BACKEND_VENV"
    "$BACKEND_PYTHON" -m pip install -e "$REPO_ROOT"
  fi
}

ensure_backend_python

swift build --package-path "$ROOT_DIR"
BUILD_BINARY="$(swift build --package-path "$ROOT_DIR" --show-bin-path)/$APP_NAME"

rm -rf "$APP_BUNDLE"
mkdir -p "$APP_MACOS" "$APP_RESOURCES/invoice-hub-core"
cp "$BUILD_BINARY" "$APP_BINARY"
chmod +x "$APP_BINARY"

ditto "$REPO_ROOT/src" "$APP_RESOURCES/invoice-hub-core/src"
ditto "$REPO_ROOT/web" "$APP_RESOURCES/invoice-hub-core/web"
if [ -d "$REPO_ROOT/docs/jierui" ]; then
  ditto "$REPO_ROOT/docs/jierui" "$APP_RESOURCES/invoice-hub-core/docs/jierui"
fi
mkdir -p "$APP_RESOURCES/invoice-hub-core/scripts/tools"
cp "$REPO_ROOT/scripts/tools/jierui_voucher_import.py" "$APP_RESOURCES/invoice-hub-core/scripts/tools/jierui_voucher_import.py"
cp "$REPO_ROOT/pyproject.toml" "$APP_RESOURCES/invoice-hub-core/pyproject.toml"
cp "$REPO_ROOT/LICENSE" "$APP_RESOURCES/invoice-hub-core/LICENSE"
cp "$REPO_ROOT/THIRD_PARTY_NOTICES.md" "$APP_RESOURCES/invoice-hub-core/THIRD_PARTY_NOTICES.md"
mkdir -p "$APP_RESOURCES/invoice-hub-core/requirements"
cp "$REPO_ROOT/requirements/macos-arm64-py314.lock" "$APP_RESOURCES/invoice-hub-core/requirements/macos-arm64-py314.lock"
find "$APP_RESOURCES/invoice-hub-core" -name '__pycache__' -type d -prune -exec rm -rf {} +
find "$APP_RESOURCES/invoice-hub-core" -type f \( -name '*.pyc' -o -name '.DS_Store' \) -delete
printf '%s\n' "$BACKEND_PYTHON" > "$APP_RESOURCES/dev-python-path.txt"

SOURCE_COMMIT="$(git -C "$REPO_ROOT" rev-parse HEAD)"
if [[ -n "$(git -C "$REPO_ROOT" status --porcelain --untracked-files=all -- src web scripts/tools/jierui_voucher_import.py docs/jierui pyproject.toml)" ]]; then
  SOURCE_COMMIT="${SOURCE_COMMIT}+dirty"
fi
BUILD_TIME="$(date -u +%Y-%m-%dT%H:%M:%SZ)"
PYTHONPATH="$REPO_ROOT/src${PYTHONPATH:+:$PYTHONPATH}" "$BACKEND_PYTHON" -m invoice_hub.release.build_manifest \
  --root "$APP_RESOURCES/invoice-hub-core" \
  --output "$APP_RESOURCES/invoice-hub-core/invoice-hub-build.json" \
  --source-commit "$SOURCE_COMMIT" \
  --built-at "$BUILD_TIME"
CORE_BUILD_ID="$("$BACKEND_PYTHON" -c 'import json,sys; print(json.load(open(sys.argv[1], encoding="utf-8"))["build_id"])' "$APP_RESOURCES/invoice-hub-core/invoice-hub-build.json")"
BACKEND_PYTHON_VERSION="$("$BACKEND_PYTHON" -c 'import platform; print(platform.python_version())')"
PYTHONPATH="$REPO_ROOT/src${PYTHONPATH:+:$PYTHONPATH}" "$BACKEND_PYTHON" -m invoice_hub.release.package_manifest \
  --output "$APP_RESOURCES/invoice-hub-core/invoice-hub-package.json" \
  --package-id "com.invoicehub.macos.arm64.dmg" \
  --platform macos \
  --architecture arm64 \
  --package-type dmg \
  --python-version "$BACKEND_PYTHON_VERSION" \
  --dependency-lock "$REPO_ROOT/requirements/macos-arm64-py314.lock" \
  --core-build-id "$CORE_BUILD_ID" \
  --source-commit "$(git -C "$REPO_ROOT" rev-parse HEAD)"

cat >"$INFO_PLIST" <<PLIST
<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0">
<dict>
  <key>CFBundleExecutable</key>
  <string>$APP_NAME</string>
  <key>CFBundleIdentifier</key>
  <string>$BUNDLE_ID</string>
  <key>CFBundleName</key>
  <string>InvoiceHub</string>
  <key>CFBundleShortVersionString</key>
  <string>0.3.0-alpha.1</string>
  <key>CFBundleVersion</key>
  <string>1</string>
  <key>CFBundlePackageType</key>
  <string>APPL</string>
  <key>LSMinimumSystemVersion</key>
  <string>$MIN_SYSTEM_VERSION</string>
  <key>NSPrincipalClass</key>
  <string>NSApplication</string>
  <key>NSHighResolutionCapable</key>
  <true/>
  <key>InvoiceHubReleaseMode</key>
  <false/>
  <key>SUEnableAutomaticChecks</key>
  <false/>
  <key>SUFeedURL</key>
  <string>https://lyc1126.github.io/InvoiceHub/updates/alpha/appcast.xml</string>
  <key>SUPublicEDKey</key>
  <string>${INVOICE_HUB_SPARKLE_PUBLIC_KEY:-}</string>
</dict>
</plist>
PLIST

open_app() {
  /usr/bin/open -n -F "$APP_BUNDLE"
}

verify_app() {
  local health_url="http://127.0.0.1:$PORT/api/v1/health"
  local health_file
  local openapi_file
  health_file="$(mktemp -t invoicehub-health.XXXXXX)"
  openapi_file="$(mktemp -t invoicehub-openapi.XXXXXX)"
  trap 'rm -f "$health_file" "$openapi_file"' RETURN

  open_app
  for _ in $(seq 1 150); do
    if pgrep -x "$APP_NAME" >/dev/null 2>&1 && /usr/bin/curl --connect-timeout 1 --max-time 1 -fsS "$health_url" -o "$health_file" 2>/dev/null; then
      break
    fi
    sleep 0.2
  done
  pgrep -x "$APP_NAME" >/dev/null
  /usr/bin/curl --connect-timeout 2 --max-time 5 -fsS "$health_url" -o "$health_file"
  /usr/bin/curl --connect-timeout 2 --max-time 5 -fsS "http://127.0.0.1:$PORT/" -o /dev/null
  /usr/bin/curl --connect-timeout 2 --max-time 5 -fsS "http://127.0.0.1:$PORT/costs" -o /dev/null
  /usr/bin/curl --connect-timeout 2 --max-time 5 -fsS "http://127.0.0.1:$PORT/documents" -o /dev/null
  /usr/bin/curl --connect-timeout 2 --max-time 5 -fsS "http://127.0.0.1:$PORT/bookkeeping" -o /dev/null
  /usr/bin/curl --connect-timeout 2 --max-time 5 -fsS "http://127.0.0.1:$PORT/settings" -o /dev/null
  /usr/bin/curl --connect-timeout 2 --max-time 5 -fsS "http://127.0.0.1:$PORT/openapi.json" -o "$openapi_file"

  "$BACKEND_PYTHON" -c '
import json, pathlib, sys
manifest = json.loads(pathlib.Path(sys.argv[1]).read_text(encoding="utf-8"))
package = json.loads(pathlib.Path(sys.argv[2]).read_text(encoding="utf-8"))
health = json.loads(pathlib.Path(sys.argv[3]).read_text(encoding="utf-8"))
openapi = json.loads(pathlib.Path(sys.argv[4]).read_text(encoding="utf-8"))
if not isinstance(manifest, dict):
    raise SystemExit("verify invalid build manifest object")
if not isinstance(health, dict):
    raise SystemExit("verify invalid health object")
if not isinstance(package, dict):
    raise SystemExit("verify invalid package manifest object")
if health.get("ok") is not True:
    raise SystemExit("verify health.ok is not true")
if health.get("build_manifest_present") is not True:
    raise SystemExit("verify build_manifest_present is not true")
if health.get("build_manifest_valid") is not True:
    raise SystemExit("verify build_manifest_valid is not true")
if health.get("package_manifest_present") is not True or health.get("package_manifest_valid") is not True:
    raise SystemExit("verify package manifest is not valid")
required_api_contract_version = "2026-08-02-release-update-v1"
manifest_api_contract = manifest.get("api_contract_version")
if manifest_api_contract != required_api_contract_version:
    raise SystemExit(
        "verify unsupported manifest API contract: "
        f"required={required_api_contract_version!r} actual={manifest_api_contract!r}"
    )
health_api_contract = health.get("api_contract_version")
if health_api_contract != required_api_contract_version:
    raise SystemExit(
        "verify unsupported backend API contract: "
        f"required={required_api_contract_version!r} actual={health_api_contract!r}"
    )
expected = {
    "build_id": manifest["build_id"],
    "api_contract_version": manifest["api_contract_version"],
    "bookkeeping_protocol_version": manifest["bookkeeping_protocol_version"],
    "config_path": str(pathlib.Path(sys.argv[5]).resolve()),
    "runtime_dir": str(pathlib.Path(sys.argv[6]).resolve()),
    "product_version": package["product_version"],
    "package_id": package["package_id"],
    "platform": package["platform"],
    "architecture": package["architecture"],
    "package_type": package["package_type"],
}
if package.get("core_build_id") != manifest.get("build_id"):
    raise SystemExit("verify package core_build_id mismatch")
actual_bookkeeping_protocol = manifest.get("bookkeeping_protocol_version")
if actual_bookkeeping_protocol != "w9-ledger-review-v1":
    raise SystemExit(
        "verify unsupported manifest bookkeeping protocol: "
        f"{actual_bookkeeping_protocol!r}"
    )
for key, value in expected.items():
    actual = health.get(key)
    if actual != value:
        raise SystemExit(f"verify mismatch {key}: expected={value!r} actual={actual!r}")
required = {
    "bookkeeping.review",
    "bookkeeping.executability.v2",
    "bookkeeping.import-batch.v1",
    "bookkeeping.import-finalize.v1",
    "bookkeeping.jierui.facts.v2",
    "bookkeeping.jierui.runner.dry-run.v2",
    "bookkeeping.state-cas.v1",
    "bookkeeping.w9-ledger-review.v1",
    "bookkeeping.mapping-resolution.v1",
    "bookkeeping.targeted-recompute.v1",
    "bookkeeping.migration-cas.v2",
    "costs.internal-scroll",
    "documents",
    "documents.validate-outbound-dir",
    "settings.center.v1",
    "settings.preferences.v1",
    "diagnostics.support-package.v1",
    "invoices.batch-print.v1",
    "invoices.classification.v1",
    "invoices.file-preview.v1",
    "invoices.rename-safe.v1",
    "invoices.selection-summary.v1",
    "macos.strict-build-handshake",
    "monitor.ready-handshake.v1",
    "release.package-identity.v1",
    "server.shutdown-choice.v1",
    "settings.startup-surface.v1",
    "skins.zip-portable",
    "updates.metadata-check.v1",
}


def normalized_capabilities(label, values):
    if not isinstance(values, (list, tuple, set, frozenset)) or not values:
        raise SystemExit(f"verify invalid {label} capabilities collection")
    if any(
        not isinstance(value, str) or not value or value != value.strip()
        for value in values
    ):
        raise SystemExit(f"verify invalid {label} capability value")
    return frozenset(values)


manifest_capabilities = normalized_capabilities("manifest", manifest.get("capabilities"))
health_capabilities = normalized_capabilities("health", health.get("capabilities"))
required_capabilities = normalized_capabilities("required", required)
if not manifest_capabilities == health_capabilities == required_capabilities:
    raise SystemExit(
        "verify capability set mismatch: "
        f"manifest={sorted(manifest_capabilities)!r} "
        f"health={sorted(health_capabilities)!r} "
        f"required={sorted(required_capabilities)!r}"
    )
if not isinstance(health.get("pid"), int) or health["pid"] <= 0:
    raise SystemExit("verify missing backend pid")
required_routes = {
    "/api/v1/documents/state": "get",
    "/api/v1/bookkeeping/state": "get",
    "/api/v1/settings": "get",
    "/api/v1/preferences": "get",
    "/api/v1/about": "get",
    "/api/v1/update/check": "post",
    "/api/v1/diagnostics/config-health": "get",
    "/api/v1/skins": "get",
    "/api/v1/invoices/selection-summary": "post",
    "/api/v1/invoices/preview-jobs": "post",
    "/api/v1/invoices/preview-jobs/{job_id}/files/{file_number}/pages/{page_number}": "get",
    "/api/v1/invoices/preview-jobs/{job_id}/files/{file_number}/text": "get",
    "/api/v1/invoices/preview-jobs/{job_id}/keep-alive": "post",
    "/api/v1/invoices/preview-jobs/{job_id}/files/{file_number}/open-file": "post",
    "/api/v1/invoices/preview-jobs/{job_id}/files/{file_number}/open-location": "post",
    "/api/v1/invoices/print-jobs": "post",
    "/api/v1/invoices/print-jobs/{job_id}/pages/{page_number}": "get",
    "/invoices/print/{job_id}": "get",
    "/api/v1/server/shutdown": "post",
}
registered_routes = openapi.get("paths")
if not isinstance(registered_routes, dict):
    raise SystemExit("verify invalid OpenAPI paths")
missing_operations = [
    f"{method.upper()} {path}"
    for path, method in required_routes.items()
    if not isinstance(registered_routes.get(path), dict)
    or not isinstance(registered_routes[path].get(method), dict)
]
if missing_operations:
    raise SystemExit(f"verify missing API operations: {sorted(missing_operations)}")
print("Verified build_id={} pid={} contract={} bookkeeping_protocol={}".format(
    health["build_id"], health["pid"], health["api_contract_version"], health["bookkeeping_protocol_version"]
))
' "$APP_RESOURCES/invoice-hub-core/invoice-hub-build.json" "$APP_RESOURCES/invoice-hub-core/invoice-hub-package.json" "$health_file" "$openapi_file" "$CONFIG_PATH" "$RUNTIME_DIR"
}

case "$MODE" in
  build|build-only|--build-only)
    echo "$APP_BUNDLE"
    ;;
  run)
    open_app
    ;;
  --debug|debug)
    lldb -- "$APP_BINARY"
    ;;
  --logs|logs)
    open_app
    /usr/bin/log stream --info --style compact --predicate "process == \"$APP_NAME\""
    ;;
  --telemetry|telemetry)
    open_app
    /usr/bin/log stream --info --style compact --predicate "subsystem == \"$BUNDLE_ID\""
    ;;
  --verify|verify)
    verify_app
    ;;
  *)
    echo "usage: $0 [build-only|run|--debug|--logs|--telemetry|--verify]" >&2
    exit 2
    ;;
esac
