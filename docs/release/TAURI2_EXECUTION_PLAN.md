# Tauri 2 Public Execution Plan

## Release boundary

The public repository starts from the audited sanitized root. Retired private
history, tags, packages, receipts, releases, and update endpoints are not
inputs to this plan and must never be uploaded or reused. The first public
development version is `0.3.0-alpha.1`; a public binary, tag, Release, or
Feed requires newly built evidence from this graph.

Tauri 2 is a host for the existing Python/FastAPI/Web/independent-monitor
core. It owns windows, tray behavior, single-instance control, native panels,
printing, backend lifecycle, the internal Host RPC boundary, and the updater.
It must not reimplement invoice extraction, projections, cost analysis,
bookkeeping, or monitoring.

## Current P1 boundary

`update_install` is deliberately unavailable while the host lacks a complete
recovery/relaunch coordinator. It consumes any in-memory candidate and returns
the existing redacted unavailable error; it must not download, stop monitor,
install, or restart. The historical L6 order is a future coordinator
requirement, not a currently executable flow. Tray Quit and the application
menu/Cmd-Q must request `app.exit(0)`, which enters the common Tauri
`ExitRequested` path. A native predefined Quit item or an external macOS
termination request can bypass that event and therefore cannot be claimed as
an orderly-shutdown path. Every `ExitRequested` that the host receives first
requests the existing structured `keep_monitor` backend shutdown and waits for
the owned child. An API error or timeout uses an explicit `kill + wait`;
failure to confirm child exit prevents host exit, and process `Drop` is not
treated as a fallback. Host updater metadata checks
have an explicit 5 秒 total timeout instead of the plugin's unbounded
default. A
development launch must explicitly supply an existing absolute state root that
canonicalizes disjoint from the bundle/core in both containment directions, and
the assembler labels dirty inputs `<HEAD>+dirty`.

### P1-R: handoff repair verification

| Field | Record |
| --- | --- |
| Hypothesis | The fail-closed install boundary, structured tray shutdown, dirty development provenance, and disjoint development state root compile and remain consistent with their focused Python/API/documentation contracts. |
| Decision changed by result | A pass permits one DCO commit and a single clean-commit development app rebuild; a failure blocks publication and confines repair to the failing P1 category. |
| Minimal sample | Locked `cargo fmt --check`, Rust library/lifecycle tests and desktop binary check; version-source synchronization; focused Python tests for the Tauri foundation, development assembler, Host RPC, lifecycle/API, update service, paths, settings migration, and current documentation; then `git diff --check`. |
| Stop condition | Stop at the first formatting, compiler, lifecycle, API, provenance, state-root, or documentation failure. Do not run the full regression, start a real updater, stop a real monitor, create an installer, sign, publish, or change GitHub settings. |
| Result (2026-08-17) | Passed. The locked Rust 1.85 environment completed `cargo fmt --check`, 16 library tests, 6 lifecycle integration tests, and the desktop binary `cargo check` without warnings. `tauri_version_sync.py --check` confirmed `0.3.0-alpha.1` and `com.invoicehub.desktop`; the focused Python foundation/development-app/Host-RPC/lifecycle/API/update/path/settings/documentation selection completed successfully with deprecations treated as errors. Python `compileall` and `git diff --check` also passed. The cleanup removed dormant monitor-stop/install-success fragments rather than suppressing dead-code warnings. This permits one DCO commit and one clean-commit development app rebuild only; it is not updater execution, an installer, signing, publication, or platform release evidence. |

### P1-E: unified exit and updater timeout repair

| Field | Record |
| --- | --- |
| Hypothesis | The then-assumed routing of tray, native system-menu, Cmd-Q, and other Tauri exit requests through one structured backend shutdown would prevent an orphaned fixed-port child; independently, setting the locked updater builder to a 5-second total timeout would prevent a stalled Feed request from permanently owning Host RPC capacity. The later product sample below disproved the native-menu part of this hypothesis. |
| Decision changed by result | A pass removes the two final P1 blockers and permits the pending lifecycle delta to be committed and rebuilt once from the clean commit. A failure blocks the Draft PR and confines repair to the exit or updater-timeout mechanism that failed. |
| Minimal sample | Locked `cargo fmt --check`; Rust library/lifecycle tests and desktop binary check; focused Python Tauri lifecycle, Host RPC, development documentation, API/update/path/settings/development-app tests; then `compileall` and `git diff --check`. The later clean-commit L9 rerun remains the single product-process sample. |
| Stop condition | Stop at the first format, compile, lifecycle, timeout, API, documentation, or whitespace failure. Do not invoke a real updater, stop a real monitor for installation, build an installer, sign, publish, or broaden the repair into the shared business core. |
| Result (2026-08-17) | Passed only for the source-level fallback and updater-timeout mechanisms. Locked Rust 1.85 formatting, 16 library tests, 6 lifecycle integration tests, and the offline desktop binary check completed without compiler warnings; the socket-authorization test was rerun outside the restricted sandbox only because the sandbox denied its temporary loopback bind. The 153 unique focused Python Tauri/foundation/development-app/Host-RPC/lifecycle/API/update/path/settings/documentation contracts all passed after one rustfmt-sensitive static assertion was corrected and its lifecycle category rerun. `compileall` and `git diff --check` passed. A later clean-commit product smoke showed that an external macOS application-quit request can bypass `RunEvent::ExitRequested`; therefore the native-menu portion of the hypothesis failed and no longer permits a Draft PR by itself. The updater timeout and explicit kill/wait fallback remain valid; P1-Q below owns the custom-menu/Cmd-Q repair. |

### P1-Q: macOS application-menu quit routing repair

| Field | Record |
| --- | --- |
| Hypothesis | A custom macOS application-menu Quit item with `CmdOrCtrl+Q`, plus tray Quit, can both call the same `app.exit(0)` request and therefore reach the existing `RunEvent::ExitRequested` structured-shutdown handler without using the native predefined Quit selector. |
| Decision changed by result | A source-contract/compile pass permits one new DCO fix-forward commit and one development `.app` rebuild from that clean commit. The genuine menu/Cmd-Q runtime pass then permits a second evidence-only DCO commit and opening a Draft PR, without rewriting the three existing commits. Any compile, routing, shutdown-POST, stopped-state, child-exit, or port-release failure keeps the PR blocked and confines repair to the application-menu/exit path. |
| Minimal sample | One static lifecycle contract that locks the custom application-menu ID, `CmdOrCtrl+Q`, shared exit-request helper, absence of `PredefinedMenuItem::quit`, and the existing `ExitRequested` handler; locked Rust formatting/tests/binary check; then one clean-commit macOS development `.app` launch against an empty isolated state root and one genuine application-menu or Cmd-Q exit, checking the shutdown POST, `server_state.status=stopped`, child exit, port release, and PID cleanup. |
| Stop condition | Stop at the first source, compile, menu dispatch, structured shutdown, state, child, port, or PID failure. Do not treat `tell application ... to quit`, Force Quit, SIGKILL, logout, or power loss as this mechanism; do not run updater/install, native picker, DMG/NSIS, signing, notarization, Release, Feed, or shared-core regression. |
| Result | Passed on 2026-08-17. The custom macOS menu/shared-exit implementation passed 10 Python lifecycle contracts, locked Rust formatting, 16 library tests, 6 lifecycle integration tests, and the offline desktop binary check without warnings. The 12 documentation contracts passed after their one demonstrated omission—`tests/test_tauri_dev_app.py` absent from the architecture file map—was added and that category alone was rerun; version synchronization and `git diff --check` passed. Commit `399b20c` retained DCO, and the locked offline toolchains rebuilt one arm64 development `.app`; its executable SHA-256 is `bd129557b5df06bbec4dbbd86d4dba05faf7eaa68289426455086e2ef1f5cb70`, its embedded source commit/build ID matched, and it remained ad-hoc/development-only. Against one empty isolated state root, health/background reached ready, the fixed port and desktop preference matched, and a genuine foreground Cmd-Q—not AppleScript quit—produced `POST /api/v1/server/shutdown` 200, `server_state.status=stopped`, `monitor_running=false`, host/backend exit, port release, and server PID cleanup. Open SSE connections prevented uvicorn from self-exiting within the bounded wait, so the host exercised the intended explicit `kill + wait` fallback after stopped state was written. No real Application Support, updater/install, native picker, DMG/NSIS, signature/notarization, Release, Feed, or shared-core regression was touched. This closes P1-Q and permits the development branch to be pushed and opened as a Draft PR; external AppleScript quit, Force Quit, SIGKILL, logout, and power loss remain outside the contract. |

### P1-S: public branch candidate content gate

| Field | Record |
| --- | --- |
| Hypothesis | The two existing foundation commits and the pending Tauri lifecycle/development-app delta contain no credential, real business data, user-machine identity, tracked runtime, or release artifact. |
| Decision changed by result | A pass permits explicit-file staging, a DCO commit, and pushing only `codex/tauri2-unified-desktop`; a real finding blocks the commit and confines repair to the affected candidate file. |
| Minimal sample | One redacted gitleaks directory scan of the candidate worktree plus one tracked-delta search from public `main` for local absolute paths, runtime/artifact names, invoice/business-data markers, private-key material, and unexpected binary files. The already completed public-`main` all-ref audit is reused rather than refreshed. |
| Stop condition | Stop at the first real credential, business-data, local-identity, runtime, or artifact finding. Do not clean the retired private graph, inspect ignored invoice outputs as release inputs, push, create a PR, alter repository settings, or publish. |
| Result (2026-08-17) | Passed after one ambiguity-only classification rerun. The redacted directory scan reported four findings: three were generated, ignored `src-tauri/target` metadata from the locked `muda` dependency, and one was the already documented deterministic test-only ledger identifier false-positive category. The tracked/non-ignored candidate search found no user path, visualization/worktree path, private-key marker, credential pattern, certificate/key file, tracked runtime, invoice output, or release artifact. After P1-E expanded the source delta, a final temporary-index scan of exactly 50 modified/untracked non-ignored candidate files completed with no gitleaks finding, no local/worktree path, and no runtime or business-output path; its only non-text file is the expected 8-bit RGBA application icon. Ignored local CSV/XLSX outputs remain outside Git and release inputs. |

