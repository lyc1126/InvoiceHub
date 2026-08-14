from __future__ import annotations

import csv
import hashlib
import json
import os
import subprocess
import sys
from pathlib import Path
from zipfile import ZipFile

import pytest

from invoice_hub.release.build_core import (
    CORE_PROVENANCE_INPUTS,
    INCLUDE_DIRS,
    INCLUDE_FILES,
    CoreBuildError,
    build_core,
)
from invoice_hub.release.build_manifest import (
    API_CONTRACT_VERSION,
    BOOKKEEPING_PROTOCOL_VERSION,
    BUILD_INPUTS,
    deterministic_build_id,
)
from invoice_hub.release.content_scan import ReleaseContentError, scan_release_text
from invoice_hub.release.package_manifest import PackageManifestError
from invoice_hub.release.runtime_manifest import (
    RuntimeManifestError,
    normalize_windows_runtime,
    write_runtime_manifest,
)
from invoice_hub.release.verify_portable import PortableVerificationError, verify_windows_portable
from invoice_hub.extraction import extract_invoice_record
from invoice_hub.extraction import parsers
from invoice_hub.version import PRODUCT_VERSION, RELEASE_PYTHON_VERSION, WINDOWS_PACKAGE_ID


COMMIT = "a" * 40
SOURCE_TIMESTAMP = "2026-08-02T12:34:56Z"


def _release_source(root: Path) -> Path:
    for directory in INCLUDE_DIRS:
        (root / directory).mkdir(parents=True, exist_ok=True)
    for name in INCLUDE_FILES:
        path = root / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(f"fixture for {name}\n", encoding="utf-8")
    (root / "src" / "invoice_hub").mkdir(parents=True, exist_ok=True)
    (root / "src" / "invoice_hub" / "__init__.py").write_text("", encoding="utf-8")
    (root / "src" / "invoice_hub" / "module.py").write_text("VALUE = 1\n", encoding="utf-8")
    (root / "web" / "index.html").write_text("<h1>InvoiceHub</h1>\n", encoding="utf-8")
    (root / "scripts" / "windows" / "start.bat").write_text("@echo off\n", encoding="ascii")
    (root / "scripts" / "tools" / "jierui_voucher_import.py").write_text("MODE = 'dry-run'\n", encoding="utf-8")
    (root / "docs" / "jierui" / "facts.json").write_text("{}\n", encoding="utf-8")
    (root / "pyproject.toml").write_text("[project]\nname = 'invoice-hub'\n", encoding="utf-8")
    return root


def _runtime(root: Path, lock: Path) -> Path:
    runtime = root / "prepared-runtime"
    runtime.mkdir(parents=True)
    (runtime / "python.exe").write_bytes(b"synthetic windows executable")
    (runtime / "python314.dll").write_bytes(b"synthetic runtime dll")
    (runtime / "Lib" / "site-packages").mkdir(parents=True)
    (runtime / "Lib" / "site-packages" / "locked.txt").write_text(
        "upstream build provenance: /" + "home/runner/work/dependency\n",
        encoding="utf-8",
    )
    write_runtime_manifest(
        runtime,
        lock,
        target_platform="windows",
        architecture="x86_64",
        python_version="3.14.6",
        python_executable="python.exe",
        source="synthetic test runtime",
        execute_probe=False,
    )
    return runtime


def _inputs(tmp_path: Path) -> tuple[Path, Path, Path]:
    source = _release_source(tmp_path / "source")
    lock = source / "requirements" / "windows-x64-py314.lock"
    lock.write_text(
        "sample==1.0 \\\n"
        "    --hash=sha256:" + "1" * 64 + "\n",
        encoding="utf-8",
    )
    runtime = _runtime(tmp_path, lock)
    return source, runtime, lock


def _inject_archive_files(archive_path: Path, additions: dict[str, bytes]) -> None:
    with ZipFile(archive_path) as archive:
        files = {
            info.filename: archive.read(info)
            for info in archive.infolist()
            if not info.is_dir()
        }
    files.update(additions)
    files["invoice-hub-files.sha256"] = (
        "\n".join(
            f"{hashlib.sha256(content).hexdigest()}  {name}"
            for name, content in sorted(files.items())
            if name != "invoice-hub-files.sha256"
        )
        + "\n"
    ).encode("utf-8")
    with ZipFile(archive_path, "w") as archive:
        for name, content in files.items():
            archive.writestr(name, content)


