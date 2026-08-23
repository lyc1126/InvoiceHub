//! Fixed-loopback adapter for the owned Python monitor bridge.
//!
//! The recovery transaction owns lease capture and revalidation.  This module
//! only supplies the narrow HTTP primitive it needs: three fixed endpoints on
//! the backend's IPv4 loopback listener, with no proxy, caller URL, path, or
//! request body surface.

use std::io::{self, Read, Write};
use std::net::{Ipv4Addr, SocketAddr, TcpStream};
use std::time::{Duration, Instant};

use serde_json::{Map, Value};

use crate::backend::{BRIDGE_START_PATH, BRIDGE_STATUS_PATH, BRIDGE_STOP_PATH};
use crate::monitor_recovery::{
    LifecycleLease, MonitorRecoveryBridge, MonitorSnapshot, RecoveryError,
};
use crate::FIXED_BACKEND_PORT;

const MAX_HTTP_RESPONSE_BYTES: usize = 128 * 1024;

const STATUS_TIMEOUT: RequestTimeout = RequestTimeout {
    connect: Duration::from_secs(1),
    write: Duration::from_secs(1),
    read: Duration::from_secs(3),
};
const START_TIMEOUT: RequestTimeout = RequestTimeout {
    connect: Duration::from_secs(1),
    write: Duration::from_secs(1),
    read: Duration::from_secs(15),
};
const STOP_TIMEOUT: RequestTimeout = RequestTimeout {
    connect: Duration::from_secs(1),
    write: Duration::from_secs(1),
    read: Duration::from_secs(25),
};

#[derive(Clone, Copy, Debug, PartialEq, Eq)]
struct RequestTimeout {
    connect: Duration,
    write: Duration,
    read: Duration,
}

#[derive(Clone, Copy, Debug, PartialEq, Eq)]
enum BridgeEndpoint {
    Status,
    Stop,
    Start,
}

impl BridgeEndpoint {
    fn method(self) -> &'static str {
        match self {
            Self::Status => "GET",
            Self::Stop | Self::Start => "POST",
        }
    }

    fn path(self) -> &'static str {
        match self {
            Self::Status => BRIDGE_STATUS_PATH,
            Self::Stop => BRIDGE_STOP_PATH,
            Self::Start => BRIDGE_START_PATH,
        }
    }
}

#[derive(Debug, PartialEq, Eq)]
struct HttpResponse {
    status_code: u16,
    body: Vec<u8>,
}

#[derive(Clone, Copy, Debug, PartialEq, Eq)]
enum TransportError {
    Timeout,
    Unavailable,
    Malformed,
    Oversized,
}

trait BridgeTransport {
    fn request(
        &mut self,
        endpoint: BridgeEndpoint,
        timeout: RequestTimeout,
    ) -> Result<HttpResponse, TransportError>;
}

/// A monitor bridge bound to the owned Python backend's fixed listener.
pub struct PythonMonitorRecoveryBridge {
    transport: Box<dyn BridgeTransport>,
}

impl PythonMonitorRecoveryBridge {
    /// Creates an adapter that connects directly to `127.0.0.1:8766`.
    pub fn new() -> Self {
        Self {
            transport: Box::new(DirectTcpTransport),
        }
    }

    #[cfg(test)]
    fn with_transport(transport: Box<dyn BridgeTransport>) -> Self {
        Self { transport }
    }

    fn request_snapshot(
        &mut self,
        lease: &LifecycleLease,
        endpoint: BridgeEndpoint,
        timeout: RequestTimeout,
    ) -> Result<MonitorSnapshot, RecoveryError> {
        ensure_eligible(lease)?;
        let response = self
            .transport
            .request(endpoint, timeout)
            .map_err(|_| RecoveryError::MonitorUnavailable)?;
        decode_snapshot(&response).map_err(|_| RecoveryError::MonitorUnavailable)
    }
}

