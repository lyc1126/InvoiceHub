# Tauri Host Boundary

This directory hosts the Tauri 2 adapter for the existing InvoiceHub Python,
FastAPI, Web, and independent-monitor core. It contains no invoice,
projection, bookkeeping, or monitor business logic.

## Development app

A bare source checkout is intentionally not runnable: `main.rs` requires an
`invoicehub-desktop-host.json` whose raw SHA-256 matches the compile-time
`INVOICE_HUB_BUNDLE_MANIFEST_SHA256`; missing or mismatched inputs exit with
status 78 before the host attaches to a listener or opens a WebView.

`scripts/dev/tauri_dev_app.py` is the only development assembly entry point.
It stages an allowlisted shared core, creates a schema-3 `development` manifest
and an explicit virtual-environment launcher, and binds both the manifest and
launcher SHA-256 values while building one macOS arm64 `.app`. It requires an
absolute venv Python; its build action also requires an absolute pnpm
executable. The development bundle is local and ignored. It does not create a
DMG, NSIS installer, update archive, release manifest, release signature, or
Feed input.

The development manifest resolves resources from `Contents/Resources`, rejects
a package manifest, and explicitly disables updater delegation.
`INVOICE_HUB_DEV_STATE_ROOT` is required for a development launch: it must name
an existing absolute directory. The host canonicalizes it and rejects either
containment direction between that state root and the bundle/core root. Release
manifests, missing or relative values fail closed, and the variable is removed
before Python is spawned. It exists only to run isolated development smoke
tests without reading or writing real user Application Support state.

L8-S, L9, and P1-Q passed their bounded macOS arm64 samples: an isolated app owned exactly
`127.0.0.1:8766`, health and background startup reached ready, the homepage and
static assets loaded, `desktop_available=true` and the default desktop surface
were observed. An external AppleScript quit released the process, port, and PID
but bypassed structured shutdown and left stale server state, so that external
path remains outside the contract. The clean-commit P1-Q sample sent a genuine
Cmd-Q to the foreground app and observed the shutdown POST, stopped state,
monitor remaining stopped, and host/backend/PID/port cleanup. Open SSE
connections required the explicit kill-and-wait fallback after stopped state
was written. The first
launch exposed a tray initialization failure caused by a 16-bit RGBA icon.
`icons/icon.png` is now 8-bit RGBA and an IHDR-focused test locks that exact
failure mechanism. The matching multi-resolution `icons/icon.ico` is required
by Tauri's Windows resource build and is generated from that controlled PNG.

## Runtime boundary

With a valid manifest, the host rejects an occupied fixed port, spawns its own
backend, and requires a fresh HMAC-SHA256 ownership challenge plus child PID,
build/package identity, static-home, and OpenAPI-method checks. It repeats the
ownership proof after reading `startup_surface`, then creates the zero-IPC
desktop WebView or uses the fixed-origin host-only browser opener. The Host RPC
token goes only to the directly spawned Python backend, which captures it and
removes it from descendants; it never reaches Web content, Tauri commands or
events, API responses, or logs.

The private loopback listener accepts four picker enums and the two updater
enums `update_check` and `update_install`. A candidate is bounded to 300
seconds, and updater metadata requests have a five-second total timeout.
`tauri-plugin-dialog` owns asynchronous main-thread dispatch for its picker;
`host_rpc.rs` calls that plugin directly and must not wrap it in a second
`run_on_main_thread` hop. The first Windows candidate returned a redacted
picker error before the chooser appeared, so this narrow source repair still
requires a fresh clean ZIP native-picker acceptance sample.
Until a complete recovery/relaunch coordinator exists, `update_install`
consumes the candidate and returns unavailable; it does not download, stop the
monitor, install, or restart. The later release coordinator must preserve the
order download plus Minisign verification, monitor stop and independent recheck,
then install/restart, with recovery on every failed path.

Tray Quit and the custom macOS application-menu Quit item/Cmd-Q both request
`app.exit(0)`. The menu must not use the predefined native Quit selector,
which can bypass Tauri's interceptable event. Every `ExitRequested` received
by the host first requests the structured `keep_monitor` shutdown and waits
for the owned backend. API failure or timeout explicitly kills and waits for
that child; inability to confirm termination prevents host exit. Process
`Drop` is not an exit fallback. External AppleScript quit, Force Quit, SIGKILL,
logout, and power loss are outside this orderly-shutdown contract.

During Tauri `setup`, the spawned backend remains a local value until tray and
the selected desktop/browser surface have initialized. If any of those steps
fails, the host explicitly uses the same keep-monitor shutdown and kill/wait
fallback. If termination is still not confirmed, setup remains blocked and
retries instead of returning the original surface error to `Drop`; a child
mutex or `try_wait` error cannot count as a graceful exit. This path does not
depend on the later `ExitRequested` handler or `Drop`.

The development app disables this updater path. L9/P1-Q did not exercise browser,
tray clicking, second-instance, native-picker, printing, download, signature validation,
monitor-stop-for-install, installation, restart, Windows, DMG, Developer ID,
notarization, Release, or Feed behavior. It is not release evidence.

## Windows portable alpha.2

`scripts/dev/tauri_windows_portable.py` is the separate Windows 10/11 x64
portable assembly path. It stages a clean exact Git commit, copies only the
allowlisted shared core and locked Python 3.14.6 runtime, writes a schema-3
release host manifest, and compiles the raw host with that manifest's exact
SHA-256. The ZIP contains `InvoiceHub.exe`, the host manifest, the runtime,
core manifests, SBOM, file-SHA manifest, licenses, receipt, and no user
configuration, invoices, logs, or runtime state.

The only release-manifest exception is a Windows x86_64 portable identity with
the exact `windows_portable` marker `{"distribution":"zip","updater_enabled":false}`.
That marker permits `updater.enabled=false`; every other release host remains
strict. The release state root is `%LOCALAPPDATA%\\InvoiceHub`. Before the
owned child starts, the host derives and creates its `webview` child and passes
that exact path to the desktop `WebviewWindowBuilder` as WebView2 user data.
The default surface is desktop, close hides the window, and tray Quit follows
the existing structured keep-monitor shutdown path.

The Windows release host uses the GUI PE subsystem, so opening `InvoiceHub.exe`
does not show a terminal window. Its Python child receives `CREATE_NO_WINDOW`;
the host appends backend stdout and stderr to `runtime/server_stdout.log` and
`runtime/server_stderr.log` under the same user-state root. Debug builds retain
a console for development diagnostics.

The ZIP is unsigned, has no MSI/NSIS installer, and never replaces its own
directory. Its Windows-only alpha Feed is check-only: the UI may open the
GitHub prerelease page, while `update_install` remains unavailable. Rust 1.85
MSVC, C++ Build Tools/Windows SDK, and Evergreen WebView2 are build/runtime
prerequisites; the doctor reports missing WebView2 without installing it.
One statically verified candidate reached owned-backend handshake under
isolated LocalAppData but failed desktop WebView creation with Windows access
denied at Tauri's implicit profile location. The explicit `webview` state path
is therefore source-level repair only, not native Windows build, tray, picker,
monitor, or publication evidence until a freshly rebuilt isolated ZIP smoke
has completed.
