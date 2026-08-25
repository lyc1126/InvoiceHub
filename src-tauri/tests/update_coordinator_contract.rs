use std::cell::RefCell;
use std::rc::Rc;

use invoicehub_desktop::update_coordinator::{
    CoordinatorError, PauseOutcome, RecoveryAttempt, RecoveryController, RelaunchRequester,
    RestoreOutcome, UpdateCandidate, UpdateCoordinator, UpdateInstaller, UpdateOutcome,
    VerifiedArtifactSource, VerifiedUpdate,
};

#[derive(Clone)]
struct Events(Rc<RefCell<Vec<&'static str>>>);

impl Events {
    fn new() -> Self {
        Self(Rc::new(RefCell::new(Vec::new())))
    }

    fn push(&self, event: &'static str) {
        self.0.borrow_mut().push(event);
    }

    fn list(&self) -> Vec<&'static str> {
        self.0.borrow().clone()
    }
}

#[derive(Debug, Clone, Copy, PartialEq, Eq)]
enum SourceFailure {
    Download,
    Verification,
}

struct MockSource {
    events: Events,
    failure: Option<SourceFailure>,
}

impl VerifiedArtifactSource for MockSource {
    type Error = SourceFailure;

    fn download_and_verify(
        &mut self,
        _candidate: &UpdateCandidate,
        promote: &mut dyn FnMut(Vec<u8>) -> VerifiedUpdate,
    ) -> Result<VerifiedUpdate, Self::Error> {
        self.events.push("download");
        if self.failure == Some(SourceFailure::Download) {
            return Err(SourceFailure::Download);
        }
        self.events.push("verify");
        if self.failure == Some(SourceFailure::Verification) {
            return Err(SourceFailure::Verification);
        }
        Ok(promote(vec![0xca, 0xfe]))
    }
}

#[derive(Debug, Clone, Copy, PartialEq, Eq)]
enum RecoveryFailure {
    Pause,
    Restore,
}

struct MockRecovery {
    events: Events,
    pause: Result<PauseOutcome, RecoveryFailure>,
    restore: Result<RestoreOutcome, RecoveryFailure>,
    marker_present: bool,
}

impl RecoveryController for MockRecovery {
    type Error = RecoveryFailure;

    fn pause_owned_monitor(&mut self) -> Result<PauseOutcome, Self::Error> {
        self.events.push("pause");
        match self.pause.clone() {
            Ok(outcome) => {
                if outcome == PauseOutcome::MonitorWasStopped {
                    self.marker_present = true;
                }
                Ok(outcome)
            }
            Err(error) => Err(error),
        }
    }

    fn restore_owned_monitor(&mut self) -> Result<RestoreOutcome, Self::Error> {
        self.events.push("restore");
        match self.restore.clone() {
            Ok(outcome) => {
                self.marker_present = false;
                Ok(outcome)
            }
            Err(error) => Err(error),
        }
    }
}

#[derive(Debug, Clone, Copy, PartialEq, Eq)]
enum InstallFailure {
    Install,
}

struct MockInstaller {
    events: Events,
    failure: Option<InstallFailure>,
    received: Vec<u8>,
}

impl UpdateInstaller for MockInstaller {
    type Error = InstallFailure;

    fn install(&mut self, update: VerifiedUpdate) -> Result<(), Self::Error> {
        self.events.push("install");
        self.received = update.as_bytes().to_vec();
        self.failure.map_or(Ok(()), Err)
    }
}

#[derive(Debug, Clone, Copy, PartialEq, Eq)]
enum RelaunchFailure {
    Relaunch,
}

struct MockRelauncher {
    events: Events,
    failure: Option<RelaunchFailure>,
}

impl RelaunchRequester for MockRelauncher {
    type Error = RelaunchFailure;

    fn request_relaunch(&mut self) -> Result<(), Self::Error> {
        self.events.push("relaunch");
        self.failure.map_or(Ok(()), Err)
    }
}

fn candidate() -> UpdateCandidate {
    UpdateCandidate::new("0.3.0-alpha.2", "macos-arm64")
}

fn coordinator<'a>(
    source: &'a mut MockSource,
    recovery: &'a mut MockRecovery,
    installer: &'a mut MockInstaller,
    relauncher: &'a mut MockRelauncher,
) -> UpdateCoordinator<'a, MockSource, MockRecovery, MockInstaller, MockRelauncher> {
    UpdateCoordinator::new(source, recovery, installer, relauncher)
}

