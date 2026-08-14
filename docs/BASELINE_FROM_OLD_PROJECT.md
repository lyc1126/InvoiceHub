# Legacy Capability Baseline

This document records product behavior retained from a private predecessor. It
does not identify the predecessor's workspace, customers, projects, or source
documents.

The public implementation retains:

- `v1 localhost` operation with one active `TargetProfile`.
- Compatible `/api/v1` endpoints and ordinary CSV/XLSX summaries in the
  configured workspace.
- Cost detail, workbook, and reference-status outputs in the active
  `watch_dir`.
- Independent monitoring that continues after a browser window closes.
- Explicit separation between stopping the localhost UI and stopping the
  monitor.
- Background startup synchronization, duplicate-invoice handling, and a
  manual-edit synchronization guard.
- An OCR entry point without an OCR runtime in the normal desktop package.

The predecessor's data and historical validation material are private and are
not a source of public test fixtures or release evidence.
