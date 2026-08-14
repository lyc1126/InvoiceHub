from pathlib import Path

from invoice_hub.services.skins import SkinService
from invoice_hub.targets import ensure_runtime_layout, load_config, target_profile_for


def test_runtime_layout_keeps_cost_outputs_in_watch_dir(tmp_path: Path) -> None:
    config_path = tmp_path / "config" / "app.local.json"
    config_path.parent.mkdir()
    config_path.write_text(
        '{"host":"127.0.0.1","port":8766,"watch_dir":"./发票文件","runtime_dir":"./runtime"}',
        encoding="utf-8",
    )
    config = load_config(tmp_path, str(config_path))
    layout, notes = ensure_runtime_layout(config)
    profile = target_profile_for(config)

    assert layout.runtime_dir == tmp_path / "runtime"
    assert Path(profile.watch_dir) == tmp_path / "发票文件"
    assert Path(profile.workspace_dir).is_dir()
    assert notes == []


def test_runtime_layout_quarantines_file_conflict(tmp_path: Path) -> None:
    (tmp_path / "runtime").write_text("conflict", encoding="utf-8")
    config = load_config(tmp_path)
    layout, notes = ensure_runtime_layout(config)

    assert layout.runtime_dir.is_dir()
    assert any("conflicting file" in note for note in notes)


def test_skin_storage_uses_runtime_local_state_not_watch_dir(tmp_path: Path) -> None:
    config = load_config(tmp_path)
    layout, _notes = ensure_runtime_layout(config)
    profile = target_profile_for(config)
    service = SkinService(layout)

    paths = {key: Path(value).resolve() for key, value in service.storage_paths().items()}

    assert paths["root"].is_relative_to(layout.runtime_dir.resolve())
    assert paths["imported"].is_relative_to(paths["root"])
    assert paths["state"].is_relative_to(paths["root"])
    assert not paths["root"].is_relative_to(Path(profile.watch_dir).resolve())
