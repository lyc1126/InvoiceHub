#![cfg_attr(
    all(target_os = "windows", not(debug_assertions)),
    windows_subsystem = "windows"
)]

use std::error::Error;
use std::path::Path;
use std::process::ExitCode;
use std::sync::atomic::{AtomicBool, AtomicU64, Ordering};
use std::sync::Arc;

#[cfg(target_os = "macos")]
use tauri::menu::Submenu;
use tauri::{
    menu::{Menu, MenuItem},
    tray::TrayIconBuilder,
    Manager, RunEvent, WindowEvent,
};
use tauri_plugin_opener::OpenerExt;

use invoicehub_desktop::app_icon::{self, AppIconId};
use invoicehub_desktop::backend::{
    default_bundle_root, load_bundle_manifest, BackendHost, BackendShutdownOutcome, StartupSurface,
};
use invoicehub_desktop::startup_diagnostics;

const MAIN_WINDOW_LABEL: &str = "main";
const PRINT_POPUP_INITIAL_URL: &str = "about:blank";
const PRINT_POPUP_ROUTE_PREFIX: &str = "/invoices/print/";
const PRINT_POPUP_JOB_ID_MIN_LENGTH: usize = 20;
const PRINT_POPUP_JOB_ID_MAX_LENGTH: usize = 80;
static PRINT_POPUP_WINDOW_SEQUENCE: AtomicU64 = AtomicU64::new(0);
#[cfg(target_os = "macos")]
const APP_QUIT_ID: &str = "invoicehub-app-quit";
const TRAY_OPEN_ID: &str = "invoicehub-open";
const TRAY_QUIT_ID: &str = "invoicehub-quit";
const TRAY_DIAGNOSE_ID: &str = "invoicehub-diagnose";

fn open_backend_in_browser(
    app: &tauri::AppHandle<tauri::Wry>,
) -> Result<(), tauri_plugin_opener::Error> {
    app.opener()
        .open_url(invoicehub_desktop::backend_origin(), None::<&str>)
}

fn reveal_desktop_window(app: &tauri::AppHandle<tauri::Wry>) {
    if let Some(window) = app.get_webview_window(MAIN_WINDOW_LABEL) {
        let _ = window.show();
        let _ = window.set_focus();
    }
}

fn reopen_startup_surface(app: &tauri::AppHandle<tauri::Wry>) {
    let Some(surface) = app.try_state::<StartupSurface>() else {
        return;
    };
    match *surface.inner() {
        StartupSurface::Desktop => reveal_desktop_window(app),
        StartupSurface::Browser => {
            let _ = open_backend_in_browser(app);
        }
    }
}

fn request_application_exit(app: &tauri::AppHandle<tauri::Wry>) {
    app.exit(0);
}

fn quit_from_tray(app: &tauri::AppHandle<tauri::Wry>) {
    request_application_exit(app);
}

#[cfg(target_os = "macos")]
fn build_application_menu(app: &tauri::AppHandle<tauri::Wry>) -> tauri::Result<Menu<tauri::Wry>> {
    let quit_item = MenuItem::with_id(
        app,
        APP_QUIT_ID,
        "Quit InvoiceHub",
        true,
        Some("CmdOrCtrl+Q"),
    )?;
    let app_menu = Submenu::with_items(app, "InvoiceHub", true, &[&quit_item])?;
    Menu::with_items(app, &[&app_menu])
}

fn prepare_backend_exit(app: &tauri::AppHandle<tauri::Wry>) -> bool {
    if let Some(backend) = app.try_state::<BackendHost>() {
        if backend.update_relaunch_prepared() {
            return true;
        }
        if backend.updater_blocks_normal_quit() {
            eprintln!("InvoiceHub desktop host exit was blocked while an update commit is active");
            return false;
        }
        match backend.shutdown_keep_monitor_or_terminate() {
            Ok(BackendShutdownOutcome::Graceful) => {}
            Ok(BackendShutdownOutcome::Forced) => {
                eprintln!("InvoiceHub backend required forced termination during host exit");
            }
            Err(error) => {
                eprintln!("InvoiceHub desktop host exit was blocked: {error}");
                return false;
            }
        }
    }
    true
}