#[test]
fn verified_update_constructor_is_module_private() {
    let source = std::fs::read_to_string(
        std::path::PathBuf::from(env!("CARGO_MANIFEST_DIR"))
            .join("src")
            .join("update_coordinator.rs"),
    )
    .expect("update coordinator source");
    let constructor = source
        .lines()
        .find(|line| line.contains("fn from_verified_bytes("))
        .expect("verified update constructor");
    assert!(constructor.trim_start().strip_prefix("fn ").is_some());
    assert!(!constructor.contains("pub"));
    assert!(source.contains("Its constructor is module-private"));
}

#[test]
fn verified_download_and_signature_check_precede_all_recovery_effects() {
    let events = Events::new();
    let mut source = MockSource {
        events: events.clone(),
        failure: None,
    };
    let mut recovery = MockRecovery {
        events: events.clone(),
        pause: Ok(PauseOutcome::MonitorWasStopped),
        restore: Ok(RestoreOutcome::MonitorRestored),
        marker_present: false,
    };
    let mut installer = MockInstaller {
        events: events.clone(),
        failure: None,
        received: Vec::new(),
    };
    let mut relauncher = MockRelauncher {
        events: events.clone(),
        failure: None,
    };

    let result = coordinator(&mut source, &mut recovery, &mut installer, &mut relauncher)
        .execute(&candidate());

    assert_eq!(
        result,
        Ok(UpdateOutcome {
            candidate: candidate(),
            pause: PauseOutcome::MonitorWasStopped,
        })
    );
    assert_eq!(
        events.list(),
        vec!["download", "verify", "pause", "install", "relaunch"]
    );
    assert_eq!(installer.received, vec![0xca, 0xfe]);
    assert!(recovery.marker_present);
}

#[test]
fn download_failure_never_publishes_marker_or_touches_monitor_install_or_relaunch() {
    let events = Events::new();
    let mut source = MockSource {
        events: events.clone(),
        failure: Some(SourceFailure::Download),
    };
    let mut recovery = MockRecovery {
        events: events.clone(),
        pause: Ok(PauseOutcome::MonitorWasStopped),
        restore: Ok(RestoreOutcome::MonitorRestored),
        marker_present: false,
    };
    let mut installer = MockInstaller {
        events: events.clone(),
        failure: None,
        received: Vec::new(),
    };
    let mut relauncher = MockRelauncher {
        events: events.clone(),
        failure: None,
    };

    let result = coordinator(&mut source, &mut recovery, &mut installer, &mut relauncher)
        .execute(&candidate());

    assert_eq!(
        result,
        Err(CoordinatorError::DownloadOrVerification(
            SourceFailure::Download
        ))
    );
    assert_eq!(events.list(), vec!["download"]);
    assert!(!recovery.marker_present);
    assert!(installer.received.is_empty());
}

#[test]
fn verification_failure_is_equally_before_recovery_and_install() {
    let events = Events::new();
    let mut source = MockSource {
        events: events.clone(),
        failure: Some(SourceFailure::Verification),
    };
    let mut recovery = MockRecovery {
        events: events.clone(),
        pause: Ok(PauseOutcome::MonitorWasStopped),
        restore: Ok(RestoreOutcome::MonitorRestored),
        marker_present: false,
    };
    let mut installer = MockInstaller {
        events: events.clone(),
        failure: None,
        received: Vec::new(),
    };
    let mut relauncher = MockRelauncher {
        events: events.clone(),
        failure: None,
    };

    let result = coordinator(&mut source, &mut recovery, &mut installer, &mut relauncher)
        .execute(&candidate());

    assert_eq!(
        result,
        Err(CoordinatorError::DownloadOrVerification(
            SourceFailure::Verification
        ))
    );
    assert_eq!(events.list(), vec!["download", "verify"]);
    assert!(!recovery.marker_present);
}

