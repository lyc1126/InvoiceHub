//! Fixed-port backend ownership and strict identity checks for the desktop host.

use std::collections::{BTreeMap, BTreeSet};
use std::env;
use std::error::Error;
use std::fmt;
use std::fs;
use std::io::{Read, Write};
use std::net::{IpAddr, Ipv4Addr, SocketAddr, TcpListener, TcpStream};
use std::path::{Component, Path, PathBuf};
use std::process::{Child, Command};
use std::sync::atomic::{AtomicBool, Ordering};
use std::sync::{Arc, Mutex};
use std::thread::{self, JoinHandle};
use std::time::{Duration, Instant};

use hmac::{Hmac, Mac};
use serde_json::{Map, Value};
use sha2::{Digest, Sha256};

use crate::host_rpc::{HostRpcServer, HostRpcServerError};
use crate::{FIXED_BACKEND_HOST, FIXED_BACKEND_PORT};

pub const BACKEND_BUNDLE_MANIFEST_FILE: &str = "invoicehub-desktop-host.json";
pub const HEALTH_PATH: &str = "/api/v1/health";
pub const OPENAPI_PATH: &str = "/openapi.json";
pub const PREFERENCES_PATH: &str = "/api/v1/preferences";
pub const BRIDGE_STATUS_PATH: &str = "/api/v1/bridge/status";
pub const BRIDGE_STOP_PATH: &str = "/api/v1/bridge/stop";
pub const SERVER_SHUTDOWN_PATH: &str = "/api/v1/server/shutdown";
pub const DESKTOP_HOST_PROOF_PATH: &str = "/api/v1/internal/desktop-host-proof";
pub const DESKTOP_HOST_CHALLENGE_HEADER: &str = "X-InvoiceHub-Desktop-Host-Challenge";
pub const DESKTOP_HOST_RESPONSE_HEADER: &str = "x-invoicehub-desktop-host-response";
pub const DESKTOP_HOST_SECRET_ENV: &str = "INVOICE_HUB_DESKTOP_HOST_SECRET";
pub const DESKTOP_HOST_MODE_ENV: &str = "INVOICE_HUB_DESKTOP_HOST";
pub const DESKTOP_UPDATER_ENABLED_ENV: &str = "INVOICE_HUB_DESKTOP_UPDATER_ENABLED";
pub const DEVELOPMENT_STATE_ROOT_ENV: &str = "INVOICE_HUB_DEV_STATE_ROOT";
const MAX_HTTP_RESPONSE_BYTES: usize = 128 * 1024;
const HTTP_TIMEOUT: Duration = Duration::from_secs(5);
const BACKEND_STARTUP_TIMEOUT: Duration = Duration::from_secs(20);
const BACKEND_SHUTDOWN_TIMEOUT: Duration = Duration::from_secs(10);
const BACKEND_RETRY_INTERVAL: Duration = Duration::from_millis(100);
const BACKEND_LIVENESS_POLL_INTERVAL: Duration = Duration::from_millis(100);
const OWNERSHIP_SECRET_BYTES: usize = 32;
const DESKTOP_STATE_DIRECTORY: &str = "InvoiceHub";
const DESKTOP_CONFIG_RELATIVE_PATH: &str = "config/app.local.json";
const DESKTOP_RUNTIME_RELATIVE_PATH: &str = "runtime";
const BUILD_MANIFEST_FILE: &str = "invoice-hub-build.json";
const PACKAGE_MANIFEST_FILE: &str = "invoice-hub-package.json";
// The packager sets this while compiling the signed desktop host from the staged manifest.
// A checkout intentionally has no value and therefore remains non-runnable.
const BUNDLE_MANIFEST_SHA256: Option<&str> = option_env!("INVOICE_HUB_BUNDLE_MANIFEST_SHA256");

type OwnershipHmac = Hmac<Sha256>;

const REQUIRED_OPENAPI_OPERATIONS: &[(&str, &str)] = &[
    ("/api/v1/health", "get"),
    ("/api/v1/settings/pick-watch-dir", "post"),
    ("/api/v1/documents/pick-outbound-dir", "post"),
    ("/api/v1/ocr/pick-file", "post"),
    ("/api/v1/ocr/pick-folder", "post"),
    ("/api/v1/update/check", "post"),
    ("/api/v1/update/install", "post"),
    (SERVER_SHUTDOWN_PATH, "post"),
    (BRIDGE_STATUS_PATH, "get"),
    (BRIDGE_STOP_PATH, "post"),
];

#[derive(Clone, Debug, PartialEq, Eq)]
pub struct ExpectedBackendIdentity {
    pub bundle_profile: BundleProfile,
    pub build_id: String,
    pub api_contract_version: String,
    pub bookkeeping_protocol_version: String,
    pub capabilities: Vec<String>,
    pub product_version: String,
    pub package_id: String,
    pub platform: String,
    pub architecture: String,
    pub package_type: String,
    pub config_path: PathBuf,
    pub runtime_dir: PathBuf,
}

#[derive(Clone, Copy, Debug, PartialEq, Eq)]
pub enum BundleProfile {
    Development,
    Release,
}

#[derive(Clone, Debug, PartialEq, Eq)]
pub struct BackendHealth {
    pub ok: bool,
    pub pid: u32,
    pub build_manifest_present: bool,
    pub build_manifest_valid: bool,
    pub package_manifest_present: bool,
    pub package_manifest_valid: bool,
    pub build_id: String,
    pub api_contract_version: String,
    pub bookkeeping_protocol_version: String,
    pub capabilities: Vec<String>,
    pub product_version: String,
    pub package_id: String,
    pub platform: String,
    pub architecture: String,
    pub package_type: String,
    pub config_path: PathBuf,
    pub runtime_dir: PathBuf,
}

#[derive(Clone, Copy, Debug, PartialEq, Eq)]
pub enum StartupSurface {
    Desktop,
    Browser,
}

#[derive(Clone, Copy, Debug, PartialEq, Eq)]
pub enum HandshakeError {
    BackendNotReady,
    PidMismatch,
    OwnershipProofMismatch,
    ManifestMismatch,
    IdentityMismatch,
    OpenApiMismatch,
}

impl fmt::Display for HandshakeError {
    fn fmt(&self, formatter: &mut fmt::Formatter<'_>) -> fmt::Result {
        let message = match self {
            Self::BackendNotReady => "the backend did not report ready",
            Self::PidMismatch => "the backend PID does not match the child process",
            Self::OwnershipProofMismatch => {
                "the backend did not prove host-issued lifecycle ownership"
            }
            Self::ManifestMismatch => "the backend build or package manifest is not valid",
            Self::IdentityMismatch => "the backend identity does not match the desktop bundle",
            Self::OpenApiMismatch => "the backend OpenAPI contract is incomplete",
        };
        formatter.write_str(message)
    }
}

impl Error for HandshakeError {}

#[derive(Debug)]
pub enum BackendError {
    FixedPortRequiresLoopback,
    FixedPortUnavailable,
    DesktopStateUnavailable,
    BundleManifestMissing,
    BundleManifestInvalid,
    BackendSpawnFailed,
    RandomUnavailable,
    ProbeFailed,
    DesktopSurfaceUnavailable,
    StartupSurfaceInvalid,
    GracefulShutdownFailed,
    GracefulShutdownTimedOut,
    BackendTerminationFailed,
    Handshake(HandshakeError),
    HostRpc(HostRpcServerError),
}

impl fmt::Display for BackendError {
    fn fmt(&self, formatter: &mut fmt::Formatter<'_>) -> fmt::Result {
        let message = match self {
            Self::FixedPortRequiresLoopback => {
                "InvoiceHub requires the fixed IPv4 loopback backend address"
            }
            Self::FixedPortUnavailable => "InvoiceHub backend port is already occupied",
            Self::DesktopStateUnavailable => "InvoiceHub user state directory is unavailable",
            Self::BundleManifestMissing => "InvoiceHub desktop bundle manifest is missing",
            Self::BundleManifestInvalid => "InvoiceHub desktop bundle manifest is invalid",
            Self::BackendSpawnFailed => "InvoiceHub backend could not be started",
            Self::RandomUnavailable => {
                "InvoiceHub could not create private backend ownership material"
            }
            Self::ProbeFailed => "InvoiceHub backend probe failed",
            Self::DesktopSurfaceUnavailable => {
                "InvoiceHub desktop surface is unavailable for this backend"
            }
            Self::StartupSurfaceInvalid => "InvoiceHub backend startup surface response is invalid",
            Self::GracefulShutdownFailed => {
                "InvoiceHub backend did not accept the requested graceful shutdown"
            }
            Self::GracefulShutdownTimedOut => {
                "InvoiceHub backend did not exit after the requested graceful shutdown"
            }
            Self::BackendTerminationFailed => {
                "InvoiceHub backend could not be terminated before the desktop host exits"
            }
            Self::Handshake(error) => {
                return write!(formatter, "InvoiceHub backend handshake failed: {error}")
            }
            Self::HostRpc(error) => {
                return write!(formatter, "InvoiceHub Host RPC setup failed: {error}")
            }
        };
        formatter.write_str(message)
    }
}

