# InvoiceHub macOS

InvoiceHub macOS is the first local shell for the existing InvoiceHub Python/FastAPI core.

The shared/platform responsibility split is documented in [`docs/architecture/PLATFORM_ARCHITECTURE.md`](../../docs/architecture/PLATFORM_ARCHITECTURE.md). The public repository is being prepared as a single sanitized root snapshot; retired private commits, packages, tags and validation material are not public release inputs. The existing SwiftUI/WKWebView/Sparkle code remains a development and migration reference for the shared-core boundary, but it is not a public release path. The next desktop implementation is Tauri 2 on `codex/tauri2-unified-desktop`, only after candidate-tree, Git-object and hosting verification, beginning at `0.3.0-alpha.1` and reusing Python/FastAPI/Web/monitor rather than rewriting business logic.

The first version keeps the current `v1 localhost` product model:

- SwiftUI owns the macOS window, menus, folder picker, Sparkle integration, startup surface, and backend process lifecycle.
- WKWebView loads the existing local web UI.
- Python continues to own invoice extraction, monitoring, summaries, cost analysis, CSV/XLSX/JSON projections, and `/api/v1`.
- Runtime state is written under `~/Library/Application Support/InvoiceHub`, not inside the app bundle.
- Docker is not a user runtime dependency.

## Run In Development

From this directory:

```bash
./script/build_and_run.sh
```

Useful modes:

```bash
./script/build_and_run.sh --build-only
./script/build_and_run.sh --verify
./script/build_and_run.sh --logs
./script/build_and_run.sh --debug
```

The script stages a local `dist/InvoiceHubMac.app`, copies the repo `src` and `web` folders into app resources without local Python/Finder caches, prepares `macos/InvoiceHubMac/.backend-venv` when backend dependencies are missing, and writes that Python path to `dev-python-path.txt`. It generates a deterministic build manifest and only stops an old backend when both its `invoice_hub.api.main` command and Application Support config path match. If TERM times out, the script rechecks that exact PID, command, and config before using KILL. Unknown port owners are reported and left running; the script never switches ports automatically. `--build-only` rebuilds the bundle without opening the app, stopping localhost, or touching monitor state. This development lookup remains available only outside formal release mode: a formal App must resolve the shared core solely from `Contents/Resources/invoice-hub-core` and fails closed rather than falling back to the checkout.

Inside the WKWebView, the watch-directory, outbound-invoice-directory, and OCR-candidate-directory buttons are bridged to Swift and use `NSOpenPanel`. HTML file inputs are handled by `WKUIDelegate`; the skins page opens a native panel restricted to one ZIP file. They should not launch Python Launcher or the Python/Tk dialog path; the generic Python picker remains a fallback for non-macOS-shell browser use.

Rebuilding an unsigned development app can change the identity macOS TCC associates with protected folders such as Downloads. If the strict localhost handshake succeeds but the page reports `Load failed` or health reports `background_status=failed`, obtain explicit user permission, reselect and save the current folder through the real `NSOpenPanel`, then verify `background_status=ready`, a manual rebuild, and source-file preview. `health.ok=true` alone does not prove the business folder is readable.

The macOS sidebar contains 首页, 成本分析, 单据, 做账, OCR, 一致性, and 设置. 皮肤 remains reachable from 设置, while 诊断 is available from the menu instead of normal user navigation. The 单据 page still uses the Python/FastAPI `/api/v1/documents/*` module for validation, previews, exports, saved defaults, and file opening; 做账 reuses `/api/v1/bookkeeping/*`; the 首页 source-file preview and batch printing paths also remain Python/FastAPI jobs. Swift only owns native shell concerns and navigation.

