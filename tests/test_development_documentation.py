import os
import re
import shutil
import subprocess
from pathlib import Path
from urllib.parse import unquote


ROOT = Path(__file__).resolve().parents[1]
FILE_MAP = ROOT / "docs" / "architecture" / "FILE_MAP.md"
ARCHITECTURE_ENTRY = ROOT / "docs" / "DEVELOPMENT_ARCHITECTURE.md"
ARCHITECTURE_APPENDICES = (
    ROOT / "docs" / "architecture" / "PLATFORM_ARCHITECTURE.md",
    ROOT / "docs" / "architecture" / "FILE_MAP.md",
    ROOT / "docs" / "architecture" / "INTERFACES_AND_FLOWS.md",
    ROOT / "docs" / "architecture" / "DATA_AND_ALGORITHMS.md",
    ROOT / "docs" / "architecture" / "AGENT_TASK_MAP.md",
    ROOT / "docs" / "architecture" / "COMMENT_RATIONALE_MAP.md",
)
ARCHITECTURE_DOCS = (ARCHITECTURE_ENTRY, *ARCHITECTURE_APPENDICES)
MACOS_ENGINEERING_FILES = tuple(
    ROOT / path
    for path in (
        "macos/InvoiceHubMac/Package.swift",
        "macos/InvoiceHubMac/Package.resolved",
        "macos/InvoiceHubMac/README.md",
        "macos/InvoiceHubMac/script/build_and_run.sh",
        "macos/InvoiceHubMac/script/build_release.sh",
        "macos/InvoiceHubMac/script/prepare_release_runtime.sh",
        "macos/InvoiceHubMac/script/verify_macos_release.sh",
        "macos/InvoiceHubMac/script/verify_sparkle_update.swift",
        "macos/InvoiceHubMac/Sources/InvoiceHubMac/InvoiceHubMacApp.swift",
        "macos/InvoiceHubMac/Sources/InvoiceHubClient/Commands/InvoiceHubCommands.swift",
        "macos/InvoiceHubMac/Sources/InvoiceHubClient/Models/AppRoute.swift",
        "macos/InvoiceHubMac/Sources/InvoiceHubClient/Models/BackendStatus.swift",
        "macos/InvoiceHubMac/Sources/InvoiceHubClient/Models/BuildHandshake.swift",
        "macos/InvoiceHubMac/Sources/InvoiceHubClient/Models/StartupSurface.swift",
        "macos/InvoiceHubMac/Sources/InvoiceHubClient/Services/BackendPaths.swift",
        "macos/InvoiceHubMac/Sources/InvoiceHubClient/Services/InvoiceHubAPIClient.swift",
        "macos/InvoiceHubMac/Sources/InvoiceHubClient/Services/InvoiceHubConfig.swift",
        "macos/InvoiceHubMac/Sources/InvoiceHubClient/Services/InvoiceHubSparkleUpdater.swift",
        "macos/InvoiceHubMac/Sources/InvoiceHubClient/Services/LocalBackendController.swift",
        "macos/InvoiceHubMac/Sources/InvoiceHubClient/Services/PythonCommandResolver.swift",
        "macos/InvoiceHubMac/Sources/InvoiceHubClient/Support/MacDirectoryPicker.swift",
        "macos/InvoiceHubMac/Sources/InvoiceHubClient/Views/ContentView.swift",
        "macos/InvoiceHubMac/Sources/InvoiceHubClient/Views/SettingsView.swift",
        "macos/InvoiceHubMac/Sources/InvoiceHubClient/Views/SidebarView.swift",
        "macos/InvoiceHubMac/Sources/InvoiceHubClient/Views/WebContentView.swift",
        "macos/InvoiceHubMac/Sources/InvoiceHubClient/Views/WebView.swift",
        "macos/InvoiceHubMac/Tests/InvoiceHubClientTests/BackendPathResolverTests.swift",
    )
)
LOCAL_EXTENSION_FILES = tuple(
    ROOT / path
    for path in (
        "src/invoice_hub/release/build_manifest.py",
        "src/invoice_hub/release/package_manifest.py",
        "src/invoice_hub/release/provenance.py",
        "src/invoice_hub/release/runtime_manifest.py",
        "src/invoice_hub/release/update_metadata.py",
        "src/invoice_hub/services/update_service.py",
        "src/invoice_hub/version.py",
        "src/invoice_hub/runners/__init__.py",
        "src/invoice_hub/runners/jierui_voucher_import.py",
        "web/static/js/page-bookkeeping.js",
        "web/templates/bookkeeping.html",
        "web/static/skins/ink-pulse/skin.json",
        "web/static/skins/ink-pulse/skin.css",
        "tests/test_build_manifest.py",
        "tests/test_release_provenance.py",
        "tests/test_api_bookkeeping.py",
        "tests/test_runner_dryrun.py",
    )
)
TAURI_FOUNDATION_FILES = tuple(
    ROOT / path
    for path in (
        "package.json",
        "pnpm-lock.yaml",
        "rust-toolchain.toml",
        ".cargo/config.toml",
        "docs/release/TAURI2_EXECUTION_PLAN.md",
        "scripts/dev/tauri_version_sync.py",
        "scripts/dev/tauri_doctor.py",
        "scripts/dev/tauri_bootstrap.py",
        "scripts/dev/tauri-doctor.sh",
        "scripts/dev/tauri-bootstrap.sh",
        "scripts/dev/tauri-doctor.ps1",
        "scripts/dev/tauri-bootstrap.ps1",
        "src-tauri/Cargo.toml",
        "src-tauri/Cargo.lock",
        "src-tauri/build.rs",
        "src-tauri/tauri.conf.json",
        "src-tauri/capabilities/no-webview-ipc.json",
        "src-tauri/src/lib.rs",
        "src-tauri/src/backend.rs",
        "src-tauri/src/host_rpc.rs",
        "src-tauri/src/main.rs",
        "src-tauri/tests/lifecycle_contract.rs",
        "src-tauri/boot/index.html",
        "src-tauri/icons/icon.png",
        "src-tauri/README.md",
        "src/invoice_hub/platform/host_rpc.py",
        "tests/test_tauri_foundation.py",
        "tests/test_tauri_host_rpc.py",
        "tests/test_tauri_lifecycle_contract.py",
    )
)
CURRENT_FACT_DOCS = (
    *ARCHITECTURE_DOCS,
    ROOT / "AGENTS.md",
    ROOT / "README.md",
    ROOT / "IMPLEMENTATION_STATUS.md",
    ROOT / "docs" / "MIGRATION_GAP_CHECKLIST.md",
    ROOT / "CLAUDE.md",
    ROOT / "docs" / "GIT_BRANCH_WORKTREE_FORK_GUIDE.md",
    ROOT / "docs" / "MAC_WINDOWS_WORKFLOW.md",
    ROOT / "macos" / "InvoiceHubMac" / "README.md",
    ROOT / "docs" / "release" / "UPDATE_SYSTEM.md",
)
PUBLIC_RELEASE_FILES = (
    ROOT / "NOTICE",
    ROOT / "CONTRIBUTING.md",
    ROOT / "SECURITY.md",
    ROOT / "CODE_OF_CONDUCT.md",
    ROOT / "PRIVACY.md",
    ROOT / ".github" / "dependabot.yml",
    ROOT / ".github" / "workflows" / "dco.yml",
    ROOT / "docs" / "release" / "HISTORY_SANITIZATION_EXECUTION.md",
)
HISTORY_SANITIZATION_EXECUTION = ROOT / "docs" / "release" / "HISTORY_SANITIZATION_EXECUTION.md"
NEW_GOVERNED_FILES = {
    path.relative_to(ROOT).as_posix() for path in ARCHITECTURE_DOCS
} | {
    path.relative_to(ROOT).as_posix()
    for path in (*MACOS_ENGINEERING_FILES, *LOCAL_EXTENSION_FILES)
} | {
    path.relative_to(ROOT).as_posix() for path in PUBLIC_RELEASE_FILES
} | {
    path.relative_to(ROOT).as_posix() for path in TAURI_FOUNDATION_FILES
} | {"tests/test_development_documentation.py"}

