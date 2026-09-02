//! Private loopback host channel. The bearer token never reaches Web content.

use std::error::Error;
use std::fmt;
use std::io::{Read, Write};
use std::net::{IpAddr, Ipv4Addr, SocketAddr, TcpListener, TcpStream};
use std::path::Path;
use std::sync::atomic::{AtomicBool, AtomicU64, AtomicU8, AtomicUsize, Ordering};
use std::sync::mpsc;
use std::sync::{Arc, Mutex};
use std::thread::{self, JoinHandle};
use std::time::{Duration, Instant};

use serde_json::{json, Value};
use sha2::{Digest, Sha256};
use tauri::Manager;
use tauri_plugin_dialog::DialogExt;
use tauri_plugin_updater::{Update, UpdaterExt};

use crate::app_icon::{self, AppIconId};
use crate::backend::{BackendHost, BackendLifecycleAuthority};
use crate::monitor_bridge::PythonMonitorRecoveryBridge;
use crate::monitor_recovery::{
    open_platform_marker_store, MonitorRecoveryTransaction, RecoveryMarkerStore,
};
use crate::update_coordinator::{
    RelaunchRequester, UpdateCandidate, UpdateCoordinator, UpdateInstaller, VerifiedArtifactSource,
    VerifiedUpdate,
};

pub const HOST_RPC_PATH: &str = "/v1/host-rpc";
pub const HOST_RPC_ORIGIN: &str = "http://127.0.0.1:8766";
const MAX_REQUEST_BYTES: usize = 16 * 1024;
const MAX_CONNECTIONS: usize = 4;
const REQUEST_TIMEOUT: Duration = Duration::from_secs(5);
const PICKER_TIMEOUT: Duration = Duration::from_secs(120);
const UPDATE_HTTP_TIMEOUT: Duration = Duration::from_secs(5);
const UPDATE_CANDIDATE_TTL: Duration = Duration::from_secs(300);

#[derive(Clone, Copy, Debug, PartialEq, Eq)]
pub enum HostRpcCommand {
    PickWatchDirectory,
    PickOutboundInvoiceDirectory,
    PickOcrDirectory,
    PickOcrFile,
    UpdateCheck,
    UpdateInstall,
    SetAppIcon(AppIconId),
}

impl HostRpcCommand {
    fn parse(value: &str) -> Option<Self> {
        match value {
            "pick_watch_dir" => Some(Self::PickWatchDirectory),
            "pick_outbound_invoice_dir" => Some(Self::PickOutboundInvoiceDirectory),
            "pick_ocr_directory" => Some(Self::PickOcrDirectory),
            "pick_ocr_file" => Some(Self::PickOcrFile),
            "update_check" => Some(Self::UpdateCheck),
            "update_install" => Some(Self::UpdateInstall),
            _ => None,
        }
    }

    fn from_payload(payload: &[u8]) -> Result<Self, HostRpcAuthorizationError> {
        let value: Value = serde_json::from_slice(payload)
            .map_err(|_| HostRpcAuthorizationError::CommandRejected)?;
        let object = value
            .as_object()
            .ok_or(HostRpcAuthorizationError::CommandRejected)?;
        let command = object
            .get("command")
            .and_then(Value::as_str)
            .ok_or(HostRpcAuthorizationError::CommandRejected)?;
        if command == "set_app_icon" {
            if object.len() != 2 {
                return Err(HostRpcAuthorizationError::CommandRejected);
            }
            let icon = object
                .get("icon")
                .and_then(Value::as_str)
                .and_then(AppIconId::parse)
                .ok_or(HostRpcAuthorizationError::CommandRejected)?;
            return Ok(Self::SetAppIcon(icon));
        }
        if object.len() != 1 {
            return Err(HostRpcAuthorizationError::CommandRejected);
        }
        Self::parse(command).ok_or(HostRpcAuthorizationError::CommandRejected)
    }
}

#[derive(Clone, Copy, Debug, PartialEq, Eq)]
pub enum HostRpcAuthorizationError {
    OwnershipRejected,
    TokenRejected,
    OriginRejected,
    CommandRejected,
}

impl fmt::Display for HostRpcAuthorizationError {
    fn fmt(&self, formatter: &mut fmt::Formatter<'_>) -> fmt::Result {
        formatter.write_str("Host RPC request was rejected")
    }
}

impl Error for HostRpcAuthorizationError {}

pub struct HostRpcAuthorizer {
    token: [u8; 32],
    ownership_verified: Arc<AtomicBool>,
}

impl Clone for HostRpcAuthorizer {
    fn clone(&self) -> Self {
        Self {
            token: self.token,
            ownership_verified: Arc::clone(&self.ownership_verified),
        }
    }
}

impl HostRpcAuthorizer {
    pub fn generate(ownership_verified: Arc<AtomicBool>) -> Result<Self, HostRpcServerError> {
        let mut token = [0_u8; 32];
        getrandom::fill(&mut token).map_err(|_| HostRpcServerError::RandomUnavailable)?;
        Ok(Self {
            token,
            ownership_verified,
        })
    }

    pub fn from_test_token(token: [u8; 32], ownership_verified: Arc<AtomicBool>) -> Self {
        Self {
            token,
            ownership_verified,
        }
    }

    pub fn authorize(
        &self,
        origin: &str,
        candidate_token: &[u8],
        command: &str,
    ) -> Result<(), HostRpcAuthorizationError> {
        if !self.ownership_verified.load(Ordering::Acquire) {
            return Err(HostRpcAuthorizationError::OwnershipRejected);
        }
        if origin != HOST_RPC_ORIGIN {
            return Err(HostRpcAuthorizationError::OriginRejected);
        }
        if !constant_time_equal(&self.token, candidate_token) {
            return Err(HostRpcAuthorizationError::TokenRejected);
        }
        matches!(
            command,
            "pick_watch_dir"
                | "pick_outbound_invoice_dir"
                | "pick_ocr_directory"
                | "pick_ocr_file"
                | "update_check"
                | "update_install"
                | "set_app_icon"
        )
        .then_some(())
        .ok_or(HostRpcAuthorizationError::CommandRejected)
    }

    fn token_hex(&self) -> String {
        let mut output = String::with_capacity(self.token.len() * 2);
        for byte in self.token {
            output.push(hex_digit(byte >> 4));
            output.push(hex_digit(byte & 0x0f));
        }
        output
    }
}

#[derive(Debug)]
pub enum HostRpcServerError {
    RandomUnavailable,
    ListenerUnavailable,
    MainThreadUnavailable,
    PickerUnavailable,
    UpdaterUnavailable,
}

