from __future__ import annotations

import hashlib
import importlib.util
import json
import shutil
import stat
import sys
from pathlib import Path

import pytest


ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "scripts/dev/tauri_dev_app.py"


def _load_module():
    spec = importlib.util.spec_from_file_location("tauri_dev_app_test_module", SCRIPT)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def _copy_source_tree(tmp_path: Path) -> Path:
    root = tmp_path / "InvoiceHub"
    root.mkdir()
    for relative in (
        "src",
        "web",
        "docs/jierui",
        "scripts/tools/jierui_voucher_import.py",
        "pyproject.toml",
        "src-tauri/tauri.conf.json",
        "src-tauri/tauri.dev.conf.json",
    ):
        source = ROOT / relative
        target = root / relative
        target.parent.mkdir(parents=True, exist_ok=True)
        if source.is_dir():
            shutil.copytree(source, target)
        else:
            shutil.copy2(source, target)
    return root


def _venv_python(tmp_path: Path) -> Path:
    venv = tmp_path / "tools" / ".venv"
    executable = venv / "bin/python"
    executable.parent.mkdir(parents=True)
    (venv / "pyvenv.cfg").write_text("home = test\n", encoding="utf-8")
    try:
        executable.symlink_to(Path(sys.executable))
    except OSError:
        shutil.copy2(sys.executable, executable)
        executable.chmod(executable.stat().st_mode | stat.S_IXUSR)
    return executable


def _tree_digest(root: Path) -> str:
    digest = hashlib.sha256()
    for path in sorted(root.rglob("*"), key=lambda item: item.as_posix()):
        relative = path.relative_to(root).as_posix().encode("utf-8")
        digest.update(relative)
        digest.update(b"\0")
        digest.update(b"d" if path.is_dir() else b"f")
        digest.update(b"\0")
        if path.is_file():
            digest.update(str(path.stat().st_mode & 0o777).encode("ascii"))
            digest.update(b"\0")
            digest.update(path.read_bytes())
            digest.update(b"\0")
    return digest.hexdigest()


def test_stage_creates_a_development_manifest_and_allowlisted_core(tmp_path: Path) -> None:
    module = _load_module()
    root = _copy_source_tree(tmp_path)
    python = _venv_python(tmp_path)
    (root / "config").mkdir()
    (root / "config/app.local.json").write_text('{"watch_dir":"private"}', encoding="utf-8")
    (root / "runtime").mkdir()
    (root / "runtime/server.pid").write_text("123", encoding="utf-8")
    (root / "发票文件").mkdir()
    (root / "发票文件/private.pdf").write_bytes(b"business-data")
    cache = root / "src/invoice_hub/__pycache__"
    cache.mkdir(exist_ok=True)
    (cache / "stale.pyc").write_bytes(b"cache")

    result = module.stage(
        root,
        python,
        source_commit="a" * 40,
        built_at="2026-08-16T00:00:00Z",
    )

    host = json.loads(result.host_manifest_path.read_text(encoding="utf-8"))
    build = json.loads((result.core_root / "invoice-hub-build.json").read_text(encoding="utf-8"))
    assert host["schema_version"] == 3
    assert host["profile"] == "development"
    assert host["updater"] == {"enabled": False}
    assert host["backend_program"] == "invoice-hub-dev-launcher.sh"
    assert host["backend_root"] == "invoice-hub-core"
    assert host["backend_args"] == []
    assert host["backend_program_sha256"] == hashlib.sha256(
        result.launcher_path.read_bytes()
    ).hexdigest()
    assert host["expected_identity"]["build_id"] == build["build_id"]
    assert host["expected_identity"]["package_id"] == "development"
    assert host["expected_identity"]["package_type"] == "source"
    assert host["expected_identity"]["platform"] == "macos"
    assert host["expected_identity"]["architecture"] == "arm64"
    assert "config_path" not in host["expected_identity"]
    assert "runtime_dir" not in host["expected_identity"]

    assert (result.core_root / "src/invoice_hub/api/main.py").is_file()
    assert (result.core_root / "web").is_dir()
    assert (result.core_root / "docs/jierui").is_dir()
    assert (result.core_root / "scripts/tools/jierui_voucher_import.py").is_file()
    for forbidden in ("config", "runtime", "发票文件", ".venv", "invoice-hub-package.json"):
        assert not (result.core_root / forbidden).exists()
    assert not any(path.name == "__pycache__" for path in result.core_root.rglob("*"))
    assert not any(path.suffix == ".pyc" for path in result.core_root.rglob("*"))

    launcher = result.launcher_path.read_text(encoding="utf-8")
    assert str(python) in launcher
    assert 'export PYTHONPATH="$CORE_ROOT/src"' in launcher
    assert 'exec "$PYTHON_EXECUTABLE" -m invoice_hub.api.main "$@"' in launcher
    assert "command -v python" not in launcher