fn complete_setup_failure_cleanup(backend: &BackendHost) {
    loop {
        match backend.shutdown_keep_monitor_or_terminate() {
            Ok(BackendShutdownOutcome::Graceful) => return,
            Ok(BackendShutdownOutcome::Forced) => {
                eprintln!("InvoiceHub backend required forced termination during desktop setup");
                return;
            }
            Err(cleanup_error) => {
                eprintln!(
                    "InvoiceHub desktop setup remains blocked until owned backend termination is confirmed: {cleanup_error}"
                );
                std::thread::sleep(std::time::Duration::from_secs(1));
            }
        }
    }
}

fn install_tray(app: &tauri::App<tauri::Wry>, icon_id: AppIconId) -> Result<(), Box<dyn Error>> {
    let open_item = MenuItem::with_id(app, TRAY_OPEN_ID, "Open InvoiceHub", true, None::<&str>)?;
    let quit_item = MenuItem::with_id(app, TRAY_QUIT_ID, "Quit InvoiceHub", true, None::<&str>)?;
    let diagnose_item = MenuItem::with_id(
        app,
        TRAY_DIAGNOSE_ID,
        "运行状态与启动诊断",
        true,
        None::<&str>,
    )?;
    let menu = Menu::with_items(app, &[&open_item, &diagnose_item, &quit_item])?;
    let mut tray = TrayIconBuilder::with_id("invoicehub")
        .menu(&menu)
        .tooltip(format!("InvoiceHub | PID {}", std::process::id()))
        .on_menu_event(|app, event| {
            if event.id() == TRAY_OPEN_ID {
                reopen_startup_surface(app);
            } else if event.id() == TRAY_QUIT_ID {
                quit_from_tray(app);
            } else if event.id() == TRAY_DIAGNOSE_ID {
                let runtime = app
                    .try_state::<BackendHost>()
                    .map(|backend| backend.runtime_dir().to_path_buf());
                std::thread::spawn(move || {
                    startup_diagnostics::present("当前运行实例", runtime.as_deref(), None)
                });
            }
        });
    tray = tray.icon(app_icon::image_for(icon_id)?);
    let tray = tray.build(app)?;
    app.manage(tray);
    Ok(())
}

