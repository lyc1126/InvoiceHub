//! Pure transaction boundary for a verified desktop update.
//!
//! The coordinator deliberately knows nothing about Tauri, HTTP, the updater
//! plugin, or a concrete monitor.  Its source must return [`VerifiedUpdate`]
//! only after download and the built-in signature check have completed.  This
//! keeps every irreversible operation after the verification boundary and
//! makes the failure order testable with small in-memory adapters.

/// Host-owned metadata for the update selected by an earlier, authenticated
/// check.  It intentionally contains no caller-supplied URL or local path.
#[derive(Clone, Debug, PartialEq, Eq)]
pub struct UpdateCandidate {
    pub version: String,
    pub artifact_id: String,
}

impl UpdateCandidate {
    pub fn new(version: impl Into<String>, artifact_id: impl Into<String>) -> Self {
        Self {
            version: version.into(),
            artifact_id: artifact_id.into(),
        }
    }
}

/// Bytes that have passed the source's built-in signature verification.
///
/// The coordinator accepts this type at the install boundary rather than raw
/// bytes so an installer cannot accidentally be called with an unverified
/// download.  Its constructor is module-private: source adapters receive a
/// coordinator-owned promotion callback and can only obtain this value by
/// invoking that callback after their built-in verification succeeds.
#[derive(Clone, Debug, PartialEq, Eq)]
pub struct VerifiedUpdate {
    candidate: UpdateCandidate,
    bytes: Vec<u8>,
}

impl VerifiedUpdate {
    fn from_verified_bytes(candidate: UpdateCandidate, bytes: Vec<u8>) -> Self {
        Self { candidate, bytes }
    }

    pub fn candidate(&self) -> &UpdateCandidate {
        &self.candidate
    }

    pub fn as_bytes(&self) -> &[u8] {
        &self.bytes
    }

    pub fn into_bytes(self) -> Vec<u8> {
        self.bytes
    }
}

/// Download and built-in signature-verification boundary.
///
/// Implementations should return only after the updater has both downloaded
/// the artifact and verified its signature.  Returning an error from either
/// phase keeps the coordinator before marker publication and monitor changes.
pub trait VerifiedArtifactSource {
    type Error;

    fn download_and_verify(
        &mut self,
        candidate: &UpdateCandidate,
        promote: &mut dyn FnMut(Vec<u8>) -> VerifiedUpdate,
    ) -> Result<VerifiedUpdate, Self::Error>;
}

/// Reuse the recovery primitive's outcomes so the coordinator and its concrete
/// monitor adapter cannot drift into separate state vocabularies.
pub use crate::monitor_recovery::{PauseOutcome, RestoreOutcome};

/// The coordinator's view of a restore attempt in a failed transaction.
#[derive(Debug, PartialEq, Eq)]
pub enum RecoveryAttempt<E> {
    /// The monitor was originally stopped, so no restore was called.
    NotNeeded,
    /// The restore request found no marker to resolve.
    NoMarker,
    /// The monitor was already ready, so the restore request only cleared the marker.
    MonitorAlreadyReady,
    /// The monitor was restarted and verified ready.
    MonitorRestored,
    /// The controller could not complete the restore.  It owns the decision
    /// to preserve an unresolved marker.
    Failed(E),
}

/// Recovery primitive injected by the host integration.
///
/// The implementation is responsible for lifecycle-authority validation,
/// marker publication/retention, and monitor status rechecks.  In particular,
/// `restore_owned_monitor` must preserve an unresolved marker when it cannot
/// restore under the still-valid authority.
pub trait RecoveryController {
    type Error;

    fn pause_owned_monitor(&mut self) -> Result<PauseOutcome, Self::Error>;

    fn restore_owned_monitor(&mut self) -> Result<RestoreOutcome, Self::Error>;
}

impl<'a, A, B, S> RecoveryController
    for crate::monitor_recovery::MonitorRecoveryTransaction<'a, A, B, S>
where
    A: crate::monitor_recovery::LifecycleAuthority,
    B: crate::monitor_recovery::MonitorRecoveryBridge,
    S: crate::monitor_recovery::RecoveryMarkerStore + ?Sized,
{
    type Error = crate::monitor_recovery::RecoveryError;

    fn pause_owned_monitor(&mut self) -> Result<PauseOutcome, Self::Error> {
        crate::monitor_recovery::MonitorRecoveryTransaction::pause_owned_monitor(self)
    }

    fn restore_owned_monitor(&mut self) -> Result<RestoreOutcome, Self::Error> {
        crate::monitor_recovery::MonitorRecoveryTransaction::restore_owned_monitor(self)
    }
}

/// Installs the already verified bytes without requesting a second download.
pub trait UpdateInstaller {
    type Error;

