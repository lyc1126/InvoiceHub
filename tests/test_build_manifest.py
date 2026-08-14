import json
import os
import re
import subprocess
import sys
from pathlib import Path

import pytest

from invoice_hub.release.build_manifest import (
    API_CAPABILITIES,
    API_CONTRACT_VERSION,
    BOOKKEEPING_PROTOCOL_VERSION,
    DEVELOPMENT_BUILD_ID,
    deterministic_build_id,
    load_build_manifest,
    write_build_manifest,
)


def test_current_macos_contract_and_protocol_are_locked() -> None:
    assert API_CONTRACT_VERSION == "2026-08-02-release-update-v1"
    assert BOOKKEEPING_PROTOCOL_VERSION == "w9-ledger-review-v1"
    assert {
        "invoices.classification.v1",
        "invoices.file-preview.v1",
        "invoices.batch-print.v1",
        "invoices.selection-summary.v1",
        "monitor.ready-handshake.v1",
        "release.package-identity.v1",
        "server.shutdown-choice.v1",
        "settings.startup-surface.v1",
        "updates.metadata-check.v1",
    } <= set(API_CAPABILITIES)


def _build_root(tmp_path: Path) -> Path:
    (tmp_path / "src").mkdir()
    (tmp_path / "web").mkdir()
    (tmp_path / "scripts" / "tools").mkdir(parents=True)
    (tmp_path / "docs" / "jierui").mkdir(parents=True)
    (tmp_path / "src" / "module.py").write_text("value = 1\n", encoding="utf-8")
    (tmp_path / "web" / "index.html").write_text("<h1>InvoiceHub</h1>\n", encoding="utf-8")
    (tmp_path / "scripts" / "tools" / "jierui_voucher_import.py").write_text("MODE = 'dry-run'\n", encoding="utf-8")
    (tmp_path / "docs" / "jierui" / "voucher-import-template.facts.json").write_text("{}\n", encoding="utf-8")
    (tmp_path / "pyproject.toml").write_text("[project]\nname = 'invoice-hub'\n", encoding="utf-8")
    return tmp_path


def test_build_id_is_deterministic_and_tracks_packaged_content(tmp_path: Path) -> None:
    root = _build_root(tmp_path)

    first = deterministic_build_id(root)
    second = deterministic_build_id(root)
    (root / "web" / "index.html").write_text("<h1>InvoiceHub current</h1>\n", encoding="utf-8")

    assert first == second
    assert deterministic_build_id(root) != first


def test_build_id_tracks_jierui_facts_and_runner(tmp_path: Path) -> None:
    root = _build_root(tmp_path)
    original = deterministic_build_id(root)
    (root / "docs" / "jierui" / "voucher-import-template.facts.json").write_text('{"schema_version": 2}\n', encoding="utf-8")
    facts_changed = deterministic_build_id(root)
    (root / "scripts" / "tools" / "jierui_voucher_import.py").write_text("MODE = 'w8'\n", encoding="utf-8")

    assert facts_changed != original
    assert deterministic_build_id(root) != facts_changed


def test_build_id_ignores_local_python_and_finder_caches(tmp_path: Path) -> None:
    root = _build_root(tmp_path)
    expected = deterministic_build_id(root)
    cache = root / "src" / "package" / "__pycache__"
    cache.mkdir(parents=True)
    (cache / "module.cpython-314.pyc").write_bytes(b"local bytecode")
    (root / "web" / ".DS_Store").write_bytes(b"finder metadata")

    assert deterministic_build_id(root) == expected


def test_build_id_ignores_windows_only_launchers_and_root_docs(tmp_path: Path) -> None:
    root = _build_root(tmp_path)
    expected = deterministic_build_id(root)
    (root / "scripts" / "windows").mkdir(parents=True)
    (root / "scripts" / "windows" / "start.ps1").write_text("Write-Host start\n", encoding="utf-8")
    (root / "README.md").write_text("Windows instructions\n", encoding="utf-8")

    assert deterministic_build_id(root) == expected