impl Error for BackendError {}

impl From<HandshakeError> for BackendError {
    fn from(error: HandshakeError) -> Self {
        Self::Handshake(error)
    }
}

impl From<HostRpcServerError> for BackendError {
    fn from(error: HostRpcServerError) -> Self {
        Self::HostRpc(error)
    }
}

impl ExpectedBackendIdentity {
    pub fn validate_health(
        &self,
        health: &BackendHealth,
        expected_pid: u32,
    ) -> Result<(), HandshakeError> {
        if !health.ok {
            return Err(HandshakeError::BackendNotReady);
        }
        if health.pid != expected_pid {
            return Err(HandshakeError::PidMismatch);
        }
        let package_manifest_matches = match self.bundle_profile {
            BundleProfile::Development => {
                !health.package_manifest_present && !health.package_manifest_valid
            }
            BundleProfile::Release => {
                health.package_manifest_present && health.package_manifest_valid
            }
        };
        if !health.build_manifest_present
            || !health.build_manifest_valid
            || !package_manifest_matches
        {
            return Err(HandshakeError::ManifestMismatch);
        }
        if health.build_id != self.build_id
            || health.api_contract_version != self.api_contract_version
            || health.bookkeeping_protocol_version != self.bookkeeping_protocol_version
            || health.capabilities != self.capabilities
            || health.product_version != self.product_version
            || health.package_id != self.package_id
            || health.platform != self.platform
            || health.architecture != self.architecture
            || health.package_type != self.package_type
            || health.config_path != self.config_path
            || health.runtime_dir != self.runtime_dir
        {
            return Err(HandshakeError::IdentityMismatch);
        }
        Ok(())
    }
}

impl BackendHealth {
    pub fn from_json(value: &Value) -> Result<Self, BackendError> {
        let fields = value.as_object().ok_or(BackendError::ProbeFailed)?;
        Ok(Self {
            ok: required_bool(fields, "ok")?,
            pid: required_u32(fields, "pid")?,
            build_manifest_present: required_bool(fields, "build_manifest_present")?,
            build_manifest_valid: required_bool(fields, "build_manifest_valid")?,
            package_manifest_present: required_bool(fields, "package_manifest_present")?,
            package_manifest_valid: required_bool(fields, "package_manifest_valid")?,
            build_id: required_text(fields, "build_id")?,
            api_contract_version: required_text(fields, "api_contract_version")?,
            bookkeeping_protocol_version: required_text(fields, "bookkeeping_protocol_version")?,
            capabilities: required_string_list(fields, "capabilities")?,
            product_version: required_text(fields, "product_version")?,
            package_id: required_text(fields, "package_id")?,
            platform: required_text(fields, "platform")?,
            architecture: required_text(fields, "architecture")?,
            package_type: required_text(fields, "package_type")?,
            config_path: PathBuf::from(required_text(fields, "config_path")?),
            runtime_dir: PathBuf::from(required_text(fields, "runtime_dir")?),
        })
    }
}

#[derive(Clone, Debug)]
pub struct BackendBundleManifest {
    profile: BundleProfile,
    program: PathBuf,
    backend_root: PathBuf,
    args: Vec<String>,
    expected_identity: ExpectedBackendIdentity,
    updater: UpdaterBundleConfig,
}

impl BackendBundleManifest {
    pub fn profile(&self) -> BundleProfile {
        self.profile
    }

    pub fn expected_identity(&self) -> &ExpectedBackendIdentity {
        &self.expected_identity
    }

    pub fn updater(&self) -> &UpdaterBundleConfig {
        &self.updater
    }
}

#[derive(Clone, Debug, PartialEq, Eq)]
pub struct UpdaterBundleConfig {
    enabled: bool,
    endpoint: Option<String>,
    public_key: Option<String>,
}

#[derive(Clone, Copy, Debug, PartialEq, Eq)]
pub enum DesktopStatePlatform {
    Windows,
    Macos,
}

#[derive(Clone, Debug, PartialEq, Eq)]
pub struct DesktopStatePaths {
    pub root: PathBuf,
    pub config_path: PathBuf,
    pub runtime_dir: PathBuf,
}

impl UpdaterBundleConfig {
    pub fn enabled(&self) -> bool {
        self.enabled
    }

    pub fn endpoint(&self) -> Option<&str> {
        self.endpoint.as_deref()
    }

    pub fn public_key(&self) -> Option<&str> {
        self.public_key.as_deref()
    }
}

pub fn desktop_state_paths_for(
    platform: DesktopStatePlatform,
    local_app_data: Option<&Path>,
    home: Option<&Path>,
) -> Result<DesktopStatePaths, BackendError> {
    let base = match platform {
        DesktopStatePlatform::Windows => local_app_data,
        DesktopStatePlatform::Macos => home,
    }
    .filter(|path| path.is_absolute())
    .ok_or(BackendError::DesktopStateUnavailable)?;
    let root = match platform {
        DesktopStatePlatform::Windows => base.join(DESKTOP_STATE_DIRECTORY),
        DesktopStatePlatform::Macos => base
            .join("Library")
            .join("Application Support")
            .join(DESKTOP_STATE_DIRECTORY),
    };
    Ok(DesktopStatePaths {
        config_path: root.join(DESKTOP_CONFIG_RELATIVE_PATH),
        runtime_dir: root.join(DESKTOP_RUNTIME_RELATIVE_PATH),
        root,
    })
}

fn desktop_state_paths() -> Result<DesktopStatePaths, BackendError> {
    #[cfg(target_os = "windows")]
    {
        let local_app_data = env::var_os("LOCALAPPDATA").map(PathBuf::from);
        return desktop_state_paths_for(
            DesktopStatePlatform::Windows,
            local_app_data.as_deref(),
            None,
        );
    }
    #[cfg(target_os = "macos")]
    {
        let home = env::var_os("HOME").map(PathBuf::from);
        return desktop_state_paths_for(DesktopStatePlatform::Macos, None, home.as_deref());
    }
    #[cfg(not(any(target_os = "windows", target_os = "macos")))]
    {
        Err(BackendError::DesktopStateUnavailable)
    }
}

pub fn fixed_backend_socket_addr() -> SocketAddr {
    SocketAddr::new(IpAddr::V4(Ipv4Addr::LOCALHOST), FIXED_BACKEND_PORT)
}

pub fn assert_loopback_port_available(address: SocketAddr) -> Result<(), BackendError> {
    if address.ip() != IpAddr::V4(Ipv4Addr::LOCALHOST) {
        return Err(BackendError::FixedPortRequiresLoopback);
    }
    TcpListener::bind(address)
        .map(|listener| drop(listener))
        .map_err(|_| BackendError::FixedPortUnavailable)
}

pub fn assert_fixed_backend_port_available() -> Result<(), BackendError> {
    assert_loopback_port_available(fixed_backend_socket_addr())
}

pub fn bundle_root_for_executable(executable: &Path) -> Result<PathBuf, BackendError> {
    let executable_dir = executable
        .parent()
        .ok_or(BackendError::BundleManifestMissing)?;
    if executable_dir.file_name().and_then(|value| value.to_str()) == Some("MacOS") {
        let contents_dir = executable_dir
            .parent()
            .filter(|path| path.file_name().and_then(|value| value.to_str()) == Some("Contents"))
            .ok_or(BackendError::BundleManifestMissing)?;
        return Ok(contents_dir.join("Resources"));
    }
    Ok(executable_dir.to_path_buf())
}

pub fn default_bundle_root() -> Result<PathBuf, BackendError> {
    let executable = env::current_exe().map_err(|_| BackendError::BundleManifestMissing)?;
    bundle_root_for_executable(&executable)
}

