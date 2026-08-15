# Changelog

## Unreleased

- 2026-08-16 Tauri 2 foundation: add the public execution plan, single-source
  version synchronizer, pinned pnpm Tauri dependencies, fixed-localhost host
  scaffold, and non-installing Windows/macOS doctor/bootstrap entry points.
  Diagnostics run from the requested project root, block Rustup/Corepack
  auto-downloads, and fail closed for missing Windows interpreter, MSVC, or
  SDK prerequisites. Rust/Cargo are absent on the current development host,
  so Cargo dependency resolution, `Cargo.lock`, compilation, lifecycle, Host
  RPC, and packaging remain explicitly blocked rather than being claimed as
  complete.
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