    fn install(&mut self, update: VerifiedUpdate) -> Result<(), Self::Error>;
}

/// Requests the host/application relaunch after installation has completed.
pub trait RelaunchRequester {
    type Error;

    fn request_relaunch(&mut self) -> Result<(), Self::Error>;
}

/// The result of a completed install/relaunch transaction.
#[derive(Clone, Debug, PartialEq, Eq)]
pub struct UpdateOutcome {
    pub candidate: UpdateCandidate,
    pub pause: PauseOutcome,
}

/// Failure at a particular phase of the transaction.
///
/// For pause, install, and relaunch failures, the `recovery` field preserves a
/// restore failure alongside the primary failure.  On a successful
/// cross-process install/relaunch no restore is attempted, intentionally
/// leaving the marker for the next verified owned startup.
#[derive(Debug, PartialEq, Eq)]
pub enum CoordinatorError<SourceError, PauseError, InstallError, RelaunchError, RecoveryError> {
    DownloadOrVerification(SourceError),
    CandidateMismatch {
        expected: UpdateCandidate,
        actual: UpdateCandidate,
    },
    Pause {
        primary: PauseError,
        recovery: RecoveryAttempt<RecoveryError>,
    },
    Install {
        primary: InstallError,
        recovery: RecoveryAttempt<RecoveryError>,
    },
    Relaunch {
        primary: RelaunchError,
        recovery: RecoveryAttempt<RecoveryError>,
    },
}

/// Alias with a descriptive name for callers that prefer update-specific
/// terminology.
pub type UpdateCoordinatorError<
    SourceError,
    PauseError,
    InstallError,
    RelaunchError,
    RecoveryError,
> = CoordinatorError<SourceError, PauseError, InstallError, RelaunchError, RecoveryError>;

/// Pure update transaction.  All external effects are supplied as traits, so
/// this type does not start a process, bind a port, touch a marker, or access
/// the network by itself.
pub struct UpdateCoordinator<'a, S, C, I, R>
where
    S: VerifiedArtifactSource,
    C: RecoveryController,
    I: UpdateInstaller,
    R: RelaunchRequester,
{
    source: &'a mut S,
    recovery: &'a mut C,
    installer: &'a mut I,
    relauncher: &'a mut R,
}

impl<'a, S, C, I, R> UpdateCoordinator<'a, S, C, I, R>
where
    S: VerifiedArtifactSource,
    C: RecoveryController,
    I: UpdateInstaller,
    R: RelaunchRequester,
{
    pub fn new(
        source: &'a mut S,
        recovery: &'a mut C,
        installer: &'a mut I,
        relauncher: &'a mut R,
    ) -> Self {
        Self {
            source,
            recovery,
            installer,
            relauncher,
        }
    }

    /// Execute the fixed transaction order:
    ///
    /// 1. download and verify the artifact;
    /// 2. pause the owned monitor;
    /// 3. install the verified bytes;
    /// 4. request relaunch.
    ///
    /// Every failure after a marker-producing pause gets one best-effort
    /// restore.  A restore failure is retained in the returned error, while a
    /// successful cross-process handoff deliberately skips restoration.
    pub fn execute(
        &mut self,
        candidate: &UpdateCandidate,
    ) -> Result<UpdateOutcome, CoordinatorError<S::Error, C::Error, I::Error, R::Error, C::Error>>
    {
        let expected_candidate = candidate.clone();
        let mut promote =
            |bytes| VerifiedUpdate::from_verified_bytes(expected_candidate.clone(), bytes);
        let verified = self
            .source
            .download_and_verify(candidate, &mut promote)
            .map_err(CoordinatorError::DownloadOrVerification)?;
        if verified.candidate() != candidate {
            return Err(CoordinatorError::CandidateMismatch {
                expected: candidate.clone(),
                actual: verified.candidate().clone(),
            });
        }

        let pause = match self.recovery.pause_owned_monitor() {
            Ok(pause) => pause,
            Err(primary) => {
                let recovery = self.best_effort_restore_after_pause_failure();
                return Err(CoordinatorError::Pause { primary, recovery });
            }
        };

        if let Err(primary) = self.installer.install(verified) {
            let recovery = self.best_effort_restore(pause);
            return Err(CoordinatorError::Install { primary, recovery });
        }

        if let Err(primary) = self.relauncher.request_relaunch() {
            let recovery = self.best_effort_restore(pause);
            return Err(CoordinatorError::Relaunch { primary, recovery });
        }

        Ok(UpdateOutcome {
            candidate: candidate.clone(),
            pause,
        })
    }

    /// Readable alias for callers that use “run” for an in-memory transaction.
    pub fn run(
        &mut self,
        candidate: &UpdateCandidate,
    ) -> Result<UpdateOutcome, CoordinatorError<S::Error, C::Error, I::Error, R::Error, C::Error>>
    {
        self.execute(candidate)
    }

    fn best_effort_restore_after_pause_failure(&mut self) -> RecoveryAttempt<C::Error> {
        match self.recovery.restore_owned_monitor() {
            Ok(RestoreOutcome::NoMarker) => RecoveryAttempt::NoMarker,
            Ok(RestoreOutcome::MonitorAlreadyReady) => RecoveryAttempt::MonitorAlreadyReady,
            Ok(RestoreOutcome::MonitorRestored) => RecoveryAttempt::MonitorRestored,
            Err(error) => RecoveryAttempt::Failed(error),
        }
    }

    fn best_effort_restore(&mut self, pause: PauseOutcome) -> RecoveryAttempt<C::Error> {
        if pause == PauseOutcome::MonitorAlreadyStopped {
            return RecoveryAttempt::NotNeeded;
        }
        self.best_effort_restore_after_pause_failure()
    }
}

