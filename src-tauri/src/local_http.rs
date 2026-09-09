//! Bounded HTTP/1 response framing for direct loopback requests. No payloads in errors.

use std::collections::BTreeMap;
use std::fmt;
use std::io::{self, Read};
use std::net::TcpStream;
use std::time::Instant;

const MAX_HEADER_BYTES: usize = 16 * 1024;

#[derive(Debug)]
pub struct Response {
    pub status: u16,
    pub headers: BTreeMap<String, String>,
    pub body: Vec<u8>,
}

#[derive(Debug)]
pub struct HttpError {
    pub stage: &'static str,
    pub reason: &'static str,
    pub received: usize,
    pub expected: Option<usize>,
    pub status: Option<u16>,
    pub io_kind: Option<io::ErrorKind>,
    pub os_code: Option<i32>,
}

impl HttpError {
    pub fn new(stage: &'static str, reason: &'static str) -> Self {
        Self {
            stage,
            reason,
            received: 0,
            expected: None,
            status: None,
            io_kind: None,
            os_code: None,
        }
    }

    pub fn io(stage: &'static str, error: io::Error) -> Self {
        Self {
            io_kind: Some(error.kind()),
            os_code: error.raw_os_error(),
            ..Self::new(stage, "io_error")
        }
    }
}

impl fmt::Display for HttpError {
    fn fmt(&self, f: &mut fmt::Formatter<'_>) -> fmt::Result {
        write!(
            f,
            "stage={} reason={} received={} expected={:?} status={:?} io={:?} os_code={:?}",
            self.stage,
            self.reason,
            self.received,
            self.expected,
            self.status,
            self.io_kind,
            self.os_code
        )
    }
}

impl std::error::Error for HttpError {}

struct DeadlineReader<'a> {
    stream: &'a mut TcpStream,
    deadline: Instant,
}

impl Read for DeadlineReader<'_> {
    fn read(&mut self, output: &mut [u8]) -> io::Result<usize> {
        let remaining = self
            .deadline
            .checked_duration_since(Instant::now())
            .filter(|value| !value.is_zero())
            .ok_or_else(|| io::Error::from(io::ErrorKind::TimedOut))?;
        self.stream.set_read_timeout(Some(remaining))?;
        self.stream.read(output)
    }
}

pub fn read_response(
    stream: &mut TcpStream,
    deadline: Instant,
    limit: usize,
) -> Result<Response, HttpError> {
    read_framed(&mut DeadlineReader { stream, deadline }, limit)
}

fn header_end(bytes: &[u8]) -> Option<usize> {
    bytes
        .windows(4)
        .position(|part| part == b"\r\n\r\n")
        .map(|offset| offset + 4)
}

fn token(text: &str) -> bool {
    !text.is_empty()
        && text
            .bytes()
            .all(|b| b.is_ascii_alphanumeric() || b"!#$%&'*+-.^_`|~".contains(&b))
}

fn parse_head(bytes: &[u8]) -> Result<Response, HttpError> {
    let invalid = || HttpError::new("headers", "invalid_or_duplicate_header");
    let head = std::str::from_utf8(bytes).map_err(|_| invalid())?;
    let mut lines = head.split("\r\n");
    let mut status_line = lines.next().ok_or_else(invalid)?.splitn(3, ' ');
    if !matches!(status_line.next(), Some("HTTP/1.1" | "HTTP/1.0")) {
        return Err(invalid());
    }
    let code = status_line.next().ok_or_else(invalid)?;
    let status = code.parse::<u16>().map_err(|_| invalid())?;
    if code.len() != 3 || !(200..=599).contains(&status) {
        return Err(invalid());
    }
    let mut headers = BTreeMap::new();
    for line in lines.filter(|line| !line.is_empty()) {
        let (name, value) = line.split_once(':').ok_or_else(invalid)?;
        if !token(name) || value.bytes().any(|b| b.is_ascii_control() && b != b'\t') {
            return Err(invalid());
        }
        // In particular, duplicate ownership proof or framing headers must never be merged.
        if headers
            .insert(name.to_ascii_lowercase(), value.trim().to_owned())
            .is_some()
        {
            return Err(invalid());
        }
    }
    Ok(Response {
        status,
        headers,
        body: Vec::new(),
    })
}

enum Framing {
    Empty,
    Length(usize),
    Chunked,
    Close,
}