def _git(root: Path, *args: str) -> subprocess.CompletedProcess[bytes]:
    return subprocess.run(["git", "-C", str(root), *args], check=True, capture_output=True)


def _archive_build_id(root: Path, destination: Path, *, autocrlf: bool) -> str:
    archive = destination.with_suffix(".zip")
    extracted = destination / "source"
    _git(
        root,
        "-c",
        f"core.autocrlf={'true' if autocrlf else 'false'}",
        "archive",
        "--format=zip",
        f"--output={archive}",
        "HEAD",
    )
    with ZipFile(archive) as zip_file:
        zip_file.extractall(extracted)
    return deterministic_build_id(extracted)


def test_git_archive_core_build_id_is_independent_of_autocrlf(tmp_path: Path) -> None:
    source = _release_source(tmp_path / "source")
    binary_relative = Path("web/static/archive-binary-fixture.png")
    binary_content = b"\x89PNG\r\n\x1a\n\x00fixture\r\nwith-crlf-like-bytes\xff"
    (source / binary_relative).parent.mkdir(parents=True, exist_ok=True)
    (source / binary_relative).write_bytes(binary_content)
    (source / "scripts/windows/start.ps1").write_text("$ErrorActionPreference = 'Stop'\n", encoding="utf-8")
    (source / ".gitattributes").write_text(
        "* text=auto\n*.png -text\n",
        encoding="utf-8",
    )
    _git(source, "init")
    _git(source, "config", "user.name", "InvoiceHub Test")
    _git(source, "config", "user.email", "invoicehub-test@example.invalid")
    _git(source, "config", "core.autocrlf", "false")
    _git(source, "add", ".")
    _git(source, "commit", "-m", "archive fixture")
    assert _git(source, "show", f"HEAD:{binary_relative.as_posix()}").stdout == binary_content

    repository_attributes = Path(__file__).resolve().parents[1] / ".gitattributes"
    (source / ".gitattributes").write_bytes(repository_attributes.read_bytes())
    _git(source, "add", ".gitattributes")
    _git(source, "commit", "-m", "apply release attributes")

    assert _git(source, "status", "--porcelain=v1", "--untracked-files=no").stdout == b""
    assert _git(source, "show", f"HEAD:{binary_relative.as_posix()}").stdout == binary_content

    checkout = tmp_path / "autocrlf-true-checkout"
    checkout.mkdir()
    _git(checkout, "init")
    _git(checkout, "config", "core.autocrlf", "true")
    _git(checkout, "fetch", "--quiet", str(source), "HEAD")
    _git(checkout, "checkout", "--quiet", "--detach", "FETCH_HEAD")
    assert _git(checkout, "status", "--porcelain=v1", "--untracked-files=no").stdout == b""
    assert (checkout / binary_relative).read_bytes() == binary_content
    assert (checkout / "web/index.html").read_bytes() == b"<h1>InvoiceHub</h1>\n"
    assert (checkout / "scripts/windows/start.bat").read_bytes() == b"@echo off\r\n"
    assert (checkout / "scripts/windows/start.ps1").read_bytes() == b"$ErrorActionPreference = 'Stop'\r\n"
    binary_eol = _git(checkout, "ls-files", "--eol", "--", binary_relative.as_posix()).stdout
    assert b"i/-text" in binary_eol
    assert b"w/-text" in binary_eol

    autocrlf_true = tmp_path / "autocrlf-true"
    autocrlf_false = tmp_path / "autocrlf-false"
    assert _archive_build_id(source, autocrlf_true, autocrlf=True) == _archive_build_id(
        source,
        autocrlf_false,
        autocrlf=False,
    )
    assert (autocrlf_true / "source" / binary_relative).read_bytes() == binary_content
    assert (autocrlf_false / "source" / binary_relative).read_bytes() == binary_content
    assert (autocrlf_true / "source/web/index.html").read_bytes() == b"<h1>InvoiceHub</h1>\n"
    assert (autocrlf_false / "source/web/index.html").read_bytes() == b"<h1>InvoiceHub</h1>\n"
    assert (autocrlf_true / "source/scripts/windows/start.bat").read_bytes() == b"@echo off\r\n"
    assert (autocrlf_false / "source/scripts/windows/start.bat").read_bytes() == b"@echo off\r\n"
    assert (autocrlf_true / "source/scripts/windows/start.ps1").read_bytes() == (
        b"$ErrorActionPreference = 'Stop'\r\n"
    )
    assert (autocrlf_false / "source/scripts/windows/start.ps1").read_bytes() == (
        b"$ErrorActionPreference = 'Stop'\r\n"
    )


