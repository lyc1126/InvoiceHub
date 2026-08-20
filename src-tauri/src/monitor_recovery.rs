//! Fail-closed building blocks for a future host-owned monitor recovery flow.
//!
//! This module deliberately has no updater, HTTP, or Tauri integration. A later
//! coordinator must supply a real bridge adapter and keep `update_install`
//! candidate-consuming until every recovery/relaunch step is wired together.

use std::fmt;
use std::path::Path;

use serde_json::{json, Map, Value};

pub const RECOVERY_MARKER_FILE: &str = ".invoicehub-monitor-recovery.json";
const RECOVERY_MARKER_SCHEMA: u64 = 1;

#[derive(Clone, Copy, Debug, PartialEq, Eq)]
pub enum LifecyclePhase {
    StartupGateHeld,
    OwnedRunning,
    Terminating,
    Invalid,
}

impl LifecyclePhase {
    fn marker_value(self) -> &'static str {
        match self {
            Self::StartupGateHeld => "startup_gate_held",
            Self::OwnedRunning => "owned_running",
            Self::Terminating => "terminating",
            Self::Invalid => "invalid",
        }
    }

    fn from_marker_value(value: &str) -> Option<Self> {
        match value {
            "startup_gate_held" => Some(Self::StartupGateHeld),
            "owned_running" => Some(Self::OwnedRunning),
            "terminating" => Some(Self::Terminating),
            "invalid" => Some(Self::Invalid),
            _ => None,
        }
    }
}

#[derive(Clone, Debug, PartialEq, Eq)]
pub struct LifecycleLease {
    pub generation: u64,
    pub phase: LifecyclePhase,
    pub health_pid: u32,
    pub owned_pid: u32,
    pub process_pid: u32,
    pub startup_gate_released: bool,
    pub state_scope: String,
}

impl LifecycleLease {
    pub fn is_recovery_eligible(&self) -> bool {
        self.generation != 0
            && self.phase == LifecyclePhase::OwnedRunning
            && self.startup_gate_released
            && self.health_pid != 0
            && self.health_pid == self.owned_pid
            && self.owned_pid == self.process_pid
            && is_lower_hex(&self.state_scope, 64)
    }
}

pub trait LifecycleAuthority {
    fn capture_released_lease(&self) -> Result<LifecycleLease, RecoveryError>;

    fn revalidate_lease(&self, lease: &LifecycleLease) -> Result<(), RecoveryError>;
}

#[derive(Clone, Copy, Debug, PartialEq, Eq)]
pub struct MonitorSnapshot {
    pub running: bool,
    pub ready: bool,
}

pub trait MonitorRecoveryBridge {
    fn status(&mut self, lease: &LifecycleLease) -> Result<MonitorSnapshot, RecoveryError>;

    fn stop(&mut self, lease: &LifecycleLease) -> Result<(), RecoveryError>;

    fn start(&mut self, lease: &LifecycleLease) -> Result<(), RecoveryError>;
}

#[derive(Clone, Debug, PartialEq, Eq)]
pub struct RecoveryMarker {
    pub nonce: String,
    pub state_scope: String,
    pub origin_lease: LifecycleLease,
}

impl RecoveryMarker {
    pub fn new(nonce: String, origin_lease: LifecycleLease) -> Result<Self, MarkerStoreError> {
        let marker = Self {
            nonce,
            state_scope: origin_lease.state_scope.clone(),
            origin_lease,
        };
        marker.validate()?;
        Ok(marker)
    }

    pub fn matches_scope(&self, lease: &LifecycleLease) -> bool {
        self.state_scope == lease.state_scope
    }

    fn validate(&self) -> Result<(), MarkerStoreError> {
        if !is_lower_hex(&self.nonce, 32)
            || !is_lower_hex(&self.state_scope, 64)
            || self.state_scope != self.origin_lease.state_scope
            || !self.origin_lease.is_recovery_eligible()
        {
            return Err(MarkerStoreError::CorruptMarker);
        }
        Ok(())
    }