def test_stage_is_byte_stable_when_the_input_commit_and_timestamp_are_fixed(tmp_path: Path) -> None:
    module = _load_module()
    root = _copy_source_tree(tmp_path)
    python = _venv_python(tmp_path)
    kwargs = {"source_commit": "b" * 40, "built_at": "2026-08-16T00:00:00Z"}

    first = module.stage(root, python, **kwargs)
    first_digest = _tree_digest(first.staging_dir)
    first_manifest_sha = first.manifest_sha256
    first_manifest_bytes = first.host_manifest_path.read_bytes()
    second = module.stage(root, python, **kwargs)

    assert _tree_digest(second.staging_dir) == first_digest
    assert second.manifest_sha256 == first_manifest_sha
    assert second.host_manifest_path.read_bytes() == first_manifest_bytes


def test_implicit_build_metadata_marks_dirty_worktrees(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    module = _load_module()
    head = "d" * 40

    def fake_git_output(_root: Path, *args: str) -> str:
        if args == ("rev-parse", "HEAD"):
            return head
        assert args == ("show", "-s", "--format=%cI", "HEAD")
        return "2026-08-17T00:00:00Z"

    monkeypatch.setattr(module, "_git_output", fake_git_output)
    monkeypatch.setattr(module, "_working_tree_is_dirty", lambda _root: False)
    assert module._build_metadata(tmp_path, None, None) == (head, "2026-08-17T00:00:00Z")

    monkeypatch.setattr(module, "_working_tree_is_dirty", lambda _root: True)
    assert module._build_metadata(tmp_path, None, None) == (
        f"{head}+dirty",
        "2026-08-17T00:00:00Z",
    )


def test_stage_rejects_non_venv_and_non_executable_python_paths(tmp_path: Path) -> None:
    module = _load_module()
    with pytest.raises(module.TauriDevAppError, match="absolute"):
        module.validate_venv_python(Path("python"))

    ordinary = tmp_path / "ordinary/bin/python"
    ordinary.parent.mkdir(parents=True)
    ordinary.write_text("#!/bin/sh\nexit 0\n", encoding="utf-8")
    ordinary.chmod(0o755)
    with pytest.raises(module.TauriDevAppError, match="virtual environment"):
        module.validate_venv_python(ordinary)

    venv = tmp_path / "broken/.venv"
    executable = venv / "bin/python"
    executable.parent.mkdir(parents=True)
    (venv / "pyvenv.cfg").write_text("home = test\n", encoding="utf-8")
    executable.write_text("not executable\n", encoding="utf-8")
    with pytest.raises(module.TauriDevAppError, match="executable"):
        module.validate_venv_python(executable)


def test_development_overlay_is_app_only_and_base_config_stays_disabled() -> None:
    base = json.loads((ROOT / "src-tauri/tauri.conf.json").read_text(encoding="utf-8"))
    overlay = json.loads((ROOT / "src-tauri/tauri.dev.conf.json").read_text(encoding="utf-8"))

    assert base["bundle"]["active"] is False
    assert base["bundle"]["macOS"]["minimumSystemVersion"] == "13.0"
    assert overlay["bundle"]["active"] is True
    assert overlay["bundle"]["targets"] == ["app"]
    assert overlay["bundle"]["resources"] == {
        ".dev-staging/invoice-hub-core": "invoice-hub-core",
        ".dev-staging/invoice-hub-dev-launcher.sh": "invoice-hub-dev-launcher.sh",
        ".dev-staging/invoicehub-desktop-host.json": "invoicehub-desktop-host.json",
    }


def test_build_command_injects_the_manifest_hash_and_requests_only_the_app(tmp_path: Path) -> None:
    module = _load_module()
    root = _copy_source_tree(tmp_path)
    pnpm = tmp_path / "tooling/pnpm"
    pnpm.parent.mkdir(parents=True)
    pnpm.write_text("#!/bin/sh\nexit 0\n", encoding="utf-8")
    pnpm.chmod(0o755)

    command, environment = module.build_command(root, pnpm, "c" * 64)

    assert command == [
        str(pnpm),
        "exec",
        "tauri",
        "build",
        "--config",
        str(root / "src-tauri/tauri.dev.conf.json"),
        "--bundles",
        "app",
    ]
    assert environment["INVOICE_HUB_BUNDLE_MANIFEST_SHA256"] == "c" * 64


def test_build_gate_rejects_non_macos_arm64_hosts() -> None:
    module = _load_module()
    with pytest.raises(module.TauriDevAppError, match="macOS arm64"):
        module._assert_macos_arm64("linux", "arm64")
    with pytest.raises(module.TauriDevAppError, match="macOS arm64"):
        module._assert_macos_arm64("darwin", "x86_64")
    module._assert_macos_arm64("darwin", "arm64")
