# Changelog

## Unreleased

- 2026-08-17 Tauri exit/update timeout repair: tray Quit now only triggers the
  common application exit path, while system Quit, Cmd-Q, and every other
  `ExitRequested` first perform the structured `keep_monitor` backend shutdown.
  An API failure or timeout explicitly kills and waits for the owned child;
  failure to confirm termination prevents host exit instead of relying on
  process `Drop`. Host updater metadata checks now use a five-second total
  timeout so a stalled Feed cannot permanently own the updater mutex or Host
  RPC connection capacity. Focused verification is recorded in the Tauri
  execution plan; this does not enable update installation.
- 2026-08-17 Tauri P1 transport/container repair: private Python Host RPC
  requests now use an explicit no-proxy loopback transport, so a configured
  `HTTP_PROXY` cannot receive the bearer token. Development state-root
  containment now treats the complete macOS `.app` bundle as protected rather
  than only `Contents/Resources`, rejecting `Contents` sibling state paths as
  well. Focused Host RPC and Rust lifecycle contracts passed; this remains a
  source-level safety repair, not a product-process, updater, installer, or
  platform-release result.
- 2026-08-17 Tauri P1 lifecycle/provenance repair: `update_install` now
  deliberately consumes any candidate and returns unavailable until a complete
  recovery/relaunch coordinator exists, so it cannot download, stop monitor,
  install, or restart halfway through an update. Tray Quit now requests the
  existing structured `keep_monitor` shutdown and waits for the owned backend;
  its direct child kill was the intended bounded timeout/error fallback and is
  now enforced for every application exit by the later repair above. Dormant
  monitor-stop/install response fragments were removed so the Rust host does
  not imply an executable coordinator. Development
  assembly records dirty allowlisted inputs as `<HEAD>+dirty`, and development
  state now requires an explicit existing canonical root that is disjoint from
  the bundle in both directions. Locked Rust formatting, 16 library tests, 6
  lifecycle integration tests, the desktop binary check, version sync, focused
  Python contracts, `compileall`, and diff whitespace checks passed without
  Rust warnings. A redacted candidate scan found only ignored dependency build
  metadata and the documented deterministic ledger-fixture false-positive
  category; tracked/non-ignored source contained no local identity, credential,
  business output, runtime, or release artifact. This is not a product-process, installer, signed-update,
  native-panel, or platform release-smoke result.
- Align the public-history execution record with the prepared sanitized-root
  Tauri development line while retaining the no-Tag/no-Release/no-Pages
  boundary.
- 2026-08-17 Tauri development application L8-S/L9: add the deterministic
  development-only assembler that stages an allowlisted core, schema-3 host
  manifest, and explicit virtual-environment launcher, then binds both raw
  manifest and launcher SHA-256 values into the host build. The macOS arm64
  development `InvoiceHub.app` was built once and smoke-tested once against an
  isolated development state root: the owned backend bound exactly
  `127.0.0.1:8766`, health and background startup became ready, the homepage
  and static assets loaded, `desktop_available=true` with the default desktop
  surface, and orderly shutdown released the port and PID state. The app is a
  local ignored development artifact; it did not touch the real user
  Application Support state. The development profile disables updater
  delegation and rejects release/relative state-root overrides. An initial
  macOS tray initialization failure was traced to a 16-bit RGBA icon; the icon
  is now 8-bit RGBA and an IHDR-focused regression guards that mechanism. This
  is not DMG, NSIS, Developer ID, notarization, Feed, Release, real updater,
  native-panel, browser/tray, or Windows smoke evidence.
- 2026-08-16 Tauri release-input L7: complete the read-only readiness audit.
  The source deliberately disables Tauri bundling and has no deterministic
  generator or stager for the schema-2 desktop host manifest and its
  compile-time SHA-256; existing Windows portable and legacy Swift/macOS
  packagers cannot supply Tauri NSIS or DMG/update-archive inputs. The audit
  also found that the current static manifest schema cannot safely hold
  per-user config/runtime paths. Release assembly remains blocked; L8 is
  recorded before implementation to define the dynamic state-layout and
  manifest-path contract before any generator. No product process, bundle, signing,
  notarization, upload, publication, or Feed was created.
- 2026-08-16 Tauri updater L6-RRRRR: make a contended hosted update check
  return its read-only busy result before `append_event`, so it cannot block on
  an SQLite event write. Add representative contracts for that blocked-event
  path and for releasing the install lock after a private RPC exception. The
  targeted isolated Python contracts passed 45 tests with deprecations as
  errors; this supersedes L6-RRRR's 44-test result for the event-write and
  exception-release scope. No Rust, product process, update, package, signing,
  or platform smoke test was run.
- 2026-08-16 Tauri updater L6-RRRR: correct the hosted-Tauri scope of update
  checks. When the Tauri marker and private Host RPC are both configured, API,
  settings, and background checks use the strict fresh-Feed/candidate
  preflight; only non-Tauri/non-host checks retain the ordinary cache/ETag
  path. Install lock contention now fails immediately without consuming the
  approval or sending a second Host RPC. The targeted isolated Python contracts
  passed 44 tests with deprecations as errors; this supersedes the L6-RRR
  42-test result but is itself superseded by L6-RRRRR for the event-write and
  exception-release scope. No Rust, product process, update, package, signing,
  or platform smoke test was run.