MARKDOWN_LINK_RE = re.compile(r"!?\[[^\]]*\]\((?P<target><[^>]+>|[^\s)]+)")
ABSOLUTE_PATH_RE = re.compile(
    r"(?<![A-Za-z0-9+.-])[A-Za-z]:[\\/]|/mnt/[A-Za-z]/|/Users/|/home/"
)
HISTORICAL_GIT_OBJECT_RE = re.compile(
    r"\b(?=[0-9a-f]{7,40}\b)(?=[0-9a-f]*[a-f])[0-9a-f]{7,40}\b"
)


def _git_tracked_files() -> set[str] | None:
    git = shutil.which("git")
    if not git:
        return None
    try:
        result = subprocess.run(
            [git, "ls-files", "-z"],
            cwd=ROOT,
            check=False,
            capture_output=True,
        )
    except OSError:
        return None
    if result.returncode != 0:
        return None
    return {
        item.decode("utf-8").replace("\\", "/")
        for item in result.stdout.split(b"\0")
        if item
    }


def _filesystem_governed_files() -> set[str]:
    excluded_roots = {
        ".agents",
        ".codex",
        ".git",
        ".playwright-cli",
        ".venv",
        "dist",
        "htmlcov",
        "ink-pulse",
        "node_modules",
        "output",
        "runtime",
        "运行状态",
    }
    governed: set[str] = set()
    for current, dirnames, filenames in os.walk(ROOT, topdown=True):
        current_path = Path(current)
        relative_dir = current_path.relative_to(ROOT)
        if relative_dir == Path("."):
            dirnames[:] = [
                name
                for name in dirnames
                if name not in excluded_roots and not name.startswith(".pytest_")
            ]
        else:
            dirnames[:] = [
                name
                for name in dirnames
                if name != "__pycache__" and not name.startswith(".pytest_")
            ]

        for filename in filenames:
            path = current_path / filename
            relative = path.relative_to(ROOT).as_posix()
            if filename.endswith((".pyc", ".lnk")):
                continue
            if relative in {".coverage", "ink-pulse.zip"}:
                continue
            if relative.startswith("发票文件/") and relative != "发票文件/.gitkeep":
                continue
            governed.add(relative)
    return governed


