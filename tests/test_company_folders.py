"""Tests for custom & standard company folder management and role-based functional dispatch."""

from __future__ import annotations

import json
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from invoice_hub.api.app import create_app
from invoice_hub.targets.companies import company_for_dir, company_taxpayer_for, read_registry_companies
from test_summary_and_costs import _xml_invoice

SAME_ORIGIN = {"Origin": "http://127.0.0.1:8766"}


@pytest.fixture
def env(tmp_path, monkeypatch):
    monkeypatch.setattr(
        "invoice_hub.services.background_sync.BackgroundSyncService.run_background_diagnostics",
        lambda *args, **kwargs: None,
    )
    watch = tmp_path / "默认监控目录"
    watch.mkdir()
    app = create_app(tmp_path)
    app.state.invoice_hub.update_settings({"watch_dir": str(watch)})
    with TestClient(app, base_url="http://127.0.0.1:8766") as client:
        yield app, client, tmp_path


def _register(client: TestClient, root: Path, name: str = "示例公司", revision: int = 0) -> tuple[str, int]:
    res = client.post(
        "/api/v1/companies",
        json={
            "name": name,
            "root_dir": str(root),
            "revision": revision,
            "taxpayer_periods": [{"effective_from": "2020-01", "taxpayer_type": "general"}],
        },
        headers=SAME_ORIGIN,
    )
    assert res.status_code == 200, res.text
    payload = res.json()
    return payload["company"]["id"], payload["revision"]


def _rev(client: TestClient, cid: str) -> int:
    res = client.get(f"/api/v1/companies/{cid}")
    assert res.status_code == 200, res.text
    return res.json()["revision"]


def test_discover_and_create_custom_folder_inside_company_root(env):
    _app, client, tmp_path = env
    root = tmp_path / "客户" / "甲公司"
    (root / "成本发票").mkdir(parents=True)
    (root / "开具发票").mkdir(parents=True)
    (root / "费用报销").mkdir(parents=True)
    (root / "专项报销单据").mkdir(parents=True)
    (root / "其他归档").mkdir(parents=True)
    (root / "做账草稿").mkdir(parents=True)  # bookkeeping system dir: excluded from discovery
    (root / ".hidden").mkdir(parents=True)
    cid, rev = _register(client, root)

    disc = client.get(f"/api/v1/companies/{cid}/folders/discover")
    assert disc.status_code == 200, disc.text
    candidates = {item["relative_path"]: item for item in disc.json()["candidates"]}
    assert set(candidates) == {"专项报销单据", "其他归档"}
    assert candidates["专项报销单据"]["suggested_role"] == "expense_reimbursement_dir"
    assert candidates["其他归档"]["suggested_role"] == "general"

    # Preview creating a new empty custom folder.
    preview = client.post(
        f"/api/v1/companies/{cid}/folders/create/preview",
        json={"revision": rev, "label": "临时验收副本", "role": "cost_invoice_dir"},
        headers=SAME_ORIGIN,
    )
    assert preview.status_code == 200, preview.text
    plan = preview.json()
    assert plan["action"] == "create"
    assert plan["relative_path"] == "临时验收副本"
    assert not (root / "临时验收副本").exists()

    # Wrong plan_hash is rejected.
    stale = client.post(
        f"/api/v1/companies/{cid}/folders/create",
        json={"revision": rev, "label": "临时验收副本", "role": "cost_invoice_dir", "confirm": True, "plan_hash": "0" * 64},
        headers=SAME_ORIGIN,
    )
    assert stale.status_code == 409

    # Confirm creates empty folder and registers custom entry.
    created = client.post(
        f"/api/v1/companies/{cid}/folders/create",
        json={
            "revision": rev,
            "label": "临时验收副本",
            "role": "cost_invoice_dir",
            "confirm": True,
            "plan_hash": plan["plan_hash"],
        },
        headers=SAME_ORIGIN,
    )
    assert created.status_code == 200, created.text
    folder_id = created.json()["folder_id"]
    assert (root / "临时验收副本").is_dir()
    entry = next(item for item in created.json()["company"]["subdirs"] if item["key"] == folder_id)
    assert entry["kind"] == "custom"
    assert entry["role"] == "cost_invoice_dir"
    assert entry["location"] == "inside_root"
    assert entry["can_promote_to_role"] is True