impl fmt::Display for HostRpcServerError {
    fn fmt(&self, formatter: &mut fmt::Formatter<'_>) -> fmt::Result {
        let message = match self {
            Self::RandomUnavailable => "secure random token generation is unavailable",
            Self::ListenerUnavailable => "the private loopback listener is unavailable",
            Self::MainThreadUnavailable => {
                "the native picker cannot reach the application main thread"
            }
            Self::PickerUnavailable => "the native picker is unavailable",
            Self::UpdaterUnavailable => "the host updater is unavailable",
        };
        formatter.write_str(message)
    }
}

impl Error for HostRpcServerError {}

pub struct HostRpcServer {
    endpoint_url: String,
    token_for_backend: String,
    shutdown: Arc<AtomicBool>,
    worker: Mutex<Option<JoinHandle<()>>>,
    updater: HostUpdater,
}

#[derive(Clone)]
struct HostUpdater {
    app_handle: tauri::AppHandle<tauri::Wry>,
    endpoint: Option<String>,
    ownership_verified: Arc<AtomicBool>,
    candidate: Arc<Mutex<Option<(u64, PendingUpdate)>>>,
    candidate_generation: Arc<AtomicU64>,
    operation: Arc<Mutex<()>>,
    runtime: Arc<Mutex<Option<ActiveUpdaterRuntime>>>,
    runtime_gate: Arc<UpdaterRuntimeGate>,
}

struct PendingUpdate {
    checked_at: Instant,
    candidate: UpdateCandidate,
    update: Update,
}

struct ActiveUpdaterRuntime {
    authority: BackendLifecycleAuthority,
    ownership_secret: [u8; 32],
    markers: Box<dyn RecoveryMarkerStore + Send>,
}

#[repr(u8)]
#[derive(Clone, Copy, Debug, PartialEq, Eq)]
enum UpdaterRuntimeState {
    Disabled = 0,
    Inactive = 1,
    Activating = 2,
    Ready = 3,
    CommitReserved = 4,
    CommitExecuting = 5,
    RelaunchPrepared = 6,
    Failed = 7,
    CommitLost = 8,
}

impl UpdaterRuntimeState {
    fn from_raw(value: u8) -> Self {
        match value {
            0 => Self::Disabled,
            1 => Self::Inactive,
            2 => Self::Activating,
            3 => Self::Ready,
            4 => Self::CommitReserved,
            5 => Self::CommitExecuting,
            6 => Self::RelaunchPrepared,
            7 => Self::Failed,
            8 => Self::CommitLost,
            _ => Self::Failed,
        }
    }
}

struct UpdaterRuntimeGate {
    state: AtomicU8,
}

impl UpdaterRuntimeGate {
    fn new(enabled: bool) -> Self {
        Self {
            state: AtomicU8::new(if enabled {
                UpdaterRuntimeState::Inactive as u8
            } else {
                UpdaterRuntimeState::Disabled as u8
            }),
        }
    }

    fn state(&self) -> UpdaterRuntimeState {
        UpdaterRuntimeState::from_raw(self.state.load(Ordering::Acquire))
    }

    fn begin_activation(&self) -> Result<bool, HostRpcServerError> {
        if self.state() == UpdaterRuntimeState::Disabled {
            return Ok(false);
        }
        self.state
            .compare_exchange(
                UpdaterRuntimeState::Inactive as u8,
                UpdaterRuntimeState::Activating as u8,
                Ordering::AcqRel,
                Ordering::Acquire,
            )
            .map(|_| true)
            .map_err(|_| HostRpcServerError::UpdaterUnavailable)
    }

    fn finish_activation(&self) -> Result<(), HostRpcServerError> {
        self.transition(UpdaterRuntimeState::Activating, UpdaterRuntimeState::Ready)
    }

    fn require_ready(&self) -> Result<(), HostRpcServerError> {
        if self.state() == UpdaterRuntimeState::Ready {
            Ok(())
        } else {
            Err(HostRpcServerError::UpdaterUnavailable)
        }
    }

    fn reserve_commit(&self) -> Result<(), HostRpcServerError> {
        self.transition(
            UpdaterRuntimeState::Ready,
            UpdaterRuntimeState::CommitReserved,
        )
    }

    fn begin_execution(&self) -> Result<(), HostRpcServerError> {
        self.transition(
            UpdaterRuntimeState::CommitReserved,
            UpdaterRuntimeState::CommitExecuting,
        )
    }

    fn prepare_relaunch(&self) -> Result<(), HostRpcServerError> {
        self.transition(
            UpdaterRuntimeState::CommitExecuting,
            UpdaterRuntimeState::RelaunchPrepared,
        )
    }

    fn mark_failed(&self) {
        self.state
            .store(UpdaterRuntimeState::Failed as u8, Ordering::Release);
    }

    fn mark_commit_lost(&self) {
        self.state
            .store(UpdaterRuntimeState::CommitLost as u8, Ordering::Release);
    }

    fn blocks_normal_quit(&self) -> bool {
        matches!(
            self.state(),
            UpdaterRuntimeState::CommitReserved | UpdaterRuntimeState::CommitExecuting
        )
    }

    fn relaunch_prepared(&self) -> bool {
        self.state() == UpdaterRuntimeState::RelaunchPrepared
    }

    fn transition(
        &self,
        from: UpdaterRuntimeState,
        to: UpdaterRuntimeState,
    ) -> Result<(), HostRpcServerError> {
        self.state
            .compare_exchange(from as u8, to as u8, Ordering::AcqRel, Ordering::Acquire)
            .map(|_| ())
            .map_err(|_| HostRpcServerError::UpdaterUnavailable)
    }
}

impl HostUpdater {
    fn new(
        app_handle: tauri::AppHandle<tauri::Wry>,
        ownership_verified: Arc<AtomicBool>,
        endpoint: Option<String>,
    ) -> Self {
        let runtime_gate = Arc::new(UpdaterRuntimeGate::new(endpoint.is_some()));
        Self {
            app_handle,
            endpoint,
            ownership_verified,
            candidate: Arc::new(Mutex::new(None)),
            candidate_generation: Arc::new(AtomicU64::new(0)),
            operation: Arc::new(Mutex::new(())),
            runtime: Arc::new(Mutex::new(None)),
            runtime_gate,
        }
    }

    fn require_owned(&self) -> Result<(), HostRpcServerError> {
        if self.endpoint.is_some() && self.ownership_verified.load(Ordering::Acquire) {
            Ok(())
        } else {
            Err(HostRpcServerError::UpdaterUnavailable)
        }
    }

    fn require_ready_owned(&self) -> Result<(), HostRpcServerError> {
        self.runtime_gate.require_ready()?;
        self.require_owned()
    }

