use std::cell::Cell;
use std::rc::Rc;

use invoicehub_desktop::monitor_recovery::{
    LifecycleAuthority, LifecycleLease, LifecyclePhase, MarkerStoreError, MonitorRecoveryBridge,
    MonitorRecoveryTransaction, MonitorSnapshot, PauseOutcome, RecoveryError, RecoveryMarker,
    RecoveryMarkerStore, RestoreOutcome,
};

const SCOPE: &str = "aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa";

fn valid_lease() -> LifecycleLease {
    LifecycleLease {
        generation: 7,
        phase: LifecyclePhase::OwnedRunning,
        health_pid: 4100,
        owned_pid: 4100,
        process_pid: 4100,
        startup_gate_released: true,
        state_scope: SCOPE.to_owned(),
    }
}

fn valid_marker() -> RecoveryMarker {
    RecoveryMarker::new("b".repeat(32), valid_lease()).expect("valid test marker")
}

struct MockAuthority {
    lease: LifecycleLease,
    valid: Rc<Cell<bool>>,
    revalidations: Cell<usize>,
}

impl MockAuthority {
    fn new(lease: LifecycleLease) -> Self {
        Self {
            lease,
            valid: Rc::new(Cell::new(true)),
            revalidations: Cell::new(0),
        }
    }
}

impl LifecycleAuthority for MockAuthority {
    fn capture_released_lease(&self) -> Result<LifecycleLease, RecoveryError> {
        if self.valid.get() {
            Ok(self.lease.clone())
        } else {
            Err(RecoveryError::OwnershipLost)
        }
    }

    fn revalidate_lease(&self, lease: &LifecycleLease) -> Result<(), RecoveryError> {
        self.revalidations.set(self.revalidations.get() + 1);
        if self.valid.get() && *lease == self.lease {
            Ok(())
        } else {
            Err(RecoveryError::OwnershipLost)
        }
    }
}

struct MockBridge {
    snapshot: MonitorSnapshot,
    calls: Vec<&'static str>,
    leases: Vec<LifecycleLease>,
    fail_status: bool,
    fail_stop: bool,
    fail_start: bool,
}

impl MockBridge {
    fn new(running: bool, ready: bool) -> Self {
        Self {
            snapshot: MonitorSnapshot { running, ready },
            calls: Vec::new(),
            leases: Vec::new(),
            fail_status: false,
            fail_stop: false,
            fail_start: false,
        }
    }

    fn record(&mut self, call: &'static str, lease: &LifecycleLease) {
        self.calls.push(call);
        self.leases.push(lease.clone());
    }
}

impl MonitorRecoveryBridge for MockBridge {
    fn status(&mut self, lease: &LifecycleLease) -> Result<MonitorSnapshot, RecoveryError> {
        self.record("status", lease);
        if self.fail_status {
            Err(RecoveryError::MonitorUnavailable)
        } else {
            Ok(self.snapshot)
        }
    }

    fn stop(&mut self, lease: &LifecycleLease) -> Result<(), RecoveryError> {
        self.record("stop", lease);
        if self.fail_stop {
            Err(RecoveryError::MonitorUnavailable)
        } else {
            self.snapshot.running = false;
            self.snapshot.ready = false;
            Ok(())
        }
    }

    fn start(&mut self, lease: &LifecycleLease) -> Result<(), RecoveryError> {
        self.record("start", lease);
        if self.fail_start {
            Err(RecoveryError::MonitorUnavailable)
        } else {
            self.snapshot.running = true;
            self.snapshot.ready = true;
            Ok(())
        }
    }
}

#[derive(Default)]
struct MockMarkerStore {
    marker: Option<RecoveryMarker>,
    calls: Vec<&'static str>,
    load_error: Option<MarkerStoreError>,
    publish_error: Option<MarkerStoreError>,
    clear_error: Option<MarkerStoreError>,
    invalidate_after_publish: Option<Rc<Cell<bool>>>,
}

impl RecoveryMarkerStore for MockMarkerStore {
    fn load(&mut self) -> Result<Option<RecoveryMarker>, MarkerStoreError> {
        self.calls.push("load");
        if let Some(error) = self.load_error {
            Err(error)
        } else {
            Ok(self.marker.clone())
        }
    }

