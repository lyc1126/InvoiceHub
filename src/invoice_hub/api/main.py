from __future__ import annotations

import argparse
import os
import socket
import subprocess
import sys
from pathlib import Path

import uvicorn


def check_startup_port(host: str, port: int) -> str | None:
    try:
        family, socktype, protocol, _, address = socket.getaddrinfo(
            host, port, type=socket.SOCK_STREAM,
        )[0]
        with socket.socket(family, socktype, protocol) as probe:
            if os.name == "nt":
                probe.setsockopt(socket.SOL_SOCKET, socket.SO_EXCLUSIVEADDRUSE, 1)
            else:
                probe.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
            probe.bind(address)
        return None
    except OSError as error:
        message = f"InvoiceHub startup blocked at {host}:{port}: {error}\n"
        if os.name == "nt":
            try:
                from invoice_hub.platform.host_rpc import child_environment

                netstat = Path(os.environ["SystemRoot"]) / "System32" / "netstat.exe"
                result = subprocess.run(
                    [str(netstat), "-ano", "-p", "tcp"], capture_output=True,
                    text=True, errors="replace", timeout=3,
                    env=child_environment(),
                    creationflags=subprocess.CREATE_NO_WINDOW, check=False,
                )
                for line in result.stdout.splitlines():
                    fields = line.split()
                    if len(fields) == 5 and fields[0] == "TCP" and fields[1] in (
                        f"127.0.0.1:{port}", f"0.0.0.0:{port}", f"[::]:{port}",
                    ) and fields[2].endswith(":0"):
                        message += f"Listener PID: {fields[4]} (Task Manager > Details).\n"
            except (OSError, subprocess.TimeoutExpired):
                message += "Listener lookup unavailable.\n"
        return message + "Close the owning instance before retrying. No process was stopped."


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Run invoice hub localhost service",
        allow_abbrev=False,
    )
    parser.add_argument("--root", default=str(Path.cwd()))
    parser.add_argument("--config", default=None)
    parser.add_argument("--initial-state-dir", default=None)
    parser.add_argument("--host", default=None)
    parser.add_argument("--port", type=int, default=None)
    args = parser.parse_args()
    root = Path(args.root).resolve()
    config_path = str(Path(args.config).resolve()) if args.config else None
    initial_state_dir = str(Path(args.initial_state_dir).resolve()) if args.initial_state_dir else None
    os.environ["INVOICE_HUB_ROOT"] = str(root)
    if args.config:
        os.environ["INVOICE_HUB_CONFIG"] = config_path or ""
    if initial_state_dir:
        os.environ["INVOICE_HUB_INITIAL_STATE_DIR"] = initial_state_dir
    from invoice_hub.targets import load_config

    config = load_config(
        root,
        config_path,
        initial_state_dir=Path(initial_state_dir) if initial_state_dir else None,
    )
    host = args.host or config.host
    port = args.port if args.port is not None else config.port
    # CLI/test launches bypass BAT/Tauri guards. Reject an occupied port before AppState
    # creates runtime state or schedules invoice sync; Uvicorn still owns the final bind.
    failure = check_startup_port(host, port)
    if failure:
        print(failure, file=sys.stderr)
        return 1
    from invoice_hub.api.app import app

    uvicorn.run(
        app,
        host=host,
        port=port,
        log_level="info",
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
