#!/usr/bin/env python3
"""Run explicit, non-system-installing setup checks for the Tauri host."""

from __future__ import annotations

import argparse
import json
import shutil
import subprocess
import sys
from pathlib import Path

from tauri_doctor import DEFAULT_ROOT, evaluate


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Prepare checked-in Tauri dependencies without installing system tools.")
    parser.add_argument("--root", type=Path, default=DEFAULT_ROOT)
    parser.add_argument(
        "--install-js",
        action="store_true",
        help="explicitly install the already locked JavaScript dependencies only",
    )
    args = parser.parse_args(argv)
    root = args.root.resolve()
    sync_script = Path(__file__).with_name("tauri_version_sync.py")
    sync = subprocess.run(
        [sys.executable, str(sync_script), "--root", str(root), "--check"],
        check=False,
        capture_output=True,
        text=True,
    )
    if sync.returncode != 0:
        print(sync.stdout or sync.stderr, end="")
        return sync.returncode
    if args.install_js:
        pnpm = shutil.which("pnpm")
        if not pnpm:
            print(json.dumps({"ok": False, "error": "pnpm is required for --install-js"}, ensure_ascii=False))
            return 2
        install = subprocess.run(
            [pnpm, "install", "--frozen-lockfile", "--ignore-scripts"],
            cwd=root,
            check=False,
        )
        if install.returncode != 0:
            return install.returncode
    report = evaluate(root)
    print(json.dumps(report, ensure_ascii=False, sort_keys=True))
    return 0 if report["ok"] else 2


if __name__ == "__main__":
    raise SystemExit(main())
