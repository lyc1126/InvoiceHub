"""Phase 1 tests: company CRUD (trash/relocate/disk-rename/setup-subset/import-extras/open) and deep directory search."""

from __future__ import annotations

from pathlib import Path
from fastapi.testclient import TestClient
import pytest

from invoice_hub.api.app import create_app
from invoice_hub.monitoring.state import MonitorState, canonical_path
from invoice_hub.projections.summary import SUMMARY_HEADERS
from invoice_hub.services.background_sync import BackgroundSyncService
from invoice_hub.storage import atomic_write_json, write_csv_rows
from invoice_hub.targets import target_profile_for

SAME_ORIGIN = {"Origin": "http://testserver"}


@pytest.fixture
def app(tmp_path: Path, monkeypatch):
    monkeypatch.setattr(BackgroundSyncService, "run_background_diagnostics", lambda self, trigger="startup_sync": None)
    monkeypatch.setenv("INVOICE_HUB_DISABLE_OPEN", "1")
    return create_app(tmp_path)


@pytest.fixture
def client(app) -> TestClient:
    return TestClient(app)


def _rev(client: TestClient) -> int:
    return client.get("/api/v1/companies").json()["revision"]


def _make_company_root(base: Path, name: str = "示例公司") -> Path:
    root = base / name
    for sub in ("成本发票", "开具发票", "银行流水", "进项抵扣", "工资社保", "费用报销"):
        (root / sub).mkdir(parents=True, exist_ok=True)
    return root


def _register_company(client: TestClient, root: Path, name: str = "示例公司") -> str:
    res = client.post(
        "/api/v1/companies",
        headers=SAME_ORIGIN,
        json={"revision": _rev(client), "name": name, "root_dir": str(root), "taxpayer_periods": []},
    )
    assert res.status_code == 200, res.text
    return res.json()["company"]["id"]


def _summary_row(
    source: Path,
    *,
    seller: str = "默认销售方",
    buyer: str = "默认购买方",
    number: str = "10000000000000000001",
    date: str = "2026-06-15",
    amount: str = "1130.00",
    tax_rate: str = "0.13",
    invoice_type: str = "增值税专用发票",
    business_type: str = "标准电子发票",
    classification_status: str = "ok",
) -> dict[str, str]:
    row = {header: "" for header in SUMMARY_HEADERS}
    row.update(
        {
            "文件名": source.name,
            "文件路径": str(source),
            "文件类型": source.suffix.lstrip(".").upper(),
            "发票类型": invoice_type,
            "特定业务类型": business_type,
            "类型识别状态": classification_status,
            "发票号码": number,
            "开票时间": date,
            "销售方": seller,
            "购买方": buyer,
            "开票金额": amount,
            "税率": tax_rate,
            "除税价": "1000.00",
            "税金": "130.00",
        }
    )
    return row


# ---- 1. Company native recycle-bin trash -----------------------------------------------------


def test_company_trash_preview_confirm_and_preserve_external_folder(app, client, tmp_path: Path, monkeypatch) -> None:
    root = _make_company_root(tmp_path / "biz", "待删公司")
    (root / "成本发票" / "a.xml").write_text("<invoice />", encoding="utf-8")
    ext_dir = tmp_path / "external_docs"
    ext_dir.mkdir()
    (ext_dir / "keep.txt").write_text("do not delete", encoding="utf-8")

    company_id = _register_company(client, root, "待删公司")
    imp = client.post(
        f"/api/v1/companies/{company_id}/folders/import",
        headers=SAME_ORIGIN,
        json={"revision": _rev(client), "path": str(ext_dir), "label": "外部共享", "role": "general"},
    )
    assert imp.status_code == 200, imp.text

    # Preview returns accurate stats and lists external folder as untouched.
    preview = client.post(
        f"/api/v1/companies/{company_id}/trash-preview",
        headers=SAME_ORIGIN,
        json={"revision": _rev(client)},
    )
    assert preview.status_code == 200, preview.text
    plan = preview.json()
    assert plan["can_trash"] is True
    assert plan["file_count"] == 1
    assert plan["dir_count"] == 6
    assert len(plan["external_folders"]) == 1
    assert plan["external_folders"][0]["label"] == "外部共享"

    # Missing confirm or stale plan_hash must fail closed.
    bad_confirm = client.post(
        f"/api/v1/companies/{company_id}/trash",
        headers=SAME_ORIGIN,
        json={"revision": plan["revision"], "plan_hash": plan["plan_hash"], "confirm": False},
    )
    assert bad_confirm.status_code == 422

    bad_hash = client.post(
        f"/api/v1/companies/{company_id}/trash",
        headers=SAME_ORIGIN,
        json={"revision": plan["revision"], "plan_hash": "0" * 64, "confirm": True},
    )
    assert bad_hash.status_code == 409

    # Mock native trash transfer to verify only company root is trashed and external stays intact.
    trashed: list[Path] = []

    def fake_trash(path: Path) -> None:
        trashed.append(path)
        dest = tmp_path / "fake_recycle_bin" / path.name
        dest.parent.mkdir(parents=True, exist_ok=True)
        path.rename(dest)

    monkeypatch.setattr("invoice_hub.services.company_folders.move_to_trash", fake_trash)

    confirmed = client.post(
        f"/api/v1/companies/{company_id}/trash",
        headers=SAME_ORIGIN,
        json={"revision": plan["revision"], "plan_hash": plan["plan_hash"], "confirm": True},
    )
    assert confirmed.status_code == 200, confirmed.text
    assert confirmed.json()["deleted"] == company_id
    assert trashed == [root]
    assert not root.exists()
    assert (ext_dir / "keep.txt").read_text(encoding="utf-8") == "do not delete"
    assert client.get("/api/v1/companies").json()["companies"] == []


