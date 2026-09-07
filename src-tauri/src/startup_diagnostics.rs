//! Read-only startup diagnostics. Listener observations never grant backend ownership.

use sha2::{Digest, Sha256};
use std::path::{Path, PathBuf};

fn identity_path(path: &Path) -> String {
    // A fresh runtime does not exist yet. Resolve its nearest existing ancestor so
    // first launch and subsequent launches derive the same singleton key.
    let mut ancestor = path.to_path_buf();
    let mut missing = Vec::new();
    let resolved = loop {
        if let Ok(mut resolved) = ancestor.canonicalize() {
            for component in missing.iter().rev() {
                resolved.push(component);
            }
            break resolved;
        }
        let Some(name) = ancestor.file_name().map(|name| name.to_os_string()) else {
            break path.to_path_buf();
        };
        missing.push(name);
        if !ancestor.pop() {
            break path.to_path_buf();
        }
    };
    let text = resolved.to_string_lossy().to_lowercase();
    if let Some(unc) = text.strip_prefix(r"\\?\unc\") {
        format!(r"\\{unc}")
    } else {
        text.strip_prefix(r"\\?\").unwrap_or(&text).to_owned()
    }
}

fn service_claim() -> Option<String> {
    use std::io::{Read, Write};
    use std::net::TcpStream;
    use std::time::{Duration, Instant};
    let budget = Duration::from_secs(1);
    let deadline = Instant::now() + budget;
    let mut stream =
        TcpStream::connect_timeout(&crate::backend::fixed_backend_socket_addr(), budget).ok()?;
    stream.set_write_timeout(Some(budget)).ok()?;
    stream
        .write_all(
            b"GET /api/v1/health HTTP/1.1\r\nHost: 127.0.0.1:8766\r\nConnection: close\r\n\r\n",
        )
        .ok()?;
    let mut raw = Vec::new();
    loop {
        stream
            .set_read_timeout(Some(deadline.checked_duration_since(Instant::now())?))
            .ok()?;
        let mut chunk = [0u8; 4096];
        let count = stream.read(&mut chunk).ok()?;
        if count == 0 {
            break;
        }
        if raw.len() + count > 32 * 1024 {
            return None;
        }
        raw.extend_from_slice(&chunk[..count]);
    }
    let separator = raw.windows(4).position(|part| part == b"\r\n\r\n")?;
    if !raw.starts_with(b"HTTP/1.1 200 ") && !raw.starts_with(b"HTTP/1.0 200 ") {
        return None;
    }
    let payload: serde_json::Value = serde_json::from_slice(&raw[separator + 4..]).ok()?;
    summarize_claim(&payload)
}

fn summarize_claim(payload: &serde_json::Value) -> Option<String> {
    if payload.get("ok")?.as_bool() != Some(true) {
        return None;
    }
    let pid = payload.get("pid")?.as_u64()?;
    let mut text = format!("\n服务自报信息（仅供诊断，不作为所有权证明）：PID {pid}\n");
    // Only these public identity fields are displayed, never arbitrary JSON or host credentials.
    for key in [
        "package_type",
        "product_version",
        "config_path",
        "runtime_dir",
    ] {
        if let Some(value) = payload.get(key).and_then(|value| value.as_str()) {
            let value: String = value
                .chars()
                .filter(|c| !c.is_control())
                .take(600)
                .collect();
            text.push_str(&format!("{key}: {value}\n"));
        }
    }
    Some(text)
}

pub fn instance_identifier(base: &str, executable: &Path, runtime: &Path) -> String {
    // Scope the existing single-instance plugin to the exact installation and state root.
    // A different dev/test/package must reach the port guard, not wake an unrelated host.
    let mut hash = Sha256::new();
    for path in [executable, runtime] {
        let text = identity_path(path);
        hash.update((text.len() as u64).to_le_bytes());
        hash.update(text.as_bytes());
    }
    format!("{base}.instance.{:x}", hash.finalize())
}

pub fn report(reason: &str, runtime: Option<&Path>, config: Option<&Path>) -> String {
    let executable = std::env::current_exe().unwrap_or_default();
    let mut text = format!(
        "InvoiceHub\n{reason}\n\n本次程序：{}\n本次进程 PID：{}\n服务地址：{}\n",
        executable.display(),
        std::process::id(),
        crate::backend_origin()
    );
    if let Some(config) = config {
        text.push_str(&format!("本次配置：{}\n", config.display()));
    }
    if let Some(runtime) = runtime {
        text.push_str(&format!("本次运行目录：{}\n", runtime.display()));
    }
    #[cfg(windows)]
    text.push_str(&windows::listener_report(crate::FIXED_BACKEND_PORT));
    if let Some(claim) = service_claim() {
        text.push_str(&claim);
    }
    text.push_str("\n如被其他环境占用，请先从对应 InvoiceHub 的页面或托盘完整退出，再重试。\n任务管理器可搜索 InvoiceHub；后台 Python 请在“详细信息”按上述 PID 定位。\n程序路径不可读表示权限受限或进程已退出，不表示没有占用。诊断不会结束其他进程。\n");
    text
}

pub fn present(reason: &str, runtime: Option<&Path>, config: Option<&Path>) {
    let mut text = report(reason, runtime, config);
    let directory = runtime.map(Path::to_path_buf).or_else(|| {
        std::env::var_os("LOCALAPPDATA")
            .map(|root| PathBuf::from(root).join("InvoiceHub").join("diagnostics"))
    });
    if let Some(directory) = directory {
        let path = directory.join(format!("startup-diagnostic-{}.txt", std::process::id()));
        text.push_str(&format!("\n诊断文件：{}\n", path.display()));
        if std::fs::create_dir_all(&directory)
            .and_then(|_| std::fs::write(&path, &text))
            .is_err()
        {
            text.push_str("诊断文件写入失败，可在此对话框按 Ctrl+C 复制。\n");
        }
    }
    eprintln!("{text}");
    #[cfg(windows)]
    if !std::env::args().any(|argument| argument == "--no-startup-dialog") {
        windows::show_message(&text);
    }
}

#[cfg(windows)]
mod windows {
    use std::{collections::BTreeSet, mem::size_of};
    use windows_sys::Win32::{
        Foundation::{CloseHandle, ERROR_INSUFFICIENT_BUFFER, INVALID_HANDLE_VALUE},
        NetworkManagement::IpHelper::{
            GetExtendedTcpTable, MIB_TCP6ROW_OWNER_PID, MIB_TCPROW_OWNER_PID,
            TCP_TABLE_OWNER_PID_LISTENER,
        },
        Networking::WinSock::{AF_INET, AF_INET6},
        System::{
            Diagnostics::ToolHelp::{
                CreateToolhelp32Snapshot, Process32FirstW, Process32NextW, PROCESSENTRY32W,
                TH32CS_SNAPPROCESS,
            },
            Threading::{
                OpenProcess, QueryFullProcessImageNameW, PROCESS_QUERY_LIMITED_INFORMATION,
            },
        },
        UI::WindowsAndMessaging::{
            MessageBoxW, MB_ICONINFORMATION, MB_OK, MB_SETFOREGROUND, MB_TOPMOST,
        },
    };

    fn tcp_rows<T: Copy>(family: u16) -> Result<Vec<T>, u32> {
        let mut bytes = 0u32;
        // The table can grow between calls; bounded retries preserve a useful failure report.
        for _ in 0..3 {
            let mut buffer = vec![0u32; (bytes as usize).div_ceil(4).max(1)];
            let result = unsafe {
                GetExtendedTcpTable(
                    buffer.as_mut_ptr().cast(),
                    &mut bytes,
                    0,
                    family as u32,
                    TCP_TABLE_OWNER_PID_LISTENER,
                    0,
                )
            };
            if result == ERROR_INSUFFICIENT_BUFFER && bytes <= 4 * 1024 * 1024 {
                continue;
            }
            if result != 0 {
                return Err(result);
            }
            let count = buffer[0] as usize;
            if count > (buffer.len() * 4 - 4) / size_of::<T>() {
                return Err(13);
            }
            return Ok((0..count)
                .map(|index| unsafe {
                    buffer
                        .as_ptr()
                        .cast::<u8>()
                        .add(4 + index * size_of::<T>())
                        .cast::<T>()
                        .read_unaligned()
                })
                .collect());
        }
        Err(ERROR_INSUFFICIENT_BUFFER)
    }

    fn process(pid: u32) -> (String, Option<u32>) {
        let mut name = "程序名称不可读".to_owned();
        let mut parent = None;
        unsafe {
            let snapshot = CreateToolhelp32Snapshot(TH32CS_SNAPPROCESS, 0);
            if snapshot != INVALID_HANDLE_VALUE {
                let mut entry: PROCESSENTRY32W = std::mem::zeroed();
                entry.dwSize = size_of::<PROCESSENTRY32W>() as u32;
                let mut found = Process32FirstW(snapshot, &mut entry);
                while found != 0 {
                    if entry.th32ProcessID == pid {
                        let end = entry
                            .szExeFile
                            .iter()
                            .position(|c| *c == 0)
                            .unwrap_or(entry.szExeFile.len());
                        name = String::from_utf16_lossy(&entry.szExeFile[..end]);
                        parent = Some(entry.th32ParentProcessID);
                        break;
                    }
                    found = Process32NextW(snapshot, &mut entry);
                }
                CloseHandle(snapshot);
            }
            let handle = OpenProcess(PROCESS_QUERY_LIMITED_INFORMATION, 0, pid);
            if !handle.is_null() {
                let mut path = vec![0u16; 32768];
                let mut length = path.len() as u32;
                if QueryFullProcessImageNameW(handle, 0, path.as_mut_ptr(), &mut length) != 0 {
                    name = String::from_utf16_lossy(&path[..length as usize]);
                }
                CloseHandle(handle);
            }
        }
        (name, parent)
    }

    pub fn listener_report(port: u16) -> String {
        let mut pids = BTreeSet::new();
        let mut errors = Vec::new();
        match tcp_rows::<MIB_TCPROW_OWNER_PID>(AF_INET) {
            Ok(rows) => {
                for row in rows {
                    if u16::from_be(row.dwLocalPort as u16) == port
                        && (row.dwLocalAddr == 0 || row.dwLocalAddr.to_ne_bytes() == [127, 0, 0, 1])
                    {
                        pids.insert(row.dwOwningPid);
                    }
                }
            }
            Err(code) => errors.push(format!("IPv4 查询失败：{code}")),
        }
        match tcp_rows::<MIB_TCP6ROW_OWNER_PID>(AF_INET6) {
            Ok(rows) => {
                for row in rows {
                    if u16::from_be(row.dwLocalPort as u16) == port && row.ucLocalAddr == [0; 16] {
                        pids.insert(row.dwOwningPid);
                    }
                }
            }
            Err(code) => errors.push(format!("IPv6 查询失败：{code}")),
        }
        let mut text = format!("\n端口 {port} 监听检查：\n");
        if pids.is_empty() {
            text.push_str("未发现监听者；若仍无法绑定，请检查端口保留或安全软件。\n");
        }
        for pid in pids.iter().take(8) {
            let (name, parent) = process(*pid);
            text.push_str(&format!("占用 PID：{pid}\n程序：{name}\n"));
            if let Some(parent) = parent.filter(|parent| *parent != 0) {
                text.push_str(&format!(
                    "父进程 PID：{parent}\n父进程程序：{}\n",
                    process(parent).0
                ));
            }
        }
        for error in errors {
            text.push_str(&format!("{error}\n"));
        }
        text
    }

    pub fn show_message(text: &str) {
        let text: Vec<u16> = text.encode_utf16().chain(Some(0)).collect();
        let title: Vec<u16> = "InvoiceHub 启动与运行诊断"
            .encode_utf16()
            .chain(Some(0))
            .collect();
        unsafe {
            MessageBoxW(
                std::ptr::null_mut(),
                text.as_ptr(),
                title.as_ptr(),
                MB_OK | MB_ICONINFORMATION | MB_SETFOREGROUND | MB_TOPMOST,
            );
        }
    }

    #[test]
    fn real_listener_is_reported_by_pid() {
        let listener = std::net::TcpListener::bind("127.0.0.1:0").unwrap();
        let report = listener_report(listener.local_addr().unwrap().port());
        assert!(
            report.contains(&format!("占用 PID：{}", std::process::id())),
            "{report}"
        );
    }
}

#[cfg(test)]
mod tests {
    use super::*;
    #[test]
    fn first_launch_and_existing_runtime_have_the_same_instance_key() {
        let base = std::env::temp_dir().join(format!(
            "invoicehub-instance-{}-{}",
            std::process::id(),
            std::time::SystemTime::now()
                .duration_since(std::time::UNIX_EPOCH)
                .unwrap()
                .as_nanos()
        ));
        std::fs::create_dir(&base).unwrap();
        let runtime = base.join("runtime");
        let executable = std::env::current_exe().unwrap();
        let before = instance_identifier("invoicehub", &executable, &runtime);
        std::fs::create_dir(&runtime).unwrap();
        assert_eq!(
            before,
            instance_identifier("invoicehub", &executable, &runtime)
        );
        std::fs::remove_dir(&runtime).unwrap();
        std::fs::remove_dir(&base).unwrap();
    }
    #[test]
    fn diagnostic_service_claim_excludes_credentials_and_control_characters() {
        let text = summarize_claim(&serde_json::json!({
            "ok": true, "pid": 42, "config_path": "test\r\nconfig.json",
            "host_rpc_token": "secret-never-display", "watch_dir": "private-business"
        }))
        .unwrap();
        assert!(text.contains("testconfig.json"));
        assert!(!text.contains("secret-never-display"));
        assert!(!text.contains("private-business"));
        assert!(summarize_claim(&serde_json::json!({"pid":42})).is_none());
    }
    #[test]
    fn singleton_scope_separates_installations_and_test_state() {
        let exe = Path::new("C:/InvoiceHub/InvoiceHub.exe");
        let runtime = Path::new("C:/state/runtime");
        let id = instance_identifier("com.invoicehub.desktop", exe, runtime);
        assert_eq!(
            id,
            instance_identifier("com.invoicehub.desktop", exe, runtime)
        );
        assert_ne!(
            id,
            instance_identifier(
                "com.invoicehub.desktop",
                Path::new("C:/other/InvoiceHub.exe"),
                runtime
            )
        );
        assert_ne!(
            id,
            instance_identifier("com.invoicehub.desktop", exe, Path::new("C:/test/runtime"))
        );
    }
}