fn main() -> ExitCode {
    // This read-only entry works even if the bundle is damaged or another host owns the port.
    if std::env::args().any(|arg| arg == "--diagnose-startup") {
        startup_diagnostics::present("启动环境检查", None, None);
        return ExitCode::SUCCESS;
    }
    let surface_override = match parse_surface_override(std::env::args().skip(1)) {
        Ok(surface) => surface,
        Err(error) => {
            startup_diagnostics::present(&error.to_string(), None, None);
            return ExitCode::from(64);
        }
    };
    // A checkout has no signed bundle manifest, so it cannot attach to a listener or start a host.
    let bundle_root = match default_bundle_root() {
        Ok(root) => root,
        Err(error) => {
            startup_diagnostics::present(&format!("启动失败：{error}"), None, None);
            return ExitCode::from(78);
        }
    };
    let manifest = match load_bundle_manifest(&bundle_root) {
        Ok(manifest) => manifest,
        Err(error) => {
            startup_diagnostics::present(&format!("启动失败：{error}"), None, None);
            return ExitCode::from(78);
        }
    };
    let updater_public_key = manifest.updater().public_key().map(str::to_owned);
    let diagnostic_runtime = manifest.expected_identity().runtime_dir.clone();
    let diagnostic_config = manifest.expected_identity().config_path.clone();
    let setup_diagnostic_runtime = diagnostic_runtime.clone();
    let setup_diagnostic_config = diagnostic_config.clone();
    let setup_failed = Arc::new(AtomicBool::new(false));
    let setup_failure_flag = Arc::clone(&setup_failed);
    #[allow(unused_mut)]
    let mut context = tauri::generate_context!();
    #[cfg(windows)]
    {
        let executable = std::env::current_exe().unwrap_or_default();
        context.config_mut().identifier = startup_diagnostics::instance_identifier(
            &context.config().identifier,
            &executable,
            &diagnostic_runtime,
        );
    }

    let mut builder = tauri::Builder::default()
        .plugin(tauri_plugin_dialog::init())
        .plugin(
            tauri_plugin_opener::Builder::new()
                .open_js_links_on_click(false)
                .build(),
        )
        .plugin(tauri_plugin_single_instance::init(|app, _args, _cwd| {
            reopen_startup_surface(app);
        }))
        .on_window_event(|window, event| {
            if window.label() == MAIN_WINDOW_LABEL {
                if let WindowEvent::CloseRequested { api, .. } = event {
                    api.prevent_close();
                    let _ = window.hide();
                }
            }
        });
    #[cfg(target_os = "macos")]
    {
        builder = builder
            .menu(build_application_menu)
            .on_menu_event(|app, event| {
                if event.id() == APP_QUIT_ID {
                    request_application_exit(app);
                }
            });
    }
    if let Some(public_key) = updater_public_key {
        builder = builder.plugin(
            tauri_plugin_updater::Builder::new()
                .pubkey(public_key)
                .build(),
        );
    }
    let app = match builder
        .setup(move |app| -> Result<(), Box<dyn Error>> {
            // Tauri executes setup during run(), where returning Err panics instead of
            // reaching Builder::build's error arm. Present and request an orderly exit here.
            let outcome = (|| -> Result<(), Box<dyn Error>> {
            let backend = BackendHost::launch(manifest, app.handle().clone())?;
            let mut startup_surface = surface_override.unwrap_or(backend.startup_surface());
            let app_icon_id = app_icon::load_selected(backend.runtime_dir());
            let setup_result = (|| -> Result<(), Box<dyn Error>> {
                install_tray(app, app_icon_id)?;
                startup_surface = start_surface(
                    startup_surface,
                    || create_desktop_window(
                        app,
                        app_icon_id,
                        backend.webview_data_directory(),
                        backend.allow_print_popups(),
                    ),
                    |error| {
                        startup_diagnostics::save(&format!("桌面窗口创建失败：{error}"),
                            Some(&setup_diagnostic_runtime), Some(&setup_diagnostic_config));
                        startup_diagnostics::offer_browser_fallback()
                    },
                    || backend.verify_surface_ownership().map_err(Into::into),
                    || { open_backend_in_browser(&app.handle())?; Ok(()) },
                )?;
                Ok(())
            })();
            if let Err(error) = setup_result {
                complete_setup_failure_cleanup(&backend);
                return Err(error);
            }
            if let Err(error) = backend.release_startup_gate() {
                complete_setup_failure_cleanup(&backend);
                return Err(Box::new(error));
            }
            app.manage(backend);
            app.manage(startup_surface);
            if let Some(backend) = app.try_state::<BackendHost>() {
                match backend.activate_updater_runtime() {
                    Ok(true) => {
                        eprintln!("InvoiceHub updater recovery runtime activated");
                    }
                    Ok(false) => {}
                    Err(error) => {
                        eprintln!(
                            "InvoiceHub updater runtime is unavailable; the backend remains available for diagnostics: {error}"
                        );
                    }
                }
            }
            Ok(())
            })();
            if let Err(error) = outcome {
                setup_failure_flag.store(true, Ordering::Release);
                startup_diagnostics::present(
                    &format!("启动失败：{error}"),
                    Some(&setup_diagnostic_runtime),
                    Some(&setup_diagnostic_config),
                );
                app.handle().exit(1);
            }
            Ok(())
        })
        .build(context)
    {
        Ok(app) => app,
        Err(error) => {
            startup_diagnostics::present(&format!("启动失败：{error}"), Some(&diagnostic_runtime), Some(&diagnostic_config));
            return ExitCode::FAILURE;
        }
    };
    let exit_code = app.run_return(|app_handle, event| {
        if let RunEvent::ExitRequested { api, .. } = event {
            if !prepare_backend_exit(app_handle) {
                api.prevent_exit();
            }
        }
    });
    if setup_failed.load(Ordering::Acquire) || exit_code != 0 {
        ExitCode::FAILURE
    } else {
        ExitCode::SUCCESS
    }
}