def test_company_trash_blocked_when_monitored(app, client, tmp_path: Path) -> None:
    root = _make_company_root(tmp_path / "biz", "监控中公司")
    company_id = _register_company(client, root, "监控中公司")
    app.state.invoice_hub.update_settings({"watch_dir": str(root / "成本发票")})

    preview = client.post(
        f"/api/v1/companies/{company_id}/trash-preview",
        headers=SAME_ORIGIN,
        json={"revision": _rev(client)},
    ).json()
    assert preview["can_trash"] is False
    assert "监控" in preview["blocked_reason"]

    denied = client.post(
        f"/api/v1/companies/{company_id}/trash",
        headers=SAME_ORIGIN,
        json={"revision": preview["revision"], "plan_hash": preview["plan_hash"], "confirm": True},
    )
    assert denied.status_code == 409
    assert root.is_dir()


# ---- 2. Company root relocation & atomic disk rename -----------------------------------------


def test_company_root_relocate_and_disk_rename_migrates_overrides(app, client, tmp_path: Path) -> None:
    root = _make_company_root(tmp_path / "biz", "旧名公司")
    ext_dir = tmp_path / "ext_keep"
    ext_dir.mkdir()
    company_id = _register_company(client, root, "旧名公司")
    client.post(
        f"/api/v1/companies/{company_id}/folders/import",
        headers=SAME_ORIGIN,
        json={"revision": _rev(client), "path": str(ext_dir), "label": "外部", "role": "general"},
    )

    # Seed a manual override inside 成本发票 to verify migration on disk rename.
    old_cost_dir = root / "成本发票"
    old_invoice = old_cost_dir / "demo.xml"
    old_invoice.write_text("<invoice />", encoding="utf-8")
    old_profile = target_profile_for(app.state.invoice_hub.config, old_cost_dir)
    old_state = MonitorState(old_profile)
    atomic_write_json(
        old_state.manual_overrides_file,
        {
            "version": 1,
            "items": {
                canonical_path(old_invoice): {
                    "source_path": canonical_path(old_invoice),
                    "fields": {"销售方": "手改销售方"},
                }
            },
        },
    )

    # Relocating onto own external folder must be rejected.
    bad_reloc = client.patch(
        f"/api/v1/companies/{company_id}",
        headers=SAME_ORIGIN,
        json={"revision": _rev(client), "root_dir": str(ext_dir)},
    )
    assert bad_reloc.status_code == 422

    # Atomic disk rename updates path and migrates manual_overrides.json.
    renamed = client.patch(
        f"/api/v1/companies/{company_id}",
        headers=SAME_ORIGIN,
        json={"revision": _rev(client), "rename_root_on_disk": True, "new_root_name": "新名公司"},
    )
    assert renamed.status_code == 200, renamed.text
    new_root = tmp_path / "biz" / "新名公司"
    assert not root.exists()
    assert new_root.is_dir()
    assert Path(renamed.json()["company"]["root_path"]) == new_root

    new_profile = target_profile_for(app.state.invoice_hub.config, new_root / "成本发票")
    new_overrides = MonitorState(new_profile).manual_overrides_file
    assert new_overrides.is_file()
    assert canonical_path(new_root / "成本发票" / "demo.xml") in new_overrides.read_text(encoding="utf-8")

    # Relocating to another existing folder works cleanly without moving disk files.
    relocated_dir = _make_company_root(tmp_path / "biz", "迁移目标公司")
    reloc = client.patch(
        f"/api/v1/companies/{company_id}",
        headers=SAME_ORIGIN,
        json={"revision": _rev(client), "root_dir": str(relocated_dir)},
    )
    assert reloc.status_code == 200, reloc.text
    assert Path(reloc.json()["company"]["root_path"]) == relocated_dir
    assert new_root.is_dir()