    fn encode(&self) -> Result<Vec<u8>, MarkerStoreError> {
        self.validate()?;
        serde_json::to_vec(&json!({
            "schema": RECOVERY_MARKER_SCHEMA,
            "nonce": self.nonce,
            "state_scope": self.state_scope,
            "origin_lease": {
                "generation": self.origin_lease.generation,
                "phase": self.origin_lease.phase.marker_value(),
                "health_pid": self.origin_lease.health_pid,
                "owned_pid": self.origin_lease.owned_pid,
                "process_pid": self.origin_lease.process_pid,
                "startup_gate_released": self.origin_lease.startup_gate_released,
                "state_scope": self.origin_lease.state_scope,
            },
        }))
        .map_err(|_| MarkerStoreError::CorruptMarker)
    }

    fn decode(raw: &[u8]) -> Result<Self, MarkerStoreError> {
        let value: Value =
            serde_json::from_slice(raw).map_err(|_| MarkerStoreError::CorruptMarker)?;
        let fields = value.as_object().ok_or(MarkerStoreError::CorruptMarker)?;
        if fields.len() != 4 || required_u64(fields, "schema")? != RECOVERY_MARKER_SCHEMA {
            return Err(MarkerStoreError::CorruptMarker);
        }
        let origin = fields
            .get("origin_lease")
            .and_then(Value::as_object)
            .ok_or(MarkerStoreError::CorruptMarker)?;
        if origin.len() != 7 {
            return Err(MarkerStoreError::CorruptMarker);
        }
        let phase = LifecyclePhase::from_marker_value(required_text(origin, "phase")?)
            .ok_or(MarkerStoreError::CorruptMarker)?;
        let marker = Self {
            nonce: required_text(fields, "nonce")?.to_owned(),
            state_scope: required_text(fields, "state_scope")?.to_owned(),
            origin_lease: LifecycleLease {
                generation: required_u64(origin, "generation")?,
                phase,
                health_pid: required_u32(origin, "health_pid")?,
                owned_pid: required_u32(origin, "owned_pid")?,
                process_pid: required_u32(origin, "process_pid")?,
                startup_gate_released: required_bool(origin, "startup_gate_released")?,
                state_scope: required_text(origin, "state_scope")?.to_owned(),
            },
        };
        marker.validate()?;
        Ok(marker)
    }
}

pub trait RecoveryMarkerStore {
    fn load(&mut self) -> Result<Option<RecoveryMarker>, MarkerStoreError>;

    fn publish(&mut self, marker: &RecoveryMarker) -> Result<(), MarkerStoreError>;

    fn clear(&mut self, expected: &RecoveryMarker) -> Result<(), MarkerStoreError>;
}

#[derive(Clone, Copy, Debug, PartialEq, Eq)]
pub enum MarkerStoreError {
    UnsupportedPlatform,
    UnsafeRoot,
    SymlinkRejected,
    InvalidEntry,
    CorruptMarker,
    MarkerChanged,
    StorageUnavailable,
    RandomUnavailable,
}

impl fmt::Display for MarkerStoreError {
    fn fmt(&self, formatter: &mut fmt::Formatter<'_>) -> fmt::Result {
        let message = match self {
            Self::UnsupportedPlatform => {
                "monitor recovery marker storage is unavailable on this platform"
            }
            Self::UnsafeRoot => "monitor recovery marker root is unsafe",
            Self::SymlinkRejected => "monitor recovery marker symlink was rejected",
            Self::InvalidEntry => "monitor recovery marker entry is invalid",
            Self::CorruptMarker => "monitor recovery marker is invalid",
            Self::MarkerChanged => "monitor recovery marker changed unexpectedly",
            Self::StorageUnavailable => "monitor recovery marker storage is unavailable",
            Self::RandomUnavailable => "monitor recovery marker randomness is unavailable",
        };
        formatter.write_str(message)
    }
}

impl std::error::Error for MarkerStoreError {}

#[derive(Clone, Copy, Debug, PartialEq, Eq)]
pub enum RecoveryError {
    OwnershipLost,
    StartupGateHeld,
    LeaseInvalid,
    RecoveryPending,
    MonitorUnavailable,
    MonitorStillRunning,
    MonitorNotReady,
    MarkerScopeMismatch,
    Marker(MarkerStoreError),
}

