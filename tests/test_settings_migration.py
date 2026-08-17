import json
from pathlib import Path

import pytest

from invoice_hub.release.settings_migration import SettingsMigrationError, import_settings


def _write_json(path: Path, payload: object) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False), encoding="utf-8")


def test_import_settings_copies_only_the_allowlist_and_preserves_backups(tmp_path: Path) -> None:
    old_root = tmp_path / "old"
    new_root = tmp_path / "new"
    _write_json(
        old_root / "config" / "app.local.json",
        {
            "host": "127.0.0.1",
            "port": 9876,
            "watch_dir": "D:/synthetic-invoices",
            "runtime_dir": "./old-state",
            "recent_watch_dirs": ["D:/synthetic-invoices"],
            "private_extension": "must-not-cross-package-boundary",
        },
    )
    _write_json(
        old_root / "old-state" / "local_state" / "preferences.json",
        {
            "startup_surface": "desktop",
            "auto_check_updates": False,
            "cost_row_limit": 100,
            "private_extension": "must-not-cross-package-boundary",
        },
    )
    _write_json(
        new_root / "config" / "app.local.json",
        {"runtime_dir": "./new-state", "new_package_only": True},
    )
    _write_json(
        new_root / "new-state" / "local_state" / "preferences.json",
        {"long_path_display": "marquee", "new_package_only": True},
    )
    (old_root / "old-state" / "server.pid").write_text("1234", encoding="ascii")
    (old_root / "invoice.pdf").write_bytes(b"synthetic")

    result = import_settings(old_root, new_root)

    config = json.loads((new_root / "config" / "app.local.json").read_text(encoding="utf-8"))
    assert config == {
        "host": "127.0.0.1",
        "new_package_only": True,
        "port": 9876,
        "recent_watch_dirs": ["D:/synthetic-invoices"],
        "runtime_dir": "./new-state",
        "watch_dir": "D:/synthetic-invoices",
    }
    preferences = json.loads(
        (new_root / "new-state" / "local_state" / "preferences.json").read_text(encoding="utf-8")
    )
    assert preferences == {
        "auto_check_updates": False,
        "cost_row_limit": 100,
        "long_path_display": "marquee",
        "new_package_only": True,
        "startup_surface": "desktop",
    }
    assert Path(result["config_backup"]).is_file()
    assert Path(result["preferences_backup"]).is_file()
    assert not (new_root / "new-state" / "server.pid").exists()
    assert not (new_root / "invoice.pdf").exists()
    assert "private_extension" not in result["config_keys"]
    assert "private_extension" not in result["preference_keys"]


def test_import_settings_preserves_existing_browser_startup_surface(tmp_path: Path) -> None:
    old_root = tmp_path / "old"
    new_root = tmp_path / "new"
    _write_json(
        old_root / "config" / "app.local.json",
        {"runtime_dir": "./old-state"},
    )
    _write_json(
        old_root / "old-state" / "local_state" / "preferences.json",
        {"startup_surface": "browser"},
    )
    _write_json(
        new_root / "config" / "app.local.json",
        {"runtime_dir": "./new-state"},
    )

    result = import_settings(old_root, new_root)

    preferences = json.loads(
        (new_root / "new-state" / "local_state" / "preferences.json").read_text(encoding="utf-8")
    )
    assert preferences == {"startup_surface": "browser"}
    assert result["preference_keys"] == ["startup_surface"]


def test_import_settings_rejects_same_root_and_missing_config(tmp_path: Path) -> None:
    with pytest.raises(SettingsMigrationError, match="must be different"):
        import_settings(tmp_path, tmp_path)
    with pytest.raises(SettingsMigrationError, match="missing"):
        import_settings(tmp_path / "missing", tmp_path / "new")