fn framing(response: &Response) -> Result<Framing, HttpError> {
    let length = response.headers.get("content-length");
    let transfer = response.headers.get("transfer-encoding");
    if length.is_some() && transfer.is_some() {
        return Err(HttpError::new("headers", "ambiguous_framing"));
    }
    let length = length
        .map(|text| {
            if text.is_empty() || !text.bytes().all(|b| b.is_ascii_digit()) {
                return Err(HttpError::new("headers", "invalid_content_length"));
            }
            text.parse::<usize>()
                .map_err(|_| HttpError::new("headers", "invalid_content_length"))
        })
        .transpose()?;
    if response.status == 204 || response.status == 304 {
        if transfer.is_some() || (response.status == 204 && length.is_some_and(|n| n != 0)) {
            return Err(HttpError::new("headers", "invalid_bodyless_framing"));
        }
        return Ok(Framing::Empty);
    }
    if let Some(transfer) = transfer {
        return if transfer.eq_ignore_ascii_case("chunked") {
            Ok(Framing::Chunked)
        } else {
            Err(HttpError::new("headers", "unsupported_transfer_encoding"))
        };
    }
    Ok(length.map(Framing::Length).unwrap_or(Framing::Close))
}

// Returns only complete decoded bodies. The wire-byte limit also bounds chunk overhead.
fn chunks(bytes: &[u8], limit: usize) -> Result<Option<Vec<u8>>, HttpError> {
    let mut cursor = 0;
    let mut body = Vec::new();
    loop {
        let Some(line_size) = bytes[cursor..].windows(2).position(|part| part == b"\r\n") else {
            return Ok(None);
        };
        let line = std::str::from_utf8(&bytes[cursor..cursor + line_size])
            .map_err(|_| HttpError::new("body", "invalid_chunk_size"))?;
        let size_text = line.split(';').next().unwrap_or_default();
        if size_text.is_empty()
            || !size_text.bytes().all(|b| b.is_ascii_hexdigit())
            || line.bytes().any(|b| b.is_ascii_control())
        {
            return Err(HttpError::new("body", "invalid_chunk_size"));
        }
        let size = usize::from_str_radix(size_text, 16)
            .map_err(|_| HttpError::new("body", "invalid_chunk_size"))?;
        cursor += line_size + 2;
        if size == 0 {
            // Our backend has no trailer protocol. Do not accept a proof moved into trailers.
            if bytes.len() < cursor + 2 {
                return Ok(None);
            }
            if bytes.len() != cursor + 2 || &bytes[cursor..] != b"\r\n" {
                return Err(HttpError::new("body", "unexpected_trailer_or_extra_bytes"));
            }
            return Ok(Some(body));
        }
        if size > limit.saturating_sub(body.len()) {
            return Err(HttpError::new("body", "response_too_large"));
        }
        let end = cursor
            .checked_add(size)
            .and_then(|n| n.checked_add(2))
            .ok_or_else(|| HttpError::new("body", "response_too_large"))?;
        if bytes.len() < end {
            return Ok(None);
        }
        if &bytes[end - 2..end] != b"\r\n" {
            return Err(HttpError::new("body", "invalid_chunk_terminator"));
        }
        body.extend_from_slice(&bytes[cursor..end - 2]);
        cursor = end;
    }
}

fn read_framed(reader: &mut impl Read, limit: usize) -> Result<Response, HttpError> {
    let mut raw = Vec::new();
    let mut head: Option<(usize, Response, Framing)> = None;
    loop {
        if head.is_none() {
            if let Some(end) = header_end(&raw) {
                if end > MAX_HEADER_BYTES {
                    return Err(HttpError::new("headers", "headers_too_large"));
                }
                let response = parse_head(&raw[..end])?;
                let mode = framing(&response)?;
                if matches!(mode, Framing::Length(n) if n > limit.saturating_sub(end)) {
                    let mut error = HttpError::new("headers", "response_too_large");
                    error.status = Some(response.status);
                    error.received = raw.len();
                    return Err(error);
                }
                head = Some((end, response, mode));
            } else if raw.len() >= MAX_HEADER_BYTES {
                return Err(HttpError::new("headers", "headers_too_large"));
            }
        }
        if let Some((end, response, mode)) = &head {
            let body = &raw[*end..];
            // A complete Content-Length body or 204 is success immediately. Waiting for TCP EOF
            // lets a later close/reset/keep-alive turn a successful backend reply into a failure.
            let complete = match mode {
                Framing::Empty if body.is_empty() => Some(Vec::new()),
                Framing::Length(n) if body.len() == *n => Some(body.to_vec()),
                Framing::Length(n) if body.len() < *n => None,
                Framing::Chunked => chunks(body, limit)?,
                Framing::Close => None,
                _ => return Err(HttpError::new("body", "extra_response_bytes")),
            };
            if let Some(body) = complete {
                return Ok(Response {
                    status: response.status,
                    headers: response.headers.clone(),
                    body,
                });
            }
        }
        let mut chunk = [0u8; 4096];
        let mut error = match reader.read(&mut chunk) {
            Ok(0) => {
                if let Some((end, mut response, Framing::Close)) = head {
                    response.body = raw[end..].to_vec();
                    return Ok(response);
                }
                HttpError::new("body", "truncated_response")
            }
            Ok(count) if count <= limit.saturating_sub(raw.len()) => {
                raw.extend_from_slice(&chunk[..count]);
                continue;
            }
            Ok(_) => HttpError::new("body", "response_too_large"),
            Err(error) if error.kind() == io::ErrorKind::Interrupted => continue,
            Err(error) => HttpError::io(if head.is_some() { "body" } else { "headers" }, error),
        };
        error.received = raw.len();
        if let Some((end, response, mode)) = head {
            error.status = Some(response.status);
            if let Framing::Length(n) = mode {
                error.expected = end.checked_add(n);
            }
        }
        return Err(error);
    }
}

