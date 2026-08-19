# L11-A Internal Tauri macOS arm64 Alpha

Status: passed bounded implementation record and separate isolated launch smoke
on 2026-08-19; started from clean source baseline
`9912004f62fc62fa16c6bc2e5c71b3f6fbdab2c3` on 2026-08-18.

## Hypothesis

A separate Tauri assembly can produce reviewable macOS arm64
internal-alpha staging tree from an exact clean Git commit. The app must carry
only an allowlisted shared core, an embedded (or explicitly staged) launcher,
and a schema-3 release-profile host manifest whose raw bytes and launcher are
hash-bound at compile time. The artifact is for controlled internal testing,
not public distribution.

## Decision Changed By Result

- A pass permits one bounded internal-alpha `.app` plus same-source ad-hoc DMG
  build and receipt/verifier run. It does not permit a Sparkle archive,
  updater, Feed, notarization, or public Release.
- A failure blocks the L11-A implementation and is repaired only in the
  staging, manifest, receipt, or verifier category that produced the failure.
- The existing development assembler remains unchanged; its schema-3
  development profile and external venv launcher are not release inputs.

## Minimal Sample

1. A copied clean Git snapshot with an isolated output directory and no user
   configuration, runtime state, invoice files, or ignored build outputs.
2. One deterministic stage pass with a fixed source commit and timestamp,
   followed by a second pass to compare tree and manifest bytes.
3. One static/fixture verifier pass over the staged app layout and receipt,
   plus negative checks for a dirty source, a non-arm64 host, a development
   marker, a package-manifest mismatch, and a tampered manifest.
4. On macOS arm64 only, one `tauri build --bundles app` invocation followed by
   one ad-hoc DMG assembly from that exact App. No product backend launch is
   part of this experiment.

## Stop Condition

Stop at the first source-integrity, allowlist, path-containment, manifest hash,
architecture, compiler, app-layout, receipt, or verifier failure. Do not read
or write Application Support, start `127.0.0.1:8766`, invoke an updater, stop a
monitor, use signing credentials, notarize, create a Sparkle ZIP, upload, publish,
or modify a Release/Feed. Preserve any audit/staging directory for diagnosis;
cleanup may remove only a temporary directory created by the current command.

## Evidence Boundary

The receipt is an audit record, not proof of signing, notarization, updater
compatibility, or product smoke. Internal mode must be explicit and mutually
exclusive with formal notarized verification. A future formal release must use
the separate package/runtime manifest, Developer ID, notarization, Sparkle and
provenance gates.

## Result (2026-08-19)

- The bounded assembly passed from clean source commit
  `1892a52bf5eba4ae3b24720fbc32899a4e6003a0`. It produced one macOS arm64
  internal-alpha `.app`, a same-source ad-hoc `.dmg`, and a schema-4 receipt.
- The independent verifier passed over the worktree copy of all three
  artifacts. The receipt records `core_build_id`
  `9188334bf2d10a7a75d99b04683c946cd34139ba0061d64e20eb33e8c5c91f76`,
  `signature_mode=internal-adhoc`, `updater_enabled=false`, and
  `public_release=false`.
- A separate, bounded post-build smoke used a temporary HOME/state root. The
  packaged launcher reached `127.0.0.1:8766`, reported `ready`, and matched the
  build/package/source identity without reading or writing the real InvoiceHub
  Application Support directory. The smoke terminated only the process group
  started for that sample.
- This result authorizes internal review of the retained artifacts only. It does
  not authorize a public Tag/Release, Feed, updater installation, Developer ID,
  notarization, or a claim of native picker, browser/tray, single-instance,
  monitor-stop, or end-user installation coverage.

## Separate post-build launch-smoke record

| Field | Record |
| --- | --- |
| Hypothesis | The newly built internal-alpha package can start its embedded backend from an isolated temporary state root and expose the expected fixed-port health identity without touching the user's existing state. |
| Decision changed by result | A pass permits retaining the package as a reviewable internal artifact; a failure would block internal handoff and confine repair to launcher, embedded runtime, manifest identity, or startup cleanup. |
| Minimal sample | One arm64 `.app`, one temporary HOME/state root, one fixed-port launch, and one health/identity check. |
| Stop condition | Stop at the first package, port, identity, state-containment, or cleanup failure; do not retry with the real HOME, change the port, or continue into picker/update/install testing. |
| Result | Passed. Health reached `ready`, package/build/source identity matched, the real Application Support directory was untouched, and only the sample's process group was terminated. |