def test_manifest_write_and_missing_fallback(tmp_path: Path) -> None:
    root = _build_root(tmp_path)
    missing = load_build_manifest(root)

    assert missing["manifest_present"] is False
    assert missing["build_id"] == DEVELOPMENT_BUILD_ID
    assert missing["api_contract_version"] == API_CONTRACT_VERSION
    assert missing["bookkeeping_protocol_version"] == BOOKKEEPING_PROTOCOL_VERSION
    assert missing["capabilities"] == list(API_CAPABILITIES)

    output = root / "invoice-hub-build.json"
    written = write_build_manifest(root, output, "abc123", "2026-06-18T00:00:00Z")
    loaded = load_build_manifest(root)

    assert loaded["manifest_present"] is True
    assert loaded["build_id"] == written["build_id"]
    assert loaded["bookkeeping_protocol_version"] == BOOKKEEPING_PROTOCOL_VERSION
    assert loaded["capabilities"] == written["capabilities"] == list(API_CAPABILITIES)
    assert loaded["source_commit"] == "abc123"
    payload = json.loads(output.read_text(encoding="utf-8"))
    assert payload["built_at"] == "2026-06-18T00:00:00Z"
    assert payload["bookkeeping_protocol_version"] == BOOKKEEPING_PROTOCOL_VERSION
    assert "bookkeeping.w9-ledger-review.v1" in payload["capabilities"]
    assert "bookkeeping.mapping-resolution.v1" in payload["capabilities"]
    assert "bookkeeping.targeted-recompute.v1" in payload["capabilities"]
    assert "bookkeeping.migration-cas.v2" in payload["capabilities"]
    assert "settings.center.v1" in payload["capabilities"]
    assert "settings.preferences.v1" in payload["capabilities"]
    assert "diagnostics.support-package.v1" in payload["capabilities"]
    assert "invoices.classification.v1" in payload["capabilities"]
    assert "invoices.file-preview.v1" in payload["capabilities"]
    assert "invoices.batch-print.v1" in payload["capabilities"]
    assert "invoices.rename-safe.v1" in payload["capabilities"]
    assert "invoices.selection-summary.v1" in payload["capabilities"]
    assert "monitor.ready-handshake.v1" in payload["capabilities"]
    assert "server.shutdown-choice.v1" in payload["capabilities"]


def test_manifest_missing_bookkeeping_protocol_falls_back_closed(tmp_path: Path) -> None:
    root = _build_root(tmp_path)
    (root / "invoice-hub-build.json").write_text(
        json.dumps({"build_id": "legacy", "api_contract_version": "legacy"}),
        encoding="utf-8",
    )

    loaded = load_build_manifest(root)

    assert loaded["manifest_present"] is False
    assert loaded["build_id"] == DEVELOPMENT_BUILD_ID
    assert loaded["bookkeeping_protocol_version"] == BOOKKEEPING_PROTOCOL_VERSION
    assert loaded["capabilities"] == list(API_CAPABILITIES)


def test_manifest_missing_or_invalid_capabilities_falls_back_closed(tmp_path: Path) -> None:
    root = _build_root(tmp_path)
    manifest_path = root / "invoice-hub-build.json"
    base = {
        "build_id": "build-123",
        "api_contract_version": API_CONTRACT_VERSION,
        "bookkeeping_protocol_version": BOOKKEEPING_PROTOCOL_VERSION,
        "source_commit": "abc123",
        "built_at": "2026-07-29T00:00:00Z",
    }

    for invalid in (None, [], "documents", ["documents", ""]):
        payload = dict(base)
        if invalid is not None:
            payload["capabilities"] = invalid
        manifest_path.write_text(json.dumps(payload), encoding="utf-8")

        loaded = load_build_manifest(root)

        assert loaded["manifest_present"] is False
        assert loaded["build_id"] == DEVELOPMENT_BUILD_ID
        assert loaded["capabilities"] == list(API_CAPABILITIES)

    manifest_path.write_text("[]", encoding="utf-8")
    assert load_build_manifest(root)["manifest_present"] is False