def _governed_files() -> set[str]:
    tracked = _git_tracked_files()
    if tracked is None:
        return _filesystem_governed_files()
    return tracked | NEW_GOVERNED_FILES


def _assert_fences_are_balanced(path: Path) -> int:
    active: tuple[str, int, str] | None = None
    mermaid_blocks = 0
    for line_number, line in enumerate(path.read_text(encoding="utf-8").splitlines(), 1):
        match = re.match(r"^\s*(`{3,}|~{3,})(.*)$", line)
        if not match:
            continue
        marker, info = match.groups()
        if active is None:
            active = (marker[0], len(marker), info.strip().lower())
            if active[2] == "mermaid":
                mermaid_blocks += 1
            continue
        marker_char, marker_length, _ = active
        if marker[0] == marker_char and len(marker) >= marker_length and not info.strip():
            active = None
    assert active is None, f"unclosed Markdown fence in {path.relative_to(ROOT)}"
    return mermaid_blocks


def test_file_map_covers_every_governed_engineering_file() -> None:
    file_map = FILE_MAP.read_text(encoding="utf-8")
    missing = sorted(
        path for path in _governed_files() if f"`{path}`" not in file_map
    )
    assert not missing, "FILE_MAP.md is missing:\n" + "\n".join(missing)


def test_architecture_documents_are_interlinked_and_local_links_exist() -> None:
    entry = ARCHITECTURE_ENTRY.read_text(encoding="utf-8")
    for appendix in ARCHITECTURE_APPENDICES:
        entry_target = appendix.relative_to(ARCHITECTURE_ENTRY.parent).as_posix()
        assert f"({entry_target})" in entry
        appendix_text = appendix.read_text(encoding="utf-8")
        assert "(../DEVELOPMENT_ARCHITECTURE.md)" in appendix_text

    readme = (ROOT / "README.md").read_text(encoding="utf-8")
    agents = (ROOT / "AGENTS.md").read_text(encoding="utf-8")
    for text in (readme, agents):
        assert "docs/DEVELOPMENT_ARCHITECTURE.md" in text
        assert "docs/architecture/AGENT_TASK_MAP.md" in text
    assert "docs/architecture/FILE_MAP.md" in agents
    assert "docs/architecture/INTERFACES_AND_FLOWS.md" in agents
    assert "docs/architecture/DATA_AND_ALGORITHMS.md" in agents

    broken: list[str] = []
    for source in CURRENT_FACT_DOCS:
        text = source.read_text(encoding="utf-8")
        for match in MARKDOWN_LINK_RE.finditer(text):
            target = match.group("target").strip("<>")
            if target.startswith(("#", "http://", "https://", "mailto:")):
                continue
            target_path = unquote(target.split("#", 1)[0].split("?", 1)[0])
            if not target_path:
                continue
            resolved = (source.parent / target_path).resolve()
            if not resolved.exists():
                broken.append(
                    f"{source.relative_to(ROOT)} -> {target}"
                )
    assert not broken, "broken local Markdown links:\n" + "\n".join(broken)


