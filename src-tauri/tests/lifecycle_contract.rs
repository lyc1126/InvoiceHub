use std::io::{Read, Write};
use std::net::TcpListener;
use std::path::PathBuf;
use std::sync::atomic::{AtomicBool, AtomicUsize, Ordering};
use std::sync::Arc;
use std::thread;
use std::time::Duration;

use invoicehub_desktop::backend::{
    assert_loopback_port_available, parse_existing_invoicehub_claim, parse_startup_preferences,
    parse_startup_surface, resolve_port_conflict_at, resolve_port_conflict_with,
    validate_openapi_routes, BackendError, BackendHealth, BundleProfile, ExistingInvoiceHubClaim,
    ExpectedBackendIdentity, HandshakeError, PortConflictOutcome, StartupPreferences,
    StartupSurface,
};
use invoicehub_desktop::host_rpc::{HostRpcAuthorizationError, HostRpcAuthorizer};
use serde_json::json;

fn expected_identity() -> ExpectedBackendIdentity {
    ExpectedBackendIdentity {
        bundle_profile: BundleProfile::Release,
        build_id: "a".repeat(64),
        api_contract_version: "2026-08-02-release-update-v1".to_owned(),
        bookkeeping_protocol_version: "w9-ledger-review-v1".to_owned(),
        capabilities: vec![
            "invoices.file-preview.v1".to_owned(),
            "monitor.ready-handshake.v1".to_owned(),
        ],
        product_version: "0.3.0-alpha.2".to_owned(),
        package_id: "com.invoicehub.macos.arm64.dmg".to_owned(),
        platform: "macos".to_owned(),
        architecture: "arm64".to_owned(),
        package_type: "dmg".to_owned(),
        config_path: PathBuf::from("/safe/config/app.json"),
        runtime_dir: PathBuf::from("/safe/runtime"),
    }
}

fn matching_health(identity: &ExpectedBackendIdentity, pid: u32) -> BackendHealth {
    BackendHealth {
        ok: true,
        pid,
        build_manifest_present: true,
        build_manifest_valid: true,
        package_manifest_present: true,
        package_manifest_valid: true,
        build_id: identity.build_id.clone(),
        api_contract_version: identity.api_contract_version.clone(),
        bookkeeping_protocol_version: identity.bookkeeping_protocol_version.clone(),
        capabilities: identity.capabilities.clone(),
        product_version: identity.product_version.clone(),
        package_id: identity.package_id.clone(),
        platform: identity.platform.clone(),
        architecture: identity.architecture.clone(),
        package_type: identity.package_type.clone(),
        config_path: identity.config_path.clone(),
        runtime_dir: identity.runtime_dir.clone(),
    }
}

#[test]
fn rejects_an_already_bound_loopback_port() {
    let listener = TcpListener::bind("127.0.0.1:0").expect("bind representative occupied port");

    assert!(
        assert_loopback_port_available(listener.local_addr().expect("socket address")).is_err()
    );
}

#[test]
fn strict_handshake_rejects_pid_and_identity_mismatches() {
    let expected = expected_identity();
    let health = matching_health(&expected, 4100);

    assert_eq!(
        expected.validate_health(&health, 4101),
        Err(HandshakeError::PidMismatch)
    );

    let mut mismatched_identity = health;
    mismatched_identity.package_id = "com.example.untrusted".to_owned();
    assert_eq!(
        expected.validate_health(&mismatched_identity, 4100),
        Err(HandshakeError::IdentityMismatch)
    );
}

#[test]
fn development_handshake_requires_a_valid_build_without_a_package_manifest() {
    let mut expected = expected_identity();
    expected.bundle_profile = BundleProfile::Development;
    expected.package_id = "development".to_owned();
    expected.package_type = "source".to_owned();
    let mut health = matching_health(&expected, 4100);
    health.package_manifest_present = false;
    health.package_manifest_valid = false;

    assert_eq!(expected.validate_health(&health, 4100), Ok(()));

    health.package_manifest_present = true;
    assert_eq!(
        expected.validate_health(&health, 4100),
        Err(HandshakeError::ManifestMismatch)
    );

    health.package_manifest_present = false;
    health.build_manifest_valid = false;
    assert_eq!(
        expected.validate_health(&health, 4100),
        Err(HandshakeError::ManifestMismatch)
    );
}