def test_macos_build_only_packages_shared_web_without_touching_runtime() -> None:
    script = (Path(__file__).resolve().parents[1] / "macos" / "InvoiceHubMac" / "script" / "build_and_run.sh").read_text(encoding="utf-8")

    assert 'build|build-only|--build-only)' in script
    assert 'if [[ "$BUILD_ONLY" != "true" ]]; then' in script
    assert 'ditto "$REPO_ROOT/web" "$APP_RESOURCES/invoice-hub-core/web"' in script
    assert "fitz, PIL" in script
    assert "fitz, PIL, watchdog" not in script
    assert '"http://127.0.0.1:$PORT/settings"' in script
    assert '"http://127.0.0.1:$PORT/openapi.json"' in script
    assert '"/api/v1/preferences"' in script
    assert '"/api/v1/about"' in script
    assert '"/api/v1/update/check"' in script
    assert '"/api/v1/diagnostics/config-health"' in script
    assert '"http://127.0.0.1:$PORT/api/v1/documents/state"' not in script
    assert '"http://127.0.0.1:$PORT/api/v1/bookkeeping/state"' not in script
    curl_lines = [line for line in script.splitlines() if "/usr/bin/curl" in line]
    assert curl_lines
    assert all("--connect-timeout" in line and "--max-time" in line for line in curl_lines)
    assert '"bookkeeping_protocol_version": manifest["bookkeeping_protocol_version"]' in script
    assert '"invoices.classification.v1"' in script
    assert '"invoices.file-preview.v1"' in script
    assert '"invoices.batch-print.v1"' in script
    assert '"invoices.selection-summary.v1"' in script
    assert '"monitor.ready-handshake.v1"' in script
    assert '"server.shutdown-choice.v1"' in script
    assert 'health.get("ok") is not True' in script
    assert 'health.get("build_manifest_present") is not True' in script
    assert 'required_api_contract_version = "2026-08-02-release-update-v1"' in script
    assert 'health.get("package_manifest_present") is not True' in script
    assert '"/api/v1/invoices/preview-jobs"' in script
    assert '"/api/v1/invoices/preview-jobs/{job_id}/keep-alive"' in script
    assert '"/api/v1/invoices/print-jobs"' in script
    assert '"/invoices/print/{job_id}"' in script
    assert '"/api/v1/invoices/preview-jobs": "post"' in script
    assert '"/api/v1/invoices/print-jobs": "post"' in script
    assert "verify missing API operations" in script
    assert "manifest_capabilities == health_capabilities == required_capabilities" in script
    assert 'SOURCE_COMMIT="${SOURCE_COMMIT}+dirty"' in script
    assert '/usr/bin/open -n -F "$APP_BUNDLE"' in script
    assert 'echo "$APP_BUNDLE"' in script
    assert "build-only|run|--debug" in script


def _macos_identity_probe_script(tmp_path: Path) -> Path:
    script = (Path(__file__).resolve().parents[1] / "macos" / "InvoiceHubMac" / "script" / "build_and_run.sh").read_text(encoding="utf-8")
    marker = "\nstop_verified_server() {"
    assert marker in script
    definitions = script.split(marker, maxsplit=1)[0]
    probe = tmp_path / "identity-probe.sh"
    probe.write_text(
        definitions + '\nCONFIG_PATH="$1"\nis_current_invoicehub_server "$2"\n',
        encoding="utf-8",
    )
    return probe


def _sleeping_module_root(tmp_path: Path, module: str) -> Path:
    root = tmp_path / ("module-" + module.replace(".", "-"))
    parts = module.split(".")
    package_path = root
    for package in parts[:-1]:
        package_path /= package
        package_path.mkdir(parents=True, exist_ok=True)
        (package_path / "__init__.py").write_text("", encoding="utf-8")
    (package_path / f"{parts[-1]}.py").write_text(
        "import time\ntime.sleep(30)\n",
        encoding="utf-8",
    )
    return root