### P1-W: Windows executable-path contract fixture repair

| Field | Record |
| --- | --- |
| Hypothesis | The hosted Windows failure is confined to a POSIX-only test-fixture assumption: changing a temporary file's mode does not make `os.access(path, os.X_OK)` reject it on Windows. Replacing that host-filesystem assumption with a deterministic denial of the executable-access probe will exercise the existing fail-closed production branch on every platform without changing development-app behavior. |
| Decision changed by result | A focused local pass permits one DCO fix-forward commit and a new branch push; the new hosted Windows pass then permits the three stable checks to become `main` ruleset requirements. Any failure keeps the ruleset unchanged and confines repair to `tests/test_tauri_dev_app.py` unless new evidence identifies a production defect. |
| Minimal sample | One representative failing hosted Windows job log; one focused `tests/test_tauri_dev_app.py` run on the existing macOS environment; the documentation contract category and `git diff --check`; then the automatically triggered DCO, Windows, and macOS checks for the new commit. |
| Stop condition | Stop at the first contradictory production-path finding, focused test failure, documentation failure, or new hosted failure mechanism. Do not rerun the old workflow, change `validate_venv_python`, expand into shared-core or release tests, rebuild the development `.app`, create an installer, merge, tag, release, or publish a Feed. |
| Result | The source review and local portion passed on 2026-08-17. The development builder is macOS-arm64-only and its existing executable-access validation remains unchanged; only the POSIX-specific fixture was replaced. The focused development-app file passed 7 tests, the directly affected documentation selection passed 13 tests, and `git diff --check` passed. The two completed Windows runs for the previous head failed at the same single test, while DCO and macOS passed; only one Windows log is used as the representative sample. The new-head hosted DCO, Windows, and macOS result remains pending at this commit. |

## Operating rules

| Change | Required verification | Rebuild |
| --- | --- | --- |
| Governance, repository visibility, documentation | Links, license, one scoped secret scan | No |
| Feed or Release metadata | Schema, signatures, one real URL | No |
| Tauri host or platform integration | Focused Rust/frontend checks and one smoke check per platform | Only the new `v0.3` build |
| Shared Python/Web core | Affected tests and one full regression before an RC | Only the new RC |

- Existing evidence for an identical source commit, package hash, lock, and
  environment is reused. It is not rerun merely to refresh numbers or fill a
  table.
- A test or experiment is run only when it can change a decision. One failure
  mechanism uses one representative sample unless results conflict, the
  change surface expands, or a different mechanism is involved.
- A repair is limited to the module that causes the problem. It does not
  trigger a shared-core refactor or replace an existing packager.
- Documentation, licenses, repository settings, and Feed metadata do not
  trigger an application rebuild. A platform is rebuilt only when packaged
  input, package integrity, signing, or embedded identity changes.
- Each RC receives at most one full regression after focused checks. A failed
  category is rerun only after its own repair.

## Delivery sequence

1. [x] Establish and verify the sanitized public baseline; retain old
   artifacts only in the private archive.
2. [x] Create the `codex/tauri2-unified-desktop` development branch from the
   public `main`.
3. [x] Establish the Tauri foundation: one version source, toolchain locks,
   a minimal `src-tauri/` project, and non-installing Windows/macOS
   `doctor/bootstrap` commands. Exact direct Cargo dependencies and the
   Rust-1.85-compatible `Cargo.lock` have been reviewed and compiled in the
   controlled macOS environment.
4. [x] Implement the code-level fixed `127.0.0.1:8766` backend ownership,
   strict handshake, single-instance handling, and internal Host RPC boundary.
   A bare checkout remains fail-closed until a compile-bound manifest exists.
5. [x] Implement code-level `startup_surface`, browser/tray behavior, and
   update-install delegation, then build one schema-3 macOS arm64 development
   `.app` and run one isolated L9 smoke. The five final decision scenarios
   still require real platform validation and are not claimed by that smoke.
6. [x] Close P1-Q with one clean-commit custom application-menu/Cmd-Q smoke.
7. [x] Push `codex/tauri2-unified-desktop`, open Draft PR #7, and let DCO,
   macOS, and Windows CI identify the exact stable check names. DCO and macOS
   passed on the first PR head; Windows exposed the P1-W fixture defect above.
8. [ ] Only after those checks pass, add them to the `main` ruleset and enable
   strict required-status policy; do not merge without explicit owner approval.
9. [ ] After the foundation PR is accepted, implement the missing
   recovery/relaunch coordinator and deterministic Tauri NSIS/DMG/update-
   archive assembly/verification as separate bounded development work. The
   local L11-A internal-alpha App/DMG assembly is a non-public prerequisite
   experiment; it does not close this formal release item or enable
   `update_install` before every failure path restores prior state.
10. [ ] Exercise the five decision scenarios on development/alpha artifacts:
   both startup surfaces; single instance and wrong port; Host RPC
   authorization; valid/tampered update; and monitor stop before install.
11. [ ] Only after the alpha/beta gates pass, cut a clean RC, run its one full
    regression, build/sign/notarize both target-platform artifacts, and run
    each platform's one final RC smoke.
12. [ ] Create immutable Tag/Release assets and switch the GitHub Pages Feed
    last, after provenance, redownload, source archive, SBOM and signature
    checks all close.

## Foundation experiments

### F1: version derivation

| Field | Record |
| --- | --- |
| Hypothesis | `src/invoice_hub/version.py` can remain the only product-version source while Cargo, Tauri, and npm configuration are deterministically synchronized from it. |
| Decision changed by result | A pass permits the foundation configuration to be committed; a mismatch blocks lifecycle, packaging, and release work until the synchronizer is corrected. |
| Minimal sample | The current `0.3.0-alpha.1` source value and one intentionally drifted derived configuration in a temporary copy. |
| Stop condition | Stop at the first source/derived-version mismatch. Do not test alternate product versions unless this mechanism is repaired. |

### F2: non-installing environment gate

| Field | Record |
| --- | --- |
| Hypothesis | `doctor` can accurately report the current platform, Node, pnpm, Rust, Cargo, lockfile, and platform-SDK readiness without installing Rust, certificates, Xcode, or Visual Studio. |
| Decision changed by result | A ready result permits local Rust validation; a missing or mismatched prerequisite keeps Rust compilation and lock generation blocked and records the exact missing prerequisite. |
| Minimal sample | The current macOS development machine and one `--require-ready` invocation. |
| Stop condition | Stop after the first missing prerequisite category. Do not retry by auto-installing a system tool. |

### F3: pnpm lock resolution

| Field | Record |
| --- | --- |
| Hypothesis | The declared Tauri JavaScript packages resolve to an immutable pnpm lock compatible with the pinned pnpm version. |
| Decision changed by result | A pass permits the checked-in pnpm lock; a resolution failure blocks JavaScript dependency setup and requires a version correction before any host work. |
| Minimal sample | One `pnpm install --lockfile-only --ignore-scripts` resolution for the root package. |
| Stop condition | Stop after the first registry, integrity, or version-resolution failure; do not substitute an unverified package version. |

### F4: Cargo dependency selection

| Field | Record |
| --- | --- |
| Hypothesis | The Rust `tauri` and `tauri-build` crates can be pinned to published Tauri 2 versions before a Cargo lock is generated. |
| Decision changed by result | A published exact version permits the Cargo manifest; an unavailable version blocks the manifest rather than recording an invented dependency. |
| Minimal sample | One crates.io metadata lookup for each direct Tauri crate. |
| Stop condition | Stop after the first unavailable direct crate, registry-access failure, or incompatible major version. Cargo lock generation remains blocked until the pinned Rust toolchain is present. |

### F5: local Cargo cache fallback

| Field | Record |
| --- | --- |
| Hypothesis | A previously populated local Cargo registry can provide published metadata when the public registry is unavailable. |
| Decision changed by result | A matching cached crate permits an exact manifest declaration; no cached metadata leaves Rust dependency selection blocked without guessing versions. |
| Minimal sample | The local Cargo registry index and cache directories for the two direct Tauri crates. |
| Stop condition | Stop after one cache lookup. A missing cache is recorded as an environment prerequisite, not retried through another network mirror. |

### F6: isolated official Rust toolchain

| Field | Record |
| --- | --- |
| Hypothesis | An official Rust `1.85.0` toolchain for the current macOS arm64 host can be installed under an explicit isolated temporary directory, after verifying the official Rustup installer checksum, without reading or modifying the user's `~/.rustup` or `~/.cargo` state. |
| Decision changed by result | A verified exact toolchain permits the F4 direct-crate lookup and Cargo lock generation in that isolated environment; an unavailable installer, checksum mismatch, or version mismatch keeps Cargo work blocked and requires no substitute mirror or system installation. |
| Minimal sample | One official `aarch64-apple-darwin` Rustup installer, its matching official `.sha256` file, one isolated `rustup-init` execution, and `rustc --version` plus `cargo --version`. |
| Stop condition | Stop at the first download, checksum, installer, or exact-version failure. Do not use a mirror, Homebrew, or the user's Rust directories. |

### F7: MSRV-aware Cargo resolution

| Field | Record |
| --- | --- |
| Hypothesis | Cargo `1.85.0` can resolve the exact published direct Tauri crates using its MSRV-aware fallback resolver, producing a graph whose declared Rust requirements do not exceed the package's `rust-version = "1.85"`. |
| Decision changed by result | A compatible graph permits keeping the direct crate selection and reviewing its lock; an unsupported resolver option or another dependency above Rust `1.85` blocks the lock and requires reconsidering the direct Tauri version, not hand-pinning arbitrary transitive packages or raising the toolchain. |
| Minimal sample | The first generated lock's representative `darling 0.23.0` Rust `1.88.0` warning, followed by one isolated `cargo generate-lockfile` run with `CARGO_RESOLVER_INCOMPATIBLE_RUST_VERSIONS=fallback`. |
| Stop condition | Stop at the first unsupported resolver setting, registry error, or selected package whose declared MSRV exceeds `1.85`. Do not run a build, hand-edit `Cargo.lock`, or change the Rust toolchain before the result is reviewed. |