impl Default for PythonMonitorRecoveryBridge {
    fn default() -> Self {
        Self::new()
    }
}

impl MonitorRecoveryBridge for PythonMonitorRecoveryBridge {
    fn status(&mut self, lease: &LifecycleLease) -> Result<MonitorSnapshot, RecoveryError> {
        self.request_snapshot(lease, BridgeEndpoint::Status, STATUS_TIMEOUT)
    }

    fn stop(&mut self, lease: &LifecycleLease) -> Result<(), RecoveryError> {
        let snapshot = self.request_snapshot(lease, BridgeEndpoint::Stop, STOP_TIMEOUT)?;
        if snapshot.running {
            return Err(RecoveryError::MonitorStillRunning);
        }
        Ok(())
    }

    fn start(&mut self, lease: &LifecycleLease) -> Result<(), RecoveryError> {
        let snapshot = self.request_snapshot(lease, BridgeEndpoint::Start, START_TIMEOUT)?;
        if !snapshot.running || !snapshot.ready {
            return Err(RecoveryError::MonitorNotReady);
        }
        Ok(())
    }
}

fn ensure_eligible(lease: &LifecycleLease) -> Result<(), RecoveryError> {
    if lease.is_recovery_eligible() {
        Ok(())
    } else {
        Err(RecoveryError::LeaseInvalid)
    }
}

#[derive(Clone, Copy, Debug, PartialEq, Eq)]
enum ResponseError {
    NonSuccess,
    Malformed,
    WrongType,
    Rejected,
    Inconsistent,
    Oversized,
}

fn decode_snapshot(response: &HttpResponse) -> Result<MonitorSnapshot, ResponseError> {
    if response.status_code != 200 {
        return Err(ResponseError::NonSuccess);
    }
    if response.body.len() > MAX_HTTP_RESPONSE_BYTES {
        return Err(ResponseError::Oversized);
    }

    let value: Value =
        serde_json::from_slice(&response.body).map_err(|_| ResponseError::Malformed)?;
    let fields = value.as_object().ok_or(ResponseError::Malformed)?;
    if required_bool(fields, "ok")? != true {
        return Err(ResponseError::Rejected);
    }

    let running = required_bool(fields, "running")?;
    let top_ready = optional_bool(fields, "ready")?;
    let nested_ready = if let Some(status) = fields.get("status") {
        let status = status.as_object().ok_or(ResponseError::Malformed)?;
        if let Some(nested_ok) = status.get("ok") {
            if !nested_ok.is_boolean() {
                return Err(ResponseError::WrongType);
            }
            if !required_bool(status, "ok")? {
                return Err(ResponseError::Rejected);
            }
        }
        let nested_running = required_bool(status, "running")?;
        if nested_running != running {
            return Err(ResponseError::Inconsistent);
        }
        Some(required_bool(status, "ready")?)
    } else {
        None
    };
    let ready = match (top_ready, nested_ready) {
        (Some(top), Some(nested)) if top != nested => return Err(ResponseError::Inconsistent),
        (Some(top), _) => top,
        (None, Some(nested)) => nested,
        (None, None) => return Err(ResponseError::Malformed),
    };
    if ready && !running {
        return Err(ResponseError::Inconsistent);
    }

    Ok(MonitorSnapshot { running, ready })
}

fn required_bool(fields: &Map<String, Value>, name: &str) -> Result<bool, ResponseError> {
    match fields.get(name) {
        Some(Value::Bool(value)) => Ok(*value),
        Some(_) => Err(ResponseError::WrongType),
        None => Err(ResponseError::Malformed),
    }
}

fn optional_bool(fields: &Map<String, Value>, name: &str) -> Result<Option<bool>, ResponseError> {
    match fields.get(name) {
        Some(Value::Bool(value)) => Ok(Some(*value)),
        Some(_) => Err(ResponseError::WrongType),
        None => Ok(None),
    }
}

struct DirectTcpTransport;

