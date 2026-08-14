import errno
import os
import multiprocessing
from pathlib import Path
import sys
import threading
import time

from openpyxl import Workbook

import invoice_hub.monitoring.state as monitoring_state
from invoice_hub.domain.models import TargetProfile
from invoice_hub.monitoring.daemon import _update_daemon_status
from invoice_hub.monitoring.state import LOCK_FILE_NAME, MonitorState, is_pid_alive
from invoice_hub.monitoring.sync import MonitorSynchronizer
from invoice_hub.projections.summary import SUMMARY_HEADERS, summary_schema_needs_refresh
from invoice_hub.services.monitor_bridge import MonitorBridge
from invoice_hub.storage import SQLiteRepository, read_csv_rows, write_csv_rows
from invoice_hub.targets import ensure_runtime_layout, load_config, target_profile_for


def _sample_xml() -> str:
    return (Path(__file__).parent / "fixtures" / "sample_invoice.xml").read_text(encoding="utf-8")


def _hold_monitor_sync_write_lock(
    profile_payload: dict[str, str],
    db_path: str,
    entered,
    release,
) -> None:
    state = MonitorState(TargetProfile.model_validate(profile_payload), Path(db_path))
    with state.sync_write_lock():
        entered.set()
        release.wait(timeout=10)


def test_pid_alive_detects_current_process_and_rejects_invalid_pid() -> None:
    assert is_pid_alive(os.getpid()) is True
    assert is_pid_alive(99999999) is False


def test_monitor_state_recovers_broken_processed_file(tmp_path: Path) -> None:
    config = load_config(tmp_path)
    profile = target_profile_for(config)
    state = MonitorState(profile, tmp_path / "runtime" / "invoice_hub.db")
    state.processed_file.write_text("{broken", encoding="utf-8")

    payload = state.load_processed()

    assert payload == {}
    assert list(state.state_dir.glob("processed_files.broken.*.json"))
    assert state.processed_file.exists()


def test_monitor_sync_rebuilds_outputs_and_processed_state(tmp_path: Path) -> None:
    config = load_config(tmp_path)
    watch = tmp_path / "发票文件"
    watch.mkdir(exist_ok=True)
    (watch / "sample.xml").write_text(_sample_xml(), encoding="utf-8")
    profile = target_profile_for(config)
    state = MonitorState(profile, tmp_path / "runtime" / "invoice_hub.db")
    repo = SQLiteRepository(tmp_path / "runtime" / "invoice_hub.db")

    result = MonitorSynchronizer(state, repo=repo).run_sync("startup_sync", force=False)

    assert result["ok"] is True
    assert (Path(profile.workspace_dir) / "发票汇总.csv").exists()
    assert (watch / "成本发票明细.csv").exists()
    assert state.processed_file.exists()
    assert len(read_csv_rows(Path(profile.workspace_dir) / "发票汇总.csv")) == 1


def test_monitor_sync_write_lock_serializes_same_profile_across_processes_and_reenters(tmp_path: Path) -> None:
    config = load_config(tmp_path)
    profile = target_profile_for(config)
    db_path = tmp_path / "runtime" / "invoice_hub.db"
    state = MonitorState(profile, db_path)

    with state.sync_write_lock():
        with state.sync_write_lock():
            assert state.sync_write_lock_file.exists()

    context = multiprocessing.get_context("spawn")
    entered = context.Event()
    release = context.Event()
    process = context.Process(
        target=_hold_monitor_sync_write_lock,
        args=(profile.model_dump(), str(db_path), entered, release),
    )
    process.start()
    assert entered.wait(timeout=10)

    second_entered = threading.Event()

    def acquire_second_lock() -> None:
        with MonitorState(profile, db_path).sync_write_lock():
            second_entered.set()

    thread = threading.Thread(target=acquire_second_lock)
    thread.start()
    try:
        assert not second_entered.wait(timeout=0.25)
        release.set()
        assert second_entered.wait(timeout=10)
    finally:
        release.set()
        thread.join(timeout=10)
        process.join(timeout=10)
        if process.is_alive():
            process.terminate()
            process.join(timeout=5)

    assert process.exitcode == 0
    assert not thread.is_alive()