### F8: locked foundation compilation

| Field | Record |
| --- | --- |
| Hypothesis | The non-runnable `src-tauri` foundation compiles with the reviewed lock and the isolated Rust `1.85.0` toolchain while preserving its explicit exit-78 guard. |
| Decision changed by result | A pass completes the dependency/lock foundation and permits later lifecycle implementation; a compiler, SDK, build-script, or lock failure keeps host implementation blocked and limits any repair to its demonstrated prerequisite. |
| Minimal sample | One `cargo check --locked --manifest-path src-tauri/Cargo.toml` using the isolated Cargo home and a temporary target directory. |
| Stop condition | Stop at the first failing compiler or build-script category. Do not run `tauri dev`, launch the binary, bind localhost, or start lifecycle/RPC/updater work. |

### F9: fixed-origin Rust unit contract

| Field | Record |
| --- | --- |
| Hypothesis | The compiled foundation retains the fixed `127.0.0.1:8766` origin contract in its smallest Rust unit test. |
| Decision changed by result | A pass confirms the lock/toolchain repair did not alter the host boundary; a failure blocks later lifecycle work until the fixed-origin module alone is repaired. |
| Minimal sample | One `cargo test --locked --offline --manifest-path src-tauri/Cargo.toml` in the same isolated toolchain and temporary target directory. |
| Stop condition | Stop at the first failing Rust test. Do not add browser, backend, updater, or platform smoke tests at this foundation stage. |

### F10: foundation source and documentation contract

| Field | Record |
| --- | --- |
| Hypothesis | The exact crate pins, MSRV resolver, reviewed lock, compile-time icon, non-running guard, file map, status documents, and execution record remain mutually consistent. |
| Decision changed by result | A pass permits the focused foundation change to enter review; a failure confines repair to the reported source or documentation contract before any later host work. |
| Minimal sample | One `pytest` invocation limited to `tests/test_tauri_foundation.py` and `tests/test_development_documentation.py`. |
| Stop condition | Stop at the first failing contract category. Do not run the complete Python regression merely to refresh coverage. |

## Foundation experiment results (2026-08-15)

| Experiment | Result | Decision and boundary retained |
| --- | --- | --- |
| F1 | Passed. `python3 scripts/dev/tauri_version_sync.py --check` matched the current `0.3.0-alpha.1` source identity; the focused test also repaired one derived-version drift in an isolated temporary copy. | The foundation may derive Cargo, Tauri JSON, and npm identity only from `version.py`; drift is a hard stop. |
| F2 | Blocked as designed. The current macOS `doctor --require-ready` found Node, pnpm, Xcode command-line tools, fixed origin, and pnpm lock, but no `rustc`, `cargo`, or `src-tauri/Cargo.lock`. | Do not compile Rust or begin host lifecycle work. Do not install Rust, certificates, Xcode, or Visual Studio from the bootstrap command. |
| F3 | Passed. One `pnpm install --lockfile-only --ignore-scripts` resolution produced the checked-in lock for `@tauri-apps/api@2.11.1` and `@tauri-apps/cli@2.11.4`. | The JavaScript lock is usable; it does not prove or replace a Cargo lock. |
| F4 | Blocked. One direct crates.io metadata lookup returned HTTP 403 before a published exact direct-crate version could be established. | Keep the scaffold's `tauri = "2"` and `tauri-build = "2"` declarations explicitly non-reproducible; do not invent an exact crate version or generate `Cargo.lock`. |
| F5 | Blocked. One local Cargo registry/index and cache lookup found no usable Tauri metadata. | Do not retry through an unapproved mirror. A controlled Rust/Cargo source is required before selecting exact crates or generating the lock. |

## Foundation continuation results (2026-08-16)

| Experiment | Result | Decision and boundary retained |
| --- | --- | --- |
| F6 | Passed. The official macOS arm64 Rustup installer checksum was verified before an isolated Rust `1.85.0`/Cargo `1.85.0` installation. | The user's Rust directories and shell PATH remain unchanged; this command-scoped toolchain is the only source used for the following Cargo work. |
| F4 | Passed. Official crates.io metadata established unyanked `tauri 2.11.5` and `tauri-build 2.6.3`, each declaring Rust `1.77.2` MSRV. | `Cargo.toml` pins those exact direct versions; no guessed crate versions remain. |
| F7 | Passed. Cargo's initial latest resolution selected `darling 0.23.0` requiring Rust `1.88.0`; repository-level MSRV fallback instead produced the reviewed Rust-1.85 graph (`darling 0.21.3`, `time 0.3.45`, and the exact direct crates). | `.cargo/config.toml` must retain the fallback resolver; do not hand-edit transitive packages or raise the toolchain merely to refresh a lock. |
| F8 | Passed. `cargo check --locked --offline` completed after two scoped foundation repairs: add the compile-time PNG required by Tauri's context macro and explicitly type the non-running context as `tauri::Context<tauri::Wry>`. | The exit-78 guard remains; no window, backend, localhost listener, lifecycle, RPC, updater, or package was launched. |
| F9 | Passed. The isolated `cargo test --locked --offline` completed the fixed-origin Rust unit test and doctest pass. | The Rust foundation retains `127.0.0.1:8766`; this is not a platform smoke test. |
| F2 recheck | Passed only with the checksum-verified toolchain injected into this command's PATH: version sync, Node, pnpm, Rust, Cargo, both locks, fixed origin, Xcode and macOS arm64 all reported ready. | Normal `doctor/bootstrap` remains non-installing and still fails closed on machines without the prerequisites. |
| F10 | Passed. The focused Tauri foundation and documentation contract suite completed with 26 tests. | The reviewed foundation can enter code review; no full Python regression is implied or required at this stage. |

The foundation has run controlled Rust lock resolution, compilation, and its
small fixed-origin test. It has not run backend lifecycle, strict handshake,
single-instance, Host RPC, preferences/API changes, updater, packaging, or
platform smoke tests. Those are later delivery steps, not evidence implied by
this table.

## Lifecycle and Host RPC experiments

### L1: official lifecycle and dialog dependency selection

| Field | Record |
| --- | --- |
| Hypothesis | Exact published Tauri 2-compatible pins for `tauri-plugin-single-instance`, `tauri-plugin-dialog`, `getrandom`, and `serde_json` can resolve with the existing exact `tauri 2.11.5`, Rust `1.85.0`, and MSRV fallback lock policy. `getrandom` supplies the Host RPC's 256-bit CSPRNG token; `serde_json` parses only manifest, health, OpenAPI, and fixed enum RPC payloads. |
| Decision changed by result | A compatible, reviewed isolated resolution permits adding only these direct crates and updating `Cargo.lock`; an unavailable, incompatible, or higher-MS RV graph blocks lifecycle implementation instead of substituting a non-official single-instance/dialog mechanism, weaker random source, or hand-edited lock. |
| Minimal sample | One temporary copy of `src-tauri` resolved with the existing checksum-verified isolated Rust/Cargo `1.85.0` environment, a temporary Cargo home/target directory, and the four exact direct declarations. |
| Stop condition | Stop at the first registry, pin, MSRV, lock, or plugin API incompatibility. Do not run `tauri dev`, launch a binary, bind the product port, modify user Rust directories, or use an alternate registry/toolchain. |

### L2: lifecycle and Host RPC focused contracts

| Field | Record |
| --- | --- |
| Hypothesis | The host can reject an occupied fixed port, PID/identity mismatch, missing bundle manifest, invalid Host RPC token/origin/command, and still allow one exact token/origin/enum request without exposing the token to a Tauri command, event, WebView, log, error, or Python API response. |
| Decision changed by result | A pass permits the fixed-port ownership and internal picker bridge code to enter review; any rejection-path failure blocks the corresponding boundary and must be repaired locally before other host features are attempted. |
| Minimal sample | One Rust lifecycle integration test with one representative per failure class plus one allowed RPC dispatch, and one Python client test covering absent-channel Tk fallback, fixed request construction, unsafe endpoint rejection, and token-redacted errors. |
| Stop condition | Stop at the first failed category. Do not add tray, browser `startup_surface`, updater, installer, arbitrary path/URL/shell forwarding, or real backend/Tauri smoke tests. |

### L2-R1: ownership-challenge dependency selection

| Field | Record |
| --- | --- |
| Hypothesis | Exact `hmac` and `sha2` crates can be added to the reviewed Rust 1.85/MSRV-fallback graph so the host verifies `HMAC-SHA256(secret, fresh_challenge)` locally instead of disclosing a bearer proof to a listener on the product port. |
| Decision changed by result | A compatible lock permits the narrow challenge-response repair; an unavailable, incompatible, or higher-MSRV graph blocks the repair rather than accepting a bespoke hash construction or a bearer-token workaround. |
| Minimal sample | One isolated temporary manifest resolution with exact `hmac` and `sha2` declarations using the authorized official Rust 1.85.0 environment and the existing fallback resolver. |
| Stop condition | Stop at the first registry, pin, MSRV, or lock failure. Do not run a host, FastAPI, `tauri dev`, or bind `127.0.0.1:8766`; do not alter the user's Rust directories or use another registry. |

### L2-R: startup-order and ownership-proof repair