    fn activate(
        &self,
        runtime_dir: &Path,
        ownership_secret: [u8; 32],
        authority: BackendLifecycleAuthority,
    ) -> Result<bool, HostRpcServerError> {
        let _operation = self
            .operation
            .try_lock()
            .map_err(|_| HostRpcServerError::UpdaterUnavailable)?;
        if !self.runtime_gate.begin_activation()? {
            return Ok(false);
        }
        let activation = (|| {
            self.require_owned()?;
            let mut markers = open_platform_marker_store(runtime_dir)
                .map_err(|_| HostRpcServerError::UpdaterUnavailable)?;
            let mut bridge = PythonMonitorRecoveryBridge::new(ownership_secret);
            let mut recovery =
                MonitorRecoveryTransaction::new(&authority, &mut bridge, markers.as_mut());
            recovery
                .restore_owned_monitor()
                .map_err(|_| HostRpcServerError::UpdaterUnavailable)?;
            self.require_owned()?;
            let mut runtime = self
                .runtime
                .lock()
                .map_err(|_| HostRpcServerError::UpdaterUnavailable)?;
            *runtime = Some(ActiveUpdaterRuntime {
                authority,
                ownership_secret,
                markers,
            });
            self.runtime_gate.finish_activation()
        })();
        if activation.is_err() {
            self.runtime_gate.mark_failed();
        }
        activation.map(|()| true)
    }

    fn clear_candidate(&self) -> Result<(), HostRpcServerError> {
        let mut candidate = self
            .candidate
            .lock()
            .map_err(|_| HostRpcServerError::UpdaterUnavailable)?;
        candidate.take();
        Ok(())
    }

    fn clear_expired_candidate(&self, now: Instant) -> Result<bool, HostRpcServerError> {
        // A concurrent update check can replace the slot after this snapshot.
        // The generation recheck below must therefore decide the actual removal.
        let expired_generation = self
            .candidate
            .lock()
            .map_err(|_| HostRpcServerError::UpdaterUnavailable)?
            .as_ref()
            .and_then(|(generation, pending)| {
                (!candidate_is_fresh(pending.checked_at, now)).then_some(*generation)
            });
        match expired_generation {
            Some(generation) => clear_candidate_if_current(self.candidate.as_ref(), generation),
            None => Ok(false),
        }
    }

    fn check(&self) -> Result<HostRpcResponse, HostRpcServerError> {
        let _operation = self
            .operation
            .try_lock()
            .map_err(|_| HostRpcServerError::UpdaterUnavailable)?;
        self.require_ready_owned()?;
        self.clear_candidate()?;

        let endpoint = self
            .endpoint
            .as_deref()
            .ok_or(HostRpcServerError::UpdaterUnavailable)?
            .parse()
            .map_err(|_| HostRpcServerError::UpdaterUnavailable)?;
        let updater_builder = self
            .app_handle
            .updater_builder()
            .endpoints(vec![endpoint])
            .map_err(|_| HostRpcServerError::UpdaterUnavailable)?
            .timeout(UPDATE_HTTP_TIMEOUT);
        #[cfg(target_os = "windows")]
        let updater_builder = {
            let app_handle = self.app_handle.clone();
            updater_builder.on_before_exit(move || {
                let backend_stopped = app_handle
                    .try_state::<BackendHost>()
                    .is_some_and(|backend| backend.shutdown_keep_monitor_or_terminate().is_ok());
                if !backend_stopped {
                    eprintln!(
                        "InvoiceHub update installer launch was blocked because the backend did not stop"
                    );
                    std::process::exit(74);
                }
                app_handle.cleanup_before_exit();
            })
        };
        let updater = updater_builder
            .build()
            .map_err(|_| HostRpcServerError::UpdaterUnavailable)?;
        let candidate = tauri::async_runtime::block_on(updater.check())
            .map_err(|_| HostRpcServerError::UpdaterUnavailable)?;
        self.require_ready_owned()?;

        let Some(mut update) = candidate else {
            return Ok(HostRpcResponse::UpdateCheck {
                available: false,
                version: String::new(),
            });
        };
        update.timeout = Some(UPDATE_HTTP_TIMEOUT);
        let version = update.version.clone();
        let internal_candidate = UpdateCandidate::new(
            version.clone(),
            update_artifact_id(
                &update.version,
                &update.target,
                update.download_url.as_str(),
                &update.signature,
            ),
        );
        let candidate_generation = self
            .candidate_generation
            .fetch_add(1, Ordering::AcqRel)
            .wrapping_add(1);
        let mut slot = self
            .candidate
            .lock()
            .map_err(|_| HostRpcServerError::UpdaterUnavailable)?;
        *slot = Some((
            candidate_generation,
            PendingUpdate {
                checked_at: Instant::now(),
                candidate: internal_candidate,
                update,
            },
        ));
        drop(slot);
        Ok(HostRpcResponse::UpdateCheck {
            available: true,
            version,
        })
    }

    fn install(&self) -> Result<HostRpcReply, HostRpcServerError> {
        let _operation = self
            .operation
            .try_lock()
            .map_err(|_| HostRpcServerError::UpdaterUnavailable)?;
        self.require_ready_owned()?;
        let pending = self
            .candidate
            .lock()
            .map_err(|_| HostRpcServerError::UpdaterUnavailable)?
            .take()
            .map(|(_, pending)| pending)
            .ok_or(HostRpcServerError::UpdaterUnavailable)?;
        if !candidate_is_fresh(pending.checked_at, Instant::now()) {
            return Err(HostRpcServerError::UpdaterUnavailable);
        }
        self.require_ready_owned()?;
        self.runtime_gate.reserve_commit()?;
        let worker_updater = self.clone();
        let commit = spawn_deferred_commit(Arc::clone(&self.runtime_gate), move || {
            worker_updater.execute_pending_update(pending);
        })
        .map_err(|_| HostRpcServerError::UpdaterUnavailable)?;
        Ok(HostRpcReply::deferred(
            HostRpcResponse::UpdateInstall,
            commit,
        ))
    }

    fn execute_pending_update(&self, pending: PendingUpdate) {
        let transaction = (|| {
            self.require_owned()?;
            let mut runtime = self
                .runtime
                .lock()
                .map_err(|_| HostRpcServerError::UpdaterUnavailable)?;
            let active = runtime
                .as_mut()
                .ok_or(HostRpcServerError::UpdaterUnavailable)?;
            let mut bridge = PythonMonitorRecoveryBridge::new(active.ownership_secret);
            let mut recovery = MonitorRecoveryTransaction::new(
                &active.authority,
                &mut bridge,
                active.markers.as_mut(),
            );
            let mut source = HostVerifiedArtifactSource {
                update: pending.update.clone(),
            };
            let mut installer = HostUpdateInstaller {
                update: pending.update,
            };
            let mut relauncher = HostRelaunchRequester {
                app_handle: self.app_handle.clone(),
                runtime_gate: Arc::clone(&self.runtime_gate),
            };
            let mut coordinator =
                UpdateCoordinator::new(&mut source, &mut recovery, &mut installer, &mut relauncher);
            coordinator
                .execute(&pending.candidate)
                .map(|_| ())
                .map_err(|_| HostRpcServerError::UpdaterUnavailable)
        })();
        if transaction.is_err() {
            self.runtime_gate.mark_failed();
            eprintln!("InvoiceHub private update transaction failed");
        }
    }
}