pub fn load_bundle_manifest(bundle_root: &Path) -> Result<BackendBundleManifest, BackendError> {
    let default_state_paths = desktop_state_paths()?;
    let manifest = load_bundle_manifest_for_state(bundle_root, &default_state_paths)?;
    let development_root = env::var_os(DEVELOPMENT_STATE_ROOT_ENV).map(PathBuf::from);
    let state_paths = state_paths_for_bundle_profile(
        manifest.profile,
        bundle_root,
        &default_state_paths,
        development_root.as_deref(),
    )?;
    if state_paths == default_state_paths {
        return Ok(manifest);
    }
    load_bundle_manifest_for_state(bundle_root, &state_paths)
}

fn load_bundle_manifest_for_state(
    bundle_root: &Path,
    state_paths: &DesktopStatePaths,
) -> Result<BackendBundleManifest, BackendError> {
    let manifest_path = bundle_root.join(BACKEND_BUNDLE_MANIFEST_FILE);
    let raw = match fs::read(&manifest_path) {
        Ok(raw) => raw,
        Err(error) if error.kind() == std::io::ErrorKind::NotFound => {
            return Err(BackendError::BundleManifestMissing)
        }
        Err(_) => return Err(BackendError::BundleManifestInvalid),
    };
    if !compiled_bundle_manifest_hash_matches(&raw) {
        return Err(BackendError::BundleManifestInvalid);
    }
    let value: Value =
        serde_json::from_slice(&raw).map_err(|_| BackendError::BundleManifestInvalid)?;
    let fields = value
        .as_object()
        .ok_or(BackendError::BundleManifestInvalid)?;
    if fields.get("schema_version").and_then(Value::as_u64) != Some(3) {
        return Err(BackendError::BundleManifestInvalid);
    }
    let profile = match required_text(fields, "profile")
        .map_err(|_| BackendError::BundleManifestInvalid)?
        .as_str()
    {
        "development" => BundleProfile::Development,
        "release" => BundleProfile::Release,
        _ => return Err(BackendError::BundleManifestInvalid),
    };
    let program_value = required_text(fields, "backend_program")
        .map_err(|_| BackendError::BundleManifestInvalid)?;
    let program = bundle_relative_file(bundle_root, &program_value)?;
    let program_sha256 = required_text(fields, "backend_program_sha256")
        .map_err(|_| BackendError::BundleManifestInvalid)?;
    if !file_sha256_matches(&program, &program_sha256) {
        return Err(BackendError::BundleManifestInvalid);
    }
    let backend_root_value =
        required_text(fields, "backend_root").map_err(|_| BackendError::BundleManifestInvalid)?;
    let backend_root = bundle_relative_directory(bundle_root, &backend_root_value)?;
    validate_backend_root(&backend_root, profile)?;
    let args = bundle_arguments(fields, &backend_root, state_paths)?;
    let expected_fields = fields
        .get("expected_identity")
        .and_then(Value::as_object)
        .ok_or(BackendError::BundleManifestInvalid)?;
    let expected_identity = identity_from_json(expected_fields, state_paths, profile)?;
    let updater_fields = fields
        .get("updater")
        .and_then(Value::as_object)
        .ok_or(BackendError::BundleManifestInvalid)?;
    let updater = updater_from_json(updater_fields, profile)?;
    Ok(BackendBundleManifest {
        profile,
        program,
        backend_root,
        args,
        expected_identity,
        updater,
    })
}

pub fn probe_backend(
    expected_identity: &ExpectedBackendIdentity,
    expected_pid: u32,
    ownership_secret: &[u8; OWNERSHIP_SECRET_BYTES],
) -> Result<BackendHealth, BackendError> {
    let challenge = generate_ownership_challenge()?;
    let proof_response = local_get_with_header(
        DESKTOP_HOST_PROOF_PATH,
        DESKTOP_HOST_CHALLENGE_HEADER,
        &challenge,
    )?;
    let response = proof_response
        .headers
        .get(DESKTOP_HOST_RESPONSE_HEADER)
        .map(String::as_str)
        .unwrap_or_default();
    if proof_response.status != 204
        || !ownership_response_matches(ownership_secret, &challenge, response)
    {
        return Err(HandshakeError::OwnershipProofMismatch.into());
    }
    let health_response = local_get(HEALTH_PATH)?;
    if health_response.status != 200 {
        return Err(BackendError::ProbeFailed);
    }
    let health_value: Value =
        serde_json::from_slice(&health_response.body).map_err(|_| BackendError::ProbeFailed)?;
    let health = BackendHealth::from_json(&health_value)?;
    expected_identity.validate_health(&health, expected_pid)?;

    let index_response = local_get("/")?;
    if index_response.status != 200 {
        return Err(BackendError::ProbeFailed);
    }
    let openapi_response = local_get(OPENAPI_PATH)?;
    if openapi_response.status != 200 {
        return Err(BackendError::ProbeFailed);
    }
    let openapi: Value =
        serde_json::from_slice(&openapi_response.body).map_err(|_| BackendError::ProbeFailed)?;
    validate_openapi_routes(&openapi)?;
    Ok(health)
}

pub fn probe_backend_with_retry(
    expected_identity: &ExpectedBackendIdentity,
    expected_pid: u32,
    ownership_secret: &[u8; OWNERSHIP_SECRET_BYTES],
) -> Result<BackendHealth, BackendError> {
    retry_probe(
        || probe_backend(expected_identity, expected_pid, ownership_secret),
        BACKEND_STARTUP_TIMEOUT,
    )
}

pub fn load_startup_surface() -> Result<StartupSurface, BackendError> {
    let response = local_get(PREFERENCES_PATH)?;
    if response.status != 200 {
        return Err(BackendError::StartupSurfaceInvalid);
    }
    let value: Value =
        serde_json::from_slice(&response.body).map_err(|_| BackendError::StartupSurfaceInvalid)?;
    parse_startup_surface(&value)
}

pub fn parse_startup_surface(value: &Value) -> Result<StartupSurface, BackendError> {
    let fields = value
        .as_object()
        .ok_or(BackendError::StartupSurfaceInvalid)?;
    if fields.get("ok").and_then(Value::as_bool) != Some(true) {
        return Err(BackendError::StartupSurfaceInvalid);
    }
    let preferences = fields
        .get("preferences")
        .and_then(Value::as_object)
        .ok_or(BackendError::StartupSurfaceInvalid)?;
    let allowed = fields
        .get("allowed")
        .and_then(Value::as_object)
        .ok_or(BackendError::StartupSurfaceInvalid)?;
    match allowed.get("desktop_available").and_then(Value::as_bool) {
        Some(true) => {}
        Some(false) => return Err(BackendError::DesktopSurfaceUnavailable),
        None => return Err(BackendError::StartupSurfaceInvalid),
    }
    match preferences.get("startup_surface").and_then(Value::as_str) {
        Some("desktop") => Ok(StartupSurface::Desktop),
        Some("browser") => Ok(StartupSurface::Browser),
        _ => Err(BackendError::StartupSurfaceInvalid),
    }
}

pub fn validate_openapi_routes(openapi: &Value) -> Result<(), HandshakeError> {
    let Some(paths) = openapi.get("paths").and_then(Value::as_object) else {
        return Err(HandshakeError::OpenApiMismatch);
    };
    if REQUIRED_OPENAPI_OPERATIONS.iter().all(|(path, method)| {
        paths
            .get(*path)
            .and_then(Value::as_object)
            .and_then(|operations| operations.get(*method))
            .is_some_and(Value::is_object)
    }) {
        Ok(())
    } else {
        Err(HandshakeError::OpenApiMismatch)
    }
}

pub struct BackendHost {
    child: Arc<Mutex<Child>>,
    child_pid: u32,
    expected_identity: ExpectedBackendIdentity,
    ownership_verified: Arc<AtomicBool>,
    liveness_shutdown: Arc<AtomicBool>,
    liveness_worker: Mutex<Option<JoinHandle<()>>>,
    startup_surface: StartupSurface,
    _host_rpc: HostRpcServer,
}

#[derive(Clone, Copy, Debug, PartialEq, Eq)]
pub enum BackendShutdownOutcome {
    Graceful,
    Forced,
}