- 2026-08-16 Tauri updater L6-RRR (superseded): keep ordinary update checks outside the
  host lifecycle lock, while a contended Tauri host approval immediately
  returns the non-persistent update busy result without metadata/candidate
  work or clearing an existing approval. The acquired host path still
  serializes strict metadata, candidate, and one-shot install with explicit
  `try/finally` release. This was superseded by L6-RRRR because its 42-test
  result did not establish the stricter hosted-Tauri public-check scope; no
  Rust, product process, update, package, signing, or platform smoke test was
  run.
- 2026-08-16 Tauri updater L6-RR: make the strict host-approval Feed request
  explicitly send `Cache-Control: no-cache` while continuing to omit ETag and
  reject `304`; non-host public update checks retain their existing cache/ETag
  headers. Clarify and lock the separate four-picker and two-updater Host RPC
  command surfaces. The targeted isolated Python contracts passed 40 tests with
  deprecations as errors; no Rust, product process, update, package, signing,
  or platform smoke test was run.
- 2026-08-16 Tauri updater L6-R: require the host-install approval path to
  revalidate a fresh allowlisted Feed `200` body without cache, ETag, or `304`
  reuse, while preserving non-host public check caching. Actively sweep the
  one-shot host candidate from the bounded listener loop after five minutes and
  generation-check removal so an old expiry sweep cannot clear a newer slot.
  Correct current documentation to describe the token handoff only from host to
  its directly spawned Python backend, followed by startup capture and
  descendant-environment scrubbing. The isolated Python selection passed 31
  tests and the Rust 1.85 offline contracts passed 13 library plus 5 lifecycle
  tests; no product process, `8766` bind, update/download, package, signing, or
  platform smoke test was run.
- 2026-08-16 Tauri updater L6: bind the raw desktop bundle manifest to the
  compile-time SHA-256 injected by the future staged-manifest packager, keeping
  source checkouts exit-78 fail-closed. Add host-delegated `update_check` and
  one-shot `update_install` commands with a five-minute candidate bound, an
  allowlisted Feed/version-match approval gate, empty-body HTTP install API,
  and redacted 503 failures. Installation now has the fixed order download plus
  Minisign verification, monitor stop and independent recheck, then
  install/restart. Controlled Rust contracts and an isolated FastAPI TestClient
  contract passed; no product process, real update, bundle, signing, or
  platform smoke was run.
- 2026-08-16 Tauri 2 lifecycle and startup-surface boundary: add fixed-port
  backend ownership, child identity/manifest/OpenAPI-method checks,
  HMAC-SHA256 challenge-response proof, and a four-enum private native-picker
  RPC. After an owned-backend handshake, the host strictly reads the persisted
  `desktop|browser` preference: desktop creates the zero-permission WebView,
  browser uses the host-only pinned opener for the fixed origin, and
  single-instance/tray open reopens that selected surface while desktop close
  hides the window without stopping monitor. A manifest-less checkout exits
  with status 78 before Tauri startup; host credentials are removed from child
  environments, and a bounded liveness watcher revokes RPC authorization. The
  host repeats its ownership proof after the preference read; the picker bridge
  preserves Rust's 120-second dialog with a 125-second Python budget and maps
  its private failures to redacted HTTP 503. Isolated `cargo check`/`cargo test`
  and focused Python static contracts passed. The later L6 isolated TestClient
  endpoint contract is recorded separately above; neither record represents a
  Tauri/FastAPI product service, installer, signing, native panel, Windows BAT,
  or platform smoke test.
- 2026-08-16 Tauri 2 foundation: add the public execution plan, single-source
  version synchronizer, pinned pnpm Tauri dependencies, fixed-localhost host
  scaffold, and non-installing Windows/macOS doctor/bootstrap entry points.
  Diagnostics run from the requested project root, block Rustup/Corepack
  auto-downloads, and fail closed for missing Windows interpreter, MSVC, or
  SDK prerequisites. A checksum-verified isolated Rust 1.85.0 environment
  now pins exact Tauri crates, generates the reviewed MSRV-compatible
  `Cargo.lock`, and passes focused `cargo check`/fixed-origin Rust tests; the
  normal user environment remains unmodified. Lifecycle, Host RPC, updater,
  packaging, and platform smoke tests remain explicitly unimplemented.
- Correct the interface-flow release boundary to record the completed public
  transition while retaining the prohibition on reusing retired private assets.
- Read the Windows CI release-version argument from `version.py` instead of
  the retired `0.2.0-beta.1` literal, keeping the source-identity gate aligned
  with the public release configuration.
- 2026-08-14 public repository transition: publish the audited sanitized root
  in a new public repository, retain the retired original graph only in an
  owner-controlled private archive, and enable public-repository security and
  contribution governance. No retired package, tag, receipt, Release asset, or
  update Feed was reused.
- Prepare a sanitized public root: replace historical business fixtures with
  explicit synthetic data, retire pre-publication release evidence, and add
  the all-ref and hosting verification gate.
- Correct alpha-channel update-feed prerelease validation and synchronize the
  local-candidate publication gate and Windows source-development guidance.

## Public Baseline - 2026-08-14

- The public repository begins from a sanitized source snapshot. Earlier
  private development history, validation narratives, and release artifacts
  are intentionally not part of the public Git graph.
- The next development line is `0.3.0-alpha.1`, which introduces the Tauri 2
  desktop host while retaining the Python, FastAPI, Web, and monitor core.
- No pre-publication binary or tag is published from this repository. Future
  public binaries use a new version and fresh audited release evidence.

## Compatibility Scope

- Invoice extraction, projections, the independent monitor, localhost APIs,
  and the existing Web UI remain the shared product core.
- The first Tauri release targets Windows 10/11 x64 NSIS and macOS 13+ arm64
  DMG/update archives. Other desktop variants remain out of scope.
