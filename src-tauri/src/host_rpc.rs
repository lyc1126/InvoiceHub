//! Private loopback host channel. The bearer token never reaches Web content.

use std::error::Error;
use std::fmt;
use std::io::{Read, Write};
use std::net::{IpAddr, Ipv4Addr, SocketAddr, TcpListener, TcpStream};
use std::sync::atomic::{AtomicBool, AtomicU64, AtomicUsize, Ordering};
use std::sync::mpsc;
use std::sync::{Arc, Mutex};
use std::thread::{self, JoinHandle};
use std::time::{Duration, Instant};

use serde_json::{json, Value};
use tauri_plugin_dialog::DialogExt;
use tauri_plugin_updater::UpdaterExt;

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
        if object.len() != 1 {
            return Err(HostRpcAuthorizationError::CommandRejected);
        }
        let command = object
            .get("command")
            .and_then(Value::as_str)
            .ok_or(HostRpcAuthorizationError::CommandRejected)?;
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
    ) -> Result<HostRpcCommand, HostRpcAuthorizationError> {
        if !self.ownership_verified.load(Ordering::Acquire) {
            return Err(HostRpcAuthorizationError::OwnershipRejected);
        }
        if origin != HOST_RPC_ORIGIN {
            return Err(HostRpcAuthorizationError::OriginRejected);
        }
        if !constant_time_equal(&self.token, candidate_token) {
            return Err(HostRpcAuthorizationError::TokenRejected);
        }
        HostRpcCommand::parse(command).ok_or(HostRpcAuthorizationError::CommandRejected)
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
}

#[derive(Clone)]
struct HostUpdater {
    app_handle: tauri::AppHandle<tauri::Wry>,
    endpoint: Option<String>,
    ownership_verified: Arc<AtomicBool>,
    candidate: Arc<Mutex<Option<(u64, PendingUpdate)>>>,
    candidate_generation: Arc<AtomicU64>,
    operation: Arc<Mutex<()>>,
}

struct PendingUpdate {
    checked_at: Instant,
}

impl HostUpdater {
    fn new(
        app_handle: tauri::AppHandle<tauri::Wry>,
        ownership_verified: Arc<AtomicBool>,
        endpoint: Option<String>,
    ) -> Self {
        Self {
            app_handle,
            endpoint,
            ownership_verified,
            candidate: Arc::new(Mutex::new(None)),
            candidate_generation: Arc::new(AtomicU64::new(0)),
            operation: Arc::new(Mutex::new(())),
        }
    }

    fn require_owned(&self) -> Result<(), HostRpcServerError> {
        if self.endpoint.is_some() && self.ownership_verified.load(Ordering::Acquire) {
            Ok(())
        } else {
            Err(HostRpcServerError::UpdaterUnavailable)
        }
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
            .lock()
            .map_err(|_| HostRpcServerError::UpdaterUnavailable)?;
        self.clear_candidate()?;
        self.require_owned()?;

        let endpoint = self
            .endpoint
            .as_deref()
            .ok_or(HostRpcServerError::UpdaterUnavailable)?
            .parse()
            .map_err(|_| HostRpcServerError::UpdaterUnavailable)?;
        let updater = self
            .app_handle
            .updater_builder()
            .endpoints(vec![endpoint])
            .map_err(|_| HostRpcServerError::UpdaterUnavailable)?
            .timeout(UPDATE_HTTP_TIMEOUT)
            .build()
            .map_err(|_| HostRpcServerError::UpdaterUnavailable)?;
        let candidate = tauri::async_runtime::block_on(updater.check())
            .map_err(|_| HostRpcServerError::UpdaterUnavailable)?;
        self.require_owned()?;

        let Some(candidate) = candidate else {
            return Ok(HostRpcResponse::UpdateCheck {
                available: false,
                version: String::new(),
            });
        };
        let version = candidate.version.clone();
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
            },
        ));
        drop(slot);
        Ok(HostRpcResponse::UpdateCheck {
            available: true,
            version,
        })
    }

    fn install(&self) -> Result<HostRpcResponse, HostRpcServerError> {
        let _operation = self
            .operation
            .lock()
            .map_err(|_| HostRpcServerError::UpdaterUnavailable)?;
        self.require_owned()?;
        // A failed install after stopping monitor has no recovery/relaunch
        // coordinator yet. Do not leave a half implementation able to alter
        // the running system. Consume any candidate and fail closed instead.
        self.clear_candidate()?;
        Err(HostRpcServerError::UpdaterUnavailable)
    }
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
        let worker = thread::spawn(move || {
            serve_listener(
                listener,
                app_handle,
                worker_authorizer,
                updater,
                worker_shutdown,
                active_connections,
            )
        });
        Ok(Self {
            endpoint_url: format!("http://127.0.0.1:{port}{HOST_RPC_PATH}"),
            token_for_backend: authorizer.token_hex(),
            shutdown,
            worker: Mutex::new(Some(worker)),
        })
    }

    pub fn endpoint_url(&self) -> &str {
        &self.endpoint_url
    }

    pub(crate) fn token_for_backend(&self) -> &str {
        &self.token_for_backend
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
        Ok(response) => write_response(&mut stream, response),
        Err(_) => write_rejected_response(&mut stream),
    };
}

fn handle_request(
    stream: &mut TcpStream,
    app_handle: &tauri::AppHandle<tauri::Wry>,
    authorizer: &HostRpcAuthorizer,
    updater: &HostUpdater,
) -> Result<HostRpcResponse, HostRpcAuthorizationError> {
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
            .map_err(|_| HostRpcAuthorizationError::CommandRejected),
        HostRpcCommand::UpdateCheck => updater
            .check()
            .map_err(|_| HostRpcAuthorizationError::CommandRejected),
        HostRpcCommand::UpdateInstall => updater
            .install()
            .map_err(|_| HostRpcAuthorizationError::CommandRejected),
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
        HostRpcCommand::UpdateCheck | HostRpcCommand::UpdateInstall => {
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

enum HostRpcResponse {
    Picker(Option<String>),
    UpdateCheck { available: bool, version: String },
}

fn write_response(stream: &mut TcpStream, response: HostRpcResponse) -> std::io::Result<()> {
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
    }
    .to_string();
    write!(
        stream,
        "HTTP/1.1 200 OK\r\nContent-Type: application/json\r\nContent-Length: {}\r\nConnection: close\r\n\r\n{}",
        body.len(),
        body
    )
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
    use std::io::Write;
    use std::net::{Ipv4Addr, TcpListener, TcpStream};
    use std::sync::Mutex;
    use std::thread;
    use std::time::{Duration, Instant};

    use super::{
        candidate_is_fresh, clear_candidate_if_current, read_request, HostRpcAuthorizationError,
        HostRpcCommand, HOST_RPC_ORIGIN, HOST_RPC_PATH, UPDATE_CANDIDATE_TTL,
    };

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
}