    fn publish(&mut self, marker: &RecoveryMarker) -> Result<(), MarkerStoreError> {
        self.calls.push("publish");
        if let Some(error) = self.publish_error {
            return Err(error);
        }
        self.marker = Some(marker.clone());
        if let Some(valid) = &self.invalidate_after_publish {
            valid.set(false);
        }
        Ok(())
    }

    fn clear(&mut self, expected: &RecoveryMarker) -> Result<(), MarkerStoreError> {
        self.calls.push("clear");
        if let Some(error) = self.clear_error {
            return Err(error);
        }
        if self.marker.as_ref() != Some(expected) {
            return Err(MarkerStoreError::MarkerChanged);
        }
        self.marker = None;
        Ok(())
    }
}

#[test]
fn pause_persists_the_owned_running_fact_before_stopping_and_rechecks_the_result() {
    let authority = MockAuthority::new(valid_lease());
    let mut bridge = MockBridge::new(true, true);
    let mut markers = MockMarkerStore::default();

    let result = MonitorRecoveryTransaction::new(&authority, &mut bridge, &mut markers)
        .pause_owned_monitor();

    assert_eq!(result, Ok(PauseOutcome::MonitorWasStopped));
    assert!(markers.marker.is_some());
    assert_eq!(markers.calls, vec!["load", "publish"]);
    assert_eq!(bridge.calls, vec!["status", "stop", "status"]);
    assert!(bridge.leases.iter().all(|lease| *lease == authority.lease));
    assert_eq!(
        bridge.snapshot,
        MonitorSnapshot {
            running: false,
            ready: false
        }
    );
    assert!(authority.revalidations.get() >= 6);
}

#[test]
fn initially_stopped_monitor_creates_no_marker_and_receives_no_stop_request() {
    let authority = MockAuthority::new(valid_lease());
    let mut bridge = MockBridge::new(false, false);
    let mut markers = MockMarkerStore::default();

    let result = MonitorRecoveryTransaction::new(&authority, &mut bridge, &mut markers)
        .pause_owned_monitor();

    assert_eq!(result, Ok(PauseOutcome::MonitorAlreadyStopped));
    assert!(markers.marker.is_none());
    assert_eq!(markers.calls, vec!["load"]);
    assert_eq!(bridge.calls, vec!["status"]);
}

#[test]
fn existing_recovery_marker_blocks_a_second_pause_before_monitor_operations() {
    let authority = MockAuthority::new(valid_lease());
    let mut bridge = MockBridge::new(true, true);
    let marker = valid_marker();
    let mut markers = MockMarkerStore {
        marker: Some(marker.clone()),
        ..MockMarkerStore::default()
    };

    let result = MonitorRecoveryTransaction::new(&authority, &mut bridge, &mut markers)
        .pause_owned_monitor();

    assert_eq!(result, Err(RecoveryError::RecoveryPending));
    assert_eq!(markers.marker, Some(marker));
    assert_eq!(markers.calls, vec!["load"]);
    assert!(bridge.calls.is_empty());
}

#[test]
fn running_but_unready_monitor_is_not_stopped_or_marked() {
    let authority = MockAuthority::new(valid_lease());
    let mut bridge = MockBridge::new(true, false);
    let mut markers = MockMarkerStore::default();

    let result = MonitorRecoveryTransaction::new(&authority, &mut bridge, &mut markers)
        .pause_owned_monitor();

    assert_eq!(result, Err(RecoveryError::MonitorNotReady));
    assert!(markers.marker.is_none());
    assert_eq!(markers.calls, vec!["load"]);
    assert_eq!(bridge.calls, vec!["status"]);
}

#[test]
fn ownership_loss_after_marker_write_blocks_the_stop_and_preserves_the_marker() {
    let authority = MockAuthority::new(valid_lease());
    let mut bridge = MockBridge::new(true, true);
    let mut markers = MockMarkerStore {
        invalidate_after_publish: Some(Rc::clone(&authority.valid)),
        ..MockMarkerStore::default()
    };

    let result = MonitorRecoveryTransaction::new(&authority, &mut bridge, &mut markers)
        .pause_owned_monitor();

    assert_eq!(result, Err(RecoveryError::OwnershipLost));
    assert!(markers.marker.is_some());
    assert_eq!(bridge.calls, vec!["status"]);
}

