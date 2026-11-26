"""Backend regressions for Phase 2: WS-11 cross-company search/project-index and WS-12 file CRUD."""

from __future__ import annotations

import json
import os
from pathlib import Path

from fastapi.testclient import TestClient

from invoice_hub.api.app import create_app
from invoice_hub.services.background_sync import BackgroundSyncService
from invoice_hub.targets import target_profile_for

SAME_ORIGIN = {"Origin": "http://testserver"}
FIXTURE_XML = Path(__file__).parent / "fixtures" / "sample_invoice.xml"


def _make_xml(seller: str, buyer: str, number: str, date_str: str, amount: str, tax_rate: str = "13%") -> str:
    raw = FIXTURE_XML.read_text(encoding="utf-8")
    # Build a minimal valid e-invoice XML matching our parser fields.
    return (
        '<?xml version="1.0" encoding="UTF-8"?>\n'
        "<EInvoice>\n"
        "  <Header><EIid>" + number + "</EIid></Header>\n"
        "  <EInvoiceData>\n"
        f"    <SellerInformation><SellerName>{seller}</SellerName></SellerInformation>\n"
        f"    <BuyerInformation><BuyerName>{buyer}</BuyerName></BuyerInformation>\n"
        "    <BasicInformation>\n"
        f"      <TotalAmWithoutTax>{amount}</TotalAmWithoutTax>\n"
        "      <TotalTaxAm>0.00</TotalTaxAm>\n"
        f"      <TotalTax-includedAmount>{amount}</TotalTax-includedAmount>\n"
        f"      <RequestTime>{date_str}</RequestTime>\n"
        "    </BasicInformation>\n"
        "    <IssuItemInformation>\n"
        f"      <ItemName>*金属制品*钢材</ItemName><TaxRate>{tax_rate}</TaxRate><Amount>{amount}</Amount>\n"
        "    </IssuItemInformation>\n"
        "  </EInvoiceData>\n"
        "  <TaxSupervisionInfo>\n"
        f"    <InvoiceNumber>{number}</InvoiceNumber>\n"
        f"    <IssueTime>{date_str}</IssueTime>\n"
        "  </TaxSupervisionInfo>\n"
        "</EInvoice>\n"
    ) if raw else ""


def _create_app_client(tmp_path: Path, monkeypatch):
    monkeypatch.setattr(
        BackgroundSyncService,
        "run_background_diagnostics",
        lambda self, trigger="startup_sync": None,
    )
    app = create_app(tmp_path)
    return app, TestClient(app)


def _register_company(client: TestClient, name: str, root: Path, *, revision: int = 0) -> dict:
    res = client.post(
        "/api/v1/companies",
        json={"name": name, "root_dir": str(root), "revision": revision},
        headers=SAME_ORIGIN,
    )
    assert res.status_code == 200, res.text
    return res.json()