impl BackendHost {
    pub fn launch(
        manifest: BackendBundleManifest,
        app_handle: tauri::AppHandle<tauri::Wry>,
    ) -> Result<Self, BackendError> {
        assert_fixed_backend_port_available()?;
        let ownership_verified = Arc::new(AtomicBool::new(false));
        let host_rpc = HostRpcServer::start(
            app_handle,
            Arc::clone(&ownership_verified),
            manifest.updater.endpoint().map(str::to_owned),
        )?;
        let ownership_secret = generate_ownership_secret()?;

        let mut command = Command::new(&manifest.program);
        command.args(&manifest.args);
        command.current_dir(&manifest.backend_root);
        command.env_remove(DEVELOPMENT_STATE_ROOT_ENV);
        command.env_remove("PYTHONPATH");
        command.env("PYTHONPATH", manifest.backend_root.join("src"));
        command.env("PYTHONNOUSERSITE", "1");
        command.env("PYTHONDONTWRITEBYTECODE", "1");
        command.env("INVOICE_HUB_HOST_RPC_URL", host_rpc.endpoint_url());
        command.env("INVOICE_HUB_HOST_RPC_TOKEN", host_rpc.token_for_backend());
        command.env(DESKTOP_HOST_SECRET_ENV, hex_encode(&ownership_secret));
        command.env(DESKTOP_HOST_MODE_ENV, "tauri");
        command.env(
            DESKTOP_UPDATER_ENABLED_ENV,
            if manifest.updater.enabled() { "1" } else { "0" },
        );
        let child = command
            .spawn()
            .map_err(|_| BackendError::BackendSpawnFailed)?;
        let child_pid = child.id();
        let child = Arc::new(Mutex::new(child));

        if let Err(error) =
            probe_backend_with_retry(&manifest.expected_identity, child_pid, &ownership_secret)
        {
            if let Ok(mut child) = child.lock() {
                let _ = child.kill();
                let _ = child.wait();
            }
            return Err(error);
        }
        let startup_surface = match load_startup_surface() {
            Ok(surface) => surface,
            Err(error) => {
                if let Ok(mut child) = child.lock() {
                    let _ = child.kill();
                    let _ = child.wait();
                }
                return Err(error);
            }
        };
        if let Err(error) = revalidate_backend_after_preferences(
            || child_is_running(&child),
            || probe_backend(&manifest.expected_identity, child_pid, &ownership_secret).map(|_| ()),
        ) {
            if let Ok(mut child) = child.lock() {
                let _ = child.kill();
                let _ = child.wait();
            }
            return Err(error);
        }
        let liveness_shutdown = Arc::new(AtomicBool::new(false));
        // Arm before the watcher starts so an already-exited child cannot re-enable Host RPC.
        ownership_verified.store(true, Ordering::Release);
        let liveness_worker = spawn_backend_liveness_watcher(
            Arc::clone(&child),
            Arc::clone(&ownership_verified),
            Arc::clone(&liveness_shutdown),
        );
        Ok(Self {
            child,
            child_pid,
            expected_identity: manifest.expected_identity,
            ownership_verified,
            liveness_shutdown,
            liveness_worker: Mutex::new(Some(liveness_worker)),
            startup_surface,
            _host_rpc: host_rpc,
        })
    }

    pub fn revalidate_owned_health(&self, health: &BackendHealth) -> Result<(), HandshakeError> {
        let result = if child_is_running(&self.child) {
            self.expected_identity
                .validate_health(health, self.child_pid)
        } else {
            Err(HandshakeError::BackendNotReady)
        };
        if result.is_err() {
            self.ownership_verified.store(false, Ordering::Release);
        }
        result
    }

    pub fn owns_backend(&self) -> bool {
        self.ownership_verified.load(Ordering::Acquire)
    }

    pub fn shutdown_keep_monitor(&self) -> Result<(), BackendError> {
        if !self.owns_backend() || !child_is_running(&self.child) {
            return Err(BackendError::GracefulShutdownFailed);
        }

        // The desktop host is about to exit. Revoke private Host RPC before asking the
        // child to perform its structured shutdown and release its PID state.
        self.ownership_verified.store(false, Ordering::Release);
        let response = local_post_json(
            SERVER_SHUTDOWN_PATH,
            br#"{"shutdown_behavior":"keep_monitor","remember":false}"#,
        )
        .map_err(|_| BackendError::GracefulShutdownFailed)?;
        if response.status != 200 {
            return Err(BackendError::GracefulShutdownFailed);
        }
        let payload: Value = serde_json::from_slice(&response.body)
            .map_err(|_| BackendError::GracefulShutdownFailed)?;
        if !is_keep_monitor_shutdown_ack(&payload) {
            return Err(BackendError::GracefulShutdownFailed);
        }

        let deadline = Instant::now() + BACKEND_SHUTDOWN_TIMEOUT;
        while child_is_running(&self.child) {
            if Instant::now() >= deadline {
                return Err(BackendError::GracefulShutdownTimedOut);
            }
            thread_sleep_until(deadline);
        }
        Ok(())
    }

    pub fn shutdown_keep_monitor_or_terminate(
        &self,
    ) -> Result<BackendShutdownOutcome, BackendError> {
        match self.shutdown_keep_monitor() {
            Ok(()) => {
                self.stop_liveness_worker();
                Ok(BackendShutdownOutcome::Graceful)
            }
            Err(_) => {
                self.terminate_backend()?;
                Ok(BackendShutdownOutcome::Forced)
            }
        }
    }

    pub fn startup_surface(&self) -> StartupSurface {
        self.startup_surface
    }

    fn stop_liveness_worker(&self) {
        self.liveness_shutdown.store(true, Ordering::Release);
        let mut worker = match self.liveness_worker.lock() {
            Ok(worker) => worker,
            Err(poisoned) => poisoned.into_inner(),
        };
        if let Some(worker) = worker.take() {
            let _ = worker.join();
        }
    }

    fn terminate_backend(&self) -> Result<(), BackendError> {
        self.ownership_verified.store(false, Ordering::Release);
        self.stop_liveness_worker();
        let mut child = match self.child.lock() {
            Ok(child) => child,
            Err(poisoned) => poisoned.into_inner(),
        };
        if matches!(child.try_wait(), Ok(Some(_))) {
            return Ok(());
        }
        child
            .kill()
            .map_err(|_| BackendError::BackendTerminationFailed)?;
        child
            .wait()
            .map(|_| ())
            .map_err(|_| BackendError::BackendTerminationFailed)
    }
}

impl Drop for BackendHost {
    fn drop(&mut self) {
        let _ = self.terminate_backend();
    }
}

fn spawn_backend_liveness_watcher(
    child: Arc<Mutex<Child>>,
    ownership_verified: Arc<AtomicBool>,
    shutdown: Arc<AtomicBool>,
) -> JoinHandle<()> {
    thread::spawn(move || {
        while !shutdown.load(Ordering::Acquire) {
            if !child_is_running(&child) {
                ownership_verified.store(false, Ordering::Release);
                return;
            }
            thread::sleep(BACKEND_LIVENESS_POLL_INTERVAL);
        }
    })
}

fn child_is_running(child: &Mutex<Child>) -> bool {
    match child.lock() {
        Ok(mut child) => matches!(child.try_wait(), Ok(None)),
        Err(_) => false,
    }
}

fn state_paths_for_bundle_profile(
    profile: BundleProfile,
    bundle_root: &Path,
    default_state_paths: &DesktopStatePaths,
    development_root: Option<&Path>,
) -> Result<DesktopStatePaths, BackendError> {
    match profile {
        BundleProfile::Release => {
            if development_root.is_some() {
                return Err(BackendError::BundleManifestInvalid);
            }
            Ok(default_state_paths.clone())
        }
        BundleProfile::Development => {
            let root = development_root.ok_or(BackendError::BundleManifestInvalid)?;
            if !root.is_absolute() || !root.is_dir() {
                return Err(BackendError::BundleManifestInvalid);
            }
            let canonical_root =
                fs::canonicalize(root).map_err(|_| BackendError::BundleManifestInvalid)?;
            let canonical_bundle =
                fs::canonicalize(bundle_root).map_err(|_| BackendError::BundleManifestInvalid)?;
            let canonical_bundle_boundary = bundle_state_boundary(&canonical_bundle);
            if canonical_root.starts_with(&canonical_bundle_boundary)
                || canonical_bundle_boundary.starts_with(&canonical_root)
            {
                return Err(BackendError::BundleManifestInvalid);
            }
            Ok(DesktopStatePaths {
                config_path: canonical_root.join(DESKTOP_CONFIG_RELATIVE_PATH),
                runtime_dir: canonical_root.join(DESKTOP_RUNTIME_RELATIVE_PATH),
                root: canonical_root,
            })
        }
    }
}