# ---- 3. New workspace subset + custom folders & existing folder extra discovery --------------


def test_setup_selected_standard_subset_and_custom_folders(client, tmp_path: Path) -> None:
    parent = tmp_path / "workspaces"
    parent.mkdir()
    planned = client.post(
        "/api/v1/companies/setup-jobs",
        headers=SAME_ORIGIN,
        json={
            "revision": _rev(client),
            "name": "精简公司",
            "parent_dir": str(parent),
            "folder_name": "精简公司",
            "selected_standard_keys": ["cost_invoice_dir", "issued_invoice_dir"],
            "custom_folders": [{"label": "项目合同", "relative_path": "项目合同", "role": "general"}],
            "taxpayer_periods": [],
        },
    )
    assert planned.status_code == 200, planned.text
    job = planned.json()
    assert [item["relative_path"] for item in job["items"]] == ["成本发票", "开具发票", "项目合同"]

    done = client.post(
        f"/api/v1/companies/setup-jobs/{job['job_id']}/confirm",
        headers=SAME_ORIGIN,
        json={"confirm": True, "plan_hash": job["plan_hash"]},
    )
    assert done.status_code == 200, done.text
    company = done.json()["company"]
    root = parent / "精简公司"
    assert (root / "成本发票").is_dir()
    assert (root / "开具发票").is_dir()
    assert (root / "项目合同").is_dir()
    assert not (root / "银行流水").exists()
    hidden_keys = {item["key"] for item in company["subdirs"] if item.get("hidden")}
    assert hidden_keys == {"bank_flow_dir", "input_deduction_dir", "payroll_social_dir", "expense_reimbursement_dir"}
    customs = [item for item in company["subdirs"] if item.get("kind") == "custom"]
    assert len(customs) == 1 and customs[0]["label"] == "项目合同" and customs[0]["role"] == "general"


def test_detect_discovers_extra_folders_and_registers_selected_ones(client, tmp_path: Path) -> None:
    root = _make_company_root(tmp_path / "existing", "老客户")
    (root / "专项成本发票").mkdir()
    (root / "专项成本发票" / "inv.pdf").write_bytes(b"%PDF-1.4")
    (root / "其他文档").mkdir()
    (root / "做账草稿").mkdir()  # excluded internal bookkeeping folder
    (root / ".hidden").mkdir()  # excluded hidden folder

    detected = client.post("/api/v1/companies/detect", headers=SAME_ORIGIN, json={"root_dir": str(root)})
    assert detected.status_code == 200, detected.text
    payload = detected.json()
    extras = {item["relative_path"]: item for item in payload["extra_folders"]}
    assert set(extras) == {"专项成本发票", "其他文档"}
    assert extras["专项成本发票"]["file_count"] == 1
    assert extras["专项成本发票"]["suggested_role"] == "cost_invoice_dir"

    reg = client.post(
        "/api/v1/companies",
        headers=SAME_ORIGIN,
        json={
            "revision": _rev(client),
            "name": "老客户",
            "root_dir": str(root),
            "plan_hash": payload["plan_hash"],
            "create_missing": [],
            "import_extra_folders": [{"relative_path": "专项成本发票", "label": "专项成本发票", "role": "cost_invoice_dir"}],
            "taxpayer_periods": [],
        },
    )
    assert reg.status_code == 200, reg.text
    customs = [item for item in reg.json()["company"]["subdirs"] if item.get("kind") == "custom"]
    assert len(customs) == 1 and customs[0]["relative_path"] == "专项成本发票" and customs[0]["role"] == "cost_invoice_dir"


