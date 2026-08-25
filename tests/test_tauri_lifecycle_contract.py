from __future__ import annotations

import json
import tomllib
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


def test_tauri_lifecycle_uses_exact_official_plugins_and_has_no_webview_command_bridge() -> None:
    cargo = tomllib.loads((ROOT / "src-tauri" / "Cargo.toml").read_text(encoding="utf-8"))
    main = (ROOT / "src-tauri" / "src" / "main.rs").read_text(encoding="utf-8")
    host_rpc = (ROOT / "src-tauri" / "src" / "host_rpc.rs").read_text(encoding="utf-8")

    for dependency in (
        "tauri-plugin-single-instance",
        "tauri-plugin-dialog",
        "tauri-plugin-updater",
        "getrandom",
        "serde_json",
        "hmac",
        "sha2",
    ):
        assert cargo["dependencies"][dependency]["version"].startswith("=")
    assert ".plugin(tauri_plugin_single_instance::init(" in main
    assert "#[tauri::command]" not in main
    assert "#[tauri::command]" not in host_rpc
    assert "emit(" not in host_rpc
    assert "FIXED_BACKEND_PORT" in (ROOT / "src-tauri" / "src" / "backend.rs").read_text(encoding="utf-8")
    backend = (ROOT / "src-tauri" / "src" / "backend.rs").read_text(encoding="utf-8")
    assert "Hmac<Sha256>" in backend
    assert "DESKTOP_HOST_CHALLENGE_HEADER" in backend
    assert "DESKTOP_HOST_PROOF_HEADER" not in backend
    assert "spawn_backend_liveness_watcher" in backend
    assert "pub mod monitor_recovery;" in (ROOT / "src-tauri" / "src" / "lib.rs").read_text(encoding="utf-8")


def test_tauri_updater_manifest_candidate_and_commit_guards_fail_closed() -> None:
    main = (ROOT / "src-tauri" / "src" / "main.rs").read_text(encoding="utf-8")
    backend = (ROOT / "src-tauri" / "src" / "backend.rs").read_text(encoding="utf-8")
    host_rpc = (ROOT / "src-tauri" / "src" / "host_rpc.rs").read_text(encoding="utf-8")

    assert "if let Some(public_key) = updater_public_key" in main
    assert ".pubkey(public_key)" in main
    assert "manifest.updater().public_key()" in main
    assert 'option_env!("INVOICE_HUB_BUNDLE_MANIFEST_SHA256")' in backend
    assert "compiled_bundle_manifest_hash_matches(&raw)" in backend
    assert 'Some(3)' in backend
    assert "const UPDATE_CANDIDATE_TTL: Duration = Duration::from_secs(300);" in host_rpc
    assert "const UPDATE_HTTP_TIMEOUT: Duration = Duration::from_secs(5);" in host_rpc
    assert ".timeout(UPDATE_HTTP_TIMEOUT)" in host_rpc
    assert "candidate_is_fresh(pending.checked_at, now)" in host_rpc
    assert "let _ = updater.clear_expired_candidate(Instant::now());" in host_rpc
    assert "clear_candidate_if_current(self.candidate.as_ref(), generation)" in host_rpc
    install = host_rpc[host_rpc.index("fn install(&self)") :]
    assert ".take()" in install
    assert "candidate_is_fresh(pending.checked_at, Instant::now())" in install
    assert "self.runtime_gate.reserve_commit()?;" in install
    assert "spawn_deferred_commit" in install
    assert "HostRpcResponse::UpdateInstall" in install
    assert "download_and_install" not in host_rpc
    assert ".update.download(" in host_rpc
    assert "self.update.install(update.into_bytes())" in host_rpc
    assert "UpdateCoordinator::new" in host_rpc


def test_tauri_startup_surface_uses_the_pinned_host_only_opener_and_empty_webview_capability() -> None:
    cargo = tomllib.loads((ROOT / "src-tauri" / "Cargo.toml").read_text(encoding="utf-8"))
    lock = tomllib.loads((ROOT / "src-tauri" / "Cargo.lock").read_text(encoding="utf-8"))
    main = (ROOT / "src-tauri" / "src" / "main.rs").read_text(encoding="utf-8")
    capability = json.loads(
        (ROOT / "src-tauri" / "capabilities" / "no-webview-ipc.json").read_text(encoding="utf-8")
    )

    assert cargo["dependencies"]["tauri-plugin-opener"]["version"] == "=2.5.4"
    assert ("tauri-plugin-opener", "2.5.4") in {
        (package["name"], package["version"])
        for package in lock["package"]
    }
    assert ".open_js_links_on_click(false)" in main
    assert "tauri_plugin_opener::init()" not in main
    assert "app.opener()" in main
    assert ".open_url(invoicehub_desktop::backend_origin(), None::<&str>)" in main
    assert capability["permissions"] == []
    assert "opener:" not in "\n".join(capability["permissions"])