struct HostVerifiedArtifactSource {
    update: Update,
}

impl VerifiedArtifactSource for HostVerifiedArtifactSource {
    type Error = tauri_plugin_updater::Error;

    fn download_and_verify(
        &mut self,
        _candidate: &UpdateCandidate,
        promote: &mut dyn FnMut(Vec<u8>) -> VerifiedUpdate,
    ) -> Result<VerifiedUpdate, Self::Error> {
        let bytes = tauri::async_runtime::block_on(self.update.download(|_, _| {}, || {}))?;
        Ok(promote(bytes))
    }
}

struct HostUpdateInstaller {
    update: Update,
}

impl UpdateInstaller for HostUpdateInstaller {
    type Error = tauri_plugin_updater::Error;

    fn install(&mut self, update: VerifiedUpdate) -> Result<(), Self::Error> {
        self.update.install(update.into_bytes())
    }
}

#[derive(Debug)]
enum HostRelaunchError {
    BackendUnavailable,
    BackendShutdownFailed,
    StateTransitionRejected,
    #[cfg(not(target_os = "macos"))]
    UnsupportedPlatform,
}

struct HostRelaunchRequester {
    app_handle: tauri::AppHandle<tauri::Wry>,
    runtime_gate: Arc<UpdaterRuntimeGate>,
}

impl RelaunchRequester for HostRelaunchRequester {
    type Error = HostRelaunchError;

    fn request_relaunch(&mut self) -> Result<(), Self::Error> {
        #[cfg(target_os = "macos")]
        {
            let backend = self
                .app_handle
                .try_state::<BackendHost>()
                .ok_or(HostRelaunchError::BackendUnavailable)?;
            backend
                .shutdown_keep_monitor_or_terminate()
                .map_err(|_| HostRelaunchError::BackendShutdownFailed)?;
            self.runtime_gate
                .prepare_relaunch()
                .map_err(|_| HostRelaunchError::StateTransitionRejected)?;
            self.app_handle.request_restart();
            return Ok(());
        }
        #[cfg(not(target_os = "macos"))]
        {
            Err(HostRelaunchError::UnsupportedPlatform)
        }
    }
}

fn update_artifact_id(version: &str, target: &str, download_url: &str, signature: &str) -> String {
    let mut digest = Sha256::new();
    digest.update(b"invoicehub-host-update-artifact-v1\0");
    for field in [version, target, download_url, signature] {
        digest.update((field.len() as u64).to_be_bytes());
        digest.update(field.as_bytes());
    }
    hex_encode(&digest.finalize())
}

fn clear_candidate_if_current<T>(
    candidate: &Mutex<Option<(u64, T)>>,
    generation: u64,
) -> Result<bool, HostRpcServerError> {
    let mut slot = candidate
        .lock()
        .map_err(|_| HostRpcServerError::UpdaterUnavailable)?;
    let is_current = slot
        .as_ref()
        .is_some_and(|(current_generation, _)| *current_generation == generation);
    if is_current {
        slot.take();
    }
    Ok(is_current)
}

fn candidate_is_fresh(checked_at: Instant, now: Instant) -> bool {
    now.checked_duration_since(checked_at)
        .is_some_and(|age| age <= UPDATE_CANDIDATE_TTL)
}

impl HostRpcServer {
    pub fn start(
        app_handle: tauri::AppHandle<tauri::Wry>,
        ownership_verified: Arc<AtomicBool>,
        updater_endpoint: Option<String>,
    ) -> Result<Self, HostRpcServerError> {
        let authorizer = HostRpcAuthorizer::generate(ownership_verified)?;
        let listener = TcpListener::bind((Ipv4Addr::LOCALHOST, 0))
            .map_err(|_| HostRpcServerError::ListenerUnavailable)?;
        let port = listener
            .local_addr()
            .map_err(|_| HostRpcServerError::ListenerUnavailable)?
            .port();
        listener
            .set_nonblocking(true)
            .map_err(|_| HostRpcServerError::ListenerUnavailable)?;
        let shutdown = Arc::new(AtomicBool::new(false));
        let worker_shutdown = Arc::clone(&shutdown);
        let active_connections = Arc::new(AtomicUsize::new(0));
        let worker_authorizer = authorizer.clone();
        let updater = HostUpdater::new(
            app_handle.clone(),
            authorizer.ownership_verified.clone(),
            updater_endpoint,
        );
        let worker_updater = updater.clone();
        let worker = thread::spawn(move || {
            serve_listener(
                listener,
                app_handle,
                worker_authorizer,
                worker_updater,
                worker_shutdown,
                active_connections,
            )
        });
        Ok(Self {
            endpoint_url: format!("http://127.0.0.1:{port}{HOST_RPC_PATH}"),
            token_for_backend: authorizer.token_hex(),
            shutdown,
            worker: Mutex::new(Some(worker)),
            updater,
        })
    }

    pub fn endpoint_url(&self) -> &str {
        &self.endpoint_url
    }

    pub(crate) fn token_for_backend(&self) -> &str {
        &self.token_for_backend
    }

    pub(crate) fn activate_updater_runtime(
        &self,
        runtime_dir: &Path,
        ownership_secret: [u8; 32],
        authority: BackendLifecycleAuthority,
    ) -> Result<bool, HostRpcServerError> {
        self.updater
            .activate(runtime_dir, ownership_secret, authority)
    }

    pub fn updater_blocks_normal_quit(&self) -> bool {
        self.updater.runtime_gate.blocks_normal_quit()
    }

    pub fn update_relaunch_prepared(&self) -> bool {
        self.updater.runtime_gate.relaunch_prepared()
    }
}

impl Drop for HostRpcServer {
    fn drop(&mut self) {
        self.shutdown.store(true, Ordering::Release);
        if let Ok(mut worker) = self.worker.lock() {
            if let Some(worker) = worker.take() {
                let _ = worker.join();
            }
        }
    }
}

fn serve_listener(
    listener: TcpListener,
    app_handle: tauri::AppHandle<tauri::Wry>,
    authorizer: HostRpcAuthorizer,
    updater: HostUpdater,
    shutdown: Arc<AtomicBool>,
    active_connections: Arc<AtomicUsize>,
) {
    while !shutdown.load(Ordering::Acquire) {
        let _ = updater.clear_expired_candidate(Instant::now());
        match listener.accept() {
            Ok((stream, peer)) => {
                if active_connections.fetch_add(1, Ordering::AcqRel) >= MAX_CONNECTIONS {
                    active_connections.fetch_sub(1, Ordering::AcqRel);
                    let _ = reject_busy_connection(stream);
                    continue;
                }
                let connection_authorizer = authorizer.clone();
                let connection_app = app_handle.clone();
                let connection_updater = updater.clone();
                let connection_count = Arc::clone(&active_connections);
                thread::spawn(move || {
                    serve_connection(
                        stream,
                        peer,
                        connection_app,
                        connection_authorizer,
                        connection_updater,
                    );
                    connection_count.fetch_sub(1, Ordering::AcqRel);
                });
            }
            Err(error) if error.kind() == std::io::ErrorKind::WouldBlock => {
                thread::sleep(Duration::from_millis(20));
            }
            Err(_) => return,
        }
    }
}