def _probe_macos_server_identity(
    probe: Path,
    expected_config: str,
    process_arguments: list[str],
    *,
    module_root: Path | None = None,
) -> bool:
    environment = os.environ.copy()
    if module_root is not None:
        environment["PYTHONPATH"] = str(module_root)
    process = subprocess.Popen(
        ["/usr/bin/python3", *process_arguments],
        cwd=module_root,
        env=environment,
    )
    try:
        completed = subprocess.run(
            ["/bin/bash", str(probe), expected_config, str(process.pid)],
            check=False,
            capture_output=True,
            text=True,
            timeout=10,
        )
        return completed.returncode == 0
    finally:
        process.terminate()
        try:
            process.wait(timeout=3)
        except subprocess.TimeoutExpired:
            process.kill()
            process.wait(timeout=3)


@pytest.mark.skipif(
    sys.platform != "darwin" or not Path("/usr/bin/python3").exists(),
    reason="Darwin KERN_PROCARGS2 and the system Python bridge are required",
)
def test_macos_server_identity_uses_exact_module_and_config_argv(tmp_path: Path) -> None:
    probe = _macos_identity_probe_script(tmp_path)
    expected_config = str(tmp_path / "Invoice Hub 配置" / "app.local.json")
    module = "invoice_hub.api.main"
    module_root = _sleeping_module_root(tmp_path, module)

    assert _probe_macos_server_identity(
        probe,
        expected_config,
        ["-m", module, "--config", expected_config],
        module_root=module_root,
    )
    assert not _probe_macos_server_identity(
        probe,
        expected_config,
        ["-c", "import time; time.sleep(30)", "-m", module, "--config", expected_config],
    )
    for actual_config in (expected_config + ".backup", "spoof-prefix" + expected_config):
        assert not _probe_macos_server_identity(
            probe,
            expected_config,
            ["-m", module, "--config", actual_config],
            module_root=module_root,
        )
    for impersonator in ("invoice_hub.api.main.spoof", "spoof.invoice_hub.api.main"):
        impersonator_root = _sleeping_module_root(tmp_path, impersonator)
        assert not _probe_macos_server_identity(
            probe,
            expected_config,
            ["-m", impersonator, "--config", expected_config],
            module_root=impersonator_root,
        )
    assert not _probe_macos_server_identity(
        probe,
        expected_config,
        ["-m", module, "--config", expected_config, "--config", expected_config],
        module_root=module_root,
    )
    assert not _probe_macos_server_identity(
        probe,
        expected_config,
        ["-m", module, "--config", expected_config, f"--config={expected_config}"],
        module_root=module_root,
    )
    unexpected_config = expected_config + ".unexpected"
    for bypass_arguments in (
        ["--config", expected_config, "--c", unexpected_config],
        ["--config", expected_config, f"--c={unexpected_config}"],
        ["--config", expected_config, "--conf", unexpected_config],
        ["--config", expected_config, f"--conf={unexpected_config}"],
        ["--config", expected_config, "--confi", unexpected_config],
        ["--config", expected_config, f"--confi={unexpected_config}"],
    ):
        assert not _probe_macos_server_identity(
            probe,
            expected_config,
            ["-m", module, *bypass_arguments],
            module_root=module_root,
        )


def test_macos_server_identity_requires_real_module_execution_mode() -> None:
    script = (Path(__file__).resolve().parents[1] / "macos" / "InvoiceHubMac" / "script" / "build_and_run.sh").read_text(encoding="utf-8")

    assert 'arguments[1:3] != ["-m", "invoice_hub.api.main"]' in script
    assert "len(config_indexes) != 1" in script
    assert "is_config_option_variant" in script
    assert "has_exact_pair" not in script