def test_tauri_setup_selects_surface_only_after_handshake_and_keeps_close_host_owned() -> None:
    main = (ROOT / "src-tauri" / "src" / "main.rs").read_text(encoding="utf-8")
    backend = (ROOT / "src-tauri" / "src" / "backend.rs").read_text(encoding="utf-8")

    assert "INVOICE_HUB_DESKTOP_HOST" in backend
    assert backend.index("probe_backend_with_retry") < backend.index("load_startup_surface")
    assert backend.index("let startup_surface = match load_startup_surface()") < backend.index(
        "revalidate_backend_after_preferences("
    )
    assert backend.index("revalidate_backend_after_preferences(") < backend.index(
        "ownership_verified.store(true, Ordering::Release);"
    )
    revalidation_start = backend.index("if let Err(error) = revalidate_backend_after_preferences(")
    revalidation_end = backend.index("let liveness_shutdown", revalidation_start)
    revalidation = backend[revalidation_start:revalidation_end]
    assert "probe_backend(&manifest.expected_identity, child_pid, &ownership_secret)" in revalidation
    assert ".map(|_| ())" in revalidation
    assert main.index("BackendHost::launch") < main.index("backend.startup_surface()")
    assert "StartupSurface::Desktop" in main
    assert "StartupSurface::Browser" in main
    assert "TrayIconBuilder" in main
    assert "WindowEvent::CloseRequested" in main
    assert "api.prevent_close();" in main
    assert ".hide();" in main
    assert 'const TRAY_OPEN_ID: &str = "invoicehub-open";' in main
    assert 'const TRAY_QUIT_ID: &str = "invoicehub-quit";' in main
    assert "event.id() == TRAY_OPEN_ID" in main
    assert "event.id() == TRAY_QUIT_ID" in main
    assert "quit_from_tray(app);" in main
    tray_quit = main[main.index("fn quit_from_tray") : main.index("fn prepare_backend_exit")]
    assert "request_application_exit(app);" in tray_quit
    assert "shutdown_keep_monitor" not in tray_quit
    exit_handler = main[main.index("app.run(") :]
    assert "RunEvent::ExitRequested" in exit_handler
    assert "prepare_backend_exit(app_handle)" in exit_handler
    assert "api.prevent_exit();" in exit_handler
    assert "monitor.stop" not in main


def test_tauri_setup_cleans_up_an_owned_backend_before_returning_surface_failure() -> None:
    main = (ROOT / "src-tauri" / "src" / "main.rs").read_text(encoding="utf-8")

    cleanup = main[
        main.index("fn complete_setup_failure_cleanup") : main.index("fn install_tray")
    ]
    assert "loop {" in cleanup
    assert "match backend.shutdown_keep_monitor_or_terminate()" in cleanup
    assert "Ok(BackendShutdownOutcome::Graceful) => return" in cleanup
    assert "Ok(BackendShutdownOutcome::Forced)" in cleanup
    assert "Err(cleanup_error)" in cleanup
    assert "std::thread::sleep(std::time::Duration::from_secs(1));" in cleanup
    assert "setup remains blocked until owned backend termination is confirmed" in cleanup

    setup = main[main.index(".setup(move |app|") : main.index(".build(tauri::generate_context!())")]
    assert "let backend = BackendHost::launch" in setup
    assert "let setup_result = (|| -> Result<(), Box<dyn Error>>" in setup
    assert "install_tray(app)?;" in setup
    assert "create_desktop_window(app)?" in setup
    assert "open_backend_in_browser(&app.handle())?" in setup
    assert "if let Err(error) = setup_result" in setup
    assert "complete_setup_failure_cleanup(&backend);" in setup
    assert "if let Err(cleanup_error)" not in setup
    assert "return Err(error);" in setup
    assert setup.index("complete_setup_failure_cleanup(&backend);") < setup.index(
        "app.manage(backend);"
    )
    assert setup.index("complete_setup_failure_cleanup(&backend);") < setup.index(
        "return Err(error);"
    )
    assert setup.index("install_tray(app)?;") < setup.index("app.manage(backend);")
    assert setup.index("create_desktop_window(app)?") < setup.index("app.manage(backend);")
    assert setup.index("open_backend_in_browser(&app.handle())?") < setup.index(
        "app.manage(backend);"
    )
    assert setup.index("app.manage(backend);") < setup.index("app.manage(startup_surface);")


