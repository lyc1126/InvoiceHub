#!/usr/bin/env python3
"""Read-only Tauri development prerequisite diagnostics."""

from __future__ import annotations

import argparse
import json
import os
import platform
import re
import shutil
import subprocess
import sys
import tomllib
from pathlib import Path
from typing import Any


DEFAULT_ROOT = Path(__file__).resolve().parents[2]
VERSION_PATTERN = re.compile(r"\d+\.\d+\.\d+(?:[-+][0-9A-Za-z.-]+)?")
MSVC_COMPONENT = "Microsoft.VisualStudio.Component.VC.Tools.x86.x64"


def _check(status: str, *, expected: str = "", actual: str = "", detail: str = "") -> dict[str, str]:
    return {"status": status, "expected": expected, "actual": actual, "detail": detail}


def _find_executable(command: str) -> str | None:
    if command == "vswhere":
        program_files_x86 = os.environ.get("ProgramFiles(x86)", "").strip()
        if program_files_x86:
            bundled_vswhere = (
                Path(program_files_x86)
                / "Microsoft Visual Studio"
                / "Installer"
                / "vswhere.exe"
            )
            if bundled_vswhere.is_file():
                return str(bundled_vswhere)
    return shutil.which(command)


def _probe(
    command: str,
    args: list[str],
    *,
    cwd: Path | None = None,
) -> tuple[str, str]:
    executable = _find_executable(command)
    if not executable:
        return "missing", ""
    environment: dict[str, str] | None = None
    if command in {"rustc", "cargo"}:
        # Rustup otherwise installs the pinned toolchain during a diagnostic.
        environment = os.environ.copy()
        environment["RUSTUP_AUTO_INSTALL"] = "0"
    elif command == "pnpm":
        # Corepack otherwise downloads pnpm while doctor is only diagnosing.
        environment = os.environ.copy()
        environment["COREPACK_ENABLE_NETWORK"] = "0"
    try:
        completed = subprocess.run(
            [executable, *args],
            check=False,
            capture_output=True,
            text=True,
            timeout=5,
            env=environment,
            cwd=cwd,
        )
    except (OSError, subprocess.TimeoutExpired) as exc:
        return "error", str(exc)
    if completed.returncode != 0:
        return "error", (completed.stderr or completed.stdout).strip()
    return "ok", (completed.stdout or completed.stderr).strip()


def _version(text: str) -> str:
    match = VERSION_PATTERN.search(text)
    return match.group(0) if match else ""


def _load_json(path: Path) -> dict[str, Any]:
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError):
        return {}
    return payload if isinstance(payload, dict) else {}


def _expected_tools(root: Path) -> tuple[str, str, str]:
    package = _load_json(root / "package.json")
    node = str((package.get("engines") or {}).get("node") or "").strip()
    manager = str(package.get("packageManager") or "").strip()
    pnpm = manager.removeprefix("pnpm@") if manager.startswith("pnpm@") else ""
    try:
        toolchain = tomllib.loads((root / "rust-toolchain.toml").read_text(encoding="utf-8"))
        rust = str((toolchain.get("toolchain") or {}).get("channel") or "").strip()
    except (OSError, UnicodeError, tomllib.TOMLDecodeError):
        rust = ""
    return node, pnpm, rust


def _version_check(command: str, expected: str, *, root: Path) -> dict[str, str]:
    status, output = _probe(command, ["--version"], cwd=root)
    if status != "ok":
        return _check(status, expected=expected, detail=output)
    actual = _version(output).lstrip("v")
    if not actual:
        return _check("error", expected=expected, detail=f"unparseable version output: {output}")
    if not expected:
        return _check("ok", actual=actual)
    return _check("ok" if actual == expected else "mismatch", expected=expected, actual=actual)


def _windows_sdk_check(root: Path) -> dict[str, str]:
    expected = "MSVC C++ tools and a Windows 10/11 SDK"
    program_files_x86 = os.environ.get("ProgramFiles(x86)", "").strip()
    if not program_files_x86:
        return _check("missing", expected=expected, detail="ProgramFiles(x86) is unavailable")
    status, output = _probe(
        "vswhere",
        [
            "-latest",
            "-products",
            "*",
            "-requires",
            MSVC_COMPONENT,
            "-property",
            "installationPath",
        ],
        cwd=root,
    )
    if status != "ok":
        return _check(status, expected=expected, detail=output)
    installation_path = output.strip()
    if not installation_path:
        return _check("missing", expected=expected, detail="vswhere found no MSVC C++ tools instance")

    include_root = Path(program_files_x86) / "Windows Kits" / "10" / "Include"
    try:
        has_windows_sdk = include_root.is_dir() and any(
            child.is_dir() for child in include_root.iterdir()
        )
    except OSError:
        has_windows_sdk = False
    if not has_windows_sdk:
        return _check("missing", expected=expected, detail=f"Windows SDK include directory missing: {include_root}")
    return _check("ok", actual=installation_path)