| Field | Record |
| --- | --- |
| Hypothesis | With no config-created WebView, a 256-bit secret supplied only to the spawned backend, a fresh host challenge, and a constant-time local verification of the backend's `HMAC-SHA256(secret, challenge)` response, an unknown listener cannot be treated as owned or receive the WebView even if it races the preliminary port check. A manifest-less checkout exits status 78 before Tauri startup, and authorization is armed before its bounded liveness watcher so an already-exited child cannot leave RPC authorized. The challenge never contains the secret; an explicit empty-permission Tauri capability prevents the dialog plugin from creating a WebView IPC path. |
| Decision changed by result | A pass retains the lifecycle implementation for review; a failure blocks step 4 and confines repair to startup ordering, challenge-response handling, argument binding, or capability configuration. |
| Minimal sample | One Rust unit sample for fixed argument rejection/append, fresh challenge generation, valid/tampered HMAC verification, and OpenAPI methods; one isolated `cargo check --locked --offline --bin invoicehub-desktop` of the checkout guard; one static Tauri configuration/order/capability contract; and one FastAPI internal challenge-response plus exact-origin contract. |
| Stop condition | Stop at the first compiler, contract, or endpoint failure. Do not start a real Tauri/FastAPI process, bind the product port deliberately, add OS-specific socket-owner code, or advance to tray/browser/updater work. |

### L3: locked focused verification

| Field | Record |
| --- | --- |
| Hypothesis | The focused Rust and Python lifecycle contracts compile and pass against the reviewed lock without refreshing unrelated dependency or full-regression evidence. |
| Decision changed by result | A pass records only the implemented ownership/handshake/RPC boundary; a failure leaves platform smoke, packaging, updater, and startup-surface work explicitly unverified. |
| Minimal sample | One isolated `cargo test --locked --offline` limited to the lifecycle library/integration contract, plus targeted `pytest` for Tauri foundation, Host RPC, API picker, and documentation contracts. |
| Stop condition | Stop after the first compiler, test, or documentation-contract failure in a category; rerun only the repaired category and clean temporary Cargo targets/caches before handoff. |

## Lifecycle and Host RPC results (2026-08-16)

| Experiment | Result | Decision and boundary retained |
| --- | --- | --- |
| L1 | Passed in the existing official isolated Rust 1.85 environment. Exact `tauri-plugin-single-instance 2.4.3`, `tauri-plugin-dialog 2.7.2`, `getrandom 0.3.4`, and `serde_json 1.0.151` remain locked. | Lifecycle work may use only the reviewed direct crates and the MSRV fallback lock. |
| L2-R1 | Passed. One temporary copy resolved `hmac 0.12.1` and `sha2 0.10.9` through crates.io under the authorized isolated toolchain; the final source lock was generated offline after the exact sources were fetched into that isolated cache. | HMAC-SHA256 is the sole ownership-proof construction. No bearer proof is sent to a candidate listener and no handwritten hash construction is used. |
| L2-R | Passed for source-level boundaries. The host generates a fresh 256-bit challenge, verifies the backend HMAC locally, requires PID/manifest/identity/OpenAPI methods before WebView creation, and requires the exact picker origin in host mode. A manifest-less checkout now returns status `78`; ownership is armed before the bounded liveness watcher starts, and the watcher only revokes it after child exit. Host credentials are cleared before child processes. | Unknown port occupants, response replay, wrong method/origin/token/command, and exited children remain fail-closed. No real backend or Tauri process was launched. |
| L3 | The isolated `cargo check --locked --offline --bin invoicehub-desktop` compiled the checkout guard, and the focused Rust/Python source contracts passed. At this L3 point no FastAPI runtime evidence was collected because the current system Python lacked FastAPI and no dependency was installed. | Step 4 source implementation can enter review. L6 later superseded the API-runtime status with an isolated TestClient result; native dialogs, real updater lifecycle, packaging, signing, and platform smoke remain pending. |

## Startup surface experiment

### L4: startup-surface dependency and source contract

| Field | Record |
| --- | --- |
| Hypothesis | The existing Tauri 2.11.5 runtime can retain a tray icon in both surface modes, while one exact published opener plugin can open the fixed localhost origin through the system browser without giving WebView code a shell, URL, or IPC capability. After the strict owned-backend handshake, the host can read the existing preferences endpoint and select `desktop` or `browser`; a backend child marked by the host defaults a missing preference to `desktop`, while a valid imported explicit preference remains unchanged. A non-Tauri Windows portable process remains browser-only. |
| Decision changed by result | A compatible official plugin/API and passing focused contract permit the narrow preference, host-surface, tray, and browser-dispatch implementation. A missing or incompatible API, dependency, or contract blocks this slice and confines any repair to startup-surface selection or the chosen host integration; it does not authorize an alternate browser launcher, a WebView bridge, updater work, or a platform smoke claim. |
| Minimal sample | One official isolated Rust 1.85 dependency lookup/resolution for the exact opener plugin, source inspection of the locked Tauri tray API, one pure Rust surface-policy contract, one Python preference/API contract, and one static source/documentation contract. |
| Stop condition | Stop at the first dependency, MSRV, compiler, or focused-contract failure in a category. Do not launch Tauri/FastAPI, deliberately bind `127.0.0.1:8766`, open a real browser, show a native tray/menu/window, add updater/install code, create a bundle manifest, package, sign, or claim a platform smoke test. |

## Startup surface results (2026-08-16)

| Experiment | Result | Decision and boundary retained |
| --- | --- | --- |
| L4 initial transport | Blocked at the first JSON metadata lookup. The official `crates.io` metadata request for `tauri-plugin-opener` returned HTTP 403 both inside the sandbox and in one authorized non-sandbox retry; the existing isolated Cargo source cache had no opener-plugin source. | Do not add an unverified dependency, hand-written platform browser launcher, WebView capability, or tray/browser source implementation on the basis of the failed JSON API transport. The sparse-index follow-up below was required before changing this decision. |

### L4-R: Cargo sparse-index resolution

| Field | Record |
| --- | --- |
| Hypothesis | The failed crates.io JSON API is a different network mechanism from Cargo's actual sparse-index resolution. One isolated temporary manifest may therefore resolve the official `tauri-plugin-opener = "2"` family through the existing crates.io registry endpoint, revealing a single exact published plugin version and its Rust requirements without changing the project lock or using another registry. |
| Decision changed by result | A compatible Cargo resolution permits review of the selected exact plugin and a separately scoped project-lock update. A sparse-index, download, lock, or MSRV failure confirms the source slice remains blocked; the JSON API failure alone must not be treated as proof of Cargo resolution behavior. |
| Minimal sample | One temporary copy of `src-tauri/Cargo.toml` with the one tentative plugin declaration, a fresh temporary target directory, the already isolated Rust 1.85.0/Cargo homes, and one `cargo generate-lockfile` invocation against the official default registry. |
| Stop condition | Stop at the first Cargo registry, crate-download, lock, or MSRV failure. Do not retry through another registry or mirror; do not modify the project dependency files, launch a host, or substitute a manual browser launcher. |

| Experiment | Result | Decision and boundary retained |
| --- | --- | --- |
| L4-R | Passed. The same isolated Rust 1.85.0 Cargo used its official crates.io sparse-index path to resolve a temporary `tauri-plugin-opener = "2"` declaration. It selected unyanked `tauri-plugin-opener 2.5.4` from `registry+https://github.com/rust-lang/crates.io-index` and generated an MSRV-fallback lock without touching the project lock or a user Cargo directory. | The JSON API 403 is recorded as a distinct failed transport, not proof that Cargo cannot resolve an official crate. `2.5.4` is the only candidate for a source/API inspection before any project dependency change. |

### L4-S: exact opener API and compile inspection

| Field | Record |
| --- | --- |
| Hypothesis | The exact resolved `tauri-plugin-opener 2.5.4` downloads from the official Cargo crate source, compiles with the reviewed Rust 1.85 graph, and exposes a host-only opener API that accepts only the already fixed backend origin. The plugin can remain unavailable to WebView content through the existing empty capability configuration. |
| Decision changed by result | A successful source inspection and isolated compile permits pinning only `=2.5.4` in the project and using its documented host API in the startup-surface implementation. A download, compile, API, or capability-boundary failure blocks the slice without a fallback launcher. |
| Minimal sample | One `cargo check --locked --lib` of the temporary resolved manifest in a fresh temporary target directory, followed by source inspection of the downloaded exact plugin API and the existing empty Tauri capability. |
| Stop condition | Stop at the first crate-download, compiler, exposed-API, or capability-boundary failure. Do not modify project dependencies, open a browser, create a tray/window, bind a backend port, or add updater/install behavior. |

| Experiment | Result | Decision and boundary retained |
| --- | --- | --- |
| L4-S | Passed. A temporary locked `cargo check --lib` downloaded and compiled `tauri-plugin-opener 2.5.4` with the isolated Rust 1.85.0 graph. Its documented host API is `app.opener().open_url(fixed_url, None::<&str>)`; `Builder::open_js_links_on_click(false)` disables the plugin's default WebView JavaScript injection, and the existing `no-webview-ipc` capability remains empty. | The project may pin only `=2.5.4` and use the host-only API for the fixed backend origin. No opener permission is granted to the WebView, and no arbitrary URL/path forwarding is permitted. |

### L4-I: startup-surface implementation and focused verification

| Field | Record |
| --- | --- |
| Hypothesis | With the reviewed opener API and tray feature, the host can defer all surface creation until the owned-backend handshake succeeds, preserve a valid imported `desktop|browser` preference, and keep the independent monitor untouched when a desktop window hides or a browser surface is reopened. |
| Decision changed by result | Passing compilation and source contracts permits this narrow code-level lifecycle boundary. A compiler or contract failure would have confined repair to the selected host integration and would not have authorized a fallback launcher, WebView bridge, updater, or platform smoke work. |
| Minimal sample | The isolated `cargo check --locked --offline --bin invoicehub-desktop`, isolated `cargo test --locked --offline`, and Python static/Host RPC lifecycle contracts. |
| Stop condition | Stop at the first compiler or focused-contract failure. Do not launch Tauri/FastAPI, bind `127.0.0.1:8766`, open a real browser, show a tray/menu/window, create a bundle manifest, package, sign, or claim a platform smoke test. |