def test_import_in_root_and_external_folders_and_company_taxpayer_resolution(env):
    app, client, tmp_path = env
    root = tmp_path / "客户" / "甲公司"
    (root / "成本发票").mkdir(parents=True)
    in_root_extra = root / "补充成本"
    in_root_extra.mkdir(parents=True)
    external = tmp_path / "独立外部资料夹" / "外挂进项"
    external.mkdir(parents=True)
    (external / "inv1.xml").write_text(
        _xml_invoice("30000000000000000001", "外部供应方", "甲公司", [("12E", "2", "300.00", "39.00", "钢筋")]),
        encoding="utf-8",
    )
    cid, rev = _register(client, root)

    # Import in-root folder by path -> automatically classified as inside_root.
    r1 = client.post(
        f"/api/v1/companies/{cid}/folders/import",
        json={"revision": rev, "path": str(in_root_extra), "role": "cost_invoice_dir"},
        headers=SAME_ORIGIN,
    )
    assert r1.status_code == 200, r1.text
    in_id = r1.json()["folder_id"]
    in_entry = next(item for item in r1.json()["company"]["subdirs"] if item["key"] == in_id)
    assert in_entry["location"] == "inside_root"
    assert in_entry["relative_path"] == "补充成本"

    # Import external folder outside company root -> classified as external.
    rev = r1.json()["revision"]
    r2 = client.post(
        f"/api/v1/companies/{cid}/folders/import",
        json={"revision": rev, "path": str(external), "label": "外部挂接进项", "role": "cost_invoice_dir"},
        headers=SAME_ORIGIN,
    )
    assert r2.status_code == 200, r2.text
    ext_id = r2.json()["folder_id"]
    ext_entry = next(item for item in r2.json()["company"]["subdirs"] if item["key"] == ext_id)
    assert ext_entry["location"] == "external"
    assert ext_entry["can_promote_to_role"] is False
    assert (external / "inv1.xml").is_file()

    # Duplicate/overlapping external import is rejected.
    dup = client.post(
        f"/api/v1/companies/{cid}/folders/import",
        json={"revision": r2.json()["revision"], "path": str(external), "role": "general"},
        headers=SAME_ORIGIN,
    )
    assert dup.status_code == 422

    # Another company cannot register a root overlapping this external folder.
    overlap_company = client.post(
        "/api/v1/companies",
        json={"name": "冲突公司", "root_dir": str(external), "revision": r2.json()["revision"], "taxpayer_periods": []},
        headers=SAME_ORIGIN,
    )
    assert overlap_company.status_code == 422

    # Cross-process lookup & monitored_subdir_key recognize the external folder as belonging to 甲公司.
    companies = read_registry_companies(app.state.invoice_hub.companies.registry_path)
    matched = company_for_dir(companies, app.state.invoice_hub.config.root_dir, external)
    assert matched is not None and matched["id"] == cid
    taxpayer = company_taxpayer_for(app.state.invoice_hub.config, external)
    assert taxpayer is not None and taxpayer["company_id"] == cid and taxpayer["taxpayer_type"] == "general"

    app.state.invoice_hub.update_settings({"watch_dir": str(external)})
    comp = client.get(f"/api/v1/companies/{cid}").json()["company"]
    assert comp["monitored"] is True
    assert comp["monitored_subdir_key"] == ext_id