def test_open_company_root_and_folder_endpoints(client, tmp_path: Path) -> None:
    root = _make_company_root(tmp_path / "biz", "打开测试")
    company_id = _register_company(client, root, "打开测试")
    r1 = client.post(f"/api/v1/companies/{company_id}/open-root", headers=SAME_ORIGIN)
    assert r1.status_code == 200 and r1.json()["opened"] is True
    r2 = client.post(f"/api/v1/companies/{company_id}/folders/cost_invoice_dir/open", headers=SAME_ORIGIN)
    assert r2.status_code == 200 and r2.json()["opened"] is True


# ---- 4. Deep single-directory search, bug fixes & multi-column sorting -----------------------


def test_directory_deep_search_buyer_multitoken_date_amount_tax_project_and_sort(app, client, tmp_path: Path) -> None:
    root = _make_company_root(tmp_path / "search_biz", "检索公司")
    company_id = _register_company(client, root, "检索公司")
    issued_dir = root / "开具发票"

    files = [issued_dir / name for name in ("a.pdf", "b.xml", "c.ofd", "dup.pdf", "nodate.pdf")]
    for f in files:
        f.write_text("dummy", encoding="utf-8")

    rows = [
        _summary_row(
            files[0],
            seller="检索公司",
            buyer="华星建设集团",
            number="20000000000000000001",
            date="2026-05-10",
            amount="11300.00",
            tax_rate="0.13",
            invoice_type="增值税专用发票",
        ),
        _summary_row(
            files[1],
            seller="检索公司",
            buyer="天明科技有限",
            number="20000000000000000002",
            date="2026-06-20",
            amount="2060.00",
            tax_rate="0.03",
            invoice_type="增值税普通发票",
            business_type="数电票",
        ),
        _summary_row(
            files[2],
            seller="检索公司",
            buyer="华星建设集团",
            number="20000000000000000003",
            date="2026-07-01",
            amount="500.00",
            tax_rate="免税",
            invoice_type="增值税普通发票",
        ),
        # Duplicate of first invoice number
        _summary_row(
            files[3],
            seller="检索公司",
            buyer="华星建设集团",
            number="20000000000000000001",
            date="2026-05-10",
            amount="11300.00",
            tax_rate="0.13",
        ),
        # Undated / missing amount / missing tax rate row
        _summary_row(
            files[4],
            seller="检索公司",
            buyer="缺项单位",
            number="20000000000000000005",
            date="",
            amount="",
            tax_rate="",
            classification_status="needs_review",
        ),
    ]
    profile = target_profile_for(app.state.invoice_hub.config, issued_dir)
    Path(profile.workspace_dir).mkdir(parents=True, exist_ok=True)
    write_csv_rows(Path(profile.workspace_dir) / "发票汇总.csv", SUMMARY_HEADERS, rows)

    # Assign manual project to invoice 20000000000000000002.
    proj_save = client.put(
        f"/api/v1/companies/{company_id}/projects/assignments",
        headers=SAME_ORIGIN,
        json={"revision": 0, "assignments": {"20000000000000000002": "南通大桥项目"}},
    )
    assert proj_save.status_code == 200, proj_save.text

    url = f"/api/v1/companies/{company_id}/directories/issued_invoice_dir/invoices"

    # Bug #1 fix: searching buyer in issued_invoice_dir works under workspace & buyer scopes.
    by_buyer = client.get(url, params={"keyword": "天明科技", "search_scope": "workspace"}).json()
    assert [item["source_file"] for item in by_buyer["items"]] == ["b.xml"]
    by_buyer_only = client.get(url, params={"keyword": "天明科技", "search_scope": "buyer"}).json()
    assert [item["source_file"] for item in by_buyer_only["items"]] == ["b.xml"]

    # Bug #3 fix: whitespace multi-token AND search across buyer + formatted tax_rate / project.
    multi = client.get(url, params={"keyword": "华星 13%", "search_scope": "workspace"}).json()
    assert {item["source_file"] for item in multi["items"]} == {"a.pdf", "dup.pdf"}
    by_proj_kw = client.get(url, params={"keyword": "南通大桥 2060", "search_scope": "workspace"}).json()
    assert [item["source_file"] for item in by_proj_kw["items"]] == ["b.xml"]

    # Bug #2 fix: date_from/date_to must exclude undated rows (nodate.pdf).
    dated = client.get(url, params={"date_from": "2026-05-01", "date_to": "2026-06-30"}).json()
    assert {item["source_file"] for item in dated["items"]} == {"a.pdf", "b.xml", "dup.pdf"}

    # Amount range (exact Decimal, excludes missing amount, rejects invalid text).
    amt = client.get(url, params={"amount_min": "1000", "amount_max": "5000"}).json()
    assert [item["source_file"] for item in amt["items"]] == ["b.xml"]
    assert client.get(url, params={"amount_min": "abc"}).status_code == 422
    assert client.get(url, params={"amount_min": "5000", "amount_max": "1000"}).status_code == 422

    # Tax rate normalization + missing tax rate.
    rate_3 = client.get(url, params={"tax_rate": "3%"}).json()
    assert [item["source_file"] for item in rate_3["items"]] == ["b.xml"]
    rate_missing = client.get(url, params={"tax_rate": "__missing__"}).json()
    assert [item["source_file"] for item in rate_missing["items"]] == ["nodate.pdf"]

    # Project filter (exact & unassigned) updates filtered stats accurately.
    proj_hit = client.get(url, params={"project": "南通大桥项目"}).json()
    assert [item["source_file"] for item in proj_hit["items"]] == ["b.xml"]
    assert proj_hit["stats"]["filtered"]["total_amount"] == "2060.00"
    proj_unassigned = client.get(url, params={"project": "__unassigned__"}).json()
    assert "b.xml" not in {item["source_file"] for item in proj_unassigned["items"]}

    # Duplicate status filter.
    dups = client.get(url, params={"status": "重复发票"}).json()
    assert [item["source_file"] for item in dups["items"]] == ["dup.pdf"]

    # Numeric amount sorting (missing amounts always last).
    sorted_desc = client.get(url, params={"sort_by": "amount", "sort_dir": "desc"}).json()
    assert [item["source_file"] for item in sorted_desc["items"]] == ["a.pdf", "dup.pdf", "b.xml", "c.ofd", "nodate.pdf"]
    sorted_asc = client.get(url, params={"sort_by": "amount", "sort_dir": "asc"}).json()
    assert [item["source_file"] for item in sorted_asc["items"]] == ["c.ofd", "b.xml", "a.pdf", "dup.pdf", "nodate.pdf"]

    # filter_options remains populated from all rows even when filters match 0 rows.
    empty = client.get(url, params={"keyword": "不存在关键词", "search_scope": "workspace"}).json()
    assert empty["count"] == 0
    assert "南通大桥项目" in empty["filter_options"]["projects"]
    assert set(empty["filter_options"]["tax_rates"]) == {"3%", "13%", "免税"}
    assert empty["filter_options"]["has_missing_tax_rate"] is True
    assert empty["filter_options"]["has_duplicates"] is True