def test_windows_sync_write_lock_retries_contention_until_acquired(monkeypatch) -> None:
    class Handle:
        def __init__(self) -> None:
            self.has_content = False
            self.offset = 0

        def seek(self, offset: int, whence: int = 0) -> None:
            if whence == os.SEEK_END:
                self.offset = 1 if self.has_content else 0
            else:
                assert whence == 0
                self.offset = offset

        def tell(self) -> int:
            return self.offset

        def read(self, length: int) -> bytes:
            assert length == 1
            return b"0" if self.has_content else b""

        def write(self, value: bytes) -> None:
            assert value == b"0"
            self.has_content = True
            self.offset += len(value)

        def flush(self) -> None:
            return None

        def fileno(self) -> int:
            return 42

    class FakeMsvcrt:
        LK_NBLCK = 9

        def __init__(self) -> None:
            self.calls: list[tuple[int, int, int]] = []

        def locking(self, fd: int, mode: int, length: int) -> None:
            self.calls.append((fd, mode, length))
            if len(self.calls) < 3:
                raise OSError(errno.EACCES, "lock is held")

    class FakeOS:
        name = "nt"
        SEEK_END = os.SEEK_END

    fake_msvcrt = FakeMsvcrt()
    pauses: list[float] = []
    monkeypatch.setattr(monitoring_state, "os", FakeOS())
    monkeypatch.setitem(sys.modules, "msvcrt", fake_msvcrt)
    monkeypatch.setattr(monitoring_state.time, "sleep", pauses.append)

    monitoring_state._acquire_sync_os_lock(Handle())

    assert fake_msvcrt.calls == [(42, fake_msvcrt.LK_NBLCK, 1)] * 3
    assert pauses == [monitoring_state.SYNC_WRITE_LOCK_POLL_SECONDS] * 2


def test_daemon_status_update_waits_for_profile_sync_lock(tmp_path: Path) -> None:
    config = load_config(tmp_path)
    profile = target_profile_for(config)
    db_path = tmp_path / "runtime" / "invoice_hub.db"
    holder_state = MonitorState(profile, db_path)
    daemon_state = MonitorState(profile, db_path)
    entered = threading.Event()
    release = threading.Event()
    updated = threading.Event()

    def hold_lock() -> None:
        with holder_state.sync_write_lock():
            entered.set()
            release.wait(timeout=10)

    def write_status() -> None:
        _update_daemon_status(daemon_state, ready=True, observer_active=True)
        updated.set()

    holder = threading.Thread(target=hold_lock)
    writer = threading.Thread(target=write_status)
    holder.start()
    assert entered.wait(timeout=5)
    writer.start()
    try:
        assert not updated.wait(timeout=0.25)
        release.set()
        assert updated.wait(timeout=5)
    finally:
        release.set()
        holder.join(timeout=5)
        writer.join(timeout=5)

    assert not holder.is_alive()
    assert not writer.is_alive()
    status = daemon_state.read_status()
    assert status["ready"] is True
    assert status["observer_active"] is True


def test_monitor_sync_can_suppress_child_events_and_notifications(tmp_path: Path, monkeypatch) -> None:
    config = load_config(tmp_path)
    watch = tmp_path / "发票文件"
    watch.mkdir(exist_ok=True)
    (watch / "sample.xml").write_text(_sample_xml(), encoding="utf-8")
    profile = target_profile_for(config)
    state = MonitorState(profile, tmp_path / "runtime" / "invoice_hub.db")
    repo = SQLiteRepository(tmp_path / "runtime" / "invoice_hub.db")
    notifications: list[tuple[str, dict[str, int]]] = []
    monkeypatch.setattr(
        state,
        "notify_invoice_change",
        lambda trigger, counts: notifications.append((trigger, counts)),
    )

    result = MonitorSynchronizer(state, repo=repo).run_sync(
        "startup_sync",
        emit_events=False,
        notify=False,
    )

    assert result["ok"] is True
    assert result["rebuilt"] is True
    assert repo.list_events_after(0) == []
    assert notifications == []

    default_root = tmp_path / "default-daemon-events"
    default_config = load_config(default_root)
    default_watch = default_root / "发票文件"
    default_watch.mkdir(exist_ok=True)
    (default_watch / "sample.xml").write_text(_sample_xml(), encoding="utf-8")
    default_profile = target_profile_for(default_config)
    default_state = MonitorState(default_profile, default_root / "runtime" / "invoice_hub.db")
    default_repo = SQLiteRepository(default_root / "runtime" / "invoice_hub.db")
    default_notifications: list[tuple[str, dict[str, int]]] = []
    monkeypatch.setattr(
        default_state,
        "notify_invoice_change",
        lambda trigger, counts: default_notifications.append((trigger, counts)),
    )

    assert MonitorSynchronizer(default_state, repo=default_repo).run_sync("startup_sync")["ok"] is True
    event_types = {event["event_type"] for event in default_repo.list_events_after(0)}
    assert {"invoice.changed", "cost_analysis.updated", "monitor.sync_completed"} <= event_types
    assert default_notifications == [("startup_sync", {"added": 1, "updated": 0, "deleted": 0})]