def test_workspace_search_cross_company_read_only_and_project_index(tmp_path: Path, monkeypatch) -> None:
    app, client = _create_app_client(tmp_path, monkeypatch)
    state = app.state.invoice_hub

    comp_a = tmp_path / "甲公司"
    (comp_a / "成本发票").mkdir(parents=True)
    (comp_a / "开具发票").mkdir(parents=True)
    (comp_a / "费用报销").mkdir(parents=True)  # Unbuilt: must stay unbuilt after GET search
    (comp_a / "成本发票" / "a_cost.xml").write_text(
        _make_xml("华东建材", "甲公司", "25000001", "2026-10-15", "1200.00", "0.13"),
        encoding="utf-8",
    )
    (comp_a / "开具发票" / "a_out.xml").write_text(
        _make_xml("甲公司", "恒信建设集团", "25000002", "2026-11-05", "8800.00", "0.09"),
        encoding="utf-8",
    )

    comp_b = tmp_path / "乙公司"
    (comp_b / "成本发票").mkdir(parents=True)
    (comp_b / "成本发票" / "b_cost.xml").write_text(
        _make_xml("北方机电", "乙公司", "26000009", "2026-11-18", "3450.00", "0.13"),
        encoding="utf-8",
    )

    reg_a = _register_company(client, "甲公司", comp_a, revision=0)
    reg_b = _register_company(client, "乙公司", comp_b, revision=reg_a["revision"])
    cid_a = reg_a["company"]["id"]
    cid_b = reg_b["company"]["id"]

    # Build projections for A/issued, B/cost, then finish with A/cost as active monitored; leave A/expense unbuilt.
    for watch_target in (comp_a / "开具发票", comp_b / "成本发票", comp_a / "成本发票"):
        assert client.put("/api/v1/settings", json={"watch_dir": str(watch_target)}, headers=SAME_ORIGIN).status_code == 200
        assert client.post("/api/v1/bridge/rebuild", json={}, headers=SAME_ORIGIN).json()["ok"] is True

    # Assign manual project on Company B (collapsed company in sidebar)
    proj_res = client.put(
        f"/api/v1/companies/{cid_b}/projects/assignments",
        json={"revision": 0, "assignments": {"26000009": "地铁二期项目"}},
        headers=SAME_ORIGIN,
    )
    assert proj_res.status_code == 200, proj_res.text

    expense_profile = target_profile_for(state.config, comp_a / "费用报销")
    assert not Path(expense_profile.state_dir).exists()

    # 1) Collapsed project index reads B's project without creating unbuilt target state dirs
    pidx = client.get("/api/v1/workspace/project-index")
    assert pidx.status_code == 200
    pidx_body = pidx.json()
    assert pidx_body["projects"][cid_b] == ["地铁二期项目"]
    assert not Path(expense_profile.state_dir).exists()

    # 2) Cross-company buyer search finds Company A's issued invoice
    res_buyer = client.get("/api/v1/workspace/search", params={"q": "恒信建设集团", "search_scope": "buyer"})
    assert res_buyer.status_code == 200
    body_buyer = res_buyer.json()
    assert body_buyer["total_matches"] == 1
    assert body_buyer["items"][0]["company_id"] == cid_a
    assert body_buyer["items"][0]["dir_key"] == "issued_invoice_dir"
    assert body_buyer["items"][0]["read_only"] is True
    assert body_buyer["stats"]["unbuilt_directories"] >= 1
    assert not Path(expense_profile.state_dir).exists()

    # 3) Multi-token cross-company search matching project + tax rate finds Company B
    res_proj = client.get("/api/v1/workspace/search", params={"q": "地铁二期 13%"})
    assert res_proj.status_code == 200
    body_proj = res_proj.json()
    assert body_proj["total_matches"] == 1
    assert body_proj["items"][0]["company_id"] == cid_b
    assert body_proj["items"][0]["project"] == "地铁二期项目"

    # 4) Entity matches: searching "地铁二期" also returns project hit
    res_entity = client.get("/api/v1/workspace/search", params={"q": "地铁二期"})
    assert res_entity.status_code == 200
    assert any(p["project"] == "地铁二期项目" and p["company_id"] == cid_b for p in res_entity.json()["projects"])

    # 5) Company-scoped search excludes other companies
    res_scoped = client.get("/api/v1/workspace/search", params={"scope": "company", "company_id": cid_a})
    assert res_scoped.status_code == 200
    assert all(item["company_id"] == cid_a for item in res_scoped.json()["items"])
    assert res_scoped.json()["total_matches"] == 2

    # 6) Invalid amount range returns 422
    bad_amt = client.get("/api/v1/workspace/search", params={"amount_min": "5000", "amount_max": "100"})
    assert bad_amt.status_code == 422