impl fmt::Display for RecoveryError {
    fn fmt(&self, formatter: &mut fmt::Formatter<'_>) -> fmt::Result {
        let message = match self {
            Self::OwnershipLost => "desktop lifecycle ownership was lost",
            Self::StartupGateHeld => "desktop startup gate is not released",
            Self::LeaseInvalid => "desktop lifecycle lease is invalid",
            Self::RecoveryPending => "an earlier monitor recovery is still pending",
            Self::MonitorUnavailable => "monitor bridge is unavailable",
            Self::MonitorStillRunning => "monitor did not stop",
            Self::MonitorNotReady => "monitor did not become ready",
            Self::MarkerScopeMismatch => "monitor recovery marker belongs to another state scope",
            Self::Marker(error) => {
                return write!(formatter, "monitor recovery marker failed: {error}")
            }
        };
        formatter.write_str(message)
    }
}

impl std::error::Error for RecoveryError {}

impl From<MarkerStoreError> for RecoveryError {
    fn from(error: MarkerStoreError) -> Self {
        Self::Marker(error)
    }
}

#[derive(Clone, Debug, PartialEq, Eq)]
pub enum PauseOutcome {
    MonitorWasStopped,
    MonitorAlreadyStopped,
}

#[derive(Clone, Debug, PartialEq, Eq)]
pub enum RestoreOutcome {
    NoMarker,
    MonitorAlreadyReady,
    MonitorRestored,
}

pub struct MonitorRecoveryTransaction<'a, A, B, S>
where
    A: LifecycleAuthority,
    B: MonitorRecoveryBridge,
    S: RecoveryMarkerStore,
{
    authority: &'a A,
    bridge: &'a mut B,
    markers: &'a mut S,
}

impl<'a, A, B, S> MonitorRecoveryTransaction<'a, A, B, S>
where
    A: LifecycleAuthority,
    B: MonitorRecoveryBridge,
    S: RecoveryMarkerStore,
{
    pub fn new(authority: &'a A, bridge: &'a mut B, markers: &'a mut S) -> Self {
        Self {
            authority,
            bridge,
            markers,
        }
    }

    pub fn pause_owned_monitor(&mut self) -> Result<PauseOutcome, RecoveryError> {
        let lease = self.capture_lease()?;
        if let Some(marker) = self.load_marker(&lease)? {
            marker.validate()?;
            if !marker.matches_scope(&lease) {
                return Err(RecoveryError::MarkerScopeMismatch);
            }
            return Err(RecoveryError::RecoveryPending);
        }
        let before = self.status(&lease)?;
        if !before.running {
            return Ok(PauseOutcome::MonitorAlreadyStopped);
        }
        if !before.ready {
            return Err(RecoveryError::MonitorNotReady);
        }

        let marker = RecoveryMarker::new(random_hex_16()?, lease.clone())?;
        self.publish_marker(&lease, &marker)?;
        self.stop(&lease)?;
        let after_stop = self.status(&lease)?;
        if after_stop.running {
            return Err(RecoveryError::MonitorStillRunning);
        }
        Ok(PauseOutcome::MonitorWasStopped)
    }

    pub fn restore_owned_monitor(&mut self) -> Result<RestoreOutcome, RecoveryError> {
        let lease = self.capture_lease()?;
        let Some(marker) = self.load_marker(&lease)? else {
            return Ok(RestoreOutcome::NoMarker);
        };
        marker.validate()?;
        if !marker.matches_scope(&lease) {
            return Err(RecoveryError::MarkerScopeMismatch);
        }

        let current = self.status(&lease)?;
        if current.running {
            if !current.ready {
                return Err(RecoveryError::MonitorNotReady);
            }
            self.clear_marker(&lease, &marker)?;
            return Ok(RestoreOutcome::MonitorAlreadyReady);
        }

        self.start(&lease)?;
        let restored = self.status(&lease)?;
        if !restored.running || !restored.ready {
            return Err(RecoveryError::MonitorNotReady);
        }
        self.clear_marker(&lease, &marker)?;
        Ok(RestoreOutcome::MonitorRestored)
    }

    fn capture_lease(&self) -> Result<LifecycleLease, RecoveryError> {
        let lease = self.authority.capture_released_lease()?;
        if !lease.startup_gate_released {
            return Err(RecoveryError::StartupGateHeld);
        }
        if !lease.is_recovery_eligible() {
            return Err(RecoveryError::LeaseInvalid);
        }
        Ok(lease)
    }

    fn revalidate(&self, lease: &LifecycleLease) -> Result<(), RecoveryError> {
        self.authority.revalidate_lease(lease)
    }

    fn status(&mut self, lease: &LifecycleLease) -> Result<MonitorSnapshot, RecoveryError> {
        self.revalidate(lease)?;
        let status = self.bridge.status(lease)?;
        self.revalidate(lease)?;
        Ok(status)
    }

    fn stop(&mut self, lease: &LifecycleLease) -> Result<(), RecoveryError> {
        self.revalidate(lease)?;
        self.bridge.stop(lease)?;
        self.revalidate(lease)
    }

    fn start(&mut self, lease: &LifecycleLease) -> Result<(), RecoveryError> {
        self.revalidate(lease)?;
        self.bridge.start(lease)?;
        self.revalidate(lease)
    }

    fn load_marker(
        &mut self,
        lease: &LifecycleLease,
    ) -> Result<Option<RecoveryMarker>, RecoveryError> {
        self.revalidate(lease)?;
        let marker = self.markers.load()?;
        self.revalidate(lease)?;
        Ok(marker)
    }

    fn publish_marker(
        &mut self,
        lease: &LifecycleLease,
        marker: &RecoveryMarker,
    ) -> Result<(), RecoveryError> {
        self.revalidate(lease)?;
        self.markers.publish(marker)?;
        self.revalidate(lease)
    }

    fn clear_marker(
        &mut self,
        lease: &LifecycleLease,
        marker: &RecoveryMarker,
    ) -> Result<(), RecoveryError> {
        self.revalidate(lease)?;
        self.markers.clear(marker)?;
        self.revalidate(lease)
    }
}

