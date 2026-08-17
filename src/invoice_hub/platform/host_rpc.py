"""Private Tauri-host client; its credentials are never exposed to Web content."""

from __future__ import annotations

import json
import os
import re
from collections.abc import MutableMapping
from enum import Enum
from typing import Any
from urllib import error, parse, request


HOST_RPC_URL_ENV = "INVOICE_HUB_HOST_RPC_URL"
HOST_RPC_TOKEN_ENV = "INVOICE_HUB_HOST_RPC_TOKEN"
HOST_RPC_EXPECTED_ORIGIN = "http://127.0.0.1:8766"
HOST_RPC_PATH = "/v1/host-rpc"
PICKER_DIALOG_TIMEOUT_SECONDS = 120
HOST_RPC_RESPONSE_MARGIN_SECONDS = 5
# Rust allows the native dialog to wait for 120 seconds; reserve time to return its response.
HOST_RPC_TIMEOUT_SECONDS = PICKER_DIALOG_TIMEOUT_SECONDS + HOST_RPC_RESPONSE_MARGIN_SECONDS
DESKTOP_HOST_SECRET_ENV = "INVOICE_HUB_DESKTOP_HOST_SECRET"
DESKTOP_HOST_MODE_ENV = "INVOICE_HUB_DESKTOP_HOST"
DESKTOP_UPDATER_ENABLED_ENV = "INVOICE_HUB_DESKTOP_UPDATER_ENABLED"
_TOKEN_PATTERN = re.compile(r"[0-9a-f]{64}")
_PRIVATE_HOST_ENV_NAMES = (
    HOST_RPC_URL_ENV,
    HOST_RPC_TOKEN_ENV,
    DESKTOP_HOST_SECRET_ENV,
    DESKTOP_HOST_MODE_ENV,
    DESKTOP_UPDATER_ENABLED_ENV,
)
_captured_configuration = ("", "")


class HostRpcError(RuntimeError):
    """A deliberately redacted failure from the private desktop-host channel."""


class HostRpcCommand(str, Enum):
    PICK_WATCH_DIRECTORY = "pick_watch_dir"
    PICK_OUTBOUND_INVOICE_DIRECTORY = "pick_outbound_invoice_dir"
    PICK_OCR_DIRECTORY = "pick_ocr_directory"
    PICK_OCR_FILE = "pick_ocr_file"
    UPDATE_CHECK = "update_check"
    UPDATE_INSTALL = "update_install"


def capture_environment() -> None:
    """Keep host-only picker credentials out of future child-process environments."""

    global _captured_configuration
    url = str(os.environ.pop(HOST_RPC_URL_ENV, "") or "").strip()
    token = str(os.environ.pop(HOST_RPC_TOKEN_ENV, "") or "").strip()
    _captured_configuration = (url, token)


def scrub_child_environment(environment: MutableMapping[str, str]) -> None:
    for name in _PRIVATE_HOST_ENV_NAMES:
        environment.pop(name, None)


def child_environment() -> dict[str, str]:
    environment = os.environ.copy()
    scrub_child_environment(environment)
    return environment


def _configured_values() -> tuple[str, str]:
    captured_url, captured_token = _captured_configuration
    if captured_url or captured_token:
        return captured_url, captured_token
    return (
        str(os.environ.get(HOST_RPC_URL_ENV) or "").strip(),
        str(os.environ.get(HOST_RPC_TOKEN_ENV) or "").strip(),
    )


def is_configured() -> bool:
    url, token = _configured_values()
    return bool(url or token)


def updater_enabled() -> bool:
    """Development bundles explicitly disable updater delegation."""

    return os.environ.get(DESKTOP_UPDATER_ENABLED_ENV, "1") == "1"


def _configuration() -> tuple[str, str] | None:
    url, token = _configured_values()
    if not url and not token:
        return None
    if not url or not token:
        raise HostRpcError("Tauri host native picker is unavailable")

    parsed = parse.urlsplit(url)
    try:
        port = parsed.port
    except ValueError as exc:
        raise HostRpcError("Tauri host native picker is unavailable") from None
    if (
        parsed.scheme != "http"
        or parsed.hostname != "127.0.0.1"
        or port is None
        or not (1 <= port <= 65535)
        or parsed.path != HOST_RPC_PATH
        or parsed.query
        or parsed.fragment
        or parsed.username is not None
        or parsed.password is not None
        or not _TOKEN_PATTERN.fullmatch(token)
    ):
        raise HostRpcError("Tauri host native picker is unavailable")
    return url, token