#[test]
fn stop_failure_keeps_the_marker_and_never_attempts_a_start() {
    let authority = MockAuthority::new(valid_lease());
    let mut bridge = MockBridge::new(true, true);
    bridge.fail_stop = true;
    let mut markers = MockMarkerStore::default();

    let result = MonitorRecoveryTransaction::new(&authority, &mut bridge, &mut markers)
        .pause_owned_monitor();

    assert_eq!(result, Err(RecoveryError::MonitorUnavailable));
    assert!(markers.marker.is_some());
    assert_eq!(bridge.calls, vec!["status", "stop"]);
}

#[test]
fn restore_requires_a_released_owned_lease_then_waits_for_running_and_ready_before_clear() {
    let authority = MockAuthority::new(valid_lease());
    let mut bridge = MockBridge::new(false, false);
    let mut markers = MockMarkerStore {
        marker: Some(valid_marker()),
        ..MockMarkerStore::default()
    };

    let result = MonitorRecoveryTransaction::new(&authority, &mut bridge, &mut markers)
        .restore_owned_monitor();

    assert_eq!(result, Ok(RestoreOutcome::MonitorRestored));
    assert!(markers.marker.is_none());
    assert_eq!(markers.calls, vec!["load", "clear"]);
    assert_eq!(bridge.calls, vec!["status", "start", "status"]);
    assert_eq!(
        bridge.snapshot,
        MonitorSnapshot {
            running: true,
            ready: true
        }
    );
}

#[test]
fn restore_never_restarts_a_monitor_that_reports_running_but_not_ready() {
    let authority = MockAuthority::new(valid_lease());
    let mut bridge = MockBridge::new(true, false);
    let marker = valid_marker();
    let mut markers = MockMarkerStore {
        marker: Some(marker.clone()),
        ..MockMarkerStore::default()
    };

    let result = MonitorRecoveryTransaction::new(&authority, &mut bridge, &mut markers)
        .restore_owned_monitor();

    assert_eq!(result, Err(RecoveryError::MonitorNotReady));
    assert_eq!(markers.marker, Some(marker));
    assert_eq!(bridge.calls, vec!["status"]);
}

#[test]
fn corrupt_or_cross_scope_marker_blocks_recovery_before_any_monitor_bridge_call() {
    let authority = MockAuthority::new(valid_lease());
    let mut bridge = MockBridge::new(false, false);
    let mut corrupt = MockMarkerStore {
        load_error: Some(MarkerStoreError::CorruptMarker),
        ..MockMarkerStore::default()
    };

    let result = MonitorRecoveryTransaction::new(&authority, &mut bridge, &mut corrupt)
        .restore_owned_monitor();

    assert_eq!(
        result,
        Err(RecoveryError::Marker(MarkerStoreError::CorruptMarker))
    );
    assert!(bridge.calls.is_empty());

    let mut other_scope = valid_marker();
    other_scope.state_scope = "c".repeat(64);
    other_scope.origin_lease.state_scope = other_scope.state_scope.clone();
    let mut markers = MockMarkerStore {
        marker: Some(other_scope),
        ..MockMarkerStore::default()
    };
    let result = MonitorRecoveryTransaction::new(&authority, &mut bridge, &mut markers)
        .restore_owned_monitor();
    assert_eq!(result, Err(RecoveryError::MarkerScopeMismatch));
    assert!(bridge.calls.is_empty());
}

#[test]
fn invalid_marker_from_a_store_implementation_is_rejected_before_monitor_operations() {
    let authority = MockAuthority::new(valid_lease());
    let mut bridge = MockBridge::new(false, false);
    let mut invalid_marker = valid_marker();
    invalid_marker.origin_lease.generation = 0;
    let mut markers = MockMarkerStore {
        marker: Some(invalid_marker),
        ..MockMarkerStore::default()
    };

    let result = MonitorRecoveryTransaction::new(&authority, &mut bridge, &mut markers)
        .restore_owned_monitor();

    assert_eq!(
        result,
        Err(RecoveryError::Marker(MarkerStoreError::CorruptMarker))
    );
    assert!(bridge.calls.is_empty());
}