fn reject_busy_connection(mut stream: TcpStream) -> std::io::Result<()> {
    stream.write_all(
        b"HTTP/1.1 503 Service Unavailable\r\nConnection: close\r\nContent-Length: 0\r\n\r\n",
    )
}

fn serve_connection(
    mut stream: TcpStream,
    peer: SocketAddr,
    app_handle: tauri::AppHandle<tauri::Wry>,
    authorizer: HostRpcAuthorizer,
    updater: HostUpdater,
) {
    let _ = stream.set_read_timeout(Some(REQUEST_TIMEOUT));
    let _ = stream.set_write_timeout(Some(REQUEST_TIMEOUT));
    let result = if peer.ip() != IpAddr::V4(Ipv4Addr::LOCALHOST) {
        Err(HostRpcAuthorizationError::OwnershipRejected)
    } else {
        handle_request(&mut stream, &app_handle, &authorizer, &updater)
    };
    let _ = match result {
        Ok(reply) => write_rpc_reply(&mut stream, reply),
        Err(_) => write_rejected_response(&mut stream),
    };
}

fn handle_request(
    stream: &mut TcpStream,
    app_handle: &tauri::AppHandle<tauri::Wry>,
    authorizer: &HostRpcAuthorizer,
    updater: &HostUpdater,
) -> Result<HostRpcReply, HostRpcAuthorizationError> {
    let request = read_request(stream)?;
    if request.method != "POST" || request.path != HOST_RPC_PATH {
        return Err(HostRpcAuthorizationError::CommandRejected);
    }
    let command = HostRpcCommand::from_payload(&request.body)?;
    let token = parse_bearer_token(&request.authorization)
        .ok_or(HostRpcAuthorizationError::TokenRejected)?;
    authorizer.authorize(&request.origin, &token, command_name(command))?;
    match command {
        HostRpcCommand::PickWatchDirectory
        | HostRpcCommand::PickOutboundInvoiceDirectory
        | HostRpcCommand::PickOcrDirectory
        | HostRpcCommand::PickOcrFile => select_path(app_handle.clone(), command)
            .map(HostRpcResponse::Picker)
            .map(HostRpcReply::immediate)
            .map_err(|_| HostRpcAuthorizationError::CommandRejected),
        HostRpcCommand::UpdateCheck => updater
            .check()
            .map(HostRpcReply::immediate)
            .map_err(|_| HostRpcAuthorizationError::CommandRejected),
        HostRpcCommand::UpdateInstall => updater
            .install()
            .map_err(|_| HostRpcAuthorizationError::CommandRejected),
        HostRpcCommand::SetAppIcon(icon) => {
            let backend = app_handle
                .try_state::<BackendHost>()
                .ok_or(HostRpcAuthorizationError::CommandRejected)?;
            let previous_icon = app_icon::load_selected(backend.runtime_dir());
            app_icon::apply(app_handle, icon, previous_icon)
                .map(|_| HostRpcReply::immediate(HostRpcResponse::AppIconUpdated))
                .map_err(|_| HostRpcAuthorizationError::CommandRejected)
        }
    }
}

struct RpcRequest {
    method: String,
    path: String,
    origin: String,
    authorization: String,
    body: Vec<u8>,
}

fn read_request(stream: &mut TcpStream) -> Result<RpcRequest, HostRpcAuthorizationError> {
    let mut bytes = Vec::new();
    let mut chunk = [0_u8; 1024];
    let mut header_end = None;
    while header_end.is_none() {
        let read = stream
            .read(&mut chunk)
            .map_err(|_| HostRpcAuthorizationError::CommandRejected)?;
        if read == 0 || bytes.len().saturating_add(read) > MAX_REQUEST_BYTES {
            return Err(HostRpcAuthorizationError::CommandRejected);
        }
        bytes.extend_from_slice(&chunk[..read]);
        header_end = bytes.windows(4).position(|window| window == b"\r\n\r\n");
    }
    let header_end = header_end.expect("header boundary checked");
    let header = std::str::from_utf8(&bytes[..header_end])
        .map_err(|_| HostRpcAuthorizationError::CommandRejected)?;
    let mut lines = header.split("\r\n");
    let request_line = lines
        .next()
        .ok_or(HostRpcAuthorizationError::CommandRejected)?;
    let mut request_parts = request_line.split_ascii_whitespace();
    let method = request_parts.next();
    let path = request_parts.next();
    let version = request_parts.next();
    if request_parts.next().is_some() || version != Some("HTTP/1.1") {
        return Err(HostRpcAuthorizationError::CommandRejected);
    }
    let method = method
        .filter(|value| !value.is_empty())
        .map(str::to_owned)
        .ok_or(HostRpcAuthorizationError::CommandRejected)?;
    let path = path
        .filter(|value| !value.is_empty())
        .map(str::to_owned)
        .ok_or(HostRpcAuthorizationError::CommandRejected)?;
    let mut origin = None;
    let mut authorization = None;
    let mut content_length = None;
    let mut content_type = None;
    for line in lines {
        let Some((name, value)) = line.split_once(':') else {
            return Err(HostRpcAuthorizationError::CommandRejected);
        };
        let value = value.trim();
        match name.trim().to_ascii_lowercase().as_str() {
            "origin" if origin.is_none() => origin = Some(value.to_owned()),
            "authorization" if authorization.is_none() => authorization = Some(value.to_owned()),
            "content-length" if content_length.is_none() => {
                content_length = Some(value.parse::<usize>().ok())
            }
            "content-type" if content_type.is_none() => content_type = Some(value.to_owned()),
            "host" | "user-agent" | "accept" | "accept-encoding" | "connection"
                if !value.is_empty() => {}
            _ => return Err(HostRpcAuthorizationError::CommandRejected),
        }
    }
    let content_length = content_length
        .flatten()
        .filter(|length| *length <= MAX_REQUEST_BYTES)
        .ok_or(HostRpcAuthorizationError::CommandRejected)?;
    if !content_type
        .as_deref()
        .is_some_and(|value| value.eq_ignore_ascii_case("application/json"))
    {
        return Err(HostRpcAuthorizationError::CommandRejected);
    }
    let body_start = header_end + 4;
    while bytes.len().saturating_sub(body_start) < content_length {
        let read = stream
            .read(&mut chunk)
            .map_err(|_| HostRpcAuthorizationError::CommandRejected)?;
        if read == 0 || bytes.len().saturating_add(read) > MAX_REQUEST_BYTES {
            return Err(HostRpcAuthorizationError::CommandRejected);
        }
        bytes.extend_from_slice(&chunk[..read]);
    }
    if bytes.len().saturating_sub(body_start) != content_length {
        return Err(HostRpcAuthorizationError::CommandRejected);
    }
    Ok(RpcRequest {
        method,
        path,
        origin: origin.ok_or(HostRpcAuthorizationError::OriginRejected)?,
        authorization: authorization.ok_or(HostRpcAuthorizationError::TokenRejected)?,
        body: bytes[body_start..].to_vec(),
    })
}

