# Tauri Host Foundation

This directory is the future Tauri 2 host for the existing InvoiceHub Python,
FastAPI, Web, and independent-monitor core. It contains no invoice,
projection, bookkeeping, or monitor business implementation.

The only executable contract currently present is the fixed backend origin
`http://127.0.0.1:8766`. The binary exits with a clear nonzero status until
the lifecycle, strict handshake, single-instance, tray, native-panel, print,
Host RPC, and updater tasks are implemented.

`Cargo.toml` pins the direct crates to the published `tauri 2.11.5` and
`tauri-build 2.6.3` releases. The matching `Cargo.lock` was generated and
reviewed only with the pinned Rust toolchain in a controlled environment; its
focused compile and fixed-origin Rust test passed there. This does not make
the host runnable or authorize a bundle. `scripts/dev/tauri_doctor.py
--require-ready` fails closed while the toolchain or lock prerequisite is
absent.
