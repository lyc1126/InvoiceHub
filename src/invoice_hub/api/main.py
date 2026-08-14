from __future__ import annotations

import argparse
import os
from pathlib import Path

import uvicorn


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Run invoice hub localhost service",
        allow_abbrev=False,
    )
    parser.add_argument("--root", default=str(Path.cwd()))
    parser.add_argument("--config", default=None)
    parser.add_argument("--host", default=None)
    parser.add_argument("--port", type=int, default=None)
    args = parser.parse_args()
    root = Path(args.root).resolve()
    config_path = str(Path(args.config).resolve()) if args.config else None
    os.environ["INVOICE_HUB_ROOT"] = str(root)
    if args.config:
        os.environ["INVOICE_HUB_CONFIG"] = config_path or ""
    from invoice_hub.targets import load_config

    config = load_config(root, config_path)
    from invoice_hub.api.app import app

    uvicorn.run(
        app,
        host=args.host or config.host,
        port=args.port if args.port is not None else config.port,
        log_level="info",
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