def _validated_response(raw: bytes) -> dict[str, Any]:
    try:
        payload = json.loads(raw.decode("utf-8"))
    except (UnicodeDecodeError, ValueError, TypeError) as exc:
        raise HostRpcError("Tauri host native picker is unavailable") from None
    if not isinstance(payload, dict) or payload.get("ok") is not True:
        raise HostRpcError("Tauri host native picker is unavailable")
    selected = payload.get("selected")
    path = payload.get("path")
    if not isinstance(selected, bool) or not isinstance(path, str):
        raise HostRpcError("Tauri host native picker is unavailable")
    if not selected and path:
        raise HostRpcError("Tauri host native picker is unavailable")
    return {"ok": True, "selected": selected, "path": path}


def _send(command: HostRpcCommand) -> bytes | None:
    """Submit one fixed enum command without accepting caller-controlled metadata."""

    configuration = _configuration()
    if configuration is None:
        return None
    url, token = configuration
    payload = json.dumps({"command": command.value}, separators=(",", ":")).encode("utf-8")
    rpc_request = request.Request(
        url,
        data=payload,
        method="POST",
        headers={
            "Authorization": f"Bearer {token}",
            "Content-Type": "application/json",
            "Origin": HOST_RPC_EXPECTED_ORIGIN,
        },
    )
    try:
        # Host RPC carries a bearer token and is only valid on the private loopback listener.
        direct_opener = request.build_opener(request.ProxyHandler({}))
        with direct_opener.open(rpc_request, timeout=HOST_RPC_TIMEOUT_SECONDS) as response:
            return response.read()
    except (HostRpcError, OSError, ValueError, error.URLError):
        # The token must not appear in a Python API error or diagnostic output.
        raise HostRpcError("Tauri host request is unavailable") from None


def pick(command: HostRpcCommand) -> dict[str, Any] | None:
    """Request one predefined native picker or return ``None`` outside Tauri."""

    try:
        raw = _send(command)
        if raw is None:
            return None
        return _validated_response(raw)
    except HostRpcError:
        raise HostRpcError("Tauri host native picker is unavailable") from None


def _validated_update_check_response(raw: bytes) -> str | None:
    try:
        payload = json.loads(raw.decode("utf-8"))
    except (UnicodeDecodeError, ValueError, TypeError):
        raise HostRpcError("Tauri host updater is unavailable") from None
    if not isinstance(payload, dict) or set(payload) != {"ok", "available", "version"}:
        raise HostRpcError("Tauri host updater is unavailable")
    available = payload.get("available")
    version = payload.get("version")
    if payload.get("ok") is not True or not isinstance(available, bool) or not isinstance(version, str):
        raise HostRpcError("Tauri host updater is unavailable")
    if available and version:
        return version
    if not available and not version:
        return None
    raise HostRpcError("Tauri host updater is unavailable")


def update_check() -> str | None:
    """Return the host-owned candidate version, never its URL or signature."""

    try:
        raw = _send(HostRpcCommand.UPDATE_CHECK)
        if raw is None:
            raise HostRpcError("Tauri host updater is unavailable")
        return _validated_update_check_response(raw)
    except HostRpcError:
        raise HostRpcError("Tauri host updater is unavailable") from None


def update_install() -> None:
    """Ask the host to install its single approved in-memory candidate."""

    try:
        raw = _send(HostRpcCommand.UPDATE_INSTALL)
        if raw is None:
            raise HostRpcError("Tauri host updater is unavailable")
        payload = json.loads(raw.decode("utf-8"))
    except (HostRpcError, UnicodeDecodeError, ValueError, TypeError):
        raise HostRpcError("Tauri host updater is unavailable") from None
    if payload != {"ok": True}:
        raise HostRpcError("Tauri host updater is unavailable")