fn parse_surface_override(
    args: impl Iterator<Item = String>,
) -> Result<Option<StartupSurface>, Box<dyn Error>> {
    let mut selected = None;
    for arg in args {
        let surface = match arg.as_str() {
            "--browser" => StartupSurface::Browser,
            "--desktop" => StartupSurface::Desktop,
            _ => continue,
        };
        if selected.is_some_and(|previous| previous != surface) {
            return Err("启动参数冲突：--browser 与 --desktop 只能选择一个".into());
        }
        selected = Some(surface);
    }
    Ok(selected)
}

fn start_surface(
    preferred: StartupSurface,
    desktop: impl FnOnce() -> Result<(), Box<dyn Error>>,
    offer_fallback: impl FnOnce(&dyn Error) -> bool,
    verify: impl FnOnce() -> Result<(), Box<dyn Error>>,
    browser: impl FnOnce() -> Result<(), Box<dyn Error>>,
) -> Result<StartupSurface, Box<dyn Error>> {
    if preferred == StartupSurface::Desktop {
        match desktop() {
            Ok(()) => return Ok(StartupSurface::Desktop),
            Err(error) => {
                if !offer_fallback(error.as_ref()) {
                    return Err(error);
                }
            }
        }
    }
    // Only a window-creation failure can offer fallback. Backend/identity failures never
    // reach here, and acceptance rechecks ownership after the potentially long native prompt.
    verify()?;
    browser()?;
    Ok(StartupSurface::Browser)
}

fn create_desktop_window(
    app: &tauri::App<tauri::Wry>,
    icon_id: AppIconId,
    webview_data_directory: &Path,
    allow_print_popups: bool,
) -> Result<(), Box<dyn Error>> {
    let backend_url = invoicehub_desktop::backend_origin().parse()?;
    let app_handle = app.handle().clone();
    let window = tauri::WebviewWindowBuilder::new(
        app,
        MAIN_WINDOW_LABEL,
        tauri::WebviewUrl::External(backend_url),
    )
    .title("InvoiceHub")
    .icon(app_icon::image_for(icon_id)?)?
    .inner_size(1280.0, 860.0)
    .min_inner_size(1024.0, 640.0)
    .data_directory(webview_data_directory.to_path_buf())
    .on_new_window(move |url, features| {
        // A child starts blank and can reach only a validated local print job, never a general popup.
        if !allow_print_popups || !is_print_popup_initial_url(url.as_str()) {
            return tauri::webview::NewWindowResponse::Deny;
        }
        let label = format!(
            "invoice-print-{}",
            PRINT_POPUP_WINDOW_SEQUENCE.fetch_add(1, Ordering::Relaxed),
        );
        let builder =
            tauri::WebviewWindowBuilder::new(&app_handle, label, tauri::WebviewUrl::External(url))
                .title("InvoiceHub - 发票打印")
                .inner_size(1000.0, 760.0)
                .min_inner_size(640.0, 480.0)
                .window_features(features)
                .on_navigation(|destination| is_print_popup_navigation_url(destination.as_str()));
        match builder.build() {
            Ok(window) => tauri::webview::NewWindowResponse::Create { window },
            Err(error) => {
                eprintln!("InvoiceHub could not create its print popup: {error}");
                tauri::webview::NewWindowResponse::Deny
            }
        }
    })
    .build()?;
    let drop_window = window.clone();
    window.on_webview_event(move |event| {
        // Forward paths only to the owned localhost homepage; never expose private Host RPC credentials.
        if drop_window.url().ok().is_none_or(|url| !invoicehub_desktop::accepts_temporary_file_drop(&url)) {
            return;
        }
        if let tauri::WebviewEvent::DragDrop(tauri::DragDropEvent::Drop { paths, .. }) = event {
            let paths: Vec<String> = paths.iter().map(|path| path.to_string_lossy().into_owned()).collect();
            if let Ok(payload) = serde_json::to_string(&paths) {
                let _ = drop_window.eval(&format!("window.dispatchEvent(new CustomEvent('invoicehub:temporary-drop', {{detail:{payload}}}));"));
            }
        }
    });
    Ok(())
}