impl BridgeTransport for DirectTcpTransport {
    fn request(
        &mut self,
        endpoint: BridgeEndpoint,
        timeout: RequestTimeout,
    ) -> Result<HttpResponse, TransportError> {
        let address = SocketAddr::from((Ipv4Addr::LOCALHOST, FIXED_BACKEND_PORT));
        let mut stream =
            TcpStream::connect_timeout(&address, timeout.connect).map_err(map_io_error)?;
        stream
            .set_write_timeout(Some(timeout.write))
            .map_err(map_io_error)?;
        stream
            .set_read_timeout(Some(timeout.read))
            .map_err(map_io_error)?;

        let request = build_request(endpoint);
        stream.write_all(&request).map_err(map_io_error)?;
        stream.flush().map_err(map_io_error)?;
        read_http_response(&mut stream, timeout.read)
    }
}

fn build_request(endpoint: BridgeEndpoint) -> Vec<u8> {
    format!(
        "{} {} HTTP/1.1\r\nHost: 127.0.0.1:8766\r\nConnection: close\r\nContent-Length: 0\r\n\r\n",
        endpoint.method(),
        endpoint.path()
    )
    .into_bytes()
}

fn map_io_error(error: io::Error) -> TransportError {
    match error.kind() {
        io::ErrorKind::TimedOut | io::ErrorKind::WouldBlock => TransportError::Timeout,
        _ => TransportError::Unavailable,
    }
}

fn read_http_response(
    stream: &mut TcpStream,
    read_timeout: Duration,
) -> Result<HttpResponse, TransportError> {
    let mut raw = Vec::with_capacity(4096);
    let mut header_info: Option<(usize, Option<usize>)> = None;
    let deadline = Instant::now() + read_timeout;

    loop {
        let remaining = deadline
            .checked_duration_since(Instant::now())
            .ok_or(TransportError::Timeout)?;
        stream
            .set_read_timeout(Some(remaining))
            .map_err(map_io_error)?;
        let mut chunk = [0_u8; 8192];
        let count = stream.read(&mut chunk).map_err(map_io_error)?;
        if count == 0 {
            break;
        }
        raw.extend_from_slice(&chunk[..count]);
        if raw.len() > MAX_HTTP_RESPONSE_BYTES {
            return Err(TransportError::Oversized);
        }

        if header_info.is_none() {
            if let Some(header_end) = find_header_end(&raw) {
                let (_, content_length) = parse_response_head(&raw[..header_end])?;
                if let Some(length) = content_length {
                    if length > MAX_HTTP_RESPONSE_BYTES.saturating_sub(header_end) {
                        return Err(TransportError::Oversized);
                    }
                    let response_end = header_end + length;
                    if raw.len() > response_end {
                        return Err(TransportError::Malformed);
                    }
                    if raw.len() == response_end {
                        return parse_http_response(&raw);
                    }
                }
                header_info = Some((header_end, content_length));
            }
        } else if let Some((header_end, Some(length))) = header_info {
            let response_end = header_end + length;
            if raw.len() > response_end {
                return Err(TransportError::Malformed);
            }
            if raw.len() == response_end {
                return parse_http_response(&raw);
            }
        }
    }

    parse_http_response(&raw)
}

fn parse_http_response(raw: &[u8]) -> Result<HttpResponse, TransportError> {
    if raw.len() > MAX_HTTP_RESPONSE_BYTES {
        return Err(TransportError::Oversized);
    }
    let header_end = find_header_end(raw).ok_or(TransportError::Malformed)?;
    let (status_code, content_length) = parse_response_head(&raw[..header_end])?;
    let body = &raw[header_end..];
    if let Some(length) = content_length {
        if length > MAX_HTTP_RESPONSE_BYTES.saturating_sub(header_end) {
            return Err(TransportError::Oversized);
        }
        if body.len() != length {
            return Err(TransportError::Malformed);
        }
    }
    Ok(HttpResponse {
        status_code,
        body: body.to_vec(),
    })
}