def _macos_verify_python_source() -> str:
    script = (Path(__file__).resolve().parents[1] / "macos" / "InvoiceHubMac" / "script" / "build_and_run.sh").read_text(encoding="utf-8")
    start_marker = "  \"$BACKEND_PYTHON\" -c '\n"
    end_marker = "\n' \"$APP_RESOURCES/invoice-hub-core/invoice-hub-build.json\""
    start = script.index(start_marker) + len(start_marker)
    end = script.index(end_marker, start)
    return script[start:end]


def _run_macos_verify_payloads(
    tmp_path: Path,
    manifest: dict,
    health: dict,
    openapi_payload: dict | None = None,
) -> subprocess.CompletedProcess[str]:
    manifest_path = tmp_path / "manifest.json"
    package_path = tmp_path / "package.json"
    health_path = tmp_path / "health.json"
    openapi_path = tmp_path / "openapi.json"
    config_path = tmp_path / "Application Support" / "config" / "app.local.json"
    runtime_path = tmp_path / "Application Support" / "runtime"
    manifest_path.write_text(json.dumps(manifest), encoding="utf-8")
    package = {
        "schema_version": 1,
        "package_id": "com.invoicehub.macos.arm64.dmg",
        "product_version": "0.3.0-alpha.1",
        "platform": "macos",
        "architecture": "arm64",
        "package_type": "dmg",
        "python_version": "3.14.6",
        "dependency_lock_sha256": "c" * 64,
        "update_channel": "alpha",
        "update_feed_url": "https://lyc1126.github.io/InvoiceHub/updates/alpha/latest.json",
        "allowed_update_hosts": [],
        "core_build_id": manifest["build_id"],
        "source_commit": "b" * 40,
    }
    package_path.write_text(json.dumps(package), encoding="utf-8")
    health_path.write_text(json.dumps(health), encoding="utf-8")
    if openapi_payload is None:
        required_operations = (
            ("get", "/api/v1/documents/state"),
            ("get", "/api/v1/bookkeeping/state"),
            ("get", "/api/v1/settings"),
            ("get", "/api/v1/preferences"),
            ("get", "/api/v1/about"),
            ("post", "/api/v1/update/check"),
            ("get", "/api/v1/diagnostics/config-health"),
            ("get", "/api/v1/skins"),
            ("post", "/api/v1/invoices/selection-summary"),
            ("post", "/api/v1/invoices/preview-jobs"),
            ("get", "/api/v1/invoices/preview-jobs/{job_id}/files/{file_number}/pages/{page_number}"),
            ("get", "/api/v1/invoices/preview-jobs/{job_id}/files/{file_number}/text"),
            ("post", "/api/v1/invoices/preview-jobs/{job_id}/keep-alive"),
            ("post", "/api/v1/invoices/preview-jobs/{job_id}/files/{file_number}/open-file"),
            ("post", "/api/v1/invoices/preview-jobs/{job_id}/files/{file_number}/open-location"),
            ("post", "/api/v1/invoices/print-jobs"),
            ("get", "/api/v1/invoices/print-jobs/{job_id}/pages/{page_number}"),
            ("get", "/invoices/print/{job_id}"),
            ("post", "/api/v1/server/shutdown"),
        )
        openapi_payload = {
            "paths": {
                path: {method: {}}
                for method, path in required_operations
            }
        }
    openapi_path.write_text(json.dumps(openapi_payload), encoding="utf-8")
    return subprocess.run(
        [
            sys.executable,
            "-c",
            _macos_verify_python_source(),
            str(manifest_path),
            str(package_path),
            str(health_path),
            str(openapi_path),
            str(config_path),
            str(runtime_path),
        ],
        check=False,
        capture_output=True,
        text=True,
        timeout=10,
    )