fn bundle_state_boundary(bundle_root: &Path) -> PathBuf {
    let Some(contents_dir) = bundle_root
        .parent()
        .filter(|_| bundle_root.file_name().and_then(|value| value.to_str()) == Some("Resources"))
        .filter(|path| path.file_name().and_then(|value| value.to_str()) == Some("Contents"))
    else {
        return bundle_root.to_path_buf();
    };
    let Some(app_bundle) = contents_dir
        .parent()
        .filter(|path| path.extension().and_then(|value| value.to_str()) == Some("app"))
    else {
        return bundle_root.to_path_buf();
    };
    app_bundle.to_path_buf()
}

fn revalidate_backend_after_preferences<ChildRunning, Probe>(
    mut child_running: ChildRunning,
    mut probe: Probe,
) -> Result<(), BackendError>
where
    ChildRunning: FnMut() -> bool,
    Probe: FnMut() -> Result<(), BackendError>,
{
    if !child_running() {
        return Err(HandshakeError::BackendNotReady.into());
    }
    probe()?;
    if !child_running() {
        return Err(HandshakeError::BackendNotReady.into());
    }
    Ok(())
}

fn bundle_relative_file(bundle_root: &Path, raw: &str) -> Result<PathBuf, BackendError> {
    let candidate = Path::new(raw);
    if candidate.is_absolute()
        || candidate.components().any(|component| {
            matches!(
                component,
                Component::ParentDir | Component::RootDir | Component::Prefix(_)
            )
        })
    {
        return Err(BackendError::BundleManifestInvalid);
    }
    let resolved = bundle_root.join(candidate);
    let canonical_root =
        fs::canonicalize(bundle_root).map_err(|_| BackendError::BundleManifestInvalid)?;
    let canonical = fs::canonicalize(&resolved).map_err(|_| BackendError::BundleManifestInvalid)?;
    if !canonical.starts_with(&canonical_root) || !canonical.is_file() {
        return Err(BackendError::BundleManifestInvalid);
    }
    Ok(canonical)
}

fn bundle_relative_directory(bundle_root: &Path, raw: &str) -> Result<PathBuf, BackendError> {
    let candidate = Path::new(raw);
    if candidate.is_absolute()
        || candidate.components().any(|component| {
            matches!(
                component,
                Component::ParentDir | Component::RootDir | Component::Prefix(_)
            )
        })
    {
        return Err(BackendError::BundleManifestInvalid);
    }
    let resolved = bundle_root.join(candidate);
    let canonical_root =
        fs::canonicalize(bundle_root).map_err(|_| BackendError::BundleManifestInvalid)?;
    let canonical = fs::canonicalize(&resolved).map_err(|_| BackendError::BundleManifestInvalid)?;
    if !canonical.starts_with(&canonical_root) || !canonical.is_dir() {
        return Err(BackendError::BundleManifestInvalid);
    }
    Ok(canonical)
}

fn validate_backend_root(backend_root: &Path, profile: BundleProfile) -> Result<(), BackendError> {
    for required in ["src/invoice_hub/api/main.py", "web", BUILD_MANIFEST_FILE] {
        if !backend_root.join(required).exists() {
            return Err(BackendError::BundleManifestInvalid);
        }
    }
    let package_manifest_present = backend_root.join(PACKAGE_MANIFEST_FILE).is_file();
    match profile {
        BundleProfile::Development if package_manifest_present => {
            Err(BackendError::BundleManifestInvalid)
        }
        BundleProfile::Release if !package_manifest_present => {
            Err(BackendError::BundleManifestInvalid)
        }
        _ => Ok(()),
    }
}

fn bundle_arguments(
    fields: &Map<String, Value>,
    backend_root: &Path,
    state_paths: &DesktopStatePaths,
) -> Result<Vec<String>, BackendError> {
    let values = fields
        .get("backend_args")
        .and_then(Value::as_array)
        .ok_or(BackendError::BundleManifestInvalid)?;
    if values.len() > 64 {
        return Err(BackendError::BundleManifestInvalid);
    }
    let args: Vec<String> = values
        .iter()
        .map(|value| {
            value
                .as_str()
                .filter(|argument| !argument.contains('\0'))
                .map(str::to_owned)
                .ok_or(BackendError::BundleManifestInvalid)
        })
        .collect::<Result<Vec<_>, _>>()?;
    fixed_backend_arguments(args, backend_root, state_paths)
}

fn fixed_backend_arguments(
    mut args: Vec<String>,
    backend_root: &Path,
    state_paths: &DesktopStatePaths,
) -> Result<Vec<String>, BackendError> {
    if args.iter().any(|argument| {
        argument == "--"
            || argument == "--host"
            || argument.starts_with("--host=")
            || argument == "--port"
            || argument.starts_with("--port=")
            || argument == "--root"
            || argument.starts_with("--root=")
            || argument == "--config"
            || argument.starts_with("--config=")
            || argument == "--initial-state-dir"
            || argument.starts_with("--initial-state-dir=")
    }) {
        return Err(BackendError::BundleManifestInvalid);
    }
    args.push("--root".to_owned());
    args.push(backend_root.to_string_lossy().into_owned());
    args.push("--config".to_owned());
    args.push(state_paths.config_path.to_string_lossy().into_owned());
    args.push("--initial-state-dir".to_owned());
    args.push(state_paths.root.to_string_lossy().into_owned());
    args.push("--host".to_owned());
    args.push(FIXED_BACKEND_HOST.to_owned());
    args.push("--port".to_owned());
    args.push(FIXED_BACKEND_PORT.to_string());
    Ok(args)
}

fn identity_from_json(
    fields: &Map<String, Value>,
    state_paths: &DesktopStatePaths,
    profile: BundleProfile,
) -> Result<ExpectedBackendIdentity, BackendError> {
    if fields.contains_key("config_path") || fields.contains_key("runtime_dir") {
        return Err(BackendError::BundleManifestInvalid);
    }
    let capabilities = required_string_list(fields, "capabilities")?;
    let unique_capabilities: BTreeSet<_> = capabilities.iter().collect();
    let build_id = required_text(fields, "build_id")?;
    if build_id.len() != 64
        || !build_id.bytes().all(|byte| {
            byte.is_ascii_digit() || (byte.is_ascii_lowercase() && byte.is_ascii_hexdigit())
        })
        || capabilities.is_empty()
        || unique_capabilities.len() != capabilities.len()
    {
        return Err(BackendError::BundleManifestInvalid);
    }
    let package_id = required_text(fields, "package_id")?;
    let package_type = required_text(fields, "package_type")?;
    match profile {
        BundleProfile::Development if package_id != "development" || package_type != "source" => {
            return Err(BackendError::BundleManifestInvalid)
        }
        BundleProfile::Release if package_id == "development" || package_type == "source" => {
            return Err(BackendError::BundleManifestInvalid)
        }
        _ => {}
    }
    Ok(ExpectedBackendIdentity {
        bundle_profile: profile,
        build_id,
        api_contract_version: required_text(fields, "api_contract_version")?,
        bookkeeping_protocol_version: required_text(fields, "bookkeeping_protocol_version")?,
        capabilities,
        product_version: required_text(fields, "product_version")?,
        package_id,
        platform: required_text(fields, "platform")?,
        architecture: required_text(fields, "architecture")?,
        package_type,
        config_path: state_paths.config_path.clone(),
        runtime_dir: state_paths.runtime_dir.clone(),
    })
}

fn updater_from_json(
    fields: &Map<String, Value>,
    profile: BundleProfile,
) -> Result<UpdaterBundleConfig, BackendError> {
    let enabled =
        required_bool(fields, "enabled").map_err(|_| BackendError::BundleManifestInvalid)?;
    if !enabled {
        if profile != BundleProfile::Development
            || fields.len() != 1
            || fields.contains_key("endpoint")
            || fields.contains_key("public_key")
        {
            return Err(BackendError::BundleManifestInvalid);
        }
        return Ok(UpdaterBundleConfig {
            enabled: false,
            endpoint: None,
            public_key: None,
        });
    }
    if profile != BundleProfile::Release {
        return Err(BackendError::BundleManifestInvalid);
    }
    let endpoint =
        required_text(fields, "endpoint").map_err(|_| BackendError::BundleManifestInvalid)?;
    let public_key =
        required_text(fields, "public_key").map_err(|_| BackendError::BundleManifestInvalid)?;
    if !endpoint.starts_with("https://")
        || endpoint.contains('@')
        || endpoint.contains('#')
        || endpoint.chars().any(char::is_control)
        || public_key.chars().any(char::is_control)
    {
        return Err(BackendError::BundleManifestInvalid);
    }
    Ok(UpdaterBundleConfig {
        enabled: true,
        endpoint: Some(endpoint),
        public_key: Some(public_key),
    })
}