fn parse_response_head(raw_head: &[u8]) -> Result<(u16, Option<usize>), TransportError> {
    if !raw_head.ends_with(b"\r\n\r\n") {
        return Err(TransportError::Malformed);
    }
    let text = std::str::from_utf8(&raw_head[..raw_head.len() - 4])
        .map_err(|_| TransportError::Malformed)?;
    let mut lines = text.split("\r\n");
    let status_line = lines.next().ok_or(TransportError::Malformed)?;
    let mut status_parts = status_line.splitn(3, ' ');
    if status_parts.next() != Some("HTTP/1.1") {
        return Err(TransportError::Malformed);
    }
    let status_text = status_parts.next().ok_or(TransportError::Malformed)?;
    if status_text.len() != 3 || !status_text.bytes().all(|byte| byte.is_ascii_digit()) {
        return Err(TransportError::Malformed);
    }
    let status_code = status_text
        .parse::<u16>()
        .map_err(|_| TransportError::Malformed)?;

    let mut content_length = None;
    for line in lines {
        if line.is_empty() {
            continue;
        }
        let (name, value) = line.split_once(':').ok_or(TransportError::Malformed)?;
        if name.is_empty() || !name.bytes().all(|byte| byte.is_ascii()) {
            return Err(TransportError::Malformed);
        }
        if name.eq_ignore_ascii_case("transfer-encoding") {
            return Err(TransportError::Malformed);
        }
        if name.eq_ignore_ascii_case("content-length") {
            if content_length.is_some() {
                return Err(TransportError::Malformed);
            }
            let value = value.trim();
            if value.is_empty() || !value.bytes().all(|byte| byte.is_ascii_digit()) {
                return Err(TransportError::Malformed);
            }
            content_length = Some(
                value
                    .parse::<usize>()
                    .map_err(|_| TransportError::Oversized)?,
            );
        }
    }
    Ok((status_code, content_length))
}

fn find_header_end(raw: &[u8]) -> Option<usize> {
    raw.windows(4)
        .position(|window| window == b"\r\n\r\n")
        .map(|index| index + 4)
}

#[cfg(test)]
mod tests {
    use super::*;
    use crate::monitor_recovery::{LifecyclePhase, MonitorRecoveryBridge};
    use std::collections::VecDeque;
    use std::sync::{Arc, Mutex};

    #[derive(Clone, Debug, PartialEq, Eq)]
    struct RecordedRequest {
        endpoint: BridgeEndpoint,
        timeout: RequestTimeout,
    }

    struct ScriptedTransport {
        responses: VecDeque<Result<HttpResponse, TransportError>>,
        requests: Arc<Mutex<Vec<RecordedRequest>>>,
    }

    impl ScriptedTransport {
        fn new(
            responses: impl IntoIterator<Item = Result<HttpResponse, TransportError>>,
        ) -> (Self, Arc<Mutex<Vec<RecordedRequest>>>) {
            let requests = Arc::new(Mutex::new(Vec::new()));
            (
                Self {
                    responses: responses.into_iter().collect(),
                    requests: Arc::clone(&requests),
                },
                requests,
            )
        }
    }

    impl BridgeTransport for ScriptedTransport {
        fn request(
            &mut self,
            endpoint: BridgeEndpoint,
            timeout: RequestTimeout,
        ) -> Result<HttpResponse, TransportError> {
            self.requests
                .lock()
                .expect("request recording lock")
                .push(RecordedRequest { endpoint, timeout });
            self.responses
                .pop_front()
                .expect("scripted response available")
        }
    }

    fn valid_lease() -> LifecycleLease {
        LifecycleLease {
            generation: 1,
            phase: LifecyclePhase::OwnedRunning,
            health_pid: 42,
            owned_pid: 42,
            process_pid: 42,
            startup_gate_released: true,
            state_scope: "a".repeat(64),
        }
    }