#[cfg(test)]
mod tests {
    use super::*;
    use std::io::{Cursor, Write};
    use std::net::TcpListener;
    use std::sync::mpsc;
    use std::time::Duration;

    struct ResetAfter {
        bytes: Cursor<Vec<u8>>,
        fragment: usize,
    }
    impl Read for ResetAfter {
        fn read(&mut self, out: &mut [u8]) -> io::Result<usize> {
            if self.bytes.position() as usize == self.bytes.get_ref().len() {
                return Err(io::Error::from(io::ErrorKind::ConnectionReset));
            }
            let length = out.len().min(self.fragment);
            self.bytes.read(&mut out[..length])
        }
    }
    fn reset_reply(bytes: &[u8], fragment: usize) -> Result<Response, HttpError> {
        read_framed(
            &mut ResetAfter {
                bytes: Cursor::new(bytes.to_vec()),
                fragment,
            },
            128 * 1024,
        )
    }

    #[test]
    fn complete_responses_do_not_wait_for_reset_or_eof() {
        for fragment in [1, 7, 4096] {
            let response = reset_reply(
                b"HTTP/1.1 200 OK\r\nContent-Length: 6\r\n\r\n\xe5\x8f\x91\xe7\xa5\xa8",
                fragment,
            )
            .unwrap();
            assert_eq!(response.body, "发票".as_bytes());
            let response = reset_reply(
                b"HTTP/1.1 204 No Content\r\nX-Proof: synthetic\r\n\r\n",
                fragment,
            )
            .unwrap();
            assert_eq!(response.status, 204);
            assert_eq!(response.headers["x-proof"], "synthetic");
        }
    }

    #[test]
    fn chunked_json_is_decoded_with_fragmented_headers_and_body() {
        let bytes = b"HTTP/1.1 200 OK\r\nTransfer-Encoding: chunked\r\n\r\n4;name=value\r\n{\"ok\r\n7\r\n\":true}\r\n0\r\n\r\n";
        for fragment in [1, 7, 4096] {
            assert_eq!(reset_reply(bytes, fragment).unwrap().body, b"{\"ok\":true}");
        }
    }

    #[test]
    fn incomplete_responses_fail_even_after_success_status() {
        let bytes = b"HTTP/1.1 200 OK\r\nContent-Length: 9\r\n\r\nshort";
        let error = reset_reply(bytes, 4096).unwrap_err();
        assert_eq!(error.io_kind, Some(io::ErrorKind::ConnectionReset));
        assert_eq!(error.status, Some(200));
        assert!(error.expected.unwrap() > error.received);
        assert_eq!(
            read_framed(&mut Cursor::new(bytes), 4096)
                .unwrap_err()
                .reason,
            "truncated_response"
        );
        assert!(reset_reply(
            b"HTTP/1.1 200 OK\r\nTransfer-Encoding: chunked\r\n\r\n2\r\n{}\r\n",
            1
        )
        .is_err());
    }