fn file_sha256_matches(path: &Path, expected: &str) -> bool {
    let Some(expected) = decode_hex_32(expected) else {
        return false;
    };
    let Ok(mut file) = fs::File::open(path) else {
        return false;
    };
    let mut digest = Sha256::new();
    let mut buffer = [0_u8; 64 * 1024];
    loop {
        let Ok(count) = file.read(&mut buffer) else {
            return false;
        };
        if count == 0 {
            break;
        }
        digest.update(&buffer[..count]);
    }
    let actual: [u8; 32] = digest.finalize().into();
    actual == expected
}

fn compiled_bundle_manifest_hash_matches(raw: &[u8]) -> bool {
    BUNDLE_MANIFEST_SHA256.is_some_and(|expected| bundle_manifest_hash_matches(raw, expected))
}

fn bundle_manifest_hash_matches(raw: &[u8], expected: &str) -> bool {
    let Some(expected) = decode_hex_32(expected) else {
        return false;
    };
    let actual: [u8; 32] = Sha256::digest(raw).into();
    actual == expected
}

fn required_text(fields: &Map<String, Value>, key: &str) -> Result<String, BackendError> {
    fields
        .get(key)
        .and_then(Value::as_str)
        .map(str::trim)
        .filter(|value| !value.is_empty())
        .map(str::to_owned)
        .ok_or(BackendError::ProbeFailed)
}

fn required_bool(fields: &Map<String, Value>, key: &str) -> Result<bool, BackendError> {
    fields
        .get(key)
        .and_then(Value::as_bool)
        .ok_or(BackendError::ProbeFailed)
}

fn required_u32(fields: &Map<String, Value>, key: &str) -> Result<u32, BackendError> {
    fields
        .get(key)
        .and_then(Value::as_u64)
        .and_then(|value| u32::try_from(value).ok())
        .filter(|value| *value != 0)
        .ok_or(BackendError::ProbeFailed)
}

fn required_string_list(
    fields: &Map<String, Value>,
    key: &str,
) -> Result<Vec<String>, BackendError> {
    fields
        .get(key)
        .and_then(Value::as_array)
        .ok_or(BackendError::ProbeFailed)?
        .iter()
        .map(|value| {
            value
                .as_str()
                .map(str::trim)
                .filter(|item| !item.is_empty())
                .map(str::to_owned)
                .ok_or(BackendError::ProbeFailed)
        })
        .collect()
}

struct HttpResponse {
    status: u16,
    headers: BTreeMap<String, String>,
    body: Vec<u8>,
}

fn local_get(path: &str) -> Result<HttpResponse, BackendError> {
    local_get_with_header(path, "", "")
}

fn is_keep_monitor_shutdown_ack(value: &Value) -> bool {
    let Some(fields) = value.as_object() else {
        return false;
    };
    fields.get("ok").and_then(Value::as_bool) == Some(true)
        && fields.get("shutdown_behavior").and_then(Value::as_str) == Some("keep_monitor")
        && (fields.get("scheduled").and_then(Value::as_bool) == Some(true)
            || fields.get("idempotent").and_then(Value::as_bool) == Some(true))
}

fn local_post_json(path: &str, body: &[u8]) -> Result<HttpResponse, BackendError> {
    let mut stream = TcpStream::connect_timeout(&fixed_backend_socket_addr(), HTTP_TIMEOUT)
        .map_err(|_| BackendError::ProbeFailed)?;
    stream
        .set_read_timeout(Some(HTTP_TIMEOUT))
        .map_err(|_| BackendError::ProbeFailed)?;
    stream
        .set_write_timeout(Some(HTTP_TIMEOUT))
        .map_err(|_| BackendError::ProbeFailed)?;
    let request = format!(
        "POST {path} HTTP/1.1\r\nHost: {FIXED_BACKEND_HOST}:{FIXED_BACKEND_PORT}\r\nContent-Type: application/json\r\nContent-Length: {}\r\nConnection: close\r\n\r\n",
        body.len(),
    );
    stream
        .write_all(request.as_bytes())
        .map_err(|_| BackendError::ProbeFailed)?;
    stream
        .write_all(body)
        .map_err(|_| BackendError::ProbeFailed)?;
    read_http_response(&mut stream)
}

fn local_get_with_header(
    path: &str,
    header_name: &str,
    header_value: &str,
) -> Result<HttpResponse, BackendError> {
    let mut stream = TcpStream::connect_timeout(&fixed_backend_socket_addr(), HTTP_TIMEOUT)
        .map_err(|_| BackendError::ProbeFailed)?;
    stream
        .set_read_timeout(Some(HTTP_TIMEOUT))
        .map_err(|_| BackendError::ProbeFailed)?;
    stream
        .set_write_timeout(Some(HTTP_TIMEOUT))
        .map_err(|_| BackendError::ProbeFailed)?;
    let extra_header = if header_name.is_empty() {
        String::new()
    } else {
        format!("{header_name}: {header_value}\r\n")
    };
    let request = format!(
        "GET {path} HTTP/1.1\r\nHost: {FIXED_BACKEND_HOST}:{FIXED_BACKEND_PORT}\r\n{extra_header}Connection: close\r\n\r\n"
    );
    stream
        .write_all(request.as_bytes())
        .map_err(|_| BackendError::ProbeFailed)?;
    read_http_response(&mut stream)
}

fn generate_ownership_secret() -> Result<[u8; OWNERSHIP_SECRET_BYTES], BackendError> {
    let mut secret = [0_u8; OWNERSHIP_SECRET_BYTES];
    getrandom::fill(&mut secret).map_err(|_| BackendError::RandomUnavailable)?;
    Ok(secret)
}

fn generate_ownership_challenge() -> Result<String, BackendError> {
    generate_ownership_secret().map(|challenge| hex_encode(&challenge))
}

fn ownership_response_matches(
    secret: &[u8; OWNERSHIP_SECRET_BYTES],
    challenge: &str,
    response: &str,
) -> bool {
    let Some(response) = decode_hex_32(response) else {
        return false;
    };
    let Ok(mut mac) = OwnershipHmac::new_from_slice(secret) else {
        return false;
    };
    mac.update(challenge.as_bytes());
    mac.verify_slice(&response).is_ok()
}

#[cfg(test)]
fn ownership_response_for_test(secret: &[u8; OWNERSHIP_SECRET_BYTES], challenge: &str) -> String {
    let mut mac = OwnershipHmac::new_from_slice(secret).expect("fixed ownership secret length");
    mac.update(challenge.as_bytes());
    hex_encode(&mac.finalize().into_bytes())
}

fn hex_encode(bytes: &[u8]) -> String {
    bytes
        .iter()
        .flat_map(|byte| [hex_digit(byte >> 4), hex_digit(byte & 0x0f)])
        .collect()
}