def test_tauri_macos_menu_and_tray_request_the_same_interceptable_exit() -> None:
    main = (ROOT / "src-tauri" / "src" / "main.rs").read_text(encoding="utf-8")

    assert (
        '#[cfg(target_os = "macos")]\n'
        'const APP_QUIT_ID: &str = "invoicehub-app-quit";'
    ) in main
    menu_builder = main[
        main.index("fn build_application_menu") : main.index("fn prepare_backend_exit")
    ]
    assert "MenuItem::with_id(" in menu_builder
    assert "APP_QUIT_ID" in menu_builder
    assert 'Some("CmdOrCtrl+Q")' in menu_builder
    assert "Submenu::with_items" in menu_builder
    assert "&quit_item" in menu_builder
    assert "Menu::with_items" in menu_builder
    assert "&app_menu" in menu_builder
    assert ".menu(build_application_menu)" in main
    assert "event.id() == APP_QUIT_ID" in main
    assert "PredefinedMenuItem" not in main

    shared_exit = main[
        main.index("fn request_application_exit") : main.index("fn prepare_backend_exit")
    ]
    assert shared_exit.count("app.exit(0);") == 1
    assert "request_application_exit(app);" in shared_exit

    app_menu = main[
        main.index(".menu(build_application_menu)") : main.index(
            "if let Some(public_key) = updater_public_key"
        )
    ]
    assert "request_application_exit(app);" in app_menu


def test_tauri_webview_is_created_only_after_the_owned_backend_handshake() -> None:
    config = json.loads((ROOT / "src-tauri" / "tauri.conf.json").read_text(encoding="utf-8"))
    main = (ROOT / "src-tauri" / "src" / "main.rs").read_text(encoding="utf-8")
    capability = json.loads(
        (ROOT / "src-tauri" / "capabilities" / "no-webview-ipc.json").read_text(encoding="utf-8")
    )

    assert config["app"]["windows"] == []
    assert config["app"]["security"]["capabilities"] == ["no-webview-ipc"]
    assert capability["windows"] == ["main"]
    assert capability["permissions"] == []
    assert main.index("BackendHost::launch") < main.index("WebviewWindowBuilder::new")
    assert "WebviewUrl::External(backend_url)" in main


def test_tauri_checkout_guard_and_liveness_order_fail_closed() -> None:
    main = (ROOT / "src-tauri" / "src" / "main.rs").read_text(encoding="utf-8")
    backend = (ROOT / "src-tauri" / "src" / "backend.rs").read_text(encoding="utf-8")

    assert "fn main() -> ExitCode" in main
    assert main.count("return ExitCode::from(78);") == 2
    assert backend.index("ownership_verified.store(true, Ordering::Release);") < backend.index(
        "let liveness_worker = spawn_backend_liveness_watcher"
    )


def test_tauri_monitor_recovery_foundation_requires_a_released_lifecycle_lease_and_pinned_marker_store() -> None:
    cargo = tomllib.loads((ROOT / "src-tauri" / "Cargo.toml").read_text(encoding="utf-8"))
    backend = (ROOT / "src-tauri" / "src" / "backend.rs").read_text(encoding="utf-8")
    main = (ROOT / "src-tauri" / "src" / "main.rs").read_text(encoding="utf-8")
    recovery = (ROOT / "src-tauri" / "src" / "monitor_recovery.rs").read_text(encoding="utf-8")

    assert cargo["target"]["cfg(unix)"]["dependencies"]["libc"]["version"] == "=0.2.189"
    assert "pub fn release_startup_gate" in backend
    assert "impl LifecycleAuthority for BackendHost" in backend
    assert "capture_released_lease" in backend
    assert "revalidate_lease" in backend
    assert main.index("backend.release_startup_gate()") < main.index("app.manage(backend);")
    for token in (
        "LifecycleLease",
        "MonitorRecoveryTransaction",
        "RecoveryMarkerStore",
        "RecoveryPending",
        "fn load_marker",
        "fn publish_marker",
        "fn clear_marker",
        "libc::openat",
        "libc::O_NOFOLLOW",
        "libc::linkat",
        "libc::unlinkat",
        "libc::AT_SYMLINK_NOFOLLOW",
        "MarkerStoreError::UnsupportedPlatform",
        "MarkerStoreError::MarkerChanged",
    ):
        assert token in recovery
    host_rpc = (ROOT / "src-tauri" / "src" / "host_rpc.rs").read_text(encoding="utf-8")
    assert "MonitorRecoveryTransaction::new" in host_rpc
    assert ".restore_owned_monitor()" in host_rpc
    assert "UpdateCoordinator::new" in host_rpc