Folder changes remain a web-page draft flow: select, validate through the backend, then save. Native rebuild and monitor actions reuse `/api/v1`, refresh the WKWebView, and surface backend messages. Async completions are accepted only while their captured lifecycle generation, phase, ownership, health PID, and Process PID still match. The shell accepts a backend only when build/package manifests and health agree on release identity, build ID, API contract, bookkeeping protocol, complete capabilities, config/runtime paths and PID; required static pages must load and `/openapi.json` must register every required API. Compatibility checks do not load business-data endpoints and every probe is bounded. The current handshake requires API contract `2026-08-02-release-update-v1`, bookkeeping protocol `w9-ledger-review-v1`, existing W8/W9/invoice/monitor/server capabilities, and `release.package-identity.v1`, `settings.startup-surface.v1`, and `updates.metadata-check.v1`.

The startup preference defaults to `desktop`. Selecting `browser` starts the same owned backend, opens the fixed localhost URL in the system browser, and hides the main window; the choice takes effect on the next launch. About/update metadata remains in the shared Web settings page. Clicking “检查更新” from the Mac shell invokes Sparkle 2.9.2 only when the current lifecycle is exact `owned`; immediately before relaunch, the updater rechecks that token, writes an Application Support marker and stops the monitor. Cancellation or failure restores a previously running monitor only while a verified owned lifecycle remains; an `externalCompatible` service receives no update bridge and is never stopped or restored by this App. The new version clears the marker only after strict handshake and monitor readiness.

Only a backend launched by the current shell is `owned` and eligible for native stop or restart. A compatible service with unknown ownership is `externalCompatible`: the Web settings shutdown control is disabled and Swift rejects owned-only lifecycle actions. Native “stop page service” calls `POST /api/v1/server/shutdown` with `keep_monitor` and `remember=false`; it accepts only `ok=true`, `scheduled || idempotent`, and a matching returned behavior. Failure leaves the service, PID, and ownership intact. App termination may directly converge an owned child, but cleanup occurs only after the process is confirmed exited. The app disables AppKit automatic termination while running so the local backend is not stopped by an empty transient window-restoration state.

WKWebView navigation, script messages, and native upload panels are restricted to the expected `http://127.0.0.1:<fixed-port>` main frame. External pages and subframes cannot call `window.invoiceHubMac` or open a native panel. The shared preview page keeps an open preview job alive through the backend's bounded idle lease and automatically recreates an expired or restart-lost job while preserving the selected file and page; Swift verifies the keep-alive POST route through OpenAPI but does not duplicate this web behavior. Batch printing is narrower still: a trusted main frame may create only exact `about:blank`; its registered popup may load or reload only its same registered, same-port `/invoices/print/{job_id}` path without query or fragment. The popup receives only `invoiceHubMacPrint`; its `window.print()` call is revalidated against the popup identity and registered route before `WKWebView.printOperation(with:)` opens the system panel. Canceling that panel is a normal completion and dispatches `afterprint`; no folder or backend bridge is exposed to the popup. On close it leaves the active message registry but remains in a process-lifetime quarantine, including across SwiftUI WebView rebuilding; do not release or reconfigure its WebKit objects from close, print, or timer callbacks.

If the first launch shows a local service timeout, inspect:

```text
~/Library/Application Support/InvoiceHub/runtime/server_stderr.log
```

`ModuleNotFoundError: No module named 'fastapi'` means the app was launched with a Python environment that does not have the backend dependencies. Re-run `./script/build_and_run.sh`; it should rebuild `.backend-venv` and restage the app resource marker.

## SwiftPM

Products:

- `InvoiceHubMac`: SwiftUI executable app.
- `InvoiceHubClient`: testable library containing backend path resolution, API client, process controller, and views.

SwiftPM pins Sparkle `2.9.2` through `Package.resolved`; changing the dependency requires updating the release notes, notices, lock evidence, and real upgrade acceptance.

Commands:

```bash
swift build
swift test
```

## Public Validation Scope