#[test]
fn host_rpc_rejects_wrong_token_origin_command_and_revoked_ownership() {
    let ownership_verified = Arc::new(AtomicBool::new(true));
    let authorizer = HostRpcAuthorizer::from_test_token([7; 32], Arc::clone(&ownership_verified));

    assert_eq!(
        authorizer.authorize("http://127.0.0.1:8766", &[8; 32], "pick_watch_dir"),
        Err(HostRpcAuthorizationError::TokenRejected)
    );
    assert_eq!(
        authorizer.authorize("https://example.invalid", &[7; 32], "pick_watch_dir"),
        Err(HostRpcAuthorizationError::OriginRejected)
    );
    assert_eq!(
        authorizer.authorize("http://127.0.0.1:8766", &[7; 32], "run_shell"),
        Err(HostRpcAuthorizationError::CommandRejected)
    );
    assert_eq!(
        authorizer.authorize("http://127.0.0.1:8766", &[7; 32], "pick_watch_dir"),
        Ok(())
    );
    assert_eq!(
        authorizer.authorize("http://127.0.0.1:8766", &[7; 32], "set_app_icon"),
        Ok(())
    );
    ownership_verified.store(false, std::sync::atomic::Ordering::Release);
    assert_eq!(
        authorizer.authorize("http://127.0.0.1:8766", &[7; 32], "pick_watch_dir"),
        Err(HostRpcAuthorizationError::OwnershipRejected)
    );
}

#[test]
fn company_picker_requires_current_ownership_and_exact_origin() {
    let ownership = Arc::new(AtomicBool::new(true));
    let authorizer = HostRpcAuthorizer::from_test_token([7; 32], Arc::clone(&ownership));
    assert_eq!(
        authorizer.authorize("http://127.0.0.1:8766", &[7; 32], "pick_company_directory"),
        Ok(())
    );
    assert_eq!(
        authorizer.authorize("http://127.0.0.1:8799", &[7; 32], "pick_company_directory"),
        Err(HostRpcAuthorizationError::OriginRejected)
    );
    ownership.store(false, std::sync::atomic::Ordering::Release);
    assert_eq!(
        authorizer.authorize("http://127.0.0.1:8766", &[7; 32], "pick_company_directory"),
        Err(HostRpcAuthorizationError::OwnershipRejected)
    );
}

#[test]
fn strict_openapi_requires_the_expected_http_methods() {
    let valid = json!({
        "paths": {
            "/api/v1/health": {"get": {}},
            "/api/v1/settings/pick-watch-dir": {"post": {}},
            "/api/v1/documents/pick-outbound-dir": {"post": {}},
            "/api/v1/ocr/pick-file": {"post": {}},
            "/api/v1/temporary-recognition/pick": {"post": {}},
            "/api/v1/temporary-recognition/drop": {"post": {}},
            "/api/v1/temporary-recognition/sessions": {"post": {}},
            "/api/v1/cost-analysis/view": {"get": {}},
            "/api/v1/invoices/trash-jobs": {"post": {}},
            "/api/v1/invoices/trash-jobs/{job_id}": {"get": {}},
            "/api/v1/invoices/trash-jobs/{job_id}/confirm": {"post": {}},
            "/api/v1/ocr/pick-folder": {"post": {}},
            "/api/v1/update/check": {"post": {}},
            "/api/v1/update/install": {"post": {}},
            "/api/v1/server/shutdown": {"post": {}},
            "/api/v1/bridge/status": {"get": {}},
            "/api/v1/bridge/stop": {"post": {}},
            "/api/v1/bridge/start": {"post": {}}
        }
    });
    assert_eq!(validate_openapi_routes(&valid), Ok(()));

    for path in [
        "/api/v1/temporary-recognition/pick",
        "/api/v1/cost-analysis/view",
        "/api/v1/invoices/trash-jobs",
        "/api/v1/invoices/trash-jobs/{job_id}",
        "/api/v1/invoices/trash-jobs/{job_id}/confirm",
    ] {
        let mut old_backend = valid.clone();
        old_backend["paths"].as_object_mut().unwrap().remove(path);
        assert_eq!(
            validate_openapi_routes(&old_backend),
            Err(HandshakeError::OpenApiMismatch)
        );
    }

    let mut missing_start = valid.clone();
    missing_start["paths"]
        .as_object_mut()
        .expect("OpenAPI paths object")
        .remove("/api/v1/bridge/start");
    assert_eq!(
        validate_openapi_routes(&missing_start),
        Err(HandshakeError::OpenApiMismatch)
    );

    let mut wrong_start_method = valid.clone();
    wrong_start_method["paths"]["/api/v1/bridge/start"] = json!({"get": {}});
    assert_eq!(
        validate_openapi_routes(&wrong_start_method),
        Err(HandshakeError::OpenApiMismatch)
    );

    let wrong_method = json!({
        "paths": {
            "/api/v1/health": {"get": {}},
            "/api/v1/settings/pick-watch-dir": {"get": {}},
            "/api/v1/documents/pick-outbound-dir": {"post": {}},
            "/api/v1/ocr/pick-file": {"post": {}},
            "/api/v1/temporary-recognition/pick": {"post": {}},
            "/api/v1/temporary-recognition/drop": {"post": {}},
            "/api/v1/temporary-recognition/sessions": {"post": {}},
            "/api/v1/ocr/pick-folder": {"post": {}}
        }
    });
    assert_eq!(
        validate_openapi_routes(&wrong_method),
        Err(HandshakeError::OpenApiMismatch)
    );
}