pub fn open_platform_marker_store(
    root: &Path,
) -> Result<Box<dyn RecoveryMarkerStore>, MarkerStoreError> {
    #[cfg(unix)]
    {
        return Ok(Box::new(UnixRecoveryMarkerStore::open(root)?));
    }
    #[cfg(not(unix))]
    {
        let _ = root;
        Err(MarkerStoreError::UnsupportedPlatform)
    }
}

fn required_text<'a>(
    fields: &'a Map<String, Value>,
    name: &str,
) -> Result<&'a str, MarkerStoreError> {
    fields
        .get(name)
        .and_then(Value::as_str)
        .ok_or(MarkerStoreError::CorruptMarker)
}

fn required_u64(fields: &Map<String, Value>, name: &str) -> Result<u64, MarkerStoreError> {
    fields
        .get(name)
        .and_then(Value::as_u64)
        .ok_or(MarkerStoreError::CorruptMarker)
}

fn required_u32(fields: &Map<String, Value>, name: &str) -> Result<u32, MarkerStoreError> {
    required_u64(fields, name)
        .and_then(|value| u32::try_from(value).map_err(|_| MarkerStoreError::CorruptMarker))
}

fn required_bool(fields: &Map<String, Value>, name: &str) -> Result<bool, MarkerStoreError> {
    fields
        .get(name)
        .and_then(Value::as_bool)
        .ok_or(MarkerStoreError::CorruptMarker)
}

fn is_lower_hex(value: &str, expected_len: usize) -> bool {
    value.len() == expected_len
        && value
            .bytes()
            .all(|byte| byte.is_ascii_digit() || (b'a'..=b'f').contains(&byte))
}

fn random_hex_16() -> Result<String, MarkerStoreError> {
    let mut bytes = [0_u8; 16];
    getrandom::fill(&mut bytes).map_err(|_| MarkerStoreError::RandomUnavailable)?;
    let mut output = String::with_capacity(32);
    for byte in bytes {
        output.push(hex_digit(byte >> 4));
        output.push(hex_digit(byte & 0x0f));
    }
    Ok(output)
}