def test_normalize_windows_runtime_removes_console_scripts_and_record_rows(tmp_path: Path) -> None:
    runtime = tmp_path / "python"
    site_packages = runtime / "Lib" / "site-packages"
    scripts = runtime / "sCrIpTs"
    distribution = site_packages / "sample-1.0.dist-info"
    other_distribution = site_packages / "other-1.0.dist-info"
    distribution.mkdir(parents=True)
    other_distribution.mkdir(parents=True)
    scripts.mkdir(parents=True)
    (scripts / "sample.exe").write_bytes(b"absolute launcher payload")
    (site_packages / "sample").mkdir()
    (site_packages / "sample" / "__init__.py").write_text("VALUE = 1\n", encoding="utf-8")
    rows = [
        ["../../SCRIPTS/sample.exe", "sha256=unstable", "25"],
        ["sample/__init__.py", "sha256=stable", "10"],
        ["sample/__pycache__/__init__.cpython-314.pyc", "", ""],
        ["sample-1.0.dist-info/RECORD", "", ""],
    ]
    record = distribution / "RECORD"
    with record.open("w", encoding="utf-8", newline="") as handle:
        csv.writer(handle, lineterminator="\n").writerows(rows)
    other_record = other_distribution / "RECORD"
    with other_record.open("w", encoding="utf-8", newline="") as handle:
        csv.writer(handle, lineterminator="\n").writerow(["other-1.0.dist-info/RECORD", "", ""])
    other_before = other_record.read_bytes()

    result = normalize_windows_runtime(runtime)

    assert not scripts.exists()
    assert result == {
        "removed_script_files": ["sCrIpTs/sample.exe"],
        "removed_record_entries": ["sample-1.0.dist-info:../../SCRIPTS/sample.exe"],
        "rewritten_records": ["Lib/site-packages/sample-1.0.dist-info/RECORD"],
    }
    with record.open("r", encoding="utf-8", newline="") as handle:
        assert list(csv.reader(handle)) == rows[1:]
    assert other_record.read_bytes() == other_before
    assert normalize_windows_runtime(runtime) == {
        "removed_script_files": [],
        "removed_record_entries": [],
        "rewritten_records": [],
    }


def test_normalize_windows_runtime_rejects_record_escape_before_removing_scripts(tmp_path: Path) -> None:
    runtime = tmp_path / "python"
    record_dir = runtime / "Lib" / "site-packages" / "sample-1.0.dist-info"
    scripts = runtime / "Scripts"
    record_dir.mkdir(parents=True)
    scripts.mkdir()
    launcher = scripts / "sample.exe"
    launcher.write_bytes(b"launcher")
    with (record_dir / "RECORD").open("w", encoding="utf-8", newline="") as handle:
        csv.writer(handle, lineterminator="\n").writerow(["../../../outside.exe", "", ""])

    with pytest.raises(RuntimeManifestError, match="escapes runtime"):
        normalize_windows_runtime(runtime)

    assert launcher.is_file()