| Experiment | Result | Decision and boundary retained |
| --- | --- | --- |
| L4-I | Passed. Rust compilation and all focused Rust contracts passed in the isolated Rust 1.85 environment; the selected Python static/Host RPC contracts also passed. The source strictly parses the post-handshake preferences response, defaults a Tauri child to desktop while preserving valid imported preference values, selects an external WebView or the fixed-origin host-only opener, and uses tray/single-instance reopen plus desktop close-to-hide without calling monitor stop. The FastAPI preference/API contract was not run because the available Python lacks FastAPI; no dependency was installed. | This proves only source-level behavior. No Tauri/FastAPI process, product-port bind, browser, tray, native window, native picker, installer, signing, or platform smoke was run. |

### L4-F: imported startup-surface migration correction

| Field | Record |
| --- | --- |
| Hypothesis | Windows settings migration can preserve a valid imported `startup_surface=desktop` value while runtime policy still rejects new desktop selection in the portable edition. |
| Decision changed by result | Whether this source slice may enter quality review. |
| Minimal sample | One migration with an existing `desktop` preference and one migration with an existing `browser` preference. |
| Stop condition | Stop at the first migration or contract failure. Do not modify the Rust host, tray, or API; do not start a service, install dependencies, or package. |
| Result | Passed. Migration preserves explicit imported `desktop` and `browser`; Windows portable still rejects a new desktop selection at runtime. Three migration tests and nine documentation tests passed. |

### L4-G: post-preference ownership revalidation

| Field | Record |
| --- | --- |
| Hypothesis | If the child exits or the fixed port is replaced while the host reads post-handshake preferences, the host must use a fresh ownership challenge/HMAC and identity probe after that read before it can arm authorization or return a startup surface. |
| Decision changed by result | Whether the startup-surface source boundary may remain in quality review. |
| Minimal sample | One Rust mock or source contract representing a replacement failure after preference retrieval. |
| Stop condition | Stop at the first identity or authorization failure. Do not start a real Tauri or FastAPI process, bind the product port, or show a browser, tray, window, or native panel. |
| Result | Passed. `BackendHost::launch` now completes the initial retry probe, reads the strict preference response, then checks child liveness before and after a fresh direct ownership/identity/OpenAPI probe before arming authorization. The isolated offline `cargo check` passed; focused Rust tests passed with 7 library and 5 lifecycle-contract tests, including replacement and child-exit rejection. No Tauri or FastAPI process, product-port bind, browser, tray, window, or native panel was started. |

### L4-H: picker response lifecycle

| Field | Record |
| --- | --- |
| Hypothesis | The Python Host RPC wait budget will not expire before Rust's bounded 120-second picker dialog, and `HostRpcError` from all four picker routes will become a stable, diagnosable 5xx response without exposing a token, URL, or secret. |
| Decision changed by result | Whether the picker bridge boundary may remain in quality review. |
| Minimal sample | Python static or unit error-mapping and timeout contracts. |
| Stop condition | Stop at the first contract failure. Do not open a real native panel or API server, install dependencies, or start/package a host. |
| Result | Passed. Rust keeps the picker dialog at 120 seconds; Python waits 125 seconds with a five-second response margin. All four picker routes catch only `HostRpcError` and return the fixed redacted `503 Native picker unavailable`, while the unconfigured Tauri path retains the Tk fallback. The focused Python suite passed 26 tests; the available Python lacks FastAPI, so no endpoint-runtime or native-panel test was run. |

### L5: updater dependency and API decision

| Field | Record |
| --- | --- |
| Hypothesis | One official crates.io sparse-index temporary manifest, using the existing isolated Rust 1.85/Cargo homes and the repository MSRV fallback resolver, can select one exact published `tauri-plugin-updater` version compatible with `tauri = 2.11.5` and Rust 1.85. Its downloaded source and metadata will show a Rust API that (a) performs signed update checks, (b) keeps download separate from install/restart sufficiently for the host to stop and verify the monitor only immediately before installation, and (c) can be configured without embedding updater key material in the public checkout. |
| Decision changed by result | A pass permits only a later minimal source implementation of the host-delegated updater slice. Any dependency, MSRV, API, or configuration inability blocks that slice: do not substitute a different updater, hand-roll signature verification, change the project `Cargo.lock`, package, sign, launch, or otherwise claim updater behavior. |
| Minimal sample | Copy `src-tauri/` to one temporary directory outside the worktree and resolve a tentative `tauri-plugin-updater = "2"` only in that temporary manifest through Cargo's default official crates.io sparse index. Inspect the selected crate metadata and downloaded Rust source with the existing isolated Rust 1.85/Cargo homes and MSRV fallback; do not mutate this repository's `Cargo.toml` or `Cargo.lock`. |
| Stop condition | Stop at the first registry, resolution, MSRV, API, or configuration failure. Do not retry via a mirror or another dependency family, install Python dependencies, launch Tauri/FastAPI, bind `127.0.0.1:8766`, open a browser/window/tray/native dialog, create a bundle/package, sign, publish, or claim a platform smoke test. |
| Result | Passed for a later minimal source slice only. The official sparse-index temporary lock selected `tauri-plugin-updater 2.10.1` from `registry+https://github.com/rust-lang/crates.io-index`; its declared MSRV is Rust `1.77.2`, its `tauri = "2.10"` dependency resolved with the existing exact `tauri 2.11.5`, and the MSRV fallback graph remained Rust-1.85-compatible. `UpdaterExt::updater_builder().build().check().await` returns a candidate; `Update::download(...)` downloads and verifies the Minisign artifact signature against `Config.pubkey` before it returns bytes, while `Update::install(bytes)` is separate and performs the platform install/restart handoff. Later host code must not use `download_and_install`: it may download and verify first, then stop and re-check the independent monitor immediately before `install`. The plugin config requires a `pubkey` field during deserialization, but both plugin `Builder::pubkey(...)` and `UpdaterBuilder::pubkey(...)` override it at runtime; a public checkout can retain only a non-key placeholder and inject the actual public verification key from a controlled bundle input. No private signing key is requested or accepted by this plugin. `check()` itself parses HTTPS metadata; artifact signature verification occurs in `download`, so the existing fixed-feed metadata gate must remain in front of host installation. |

### L6: host-delegated updater source boundary

| Field | Record |
| --- | --- |
| Hypothesis | With the L5-reviewed exact plugin, the owned Tauri host can expose only fixed `update_check` and `update_install` Host RPC commands. The backend keeps its existing allowlisted feed check as the metadata gate, while the host stores one verified candidate, downloads and Minisign-verifies it before any monitor action, then stops and independently rechecks the monitor immediately before `install`. A missing candidate, stale/cancelled request, download/signature error, monitor-stop failure, or monitor still running aborts before installation and does not falsely report a runtime transition. |
| Decision changed by result | A compatible official locked dependency plus focused source contracts permits adding `POST /api/v1/update/install` and Tauri-only delegation while preserving the existing check response. Any lock, compiler, contract, ownership, or state-order failure blocks this slice; it does not authorize a fallback updater, browser download, arbitrary URL/path/signature forwarding, package, signing, restart, or release claim. |
| Minimal sample | First add only `tauri-plugin-updater = "=2.10.1"` to a temporary copy that also carries the root `.cargo/config.toml` MSRV-fallback policy, with the authorized official Rust 1.85/Cargo homes, and generate its lock through the default crates.io sparse index. Then update this checkout with the exact reviewed declaration and lock, compile only the locked offline desktop binary and focused Rust contracts, and run focused Python Host RPC/API-static tests. The implementation sample uses one allowed and one rejected request per failure category. |
| Stop condition | Stop at the first registry, lock, MSRV, compiler, ownership, metadata-gate, signature/download-order, monitor-stop, or contract failure. Do not launch Tauri/FastAPI, bind `127.0.0.1:8766`, invoke a real updater, open browser/window/tray/native dialog, create an artifact, package, sign, publish, or claim a platform smoke test. |
| Result (2026-08-16) | Passed as a source boundary. `backend.rs` reads the bundle manifest as raw bytes and requires its SHA-256 to equal the compile-time `INVOICE_HUB_BUNDLE_MANIFEST_SHA256`; the future packager injects that value only while compiling the signed desktop host from the staged manifest, so a source checkout has neither the value nor the manifest and remains exit `78`. The update-specific Host RPC surface accepts only `update_check` and `update_install`; a candidate lasts at most 300 seconds and is consumed before download. The install order is fixed: host-verified candidate -> download plus Minisign verification -> monitor stop -> independent stopped recheck -> install/restart. Expiry/cancellation, download/signature failure, monitor-stop failure, or a still-running monitor abort before install. In the controlled Rust 1.85 offline environment, `cargo test --locked --offline --lib --test lifecycle_contract` passed 12 library tests and 5 lifecycle tests, and `cargo check --locked --offline --bin invoicehub-desktop` passed. No Tauri/FastAPI product process, `127.0.0.1:8766` bind, real download/update, bundle, signature, package, restart, or platform smoke was run. |

### L6-P: isolated Python API and Host RPC runtime contract