#[cfg(test)]
mod tests {
    use std::cell::Cell;

    use super::{
        CoordinatorError, PauseOutcome, RecoveryController, RelaunchRequester, RestoreOutcome,
        UpdateCandidate, UpdateCoordinator, UpdateInstaller, VerifiedArtifactSource,
        VerifiedUpdate,
    };

    #[test]
    fn verified_update_keeps_candidate_and_bytes_together() {
        let candidate = UpdateCandidate::new("0.3.0", "macos-arm64");
        let update = VerifiedUpdate::from_verified_bytes(candidate.clone(), vec![1, 2, 3]);

        assert_eq!(update.candidate(), &candidate);
        assert_eq!(update.as_bytes(), &[1, 2, 3]);
        assert_eq!(update.clone().into_bytes(), vec![1, 2, 3]);
    }

    struct MismatchedSource;

    impl VerifiedArtifactSource for MismatchedSource {
        type Error = ();

        fn download_and_verify(
            &mut self,
            _candidate: &UpdateCandidate,
            _promote: &mut dyn FnMut(Vec<u8>) -> VerifiedUpdate,
        ) -> Result<VerifiedUpdate, Self::Error> {
            Ok(VerifiedUpdate::from_verified_bytes(
                UpdateCandidate::new("wrong-version", "wrong-artifact"),
                vec![0xde, 0xad],
            ))
        }
    }

    struct CountingRecovery {
        pause_calls: Cell<usize>,
        restore_calls: Cell<usize>,
    }

    impl RecoveryController for CountingRecovery {
        type Error = ();

        fn pause_owned_monitor(&mut self) -> Result<PauseOutcome, Self::Error> {
            self.pause_calls.set(self.pause_calls.get() + 1);
            Ok(PauseOutcome::MonitorWasStopped)
        }

        fn restore_owned_monitor(&mut self) -> Result<RestoreOutcome, Self::Error> {
            self.restore_calls.set(self.restore_calls.get() + 1);
            Ok(RestoreOutcome::MonitorRestored)
        }
    }

    struct CountingInstaller(Cell<usize>);

    impl UpdateInstaller for CountingInstaller {
        type Error = ();

        fn install(&mut self, _update: VerifiedUpdate) -> Result<(), Self::Error> {
            self.0.set(self.0.get() + 1);
            Ok(())
        }
    }

    struct CountingRelauncher(Cell<usize>);

    impl RelaunchRequester for CountingRelauncher {
        type Error = ();

        fn request_relaunch(&mut self) -> Result<(), Self::Error> {
            self.0.set(self.0.get() + 1);
            Ok(())
        }
    }

    #[test]
    fn candidate_mismatch_is_rejected_before_pause_install_or_relaunch() {
        let candidate = UpdateCandidate::new("0.3.0", "macos-arm64");
        let mismatched = UpdateCandidate::new("wrong-version", "wrong-artifact");
        let mut source = MismatchedSource;
        let mut recovery = CountingRecovery {
            pause_calls: Cell::new(0),
            restore_calls: Cell::new(0),
        };
        let mut installer = CountingInstaller(Cell::new(0));
        let mut relauncher = CountingRelauncher(Cell::new(0));

        let result =
            UpdateCoordinator::new(&mut source, &mut recovery, &mut installer, &mut relauncher)
                .execute(&candidate);

        assert_eq!(
            result,
            Err(CoordinatorError::CandidateMismatch {
                expected: candidate,
                actual: mismatched,
            })
        );
        assert_eq!(recovery.pause_calls.get(), 0);
        assert_eq!(recovery.restore_calls.get(), 0);
        assert_eq!(installer.0.get(), 0);
        assert_eq!(relauncher.0.get(), 0);
    }
}