def test_platform_architecture_covers_macos_and_shared_boundaries() -> None:
    platform = (
        ROOT / "docs" / "architecture" / "PLATFORM_ARCHITECTURE.md"
    ).read_text(encoding="utf-8")
    file_map = FILE_MAP.read_text(encoding="utf-8")
    required_facts = (
        "共享核心",
        "Windows",
        "macOS",
        "SwiftUI",
        "WKWebView",
        "NSOpenPanel",
        "Application Support",
        "externalCompatible",
        "w9-ledger-review-v1",
        "2026-08-02-release-update-v1",
        "invoices.file-preview.v1",
        "invoices.batch-print.v1",
        "不得分叉",
        "单仓库",
        "成品边界则必须互斥",
    )
    for fact in required_facts:
        assert fact in platform

    for path in (*MACOS_ENGINEERING_FILES, *LOCAL_EXTENSION_FILES):
        assert path.is_file(), path.relative_to(ROOT)
        relative = path.relative_to(ROOT).as_posix()
        assert f"`{relative}`" in file_map


def test_architecture_mermaid_and_markdown_fences_are_balanced() -> None:
    mermaid_blocks = sum(_assert_fences_are_balanced(path) for path in ARCHITECTURE_DOCS)
    assert mermaid_blocks >= 3


def test_current_baselines_and_non_drifting_facts_are_explicit() -> None:
    entry = ARCHITECTURE_ENTRY.read_text(encoding="utf-8")
    status = (ROOT / "IMPLEMENTATION_STATUS.md").read_text(encoding="utf-8")
    flows = (ROOT / "docs" / "architecture" / "INTERFACES_AND_FLOWS.md").read_text(
        encoding="utf-8"
    )
    for text in (entry, status):
        assert "main" in text
        assert "脱敏" in text
        assert "0.3.0-alpha.1" in text
    assert "候选树、Git 对象和托管面验证已通过" in flows
    assert "验证通过前，仓库不得公开" not in flows

    stale_markers = (
        "59 tests",
        "~770",
        "~1340",
        "107 个受版本控制文件",
        "尚未推送",
        "本轮未执行 `git push`",
        "当前开发工作树",
        "描述该未合并实现",
        "2026-08-02-preview-session-resilience",
        "当前开发分支：`codex/preview-session-resilience`",
    )
    stale: list[str] = []
    for path in CURRENT_FACT_DOCS:
        text = path.read_text(encoding="utf-8")
        for marker in stale_markers:
            if marker in text:
                stale.append(f"{path.relative_to(ROOT)}: {marker}")
        if HISTORICAL_GIT_OBJECT_RE.search(text):
            stale.append(f"{path.relative_to(ROOT)}: commit-like identifier")
    assert not stale, "stale current-fact markers:\n" + "\n".join(stale)


def test_host_rpc_docs_describe_the_direct_backend_token_handoff() -> None:
    update_system = (ROOT / "docs" / "release" / "UPDATE_SYSTEM.md").read_text(
        encoding="utf-8"
    )
    plan = (ROOT / "docs" / "release" / "TAURI2_EXECUTION_PLAN.md").read_text(
        encoding="utf-8"
    )
    host_rpc_architecture_docs = (
        ROOT / "docs" / "architecture" / "PLATFORM_ARCHITECTURE.md",
        ROOT / "docs" / "architecture" / "INTERFACES_AND_FLOWS.md",
    )

    assert "只留在 Tauri 进程内" not in update_system
    assert "directly spawned Python backend" in plan
    assert "descendant" in update_system
    assert "网页、Tauri command/event、API 响应或日志" in update_system
    for path in host_rpc_architecture_docs:
        text = path.read_text(encoding="utf-8")
        assert "直接启动的 Python backend" in text
        assert "descendant 环境清除" in text
        assert "四种固定 picker enum" in text
        assert "`update_check` / `update_install` 两个固定 enum" in text


def test_current_tauri_docs_keep_install_fail_closed_until_recovery_exists() -> None:
    readme = (ROOT / "README.md").read_text(encoding="utf-8")
    file_map = FILE_MAP.read_text(encoding="utf-8")
    task_map = (ROOT / "docs" / "architecture" / "AGENT_TASK_MAP.md").read_text(
        encoding="utf-8"
    )

    assert "install 请求只清除候选并返回不可用" in readme
    assert "Current install consumes the candidate and fails closed" in file_map
    assert "当前 install 只清除候选并 fail closed" in task_map
    assert "随后才按下载+Minisign 验签" not in readme