def test_startup_sync_refreshes_old_summary_schema_and_preserves_manual_fields(tmp_path: Path) -> None:
    config = load_config(tmp_path)
    watch = tmp_path / "发票文件"
    watch.mkdir(exist_ok=True)
    source = watch / "sample.xml"
    source.write_text(_sample_xml(), encoding="utf-8")
    profile = target_profile_for(config)
    state = MonitorState(profile, tmp_path / "runtime" / "invoice_hub.db")
    synchronizer = MonitorSynchronizer(state)
    assert synchronizer.run_sync("startup_sync")["ok"] is True

    current = read_csv_rows(state.summary_csv)[0]
    old_headers = [
        header
        for header in SUMMARY_HEADERS
        if header not in {"特定业务类型", "类型识别状态", "类型识别说明"}
    ]
    write_csv_rows(state.summary_csv, old_headers, [current])

    edited = dict(current)
    edited.update(
        {
            "销售方": "手工修订销售方",
            "开票金额": "999.99",
            "发票号码": "25322000000043426431",
        }
    )
    workbook = Workbook()
    sheet = workbook.active
    sheet.append(old_headers)
    sheet.append([edited.get(header, "") for header in old_headers])
    workbook.save(state.summary_xlsx)

    result = synchronizer.run_sync("startup_sync")
    row = read_csv_rows(state.summary_csv)[0]

    assert result["ok"] is True
    assert result["manual_changed"] == 1
    assert result["manual_applied"] == 1
    assert row["销售方"] == "手工修订销售方"
    assert row["开票金额"] == "999.99"
    assert row["发票号码"] == "25322000000043426431"
    assert row["手改状态"] == "已手改"
    assert row["特定业务类型"] == "标准电子发票"
    assert row["类型识别状态"] == "ok"
    assert summary_schema_needs_refresh(state.summary_csv, state.summary_xlsx) is False


def test_monitor_lock_rejects_live_duplicate_and_cleans_stale(tmp_path: Path) -> None:
    config = load_config(tmp_path)
    profile = target_profile_for(config)
    state = MonitorState(profile, tmp_path / "runtime" / "invoice_hub.db")
    assert state.acquire_lock() is True

    duplicate = MonitorState(profile, tmp_path / "runtime" / "invoice_hub.db")
    assert duplicate.acquire_lock() is False
    state.release_lock()

    stale = state.state_dir / LOCK_FILE_NAME
    stale.write_text('{"pid": 99999999}', encoding="utf-8")
    assert state.acquire_lock() is True
    state.release_lock()


def test_monitor_bridge_starts_and_stops_daemon_process(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setenv("INVOICE_HUB_DISABLE_NOTIFY", "1")
    config = load_config(tmp_path)
    watch = tmp_path / "发票文件"
    watch.mkdir(exist_ok=True)
    (watch / "sample.xml").write_text(_sample_xml(), encoding="utf-8")
    layout, _notes = ensure_runtime_layout(config)
    profile = target_profile_for(config)
    repo = SQLiteRepository(layout.db_path)
    repo.init_db()
    bridge = MonitorBridge(config, layout, profile, repo)

    started = bridge.start()
    try:
        assert started["ok"] is True
        assert started["status"]["ready"] is True
        status = bridge.status()
        assert status["running"] is True
        assert status["ready"] is True
        assert status["observer_active"] is True
        assert status["pid"] > 0
        log_path = Path(status["log_path"])
        assert log_path.exists()
        log_text = log_path.read_text(encoding="utf-8")
        assert log_text.index("WATCHDOG_STARTED") < log_text.index("MONITOR_READY")
        if sys.platform == "darwin":
            assert "observer=polling" in log_text
        startup_events = [
            item
            for item in repo.list_events_after(0)
            if item["payload"].get("trigger") == "startup_sync"
        ]
        assert len(startup_events) >= 2
    finally:
        stopped = bridge.stop(timeout=10)
    assert stopped["ok"] is True
    assert bridge.status()["running"] is False


def test_monitor_daemon_picks_up_new_file_event(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setenv("INVOICE_HUB_DISABLE_NOTIFY", "1")
    config = load_config(tmp_path)
    layout, _notes = ensure_runtime_layout(config)
    profile = target_profile_for(config)
    repo = SQLiteRepository(layout.db_path)
    repo.init_db()
    bridge = MonitorBridge(config, layout, profile, repo)

    started = bridge.start()
    assert started["ok"] is True
    assert started["status"]["ready"] is True
    try:
        watch = Path(profile.watch_dir)
        (watch / "event-sample.xml").write_text(_sample_xml(), encoding="utf-8")
        summary_csv = Path(profile.workspace_dir) / "发票汇总.csv"
        deadline = time.time() + 10
        while time.time() < deadline:
            if summary_csv.exists() and len(read_csv_rows(summary_csv)) == 1:
                break
            time.sleep(0.25)
        assert summary_csv.exists()
        assert len(read_csv_rows(summary_csv)) == 1
    finally:
        bridge.stop(timeout=10)
