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
Its ordinary `stage/build` actions stage an allowlisted shared core, create an
updater-disabled schema-3 `development` manifest and explicit virtual-
environment launcher, and bind both manifest and launcher SHA-256 values while
building one macOS arm64 `.app`. Build accepts an absolute pnpm or direct Tauri
CLI executable. The explicit `stage-recovery/build-recovery` actions differ
only by writing the exact L10-E non-installing recovery-smoke tuple. Every
development bundle is local and ignored; none creates a DMG, NSIS installer,
update archive, release manifest, release signature, or Feed input.

The development manifest resolves resources from `Contents/Resources` and
rejects a package manifest. Ordinary manifests explicitly disable updater
delegation. An enabled development manifest is valid only when its updater
object has exactly `enabled`, `endpoint`, and `public_key`, with the endpoint
fixed to unreachable `https://127.0.0.1:1/invoicehub-recovery-smoke/latest.json`
and the key fixed to a sentinel that is not a signing key. Arbitrary endpoints,
keys, or extra fields fail closed.
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
enums `update_check` and `update_install`. A complete host-owned candidate is
bounded to 300 seconds; updater metadata and the retained download object both
use a five-second timeout. Updater-disabled profiles remain inert. An enabled
profile activates only after the owned startup gate is released and
`BackendHost` is registered, opens the platform marker store under the strict
backend `runtime_dir`, and completes authenticated startup restore before it
accepts update operations.

`update_install` accepts no caller metadata. It atomically consumes one fresh
candidate, reserves the runtime, and starts a private worker behind an
execute/cancel latch. Only after the exact `{"ok":true}` response is written
and flushed does that worker run Tauri download with built-in signature
verification -> owned-monitor pause -> install -> platform relaunch. Response
write failure, worker spawn failure, or latch loss enters `CommitLost` without
download, marker, monitor, or installer effects. Startup restore or transaction
failure leaves the backend/WebUI available for diagnostics and blocks further
updater work in that process.

## L10-R/C foundation and L10-D runtime wiring

L10-R established the source-level recovery primitive. It captures a released
owned lifecycle lease containing generation, phase, health/owned/process PIDs,
and a state scope, and revalidates it around every marker or bridge operation.
A pause requires a ready owned monitor, will not overwrite an existing marker,
and preserves the marker on failure; restore clears only after a later owned
status is both running and ready. L10-C then added the fixed-loopback bridge,
pure update coordinator, shared lifecycle authority, the Windows
handle-relative/no-reparse marker store, and Unix whole-operation locking. The
historical L10-C verification passed 56 Rust checks and 42 Python contracts; it
did not itself wire Host RPC, updater, startup restore, or a real monitor.

L10-D wires those seams into the owned host runtime. Every recovery request and
exact response uses a fresh challenge and HMAC-SHA256 under the existing
backend-private ownership secret; Python rejects incomplete, tampered,
non-empty, or replayed authenticated requests, while ordinary browser bridge
calls keep their prior unauthenticated localhost behavior. The host retains the
cloneable Tauri `Update` and a private domain-separated artifact identity, then
uses `UpdateCoordinator` for the fixed verified-download -> pause -> install ->
relaunch order. Windows confirms managed-backend termination in
`on_before_exit`; macOS stops the backend, marks relaunch prepared, and calls
`request_restart()`. Normal Quit is blocked while a commit is reserved or
executing. These are source and contract boundaries only: ordinary development
and internal-alpha profiles disable updater, and no real Feed, update, restart,
package, signing, or platform smoke is claimed.

L10-E adds `scripts/dev/tauri_recovery_smoke.py` solely to exercise authenticated
startup restore. It accepts only the exact recovery App, creates temporary HOME,
state, runtime, and watch directories, writes `auto_check_updates=false`, seeds
a scope-bound prior marker, then permits only health, monitor status, and
monitor stop requests. Authenticated monitor start comes from the host recovery
transaction itself; the runner cannot request bridge start or updater check/
install. It verifies App/health/path ownership before cleanup and terminates only
its spawned process group. The locked offline macOS arm64 sample restored an
owned monitor to `running && ready`, removed the marker, explicitly stopped the
monitor, and cleared its process group, fixed port, and temporary directories;
the runner reported `update_requests=0`. This remains startup-recovery evidence,
not Feed, candidate, download, signature-validation, install, or restart evidence.

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

The ordinary development app disables this updater path. L9/P1-Q did not
exercise browser, tray clicking, second-instance, native-picker, printing,
download, signature validation, monitor-stop-for-install, installation,
restart, Windows, DMG, Developer ID, notarization, Release, or Feed behavior.
L10-E does not widen those claims. Neither profile is release evidence.