#[test]
fn partial_pause_blocks_install_and_relaunch_and_preserves_marker_on_restore_failure() {
    let events = Events::new();
    let mut source = MockSource {
        events: events.clone(),
        failure: None,
    };
    let mut recovery = MockRecovery {
        events: events.clone(),
        pause: Err(RecoveryFailure::Pause),
        restore: Err(RecoveryFailure::Restore),
        marker_present: true,
    };
    let mut installer = MockInstaller {
        events: events.clone(),
        failure: None,
        received: Vec::new(),
    };
    let mut relauncher = MockRelauncher {
        events: events.clone(),
        failure: None,
    };

    let result = coordinator(&mut source, &mut recovery, &mut installer, &mut relauncher)
        .execute(&candidate());

    assert_eq!(
        result,
        Err(CoordinatorError::Pause {
            primary: RecoveryFailure::Pause,
            recovery: RecoveryAttempt::Failed(RecoveryFailure::Restore),
        })
    );
    assert_eq!(
        events.list(),
        vec!["download", "verify", "pause", "restore"]
    );
    assert!(recovery.marker_present);
    assert!(installer.received.is_empty());
}

#[test]
fn pause_failure_before_marker_publication_reports_no_marker_restore() {
    let events = Events::new();
    let mut source = MockSource {
        events: events.clone(),
        failure: None,
    };
    let mut recovery = MockRecovery {
        events: events.clone(),
        pause: Err(RecoveryFailure::Pause),
        restore: Ok(RestoreOutcome::NoMarker),
        marker_present: false,
    };
    let mut installer = MockInstaller {
        events: events.clone(),
        failure: None,
        received: Vec::new(),
    };
    let mut relauncher = MockRelauncher {
        events: events.clone(),
        failure: None,
    };

    let result = coordinator(&mut source, &mut recovery, &mut installer, &mut relauncher)
        .execute(&candidate());

    assert_eq!(
        result,
        Err(CoordinatorError::Pause {
            primary: RecoveryFailure::Pause,
            recovery: RecoveryAttempt::NoMarker,
        })
    );
    assert_eq!(
        events.list(),
        vec!["download", "verify", "pause", "restore"]
    );
    assert!(!recovery.marker_present);
    assert!(installer.received.is_empty());
}

#[test]
fn install_failure_attempts_restore_and_keeps_both_failure_values() {
    let events = Events::new();
    let mut source = MockSource {
        events: events.clone(),
        failure: None,
    };
    let mut recovery = MockRecovery {
        events: events.clone(),
        pause: Ok(PauseOutcome::MonitorWasStopped),
        restore: Err(RecoveryFailure::Restore),
        marker_present: false,
    };
    let mut installer = MockInstaller {
        events: events.clone(),
        failure: Some(InstallFailure::Install),
        received: Vec::new(),
    };
    let mut relauncher = MockRelauncher {
        events: events.clone(),
        failure: None,
    };

    let result = coordinator(&mut source, &mut recovery, &mut installer, &mut relauncher)
        .execute(&candidate());

    assert_eq!(
        result,
        Err(CoordinatorError::Install {
            primary: InstallFailure::Install,
            recovery: RecoveryAttempt::Failed(RecoveryFailure::Restore),
        })
    );
    assert_eq!(
        events.list(),
        vec!["download", "verify", "pause", "install", "restore"]
    );
    assert!(recovery.marker_present);
    assert!(relauncher
        .events
        .list()
        .iter()
        .all(|event| *event != "relaunch"));
}

#[test]
fn relaunch_failure_attempts_restore_after_install_and_preserves_primary_failure() {
    let events = Events::new();
    let mut source = MockSource {
        events: events.clone(),
        failure: None,
    };
    let mut recovery = MockRecovery {
        events: events.clone(),
        pause: Ok(PauseOutcome::MonitorWasStopped),
        restore: Ok(RestoreOutcome::MonitorRestored),
        marker_present: false,
    };
    let mut installer = MockInstaller {
        events: events.clone(),
        failure: None,
        received: Vec::new(),
    };
    let mut relauncher = MockRelauncher {
        events: events.clone(),
        failure: Some(RelaunchFailure::Relaunch),
    };

    let result = coordinator(&mut source, &mut recovery, &mut installer, &mut relauncher)
        .execute(&candidate());

    assert_eq!(
        result,
        Err(CoordinatorError::Relaunch {
            primary: RelaunchFailure::Relaunch,
            recovery: RecoveryAttempt::MonitorRestored,
        })
    );
    assert_eq!(
        events.list(),
        vec!["download", "verify", "pause", "install", "relaunch", "restore"]
    );
    assert!(!recovery.marker_present);
}