def test_tauri_updater_runtime_activates_after_the_owned_gate_and_commits_after_response_flush() -> None:
    backend = (ROOT / "src-tauri" / "src" / "backend.rs").read_text(encoding="utf-8")
    host_rpc = (ROOT / "src-tauri" / "src" / "host_rpc.rs").read_text(encoding="utf-8")
    main = (ROOT / "src-tauri" / "src" / "main.rs").read_text(encoding="utf-8")

    backend_struct = backend[backend.index("pub struct BackendHost") : backend.index("#[derive(Clone)]\npub struct BackendLifecycleAuthority")]
    assert "ownership_secret: [u8; OWNERSHIP_SECRET_BYTES]" in backend_struct
    assert "pub ownership_secret" not in backend
    assert "fn ownership_secret(" not in backend

    setup = main[main.index(".setup(move |app|") : main.index(".build(tauri::generate_context!())")]
    assert setup.index("backend.release_startup_gate()") < setup.index("app.manage(backend);")
    assert setup.index("app.manage(backend);") < setup.index("backend.activate_updater_runtime()")
    assert "the backend remains available for diagnostics" in setup
    assert "InvoiceHub updater recovery runtime activated" in setup

    activation = host_rpc[host_rpc.index("fn activate(") : host_rpc.index("fn clear_candidate")]
    assert "if !self.runtime_gate.begin_activation()?" in activation
    assert "open_platform_marker_store(runtime_dir)" in activation
    assert "PythonMonitorRecoveryBridge::new(ownership_secret)" in activation
    assert ".restore_owned_monitor()" in activation
    assert activation.index(".restore_owned_monitor()") < activation.index("finish_activation()")

    response_commit = host_rpc[host_rpc.index("fn write_rpc_reply") : host_rpc.index("fn write_rejected_response")]
    assert response_commit.index("write_response(writer, reply.response)") < response_commit.index("commit.execute()")
    assert "writer.flush()" in response_commit
    assert "commit.cancel();" in response_commit
    assert "mark_commit_lost" in host_rpc
    assert '"invoicehub-update-commit"' in host_rpc

    exit_guard = main[main.index("fn prepare_backend_exit") : main.index("fn complete_setup_failure_cleanup")]
    assert exit_guard.index("backend.update_relaunch_prepared()") < exit_guard.index(
        "backend.updater_blocks_normal_quit()"
    )
    assert "return false;" in exit_guard
    assert "backend.shutdown_keep_monitor_or_terminate()" in host_rpc
    assert "self.app_handle.request_restart();" in host_rpc


def test_tauri_backend_lifecycle_authority_is_cloneable_and_delegated() -> None:
    backend = (ROOT / "src-tauri" / "src" / "backend.rs").read_text(encoding="utf-8")

    assert "#[derive(Clone)]\npub struct BackendLifecycleAuthority" in backend
    assert "pub fn lifecycle_authority(&self) -> BackendLifecycleAuthority" in backend
    factory = backend[
        backend.index("pub fn lifecycle_authority") : backend.index("    pub fn launch", backend.index("pub fn lifecycle_authority"))
    ]
    for handle in ("child", "ownership_verified", "lifecycle"):
        assert f"Arc::clone(&self.{handle})" in factory
    assert "self.child_pid" in factory

    authority_impl = backend[
        backend.index("impl LifecycleAuthority for BackendLifecycleAuthority") : backend.index(
            "impl LifecycleAuthority for BackendHost"
        )
    ]
    assert "self.ownership_verified.load(Ordering::Acquire)" in authority_impl
    assert "current_child_pid(&self.child)" in authority_impl
    assert "RecoveryError::StartupGateHeld" in authority_impl
    assert "RecoveryError::LeaseInvalid" in authority_impl
    assert "RecoveryError::OwnershipLost" in authority_impl

    host_impl = backend[backend.index("impl LifecycleAuthority for BackendHost") :]
    assert "self.lifecycle_authority().capture_released_lease()" in host_impl
    assert "self.lifecycle_authority().revalidate_lease(lease)" in host_impl