fn select_path(
    app_handle: tauri::AppHandle<tauri::Wry>,
    command: HostRpcCommand,
) -> Result<Option<String>, HostRpcServerError> {
    let pick_file = match command {
        HostRpcCommand::PickWatchDirectory
        | HostRpcCommand::PickOutboundInvoiceDirectory
        | HostRpcCommand::PickOcrDirectory => false,
        HostRpcCommand::PickOcrFile => true,
        HostRpcCommand::UpdateCheck
        | HostRpcCommand::UpdateInstall
        | HostRpcCommand::SetAppIcon(_) => {
            return Err(HostRpcServerError::PickerUnavailable)
        }
    };
    let (sender, receiver) = mpsc::sync_channel(1);
    let dispatch_handle = app_handle.clone();
    app_handle
        .run_on_main_thread(move || {
            let respond = move |selection: Option<tauri_plugin_dialog::FilePath>| {
                let path = selection
                    .and_then(|file_path| file_path.into_path().ok())
                    .map(|path| path.to_string_lossy().into_owned());
                let _ = sender.send(path);
            };
            if pick_file {
                dispatch_handle.dialog().file().pick_file(respond);
            } else {
                dispatch_handle.dialog().file().pick_folder(respond);
            }
        })
        .map_err(|_| HostRpcServerError::MainThreadUnavailable)?;
    receiver
        .recv_timeout(PICKER_TIMEOUT)
        .map_err(|_| HostRpcServerError::PickerUnavailable)
}

enum CommitSignal {
    Execute,
    Cancel,
}

struct DeferredCommit {
    sender: Option<mpsc::SyncSender<CommitSignal>>,
    runtime_gate: Arc<UpdaterRuntimeGate>,
}

impl DeferredCommit {
    fn execute(mut self) -> Result<(), ()> {
        if self.runtime_gate.begin_execution().is_err() {
            self.runtime_gate.mark_commit_lost();
            if let Some(sender) = self.sender.take() {
                let _ = sender.send(CommitSignal::Cancel);
            }
            return Err(());
        }
        let Some(sender) = self.sender.take() else {
            self.runtime_gate.mark_commit_lost();
            return Err(());
        };
        if sender.send(CommitSignal::Execute).is_err() {
            self.runtime_gate.mark_commit_lost();
            return Err(());
        }
        Ok(())
    }

    fn cancel(mut self) {
        self.runtime_gate.mark_commit_lost();
        if let Some(sender) = self.sender.take() {
            let _ = sender.send(CommitSignal::Cancel);
        }
    }
}

impl Drop for DeferredCommit {
    fn drop(&mut self) {
        if let Some(sender) = self.sender.take() {
            self.runtime_gate.mark_commit_lost();
            let _ = sender.send(CommitSignal::Cancel);
        }
    }
}

fn spawn_deferred_commit<F>(
    runtime_gate: Arc<UpdaterRuntimeGate>,
    action: F,
) -> Result<DeferredCommit, ()>
where
    F: FnOnce() + Send + 'static,
{
    let (sender, receiver) = mpsc::sync_channel(1);
    let worker_gate = Arc::clone(&runtime_gate);
    let worker = thread::Builder::new()
        .name("invoicehub-update-commit".to_owned())
        .spawn(move || match receiver.recv() {
            Ok(CommitSignal::Execute) => {
                if std::panic::catch_unwind(std::panic::AssertUnwindSafe(action)).is_err() {
                    worker_gate.mark_failed();
                }
            }
            Ok(CommitSignal::Cancel) | Err(_) => worker_gate.mark_commit_lost(),
        });
    if worker.is_err() {
        runtime_gate.mark_commit_lost();
        return Err(());
    }
    Ok(DeferredCommit {
        sender: Some(sender),
        runtime_gate,
    })
}

struct HostRpcReply {
    response: HostRpcResponse,
    deferred_commit: Option<DeferredCommit>,
}

impl HostRpcReply {
    fn immediate(response: HostRpcResponse) -> Self {
        Self {
            response,
            deferred_commit: None,
        }
    }

    fn deferred(response: HostRpcResponse, deferred_commit: DeferredCommit) -> Self {
        Self {
            response,
            deferred_commit: Some(deferred_commit),
        }
    }
}

enum HostRpcResponse {
    Picker(Option<String>),
    UpdateCheck { available: bool, version: String },
    UpdateInstall,
    AppIconUpdated,
}

fn write_rpc_reply<W: Write>(writer: &mut W, mut reply: HostRpcReply) -> std::io::Result<()> {
    match write_response(writer, reply.response) {
        Ok(()) => {
            if let Some(commit) = reply.deferred_commit.take() {
                commit.execute().map_err(|_| {
                    std::io::Error::new(
                        std::io::ErrorKind::BrokenPipe,
                        "private update commit dispatch was lost",
                    )
                })?;
            }
            Ok(())
        }
        Err(error) => {
            if let Some(commit) = reply.deferred_commit.take() {
                commit.cancel();
            }
            Err(error)
        }
    }
}

fn write_response<W: Write>(writer: &mut W, response: HostRpcResponse) -> std::io::Result<()> {
    let body = match response {
        HostRpcResponse::Picker(selected) => json!({
            "ok": true,
            "selected": selected.is_some(),
            "path": selected.unwrap_or_default(),
        }),
        HostRpcResponse::UpdateCheck { available, version } => json!({
            "ok": true,
            "available": available,
            "version": version,
        }),
        HostRpcResponse::UpdateInstall => json!({
            "ok": true,
        }),
        HostRpcResponse::AppIconUpdated => json!({
            "ok": true,
        }),
    }
    .to_string();
    let header = format!(
        "HTTP/1.1 200 OK\r\nContent-Type: application/json\r\nContent-Length: {}\r\nConnection: close\r\n\r\n{}",
        body.len(),
        body
    );
    writer.write_all(header.as_bytes())?;
    writer.flush()
}

