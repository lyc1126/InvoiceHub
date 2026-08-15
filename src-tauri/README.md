# Tauri Host Foundation

This directory is the future Tauri 2 host for the existing InvoiceHub Python,
FastAPI, Web, and independent-monitor core. It contains no invoice,
projection, bookkeeping, or monitor business implementation.

The only executable contract currently present is the fixed backend origin
`http://127.0.0.1:8766`. The binary exits with a clear nonzero status until
the lifecycle, strict handshake, single-instance, tray, native-panel, print,
Host RPC, and updater tasks are implemented.

`Cargo.toml` permits the Tauri 2 major line, but the direct crate resolution
and `Cargo.lock` are intentionally not claimed as complete: the pinned Rust
toolchain and published crate metadata must be available before generating and
reviewing that lock. `scripts/dev/tauri_doctor.py --require-ready` fails closed
while that prerequisite is absent.