| Field | Record |
| --- | --- |
| Hypothesis | An isolated temporary Python 3.14 virtual environment populated only from the official PyPI index with the project's exact runtime pins, `pytest`, and the FastAPI TestClient runtime can import the source tree and execute the L6 Host RPC and update-install endpoint contracts. |
| Decision changed by result | A pass upgrades the prior static-only Python evidence to focused runtime API evidence for L6. A dependency resolution, import, or test failure blocks L6 at that category; it must be repaired in the smallest demonstrated module rather than treated as covered by the existing source assertions. |
| Minimal sample | One fresh temporary virtual environment outside the worktree; one explicit official-index installation of the exact runtime pins plus `pytest==9.1.1` and `httpx2==2.9.1`; then `pytest -W error::DeprecationWarning tests/test_tauri_host_rpc.py tests/test_tauri_lifecycle_contract.py tests/test_api_contract.py::test_host_delegated_update_install_requires_an_empty_body_and_redacts_failures`, importing this checkout through `PYTHONPATH=src`. This replaces the obsolete first-round `httpx==0.28.1` sample. |
| Stop condition | Stop at the first package-resolution/install failure, import failure, or failing test category. Do not modify the user Python, project dependency declarations, Rust lock, updater configuration, start FastAPI/Tauri, bind `127.0.0.1:8766`, or run a real update/install. |
| Result (2026-08-16) | Passed. A clean temporary Python environment with the project exact runtime pins, `pytest==9.1.1`, and `httpx2==2.9.1` ran `pytest -W error::DeprecationWarning tests/test_tauri_host_rpc.py tests/test_tauri_lifecycle_contract.py tests/test_api_contract.py::test_host_delegated_update_install_requires_an_empty_body_and_redacts_failures`: 20 passed with deprecations treated as errors. This is isolated in-process FastAPI TestClient runtime evidence, replacing the prior static-only wording; it is not a started product FastAPI service or host updater. No Tauri process, product-port bind, real download/update, bundle/package/signature, restart, or platform smoke was run. |

### L6-P-R: declared TestClient transport confirmation

| Field | Record |
| --- | --- |
| Hypothesis | The repository's declared `httpx2==2.9.1` test transport, rather than the deprecated compatibility `httpx` transport, can execute the same isolated L6 API/Host RPC sample on Python 3.14. |
| Decision changed by result | A pass makes the focused Python evidence match the declared test tooling. A resolver, import, warning-as-failure, or test failure blocks this evidence category and must be addressed as a dependency/test-harness issue without changing updater behavior. |
| Minimal sample | One new temporary virtual environment under the existing disposable L6 directory; the same exact runtime pins and `pytest==9.1.1`, but `httpx2==2.9.1` in place of `httpx`; then rerun the exact L6-P pytest selection once. |
| Stop condition | Stop at the first package-resolution/install failure, import failure, deprecation warning, or failing test category. Do not alter project dependency declarations, source, locks, product ports, or any real updater lifecycle. |
| Result (2026-08-16) | Passed and is the authoritative L6-P transport record. With `httpx2==2.9.1`, the exact command `pytest -W error::DeprecationWarning tests/test_tauri_host_rpc.py tests/test_tauri_lifecycle_contract.py tests/test_api_contract.py::test_host_delegated_update_install_requires_an_empty_body_and_redacts_failures` completed with 20 passed and no accepted deprecation warning. It validates only the isolated TestClient transport and contracts; it does not start Tauri/FastAPI, bind `127.0.0.1:8766`, download or install an update, create a bundle, sign, package, restart, or provide platform smoke evidence. |

### L6-R: fresh metadata approval and candidate expiry repair

| Field | Record |
| --- | --- |
| Hypothesis | A Tauri host-install approval cannot be derived from a persisted cache, cached ETag, or `304` response: it must receive and revalidate one fresh `200` body from the fixed allowlisted Feed in the same serialized approval session. The host's stored candidate is also actively removed at its 300-second deadline without waiting for a later install request, while the Host RPC token remains confined to the host and its directly spawned backend rather than Web content or descendant processes. |
| Decision changed by result | A pass permits the repaired L6 source boundary to return to specification review. A cache, expiry, token-boundary, compiler, or contract failure blocks only updater delegation and confines any repair to the demonstrated updater/Host RPC/documentation module. |
| Minimal sample | One isolated Python contract with a representative fresh-looking persisted cache/ETag and one fresh `200` allowlisted metadata response, one Rust candidate-expiry unit/static contract, and the documentation contract. |
| Stop condition | Stop at the first dependency, compiler, cache-authorization, candidate-expiry, token-boundary, or documentation-contract failure. Do not start Tauri/FastAPI, bind `127.0.0.1:8766`, invoke an actual updater, open a native surface, create an artifact, package, sign, publish, or claim a platform smoke test. |
| Result (2026-08-16) | Passed. `UpdateService.check(require_fresh_body=True)` bypasses cache and `If-None-Match`, rejects `304`, and only returns an approval-eligible result after a fresh allowlisted `200` body; `AppState` uses that strict path only for the serialized Tauri host approval session. `HostUpdater` now has the existing bounded listener loop actively sweep the 300-second slot and generation-recheck removal, so an old sweep cannot clear a newer candidate. Current-fact documents now state the actual token handoff: host -> directly spawned Python backend -> startup capture and descendant scrub, never Web/Tauri command/event/API response/logs. In the isolated Python 3.14 `httpx2` environment, the existing L6 selection plus the fresh-body and documentation contracts passed: 31 tests with `DeprecationWarning` as errors. In the reviewed Rust 1.85 offline environment, 13 library tests and 5 lifecycle integration tests passed. The existing L6 binary `cargo check` was not rerun because `main.rs`, `backend.rs`, Cargo inputs, and public host interfaces were unchanged; the modified Rust library compiled in the focused test. No Tauri/FastAPI product process, `127.0.0.1:8766` bind, real update/download, bundle, signature, package, restart, or platform smoke was run. |

### L6-RR: strict-request cache directive and command-surface clarification

| Field | Record |
| --- | --- |
| Hypothesis | A strict Tauri host-approval metadata request must explicitly ask the fixed Feed to revalidate via `Cache-Control: no-cache`, while continuing to omit `If-None-Match` and reject `304`; non-host ordinary update checks must retain their existing cache/ETag behavior. The Host RPC documentation must distinguish the four picker enums from the separate, fixed `update_check` and `update_install` updater enums without widening the token boundary. |
| Decision changed by result | A pass keeps L6-R's host-approval evidence suitable for specification review with an explicit on-wire freshness directive and a non-ambiguous command-surface contract. A header, cache-semantics, Host RPC, or documentation-contract failure blocks only this L6-RR evidence and confines repair to the demonstrated update/Host RPC/documentation surface. |
| Minimal sample | In the existing isolated Python environment, run the targeted update-service, Host RPC, and documentation contracts with deprecations as errors. The sample asserts the strict request's `Cache-Control: no-cache`, absence of `If-None-Match`, `304` rejection, unchanged non-host cache/ETag path, and both architecture documents' four-picker/two-updater distinction. |
| Stop condition | Stop at the first dependency, warning, strict-request header, ordinary-cache, Host RPC, or documentation-contract failure. Do not modify Rust, start Tauri/FastAPI, bind `127.0.0.1:8766`, invoke a real update, open a native surface, package, sign, publish, or claim a platform smoke test. |
| Result (2026-08-16) | Passed. The strict host-approval branch now sends `Cache-Control: no-cache`, still omits `If-None-Match`, and rejects `304`; non-host checks retain their existing ETag cache behavior without the new header. The platform and interface documents explicitly separate the four fixed picker enums from the two fixed updater enums, and the documentation contract locks that distinction together with the direct-backend token handoff. In the isolated Python `httpx2` environment, `PYTHONPATH=src pytest -W error::DeprecationWarning -q tests/test_update_service.py tests/test_tauri_host_rpc.py tests/test_development_documentation.py` completed with 40 passed. No Rust test was rerun or modified, and no Tauri/FastAPI product process, product-port bind, real update, package, signing, or platform smoke test was run. |

### L6-RRR: nonblocking host-approval contention (superseded by L6-RRRR)

| Field | Record |
| --- | --- |
| Hypothesis | The initial experiment incorrectly generalized that every ordinary `/api/v1/update/check` could bypass `_host_update_lock`. L6-RRRR narrows that behavior to non-Tauri/non-host processes. A contended hosted-Tauri approval check must still return the same non-persistent busy result without touching metadata transport, the host candidate, or an existing approval. |
| Decision changed by result | The 42-test pass is superseded for hosted-Tauri scope: it does not establish the public strict-preflight or install-contention behavior now required by L6-RRRR. |
| Minimal sample | In the isolated Python environment, replace the queued-second-host-check contract with a held-host-lock immediate-busy sample that proves no metadata/candidate call and no approval reset; add an ordinary non-Tauri check while that host lock is held; retain the successful strict metadata -> candidate -> install sample and assert the AppState path delegates busy-result construction to `UpdateService`. |
| Stop condition | Stop at the first dependency, warning, lock-contention, ordinary-check, approval-retention, metadata/candidate, API-contract, or documentation-contract failure. Do not modify Rust, start Tauri/FastAPI, bind `127.0.0.1:8766`, invoke a real update, open a native surface, package, sign, publish, or claim a platform smoke test. |
| Result (2026-08-16) | Superseded by L6-RRRR. The 42-pass command is historical output only; it is not current evidence that hosted-Tauri public checks are strict preflight or that install lock contention is nonblocking. No Rust test was rerun or modified, and no Tauri/FastAPI product process, product-port bind, real update, package, signing, or platform smoke test was run. |

### L6-RRRR: hosted-Tauri strict public checks and nonblocking install contention

| Field | Record |
| --- | --- |
| Hypothesis | In a process with both the Tauri host marker and configured private Host RPC, every caller of `AppState.check_for_updates` (public API, settings, and background timer) is the delegated-install preflight: it must take the nonblocking host lock, require a fresh allowlisted Feed `200` body, and require the exact host candidate before approval. Only a non-Tauri/non-host process keeps `UpdateService` cache/ETag/busy semantics. `install_update` lock contention must fail immediately without consuming an approval or issuing a second private RPC, while an acquired install remains one-shot. |
| Decision changed by result | A pass replaces L6-RRR as the current Python evidence for hosted-Tauri update orchestration. A strict-path, lock, approval-retention, second-RPC, or documentation failure blocks only this L6-RRRR slice and confines repair to `AppState`, its focused contracts, and current-fact documentation. |
| Minimal sample | In the existing isolated Python environment, run only `tests/test_update_service.py`, `tests/test_tauri_host_rpc.py`, and `tests/test_development_documentation.py` with `DeprecationWarning` as errors. The host-RPC sample uses `force=False` to prove strict hosted public preflight, preserves the non-host held-lock cache path, holds a lifecycle lock to prove install retains approval, and blocks a first `update_install` RPC to prove a second request returns before that RPC completes and makes no second RPC. |
| Stop condition | Stop at the first dependency, warning, strict-preflight, cache-scope, lock-contention, approval-retention, RPC-count, or documentation-contract failure. Do not modify Rust, start Tauri/FastAPI, bind `127.0.0.1:8766`, invoke a real update, open a native surface, package, sign, publish, or claim a platform smoke test. |
| Result (2026-08-16) | Superseded by L6-RRRRR for the event-write and exception-release gap. The historical 44-pass sample did not prove a lock-contended hosted check bypasses `append_event`/SQLite, or that a private install RPC exception releases the host lock for a later approved install. No Rust test, Tauri/FastAPI product process, product-port bind, real update, package, signing, or platform smoke test was run. |