fn decode_hex_32(value: &str) -> Option<[u8; OWNERSHIP_SECRET_BYTES]> {
    if value.len() != OWNERSHIP_SECRET_BYTES * 2 {
        return None;
    }
    let mut decoded = [0_u8; OWNERSHIP_SECRET_BYTES];
    for (index, pair) in value.as_bytes().chunks_exact(2).enumerate() {
        decoded[index] = (hex_value(pair[0])? << 4) | hex_value(pair[1])?;
    }
    Some(decoded)
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

fn read_http_response(stream: &mut TcpStream) -> Result<HttpResponse, BackendError> {
    let mut raw = Vec::new();
    let mut chunk = [0_u8; 4096];
    loop {
        let read = stream
            .read(&mut chunk)
            .map_err(|_| BackendError::ProbeFailed)?;
        if read == 0 {
            break;
        }
        if raw.len().saturating_add(read) > MAX_HTTP_RESPONSE_BYTES {
            return Err(BackendError::ProbeFailed);
        }
        raw.extend_from_slice(&chunk[..read]);
    }
    let header_end = raw
        .windows(4)
        .position(|window| window == b"\r\n\r\n")
        .ok_or(BackendError::ProbeFailed)?;
    let header = std::str::from_utf8(&raw[..header_end]).map_err(|_| BackendError::ProbeFailed)?;
    let mut lines = header.lines();
    let status = lines
        .next()
        .and_then(|line| line.split_whitespace().nth(1))
        .and_then(|status| status.parse::<u16>().ok())
        .ok_or(BackendError::ProbeFailed)?;
    let mut headers = BTreeMap::new();
    for line in lines {
        let Some((name, value)) = line.split_once(':') else {
            return Err(BackendError::ProbeFailed);
        };
        let name = name.trim().to_ascii_lowercase();
        let value = value.trim().to_owned();
        if name.is_empty() || headers.insert(name, value).is_some() {
            return Err(BackendError::ProbeFailed);
        }
    }
    let body_start = header_end + 4;
    if raw.len() < body_start {
        return Err(BackendError::ProbeFailed);
    }
    Ok(HttpResponse {
        status,
        headers,
        body: raw[body_start..].to_vec(),
    })
}

fn retry_probe<F>(mut probe: F, timeout: Duration) -> Result<BackendHealth, BackendError>
where
    F: FnMut() -> Result<BackendHealth, BackendError>,
{
    let deadline = Instant::now() + timeout;
    loop {
        match probe() {
            Ok(health) => return Ok(health),
            Err(error) if Instant::now() >= deadline => return Err(error),
            Err(_) => thread_sleep_until(deadline),
        }
    }
}

fn thread_sleep_until(deadline: Instant) {
    let remaining = deadline.saturating_duration_since(Instant::now());
    if !remaining.is_zero() {
        std::thread::sleep(remaining.min(BACKEND_RETRY_INTERVAL));
    }
}

#[cfg(test)]
mod tests {
    use std::fs;
    use std::path::Path;
    use std::sync::atomic::{AtomicUsize, Ordering};

    use serde_json::{Map, Value};
    use sha2::{Digest, Sha256};

    use super::{
        bundle_manifest_hash_matches, bundle_relative_directory, bundle_root_for_executable,
        desktop_state_paths_for, fixed_backend_arguments, generate_ownership_challenge,
        generate_ownership_secret, identity_from_json, is_keep_monitor_shutdown_ack,
        ownership_response_for_test, ownership_response_matches, retry_probe,
        revalidate_backend_after_preferences, state_paths_for_bundle_profile, BackendError,
        BackendHealth, BundleProfile, DesktopStatePaths, DesktopStatePlatform, HandshakeError,
    };

    fn health() -> BackendHealth {
        BackendHealth {
            ok: true,
            pid: 1,
            build_manifest_present: true,
            build_manifest_valid: true,
            package_manifest_present: true,
            package_manifest_valid: true,
            build_id: "a".repeat(64),
            api_contract_version: "contract".to_owned(),
            bookkeeping_protocol_version: "protocol".to_owned(),
            capabilities: vec!["capability".to_owned()],
            product_version: "version".to_owned(),
            package_id: "package".to_owned(),
            platform: "platform".to_owned(),
            architecture: "architecture".to_owned(),
            package_type: "package_type".to_owned(),
            config_path: "/config".into(),
            runtime_dir: "/runtime".into(),
        }
    }

    #[test]
    fn retry_probe_allows_a_transient_unready_backend() {
        let attempts = AtomicUsize::new(0);
        let result = retry_probe(
            || {
                if attempts.fetch_add(1, Ordering::AcqRel) == 0 {
                    Err(BackendError::ProbeFailed)
                } else {
                    Ok(health())
                }
            },
            std::time::Duration::from_millis(50),
        );

        assert_eq!(result.expect("second probe succeeds").pid, 1);
        assert_eq!(attempts.load(Ordering::Acquire), 2);
    }

    #[test]
    fn retry_probe_preserves_the_final_handshake_failure() {
        let result = retry_probe(
            || Err(BackendError::Handshake(HandshakeError::PidMismatch)),
            std::time::Duration::ZERO,
        );

        assert!(matches!(
            result,
            Err(BackendError::Handshake(HandshakeError::PidMismatch))
        ));
    }

    #[test]
    fn backend_arguments_cannot_override_the_fixed_loopback_binding() {
        let state_paths = DesktopStatePaths {
            root: "/user-data/InvoiceHub".into(),
            config_path: "/user-data/InvoiceHub/config/app.local.json".into(),
            runtime_dir: "/user-data/InvoiceHub/runtime".into(),
        };
        assert_eq!(
            fixed_backend_arguments(
                vec!["-m".to_owned(), "invoice_hub.api.main".to_owned()],
                Path::new("/bundle/core"),
                &state_paths,
            )
            .expect("fixed arguments"),
            vec![
                "-m".to_owned(),
                "invoice_hub.api.main".to_owned(),
                "--root".to_owned(),
                "/bundle/core".to_owned(),
                "--config".to_owned(),
                "/user-data/InvoiceHub/config/app.local.json".to_owned(),
                "--initial-state-dir".to_owned(),
                "/user-data/InvoiceHub".to_owned(),
                "--host".to_owned(),
                "127.0.0.1".to_owned(),
                "--port".to_owned(),
                "8766".to_owned(),
            ]
        );
        for override_argument in [
            "--host",
            "--host=0.0.0.0",
            "--port",
            "--port=9999",
            "--root",
            "--config=/tmp/other.json",
            "--initial-state-dir",
            "--",
        ] {
            assert!(matches!(
                fixed_backend_arguments(
                    vec![override_argument.to_owned()],
                    Path::new("/bundle/core"),
                    &state_paths,
                ),
                Err(BackendError::BundleManifestInvalid)
            ));
        }
    }

    #[test]
    fn desktop_state_paths_are_derived_from_platform_user_roots() {
        let windows = desktop_state_paths_for(
            DesktopStatePlatform::Windows,
            Some(Path::new("/users/example/local-app-data")),
            None,
        )
        .expect("Windows state paths");
        assert_eq!(
            windows.root,
            Path::new("/users/example/local-app-data/InvoiceHub")
        );
        assert_eq!(
            windows.config_path,
            Path::new("/users/example/local-app-data/InvoiceHub/config/app.local.json")
        );
        assert_eq!(
            windows.runtime_dir,
            Path::new("/users/example/local-app-data/InvoiceHub/runtime")
        );

        let macos = desktop_state_paths_for(
            DesktopStatePlatform::Macos,
            None,
            Some(Path::new("/Users/example")),
        )
        .expect("macOS state paths");
        assert_eq!(
            macos.root,
            Path::new("/Users/example/Library/Application Support/InvoiceHub")
        );
        assert_eq!(
            macos.config_path,
            Path::new(
                "/Users/example/Library/Application Support/InvoiceHub/config/app.local.json"
            )
        );
        assert_eq!(
            macos.runtime_dir,
            Path::new("/Users/example/Library/Application Support/InvoiceHub/runtime")
        );
        assert!(matches!(
            desktop_state_paths_for(
                DesktopStatePlatform::Windows,
                Some(Path::new("relative")),
                None
            ),
            Err(BackendError::DesktopStateUnavailable)
        ));
    }

    #[test]
    fn development_state_root_is_explicit_existing_and_disjoint_from_the_bundle() {
        let default_state_paths = DesktopStatePaths {
            root: Path::new("/Users/example/Library/Application Support/InvoiceHub").to_path_buf(),
            config_path: Path::new(
                "/Users/example/Library/Application Support/InvoiceHub/config/app.local.json",
            )
            .to_path_buf(),
            runtime_dir: Path::new("/Users/example/Library/Application Support/InvoiceHub/runtime")
                .to_path_buf(),
        };
        let temporary_root = std::env::temp_dir().join(format!(
            "invoicehub-tauri-state-profile-{}",
            std::process::id()
        ));
        let _ = fs::remove_dir_all(&temporary_root);
        let bundle_root = temporary_root.join("bundle");
        let app_bundle_root = temporary_root
            .join("InvoiceHub.app")
            .join("Contents")
            .join("Resources");
        let app_contents_state = temporary_root
            .join("InvoiceHub.app")
            .join("Contents")
            .join("state");
        let isolated_root = temporary_root.join("isolated-state");
        let inside_bundle = bundle_root.join("state");
        fs::create_dir_all(&bundle_root).expect("create bundle root");
        fs::create_dir_all(&app_bundle_root).expect("create app bundle root");
        fs::create_dir_all(&app_contents_state).expect("create app contents state root");
        fs::create_dir_all(&isolated_root).expect("create isolated state root");
        fs::create_dir_all(&inside_bundle).expect("create nested state root");

        assert!(matches!(
            state_paths_for_bundle_profile(
                BundleProfile::Development,
                &bundle_root,
                &default_state_paths,
                None,
            ),
            Err(BackendError::BundleManifestInvalid)
        ));

        let isolated = state_paths_for_bundle_profile(
            BundleProfile::Development,
            &bundle_root,
            &default_state_paths,
            Some(&isolated_root),
        )
        .expect("isolated development state");
        let canonical_isolated_root =
            fs::canonicalize(&isolated_root).expect("canonical state root");
        assert_eq!(isolated.root, canonical_isolated_root);
        assert_eq!(
            isolated.config_path,
            canonical_isolated_root.join("config/app.local.json")
        );
        assert_eq!(
            isolated.runtime_dir,
            canonical_isolated_root.join("runtime")
        );

        assert!(matches!(
            state_paths_for_bundle_profile(
                BundleProfile::Release,
                &bundle_root,
                &default_state_paths,
                Some(&isolated_root),
            ),
            Err(BackendError::BundleManifestInvalid)
        ));
        assert!(matches!(
            state_paths_for_bundle_profile(
                BundleProfile::Development,
                &app_bundle_root,
                &default_state_paths,
                Some(&app_contents_state),
            ),
            Err(BackendError::BundleManifestInvalid)
        ));
        assert!(matches!(
            state_paths_for_bundle_profile(
                BundleProfile::Development,
                &bundle_root,
                &default_state_paths,
                Some(Path::new("relative/state")),
            ),
            Err(BackendError::BundleManifestInvalid)
        ));
        assert!(matches!(
            state_paths_for_bundle_profile(
                BundleProfile::Development,
                &bundle_root,
                &default_state_paths,
                Some(&temporary_root.join("missing-state")),
            ),
            Err(BackendError::BundleManifestInvalid)
        ));
        assert!(matches!(
            state_paths_for_bundle_profile(
                BundleProfile::Development,
                &bundle_root,
                &default_state_paths,
                Some(&inside_bundle),
            ),
            Err(BackendError::BundleManifestInvalid)
        ));
        assert!(matches!(
            state_paths_for_bundle_profile(
                BundleProfile::Development,
                &bundle_root,
                &default_state_paths,
                Some(&temporary_root),
            ),
            Err(BackendError::BundleManifestInvalid)
        ));
        fs::remove_dir_all(&temporary_root).expect("remove temporary roots");
    }

    #[test]
    fn graceful_shutdown_response_requires_a_keep_monitor_acknowledgement() {
        assert!(is_keep_monitor_shutdown_ack(&serde_json::json!({
            "ok": true,
            "scheduled": true,
            "idempotent": false,
            "shutdown_behavior": "keep_monitor",
        })));
        for invalid in [
            serde_json::json!({"ok": false, "scheduled": true, "shutdown_behavior": "keep_monitor"}),
            serde_json::json!({"ok": true, "scheduled": false, "idempotent": false, "shutdown_behavior": "keep_monitor"}),
            serde_json::json!({"ok": true, "scheduled": true, "shutdown_behavior": "stop_monitor"}),
        ] {
            assert!(!is_keep_monitor_shutdown_ack(&invalid));
        }
    }

    #[test]
    fn manifest_identity_uses_derived_state_paths_and_rejects_embedded_ones() {
        let state_paths = DesktopStatePaths {
            root: "/user-data/InvoiceHub".into(),
            config_path: "/user-data/InvoiceHub/config/app.local.json".into(),
            runtime_dir: "/user-data/InvoiceHub/runtime".into(),
        };
        let mut fields = Map::from_iter([
            ("build_id".to_owned(), Value::String("a".repeat(64))),
            (
                "api_contract_version".to_owned(),
                Value::String("2026-08-02-release-update-v1".to_owned()),
            ),
            (
                "bookkeeping_protocol_version".to_owned(),
                Value::String("w9-ledger-review-v1".to_owned()),
            ),
            (
                "capabilities".to_owned(),
                Value::Array(vec![Value::String(
                    "release.package-identity.v1".to_owned(),
                )]),
            ),
            (
                "product_version".to_owned(),
                Value::String("0.3.0-alpha.1".to_owned()),
            ),
            (
                "package_id".to_owned(),
                Value::String("com.invoicehub.desktop".to_owned()),
            ),
            ("platform".to_owned(), Value::String("windows".to_owned())),
            (
                "architecture".to_owned(),
                Value::String("x86_64".to_owned()),
            ),
            ("package_type".to_owned(), Value::String("nsis".to_owned())),
        ]);
        let identity = identity_from_json(&fields, &state_paths, BundleProfile::Release)
            .expect("derived identity");
        assert_eq!(identity.config_path, state_paths.config_path);
        assert_eq!(identity.runtime_dir, state_paths.runtime_dir);

        fields.insert(
            "config_path".to_owned(),
            Value::String("/bundle/runtime".to_owned()),
        );
        assert!(matches!(
            identity_from_json(&fields, &state_paths, BundleProfile::Release),
            Err(BackendError::BundleManifestInvalid)
        ));
        assert!(matches!(
            bundle_relative_directory(Path::new("/bundle"), "../escape"),
            Err(BackendError::BundleManifestInvalid)
        ));
    }

    #[test]
    fn macos_app_executable_resolves_the_resources_root() {
        assert_eq!(
            bundle_root_for_executable(Path::new(
                "/Applications/InvoiceHub.app/Contents/MacOS/InvoiceHub"
            ))
            .expect("macOS resources root"),
            Path::new("/Applications/InvoiceHub.app/Contents/Resources")
        );
        assert_eq!(
            bundle_root_for_executable(Path::new("/opt/invoicehub/InvoiceHub.exe"))
                .expect("Windows executable root"),
            Path::new("/opt/invoicehub")
        );
    }

    #[test]
    fn bundle_manifest_hash_requires_the_build_bound_digest() {
        let manifest = br#"{\"schema_version\":3}"#;
        let digest = Sha256::digest(manifest)
            .iter()
            .map(|byte| format!("{byte:02x}"))
            .collect::<String>();

        assert!(bundle_manifest_hash_matches(manifest, &digest));
        assert!(!bundle_manifest_hash_matches(
            manifest,
            &format!("0{digest}")
        ));
        assert!(!bundle_manifest_hash_matches(manifest, "not-a-digest"));
    }

    #[test]
    fn ownership_challenge_response_requires_the_private_secret() {
        let secret = generate_ownership_secret().expect("ownership secret");
        let challenge = generate_ownership_challenge().expect("ownership challenge");
        let response = ownership_response_for_test(&secret, &challenge);

        assert_eq!(challenge.len(), 64);
        assert_eq!(response.len(), 64);
        assert!(ownership_response_matches(&secret, &challenge, &response));
        assert!(!ownership_response_matches(
            &secret,
            &format!("0{challenge}"),
            &response
        ));

        let mut tampered_response = response.into_bytes();
        tampered_response[0] = if tampered_response[0] == b'0' {
            b'1'
        } else {
            b'0'
        };
        let tampered_response = String::from_utf8(tampered_response).expect("ASCII response");
        assert!(!ownership_response_matches(
            &secret,
            &challenge,
            &tampered_response
        ));
    }

    #[test]
    fn post_preference_revalidation_rejects_replaced_or_exited_backend() {
        let replaced = revalidate_backend_after_preferences(
            || true,
            || {
                Err(BackendError::Handshake(
                    HandshakeError::OwnershipProofMismatch,
                ))
            },
        );
        assert!(matches!(
            replaced,
            Err(BackendError::Handshake(
                HandshakeError::OwnershipProofMismatch
            ))
        ));

        let checks = AtomicUsize::new(0);
        let exited = revalidate_backend_after_preferences(
            || checks.fetch_add(1, Ordering::AcqRel) == 0,
            || Ok(()),
        );
        assert!(matches!(
            exited,
            Err(BackendError::Handshake(HandshakeError::BackendNotReady))
        ));
    }
}