def test_macos_verify_requires_health_truth_and_exact_capability_sets(tmp_path: Path) -> None:
    assert "'" not in _macos_verify_python_source()
    config_path = tmp_path / "Application Support" / "config" / "app.local.json"
    runtime_path = tmp_path / "Application Support" / "runtime"
    manifest = {
        "build_id": "build-123",
        "api_contract_version": API_CONTRACT_VERSION,
        "bookkeeping_protocol_version": BOOKKEEPING_PROTOCOL_VERSION,
        "capabilities": list(API_CAPABILITIES),
    }
    health = {
        "ok": True,
        "pid": 123,
        "config_path": str(config_path.resolve()),
        "runtime_dir": str(runtime_path.resolve()),
        "build_id": manifest["build_id"],
        "api_contract_version": manifest["api_contract_version"],
        "bookkeeping_protocol_version": manifest["bookkeeping_protocol_version"],
        "capabilities": list(API_CAPABILITIES),
        "build_manifest_present": True,
        "build_manifest_valid": True,
        "product_version": "0.3.0-alpha.1",
        "package_id": "com.invoicehub.macos.arm64.dmg",
        "platform": "macos",
        "architecture": "arm64",
        "package_type": "dmg",
        "package_manifest_present": True,
        "package_manifest_valid": True,
    }

    accepted = _run_macos_verify_payloads(tmp_path, manifest, health)
    assert accepted.returncode == 0, accepted.stderr

    unhealthy = dict(health, ok=False)
    rejected = _run_macos_verify_payloads(tmp_path, manifest, unhealthy)
    assert rejected.returncode != 0
    assert "health.ok is not true" in rejected.stderr

    unmanifested = dict(health, build_manifest_present=False)
    rejected = _run_macos_verify_payloads(tmp_path, manifest, unmanifested)
    assert rejected.returncode != 0
    assert "build_manifest_present is not true" in rejected.stderr

    extra_capabilities = list(API_CAPABILITIES) + ["unexpected.extra"]
    extra_manifest = dict(manifest, capabilities=extra_capabilities)
    extra_health = dict(health, capabilities=extra_capabilities)
    rejected = _run_macos_verify_payloads(tmp_path, extra_manifest, extra_health)
    assert rejected.returncode != 0
    assert "capability set mismatch" in rejected.stderr

    invalid_health = dict(health, capabilities=list(API_CAPABILITIES) + [" "])
    rejected = _run_macos_verify_payloads(tmp_path, manifest, invalid_health)
    assert rejected.returncode != 0
    assert "invalid health capability value" in rejected.stderr

    invalid_manifest = dict(manifest, capabilities=list(API_CAPABILITIES) + [42])
    rejected = _run_macos_verify_payloads(tmp_path, invalid_manifest, health)
    assert rejected.returncode != 0
    assert "invalid manifest capability value" in rejected.stderr

    matching_legacy_manifest = dict(manifest, api_contract_version="legacy-but-matching")
    matching_legacy_health = dict(health, api_contract_version="legacy-but-matching")
    rejected = _run_macos_verify_payloads(tmp_path, matching_legacy_manifest, matching_legacy_health)
    assert rejected.returncode != 0
    assert "unsupported manifest API contract" in rejected.stderr

    legacy_health = dict(health, api_contract_version="legacy-but-matching")
    rejected = _run_macos_verify_payloads(tmp_path, manifest, legacy_health)
    assert rejected.returncode != 0
    assert "unsupported backend API contract" in rejected.stderr

    wrong_method_openapi = {
        "paths": {
            "/api/v1/documents/state": {"get": {}},
            "/api/v1/bookkeeping/state": {"get": {}},
            "/api/v1/settings": {"get": {}},
            "/api/v1/preferences": {"get": {}},
            "/api/v1/about": {"get": {}},
            "/api/v1/update/check": {"post": {}},
            "/api/v1/diagnostics/config-health": {"get": {}},
            "/api/v1/skins": {"get": {}},
            "/api/v1/invoices/selection-summary": {"post": {}},
            "/api/v1/invoices/preview-jobs": {"post": {}},
            "/api/v1/invoices/preview-jobs/{job_id}/files/{file_number}/pages/{page_number}": {"get": {}},
            "/api/v1/invoices/preview-jobs/{job_id}/files/{file_number}/text": {"get": {}},
            "/api/v1/invoices/preview-jobs/{job_id}/keep-alive": {"post": {}},
            "/api/v1/invoices/preview-jobs/{job_id}/files/{file_number}/open-file": {"post": {}},
            "/api/v1/invoices/preview-jobs/{job_id}/files/{file_number}/open-location": {"post": {}},
            "/api/v1/invoices/print-jobs": {"get": {}},
            "/api/v1/invoices/print-jobs/{job_id}/pages/{page_number}": {"get": {}},
            "/invoices/print/{job_id}": {"get": {}},
            "/api/v1/server/shutdown": {"post": {}},
        }
    }
    rejected = _run_macos_verify_payloads(
        tmp_path,
        manifest,
        health,
        openapi_payload=wrong_method_openapi,
    )
    assert rejected.returncode != 0
    assert "verify missing API operations" in rejected.stderr
    assert "POST /api/v1/invoices/print-jobs" in rejected.stderr


