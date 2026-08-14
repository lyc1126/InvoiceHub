from __future__ import annotations

import argparse
import hashlib
import json
import re
from datetime import datetime, timezone
from pathlib import Path

from invoice_hub.version import API_CONTRACT_VERSION


BUILD_MANIFEST_NAME = "invoice-hub-build.json"
BOOKKEEPING_PROTOCOL_VERSION = "w9-ledger-review-v1"
API_CAPABILITIES = (
    "bookkeeping.review",
    "bookkeeping.executability.v2",
    "bookkeeping.import-batch.v1",
    "bookkeeping.import-finalize.v1",
    "bookkeeping.jierui.facts.v2",
    "bookkeeping.jierui.runner.dry-run.v2",
    "bookkeeping.state-cas.v1",
    "bookkeeping.w9-ledger-review.v1",
    "bookkeeping.mapping-resolution.v1",
    "bookkeeping.targeted-recompute.v1",
    "bookkeeping.migration-cas.v2",
    "costs.internal-scroll",
    "documents",
    "documents.validate-outbound-dir",
    "settings.center.v1",
    "settings.preferences.v1",
    "diagnostics.support-package.v1",
    "invoices.batch-print.v1",
    "invoices.classification.v1",
    "invoices.file-preview.v1",
    "invoices.rename-safe.v1",
    "invoices.selection-summary.v1",
    "macos.strict-build-handshake",
    "monitor.ready-handshake.v1",
    "release.package-identity.v1",
    "server.shutdown-choice.v1",
    "settings.startup-surface.v1",
    "skins.zip-portable",
    "updates.metadata-check.v1",
)
DEVELOPMENT_BUILD_ID = "development"
BUILD_INPUTS = (
    "src",
    "web",
    "scripts/tools/jierui_voucher_import.py",
    "docs/jierui",
    "pyproject.toml",
)


class BuildManifestError(ValueError):
    pass


def _is_build_cache(path: Path, root: Path) -> bool:
    relative = path.relative_to(root)
    return path.name == ".DS_Store" or path.suffix == ".pyc" or "__pycache__" in relative.parts


def deterministic_build_id(root: Path) -> str:
    root = Path(root).resolve()
    files: list[Path] = []
    for name in BUILD_INPUTS:
        candidate = root / name
        if candidate.is_dir():
            files.extend(item for item in candidate.rglob("*") if item.is_file() and not _is_build_cache(item, root))
        elif candidate.is_file():
            files.append(candidate)
        else:
            raise FileNotFoundError(f"build input missing: {candidate}")

    digest = hashlib.sha256()
    for path in sorted(files, key=lambda item: item.relative_to(root).as_posix()):
        relative = path.relative_to(root).as_posix().encode("utf-8")
        content = path.read_bytes()
        digest.update(relative)
        digest.update(b"\0")
        digest.update(str(len(content)).encode("ascii"))
        digest.update(b"\0")
        digest.update(content)
        digest.update(b"\0")
    return digest.hexdigest()


def build_manifest_payload(root: Path, source_commit: str, built_at: str) -> dict:
    return {
        "build_id": deterministic_build_id(root),
        "api_contract_version": API_CONTRACT_VERSION,
        "bookkeeping_protocol_version": BOOKKEEPING_PROTOCOL_VERSION,
        "capabilities": list(API_CAPABILITIES),
        "source_commit": source_commit.strip(),
        "built_at": built_at.strip(),
    }


def write_build_manifest(root: Path, output: Path, source_commit: str, built_at: str | None = None) -> dict:
    timestamp = built_at or datetime.now(timezone.utc).isoformat(timespec="seconds").replace("+00:00", "Z")
    payload = build_manifest_payload(root, source_commit, timestamp)
    output = Path(output)
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    return payload


def load_build_manifest(root: Path, *, required: bool = False) -> dict:
    path = Path(root) / BUILD_MANIFEST_NAME
    fallback = {
        "build_id": DEVELOPMENT_BUILD_ID,
        "api_contract_version": API_CONTRACT_VERSION,
        "bookkeeping_protocol_version": BOOKKEEPING_PROTOCOL_VERSION,
        "capabilities": list(API_CAPABILITIES),
        "source_commit": "",
        "built_at": "",
        "manifest_present": False,
        "manifest_valid": False,
        "manifest_status": "missing",
        "manifest_error": "",
    }
    if not path.is_file():
        if required:
            raise BuildManifestError(f"release build manifest is missing: {path}")
        return fallback
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError, TypeError) as exc:
        if required:
            raise BuildManifestError(f"release build manifest is invalid: {exc}") from exc
        return {**fallback, "manifest_status": "invalid", "manifest_error": str(exc)}
    if not isinstance(payload, dict):
        if required:
            raise BuildManifestError("release build manifest must be a JSON object")
        return {**fallback, "manifest_status": "invalid", "manifest_error": "manifest must be a JSON object"}
    build_id = str(payload.get("build_id") or "").strip()
    contract = str(payload.get("api_contract_version") or "").strip()
    bookkeeping_protocol = str(payload.get("bookkeeping_protocol_version") or "").strip()
    capabilities = payload.get("capabilities")
    capabilities_are_valid = (
        isinstance(capabilities, list)
        and bool(capabilities)
        and all(isinstance(item, str) and bool(item.strip()) for item in capabilities)
    )
    if not build_id or not contract or not bookkeeping_protocol or not capabilities_are_valid:
        error = "release build manifest is missing required identity fields"
        if required:
            raise BuildManifestError(error)
        return {**fallback, "manifest_status": "invalid", "manifest_error": error}
    if required:
        source_commit = str(payload.get("source_commit") or "").strip()
        built_at = str(payload.get("built_at") or "").strip()
        problems: list[str] = []
        if not re.fullmatch(r"[0-9a-f]{64}", build_id):
            problems.append("build_id must be a lowercase SHA-256")
        if contract != API_CONTRACT_VERSION:
            problems.append("api_contract_version does not match this release")
        if bookkeeping_protocol != BOOKKEEPING_PROTOCOL_VERSION:
            problems.append("bookkeeping_protocol_version does not match this release")
        if tuple(capabilities) != API_CAPABILITIES:
            problems.append("capabilities do not match this release")
        if not re.fullmatch(r"[0-9a-f]{40}", source_commit):
            problems.append("source_commit must be a clean 40-character Git SHA")
        if not built_at:
            problems.append("built_at is required")
        if problems:
            raise BuildManifestError("release build manifest is invalid: " + "; ".join(problems))
    return {
        "build_id": build_id,
        "api_contract_version": contract,
        "bookkeeping_protocol_version": bookkeeping_protocol,
        "capabilities": list(capabilities),
        "source_commit": str(payload.get("source_commit") or "").strip(),
        "built_at": str(payload.get("built_at") or "").strip(),
        "manifest_present": True,
        "manifest_valid": True,
        "manifest_status": "valid",
        "manifest_error": "",
    }


def main() -> int:
    parser = argparse.ArgumentParser(description="Generate the deterministic InvoiceHub macOS build manifest.")
    parser.add_argument("--root", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--source-commit", required=True)
    parser.add_argument("--built-at", default="")
    args = parser.parse_args()
    payload = write_build_manifest(
        args.root,
        args.output,
        source_commit=args.source_commit,
        built_at=args.built_at or None,
    )
    print(json.dumps(payload, ensure_ascii=False, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