    fn response(status_code: u16, body: Value) -> HttpResponse {
        HttpResponse {
            status_code,
            body: serde_json::to_vec(&body).expect("test JSON serializes"),
        }
    }

    fn status_body(running: bool, ready: bool) -> Value {
        serde_json::json!({"ok": true, "running": running, "ready": ready})
    }

    fn command_body(running: bool, ready: bool) -> Value {
        serde_json::json!({
            "ok": true,
            "running": running,
            "status": {"ok": true, "running": running, "ready": ready}
        })
    }

    #[test]
    fn status_success_uses_only_the_fixed_status_endpoint() {
        let (transport, requests) =
            ScriptedTransport::new([Ok(response(200, status_body(true, true)))]);
        let mut bridge = PythonMonitorRecoveryBridge::with_transport(Box::new(transport));

        assert_eq!(
            bridge.status(&valid_lease()),
            Ok(MonitorSnapshot {
                running: true,
                ready: true
            })
        );
        assert_eq!(
            requests.lock().expect("request recording lock").as_slice(),
            &[RecordedRequest {
                endpoint: BridgeEndpoint::Status,
                timeout: STATUS_TIMEOUT
            }]
        );
        assert_eq!(
            String::from_utf8(build_request(BridgeEndpoint::Status)).expect("ASCII request"),
            "GET /api/v1/bridge/status HTTP/1.1\r\nHost: 127.0.0.1:8766\r\nConnection: close\r\nContent-Length: 0\r\n\r\n"
        );
    }

    #[test]
    fn stop_success_requires_a_stopped_snapshot_and_fixed_post_path() {
        let (transport, requests) =
            ScriptedTransport::new([Ok(response(200, command_body(false, false)))]);
        let mut bridge = PythonMonitorRecoveryBridge::with_transport(Box::new(transport));

        assert_eq!(bridge.stop(&valid_lease()), Ok(()));
        assert_eq!(
            requests.lock().expect("request recording lock").as_slice(),
            &[RecordedRequest {
                endpoint: BridgeEndpoint::Stop,
                timeout: STOP_TIMEOUT
            }]
        );
        assert_eq!(
            String::from_utf8(build_request(BridgeEndpoint::Stop)).expect("ASCII request"),
            "POST /api/v1/bridge/stop HTTP/1.1\r\nHost: 127.0.0.1:8766\r\nConnection: close\r\nContent-Length: 0\r\n\r\n"
        );
    }

    #[test]
    fn start_success_requires_running_and_ready_and_fixed_post_path() {
        let (transport, requests) =
            ScriptedTransport::new([Ok(response(200, command_body(true, true)))]);
        let mut bridge = PythonMonitorRecoveryBridge::with_transport(Box::new(transport));

        assert_eq!(bridge.start(&valid_lease()), Ok(()));
        assert_eq!(
            requests.lock().expect("request recording lock").as_slice(),
            &[RecordedRequest {
                endpoint: BridgeEndpoint::Start,
                timeout: START_TIMEOUT
            }]
        );
        assert_eq!(
            String::from_utf8(build_request(BridgeEndpoint::Start)).expect("ASCII request"),
            "POST /api/v1/bridge/start HTTP/1.1\r\nHost: 127.0.0.1:8766\r\nConnection: close\r\nContent-Length: 0\r\n\r\n"
        );
    }

    #[test]
    fn malformed_oversized_and_non_success_responses_are_unavailable() {
        let malformed = HttpResponse {
            status_code: 200,
            body: b"not-json".to_vec(),
        };
        let oversized = HttpResponse {
            status_code: 200,
            body: vec![b'x'; MAX_HTTP_RESPONSE_BYTES + 1],
        };
        let non_success = response(201, status_body(true, true));
        let (transport, _) =
            ScriptedTransport::new([Ok(malformed), Ok(oversized), Ok(non_success)]);
        let mut bridge = PythonMonitorRecoveryBridge::with_transport(Box::new(transport));
        let lease = valid_lease();

        assert_eq!(
            bridge.status(&lease),
            Err(RecoveryError::MonitorUnavailable)
        );
        assert_eq!(
            bridge.status(&lease),
            Err(RecoveryError::MonitorUnavailable)
        );
        assert_eq!(
            bridge.status(&lease),
            Err(RecoveryError::MonitorUnavailable)
        );
    }