def test_rename_hide_restore_trash_and_promote_lifecycle(env, monkeypatch):
    app, client, tmp_path = env
    root = tmp_path / "客户" / "乙公司"
    (root / "成本发票").mkdir(parents=True)
    (root / "开具发票").mkdir(parents=True)
    (root / "补充成本").mkdir(parents=True)
    (root / "补充成本" / "keep.txt").write_text("hello", encoding="utf-8")
    cid, rev = _register(client, root, name="乙公司")

    # Import custom folder.
    imp = client.post(
        f"/api/v1/companies/{cid}/folders/import",
        json={"revision": rev, "relative_path": "补充成本", "label": "补充成本", "role": "cost_invoice_dir"},
        headers=SAME_ORIGIN,
    )
    assert imp.status_code == 200, imp.text
    fid = imp.json()["folder_id"]

    # Rename label + disk folder for custom folder, and change role.
    upd = client.post(
        f"/api/v1/companies/{cid}/folders/{fid}/update",
        json={
            "revision": imp.json()["revision"],
            "label": "二期成本",
            "role": "issued_invoice_dir",
            "rename_disk": True,
            "new_relative_path": "二期成本",
        },
        headers=SAME_ORIGIN,
    )
    assert upd.status_code == 200, upd.text
    assert upd.json()["disk_renamed"] is True
    assert not (root / "补充成本").exists()
    assert (root / "二期成本" / "keep.txt").read_text(encoding="utf-8") == "hello"

    # Rename a standard folder on disk + display label.
    std_upd = client.post(
        f"/api/v1/companies/{cid}/folders/cost_invoice_dir/update",
        json={
            "revision": upd.json()["revision"],
            "label": "主进项",
            "rename_disk": True,
            "new_relative_path": "主进项发票",
        },
        headers=SAME_ORIGIN,
    )
    assert std_upd.status_code == 200, std_upd.text
    assert (root / "主进项发票").is_dir()
    std_item = next(item for item in std_upd.json()["company"]["subdirs"] if item["key"] == "cost_invoice_dir")
    assert std_item["label"] == "主进项" and std_item["relative_path"] == "主进项发票"

    # Hide standard folder (non-destructive) -> excluded from missing_subdir_count & default subdir_plan -> restore.
    hid = client.post(
        f"/api/v1/companies/{cid}/folders/payroll_social_dir/remove",
        json={"revision": std_upd.json()["revision"]},
        headers=SAME_ORIGIN,
    )
    assert hid.status_code == 200, hid.text
    assert hid.json()["files_touched"] == 0
    payroll_entry = next(item for item in hid.json()["company"]["subdirs"] if item["key"] == "payroll_social_dir")
    assert payroll_entry["hidden"] is True
    plan = client.get(f"/api/v1/companies/{cid}/subdirs/plan").json()
    assert all(item["key"] != "payroll_social_dir" for item in plan["items"])

    restored = client.post(
        f"/api/v1/companies/{cid}/folders/payroll_social_dir/restore",
        json={"revision": hid.json()["revision"]},
        headers=SAME_ORIGIN,
    )
    assert restored.status_code == 200, restored.text
    payroll_entry2 = next(item for item in restored.json()["company"]["subdirs"] if item["key"] == "payroll_social_dir")
    assert payroll_entry2["hidden"] is False

    # Promote in-root custom folder (role=issued_invoice_dir) to become standard issued_invoice_dir,
    # automatically preserving the previous existing 开具发票 folder as a custom folder.
    prom = client.post(
        f"/api/v1/companies/{cid}/folders/{fid}/promote",
        json={"revision": restored.json()["revision"], "keep_previous_as_custom": True},
        headers=SAME_ORIGIN,
    )
    assert prom.status_code == 200, prom.text
    assert prom.json()["promoted_to"] == "issued_invoice_dir"
    preserved_id = prom.json()["preserved_folder_id"]
    assert preserved_id
    by_key = {item["key"]: item for item in prom.json()["company"]["subdirs"]}
    assert by_key["issued_invoice_dir"]["relative_path"] == "二期成本"
    assert by_key[preserved_id]["relative_path"] == "开具发票"

    # Trash guard: monitored folder is blocked from trashing.
    app.state.invoice_hub.update_settings({"watch_dir": str(root / "开具发票")})
    blocked_prev = client.post(
        f"/api/v1/companies/{cid}/folders/{preserved_id}/trash/preview",
        json={"revision": prom.json()["revision"]},
        headers=SAME_ORIGIN,
    )
    assert blocked_prev.status_code == 200
    assert blocked_prev.json()["can_trash"] is False

    # Switch monitor away, then preview + confirm native move_to_trash (monkeypatched to simulate recycle bin).
    app.state.invoice_hub.update_settings({"watch_dir": str(tmp_path / "默认监控目录")})
    trashed_targets: list[Path] = []

    def fake_trash(path: Path) -> None:
        trashed_targets.append(path)
        import shutil
        shutil.rmtree(path)

    monkeypatch.setattr("invoice_hub.services.company_folders.move_to_trash", fake_trash)
    tprev = client.post(
        f"/api/v1/companies/{cid}/folders/{preserved_id}/trash/preview",
        json={"revision": prom.json()["revision"]},
        headers=SAME_ORIGIN,
    )
    assert tprev.status_code == 200, tprev.text
    assert tprev.json()["can_trash"] is True
    trashed = client.post(
        f"/api/v1/companies/{cid}/folders/{preserved_id}/trash",
        json={"revision": prom.json()["revision"], "plan_hash": tprev.json()["plan_hash"], "confirm": True},
        headers=SAME_ORIGIN,
    )
    assert trashed.status_code == 200, trashed.text
    assert trashed_targets == [root / "开具发票"]
    assert not (root / "开具发票").exists()
    assert all(item["key"] != preserved_id for item in trashed.json()["company"]["subdirs"])

    # Also test trashing a standard folder leaves the slot in missing state when also_unregister=False.
    sprev = client.post(
        f"/api/v1/companies/{cid}/folders/cost_invoice_dir/trash/preview",
        json={"revision": trashed.json()["revision"]},
        headers=SAME_ORIGIN,
    )
    assert sprev.json()["can_trash"] is True
    strashed = client.post(
        f"/api/v1/companies/{cid}/folders/cost_invoice_dir/trash",
        json={"revision": trashed.json()["revision"], "plan_hash": sprev.json()["plan_hash"], "confirm": True, "also_unregister": False},
        headers=SAME_ORIGIN,
    )
    assert strashed.status_code == 200, strashed.text
    cost_slot = next(item for item in strashed.json()["company"]["subdirs"] if item["key"] == "cost_invoice_dir")
    assert cost_slot["status"] == "missing" and cost_slot["hidden"] is False