def test_windows_portable_is_deterministic_and_excludes_local_state(tmp_path: Path) -> None:
    source, runtime, lock = _inputs(tmp_path)
    private_watch_dir = tmp_path / "private invoices"
    (source / "config").mkdir()
    (source / "config" / "app.local.json").write_text(
        json.dumps({"watch_dir": str(private_watch_dir)}),
        encoding="utf-8",
    )
    (source / "runtime").mkdir()
    (source / "runtime" / "server.pid").write_text("1", encoding="ascii")
    (source / "tests").mkdir()
    (source / "tests" / "secret.pdf").write_bytes(b"real invoice")
    (source / "src" / ".DS_Store").write_bytes(b"finder metadata")

    first = build_core(
        source,
        tmp_path / "dist-one",
        runtime_dir=runtime,
        dependency_lock=lock,
        source_commit=COMMIT,
        source_timestamp=SOURCE_TIMESTAMP,
    )
    second = build_core(
        source,
        tmp_path / "dist-two",
        runtime_dir=runtime,
        dependency_lock=lock,
        source_commit=COMMIT,
        source_timestamp=SOURCE_TIMESTAMP,
    )

    assert first.archive_path.name == f"InvoiceHub-v{PRODUCT_VERSION}-windows-x64-portable.zip"
    assert first.archive_sha256 == second.archive_sha256
    assert first.build_id == second.build_id
    with ZipFile(first.archive_path) as archive:
        names = set(archive.namelist())
        packaged_config = json.loads(archive.read("config/app.default.json"))
        build_manifest = json.loads(archive.read("invoice-hub-build.json"))
        package_manifest = json.loads(archive.read("invoice-hub-package.json"))
        contents = archive.read("invoice-hub-files.sha256").decode("utf-8")
        sbom = json.loads(archive.read("sbom/InvoiceHub-windows-x64.cdx.json"))

    assert "config/app.local.json" not in names
    assert "runtime/server.pid" not in names
    assert "tests/secret.pdf" not in names
    assert "src/.DS_Store" not in names
    assert "发票文件/" in names
    assert "运行状态/" in names
    assert "python/python.exe" in names
    assert "python/invoice-hub-runtime.json" in names
    assert "导入旧版设置.bat" in names
    assert "sbom/InvoiceHub-windows-x64.cdx.json" in names
    assert packaged_config["watch_dir"] == "./发票文件"
    assert packaged_config["runtime_dir"] == "./运行状态"
    assert str(private_watch_dir) not in json.dumps(packaged_config, ensure_ascii=False)
    assert build_manifest["source_commit"] == COMMIT
    assert build_manifest["built_at"] == SOURCE_TIMESTAMP
    assert build_manifest["api_contract_version"] == API_CONTRACT_VERSION
    assert build_manifest["bookkeeping_protocol_version"] == BOOKKEEPING_PROTOCOL_VERSION
    assert package_manifest["package_id"] == WINDOWS_PACKAGE_ID
    assert package_manifest["python_version"] == RELEASE_PYTHON_VERSION
    assert package_manifest["core_build_id"] == build_manifest["build_id"]
    assert sbom["bomFormat"] == "CycloneDX"
    assert sbom["metadata"]["component"]["version"] == PRODUCT_VERSION
    assert "invoice-hub-build.json" in contents
    assert "invoice-hub-files.sha256" not in contents

    verified = verify_windows_portable(first.archive_path, execute_runtime_probe=False)
    assert verified["ok"] is True
    assert verified["archive_sha256"] == first.archive_sha256
    assert verified["source_commit"] == COMMIT


def test_windows_portable_allows_scanned_dependency_test_directories(tmp_path: Path) -> None:
    source, runtime, lock = _inputs(tmp_path)
    dependency_test = runtime / "Lib" / "site-packages" / "sample" / "TeStS" / "test_runtime.py"
    dependency_test.parent.mkdir(parents=True)
    upstream_path = "/" + "home" + "/runner/work/sample"
    dependency_test.write_text(
        f'UPSTREAM_BUILD_ROOT = "{upstream_path}"\n',
        encoding="utf-8",
    )
    write_runtime_manifest(
        runtime,
        lock,
        target_platform="windows",
        architecture="x86_64",
        python_version="3.14.6",
        python_executable="python.exe",
        source="synthetic test runtime",
        execute_probe=False,
    )

    built = build_core(
        source,
        tmp_path / "dist",
        runtime_dir=runtime,
        dependency_lock=lock,
        source_commit=COMMIT,
        source_timestamp=SOURCE_TIMESTAMP,
    )

    with ZipFile(built.archive_path) as archive:
        assert "python/Lib/site-packages/sample/TeStS/test_runtime.py" in archive.namelist()
    verified = verify_windows_portable(built.archive_path, execute_runtime_probe=False)
    assert verified["ok"] is True


