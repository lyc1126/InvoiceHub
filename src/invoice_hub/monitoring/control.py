from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from invoice_hub.services.monitor_bridge import MonitorBridge
from invoice_hub.storage import SQLiteRepository
from invoice_hub.targets import ensure_runtime_layout, load_config, target_profile_for


def _bridge(root: Path, config_path: str | None) -> MonitorBridge:
    config = load_config(root, config_path)
    layout, _notes = ensure_runtime_layout(config)
    profile = target_profile_for(config)
    repo = SQLiteRepository(layout.db_path)
    repo.init_db()
    return MonitorBridge(config, layout, profile, repo)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Invoice Hub monitor control")
    parser.add_argument("command", choices=["status", "start", "stop", "notify-self-test"])
    parser.add_argument("--root", default=str(Path.cwd()))
    parser.add_argument("--config", default="")
    parser.add_argument("--timeout", type=float, default=20.0)
    args = parser.parse_args(argv)
    bridge = _bridge(Path(args.root), args.config or None)
    if args.command == "status":
        payload = bridge.status()
    elif args.command == "start":
        payload = bridge.start()
    elif args.command == "stop":
        payload = bridge.stop(timeout=args.timeout)
    else:
        payload = bridge.state.notify_self_test()
    print(json.dumps(payload, ensure_ascii=False, indent=2))
    return 0 if payload.get("ok", True) else 1


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