def test_workspace_file_browser_upload_mkdir_and_symlink_blocks(tmp_path: Path, monkeypatch) -> None:
    _, client = _create_app_client(tmp_path, monkeypatch)
    comp = tmp_path / "资料公司"
    (comp / "成本发票").mkdir(parents=True)
    (comp / "合同归档").mkdir(parents=True)
    (comp / "合同归档" / "合同A.txt").write_text("hello", encoding="utf-8")

    outside = tmp_path / "outside_secret.txt"
    outside.write_text("secret", encoding="utf-8")
    link_file = comp / "合同归档" / "evil_link.txt"
    os.symlink(outside, link_file)

    reg = _register_company(client, "资料公司", comp, revision=0)
    cid = reg["company"]["id"]
    imp = client.post(
        f"/api/v1/companies/{cid}/folders/import",
        json={"revision": reg["revision"], "location": "inside_root", "relative_path": "合同归档", "label": "合同归档", "role": "general"},
        headers=SAME_ORIGIN,
    )
    assert imp.status_code == 200, imp.text
    custom_key = next(sub["key"] for sub in imp.json()["company"]["subdirs"] if sub["label"] == "合同归档")

    # List files shows normal file and flags symlink
    listed = client.get(f"/api/v1/companies/{cid}/directories/{custom_key}/files")
    assert listed.status_code == 200
    body = listed.json()
    assert body["can_mutate_existing"] is True
    by_name = {f["name"]: f for f in body["files"]}
    assert by_name["合同A.txt"]["is_symlink"] is False
    assert by_name["evil_link.txt"]["is_symlink"] is True

    # Symlink open/rename/trash all blocked with 409
    assert client.post(
        f"/api/v1/companies/{cid}/directories/{custom_key}/files/open",
        json={"relative_path": "evil_link.txt"},
        headers=SAME_ORIGIN,
    ).status_code == 409
    assert client.post(
        f"/api/v1/companies/{cid}/directories/{custom_key}/files/rename",
        json={"relative_path": "evil_link.txt", "new_name": "renamed.txt"},
        headers=SAME_ORIGIN,
    ).status_code == 409

    # Create subfolder; reject traversal and Windows reserved names
    assert client.post(
        f"/api/v1/companies/{cid}/directories/{custom_key}/files/mkdir",
        json={"subpath": "", "name": "2026-11"},
        headers=SAME_ORIGIN,
    ).status_code == 200
    assert (comp / "合同归档" / "2026-11").is_dir()
    assert client.post(
        f"/api/v1/companies/{cid}/directories/{custom_key}/files/mkdir",
        json={"subpath": "", "name": "../escape"},
        headers=SAME_ORIGIN,
    ).status_code == 422
    assert client.post(
        f"/api/v1/companies/{cid}/directories/{custom_key}/files/mkdir",
        json={"subpath": "", "name": "CON"},
        headers=SAME_ORIGIN,
    ).status_code == 422

    # Import preview detects conflict for 合同A.txt
    prev = client.post(
        f"/api/v1/companies/{cid}/directories/{custom_key}/files/import-preview",
        json={"subpath": "", "conflict_policy": "rename", "filenames": ["合同A.txt", "新合同.pdf"]},
        headers=SAME_ORIGIN,
    )
    assert prev.status_code == 200
    prev_items = {it["original_name"]: it for it in prev.json()["items"]}
    assert prev_items["合同A.txt"]["action"] == "rename"
    assert prev_items["合同A.txt"]["target_name"] == "合同A (1).txt"
    assert prev_items["新合同.pdf"]["action"] == "write"

    # Upload conflict_policy=skip does not overwrite original file
    up_skip = client.post(
        f"/api/v1/companies/{cid}/directories/{custom_key}/files/upload",
        params={"filename": "合同A.txt", "conflict_policy": "skip"},
        content=b"OVERWRITE_ATTEMPT",
        headers={**SAME_ORIGIN, "Content-Type": "application/octet-stream"},
    )
    assert up_skip.status_code == 200
    assert up_skip.json()["status"] == "skipped"
    assert (comp / "合同归档" / "合同A.txt").read_text(encoding="utf-8") == "hello"

    # Upload conflict_policy=rename saves as 合同A (1).txt while keeping original intact
    up_ren = client.post(
        f"/api/v1/companies/{cid}/directories/{custom_key}/files/upload",
        params={"filename": "合同A.txt", "conflict_policy": "rename"},
        content=b"SECOND_COPY",
        headers={**SAME_ORIGIN, "Content-Type": "application/octet-stream"},
    )
    assert up_ren.status_code == 200
    assert up_ren.json()["status"] == "renamed"
    assert up_ren.json()["saved_name"] == "合同A (1).txt"
    assert (comp / "合同归档" / "合同A (1).txt").read_bytes() == b"SECOND_COPY"
    assert (comp / "合同归档" / "合同A.txt").read_text(encoding="utf-8") == "hello"