#[test]
fn held_startup_gate_blocks_marker_and_monitor_operations() {
    let mut lease = valid_lease();
    lease.startup_gate_released = false;
    let authority = MockAuthority::new(lease);
    let mut bridge = MockBridge::new(true, true);
    let mut markers = MockMarkerStore::default();

    let result = MonitorRecoveryTransaction::new(&authority, &mut bridge, &mut markers)
        .pause_owned_monitor();

    assert_eq!(result, Err(RecoveryError::StartupGateHeld));
    assert!(markers.marker.is_none());
    assert!(markers.calls.is_empty());
    assert!(bridge.calls.is_empty());
}

#[cfg(unix)]
#[test]
fn unix_marker_store_rejects_a_symlink_marker_without_following_it() {
    use std::fs;
    use std::os::unix::fs::symlink;
    use std::time::{SystemTime, UNIX_EPOCH};

    use invoicehub_desktop::monitor_recovery::{UnixRecoveryMarkerStore, RECOVERY_MARKER_FILE};

    let unique = SystemTime::now()
        .duration_since(UNIX_EPOCH)
        .expect("clock")
        .as_nanos();
    let root = std::env::temp_dir().join(format!(
        "invoicehub-monitor-recovery-{}-{unique}",
        std::process::id()
    ));
    fs::create_dir(&root).expect("create isolated marker root");
    let marker = root.join(RECOVERY_MARKER_FILE);
    symlink(root.join("outside"), &marker).expect("create marker symlink");

    let mut store = UnixRecoveryMarkerStore::open(&root).expect("open pinned marker root");
    assert_eq!(store.load(), Err(MarkerStoreError::SymlinkRejected));
    drop(store);

    fs::remove_file(marker).expect("remove own test symlink");
    fs::remove_dir(root).expect("remove own test directory");
}

#[cfg(unix)]
#[test]
fn unix_marker_store_rejects_a_fifo_marker_without_blocking() {
    use std::ffi::CString;
    use std::fs;
    use std::os::unix::ffi::OsStrExt;
    use std::time::{SystemTime, UNIX_EPOCH};

    use invoicehub_desktop::monitor_recovery::{UnixRecoveryMarkerStore, RECOVERY_MARKER_FILE};

    let unique = SystemTime::now()
        .duration_since(UNIX_EPOCH)
        .expect("clock")
        .as_nanos();
    let root = std::env::temp_dir().join(format!(
        "invoicehub-monitor-recovery-{}-{unique}",
        std::process::id()
    ));
    fs::create_dir(&root).expect("create isolated marker root");
    let marker = root.join(RECOVERY_MARKER_FILE);
    let marker_name = CString::new(marker.as_os_str().as_bytes()).expect("marker name");
    assert_eq!(unsafe { libc::mkfifo(marker_name.as_ptr(), 0o600) }, 0);

    let mut store = UnixRecoveryMarkerStore::open(&root).expect("open pinned marker root");
    assert_eq!(store.load(), Err(MarkerStoreError::InvalidEntry));
    drop(store);

    fs::remove_file(marker).expect("remove own test FIFO");
    fs::remove_dir(root).expect("remove own test directory");
}

#[cfg(unix)]
#[test]
fn unix_marker_store_atomically_refuses_to_replace_an_existing_marker() {
    use std::fs;
    use std::time::{SystemTime, UNIX_EPOCH};

    use invoicehub_desktop::monitor_recovery::{UnixRecoveryMarkerStore, RECOVERY_MARKER_FILE};

    let unique = SystemTime::now()
        .duration_since(UNIX_EPOCH)
        .expect("clock")
        .as_nanos();
    let root = std::env::temp_dir().join(format!(
        "invoicehub-monitor-recovery-{}-{unique}",
        std::process::id()
    ));
    fs::create_dir(&root).expect("create isolated marker root");
    let first = valid_marker();
    let second = RecoveryMarker::new("c".repeat(32), valid_lease()).expect("second marker");

    let mut store = UnixRecoveryMarkerStore::open(&root).expect("open pinned marker root");
    store.publish(&first).expect("publish first marker");
    assert_eq!(store.publish(&second), Err(MarkerStoreError::MarkerChanged));
    assert_eq!(store.load(), Ok(Some(first)));
    drop(store);

    fs::remove_file(root.join(RECOVERY_MARKER_FILE)).expect("remove own marker");
    fs::remove_dir(root).expect("remove own test directory");
}