def test_custom_folder_role_dispatch_isolated_from_company_ledger(env):
    app, client, tmp_path = env
    root = tmp_path / "客户" / "丙公司"
    for std in ("成本发票", "开具发票", "进项抵扣", "银行流水", "工资社保"):
        (root / std).mkdir(parents=True)
    (root / "成本发票" / "std_in.xml").write_text(
        _xml_invoice("40000000000000000001", "标准供应方", "丙公司", [("12E", "1", "100.00", "13.00", "钢筋")]),
        encoding="utf-8",
    )
    custom_in = tmp_path / "外部临时目录" / "测试进项副本"
    custom_in.mkdir(parents=True)
    (custom_in / "ext_in.xml").write_text(
        _xml_invoice("40000000000000000001", "测试供应方", "丙公司", [("12E", "5", "999.00", "129.87", "钢筋")]),
        encoding="utf-8",
    )
    custom_deduct = root / "自定义抵扣清单"
    custom_deduct.mkdir(parents=True)
    custom_bank = root / "专户流水"
    custom_bank.mkdir(parents=True)
    custom_payroll = root / "补充社保"
    custom_payroll.mkdir(parents=True)

    cid, rev = _register(client, root, name="丙公司")

    # Import 4 custom folders with distinct benchmark roles.
    res_in = client.post(
        f"/api/v1/companies/{cid}/folders/import",
        json={"revision": rev, "path": str(custom_in), "label": "外部测试进项", "role": "cost_invoice_dir"},
        headers=SAME_ORIGIN,
    )
    assert res_in.status_code == 200, res_in.text
    ext_in_id = res_in.json()["folder_id"]

    res_ded = client.post(
        f"/api/v1/companies/{cid}/folders/import",
        json={"revision": res_in.json()["revision"], "relative_path": "自定义抵扣清单", "role": "input_deduction_dir"},
        headers=SAME_ORIGIN,
    )
    assert res_ded.status_code == 200, res_ded.text
    ded_id = res_ded.json()["folder_id"]

    res_bank = client.post(
        f"/api/v1/companies/{cid}/folders/import",
        json={"revision": res_ded.json()["revision"], "relative_path": "专户流水", "role": "bank_flow_dir"},
        headers=SAME_ORIGIN,
    )
    assert res_bank.status_code == 200, res_bank.text
    bank_id = res_bank.json()["folder_id"]

    res_pay = client.post(
        f"/api/v1/companies/{cid}/folders/import",
        json={"revision": res_bank.json()["revision"], "relative_path": "补充社保", "role": "payroll_social_dir"},
        headers=SAME_ORIGIN,
    )
    assert res_pay.status_code == 200, res_pay.text
    pay_id = res_pay.json()["folder_id"]

    # Refresh standard + custom invoice folder; external folder gets workspace-only generation (source untouched).
    job = app.state.invoice_hub.company_views.refresh.start(cid, wait=True)
    assert job["status"] == "completed", job
    assert job["directories"][ext_in_id]["status"] == "done"
    assert job["directories"][ext_in_id]["count"] == 1
    assert not (custom_in / "成本发票明细.csv").exists()

    # Single-directory invoice list reads the custom external folder cleanly.
    listed = client.get(f"/api/v1/companies/{cid}/directories/{ext_in_id}/invoices")
    assert listed.status_code == 200, listed.text
    assert listed.json()["count"] == 1
    assert listed.json()["items"][0]["invoice_number"] == "40000000000000000001"

    # Company ledger MUST remain isolated (only standard 成本发票 = 100.00, NOT polluted by external 999.00!).
    ledger = client.get(f"/api/v1/companies/{cid}/ledger").json()
    assert ledger["totals"]["input"]["count"] == 1
    assert ledger["totals"]["input"]["total"] == "113.00"

    # Same-number comparison works between standard cost_invoice_dir and custom external cost_invoice_dir!
    same = client.get(f"/api/v1/companies/{cid}/same-number", params={"a": "cost_invoice_dir", "b": ext_in_id})
    assert same.status_code == 200, same.text
    assert [item["number"] for item in same.json()["matches"]] == ["40000000000000000001"]

    # Period-folder check works for custom input_deduction_dir and bank_flow_dir roles.
    p_ded = client.get(f"/api/v1/companies/{cid}/period-folders", params={"key": ded_id})
    assert p_ded.status_code == 200, p_ded.text
    assert p_ded.json()["role"] == "input_deduction_dir"

    p_bank = client.get(f"/api/v1/companies/{cid}/period-folders", params={"key": bank_id})
    assert p_bank.status_code == 200, p_bank.text
    assert p_bank.json()["role"] == "bank_flow_dir"

    # Bank layouts index accepts custom bank_flow_dir dir_key.
    bl = client.get(f"/api/v1/companies/{cid}/bank-layouts", params={"files": 1, "dir_key": bank_id})
    assert bl.status_code == 200, bl.text
    assert bl.json()["dir_key"] == bank_id

    # Payroll read accepts custom payroll_social_dir dir_key, and rejects wrong role.
    pr = client.get(f"/api/v1/companies/{cid}/payroll", params={"dir_key": pay_id})
    assert pr.status_code == 200, pr.text
    assert pr.json()["dir_key"] == pay_id and pr.json()["folder_present"] is True
    bad_pr = client.get(f"/api/v1/companies/{cid}/payroll", params={"dir_key": ext_in_id})
    assert bad_pr.status_code == 422