def test_runtime_tampering_and_dirty_source_identity_fail_closed(tmp_path: Path) -> None:
    source, runtime, lock = _inputs(tmp_path)
    (runtime / "python314.dll").write_bytes(b"tampered")
    with pytest.raises(RuntimeManifestError, match="runtime tree SHA-256"):
        build_core(
            source,
            tmp_path / "dist",
            runtime_dir=runtime,
            dependency_lock=lock,
            source_commit=COMMIT,
            source_timestamp=SOURCE_TIMESTAMP,
        )

    runtime = _runtime(tmp_path / "fresh", lock)
    with pytest.raises(CoreBuildError, match="40-character"):
        build_core(
            source,
            tmp_path / "dist",
            runtime_dir=runtime,
            dependency_lock=lock,
            source_commit=COMMIT + "+dirty",
            source_timestamp=SOURCE_TIMESTAMP,
        )


def test_windows_portable_build_rejects_non_release_python_patch(tmp_path: Path) -> None:
    source, runtime, lock = _inputs(tmp_path)

    with pytest.raises(CoreBuildError, match="Python 3.14.6"):
        build_core(
            source,
            tmp_path / "dist",
            runtime_dir=runtime,
            dependency_lock=lock,
            source_commit=COMMIT,
            source_timestamp=SOURCE_TIMESTAMP,
            python_version="3.14.7",
        )


def test_windows_portable_verifier_rejects_runtime_patch_drift(tmp_path: Path) -> None:
    source, runtime, lock = _inputs(tmp_path)
    built = build_core(
        source,
        tmp_path / "dist",
        runtime_dir=runtime,
        dependency_lock=lock,
        source_commit=COMMIT,
        source_timestamp=SOURCE_TIMESTAMP,
    )
    with ZipFile(built.archive_path) as archive:
        files = {
            info.filename: archive.read(info)
            for info in archive.infolist()
            if not info.is_dir()
        }
    runtime_manifest = json.loads(files["python/invoice-hub-runtime.json"])
    runtime_manifest["python_version"] = "3.14.7"
    files["python/invoice-hub-runtime.json"] = (
        json.dumps(runtime_manifest, ensure_ascii=False, indent=2, sort_keys=True) + "\n"
    ).encode("utf-8")
    files["invoice-hub-files.sha256"] = (
        "\n".join(
            f"{hashlib.sha256(content).hexdigest()}  {name}"
            for name, content in sorted(files.items())
            if name != "invoice-hub-files.sha256"
        )
        + "\n"
    ).encode("utf-8")
    with ZipFile(built.archive_path, "w") as archive:
        for name, content in files.items():
            archive.writestr(name, content)

    with pytest.raises(RuntimeManifestError, match="3.14.6"):
        verify_windows_portable(built.archive_path, execute_runtime_probe=False)


def test_windows_portable_verifier_rejects_package_source_commit_drift(tmp_path: Path) -> None:
    source, runtime, lock = _inputs(tmp_path)
    built = build_core(
        source,
        tmp_path / "dist",
        runtime_dir=runtime,
        dependency_lock=lock,
        source_commit=COMMIT,
        source_timestamp=SOURCE_TIMESTAMP,
    )
    with ZipFile(built.archive_path) as archive:
        files = {
            info.filename: archive.read(info)
            for info in archive.infolist()
            if not info.is_dir()
        }
    package_manifest = json.loads(files["invoice-hub-package.json"])
    package_manifest["source_commit"] = "b" * 40
    files["invoice-hub-package.json"] = (
        json.dumps(package_manifest, ensure_ascii=False, indent=2, sort_keys=True) + "\n"
    ).encode("utf-8")
    files["invoice-hub-files.sha256"] = (
        "\n".join(
            f"{hashlib.sha256(content).hexdigest()}  {name}"
            for name, content in sorted(files.items())
            if name != "invoice-hub-files.sha256"
        )
        + "\n"
    ).encode("utf-8")
    with ZipFile(built.archive_path, "w") as archive:
        for name, content in files.items():
            archive.writestr(name, content)

    with pytest.raises(PackageManifestError, match="source_commit"):
        verify_windows_portable(built.archive_path, execute_runtime_probe=False)