### L6-RRRRR: lock-contended busy event bypass and exception-path release

| Field | Record |
| --- | --- |
| Hypothesis | A hosted check that loses `_host_update_lock` must return its non-persistent busy result before `append_event`, otherwise its supposedly immediate path can block on SQLite. Separately, an acquired `install_update` must consume its one-shot approval even when private `update_install` raises, and its `finally` must release the lock so a newly granted approval can install later. |
| Decision changed by result | A pass replaces L6-RRRR as the current Python evidence for these two independent failure modes. A busy-event, approval-consumption, exception-release, lock, or documentation failure blocks only L6-RRRRR and confines repair to `AppState`, focused Host RPC contracts, and current-fact documents. |
| Minimal sample | In the declared isolated Python environment, run the same three targeted test files. One contended hosted-check worker receives a deliberately blocking `append_event` and must complete under the short budget without invoking it; this is distinct from L6-RRRR's lifecycle-lock and active-install samples because it detects a post-lock SQLite event write. A second sample makes the first private `update_install` raise `HostRpcError`, proves approval was consumed, then grants a new approval and succeeds to prove `finally` released the lock; this is distinct from ordinary install contention because it exercises the exception path. |
| Stop condition | Stop at the first dependency, warning, event-write, immediate-return, approval-consumption, exception-release, lock, RPC, or documentation-contract failure. Do not modify Rust, start Tauri/FastAPI, bind `127.0.0.1:8766`, invoke a real update, open a native surface, package, sign, publish, or claim a platform smoke test. |
| Result (2026-08-16) | Passed. The declared isolated Python command `PYTHONPATH=src /private/tmp/invoicehub-l6-python.eljPta/venv-httpx2/bin/pytest -W error::DeprecationWarning -q tests/test_update_service.py tests/test_tauri_host_rpc.py tests/test_development_documentation.py` completed with 45 passed. The blocked-`append_event` host-check sample returned before the event writer was invoked, while the private install exception sample consumed its first approval and completed a later approved install, proving `finally` released the lock. This replaces L6-RRRR's historical 44-pass result for the event-write and exception-release scope. No Rust test, Tauri/FastAPI product process, product-port bind, real update, package, signing, or platform smoke test was run. |

### L6-R-E: isolated Rust toolchain PATH recovery

| Field | Record |
| --- | --- |
| Hypothesis | Adding only the already reviewed official Rust 1.85 toolchain `bin` directory to this child process `PATH` lets Cargo locate its matching `rustc`, without downloading, installing, or changing any lock. |
| Decision changed by result | Whether the Rust code-level evidence can resume; a failure blocks this category. |
| Minimal sample | `rustc -vV` and one existing offline `cargo test --locked --offline --lib --test lifecycle_contract`. |
| Stop condition | Stop at the first path, toolchain, or compiler failure; do not retry, download, install, change a lock, start a product process, bind `127.0.0.1:8766`, invoke an updater, package, sign, or publish. |
| Result (2026-08-16) | Passed. With only the previously reviewed Rust 1.85 toolchain `bin` prepended to the child `PATH`, `rustc -vV` reported `rustc 1.85.0`, and the exact locked offline lifecycle test passed with 13 library tests and 5 integration tests. It used only a test-only `127.0.0.1:0` listener; it did not download/install, change a lock, start Tauri/FastAPI, bind `127.0.0.1:8766`, invoke an updater, package, sign, or publish. |

### L7: release-input readiness audit

| Field | Record |
| --- | --- |
| Hypothesis | The sanitized source tree contains enough deterministic, non-secret build inputs to identify the next smallest implementation task for the Windows NSIS and macOS DMG/update-archive release paths without creating an artifact. |
| Decision changed by result | A complete input chain permits a later separately authorized build-preflight experiment; a missing staged manifest generator, platform builder, verifier, provenance input, or documented credential boundary narrows the next task to that missing source-level component rather than attempting a package or release. |
| Minimal sample | Read-only inspection of `version.py`, the Tauri manifest/configuration, version synchronizer, release/build/verification scripts, dependency locks, package manifests, and their documented consumers for each target platform. |
| Stop condition | Stop at the first mandatory missing or ambiguous release input. Do not generate a bundle or artifact, start Tauri/FastAPI, bind `127.0.0.1:8766`, use signing credentials, notarize, upload, publish, or create a Release/Feed. |
| Result (2026-08-16) | Blocked at the first mandatory input at that time. `src-tauri/tauri.conf.json` deliberately kept `bundle.active=false`, while `backend.rs` required a schema-2 `invoicehub-desktop-host.json` whose raw SHA-256 had no generator or staged compiler input. The existing Windows script produced the retired portable ZIP identity and the existing macOS script built the legacy Swift/Sparkle app, so neither could supply Tauri NSIS or DMG/update-archive inputs. The next task was therefore the dynamic state-layout and manifest-path contract. L8-R, L8-S, and L9 below supersede this development-assembly blocker only; they do not supply NSIS, DMG/update archive, signing, notarization, Feed, Release, or platform-release evidence. |

### L8: desktop state-layout and staged-manifest path contract

| Field | Record |
| --- | --- |
| Hypothesis | The host can resolve a per-user desktop state root at launch, derive the config and runtime paths from that root, and bind the derived paths into the expected backend identity while accepting only bundle-relative core/launcher inputs from a future signed manifest. This prevents a compile-time manifest from embedding a workstation path or directing user writes into bundle resources. |
| Decision changed by result | A passing pure source contract permits a later canonical staged-host-manifest generator to use fixed relative resource inputs and runtime-derived state paths. Any path-resolution, identity, or unsafe-relative-path failure keeps platform assembly blocked and confines repair to this host boundary. |
| Minimal sample | One synthetic Windows local-app-data root, one synthetic macOS home root, and one representative traversal/absolute bundle-path rejection. |
| Stop condition | Stop at the first platform-root, derived config/runtime, identity, or unsafe-path failure. Do not invoke `tauri build`, produce a bundle, start Tauri/FastAPI, bind `127.0.0.1:8766`, use credentials, sign, notarize, upload, publish, or create a Release/Feed. |
| Result | Implementation present; focused verification is recorded separately in L8-R. The host derives Windows and macOS per-user state paths, rejects manifest-embedded config/runtime paths, and accepts only bundle-relative launcher/core inputs. The implementation uses schema 3; the earlier L7 schema-2 wording is superseded. |

### L8-R: development profile and resource-root source contract

| Field | Record |
| --- | --- |
| Hypothesis | A compile-bound schema-3 `development` profile can resolve a macOS `.app` executable to `Contents/Resources`, require a staged build manifest plus a hash-bound launcher/core, derive all writable state below the user state root, and explicitly disable updater delegation without weakening the `release` profile. |
| Decision changed by result | A pass permits one separately bounded macOS development-app assembly experiment. Any resource-root, launcher hash, manifest profile, updater-disable, state-path, compiler, or focused Python contract failure keeps application assembly blocked and confines repair to this development host boundary. |
| Minimal sample | `cargo fmt --check`; locked Rust library and lifecycle contracts covering the macOS resource root, release/development manifest validity, path containment, launcher hash and updater-disable boundary; focused Python Host RPC/update-disable and development-assembler contracts only. |
| Stop condition | Stop at the first formatting, compiler, manifest, path, updater-disable, or focused Python failure. Do not start the product, bind `127.0.0.1:8766`, open a window/browser/dialog, build an `.app`, invoke an updater, sign, notarize, upload, publish, or create a Release/Feed. |
| Result | Passed on 2026-08-16. Locked `rustfmt` completed without drift; the current affected suite passed 17 Rust library tests, 6 Rust lifecycle tests, and 149 focused Python contracts. The schema-3 development profile resolves `Contents/Resources`, requires the staged build manifest and launcher hash, rejects a package manifest, disables updater registration/delegation, and keeps the release profile strict. |

### L8-S: isolated development smoke state

| Field | Record |
| --- | --- |
| Hypothesis | A development-only absolute `INVOICE_HUB_DEV_STATE_ROOT` can replace the normal user state root for one clean smoke launch, while release manifests and relative overrides fail closed and the override is removed from the Python child environment. |
| Decision changed by result | A pass permits the single L9 launch without reading or writing the existing `~/Library/Application Support/InvoiceHub`; a failure keeps L9 blocked rather than repurposing `HOME`, moving user state, or scanning an existing watch directory. |
| Minimal sample | Pure Rust path-selection cases for development/default/release/relative inputs, one static child-environment removal contract, then the same single L9 application launch against one empty absolute temporary root. |
| Stop condition | Stop at the first profile, absolute-path, child-environment, identity, or state-containment failure. Do not touch existing InvoiceHub user state, alter `HOME`, add a release override, or broaden the state path contract. |
| Result | Passed on 2026-08-17. Development accepts one absolute isolated state root, rejects release/relative overrides, and removes the override before spawning Python. The single L9 launch used that clean root; the real user Application Support directory was neither read nor written. Stop after this representative sample. |

### L9: one unsigned macOS development application