def test_company_disk_rename_validates_complete_update_before_renaming_root(client, tmp_path: Path) -> None:
    root = _make_company_root(tmp_path, "原公司根")
    (root / "合同归档").mkdir()
    company_id = _register_company(client, root, "原公司根")

    # Add an inside-root custom folder so we can trigger a subdirs overlap validation error.
    imp = client.post(
        f"/api/v1/companies/{company_id}/folders/import",
        headers=SAME_ORIGIN,
        json={"revision": _rev(client), "relative_path": "合同归档", "label": "合同归档", "role": "general"},
    )
    assert imp.status_code == 200, imp.text

    # 1) Disk rename combined with invalid subdirs (overlapping custom folder) must reject BEFORE renaming disk.
    bad_subdirs = client.patch(
        f"/api/v1/companies/{company_id}",
        headers=SAME_ORIGIN,
        json={
            "revision": _rev(client),
            "rename_root_on_disk": True,
            "new_root_name": "不应改名一",
            "subdirs": {"cost_invoice_dir": "合同归档"},
        },
    )
    assert bad_subdirs.status_code == 422
    assert root.is_dir()
    assert not (tmp_path / "不应改名一").exists()
    assert client.get(f"/api/v1/companies/{company_id}").json()["company"]["root_path"] == str(root.resolve())

    # 2) Disk rename combined with duplicate taxpayer effective months must reject BEFORE renaming disk.
    bad_tax = client.patch(
        f"/api/v1/companies/{company_id}",
        headers=SAME_ORIGIN,
        json={
            "revision": _rev(client),
            "rename_root_on_disk": True,
            "new_root_name": "不应改名二",
            "taxpayer_periods": [
                {"effective_from": "2026-01", "taxpayer_type": "general"},
                {"effective_from": "2026-01", "taxpayer_type": "small_scale"},
            ],
        },
    )
    assert bad_tax.status_code == 422
    assert root.is_dir()
    assert not (tmp_path / "不应改名二").exists()
    assert client.get(f"/api/v1/companies/{company_id}").json()["company"]["root_path"] == str(root.resolve())