fn write_rejected_response(stream: &mut TcpStream) -> std::io::Result<()> {
    const BODY: &str = "{\"ok\":false}";
    write!(
        stream,
        "HTTP/1.1 403 Forbidden\r\nContent-Type: application/json\r\nContent-Length: {}\r\nConnection: close\r\n\r\n{}",
        BODY.len(),
        BODY
    )
}

fn command_name(command: HostRpcCommand) -> &'static str {
    match command {
        HostRpcCommand::PickWatchDirectory => "pick_watch_dir",
        HostRpcCommand::PickOutboundInvoiceDirectory => "pick_outbound_invoice_dir",
        HostRpcCommand::PickOcrDirectory => "pick_ocr_directory",
        HostRpcCommand::PickOcrFile => "pick_ocr_file",
        HostRpcCommand::UpdateCheck => "update_check",
        HostRpcCommand::UpdateInstall => "update_install",
        HostRpcCommand::SetAppIcon(_) => "set_app_icon",
    }
}

fn parse_bearer_token(value: &str) -> Option<[u8; 32]> {
    let raw = value.strip_prefix("Bearer ")?;
    if raw.len() != 64
        || !raw.bytes().all(|byte| {
            byte.is_ascii_digit() || (byte.is_ascii_lowercase() && byte.is_ascii_hexdigit())
        })
    {
        return None;
    }
    let mut token = [0_u8; 32];
    for (index, pair) in raw.as_bytes().chunks_exact(2).enumerate() {
        token[index] = (hex_value(pair[0])? << 4) | hex_value(pair[1])?;
    }
    Some(token)
}

fn constant_time_equal(expected: &[u8; 32], candidate: &[u8]) -> bool {
    let mut difference = expected.len() ^ candidate.len();
    for (index, byte) in expected.iter().enumerate() {
        difference |= usize::from(*byte ^ candidate.get(index).copied().unwrap_or_default());
    }
    difference == 0
}

fn hex_encode(value: &[u8]) -> String {
    let mut output = String::with_capacity(value.len() * 2);
    for byte in value {
        output.push(hex_digit(byte >> 4));
        output.push(hex_digit(byte & 0x0f));
    }
    output
}

fn hex_digit(value: u8) -> char {
    match value {
        0..=9 => char::from(b'0' + value),
        _ => char::from(b'a' + value - 10),
    }
}

fn hex_value(value: u8) -> Option<u8> {
    match value {
        b'0'..=b'9' => Some(value - b'0'),
        b'a'..=b'f' => Some(value - b'a' + 10),
        _ => None,
    }
}

#[cfg(test)]
mod tests {
    use std::io::{self, Write};
    use std::net::{Ipv4Addr, TcpListener, TcpStream};
    use std::sync::atomic::{AtomicBool, AtomicUsize, Ordering};
    use std::sync::{mpsc, Arc, Mutex};
    use std::thread;
    use std::time::{Duration, Instant};

    use crate::app_icon::AppIconId;

    use super::{
        candidate_is_fresh, clear_candidate_if_current, read_request, spawn_deferred_commit,
        update_artifact_id, write_rpc_reply, CommitSignal, DeferredCommit,
        HostRpcAuthorizationError, HostRpcCommand, HostRpcReply, HostRpcResponse,
        UpdaterRuntimeGate, UpdaterRuntimeState, HOST_RPC_ORIGIN, HOST_RPC_PATH,
        UPDATE_CANDIDATE_TTL,
    };

    struct RecordingWriter {
        bytes: Vec<u8>,
        flushed: Arc<AtomicBool>,
        fail_flush: bool,
    }

    impl Write for RecordingWriter {
        fn write(&mut self, buffer: &[u8]) -> io::Result<usize> {
            self.bytes.extend_from_slice(buffer);
            Ok(buffer.len())
        }

        fn flush(&mut self) -> io::Result<()> {
            if self.fail_flush {
                return Err(io::Error::new(io::ErrorKind::BrokenPipe, "test failure"));
            }
            self.flushed.store(true, Ordering::Release);
            Ok(())
        }
    }

    fn reserved_runtime_gate() -> Arc<UpdaterRuntimeGate> {
        let gate = Arc::new(UpdaterRuntimeGate::new(true));
        assert!(gate.begin_activation().expect("activation begins"));
        gate.finish_activation().expect("activation completes");
        gate.reserve_commit().expect("commit is reserved");
        gate
    }

    #[test]
    fn parser_accepts_standard_urllib_headers_but_requires_an_exact_request_line() {
        let listener = TcpListener::bind((Ipv4Addr::LOCALHOST, 0)).expect("bind test listener");
        let address = listener.local_addr().expect("test address");
        let request = format!(
            "POST {HOST_RPC_PATH} HTTP/1.1\r\nHost: 127.0.0.1:{}\r\nUser-Agent: Python-urllib/3.14\r\nAccept-Encoding: identity\r\nConnection: close\r\nOrigin: {HOST_RPC_ORIGIN}\r\nAuthorization: Bearer {}\r\nContent-Type: application/json\r\nContent-Length: 28\r\n\r\n{{\"command\":\"pick_watch_dir\"}}",
            address.port(),
            "a".repeat(64),
        );
        let sender = thread::spawn(move || {
            let mut stream = TcpStream::connect(address).expect("connect test listener");
            stream.write_all(request.as_bytes()).expect("send request");
        });
        let (mut stream, _) = listener.accept().expect("accept request");
        let parsed = read_request(&mut stream).expect("urllib-shaped request is accepted");
        sender.join().expect("sender exits");

        assert_eq!(parsed.method, "POST");
        assert_eq!(parsed.path, HOST_RPC_PATH);
        assert_eq!(parsed.origin, HOST_RPC_ORIGIN);

        let invalid_listener =
            TcpListener::bind((Ipv4Addr::LOCALHOST, 0)).expect("bind invalid listener");
        let invalid_address = invalid_listener.local_addr().expect("invalid address");
        let invalid_sender = thread::spawn(move || {
            let mut stream = TcpStream::connect(invalid_address).expect("connect invalid listener");
            stream
                .write_all(b"POST /v1/host-rpc HTTP/1.1 extra\r\nContent-Length: 0\r\n\r\n")
                .expect("send invalid request");
        });
        let (mut invalid_stream, _) = invalid_listener.accept().expect("accept invalid request");
        assert!(read_request(&mut invalid_stream).is_err());
        invalid_sender.join().expect("invalid sender exits");
    }