| Field | Record |
| --- | --- |
| Hypothesis | After L8-R passes, the dev-only assembler can copy the explicit shared-core allowlist into ignored staging, generate the compile-bound schema-3 manifest, build one unsigned macOS `.app`, and run one owned backend at exactly `127.0.0.1:8766` with valid health/home identity before a clean host exit. |
| Decision changed by result | A pass establishes the first runnable Tauri development artifact and permits review through a Draft PR. A staging, compile, bundle layout, fixed-port ownership, health, homepage, or shutdown failure blocks publication of this implementation and is repaired only in the demonstrated category. |
| Minimal sample | One arm64 macOS development `.app` built from the reviewed branch with the explicit project virtual-environment Python; inspect `Contents/Resources`, manifest SHA and prohibited inputs; launch once against a clean development state root; check fixed-port ownership, `/api/v1/health`, `/`, and clean exit. |
| Stop condition | Stop at the first staging, build, layout, port, handshake, page, or exit failure. Do not create a DMG/update archive, use signing credentials, invoke a real updater, notarize, upload, publish a Release/Feed, or claim Windows/platform-release coverage. |
| Result | Passed for this bounded development-app scope on 2026-08-17 after P1-Q. The assembler staged only the allowed shared core, generated a schema-3 development manifest and explicit venv launcher, then built one local macOS arm64 `InvoiceHub.app`. Resource inspection found the manifest/launcher SHA bindings and no package manifest, user configuration, runtime state, virtual environment, business data, or `node_modules`. The local artifact carried only a development ad-hoc linker mark, not Developer ID, Team ID, CMS, resource sealing, notarization, or release provenance. The isolated launch owned exactly `127.0.0.1:8766`; health and background startup became ready, homepage/static assets loaded, and `desktop_available=true` with the default `desktop` surface. The first launch exposed a tray initialization failure from a 16-bit RGBA icon; converting the icon to 8-bit RGBA and adding an IHDR contract repaired that mechanism. An external AppleScript quit later invalidated the original exit subclaim, so P1-Q rebuilt from clean commit `399b20c` and replaced only that failed evidence with a genuine Cmd-Q sample: shutdown POST 200, stopped state, monitor unchanged, process/PID/port cleanup, and explicit kill+wait fallback for open SSE connections all behaved as designed. No DMG, NSIS, update archive, real updater/download/install, native picker, browser/tray-click/second-instance scenario, Developer ID, notarization, upload, Release, Feed, or Windows smoke was run. |

### L10: host-owned monitor recovery transaction

| Field | Record |
| --- | --- |
| Hypothesis | A small host-owned recovery primitive can persist the fact that an owned monitor was running, stop it, and restore it only after a later owned status reports `running=true` and `ready=true`; marker corruption, symlink substitution, ownership loss, stop/status/start failure, and an originally stopped monitor must fail closed without changing an external monitor. |
| Decision changed by result | A passing source-level transaction permits a DCO implementation commit and focused Rust/documentation verification, but does not authorize real download, signature verification, installer replacement, relaunch, or enabling `update_install`. Any failure blocks updater integration and confines repair to the marker/recovery module. |
| Minimal sample | One representative owned running monitor, one originally stopped monitor, one stop/status/start failure path, one unowned backend, and one invalid/symlink marker; run focused Rust formatting/tests when the locked offline cache is available, plus the affected documentation contract and `git diff --check`. |
| Stop condition | Stop at the first marker, ownership, monitor-state, compiler, test, or documentation-contract failure. Do not start Tauri/FastAPI, bind `127.0.0.1:8766`, call a real updater, download or verify an update, stop a real monitor, build a bundle, sign, publish, or create a Release/Feed. |
| Result (2026-08-18) | Stopped during the source-level safety review. The candidate could not bind each bridge operation to a captured lifecycle generation/phase/health PID/owned PID/process PID lease or require a released startup gate; its final marker publication and clear operations also remained path-based after parent checks, so a same-user parent/destination swap could not be ruled out. The candidate and its implementation claims were removed rather than committing an unaudited primitive. `update_install` remains candidate-consuming and fail-closed; no monitor, download, signature verification, installer replacement, relaunch, bundle, signing, or release smoke occurred. A later coordinator must define the lease and opened-directory/no-follow final-operation contract before retrying this experiment. |

### P1-SC: setup-failure termination confirmation

| Field | Record |
| --- | --- |
| Hypothesis | If tray or the chosen surface fails after `BackendHost::launch`, setup can retain its local host object and retry the existing graceful/forced shutdown path until the owned child exit is confirmed; it never returns the surface error while cleanup remains unconfirmed. |
| Decision changed by result | A pass permits one DCO fix-forward commit and one rebuild of the development `.app`; a failure blocks that rebuild and confines repair to the setup-cleanup boundary. |
| Minimal sample | One static lifecycle contract for local ownership, cleanup retry, no cleanup-error return to `Drop`, and order before `app.manage`; locked Rust formatting and offline desktop check; focused lifecycle/foundation/documentation contracts and `git diff --check`. |
| Stop condition | Stop at the first cleanup-order, retry, format, compiler, contract, or documentation failure. Do not launch Tauri/FastAPI, bind the product port, invoke update/install, create a DMG/NSIS, sign, publish, or change release settings. |
| Result (2026-08-18) | The first source-level implementation was rejected during review before commit: its post-shutdown polling used `child_is_running`, which treats a child mutex or `try_wait` error as false and could therefore accept an unconfirmed exit. The initial static test did not exercise that distinction. P1-SC-R below owns the narrowed repair; no DCO commit or rebuild is authorized by this rejected result. |

### P1-SC-R: strict graceful child-exit confirmation

| Field | Record |
| --- | --- |
| Hypothesis | The graceful shutdown polling can use a strict `Result<bool, BackendError>` confirmation helper, so child mutex or `try_wait` errors fall into the existing forced `kill + wait` path rather than being accepted as an exit. |
| Decision changed by result | A pass permits one DCO fix-forward commit and one development-app rebuild; a failure blocks both and confines repair to child-exit confirmation. |
| Minimal sample | One static lifecycle contract for the strict helper and graceful-loop propagation, plus the P1-SC setup-retry/order contract; locked Rust formatting and offline desktop check; focused lifecycle/foundation/documentation tests and `git diff --check`. |
| Stop condition | Stop at the first child-confirmation, retry, format, compiler, contract, or documentation failure. Do not launch Tauri/FastAPI, bind the product port, invoke update/install, create a DMG/NSIS, sign, publish, or change release settings. |
| Result (2026-08-18) | Passed for the narrowed source-level confirmation boundary. Locked Rust 1.85 `cargo fmt --check --all` and offline `cargo check --locked --offline --bin invoicehub-desktop` passed. The 40 focused Python lifecycle/foundation/documentation contracts passed with `DeprecationWarning` treated as errors; version synchronization and `git diff --check` also passed. This permits one DCO fix-forward commit and one rebuild of the development `.app` only. It does not exercise setup failure in a running app, enable updater/install, create a DMG/NSIS, sign, publish, or establish platform-release evidence. |

### L11-A: internal-alpha macOS arm64 assembly and isolated launch smoke

| Field | Record |
| --- | --- |
| Hypothesis | A clean-snapshot Tauri assembly can embed the allowlisted shared core and pinned Python 3.14.6 arm64 runtime, produce a reviewable App/DMG/receipt, and start once from an isolated state root without touching user state. |
| Decision changed by result | The pass permits retaining one internal-alpha App/DMG for controlled review. It does not close recovery/relaunch, updater, signing, notarization, public Release, Feed, or final platform-install gates. |
| Minimal sample | One clean source commit (`1892a52bf5eba4ae3b24720fbc32899a4e6003a0`), one arm64 App, one same-source ad-hoc DMG, one schema-4 receipt, one independent verifier pass, and one temporary-HOME fixed-port launch smoke. |
| Stop condition | Stop at the first staging, runtime, manifest, artifact, verifier, port, identity, state-containment, or cleanup failure. Do not retry with the real HOME, change the port, invoke updater/install, sign, notarize, upload, publish, or create a Release/Feed. |
| Result (2026-08-19) | Passed. The App/DMG/receipt verifier passed with `core_build_id=9188334bf2d10a7a75d99b04683c946cd34139ba0061d64e20eb33e8c5c91f76`, `signature_mode=internal-adhoc`, `updater_enabled=false`, and `public_release=false`. The separate launch smoke reached `ready` on `127.0.0.1:8766`, matched package/build/source identity, left the real Application Support directory untouched, and terminated only its own process group. This is internal evidence, not a release or installation result. |

## Fixed scope and validation

- The backend binds only `127.0.0.1:8766`. An unknown listener is a clear
  error, never a reason to select another port or attach to an older process.
- `startup_surface` remains `desktop | browser`; a new Tauri installation
  defaults to desktop, while an imported explicit preference survives and is
  applied at the next start.
- After the owned-backend handshake, desktop creates the WebView and browser
  dispatches only the fixed origin through the host-only opener. Tray and a
  second instance reopen that surface; desktop close hides it and does not
  stop the independent monitor. L9 observed only the default desktop surface;
  browser, tray, second-instance, native-panel, and print behavior remain
  unexercised.
- The host passes the Host RPC token only to its directly spawned Python backend,
  which captures it at startup and scrubs it from descendant
  environments. It never reaches Web content, a Tauri command/event, API
  response, or logs; Web content can access only enumerated commands from the
  expected localhost origin.
- `POST /api/v1/update/check` remains compatible. `POST /api/v1/update/install`
  accepts only `{}` but currently consumes its process-local candidate and
  fails closed. It performs no download, monitor stop, installation, or restart
  until a recovery/relaunch coordinator can restore failed paths safely.
- The five final decision scenarios are startup surface, single instance and
  wrong port, Host RPC authorization, valid/tampered update, and monitor stop
  before install. They are not claimed by the foundation step.
- Windows 10/11 x64 NSIS and macOS 13+ arm64 DMG/update archives are the only
  first-release targets. MSI, Windows ARM64, Intel macOS, App Store, and
  GitHub Packages remain out of scope.
