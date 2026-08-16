use std::error::Error;
use std::process::ExitCode;

use tauri::{
    menu::{Menu, MenuItem},
    tray::TrayIconBuilder,
    Manager, RunEvent, WindowEvent,
};
use tauri_plugin_opener::OpenerExt;

use invoicehub_desktop::backend::{
    default_bundle_root, load_bundle_manifest, BackendHost, BackendShutdownOutcome, StartupSurface,
};

const MAIN_WINDOW_LABEL: &str = "main";
const TRAY_OPEN_ID: &str = "invoicehub-open";
const TRAY_QUIT_ID: &str = "invoicehub-quit";

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

fn quit_from_tray(app: &tauri::AppHandle<tauri::Wry>) {
    app.exit(0);
}

fn prepare_backend_exit(app: &tauri::AppHandle<tauri::Wry>) -> bool {
    if let Some(backend) = app.try_state::<BackendHost>() {
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

fn install_tray(app: &tauri::App<tauri::Wry>) -> Result<(), Box<dyn Error>> {
    let open_item = MenuItem::with_id(app, TRAY_OPEN_ID, "Open InvoiceHub", true, None::<&str>)?;
    let quit_item = MenuItem::with_id(app, TRAY_QUIT_ID, "Quit InvoiceHub", true, None::<&str>)?;
    let menu = Menu::with_items(app, &[&open_item, &quit_item])?;
    let mut tray = TrayIconBuilder::with_id("invoicehub")
        .menu(&menu)
        .tooltip("InvoiceHub")
        .on_menu_event(|app, event| {
            if event.id() == TRAY_OPEN_ID {
                reopen_startup_surface(app);
            } else if event.id() == TRAY_QUIT_ID {
                quit_from_tray(app);
            }
        });
    if let Some(icon) = app.default_window_icon() {
        tray = tray.icon(icon.clone());
    }
    tray.build(app)?;
    Ok(())
}

fn main() -> ExitCode {
    // A checkout has no signed bundle manifest, so it cannot attach to a listener or start a host.
    let bundle_root = match default_bundle_root() {
        Ok(root) => root,
        Err(error) => {
            eprintln!("{error}");
            return ExitCode::from(78);
        }
    };
    let manifest = match load_bundle_manifest(&bundle_root) {
        Ok(manifest) => manifest,
        Err(error) => {
            eprintln!("{error}");
            return ExitCode::from(78);
        }
    };
    let updater_public_key = manifest.updater().public_key().map(str::to_owned);

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
    if let Some(public_key) = updater_public_key {
        builder = builder.plugin(
            tauri_plugin_updater::Builder::new()
                .pubkey(public_key)
                .build(),
        );
    }
    let app = match builder
        .setup(move |app| -> Result<(), Box<dyn Error>> {
            let backend = BackendHost::launch(manifest, app.handle().clone())?;
            let startup_surface = backend.startup_surface();
            app.manage(backend);
            app.manage(startup_surface);
            install_tray(app)?;
            match startup_surface {
                StartupSurface::Desktop => create_desktop_window(app)?,
                StartupSurface::Browser => open_backend_in_browser(&app.handle())?,
            }
            Ok(())
        })
        .build(tauri::generate_context!())
    {
        Ok(app) => app,
        Err(error) => {
            eprintln!("InvoiceHub desktop host failed: {error}");
            return ExitCode::FAILURE;
        }
    };
    app.run(|app_handle, event| {
        if let RunEvent::ExitRequested { api, .. } = event {
            if !prepare_backend_exit(app_handle) {
                api.prevent_exit();
            }
        }
    });
    ExitCode::SUCCESS
}

fn create_desktop_window(app: &tauri::App<tauri::Wry>) -> Result<(), Box<dyn Error>> {
    let backend_url = invoicehub_desktop::backend_origin().parse()?;
    tauri::WebviewWindowBuilder::new(
        app,
        MAIN_WINDOW_LABEL,
        tauri::WebviewUrl::External(backend_url),
    )
    .title("InvoiceHub")
    .inner_size(1280.0, 860.0)
    .min_inner_size(1024.0, 640.0)
    .build()?;
    Ok(())
}