def _version_sync_check(root: Path) -> dict[str, str]:
    script = Path(__file__).with_name("tauri_version_sync.py")
    completed = subprocess.run(
        [sys.executable, str(script), "--root", str(root), "--check"],
        check=False,
        capture_output=True,
        text=True,
        timeout=10,
        cwd=root,
    )
    if completed.returncode == 0:
        return _check("ok")
    return _check("error", detail=(completed.stdout or completed.stderr).strip())


def evaluate(root: Path) -> dict[str, Any]:
    root = Path(root).resolve()
    node, pnpm, rust = _expected_tools(root)
    cargo = rust
    machine = platform.machine().strip().casefold().replace("-", "_")
    system = sys.platform
    checks: dict[str, dict[str, str]] = {
        "version_sync": _version_sync_check(root),
        "node": _version_check("node", node, root=root),
        "pnpm": _version_check("pnpm", pnpm, root=root),
        "rustc": _version_check("rustc", rust, root=root),
        "cargo": _version_check("cargo", cargo, root=root),
        "pnpm_lock": _check("ok" if (root / "pnpm-lock.yaml").is_file() else "missing"),
        "cargo_lock": _check("ok" if (root / "src-tauri" / "Cargo.lock").is_file() else "missing"),
    }
    cargo_manifest = root / "src-tauri" / "Cargo.toml"
    tauri_config = root / "src-tauri" / "tauri.conf.json"
    try:
        cargo_payload = tomllib.loads(cargo_manifest.read_text(encoding="utf-8"))
        dependencies = cargo_payload.get("dependencies") or {}
        build_dependencies = cargo_payload.get("build-dependencies") or {}
        has_tauri = "tauri" in dependencies and "tauri-build" in build_dependencies
        checks["cargo_manifest"] = _check("ok" if has_tauri else "error")
    except (OSError, UnicodeError, tomllib.TOMLDecodeError) as exc:
        checks["cargo_manifest"] = _check("error", detail=str(exc))
    config = _load_json(tauri_config)
    expected_origin = "http://127.0.0.1:8766"
    checks["fixed_origin"] = _check(
        "ok" if (config.get("build") or {}).get("devUrl") == expected_origin else "error",
        expected=expected_origin,
        actual=str((config.get("build") or {}).get("devUrl") or ""),
    )

    if system == "darwin":
        status, output = _probe("xcode-select", ["-p"], cwd=root)
        checks["platform_sdk"] = _check(status, detail=output)
        target_status = "ok" if machine in {"arm64", "aarch64"} else "unsupported"
        checks["platform_target"] = _check(target_status, expected="arm64", actual=machine)
    elif system.startswith("win"):
        checks["platform_sdk"] = _windows_sdk_check(root)
        target_status = "ok" if machine in {"amd64", "x86_64"} else "unsupported"
        checks["platform_target"] = _check(target_status, expected="x86_64", actual=machine)
    else:
        checks["platform_sdk"] = _check("unsupported", actual=system)
        checks["platform_target"] = _check("unsupported", actual=machine)

    ready = all(item["status"] == "ok" for item in checks.values())
    return {"ok": ready, "platform": system, "architecture": machine, "checks": checks}


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Diagnose Tauri prerequisites without installing anything.")
    parser.add_argument("--root", type=Path, default=DEFAULT_ROOT)
    parser.add_argument("--json", action="store_true")
    parser.add_argument("--require-ready", action="store_true")
    args = parser.parse_args(argv)
    report = evaluate(args.root)
    if args.json:
        print(json.dumps(report, ensure_ascii=False, sort_keys=True))
    else:
        for name, item in report["checks"].items():
            print(f"{name}: {item['status']}")
        print(f"ready: {str(report['ok']).lower()}")
    return 0 if report["ok"] or not args.require_ready else 2


if __name__ == "__main__":
    raise SystemExit(main())