    #[test]
    fn ambiguous_oversized_or_malformed_responses_are_rejected() {
        for bytes in [
            b"HTTP/1.1 200 OK\r\nContent-Length: 0\r\nContent-Length: 0\r\n\r\n".as_slice(),
            b"HTTP/1.1 200 OK\r\nContent-Length: 0\r\nTransfer-Encoding: chunked\r\n\r\n",
            b"HTTP/1.1 204 No Content\r\nX-Proof: a\r\nx-proof: b\r\n\r\n",
            b"HTTP/1.1 204 No Content\r\nContent-Length: 1\r\n\r\nx",
            b"HTTP/1.1 200 OK\r\nContent-Length: +2\r\n\r\nOK",
            b"HTTP/1.1 200 OK\r\nContent-Length: 999999999999999999999999\r\n\r\n",
            b"HTTP/1.1 200 OK\r\nContent-Length: 1\r\n\r\nextra",
            b"HTTP/1.1 200 OK\r\nTransfer-Encoding: gzip\r\n\r\n",
            b"HTTP/1.1 200 OK\r\nTransfer-Encoding: chunked\r\n\r\nz\r\n",
            b"HTTP/1.1 200 OK\r\nTransfer-Encoding: chunked\r\n\r\n0\r\nX-Proof: a\r\n\r\n",
        ] {
            assert!(reset_reply(bytes, 4096).is_err(), "{:?}", bytes);
        }
        assert_eq!(
            read_framed(
                &mut Cursor::new(b"HTTP/1.1 200 OK\r\nContent-Length: 9000\r\n\r\n"),
                128
            )
            .unwrap_err()
            .reason,
            "response_too_large"
        );
        assert_eq!(
            read_framed(&mut Cursor::new(vec![b'x'; MAX_HEADER_BYTES]), 32 * 1024)
                .unwrap_err()
                .reason,
            "headers_too_large"
        );
    }

    #[test]
    fn close_delimited_reply_requires_clean_eof() {
        let bytes = b"HTTP/1.0 200 OK\r\n\r\nlegacy";
        assert_eq!(
            read_framed(&mut Cursor::new(bytes), 4096).unwrap().body,
            b"legacy"
        );
        assert!(reset_reply(bytes, 4096).is_err());
    }

    #[test]
    fn error_does_not_contain_server_payload_or_headers() {
        let error = reset_reply(b"HTTP/1.1 200 OK\r\nX-Secret: never-log-this\r\nContent-Length: 100\r\n\r\nprivate-body", 4096).unwrap_err();
        let rendered = format!("{error:?} {error}");
        assert!(!rendered.contains("never-log-this"));
        assert!(!rendered.contains("private-body"));
    }

    #[test]
    fn real_socket_returns_complete_body_while_server_stays_open() {
        let listener = TcpListener::bind("127.0.0.1:0").unwrap();
        let address = listener.local_addr().unwrap();
        let (release, held) = mpsc::channel();
        let server = std::thread::spawn(move || {
            let (mut stream, _) = listener.accept().unwrap();
            stream
                .write_all(b"HTTP/1.1 200 OK\r\nContent-Length: 2\r\n\r\nOK")
                .unwrap();
            let _ = held.recv_timeout(Duration::from_secs(2));
        });
        let mut stream = TcpStream::connect(address).unwrap();
        let result = read_response(&mut stream, Instant::now() + Duration::from_secs(1), 4096);
        let _ = release.send(());
        server.join().unwrap();
        assert_eq!(result.unwrap().body, b"OK");
    }

    #[test]
    fn expired_deadline_fails_without_waiting_for_bytes() {
        let listener = TcpListener::bind("127.0.0.1:0").unwrap();
        let mut stream = TcpStream::connect(listener.local_addr().unwrap()).unwrap();
        let (_server, _) = listener.accept().unwrap();
        assert_eq!(
            read_response(&mut stream, Instant::now(), 4096)
                .unwrap_err()
                .io_kind,
            Some(io::ErrorKind::TimedOut)
        );
    }

    #[test]
    fn continuous_slow_body_cannot_extend_the_total_deadline() {
        let listener = TcpListener::bind("127.0.0.1:0").unwrap();
        let address = listener.local_addr().unwrap();
        let (release, stop) = mpsc::channel();
        let server = std::thread::spawn(move || {
            let (mut stream, _) = listener.accept().unwrap();
            if stream
                .write_all(b"HTTP/1.1 200 OK\r\nContent-Length: 1000\r\n\r\n")
                .is_err()
            {
                return;
            }
            for _ in 0..1000 {
                if stream.write_all(b"x").is_err()
                    || stop.recv_timeout(Duration::from_millis(5)).is_ok()
                {
                    break;
                }
            }
        });
        let mut stream = TcpStream::connect(address).unwrap();
        let started = Instant::now();
        let result = read_response(&mut stream, started + Duration::from_millis(100), 4096);
        let _ = release.send(());
        server.join().unwrap();
        assert!(matches!(
            result.unwrap_err().io_kind,
            Some(io::ErrorKind::TimedOut | io::ErrorKind::WouldBlock)
        ));
        assert!(started.elapsed() < Duration::from_secs(2));
    }
}