def test_workspace_manual_edit_6_fields_rename_override_migration_and_readonly_guard(tmp_path: Path, monkeypatch) -> None:
    app, client = _create_app_client(tmp_path, monkeypatch)
    comp = tmp_path / "手改公司"
    (comp / "成本发票").mkdir(parents=True)
    (comp / "开具发票").mkdir(parents=True)
    src = comp / "成本发票" / "orig.xml"
    src.write_text(_make_xml("原销售方", "原购买方", "30000001", "2026-10-01", "500.00", "0.13"), encoding="utf-8")
    (comp / "开具发票" / "out.xml").write_text(
        _make_xml("手改公司", "客户甲", "30000002", "2026-10-02", "600.00", "0.13"),
        encoding="utf-8",
    )

    reg = _register_company(client, "手改公司", comp, revision=0)
    cid = reg["company"]["id"]

    assert client.put("/api/v1/settings", json={"watch_dir": str(comp / "成本发票")}, headers=SAME_ORIGIN).status_code == 200
    assert client.post("/api/v1/bridge/rebuild", json={}, headers=SAME_ORIGIN).json()["ok"] is True

    # Non-monitored invoice directory strictly rejects open/rename/move/trash per BOOKKEEPING.md
    assert client.post(
        f"/api/v1/companies/{cid}/directories/issued_invoice_dir/files/rename",
        json={"relative_path": "out.xml", "new_name": "out2.xml"},
        headers=SAME_ORIGIN,
    ).status_code == 409
    assert client.post(
        f"/api/v1/companies/{cid}/directories/issued_invoice_dir/files/trash/preview",
        json={"relative_paths": ["out.xml"]},
        headers=SAME_ORIGIN,
    ).status_code == 409

    # Monitored invoice directory supports patching all 6 manual fields and survives rebuild
    patch = client.patch(
        "/api/v1/invoices/0/manual-fields",
        json={"fields": {"销售方": "改后销售方", "购买方": "改后购买方", "开票金额": "777.88", "开票时间": "2026-11-20", "税率": "6%"}},
        headers=SAME_ORIGIN,
    )
    assert patch.status_code == 200
    assert patch.json()["ok"] is True

    # Single-file rename migrates manual_overrides.json and preserves edits across rebuild
    ren = client.post(
        f"/api/v1/companies/{cid}/directories/cost_invoice_dir/files/rename",
        json={"relative_path": "orig.xml", "new_name": "renamed_inv.xml"},
        headers=SAME_ORIGIN,
    )
    assert ren.status_code == 200, ren.text
    ren_body = ren.json()
    assert ren_body["renamed"] is True
    assert ren_body["manual_override_migrated"] is True
    assert not src.exists()
    assert (comp / "成本发票" / "renamed_inv.xml").is_file()

    assert client.post("/api/v1/bridge/rebuild", json={}, headers=SAME_ORIGIN).json()["ok"] is True
    listed = client.get("/api/v1/invoices").json()["items"]
    assert len(listed) == 1
    assert listed[0]["source_file"] == "renamed_inv.xml"
    assert listed[0]["seller"] == "改后销售方"
    assert listed[0]["buyer"] == "改后购买方"
    assert listed[0]["amount"] == "777.88"
    assert listed[0]["invoice_date"] == "2026-11-20"
    assert listed[0]["tax_rate"] == "6%"
    assert app.state.invoice_hub.active_profile.watch_dir == str((comp / "成本发票").resolve())


