from __future__ import annotations

import importlib.util
import sys
from pathlib import Path


def _load_runner():
    script = Path(__file__).resolve().parents[3] / "scripts" / "tools" / "jierui_voucher_import.py"
    if not script.is_file():
        raise RuntimeError(f"packaged JieRui runner missing: {script}")
    spec = importlib.util.spec_from_file_location("invoice_hub._packaged_jierui_runner", script)
    if spec is None or spec.loader is None:
        raise RuntimeError(f"cannot load packaged JieRui runner: {script}")
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    try:
        spec.loader.exec_module(module)
    except Exception:
        sys.modules.pop(spec.name, None)
        raise
    return module


def main(argv: list[str] | None = None) -> int:
    return int(_load_runner().main(argv))


if __name__ == "__main__":
    raise SystemExit(main())
