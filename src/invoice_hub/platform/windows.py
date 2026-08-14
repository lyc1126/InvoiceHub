from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path


IMAGE_EXTENSIONS = {".png", ".jpg", ".jpeg", ".bmp", ".tif", ".tiff", ".webp"}
OCR_EXTENSIONS = {".pdf", ".ofd", *IMAGE_EXTENSIONS}


def open_local_path(path: Path) -> None:
    resolved = Path(path).resolve()
    if not resolved.exists():
        raise FileNotFoundError(str(resolved))
    if os.environ.get("INVOICE_HUB_DISABLE_OPEN") == "1":
        return
    if os.name == "nt":
        os.startfile(str(resolved))  # type: ignore[attr-defined]
        return
    opener = "open" if sys.platform == "darwin" else "xdg-open"
    subprocess.Popen([opener, str(resolved)], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)


def run_native_dialog(command_name: str, initial_path: Path, title: str) -> dict:
    mock_path = os.environ.get("INVOICE_HUB_DIALOG_MOCK_PATH")
    if mock_path is not None:
        return {"ok": True, "selected": bool(mock_path), "path": mock_path}

    command = [
        sys.executable,
        "-m",
        "invoice_hub.platform.native_dialogs",
        command_name,
        "--title",
        title,
    ]
    if str(initial_path):
        command.extend(["--initial-dir", str(initial_path)])
    env = os.environ.copy()
    env["PYTHONUTF8"] = "1"
    env["PYTHONIOENCODING"] = "utf-8"
    result = subprocess.run(
        command,
        cwd=str(Path(__file__).resolve().parents[3]),
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        env=env,
        creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
        check=False,
    )
    if result.returncode != 0:
        stderr_tail = "\n".join((result.stderr or "").splitlines()[-20:])
        raise RuntimeError(f"native picker failed: {stderr_tail or 'unknown error'}")
    payload = json.loads(result.stdout or "{}")
    if not isinstance(payload, dict) or not payload.get("ok", False):
        raise RuntimeError("native picker returned invalid payload")
    return payload


def pick_directory(initial_dir: Path, title: str = "选择发票监控文件夹") -> dict:
    return run_native_dialog("pick-directory", initial_dir, title)


def pick_file(initial_dir: Path, title: str = "选择 OCR 识别文件") -> dict:
    return run_native_dialog("pick-file", initial_dir, title)