@pytest.mark.parametrize(
    "forbidden_name",
    (
        "macos/InvoiceHubMac/Package.swift",
        "scripts/macos/build_release.sh",
        "requirements/macos-arm64-py314.lock",
        "python/bin/python3",
        "python/Doc/html/index.html",
        "python/sCrIpTs/uvicorn.exe",
        "python/Lib/TeStS/test_os.py",
        "src/invoice_hub/TeStS/test_secret.py",
        "python/Lib/site-packages/sample/tests/__PyCaChE__/cached.py",
        "src/invoice_hub/platform/DesktopShell.swift",
        "docs/jierui/InvoiceHub.app/Contents/Info.plist",
        "scripts/dev/build_windows_portable.ps1",
    ),
)
def test_windows_portable_verifier_rejects_cross_platform_and_non_product_members(
    tmp_path: Path,
    forbidden_name: str,
) -> None:
    source, runtime, lock = _inputs(tmp_path)
    built = build_core(
        source,
        tmp_path / "dist",
        runtime_dir=runtime,
        dependency_lock=lock,
        source_commit=COMMIT,
        source_timestamp=SOURCE_TIMESTAMP,
    )
    _inject_archive_files(
        built.archive_path,
        {forbidden_name: b"platform-specific release content\n"},
    )

    with pytest.raises(
        PortableVerificationError,
        match=(
            r"macOS-only ZIP member|Python documentation|Python console scripts|"
            r"outside the Windows package allowlist|forbidden ZIP member"
        ),
    ):
        verify_windows_portable(built.archive_path, execute_runtime_probe=False)


def test_dependency_test_directories_remain_subject_to_content_scan(tmp_path: Path) -> None:
    source, runtime, lock = _inputs(tmp_path)
    built = build_core(
        source,
        tmp_path / "dist",
        runtime_dir=runtime,
        dependency_lock=lock,
        source_commit=COMMIT,
        source_timestamp=SOURCE_TIMESTAMP,
    )
    synthetic_token = b"ghp_" + b"abcdefghijklmnopqrstuvwxyz123456"
    _inject_archive_files(
        built.archive_path,
        {
            "python/Lib/site-packages/sample/tests/token.py": (
                b'TOKEN = "' + synthetic_token + b'"\n'
            )
        },
    )

    with pytest.raises(PortableVerificationError, match="possible secret"):
        verify_windows_portable(built.archive_path, execute_runtime_probe=False)


def test_windows_portable_rejects_secret_or_local_path_before_writing_archive(tmp_path: Path) -> None:
    source, runtime, lock = _inputs(tmp_path)
    archive = tmp_path / "dist" / f"InvoiceHub-v{PRODUCT_VERSION}-windows-x64-portable.zip"
    synthetic_token = "ghp_" + "abcdefghijklmnopqrstuvwxyz123456"
    secret_field = "api" + "_key"
    (source / "src" / "invoice_hub" / "secret.py").write_text(
        f'{secret_field} = "{synthetic_token}"\n',
        encoding="utf-8",
    )

    with pytest.raises(CoreBuildError, match="possible secret"):
        build_core(
            source,
            tmp_path / "dist",
            runtime_dir=runtime,
            dependency_lock=lock,
            source_commit=COMMIT,
            source_timestamp=SOURCE_TIMESTAMP,
        )

    assert not archive.exists()