    #[test]
    fn strict_boolean_and_state_validation_rejects_wrong_responses() {
        let wrong_boolean = response(
            200,
            serde_json::json!({"ok": true, "running": "true", "ready": true}),
        );
        let (transport, _) = ScriptedTransport::new([
            Ok(response(200, command_body(true, false))),
            Ok(response(200, command_body(true, true))),
            Ok(wrong_boolean),
        ]);
        let mut bridge = PythonMonitorRecoveryBridge::with_transport(Box::new(transport));
        let lease = valid_lease();

        assert_eq!(bridge.start(&lease), Err(RecoveryError::MonitorNotReady));
        assert_eq!(bridge.stop(&lease), Err(RecoveryError::MonitorStillRunning));
        assert_eq!(
            bridge.status(&lease),
            Err(RecoveryError::MonitorUnavailable)
        );
    }

    #[test]
    fn ready_without_running_is_rejected_as_an_inconsistent_snapshot() {
        let (transport, _) = ScriptedTransport::new([Ok(response(200, status_body(false, true)))]);
        let mut bridge = PythonMonitorRecoveryBridge::with_transport(Box::new(transport));

        assert_eq!(
            bridge.status(&valid_lease()),
            Err(RecoveryError::MonitorUnavailable)
        );
    }

    #[test]
    fn timeout_and_unavailable_transport_fail_closed() {
        let (transport, _) = ScriptedTransport::new([
            Err(TransportError::Timeout),
            Err(TransportError::Unavailable),
        ]);
        let mut bridge = PythonMonitorRecoveryBridge::with_transport(Box::new(transport));
        let lease = valid_lease();

        assert_eq!(
            bridge.status(&lease),
            Err(RecoveryError::MonitorUnavailable)
        );
        assert_eq!(
            bridge.status(&lease),
            Err(RecoveryError::MonitorUnavailable)
        );
    }

    #[test]
    fn ineligible_lease_is_rejected_before_transport() {
        let (transport, requests) =
            ScriptedTransport::new([Ok(response(200, status_body(true, true)))]);
        let mut bridge = PythonMonitorRecoveryBridge::with_transport(Box::new(transport));
        let mut lease = valid_lease();
        lease.phase = LifecyclePhase::Terminating;

        assert_eq!(bridge.status(&lease), Err(RecoveryError::LeaseInvalid));
        assert!(requests.lock().expect("request recording lock").is_empty());
    }

    #[test]
    fn raw_http_parser_requires_bounded_well_formed_responses() {
        let raw = b"HTTP/1.1 200 OK\r\nContent-Length: 2\r\n\r\n{}";
        assert_eq!(
            parse_http_response(raw),
            Ok(HttpResponse {
                status_code: 200,
                body: b"{}".to_vec()
            })
        );
        assert_eq!(
            parse_http_response(b"HTTP/1.1 200 OK\n\n{}"),
            Err(TransportError::Malformed)
        );
        assert_eq!(
            parse_http_response(b"HTTP/1.1 200 OK\r\nContent-Length: 1\r\n\r\n{}"),
            Err(TransportError::Malformed)
        );
        assert_eq!(
            parse_http_response(b"HTTP/1.1 200 OK\r\nTransfer-Encoding: chunked\r\n\r\n0\r\n\r\n"),
            Err(TransportError::Malformed)
        );
        assert_eq!(
            parse_http_response(&vec![b'x'; MAX_HTTP_RESPONSE_BYTES + 1]),
            Err(TransportError::Oversized)
        );
    }
}