#[test]
fn startup_preferences_parser_requires_a_desktop_capable_owned_backend() {
    let desktop = json!({
        "ok": true,
        "preferences": {"startup_surface": "desktop", "allow_print_popups": true},
        "allowed": {"desktop_available": true}
    });
    assert!(matches!(
        parse_startup_preferences(&desktop),
        Ok(StartupPreferences {
            startup_surface: StartupSurface::Desktop,
            allow_print_popups: true,
        })
    ));
    assert!(matches!(
        parse_startup_surface(&desktop),
        Ok(StartupSurface::Desktop)
    ));

    let browser = json!({
        "ok": true,
        "preferences": {"startup_surface": "browser", "allow_print_popups": false},
        "allowed": {"desktop_available": true}
    });
    assert!(matches!(
        parse_startup_preferences(&browser),
        Ok(StartupPreferences {
            startup_surface: StartupSurface::Browser,
            allow_print_popups: false,
        })
    ));
    assert!(matches!(
        parse_startup_surface(&browser),
        Ok(StartupSurface::Browser)
    ));

    let unavailable = json!({
        "ok": true,
        "preferences": {"startup_surface": "browser", "allow_print_popups": true},
        "allowed": {"desktop_available": false}
    });
    assert!(matches!(
        parse_startup_surface(&unavailable),
        Err(BackendError::DesktopSurfaceUnavailable)
    ));

    for malformed in [
        json!({"ok": true, "preferences": {}, "allowed": {"desktop_available": true}}),
        json!({"ok": true, "preferences": {"startup_surface": "external"}, "allowed": {"desktop_available": true}}),
        json!({"ok": true, "preferences": {"startup_surface": "desktop", "allow_print_popups": true}, "allowed": {}}),
        json!({"ok": true, "preferences": {"startup_surface": "desktop"}, "allowed": {"desktop_available": true}}),
        json!({"ok": true, "preferences": {"startup_surface": "desktop", "allow_print_popups": "true"}, "allowed": {"desktop_available": true}}),
    ] {
        assert!(matches!(
            parse_startup_surface(&malformed),
            Err(BackendError::StartupSurfaceInvalid)
        ));
    }
}

#[test]
fn existing_invoicehub_claim_requires_contract_fields_and_sanitizes_control_chars() {
    let valid = json!({
        "ok": true,
        "pid": 4242,
        "api_contract_version": "2026-08-02-release-update-v1",
        "product_version": "1.0.0-beta.1",
        "package_type": "dmg",
        "config_path": "/safe/config\r\n/app.local.json",
        "runtime_dir": "/safe/runtime",
        "host_rpc_token": "secret-must-not-appear"
    });
    let claim = parse_existing_invoicehub_claim(&valid).expect("valid InvoiceHub health claim");
    assert_eq!(claim.pid, 4242);
    assert_eq!(claim.product_version, "1.0.0-beta.1");
    assert_eq!(claim.package_type, "dmg");
    assert_eq!(claim.config_path, "/safe/config/app.local.json");
    assert_eq!(claim.runtime_dir, "/safe/runtime");

    // Non-InvoiceHub /api/v1/health payloads must be rejected so shutdown is never sent.
    for non_invoicehub in [
        json!({"ok": true, "pid": 4242, "product_version": "1.0.0", "package_type": "dmg", "config_path": "/a", "runtime_dir": "/b"}),
        json!({"ok": false, "pid": 4242, "api_contract_version": "v1", "product_version": "1.0.0", "package_type": "dmg", "config_path": "/a", "runtime_dir": "/b"}),
        json!({"ok": true, "pid": 0, "api_contract_version": "v1", "product_version": "1.0.0", "package_type": "dmg", "config_path": "/a", "runtime_dir": "/b"}),
        json!({"status": "healthy"}),
    ] {
        assert!(parse_existing_invoicehub_claim(&non_invoicehub).is_none());
    }
}