def test_windows_portable_rejects_symlinked_source_input(tmp_path: Path) -> None:
    source, runtime, lock = _inputs(tmp_path)
    external = tmp_path / "external.py"
    external.write_text("VALUE = 2\n", encoding="utf-8")
    linked = source / "src" / "invoice_hub" / "linked.py"
    try:
        linked.symlink_to(external)
    except (OSError, NotImplementedError):
        pytest.skip("symlink creation is unavailable")

    with pytest.raises(CoreBuildError, match="symbolic links"):
        build_core(
            source,
            tmp_path / "dist",
            runtime_dir=runtime,
            dependency_lock=lock,
            source_commit=COMMIT,
            source_timestamp=SOURCE_TIMESTAMP,
        )


def test_dependency_scan_allows_upstream_build_paths_but_rejects_high_confidence_secrets() -> None:
    upstream_path = b"/" + b"home/runner/work/upstream"
    scan_release_text(
        "python/Lib/site-packages/example/_build.py",
        b'BUILD_ROOT = "' + upstream_path + b'"\n',
        scope="dependency",
    )
    synthetic_token = b"ghp_" + b"abcdefghijklmnopqrstuvwxyz123456"
    with pytest.raises(ReleaseContentError, match="possible secret"):
        scan_release_text(
            "python/Lib/site-packages/example/token.py",
            b'TOKEN = "' + synthetic_token + b'"\n',
            scope="dependency",
        )


def test_synthetic_release_fixture_contains_parseable_pdf_xml_and_ofd(tmp_path: Path) -> None:
    output = tmp_path / "合成 release fixture"
    script = Path(__file__).resolve().parents[1] / "scripts" / "dev" / "generate_synthetic_release_fixture.py"
    env = dict(os.environ)
    env["PYTHONIOENCODING"] = "ascii"
    completed = subprocess.run(
        [sys.executable, str(script), "--output-dir", str(output)],
        capture_output=True,
        text=True,
        env=env,
    )
    assert completed.returncode == 0, completed.stderr
    result = json.loads(completed.stdout)
    assert result["synthetic_only"] is True
    assert result["contains_real_business_data"] is False
    assert result["output_dir"] == str(output.resolve())
    assert {path.suffix for path in output.iterdir()} >= {".pdf", ".xml", ".ofd"}

    records = {
        path.suffix: extract_invoice_record(path)
        for path in sorted(output.iterdir())
        if path.suffix in {".pdf", ".xml", ".ofd"}
    }
    assert records[".pdf"].invoice_number == "10000000000000000016"
    assert records[".pdf"].amount == "113.00"
    assert records[".xml"].invoice_number == "10000000000000000017"
    assert records[".xml"].amount == "226.00"
    assert records[".ofd"].invoice_number == "10000000000000000018"
    assert records[".ofd"].amount == "339.00"

    with pytest.raises(subprocess.CalledProcessError):
        subprocess.run(
            [sys.executable, str(script), "--output-dir", str(output)],
            check=True,
            capture_output=True,
            text=True,
        )


def test_ordinary_english_business_text_is_not_promoted_to_invoice_fields(tmp_path: Path) -> None:
    record = parsers._record_from_text(
        tmp_path / "ordinary-business-document.pdf",
        "\n".join(
            (
                "Monthly customer statement",
                "Invoice number: 10000000000000000016",
                "Issue date: 2026-08-02",
                "Buyer: Example Customer LLC",
                "Seller: Example Supplier LLC",
                "Amount total: 100.00",
                "Tax total: 13.00",
                "Total amount: 113.00",
                "Tax rate: 13%",
            )
        ),
    )

    assert record.invoice_number == ""
    assert record.invoice_date == ""
    assert record.buyer == ""
    assert record.seller == ""
    assert record.pretax_amount == ""
    assert record.tax_amount == ""
    assert record.amount == ""
    assert record.tax_rate == ""


def test_core_provenance_inputs_cover_every_packaged_repository_source() -> None:
    provenance = set(CORE_PROVENANCE_INPUTS)
    assert set(INCLUDE_DIRS) == {"src", "web", "scripts/windows", "docs/jierui"}
    assert set(BUILD_INPUTS) <= provenance
    assert set(INCLUDE_DIRS) <= provenance
    assert set(INCLUDE_FILES) <= provenance
    assert "config" not in provenance