fn hex_digit(value: u8) -> char {
    match value {
        0..=9 => char::from(b'0' + value),
        _ => char::from(b'a' + (value - 10)),
    }
}

#[cfg(unix)]
pub struct UnixRecoveryMarkerStore {
    directory: std::fs::File,
}

#[cfg(unix)]
impl UnixRecoveryMarkerStore {
    pub fn open(root: &Path) -> Result<Self, MarkerStoreError> {
        use std::ffi::CString;
        use std::os::unix::ffi::OsStrExt;
        use std::os::unix::io::FromRawFd;

        if !root.is_absolute() {
            return Err(MarkerStoreError::UnsafeRoot);
        }
        let root =
            CString::new(root.as_os_str().as_bytes()).map_err(|_| MarkerStoreError::UnsafeRoot)?;
        // Hold this descriptor for every subsequent operation so replacing an ancestor
        // path cannot redirect marker reads, publication, or deletion.
        let descriptor = unsafe {
            libc::open(
                root.as_ptr(),
                libc::O_RDONLY | libc::O_DIRECTORY | libc::O_CLOEXEC | libc::O_NOFOLLOW,
            )
        };
        if descriptor < 0 {
            return Err(last_marker_error());
        }
        let directory = unsafe { std::fs::File::from_raw_fd(descriptor) };
        Ok(Self { directory })
    }

    fn read_named(&self, name: &str) -> Result<Option<RecoveryMarker>, MarkerStoreError> {
        use std::ffi::CString;
        use std::io::Read;
        use std::os::fd::{AsRawFd, FromRawFd};

        let name = CString::new(name).map_err(|_| MarkerStoreError::InvalidEntry)?;
        let descriptor = unsafe {
            // Reject nonregular entries after opening them without allowing a FIFO to
            // block the recovery path before its descriptor metadata is checked.
            libc::openat(
                self.directory.as_raw_fd(),
                name.as_ptr(),
                libc::O_RDONLY | libc::O_CLOEXEC | libc::O_NOFOLLOW | libc::O_NONBLOCK,
            )
        };
        if descriptor < 0 {
            let error = std::io::Error::last_os_error();
            if error.raw_os_error() == Some(libc::ENOENT) {
                return Ok(None);
            }
            return Err(last_marker_error());
        }
        let file = unsafe { std::fs::File::from_raw_fd(descriptor) };
        if !file
            .metadata()
            .map_err(|_| MarkerStoreError::StorageUnavailable)?
            .is_file()
        {
            return Err(MarkerStoreError::InvalidEntry);
        }
        let mut bytes = Vec::with_capacity(512);
        file.take(16 * 1024 + 1)
            .read_to_end(&mut bytes)
            .map_err(|_| MarkerStoreError::StorageUnavailable)?;
        if bytes.len() > 16 * 1024 {
            return Err(MarkerStoreError::CorruptMarker);
        }
        RecoveryMarker::decode(&bytes).map(Some)
    }

    fn entry_is_regular(&self, name: &str) -> Result<(), MarkerStoreError> {
        use std::ffi::CString;
        use std::os::fd::AsRawFd;

        let name = CString::new(name).map_err(|_| MarkerStoreError::InvalidEntry)?;
        let mut stat = unsafe { std::mem::zeroed::<libc::stat>() };
        let result = unsafe {
            libc::fstatat(
                self.directory.as_raw_fd(),
                name.as_ptr(),
                &mut stat,
                libc::AT_SYMLINK_NOFOLLOW,
            )
        };
        if result != 0 {
            return Err(last_marker_error());
        }
        let kind = stat.st_mode & libc::S_IFMT as libc::mode_t;
        if kind == libc::S_IFLNK as libc::mode_t {
            return Err(MarkerStoreError::SymlinkRejected);
        }
        if kind != libc::S_IFREG as libc::mode_t {
            return Err(MarkerStoreError::InvalidEntry);
        }
        Ok(())
    }