def test_macos_run_script_cas_deletes_only_unchanged_numeric_stale_pid() -> None:
    script = (Path(__file__).resolve().parents[1] / "macos" / "InvoiceHubMac" / "script" / "build_and_run.sh").read_text(encoding="utf-8")

    assert "read_server_pid_file()" in script
    assert 'value="$(< "$SERVER_PID_FILE")"' in script
    assert '[[ "$value" =~ ^[0-9]+$ ]]' in script
    assert 'OLD_SERVER_PID="$(read_server_pid_file || true)"' in script
    assert 'CURRENT_SERVER_PID="$(read_server_pid_file || true)"' in script
    assert '[[ -n "$OLD_SERVER_PID" ]]' in script
    assert '[[ "$CURRENT_SERVER_PID" == "$OLD_SERVER_PID" ]]' in script
    assert '! kill -0 "$OLD_SERVER_PID"' in script


def test_macos_run_script_force_stops_only_after_rechecking_backend_identity() -> None:
    script = (Path(__file__).resolve().parents[1] / "macos" / "InvoiceHubMac" / "script" / "build_and_run.sh").read_text(encoding="utf-8")
    identity_match = re.search(r"is_current_invoicehub_server\(\) \{(?P<body>.*?)\n\}", script, re.S)
    match = re.search(r"stop_verified_server\(\) \{(?P<body>.*?)\n\}", script, re.S)

    assert identity_match
    identity_body = identity_match.group("body")
    assert 'server_argv_matches_expected_identity "$pid" "$CONFIG_PATH"' in identity_body
    assert "server_command" not in identity_body
    assert match
    body = match.group("body")
    assert body.count('is_current_invoicehub_server "$pid"') >= 2
    assert 'kill -TERM "$pid"' in body
    assert 'kill -KILL "$pid"' in body
    assert body.index('kill -TERM "$pid"') < body.rindex('is_current_invoicehub_server "$pid"') < body.index('kill -KILL "$pid"')


def test_macos_wait_helpers_fail_explicitly_after_timeout() -> None:
    script = (Path(__file__).resolve().parents[1] / "macos" / "InvoiceHubMac" / "script" / "build_and_run.sh").read_text(encoding="utf-8")

    for function_name in ("wait_for_process_exit", "wait_for_pid_exit"):
        match = re.search(rf"{function_name}\(\) \{{(?P<body>.*?)\n\}}", script, re.S)
        assert match, function_name
        assert match.group("body").rstrip().endswith("return 1"), function_name