def test_corrupt_custom_folders_in_registry_fails_closed(env):
    app, client, tmp_path = env
    root = tmp_path / "客户" / "丁公司"
    (root / "成本发票").mkdir(parents=True)
    _cid, _rev = _register(client, root, name="丁公司")
    reg_path = app.state.invoice_hub.companies.registry_path
    data = json.loads(reg_path.read_text(encoding="utf-8"))
    data["companies"][0]["custom_folders"] = [{"id": "bad_id", "label": "坏数据", "role": "general", "location": "inside_root", "relative_path": "x", "external_path": ""}]
    reg_path.write_text(json.dumps(data, ensure_ascii=False), encoding="utf-8")

    res = client.get("/api/v1/companies")
    assert res.status_code == 409
    assert res.json()["error"]["code"] == "COMPANY_REGISTRY_CORRUPT"


def test_post_import_linked_external_folder_and_parent_are_rejected_without_following(env):
    """P1 guard: replacing an imported external folder (or its parent) with a symlink must never follow the link."""
    import os
    import shutil

    app, client, tmp_path = env
    root = tmp_path / "客户" / "戊公司"
    (root / "成本发票").mkdir(parents=True)
    cid, rev = _register(client, root, name="戊公司")

    ext_parent = tmp_path / "外部挂载容器"
    ext_dir = ext_parent / "外部原目录"
    ext_dir.mkdir(parents=True)
    unregistered = tmp_path / "未登记机密目录"
    unregistered.mkdir()
    (unregistered / "secret.txt").write_text("keep-me", encoding="utf-8")

    # 0. Importing through a linked parent directory must be rejected at import time.
    link_parent = tmp_path / "软链父目录"
    try:
        os.symlink(unregistered, link_parent, target_is_directory=True)
    except OSError:
        pytest.skip("symlinks unavailable in this environment")
    (unregistered / "child").mkdir()
    blocked_import = client.post(
        f"/api/v1/companies/{cid}/folders/import",
        json={"path": str(link_parent / "child"), "role": "general", "revision": rev},
        headers=SAME_ORIGIN,
    )
    assert blocked_import.status_code == 422

    # 1. Import genuine external folder, then replace leaf with symlink to unregistered target.
    imp = client.post(
        f"/api/v1/companies/{cid}/folders/import",
        json={"path": str(ext_dir), "label": "外部目录", "role": "cost_invoice_dir", "revision": rev},
        headers=SAME_ORIGIN,
    )
    assert imp.status_code == 200, imp.text
    fid, rev = imp.json()["folder_id"], imp.json()["revision"]

    ext_dir.rmdir()
    os.symlink(unregistered, ext_dir, target_is_directory=True)

    # Public view reports outside_root (never present) and preserves the registered path (not target).
    comp = client.get(f"/api/v1/companies/{cid}").json()["company"]
    sub = next(s for s in comp["subdirs"] if s["key"] == fid)
    assert sub["status"] == "outside_root"
    assert str(unregistered) not in sub["path"]

    # Trash preview MUST block (can_trash=False) and never inspect or target the unregistered directory.
    tp = client.post(f"/api/v1/companies/{cid}/folders/{fid}/trash/preview", json={"revision": rev}, headers=SAME_ORIGIN)
    assert tp.status_code == 200, tp.text
    assert tp.json()["can_trash"] is False
    assert tp.json()["file_count"] == 0
    assert str(unregistered) not in tp.json()["path"]

    # Disk rename MUST reject with 409 without touching the unregistered directory.
    ren = client.post(
        f"/api/v1/companies/{cid}/folders/{fid}/update",
        json={"label": "试图改名", "rename_disk": True, "new_name": "改名后", "revision": rev},
        headers=SAME_ORIGIN,
    )
    assert ren.status_code == 409
    assert unregistered.is_dir() and (unregistered / "secret.txt").exists()

    # Cross-process lookup company_for_dir MUST NOT adopt the unregistered symlink target.
    companies = read_registry_companies(app.state.invoice_hub.companies.registry_path)
    assert company_for_dir(companies, app.state.invoice_hub.config.root_dir, unregistered) is None

    # 2. Restore leaf as real dir, then replace its parent directory with a symlink to a fake parent.
    ext_dir.unlink()
    fake_parent = tmp_path / "假容器"
    (fake_parent / "外部原目录").mkdir(parents=True)
    shutil.rmtree(ext_parent)
    os.symlink(fake_parent, ext_parent, target_is_directory=True)

    comp2 = client.get(f"/api/v1/companies/{cid}").json()["company"]
    sub2 = next(s for s in comp2["subdirs"] if s["key"] == fid)
    assert sub2["status"] == "outside_root"
    tp2 = client.post(f"/api/v1/companies/{cid}/folders/{fid}/trash/preview", json={"revision": rev}, headers=SAME_ORIGIN)
    assert tp2.status_code == 200 and tp2.json()["can_trash"] is False
    companies2 = read_registry_companies(app.state.invoice_hub.companies.registry_path)
    assert company_for_dir(companies2, app.state.invoice_hub.config.root_dir, fake_parent / "外部原目录") is None