#[test]
fn port_conflict_state_machine_guards_unknown_decline_and_toctou_changes() {
    let sample_claim = |pid: u32| ExistingInvoiceHubClaim {
        pid,
        product_version: "1.0.0-beta.1".to_owned(),
        package_type: "source".to_owned(),
        config_path: "/safe/config.json".to_owned(),
        runtime_dir: "/safe/runtime".to_owned(),
    };

    // Free port never probes or prompts.
    assert_eq!(
        resolve_port_conflict_with(
            || Ok(()),
            || panic!("unexpected probe"),
            |_| panic!("unexpected prompt"),
            || panic!("unexpected shutdown"),
            || panic!("unexpected wait"),
        )
        .unwrap(),
        PortConflictOutcome::PortAvailable
    );

    // Unknown occupant never prompts or sends shutdown.
    assert!(matches!(
        resolve_port_conflict_with(
            || Err(BackendError::FixedPortUnavailable),
            || None,
            |_| panic!("unexpected prompt"),
            || panic!("unexpected shutdown"),
            || panic!("unexpected wait"),
        ),
        Err(BackendError::FixedPortUnavailable)
    ));

    // User decline preserves the existing instance without calling shutdown.
    assert!(matches!(
        resolve_port_conflict_with(
            || Err(BackendError::FixedPortUnavailable),
            || Some(sample_claim(100)),
            |_| false,
            || panic!("unexpected shutdown"),
            || panic!("unexpected wait"),
        ),
        Err(BackendError::FixedPortUnavailable)
    ));

    // Occupant changing PID during the user prompt aborts without sending shutdown.
    let probe_count = AtomicUsize::new(0);
    assert!(matches!(
        resolve_port_conflict_with(
            || Err(BackendError::FixedPortUnavailable),
            || {
                let n = probe_count.fetch_add(1, Ordering::SeqCst);
                Some(sample_claim(if n == 0 { 100 } else { 200 }))
            },
            |_| true,
            || panic!("must not send shutdown to changed occupant"),
            || panic!("unexpected wait"),
        ),
        Err(BackendError::ExistingInstanceChanged)
    ));

    // If the old instance exited while the dialog was open, proceed without calling shutdown.
    let check_count = AtomicUsize::new(0);
    assert_eq!(
        resolve_port_conflict_with(
            || {
                if check_count.fetch_add(1, Ordering::SeqCst) == 0 {
                    Err(BackendError::FixedPortUnavailable)
                } else {
                    Ok(())
                }
            },
            || Some(sample_claim(100)),
            |_| true,
            || panic!("unexpected shutdown after port freed"),
            || panic!("unexpected wait"),
        )
        .unwrap(),
        PortConflictOutcome::PortAvailable
    );
}