def test_tauri_manifest_uses_runtime_derived_user_state_paths() -> None:
    backend = (ROOT / "src-tauri" / "src" / "backend.rs").read_text(encoding="utf-8")

    assert 'const DESKTOP_STATE_DIRECTORY: &str = "InvoiceHub";' in backend
    assert 'DesktopStatePlatform::Windows => base.join(DESKTOP_STATE_DIRECTORY)' in backend
    assert 'join("Application Support")' in backend
    assert 'fields.contains_key("config_path") || fields.contains_key("runtime_dir")' in backend
    assert 'command.current_dir(&manifest.backend_root);' in backend
    assert 'env::var_os(DEVELOPMENT_STATE_ROOT_ENV)' in backend
    assert 'command.env_remove(DEVELOPMENT_STATE_ROOT_ENV);' in backend
    assert '"--initial-state-dir".to_owned()' in backend
    assert "development_root.ok_or(BackendError::BundleManifestInvalid)?" in backend
    assert "!root.is_absolute() || !root.is_dir()" in backend
    assert "fs::canonicalize(root)" in backend
    assert "fs::canonicalize(bundle_root)" in backend
    assert "bundle_state_boundary(&canonical_bundle)" in backend
    assert "canonical_root.starts_with(&canonical_bundle_boundary)" in backend
    assert "canonical_bundle_boundary.starts_with(&canonical_root)" in backend
    assert 'path.extension().and_then(|value| value.to_str()) == Some("app")' in backend
    assert "app_contents_state" in backend


def test_tauri_all_exit_requests_use_structured_shutdown_with_confirmed_termination_fallback() -> None:
    main = (ROOT / "src-tauri" / "src" / "main.rs").read_text(encoding="utf-8")
    backend = (ROOT / "src-tauri" / "src" / "backend.rs").read_text(encoding="utf-8")

    assert 'pub const SERVER_SHUTDOWN_PATH: &str = "/api/v1/server/shutdown";' in backend
    assert '(SERVER_SHUTDOWN_PATH, "post")' in backend
    assert 'br#"{"shutdown_behavior":"keep_monitor","remember":false}"#' in backend
    assert "fn local_post_json" in backend
    assert "is_keep_monitor_shutdown_ack" in backend
    assert "GracefulShutdownTimedOut" in backend
    assert "pub fn shutdown_keep_monitor_or_terminate" in backend
    graceful = backend[
        backend.index("pub fn shutdown_keep_monitor") : backend.index(
            "pub fn shutdown_keep_monitor_or_terminate"
        )
    ]
    assert "while !child_exit_confirmed(&self.child)?" in graceful
    confirmation = backend[
        backend.index("fn child_exit_confirmed") : backend.index("fn state_paths_for_bundle_profile")
    ]
    assert "Result<bool, BackendError>" in confirmation
    assert ".map_err(|_| BackendError::BackendTerminationFailed)?" in confirmation
    assert "Ok(Some(_)) => Ok(true)" in confirmation
    assert "Ok(None) => Ok(false)" in confirmation
    assert "Err(_) => Err(BackendError::BackendTerminationFailed)" in confirmation
    shutdown = backend[
        backend.index("pub fn shutdown_keep_monitor_or_terminate") : backend.index(
            "pub fn startup_surface"
        )
    ]
    assert shutdown.index("self.shutdown_keep_monitor()") < shutdown.index(
        "self.terminate_backend()?"
    )
    terminate = backend[backend.index("fn terminate_backend") : backend.index("impl Drop")]
    assert terminate.index(".kill()") < terminate.index(".wait()")
    prepare = main[main.index("fn prepare_backend_exit") : main.index("fn install_tray")]
    assert "backend.shutdown_keep_monitor_or_terminate()" in prepare
    assert "return false;" in prepare


def test_tauri_configuration_remains_fixed_to_the_product_localhost_origin() -> None:
    config = json.loads((ROOT / "src-tauri" / "tauri.conf.json").read_text(encoding="utf-8"))

    assert config["build"]["devUrl"] == "http://127.0.0.1:8766"
    assert config["bundle"]["active"] is False
    assert config["bundle"]["macOS"]["minimumSystemVersion"] == "13.0"
