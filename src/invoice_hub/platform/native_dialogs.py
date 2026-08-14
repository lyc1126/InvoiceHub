from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path


OCR_FILE_TYPES = [
    ("OCR 支持文件", "*.pdf *.ofd *.png *.jpg *.jpeg *.bmp *.tif *.tiff *.webp"),
    ("PDF 文件", "*.pdf"),
    ("OFD 文件", "*.ofd"),
    ("图片文件", "*.png *.jpg *.jpeg *.bmp *.tif *.tiff *.webp"),
    ("所有文件", "*.*"),
]


def _tk_root():
    from tkinter import Tk

    root = Tk()
    root.withdraw()
    try:
        root.attributes("-topmost", True)
    except Exception:
        pass
    root.update_idletasks()
    return root


def pick_directory(initial_dir: str = "", title: str = "选择发票监控文件夹") -> str:
    from tkinter import filedialog

    root = _tk_root()
    try:
        options: dict[str, object] = {"title": title, "mustexist": False, "parent": root}
        initial_path = Path(str(initial_dir or "").strip()).expanduser()
        if str(initial_path) and initial_path.exists():
            options["initialdir"] = str(initial_path if initial_path.is_dir() else initial_path.parent)
        elif str(initial_path) and initial_path.parent.exists():
            options["initialdir"] = str(initial_path.parent)
        return str(filedialog.askdirectory(**options) or "").strip()
    finally:
        root.destroy()


def pick_file(initial_dir: str = "", title: str = "选择 OCR 识别文件") -> str:
    from tkinter import filedialog

    root = _tk_root()
    try:
        options: dict[str, object] = {"title": title, "parent": root, "filetypes": OCR_FILE_TYPES}
        initial_path = Path(str(initial_dir or "").strip()).expanduser()
        if str(initial_path) and initial_path.exists():
            if initial_path.is_file():
                options["initialdir"] = str(initial_path.parent)
                options["initialfile"] = initial_path.name
            else:
                options["initialdir"] = str(initial_path)
        elif str(initial_path) and initial_path.parent.exists():
            options["initialdir"] = str(initial_path.parent)
        return str(filedialog.askopenfilename(**options) or "").strip()
    finally:
        root.destroy()


def main() -> int:
    try:
        sys.stdout.reconfigure(encoding="utf-8")
        sys.stderr.reconfigure(encoding="utf-8")
    except Exception:
        pass

    parser = argparse.ArgumentParser(description="Native dialogs for invoice hub")
    parser.add_argument("command", choices=["pick-directory", "pick-file"])
    parser.add_argument("--initial-dir", default="")
    parser.add_argument("--title", default="选择发票监控文件夹")
    args = parser.parse_args()

    if args.command == "pick-directory":
        selected = pick_directory(args.initial_dir, args.title)
    else:
        selected = pick_file(args.initial_dir, args.title)
    print(json.dumps({"ok": True, "selected": bool(selected), "path": selected}, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