def test_custom_payroll_preview_excludes_company_saved_months(env):
    """P2 guard: custom payroll_social_dir previews must not mix in company-wide 申报数据.json months."""
    _app, client, tmp_path = env
    root = tmp_path / "客户" / "己公司"
    (root / "成本发票").mkdir(parents=True)
    (root / "工资社保").mkdir(parents=True)
    (root / "做账草稿").mkdir(parents=True)
    (root / "做账草稿" / "申报数据.json").write_text(
        json.dumps(
            {
                "社保明细": {
                    "2026-09": {
                        "单位部分": "1000.00",
                        "个人部分": "500.00",
                        "来源": "手工录入",
                        "险种明细": [
                            {
                                "insurance": "养老保险",
                                "total": "1500.00",
                                "unit": {"due": "1000.00"},
                                "personal": {"due": "500.00"},
                            }
                        ],
                    }
                }
            },
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )
    cid, rev = _register(client, root, name="己公司")

    # Create an EMPTY custom folder with payroll_social_dir benchmark role.
    custom_dir = root / "外包社保空目录"
    custom_dir.mkdir()
    imp = client.post(
        f"/api/v1/companies/{cid}/folders/import",
        json={"relative_path": "外包社保空目录", "role": "payroll_social_dir", "revision": rev},
        headers=SAME_ORIGIN,
    )
    assert imp.status_code == 200, imp.text
    pay_id = imp.json()["folder_id"]

    # Standard payroll view MUST still include the company-wide saved 2026-09 month.
    std_res = client.get(f"/api/v1/companies/{cid}/payroll")
    assert std_res.status_code == 200, std_res.text
    assert [m["month"] for m in std_res.json()["months"]] == ["2026-09"]
    assert "2026-09" in std_res.json()["confirmed"]

    # Custom payroll folder preview MUST stay strictly folder-only (empty -> no leaked 2026-09!).
    custom_res = client.get(f"/api/v1/companies/{cid}/payroll", params={"dir_key": pay_id})
    assert custom_res.status_code == 200, custom_res.text
    assert custom_res.json()["months"] == []
    assert custom_res.json()["confirmed"] == {}
    assert custom_res.json()["tax_file"] is False
