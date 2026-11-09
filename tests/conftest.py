"""Session guard: the suite must never write the checkout's own runtime state.

The repository default config points at ./发票文件 and ./runtime. If a test (or an
import side effect, see ENG-07) builds an AppState from that config, the startup sync
rewrites those projections; with a local config pointing at a real directory it would
sync real invoices. This guard fails the run when any guarded file changes.
Set INVOICE_HUB_SKIP_REPO_STATE_GUARD=1 only while a live server runs from this checkout.
"""

import os
from pathlib import Path

import pytest


ROOT = Path(__file__).resolve().parents[1]
GUARDED_DIRECTORIES = ("runtime", "发票文件", "config")


def _repo_state_snapshot() -> dict[str, tuple[int, int]]:
    files: dict[str, tuple[int, int]] = {}
    for name in GUARDED_DIRECTORIES:
        base = ROOT / name
        if not base.is_dir():
            continue
        for path in base.rglob("*"):
            if path.is_file():
                stat = path.stat()
                files[path.relative_to(ROOT).as_posix()] = (stat.st_size, stat.st_mtime_ns)
    return files


def pytest_sessionstart(session: pytest.Session) -> None:
    session.config.stash[_SNAPSHOT_KEY] = _repo_state_snapshot()


def pytest_sessionfinish(session: pytest.Session, exitstatus: int) -> None:
    before = session.config.stash.get(_SNAPSHOT_KEY, None)
    if before is None or os.environ.get("INVOICE_HUB_SKIP_REPO_STATE_GUARD") == "1":
        return
    after = _repo_state_snapshot()
    changed = sorted(path for path in before.keys() | after.keys() if before.get(path) != after.get(path))
    if not changed:
        return
    session.exitstatus = pytest.ExitCode.TESTS_FAILED
    reporter = session.config.pluginmanager.get_plugin("terminalreporter")
    if reporter is not None:
        reporter.write_line(
            "Tests wrote the checkout's runtime state (use tmp_path-based config instead):",
            red=True,
        )
        for path in changed[:20]:
            reporter.write_line(f"  {path}", red=True)


_SNAPSHOT_KEY = pytest.StashKey[dict[str, tuple[int, int]]]()
