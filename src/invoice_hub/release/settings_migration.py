from __future__ import annotations

import argparse
import json
import shutil
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


CONFIG_KEYS = {
    "host",
    "port",
    "watch_dir",
    "outbound_invoice_dir",
    "bookkeeping_root",
    "reference_markup_rate",
    "recent_watch_dirs",
    "recent_outbound_invoice_dirs",
}
PREFERENCE_KEYS = {
    "cost_row_limit",
    "long_path_display",
    "document_export_existing_strategy",
    "system_shutdown_behavior",
    "ocr_candidate_dir",
    "startup_surface",
    "auto_check_updates",
}


class SettingsMigrationError(ValueError):
    pass


def _read_object(path: Path) -> dict[str, Any]:
    try:
        payload = json.loads(path.read_text(encoding="utf-8-sig"))
    except (OSError, UnicodeError, json.JSONDecodeError) as exc:
        raise SettingsMigrationError(f"cannot read JSON object {path}: {exc}") from exc
    if not isinstance(payload, dict):
        raise SettingsMigrationError(f"settings file must contain a JSON object: {path}")
    return payload


def _backup(path: Path) -> Path | None:
    if not path.exists():
        return None
    stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    candidate = path.with_name(f"{path.name}.before-import-{stamp}.bak")
    index = 0
    while candidate.exists():
        index += 1
        candidate = path.with_name(f"{path.name}.before-import-{stamp}-{index}.bak")
    candidate.parent.mkdir(parents=True, exist_ok=True)
    shutil.copy2(path, candidate)
    return candidate


def _write_object(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(path.name + ".tmp")
    temporary.write_text(json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    temporary.replace(path)


def import_settings(old_root: Path, new_root: Path) -> dict[str, Any]:
    old_root = Path(old_root).resolve()
    new_root = Path(new_root).resolve()
    if old_root == new_root:
        raise SettingsMigrationError("old and new package roots must be different")
    source_config = old_root / "config" / "app.local.json"
    target_config = new_root / "config" / "app.local.json"
    if not source_config.is_file():
        raise SettingsMigrationError(f"old local config is missing: {source_config}")
    source = _read_object(source_config)
    target = _read_object(target_config) if target_config.is_file() else {}
    imported_config = {key: source[key] for key in sorted(CONFIG_KEYS) if key in source}
    merged_config = {**target, **imported_config}
    config_backup = _backup(target_config)
    _write_object(target_config, merged_config)

    old_runtime_raw = str(source.get("runtime_dir") or "./运行状态")
    new_runtime_raw = str(merged_config.get("runtime_dir") or "./运行状态")
    old_runtime = Path(old_runtime_raw)
    new_runtime = Path(new_runtime_raw)
    if not old_runtime.is_absolute():
        old_runtime = (old_root / old_runtime).resolve()
    if not new_runtime.is_absolute():
        new_runtime = (new_root / new_runtime).resolve()
    source_preferences = old_runtime / "local_state" / "preferences.json"
    target_preferences = new_runtime / "local_state" / "preferences.json"
    imported_preferences: dict[str, Any] = {}
    preference_backup: Path | None = None
    if source_preferences.is_file():
        source_pref_payload = _read_object(source_preferences)
        target_pref_payload = _read_object(target_preferences) if target_preferences.is_file() else {}
        imported_preferences = {
            key: source_pref_payload[key]
            for key in sorted(PREFERENCE_KEYS)
            if key in source_pref_payload
        }
        if imported_preferences.get("startup_surface") == "desktop":
            imported_preferences["startup_surface"] = "browser"
        preference_backup = _backup(target_preferences)
        _write_object(target_preferences, {**target_pref_payload, **imported_preferences})

    return {
        "ok": True,
        "old_root": str(old_root),
        "new_root": str(new_root),
        "config_path": str(target_config),
        "config_keys": sorted(imported_config),
        "config_backup": str(config_backup) if config_backup else "",
        "preferences_path": str(target_preferences),
        "preference_keys": sorted(imported_preferences),
        "preferences_backup": str(preference_backup) if preference_backup else "",
        "excluded": ["logs", "pid", "sqlite", "cache", "source invoices", "cost outputs", "skins"],
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Import safe settings from an older InvoiceHub portable directory")
    parser.add_argument("--old-root", type=Path, required=True)
    parser.add_argument("--new-root", type=Path, required=True)
    args = parser.parse_args(argv)
    print(json.dumps(import_settings(args.old_root, args.new_root), ensure_ascii=False, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