#[test]
fn loopback_port_conflict_recovery_shuts_down_confirmed_invoicehub_and_rejects_unknown() {
    // 1. Non-InvoiceHub listener: must fail closed without prompting or receiving shutdown.
    let unknown_listener = TcpListener::bind("127.0.0.1:0").expect("bind unknown listener");
    let unknown_addr = unknown_listener.local_addr().expect("unknown addr");
    let unknown_shutdown_called = Arc::new(AtomicBool::new(false));
    let unknown_flag = Arc::clone(&unknown_shutdown_called);
    let unknown_server = thread::spawn(move || {
        if let Ok((mut stream, _)) = unknown_listener.accept() {
            let mut buf = [0_u8; 2048];
            let n = stream.read(&mut buf).unwrap_or(0);
            let req = String::from_utf8_lossy(&buf[..n]);
            if req.contains("/api/v1/server/shutdown") {
                unknown_flag.store(true, Ordering::SeqCst);
            }
            let body = r#"{"service":"unrelated"}"#;
            let resp = format!(
                "HTTP/1.1 200 OK\r\nContent-Type: application/json\r\nContent-Length: {}\r\nConnection: close\r\n\r\n{}",
                body.len(),
                body
            );
            let _ = stream.write_all(resp.as_bytes());
        }
    });
    assert!(matches!(
        resolve_port_conflict_at(unknown_addr, Duration::from_secs(1), |_| {
            panic!("must not prompt for non-InvoiceHub service")
        }),
        Err(BackendError::FixedPortUnavailable)
    ));
    unknown_server.join().unwrap();
    assert!(!unknown_shutdown_called.load(Ordering::SeqCst));

    // 2. Confirmed local InvoiceHub listener: re-probes health, sends keep_monitor shutdown, releases port.
    let old_listener = TcpListener::bind("127.0.0.1:0").expect("bind mock InvoiceHub");
    let old_addr = old_listener.local_addr().expect("old addr");
    let saw_keep_monitor = Arc::new(AtomicBool::new(false));
    let saw_flag = Arc::clone(&saw_keep_monitor);
    let health_body = json!({
        "ok": true,
        "pid": 9876,
        "api_contract_version": "2026-08-02-release-update-v1",
        "product_version": "0.3.0-alpha.2",
        "package_type": "portable",
        "config_path": "/old/config.json",
        "runtime_dir": "/old/runtime"
    })
    .to_string();
    let old_server = thread::spawn(move || {
        let mut health_hits = 0usize;
        for incoming in old_listener.incoming() {
            let Ok(mut stream) = incoming else { break };
            let mut buf = [0_u8; 4096];
            let n = stream.read(&mut buf).unwrap_or(0);
            let req = String::from_utf8_lossy(&buf[..n]);
            if req.starts_with("GET /api/v1/health ") {
                health_hits += 1;
                let resp = format!(
                    "HTTP/1.1 200 OK\r\nContent-Type: application/json\r\nContent-Length: {}\r\nConnection: close\r\n\r\n{}",
                    health_body.len(),
                    health_body
                );
                let _ = stream.write_all(resp.as_bytes());
            } else if req.starts_with("POST /api/v1/server/shutdown ") {
                if req.contains(r#"{"shutdown_behavior":"keep_monitor","remember":false}"#) {
                    saw_flag.store(true, Ordering::SeqCst);
                }
                let ack = r#"{"ok":true,"shutdown_behavior":"keep_monitor","scheduled":true}"#;
                let resp = format!(
                    "HTTP/1.1 200 OK\r\nContent-Type: application/json\r\nContent-Length: {}\r\nConnection: close\r\n\r\n{}",
                    ack.len(),
                    ack
                );
                let _ = stream.write_all(resp.as_bytes());
                break; // Drop old_listener to release the port.
            }
        }
        health_hits
    });
    let outcome = resolve_port_conflict_at(old_addr, Duration::from_secs(3), |claim| {
        assert_eq!(claim.pid, 9876);
        assert_eq!(claim.product_version, "0.3.0-alpha.2");
        true
    })
    .expect("confirmed InvoiceHub should shut down cleanly");
    let health_hits = old_server.join().unwrap();
    assert_eq!(
        outcome,
        PortConflictOutcome::RecoveredByShutdown { pid: 9876 }
    );
    assert_eq!(health_hits, 2);
    assert!(saw_keep_monitor.load(Ordering::SeqCst));
    assert!(assert_loopback_port_available(old_addr).is_ok());

    // 3. Confirmed InvoiceHub that acks shutdown but refuses to release the port times out cleanly.
    let stuck_listener = TcpListener::bind("127.0.0.1:0").expect("bind stuck mock");
    let stuck_addr = stuck_listener.local_addr().expect("stuck addr");
    let keep_alive = Arc::new(AtomicBool::new(true));
    let keep_flag = Arc::clone(&keep_alive);
    let stuck_health = json!({
        "ok": true,
        "pid": 5432,
        "api_contract_version": "2026-08-02-release-update-v1",
        "product_version": "0.3.0-alpha.2",
        "package_type": "portable",
        "config_path": "/stuck/config.json",
        "runtime_dir": "/stuck/runtime"
    })
    .to_string();
    let stuck_server = thread::spawn(move || {
        for _ in 0..3 {
            let Ok((mut stream, _)) = stuck_listener.accept() else {
                break;
            };
            let mut buf = [0_u8; 4096];
            let n = stream.read(&mut buf).unwrap_or(0);
            let req = String::from_utf8_lossy(&buf[..n]);
            let body = if req.starts_with("POST /api/v1/server/shutdown ") {
                r#"{"ok":true,"shutdown_behavior":"keep_monitor","scheduled":true}"#
            } else {
                stuck_health.as_str()
            };
            let resp = format!(
                "HTTP/1.1 200 OK\r\nContent-Type: application/json\r\nContent-Length: {}\r\nConnection: close\r\n\r\n{}",
                body.len(),
                body
            );
            let _ = stream.write_all(resp.as_bytes());
        }
        while keep_flag.load(Ordering::SeqCst) {
            thread::sleep(Duration::from_millis(20));
        }
    });
    let timeout_result = resolve_port_conflict_at(stuck_addr, Duration::from_millis(250), |_| true);
    keep_alive.store(false, Ordering::SeqCst);
    stuck_server.join().unwrap();
    assert!(matches!(
        timeout_result,
        Err(BackendError::ExistingInstanceShutdownTimedOut { pid: 5432 })
    ));
}
