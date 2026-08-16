use std::net::TcpListener;
use std::path::PathBuf;
use std::sync::atomic::AtomicBool;
use std::sync::Arc;

use invoicehub_desktop::backend::{
    assert_loopback_port_available, parse_startup_surface, validate_openapi_routes, BackendError,
    BackendHealth, BundleProfile, ExpectedBackendIdentity, HandshakeError, StartupSurface,
};
use invoicehub_desktop::host_rpc::{HostRpcAuthorizationError, HostRpcAuthorizer, HostRpcCommand};
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
        product_version: "0.3.0-alpha.1".to_owned(),
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
        Ok(HostRpcCommand::PickWatchDirectory)
    );
    ownership_verified.store(false, std::sync::atomic::Ordering::Release);
    assert_eq!(
        authorizer.authorize("http://127.0.0.1:8766", &[7; 32], "pick_watch_dir"),
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
            "/api/v1/ocr/pick-folder": {"post": {}},
            "/api/v1/update/check": {"post": {}},
            "/api/v1/update/install": {"post": {}},
            "/api/v1/server/shutdown": {"post": {}},
            "/api/v1/bridge/status": {"get": {}},
            "/api/v1/bridge/stop": {"post": {}}
        }
    });
    assert_eq!(validate_openapi_routes(&valid), Ok(()));

    let wrong_method = json!({
        "paths": {
            "/api/v1/health": {"get": {}},
            "/api/v1/settings/pick-watch-dir": {"get": {}},
            "/api/v1/documents/pick-outbound-dir": {"post": {}},
            "/api/v1/ocr/pick-file": {"post": {}},
            "/api/v1/ocr/pick-folder": {"post": {}}
        }
    });
    assert_eq!(
        validate_openapi_routes(&wrong_method),
        Err(HandshakeError::OpenApiMismatch)
    );
}

#[test]
fn startup_surface_parser_requires_a_desktop_capable_owned_backend() {
    let desktop = json!({
        "ok": true,
        "preferences": {"startup_surface": "desktop"},
        "allowed": {"desktop_available": true}
    });
    assert!(matches!(
        parse_startup_surface(&desktop),
        Ok(StartupSurface::Desktop)
    ));

    let browser = json!({
        "ok": true,
        "preferences": {"startup_surface": "browser"},
        "allowed": {"desktop_available": true}
    });
    assert!(matches!(
        parse_startup_surface(&browser),
        Ok(StartupSurface::Browser)
    ));

    let unavailable = json!({
        "ok": true,
        "preferences": {"startup_surface": "browser"},
        "allowed": {"desktop_available": false}
    });
    assert!(matches!(
        parse_startup_surface(&unavailable),
        Err(BackendError::DesktopSurfaceUnavailable)
    ));

    for malformed in [
        json!({"ok": true, "preferences": {}, "allowed": {"desktop_available": true}}),
        json!({"ok": true, "preferences": {"startup_surface": "external"}, "allowed": {"desktop_available": true}}),
        json!({"ok": true, "preferences": {"startup_surface": "desktop"}, "allowed": {}}),
    ] {
        assert!(matches!(
            parse_startup_surface(&malformed),
            Err(BackendError::StartupSurfaceInvalid)
        ));
    }
}
