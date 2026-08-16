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

L8-S and L9 passed once on macOS arm64: an isolated app owned exactly
`127.0.0.1:8766`, health and background startup reached ready, the homepage and
static assets loaded, `desktop_available=true` and the default desktop surface
were observed, and orderly shutdown released the port and PID state. The first
launch exposed a tray initialization failure caused by a 16-bit RGBA icon.
`icons/icon.png` is now 8-bit RGBA and an IHDR-focused test locks that exact
failure mechanism.

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
Until a complete recovery/relaunch coordinator exists, `update_install`
consumes the candidate and returns unavailable; it does not download, stop the
monitor, install, or restart. The later release coordinator must preserve the
order download plus Minisign verification, monitor stop and independent recheck,
then install/restart, with recovery on every failed path.

Tray Quit only requests the common Tauri exit path. System Quit, Cmd-Q, and
every other `ExitRequested` first request the structured `keep_monitor`
shutdown and wait for the owned backend. API failure or timeout explicitly
kills and waits for that child; inability to confirm termination prevents host
exit. Process `Drop` is not an exit fallback.

The development app disables this updater path. L9 did not exercise browser,
tray, second-instance, native-picker, printing, download, signature validation,
monitor-stop-for-install, installation, restart, Windows, DMG, Developer ID,
notarization, Release, or Feed behavior. It is not release evidence.