This public source tree retains implementation and automated-contract
descriptions, not past local validation outcomes. It intentionally omits
pre-publication build identifiers, process identifiers, test counts,
screenshots, local-folder permissions, and business-file observations.
Neither this Swift reference nor its development scripts constitute public
release evidence. A future Tauri package must establish fresh, version-bound
evidence with its own focused tests and final-RC installation smoke test.

## Swift Release Reference

The procedures below document the existing Swift/Sparkle implementation and
its security boundaries. They do not authorize a macOS publication or
substitute for the Tauri `v0.3` design. A future Tauri macOS package requires
its own focused integration tests and one final-RC install/start/picker/tray/
update smoke test.

The formal arm64 release path is implemented but remains gated by real signing credentials and platform acceptance:

Internal developer-local artifacts must obtain their signing account and
credentials from the private build environment. Prepare the runtime online,
prove the cached runtime/wheelhouse offline, then build without another
`--clean`:

```bash
./script/prepare_release_runtime.sh --clean
./script/prepare_release_runtime.sh --offline
./script/build_release.sh \
  --source-commit <40-character-RC_SHA> \
  --internal-unsigned \
  --offline
./script/verify_macos_release.sh \
  --app <internal-adhoc-app> \
  --dmg <internal-adhoc-dmg> \
  --update-zip <sparkle-update-zip> \
  --sparkle-signature-file <sparkle-signature-sidecar> \
  --trusted-sparkle-public-key <trusted-Ed25519-public-key> \
  --expected-source-commit <40-character-RC_SHA> \
  --expected-core-build-id <64-character-core-build-ID> \
  --expect-internal-adhoc
```

Internal verification requires the staging App, extracted Sparkle App, DMG App, and DMG container all to be ad-hoc signed with no Developer ID Authority or Team ID. It produces a schema 4 receipt with `signature_mode=internal-adhoc`, the configured account, and `verify_macos_release.sh/v4`; provenance always rejects it for a public Feed.

```bash
./script/prepare_release_runtime.sh --clean
./script/build_release.sh --source-commit <40-character-RC_SHA>
./script/verify_macos_release.sh \
  --app <signed-app> \
  --dmg <stapled-dmg> \
  --update-zip <sparkle-update-zip> \
  --sparkle-signature-file <sparkle-signature-sidecar> \
  --trusted-sparkle-public-key <trusted-Ed25519-public-key> \
  --expected-developer-id-identity 'Developer ID Application: <subject> (<TeamID>)' \
  --expected-developer-team-id <TeamID> \
  --expected-source-commit <40-character-RC_SHA> \
  --expected-core-build-id <64-character-core-build-ID> \
  --expect-notarized
```

`prepare_release_runtime.sh` pins the Python 3.14.6 arm64 python-build-standalone archive and SHA-256, installs the macOS hash lock offline, and writes a runtime manifest. macOS deliberately omits watchdog and uses the built-in polling observer. `build_release.sh` requires a clean commit, uses an operator-provided signing account, builds Release/arm64, embeds the Python runtime and shared core, adds package/build/runtime manifests and SBOM, then selects either internal ad-hoc or formal Developer ID/notarized signing. `verify_macos_release.sh` requires exactly one of `--expect-internal-adhoc` and `--expect-notarized`; the formal path continues to reject development markers, wrong architecture/identity, missing manifests, broken imports, unstapled output, local paths, secrets, and SBOM drift. Formal schema 4 receipts use `signature_mode=developer-id-notarized`, and the fixed Tag-bound Feed finalizer invokes the verifier with `--artifact-only --expect-notarized`; receipts remain audit records rather than proof of signing or notarization.

Required external gates are documented in [`docs/release/UPDATE_SYSTEM.md`](../../docs/release/UPDATE_SYSTEM.md): a real Developer ID Application identity, notary profile, trusted update-signing key, clean-machine quarantine launch, protected-folder authorization, and a real update with monitor restoration only after strict handshake has established verified owned running identity and released the startup gate. The package must not include local config, runtime data, real invoice files, generated cost outputs, or a development virtual environment.