fn is_print_popup_initial_url(url: &str) -> bool {
    url == PRINT_POPUP_INITIAL_URL
}

fn is_print_popup_navigation_url(url: &str) -> bool {
    if is_print_popup_initial_url(url) {
        return true;
    }
    let prefix = format!(
        "{}{}",
        invoicehub_desktop::backend_origin(),
        PRINT_POPUP_ROUTE_PREFIX
    );
    let Some(job_id) = url.strip_prefix(&prefix) else {
        return false;
    };
    (PRINT_POPUP_JOB_ID_MIN_LENGTH..=PRINT_POPUP_JOB_ID_MAX_LENGTH).contains(&job_id.len())
        && job_id
            .bytes()
            .all(|byte| byte.is_ascii_alphanumeric() || matches!(byte, b'-' | b'_'))
}

#[cfg(test)]
mod startup_tests {
    use super::*;
    use std::cell::{Cell, RefCell};

    #[test]
    fn successful_desktop_never_prompts_or_opens_browser() {
        assert_eq!(
            start_surface(
                StartupSurface::Desktop,
                || Ok(()),
                |_| panic!("unexpected prompt"),
                || panic!("unexpected retry"),
                || panic!("unexpected browser")
            )
            .unwrap(),
            StartupSurface::Desktop
        );
    }

    #[test]
    fn accepted_fallback_revalidates_before_opening_browser_once() {
        let order = RefCell::new(Vec::new());
        let result = start_surface(
            StartupSurface::Desktop,
            || {
                order.borrow_mut().push("desktop");
                Err("window unavailable".into())
            },
            |_| {
                order.borrow_mut().push("prompt");
                true
            },
            || {
                order.borrow_mut().push("verify");
                Ok(())
            },
            || {
                order.borrow_mut().push("browser");
                Ok(())
            },
        );
        assert_eq!(result.unwrap(), StartupSurface::Browser);
        assert_eq!(*order.borrow(), ["desktop", "prompt", "verify", "browser"]);
    }

    #[test]
    fn declined_fallback_preserves_window_error_without_opening_browser() {
        let result = start_surface(
            StartupSurface::Desktop,
            || Err("window unavailable".into()),
            |_| false,
            || panic!("unexpected verification"),
            || panic!("unexpected browser"),
        );
        assert_eq!(result.unwrap_err().to_string(), "window unavailable");
    }

    #[test]
    fn ownership_lost_during_prompt_blocks_fallback() {
        let opened = Cell::new(false);
        let result = start_surface(
            StartupSurface::Desktop,
            || Err("window unavailable".into()),
            |_| true,
            || Err("ownership lost".into()),
            || {
                opened.set(true);
                Ok(())
            },
        );
        assert_eq!(result.unwrap_err().to_string(), "ownership lost");
        assert!(!opened.get());
    }

    #[test]
    fn browser_override_skips_webview_and_propagates_browser_failure() {
        let result = start_surface(
            StartupSurface::Browser,
            || panic!("unexpected WebView"),
            |_| panic!("unexpected prompt"),
            || Ok(()),
            || Err("browser launch failed".into()),
        );
        assert_eq!(result.unwrap_err().to_string(), "browser launch failed");
    }

    #[test]
    fn launch_flags_are_optional_and_conflicting_modes_are_rejected() {
        let parse = |args: &[&str]| parse_surface_override(args.iter().map(|arg| arg.to_string()));
        assert_eq!(parse(&[]).unwrap(), None);
        assert_eq!(
            parse(&["--browser"]).unwrap(),
            Some(StartupSurface::Browser)
        );
        assert_eq!(
            parse(&["--desktop"]).unwrap(),
            Some(StartupSurface::Desktop)
        );
        assert!(parse(&["--browser", "--desktop"]).is_err());
    }
}