def test_current_tauri_docs_require_bounded_update_checks_and_confirmed_exit_cleanup() -> None:
    agents = (ROOT / "AGENTS.md").read_text(encoding="utf-8")
    plan = (ROOT / "docs" / "release" / "TAURI2_EXECUTION_PLAN.md").read_text(
        encoding="utf-8"
    )
    platform = (ROOT / "docs" / "architecture" / "PLATFORM_ARCHITECTURE.md").read_text(
        encoding="utf-8"
    )

    for text in (agents, plan, platform):
        assert "ExitRequested" in text
        assert "kill" in text
        assert "5 秒" in text
    assert "Drop kill fallback" not in plan
    assert "Drop fallback" not in platform

    current_exit_docs = (
        ROOT / "CHANGELOG.md",
        ROOT / "README.md",
        ROOT / "IMPLEMENTATION_STATUS.md",
        ROOT / "docs" / "MIGRATION_GAP_CHECKLIST.md",
        ROOT / "docs" / "MAC_WINDOWS_WORKFLOW.md",
        ROOT / "docs" / "architecture" / "PLATFORM_ARCHITECTURE.md",
        ROOT / "docs" / "release" / "UPDATE_SYSTEM.md",
        ROOT / "src-tauri" / "README.md",
    )
    stale_exit_claims = (
        "and orderly shutdown released the port and PID state",
        "和正常退出，未触碰用户",
        "启动和正常退出烟测",
        "desktop 默认值和有序退出。",
        "首页与有序退出",
        "和正常 shutdown 后的端口/PID 清理",
        "系统菜单、Cmd-Q 和其它 `ExitRequested` 都先",
        "和正常退出检查",
        "加载页面并正常退出",
        "were observed, and orderly shutdown released",
    )
    for path in current_exit_docs:
        text = path.read_text(encoding="utf-8")
        for stale_claim in stale_exit_claims:
            assert stale_claim not in text, f"{path.relative_to(ROOT)}: {stale_claim}"


def test_public_history_sanitization_governance_is_consistent() -> None:
    record = HISTORY_SANITIZATION_EXECUTION.read_text(encoding="utf-8")
    for field in ("Hypothesis", "Decision changed by result", "Minimal sample", "Stop condition"):
        assert field in record
    for fact in (
        "Authorized by the repository owner",
        "one sanitized root snapshot",
        "owner-only",
        "gitleaks 8.30.1",
        "Releases and assets",
        "only the sanitized `main`",
    ):
        assert fact in record
    for path in PUBLIC_RELEASE_FILES:
        assert path.is_file(), path.relative_to(ROOT)
    assert "AGPL-3.0-or-later" in (ROOT / "CONTRIBUTING.md").read_text(encoding="utf-8")
    assert "Copyright (c) 2026 lyc1126 and contributors" in (ROOT / "NOTICE").read_text(encoding="utf-8")
    assert "Signed-off-by" in (ROOT / ".github" / "workflows" / "dco.yml").read_text(encoding="utf-8")


def test_windows_ci_derives_release_version_from_version_source() -> None:
    workflow = (ROOT / ".github" / "workflows" / "ci.yml").read_text(encoding="utf-8")

    assert "0.2.0-beta.1" not in workflow
    assert "runpy.run_path('src/invoice_hub/version.py')" in workflow
    assert "-Version $version" in workflow


def test_current_architecture_docs_do_not_expose_absolute_machine_paths() -> None:
    exposed: list[str] = []
    for path in CURRENT_FACT_DOCS:
        for line_number, line in enumerate(
            path.read_text(encoding="utf-8").splitlines(), 1
        ):
            if ABSOLUTE_PATH_RE.search(line):
                exposed.append(f"{path.relative_to(ROOT)}:{line_number}")
    assert not exposed, "absolute machine paths found:\n" + "\n".join(exposed)


def test_all_fastapi_routes_are_registered_in_flow_map() -> None:
    api_source = (ROOT / "src" / "invoice_hub" / "api" / "app.py").read_text(
        encoding="utf-8"
    )
    flow_map = (
        ROOT / "docs" / "architecture" / "INTERFACES_AND_FLOWS.md"
    ).read_text(encoding="utf-8")
    route_pattern = re.compile(
        r'''@app\.(?:get|post|put|delete|patch|api_route)\(\s*["']([^"']+)["']'''
    )
    routes = sorted(set(route_pattern.findall(api_source)))
    missing = [route for route in routes if route not in flow_map]
    assert routes
    assert not missing, "INTERFACES_AND_FLOWS.md is missing routes:\n" + "\n".join(missing)