    fn remove_named(&self, name: &str) -> Result<(), MarkerStoreError> {
        use std::ffi::CString;
        use std::os::fd::AsRawFd;

        let name = CString::new(name).map_err(|_| MarkerStoreError::InvalidEntry)?;
        let result = unsafe { libc::unlinkat(self.directory.as_raw_fd(), name.as_ptr(), 0) };
        if result == 0 {
            Ok(())
        } else {
            let error = std::io::Error::last_os_error();
            if error.raw_os_error() == Some(libc::ENOENT) {
                Ok(())
            } else {
                Err(last_marker_error())
            }
        }
    }

    fn temporary_name(&self, purpose: &str) -> Result<String, MarkerStoreError> {
        Ok(format!(
            ".{RECOVERY_MARKER_FILE}.{purpose}.{}",
            random_hex_16()?
        ))
    }
}

#[cfg(unix)]
impl RecoveryMarkerStore for UnixRecoveryMarkerStore {
    fn load(&mut self) -> Result<Option<RecoveryMarker>, MarkerStoreError> {
        self.read_named(RECOVERY_MARKER_FILE)
    }

    fn publish(&mut self, marker: &RecoveryMarker) -> Result<(), MarkerStoreError> {
        use std::ffi::CString;
        use std::io::Write;
        use std::os::fd::{AsRawFd, FromRawFd};

        let bytes = marker.encode()?;
        let temporary_name = self.temporary_name("pending")?;
        let temporary =
            CString::new(temporary_name.as_str()).map_err(|_| MarkerStoreError::InvalidEntry)?;
        let descriptor = unsafe {
            libc::openat(
                self.directory.as_raw_fd(),
                temporary.as_ptr(),
                libc::O_WRONLY | libc::O_CREAT | libc::O_EXCL | libc::O_CLOEXEC | libc::O_NOFOLLOW,
                0o600,
            )
        };
        if descriptor < 0 {
            return Err(last_marker_error());
        }
        let mut file = unsafe { std::fs::File::from_raw_fd(descriptor) };
        let write_result = file
            .write_all(&bytes)
            .and_then(|()| file.sync_all())
            .map_err(|_| MarkerStoreError::StorageUnavailable);
        drop(file);
        if let Err(error) = write_result {
            let _ = self.remove_named(&temporary_name);
            return Err(error);
        }

        let final_name = CString::new(RECOVERY_MARKER_FILE).expect("static marker name has no NUL");
        // `linkat` resolves both names from the pinned directory descriptor and
        // atomically refuses an existing destination rather than replacing it.
        let linked = unsafe {
            libc::linkat(
                self.directory.as_raw_fd(),
                temporary.as_ptr(),
                self.directory.as_raw_fd(),
                final_name.as_ptr(),
                0,
            )
        };
        if linked != 0 {
            let error = std::io::Error::last_os_error();
            let _ = self.remove_named(&temporary_name);
            if error.raw_os_error() == Some(libc::EEXIST) {
                return Err(MarkerStoreError::MarkerChanged);
            }
            return Err(marker_error_from_os_error(&error));
        }
        if let Err(error) = self.remove_named(&temporary_name) {
            return Err(error);
        }
        match self.read_named(RECOVERY_MARKER_FILE)? {
            Some(written) if written == *marker => Ok(()),
            _ => Err(MarkerStoreError::MarkerChanged),
        }
    }

    fn clear(&mut self, expected: &RecoveryMarker) -> Result<(), MarkerStoreError> {
        match self.read_named(RECOVERY_MARKER_FILE)? {
            Some(current) if current == *expected => {}
            _ => return Err(MarkerStoreError::MarkerChanged),
        }
        self.entry_is_regular(RECOVERY_MARKER_FILE)?;
        // `unlinkat` acts on the fixed entry in the already-open directory; it
        // never traverses a replacement symlink or an ancestor path.
        self.remove_named(RECOVERY_MARKER_FILE)
    }
}

#[cfg(unix)]
fn last_marker_error() -> MarkerStoreError {
    marker_error_from_os_error(&std::io::Error::last_os_error())
}

#[cfg(unix)]
fn marker_error_from_os_error(error: &std::io::Error) -> MarkerStoreError {
    if error.raw_os_error() == Some(libc::ELOOP) {
        MarkerStoreError::SymlinkRejected
    } else {
        MarkerStoreError::StorageUnavailable
    }
}