    #[test]
    fn updater_commands_are_fixed_enums_with_no_metadata_payload() {
        assert_eq!(
            HostRpcCommand::from_payload(br#"{"command":"update_check"}"#),
            Ok(HostRpcCommand::UpdateCheck)
        );
        assert_eq!(
            HostRpcCommand::from_payload(br#"{"command":"update_install"}"#),
            Ok(HostRpcCommand::UpdateInstall)
        );
        for payload in [
            br#"{"command":"update_check","url":"https://attacker.invalid"}"#.as_slice(),
            br#"{"command":"update_install","signature":"candidate"}"#.as_slice(),
            br#"{"command":"run_updater"}"#.as_slice(),
        ] {
            assert_eq!(
                HostRpcCommand::from_payload(payload),
                Err(HostRpcAuthorizationError::CommandRejected)
            );
        }
    }

    #[test]
    fn app_icon_command_accepts_only_one_bundled_icon_without_extra_metadata() {
        assert_eq!(
            HostRpcCommand::from_payload(br#"{"command":"set_app_icon","icon":"teal"}"#),
            Ok(HostRpcCommand::SetAppIcon(AppIconId::Teal))
        );
        for payload in [
            br#"{"command":"set_app_icon"}"#.as_slice(),
            br#"{"command":"set_app_icon","icon":"unbundled"}"#.as_slice(),
            br#"{"command":"set_app_icon","icon":"teal","path":"/tmp/icon.png"}"#.as_slice(),
        ] {
            assert_eq!(
                HostRpcCommand::from_payload(payload),
                Err(HostRpcAuthorizationError::CommandRejected)
            );
        }
    }

    #[test]
    fn updater_candidate_expires_before_install() {
        let checked_at = Instant::now();

        assert!(candidate_is_fresh(checked_at, checked_at));
        assert!(candidate_is_fresh(
            checked_at,
            checked_at + UPDATE_CANDIDATE_TTL
        ));
        assert!(!candidate_is_fresh(
            checked_at,
            checked_at + UPDATE_CANDIDATE_TTL + Duration::from_millis(1)
        ));
    }

    #[test]
    fn candidate_expiry_clears_only_the_matching_generation() {
        let candidate = Mutex::new(Some((8_u64, "newer")));

        assert!(!clear_candidate_if_current(&candidate, 7).expect("expiry check succeeds"));
        assert_eq!(
            candidate
                .lock()
                .expect("candidate lock")
                .as_ref()
                .map(|(_, value)| *value),
            Some("newer")
        );
        assert!(clear_candidate_if_current(&candidate, 8).expect("matching expiry clears"));
        assert!(candidate.lock().expect("candidate lock").is_none());
    }

    #[test]
    fn successful_install_response_is_flushed_before_private_commit_runs() {
        let gate = reserved_runtime_gate();
        let flushed = Arc::new(AtomicBool::new(false));
        let (observed_sender, observed_receiver) = mpsc::sync_channel(1);
        let action_flushed = Arc::clone(&flushed);
        let commit = spawn_deferred_commit(Arc::clone(&gate), move || {
            observed_sender
                .send(action_flushed.load(Ordering::Acquire))
                .expect("record flush state");
        })
        .expect("commit worker starts");
        let mut writer = RecordingWriter {
            bytes: Vec::new(),
            flushed,
            fail_flush: false,
        };

        write_rpc_reply(
            &mut writer,
            HostRpcReply::deferred(HostRpcResponse::UpdateInstall, commit),
        )
        .expect("response and commit dispatch succeed");

        assert!(observed_receiver
            .recv_timeout(Duration::from_secs(1))
            .expect("commit runs"));
        assert_eq!(gate.state(), UpdaterRuntimeState::CommitExecuting);
        assert!(String::from_utf8(writer.bytes)
            .expect("response is UTF-8")
            .ends_with("{\"ok\":true}"));
    }

    #[test]
    fn failed_response_flush_cancels_commit_and_records_commit_lost() {
        let gate = reserved_runtime_gate();
        let action_calls = Arc::new(AtomicUsize::new(0));
        let worker_calls = Arc::clone(&action_calls);
        let commit = spawn_deferred_commit(Arc::clone(&gate), move || {
            worker_calls.fetch_add(1, Ordering::AcqRel);
        })
        .expect("commit worker starts");
        let mut writer = RecordingWriter {
            bytes: Vec::new(),
            flushed: Arc::new(AtomicBool::new(false)),
            fail_flush: true,
        };

        assert!(write_rpc_reply(
            &mut writer,
            HostRpcReply::deferred(HostRpcResponse::UpdateInstall, commit),
        )
        .is_err());

        assert_eq!(gate.state(), UpdaterRuntimeState::CommitLost);
        assert_eq!(action_calls.load(Ordering::Acquire), 0);
    }

    #[test]
    fn lost_execute_latch_never_runs_an_action_and_records_commit_lost() {
        let gate = reserved_runtime_gate();
        let (sender, receiver) = mpsc::sync_channel::<CommitSignal>(1);
        drop(receiver);
        let commit = DeferredCommit {
            sender: Some(sender),
            runtime_gate: Arc::clone(&gate),
        };
        let mut writer = RecordingWriter {
            bytes: Vec::new(),
            flushed: Arc::new(AtomicBool::new(false)),
            fail_flush: false,
        };

        assert!(write_rpc_reply(
            &mut writer,
            HostRpcReply::deferred(HostRpcResponse::UpdateInstall, commit),
        )
        .is_err());
        assert_eq!(gate.state(), UpdaterRuntimeState::CommitLost);
    }

    #[test]
    fn missing_execute_latch_records_commit_lost() {
        let gate = reserved_runtime_gate();
        let commit = DeferredCommit {
            sender: None,
            runtime_gate: Arc::clone(&gate),
        };

        assert!(commit.execute().is_err());
        assert_eq!(gate.state(), UpdaterRuntimeState::CommitLost);
    }

    #[test]
    fn disabled_runtime_never_activates_or_reserves_a_commit() {
        let gate = UpdaterRuntimeGate::new(false);

        assert!(!gate.begin_activation().expect("disabled is inert"));
        assert_eq!(gate.state(), UpdaterRuntimeState::Disabled);
        assert!(gate.require_ready().is_err());
        assert!(gate.reserve_commit().is_err());
    }

    #[test]
    fn reserved_commit_rejects_concurrent_update_operations() {
        let gate = reserved_runtime_gate();

        assert!(gate.require_ready().is_err());
        assert!(gate.reserve_commit().is_err());
        assert!(gate.blocks_normal_quit());
    }

    #[test]
    fn artifact_identity_binds_all_immutable_update_metadata() {
        let baseline = update_artifact_id(
            "0.3.0-alpha.2",
            "darwin",
            "https://updates.invalid/invoicehub.tar.gz",
            "signed-metadata",
        );

        assert_eq!(
            baseline,
            update_artifact_id(
                "0.3.0-alpha.2",
                "darwin",
                "https://updates.invalid/invoicehub.tar.gz",
                "signed-metadata",
            )
        );
        assert_ne!(
            baseline,
            update_artifact_id(
                "0.3.0-alpha.2",
                "darwin",
                "https://updates.invalid/invoicehub.tar.gz",
                "tampered-signature",
            )
        );
    }
}
