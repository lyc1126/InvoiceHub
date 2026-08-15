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
3. [ ] Establish the Tauri foundation: one version source, toolchain locks,
   a minimal `src-tauri/` project, and non-installing Windows/macOS
   `doctor/bootstrap` commands. The version source, JavaScript lock, scaffold,
   and diagnostics are complete; exact Cargo dependency selection and
   `Cargo.lock` remain blocked by the recorded Rust/registry prerequisite.
4. [ ] Implement fixed `127.0.0.1:8766` backend ownership, strict handshake,
   single-instance handling, and the internal Host RPC boundary.
5. [ ] Implement `startup_surface`, browser/tray behavior, update-install
   delegation, and the five fixed decision scenarios.
6. [ ] Build platform artifacts, perform each final RC smoke test once, and
   create the public Release and Pages Feed only after their separate gates.

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

## Foundation experiment results (2026-08-15)

| Experiment | Result | Decision and boundary retained |
| --- | --- | --- |
| F1 | Passed. `python3 scripts/dev/tauri_version_sync.py --check` matched the current `0.3.0-alpha.1` source identity; the focused test also repaired one derived-version drift in an isolated temporary copy. | The foundation may derive Cargo, Tauri JSON, and npm identity only from `version.py`; drift is a hard stop. |
| F2 | Blocked as designed. The current macOS `doctor --require-ready` found Node, pnpm, Xcode command-line tools, fixed origin, and pnpm lock, but no `rustc`, `cargo`, or `src-tauri/Cargo.lock`. | Do not compile Rust or begin host lifecycle work. Do not install Rust, certificates, Xcode, or Visual Studio from the bootstrap command. |
| F3 | Passed. One `pnpm install --lockfile-only --ignore-scripts` resolution produced the checked-in lock for `@tauri-apps/api@2.11.1` and `@tauri-apps/cli@2.11.4`. | The JavaScript lock is usable; it does not prove or replace a Cargo lock. |
| F4 | Blocked. One direct crates.io metadata lookup returned HTTP 403 before a published exact direct-crate version could be established. | Keep the scaffold's `tauri = "2"` and `tauri-build = "2"` declarations explicitly non-reproducible; do not invent an exact crate version or generate `Cargo.lock`. |
| F5 | Blocked. One local Cargo registry/index and cache lookup found no usable Tauri metadata. | Do not retry through an unapproved mirror. A controlled Rust/Cargo source is required before selecting exact crates or generating the lock. |

The foundation has not run Rust compilation, backend lifecycle, strict
handshake, single-instance, Host RPC, preferences/API changes, updater, or
packaging. Those are later delivery steps, not evidence implied by this table.

## Fixed scope and validation

- The backend binds only `127.0.0.1:8766`. An unknown listener is a clear
  error, never a reason to select another port or attach to an older process.
- `startup_surface` remains `desktop | browser`; a new Tauri installation
  defaults to desktop, while an imported explicit preference survives and is
  applied at the next start.
- The Host RPC token remains inside the host process. Web content receives no
  token and can access only enumerated commands from the expected localhost
  origin.
- `POST /api/v1/update/check` remains compatible. The future
  `POST /api/v1/update/install` delegates only to a host that can stop and
  verify the monitor; stop failure or user cancellation leaves runtime state
  unchanged.
- The five final decision scenarios are startup surface, single instance and
  wrong port, Host RPC authorization, valid/tampered update, and monitor stop
  before install. They are not claimed by the foundation step.
- Windows 10/11 x64 NSIS and macOS 13+ arm64 DMG/update archives are the only
  first-release targets. MSI, Windows ARM64, Intel macOS, App Store, and
  GitHub Packages remain out of scope.