def test_macos_app_delegate_and_owned_process_cleanup_contract() -> None:
    root = Path(__file__).resolve().parents[1] / "macos" / "InvoiceHubMac" / "Sources"
    app = (root / "InvoiceHubMac" / "InvoiceHubMacApp.swift").read_text(encoding="utf-8")
    controller = (root / "InvoiceHubClient" / "Services" / "LocalBackendController.swift").read_text(encoding="utf-8")

    assert "func applicationWillTerminate(_ notification: Notification)" in app
    assert "backend?.terminateOwnedBackendForAppQuit()" in app
    assert "NSApplication.willTerminateNotification" not in app
    assert "finalizeOwnedBackendExit" in controller
    assert "guard !trackedProcess.isRunning else { return false }" in controller
    assert "BackendPIDFile.removeIfMatches(pidFile, expectedPID: expectedPID)" in controller
    launch_token = controller.index("launchedOwnedPID = launchedProcess.processIdentifier")
    pid_write = controller.index("try writeOwnedPIDFile(paths: resolvedPaths, launchedProcess: launchedProcess)")
    assert launch_token < pid_write
    assert "BackendProcessTruth.shouldCleanupFailedLaunch" in controller
    assert "BackendProcessTruth.healthMatchesTrackedOwnedProcess" in controller
    assert "startupGate.tryAcquire" in controller
    assert "defer { startupGate.release() }" in controller
    assert "throw BackendLaunchError.ownedProcessUnavailable(ownedPID)" in controller
    assert "struct BackendControlPolicy" in controller
    assert "struct BackendLifecycleToken" in controller
    assert "private var lifecycleGeneration: UInt64" in controller
    assert "BackendControlPolicy.canManageBackend" in controller
    assert "controlFailurePhase" not in controller
    assert "appDelegate.backend = backend" not in app
    assert "func bindBackend(_ backend: LocalBackendController)" in app
    bind_backend = app.index("appDelegate.bindBackend(backend)")
    start_backend = app.index("await backend.start()")
    assert bind_backend < start_backend

    start_flow = controller[
        controller.index("public func start() async") : controller.index("public func stopLocalhost() async")
    ]
    assert "let startGeneration = advanceLifecycleGeneration()" in start_flow
    assert "BackendLifecyclePolicy.canApplyStartupCompletion" in start_flow
    failure_message = start_flow.index("let failureMessage = error.localizedDescription")
    terminate_attempt = start_flow.index("await terminateOwnedBackend(waitForExit: true)")
    failure_policy = start_flow.index("BackendLifecyclePolicy.startupFailurePhase")
    assert failure_message < terminate_attempt < failure_policy
    assert "BackendStartupCleanupResult" in start_flow
    assert "phase: failurePhase" in start_flow

    stop_flow = controller[
        controller.index("public func stopLocalhost() async") : controller.index("public func terminateOwnedBackendForAppQuit()")
    ]
    stopping_phase = stop_flow.index("phase: .stopping")
    stop_token = stop_flow.index("let stopToken = BackendLifecycleToken(capturing: lifecycleSnapshot)")
    assert stop_flow.index("advanceLifecycleGeneration()") < stopping_phase < stop_token
    assert stop_flow.count("BackendLifecyclePolicy.canApplyAsyncCompletion") >= 2

    control_action = controller[
        controller.index("private func runControlAction") : controller.index("private func finishControlAction")
    ]
    block_guard = control_action.index("guard !BackendControlPolicy.blocksControlAction")
    assert block_guard < control_action.index("await start()")
    assert "BackendControlPolicy.canRunControlAction" in control_action
    assert "let controlToken = BackendLifecycleToken(capturing: lifecycleSnapshot)" in control_action
    assert "finishControlAction(with: try await operation(client), token: controlToken)" in control_action
    assert "failControlAction(with: error, token: controlToken)" in control_action

    control_success = controller[
        controller.index("private func finishControlAction") : controller.index("private func failControlAction")
    ]
    control_failure = controller[
        controller.index("private func failControlAction") : controller.index("private func verifyBackend")
    ]
    for completion in (control_success, control_failure):
        assert "BackendLifecyclePolicy.canApplyAsyncCompletion" in completion
        assert "token: token" in completion

    finalize_exit = controller[
        controller.index("private func finalizeOwnedBackendExit") : controller.index("private func advanceLifecycleGeneration")
    ]
    assert finalize_exit.index("advanceLifecycleGeneration()") < finalize_exit.index("process = nil")