#[test]
fn restore_when_monitor_is_already_ready_reports_that_outcome() {
    let events = Events::new();
    let mut source = MockSource {
        events: events.clone(),
        failure: None,
    };
    let mut recovery = MockRecovery {
        events: events.clone(),
        pause: Ok(PauseOutcome::MonitorWasStopped),
        restore: Ok(RestoreOutcome::MonitorAlreadyReady),
        marker_present: false,
    };
    let mut installer = MockInstaller {
        events: events.clone(),
        failure: Some(InstallFailure::Install),
        received: Vec::new(),
    };
    let mut relauncher = MockRelauncher {
        events: events.clone(),
        failure: None,
    };

    let result = coordinator(&mut source, &mut recovery, &mut installer, &mut relauncher)
        .execute(&candidate());

    assert_eq!(
        result,
        Err(CoordinatorError::Install {
            primary: InstallFailure::Install,
            recovery: RecoveryAttempt::MonitorAlreadyReady,
        })
    );
    assert_eq!(
        events.list(),
        vec!["download", "verify", "pause", "install", "restore"]
    );
    assert!(!recovery.marker_present);
    assert!(relauncher
        .events
        .list()
        .iter()
        .all(|event| *event != "relaunch"));
}

#[test]
fn originally_stopped_monitor_has_no_restore_obligation() {
    let events = Events::new();
    let mut source = MockSource {
        events: events.clone(),
        failure: None,
    };
    let mut recovery = MockRecovery {
        events: events.clone(),
        pause: Ok(PauseOutcome::MonitorAlreadyStopped),
        restore: Err(RecoveryFailure::Restore),
        marker_present: false,
    };
    let mut installer = MockInstaller {
        events: events.clone(),
        failure: None,
        received: Vec::new(),
    };
    let mut relauncher = MockRelauncher {
        events: events.clone(),
        failure: None,
    };

    let result = coordinator(&mut source, &mut recovery, &mut installer, &mut relauncher)
        .execute(&candidate());

    assert_eq!(
        result,
        Ok(UpdateOutcome {
            candidate: candidate(),
            pause: PauseOutcome::MonitorAlreadyStopped,
        })
    );
    assert_eq!(
        events.list(),
        vec!["download", "verify", "pause", "install", "relaunch"]
    );
    assert!(!recovery.marker_present);
}

#[test]
fn install_failure_for_stopped_monitor_does_not_call_restore() {
    let events = Events::new();
    let mut source = MockSource {
        events: events.clone(),
        failure: None,
    };
    let mut recovery = MockRecovery {
        events: events.clone(),
        pause: Ok(PauseOutcome::MonitorAlreadyStopped),
        restore: Err(RecoveryFailure::Restore),
        marker_present: false,
    };
    let mut installer = MockInstaller {
        events: events.clone(),
        failure: Some(InstallFailure::Install),
        received: Vec::new(),
    };
    let mut relauncher = MockRelauncher {
        events: events.clone(),
        failure: None,
    };

    let result = coordinator(&mut source, &mut recovery, &mut installer, &mut relauncher)
        .execute(&candidate());

    assert_eq!(
        result,
        Err(CoordinatorError::Install {
            primary: InstallFailure::Install,
            recovery: RecoveryAttempt::NotNeeded,
        })
    );
    assert_eq!(
        events.list(),
        vec!["download", "verify", "pause", "install"]
    );
}

#[test]
fn relaunch_failure_for_stopped_monitor_does_not_call_restore() {
    let events = Events::new();
    let mut source = MockSource {
        events: events.clone(),
        failure: None,
    };
    let mut recovery = MockRecovery {
        events: events.clone(),
        pause: Ok(PauseOutcome::MonitorAlreadyStopped),
        restore: Err(RecoveryFailure::Restore),
        marker_present: false,
    };
    let mut installer = MockInstaller {
        events: events.clone(),
        failure: None,
        received: Vec::new(),
    };
    let mut relauncher = MockRelauncher {
        events: events.clone(),
        failure: Some(RelaunchFailure::Relaunch),
    };

    let result = coordinator(&mut source, &mut recovery, &mut installer, &mut relauncher)
        .execute(&candidate());

    assert_eq!(
        result,
        Err(CoordinatorError::Relaunch {
            primary: RelaunchFailure::Relaunch,
            recovery: RecoveryAttempt::NotNeeded,
        })
    );
    assert_eq!(
        events.list(),
        vec!["download", "verify", "pause", "install", "relaunch"]
    );
    assert!(!recovery.marker_present);
}