def test_workspace_cross_directory_move_and_native_trash(tmp_path: Path, monkeypatch) -> None:
    app, client = _create_app_client(tmp_path, monkeypatch)
    comp = tmp_path / "流转公司"
    (comp / "成本发票").mkdir(parents=True)
    (comp / "费用报销").mkdir(parents=True)
    (comp / "费用报销" / "dup.xml").write_text("existing", encoding="utf-8")
    (comp / "成本发票" / "dup.xml").write_text(
        _make_xml("差旅供应商", "流转公司", "40000001", "2026-11-10", "200.00", "0.06"),
        encoding="utf-8",
    )

    reg = _register_company(client, "流转公司", comp, revision=0)
    cid = reg["company"]["id"]
    assert client.put("/api/v1/settings", json={"watch_dir": str(comp / "成本发票")}, headers=SAME_ORIGIN).status_code == 200
    assert client.post("/api/v1/bridge/rebuild", json={}, headers=SAME_ORIGIN).json()["ok"] is True

    # Add manual override before moving
    assert client.patch("/api/v1/invoices/0/manual-fields", json={"fields": {"销售方": "手工差旅"}}, headers=SAME_ORIGIN).status_code == 200

    # Prepare destination state dir so override migration can carry over to target profile
    dst_profile = target_profile_for(app.state.invoice_hub.config, comp / "费用报销")
    Path(dst_profile.state_dir).mkdir(parents=True, exist_ok=True)

    # 1) conflict_policy=reject blocks move when target already has dup.xml
    prev_reject = client.post(
        f"/api/v1/companies/{cid}/directories/cost_invoice_dir/files/move/preview",
        json={
            "conflict_policy": "reject",
            "items": [{"relative_path": "dup.xml", "target_company_id": cid, "target_dir_key": "expense_reimbursement_dir"}],
        },
        headers=SAME_ORIGIN,
    )
    assert prev_reject.status_code == 200
    assert prev_reject.json()["can_confirm"] is False
    assert prev_reject.json()["summary"]["conflict"] == 1

    # 2) conflict_policy=rename plans dup (1).xml without overwriting existing dup.xml
    prev_ren = client.post(
        f"/api/v1/companies/{cid}/directories/cost_invoice_dir/files/move/preview",
        json={
            "conflict_policy": "rename",
            "items": [{"relative_path": "dup.xml", "target_company_id": cid, "target_dir_key": "expense_reimbursement_dir"}],
        },
        headers=SAME_ORIGIN,
    )
    assert prev_ren.status_code == 200
    plan = prev_ren.json()
    assert plan["can_confirm"] is True
    assert plan["items"][0]["target_name"] == "dup (1).xml"

    # Bad plan hash rejected
    assert client.post(
        f"/api/v1/companies/{cid}/directories/cost_invoice_dir/files/move/{plan['job_id']}/confirm",
        json={"confirm": True, "plan_hash": "wrong"},
        headers=SAME_ORIGIN,
    ).status_code == 409

    # Confirm executes move, migrates override, preserves existing dup.xml
    confirmed = client.post(
        f"/api/v1/companies/{cid}/directories/cost_invoice_dir/files/move/{plan['job_id']}/confirm",
        json={"confirm": True, "plan_hash": plan["plan_hash"]},
        headers=SAME_ORIGIN,
    )
    assert confirmed.status_code == 200, confirmed.text
    cbody = confirmed.json()
    assert cbody["moved"] == 1
    assert cbody["overrides_migrated"] == 1
    assert not (comp / "成本发票" / "dup.xml").exists()
    assert (comp / "费用报销" / "dup.xml").read_text(encoding="utf-8") == "existing"
    assert (comp / "费用报销" / "dup (1).xml").is_file()

    # Re-reading durable journal returns completed status idempotently
    journal = client.get(f"/api/v1/companies/{cid}/directories/cost_invoice_dir/files/move/{plan['job_id']}")
    assert journal.status_code == 200
    assert journal.json()["status"] == "completed"

    # Destination profile received migrated manual override
    dst_overrides = json.loads((Path(dst_profile.state_dir) / "manual_overrides.json").read_text(encoding="utf-8"))
    assert str((comp / "费用报销" / "dup (1).xml").resolve()) in dst_overrides["items"]

    # 3) Native recycle bin delete on a general folder calls move_to_trash (never unlink)
    (comp / "归档").mkdir()
    trash_file = comp / "归档" / "note.txt"
    trash_file.write_text("to trash", encoding="utf-8")
    imp = client.post(
        f"/api/v1/companies/{cid}/folders/import",
        json={"revision": reg["revision"], "location": "inside_root", "relative_path": "归档", "label": "归档", "role": "general"},
        headers=SAME_ORIGIN,
    )
    assert imp.status_code == 200
    gkey = next(sub["key"] for sub in imp.json()["company"]["subdirs"] if sub["label"] == "归档")

    trashed_targets: list[Path] = []
    monkeypatch.setattr("invoice_hub.services.workspace_files.move_to_trash", lambda p: (trashed_targets.append(Path(p)), Path(p).unlink()))

    tp = client.post(
        f"/api/v1/companies/{cid}/directories/{gkey}/files/trash/preview",
        json={"relative_paths": ["note.txt"]},
        headers=SAME_ORIGIN,
    )
    assert tp.status_code == 200
    tp_body = tp.json()
    assert tp_body["file_count"] == 1

    # Missing confirm rejected
    assert client.post(
        f"/api/v1/companies/{cid}/directories/{gkey}/files/trash",
        json={"confirm": False, "plan_hash": tp_body["plan_hash"], "relative_paths": ["note.txt"]},
        headers=SAME_ORIGIN,
    ).status_code == 422

    tc = client.post(
        f"/api/v1/companies/{cid}/directories/{gkey}/files/trash",
        json={"confirm": True, "plan_hash": tp_body["plan_hash"], "relative_paths": ["note.txt"]},
        headers=SAME_ORIGIN,
    )
    assert tc.status_code == 200
    assert tc.json()["trashed"] == 1
    assert trashed_targets == [trash_file.resolve()]
