# CLAUDE.md

This file is a concise entry point for coding agents. `AGENTS.md` is the authoritative repository instruction set and must be read in full before analysis, edits, tests, or conclusions.

## Current Baseline

- Public source and architecture baseline: a single sanitized root commit and its public descendants after the completed verification gate.
- Retired private commits, packages, tags, receipts, and validation material are not public release inputs and must not be recreated or uploaded.
- The next implementation branch is `codex/tauri2-unified-desktop` from the governance-complete, sanitized public `main`, beginning at `0.3.0-alpha.1`. Tauri 2 owns only desktop integration and continues to use the Python/FastAPI/Web/monitor core.
- The original worktree, stashes, untracked assets, ignored runtime state, and user data remain outside this release worktree.
- The repository is public after the approved history-sanitization gate. This does not authorize a Release asset, Feed, or Tauri branch: each still requires its own documented gate.

Always refresh the facts with:

```bash
git status --short --branch --ignored
git log --oneline --decorate --graph --all -8
git stash list
```

Do not stage unrelated accounting plugin files, cloud tutorial assets, `outputs/`, `.playwright-cli/`, local configuration, runtime state, or build products.

## Architecture Reading Order

1. [`AGENTS.md`](AGENTS.md)
2. [`docs/DEVELOPMENT_ARCHITECTURE.md`](docs/DEVELOPMENT_ARCHITECTURE.md)
3. [`docs/architecture/PLATFORM_ARCHITECTURE.md`](docs/architecture/PLATFORM_ARCHITECTURE.md)
4. [`docs/architecture/AGENT_TASK_MAP.md`](docs/architecture/AGENT_TASK_MAP.md)
5. The task-specific file, interface, data, and comment maps under `docs/architecture/`

For invoice recognition, summary stability, localhost, OCR, cost analysis, launch scripts, release acceptance, or old-project comparison, also read the truth documents required by `AGENTS.md`.

## Non-Negotiable Data Boundaries

- Source PDF/OFD/XML invoices are facts. CSV/XLSX/JSON outputs are rebuildable projections.
- Prefer empty values to polluted values. Money requires a valid format and nearby invoice evidence.
- `watch_dir`, TargetProfile workspace/state/localappdata, and project runtime have distinct roles.
- Cost detail, workbook, and status JSON stay in the active `watch_dir`; ordinary summaries stay in the profile workspace.
- SQLite stores tasks, events, settings, and cache only, never invoice master data.
- Bookkeeping truth stays under the company folder's `凭证/`; repository data must never enter source control.

## Shared Core And Platforms

There is one business core:

- Python/FastAPI and `/api/v1`
- shared Web templates, JS, CSS, and skins
- TargetProfile and file-based projections
- independent monitor daemon
- bookkeeping W8/W9 protocol

The current Windows source entry remains root BAT, shared PowerShell, external browser, and Python/Tk picker. The first public desktop target is `v0.3`, whose Windows installer and native desktop integration will be supplied by Tauri 2.

The existing macOS SwiftUI/WKWebView shell is a development and migration reference, not a public release target. `v0.3` replaces platform integration with Tauri 2, while retaining the same no-duplication boundary for invoice, cost, document, and bookkeeping logic.

Current handshake constants:

- API contract: `2026-08-02-release-update-v1`
- bookkeeping protocol: `w9-ledger-review-v1`
- required capabilities include the existing invoice/monitor/server contracts plus `release.package-identity.v1`, `settings.startup-surface.v1`, and `updates.metadata-check.v1`

The macOS shell compares packaged manifest, health, and required capabilities. It also validates build ID, config/runtime paths, PID, and required pages/APIs. `health.ok=true` alone is never sufficient.

Only a process launched by the current shell and matched across health/attempt/owned/Process PID is `owned`. A compatible unknown process is `externalCompatible` and cannot be stopped by the shell or Web settings page. Failed control actions retain ownership. PID/ownership cleanup occurs only after confirmed process exit.

WKWebView bridge messages, navigation, and native panels are limited to the expected localhost main frame. External pages and subframes receive no native capability.

Batch printing is narrower: only a trusted main frame can create exact `about:blank`. The registered popup may load or reload only its same-port, query-free `/invoices/print/{job_id}` route; it receives only the print bridge, never the folder or backend bridge.

## Monitor And Shutdown

- Monitor truth is live PID plus `.invoice_monitor.lock`; server state JSON is diagnostic only.
- Ready means first startup sync, observer or periodic fallback initialization, second catch-up sync, then `ready=true`.
- macOS prefers `PollingObserver`; if no observer is active, periodic fallback may continue but `observer_active=false` must remain visible.
- Closing a browser or macOS window does not stop monitor.
- Web shutdown accepts only `ok=true`, `scheduled || idempotent`, and the requested returned behavior.
- Native macOS stop sends `keep_monitor` with `remember=false`. App termination may converge an owned child directly.

## Bookkeeping Safety

- Stable business identity is `posting_key`; mutable facts, rules, accounts, decisions, and entries belong in `proposal_revision_hash`.
- Approval and export reuse `VoucherExecutabilityValidator` and server-side `blockers[]`.
- Mapping and state migrations are explicit preview/apply workflows with source SHA, preview hash, revision, binding, command identity, and backup verification.
- Export creates an immutable batch manifest and bound XLSX. Batch observations are finalized idempotently.
- Legacy per-item import result is HTTP 410. Runner input is an explicit `--batch-manifest`.
- W8 dry-run and W9 review completion do not authorize real state migration or Safari apply. Real apply/reconcile remains W10 and requires explicit same-turn user authority.

## Required Verification

Shared checks:

```bash
macos/InvoiceHubMac/.backend-venv/bin/python -m pytest
macos/InvoiceHubMac/.backend-venv/bin/python -m compileall src tests
git diff --check
```

Run `node --check` for every frontend JS file. Run documentation contracts and local Markdown link checks after architecture changes.

macOS checks:

```bash
(cd macos/InvoiceHubMac && swift test)
bash -n macos/InvoiceHubMac/script/build_and_run.sh
macos/InvoiceHubMac/script/build_and_run.sh --build-only
macos/InvoiceHubMac/script/build_and_run.sh --verify
```

Frontend changes require served-resource verification, current Ink Pulse, Animal Island, and `?no_skin=1`, desktop and narrow viewports, console errors, interactions, and scroll-chain checks. Native picker behavior must be tested in the real `.app` before claiming it.

Do not infer Windows BAT, browser foreground, Tk picker, core package, formal `.dmg`, signing, or notarization coverage from Python, Swift, or browser tests. Report exactly what was and was not exercised.

## Documentation And Closeout

- Every project change updates `CHANGELOG.md` Unreleased.
- Behavior/structure updates also update README and implementation status.
- Migration or acceptance changes update the migration checklist.
- Platform changes update the platform architecture, Mac/Windows workflow, and macOS README.
- API routes must appear in `INTERFACES_AND_FLOWS.md`; new files must appear in `FILE_MAP.md`.
- Finish with `git status --short --branch --ignored` and classify modified, deleted, untracked, ignored, and warnings.
