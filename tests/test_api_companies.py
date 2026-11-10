"""WS-07 step 1: company registry API, subfolder detection and preview -> confirm creation."""

import json
import os
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from invoice_hub.api.app import create_app
from invoice_hub.services.company_registry import taxpayer_type_for


@pytest.fixture
def app(tmp_path, monkeypatch):
    monkeypatch.setattr("invoice_hub.services.background_sync.BackgroundSyncService.run_background_diagnostics", lambda *args, **kwargs: None)
    return create_app(tmp_path)


@pytest.fixture
def client(app):
    return TestClient(app)


def _registry_path(app) -> Path:
    return app.state.invoice_hub.companies.registry_path


def _tree(root: Path) -> dict[str, str]:
    """Every file under root with its bytes, to prove the registry never rewrites files."""
    return {str(path.relative_to(root)): path.read_bytes().hex() for path in sorted(root.rglob("*")) if path.is_file()}


def _create(client, root: Path, name: str = "甲公司", revision: int = 0, **extra) -> dict:
    response = client.post("/api/v1/companies", json={"name": name, "root_dir": str(root), "revision": revision, **extra})
    assert response.status_code == 200, response.text
    return response.json()


def test_empty_registry_reads_as_no_companies_without_creating_a_file(app, client):
    payload = client.get("/api/v1/companies").json()
    assert payload["ok"] is True and payload["revision"] == 0 and payload["companies"] == []
    assert payload["monitored_company_id"] is None
    assert [item["label"] for item in payload["standard_subdirs"]] == ["成本发票", "开具发票", "银行流水", "进项抵扣", "工资社保", "费用报销"]
    assert not _registry_path(app).exists()


def test_create_detects_existing_folders_and_never_guesses_ambiguous_ones(app, client, tmp_path):
    root = tmp_path / "客户" / "甲公司"
    for name in ("进项发票", "银行流水", "工资", "费用报销2026", "开票资料与抵扣"):
        (root / name).mkdir(parents=True)
    result = _create(client, root)
    company = result["company"]
    by_key = {item["key"]: item for item in company["subdirs"]}
    assert by_key["cost_invoice_dir"]["relative_path"] == "进项发票"
    assert by_key["bank_flow_dir"]["relative_path"] == "银行流水"
    assert by_key["payroll_social_dir"]["relative_path"] == "工资"
    assert by_key["expense_reimbursement_dir"]["relative_path"] == "费用报销2026"
    # "开票资料与抵扣" hits both 开具发票 and 进项抵扣, so neither key takes it.
    assert by_key["issued_invoice_dir"]["relative_path"] == "开具发票"
    assert by_key["input_deduction_dir"]["relative_path"] == "进项抵扣"
    assert result["subdir_sources"] == {
        "cost_invoice_dir": "detected", "issued_invoice_dir": "default", "bank_flow_dir": "standard",
        "input_deduction_dir": "default", "payroll_social_dir": "detected", "expense_reimbursement_dir": "detected",
    }
    assert company["missing_subdir_count"] == 2
    assert company["current_taxpayer_type"] is None and company["current_taxpayer_label"] == "未设置"
    # Inside the project root the folder is stored relative (AGENTS.md path rule).
    assert company["root_dir"] == "./客户/甲公司"
    stored = json.loads(_registry_path(app).read_text(encoding="utf-8"))
    assert stored["schema_version"] == 1 and stored["revision"] == 1 and stored["companies"][0]["root_dir"] == "./客户/甲公司"


def test_folder_outside_the_project_is_stored_absolute(client, tmp_path_factory):
    outside = tmp_path_factory.mktemp("用户目录") / "乙公司"
    outside.mkdir()
    company = _create(client, outside)["company"]
    assert Path(company["root_dir"]).is_absolute()
    assert company["root_path"] == str(outside.resolve())


def test_writes_require_the_current_revision(client, tmp_path):
    (tmp_path / "甲").mkdir()
    (tmp_path / "乙").mkdir()
    missing = client.post("/api/v1/companies", json={"name": "甲", "root_dir": str(tmp_path / "甲")})
    assert missing.status_code == 422 and missing.json()["error"]["code"] == "COMPANY_INVALID"
    created = _create(client, tmp_path / "甲", name="甲")
    stale = client.post("/api/v1/companies", json={"name": "乙", "root_dir": str(tmp_path / "乙"), "revision": 0})
    assert stale.status_code == 409 and stale.json()["error"]["code"] == "COMPANY_REVISION_CONFLICT"
    company_id = created["company"]["id"]
    stale_patch = client.patch(f"/api/v1/companies/{company_id}", json={"name": "甲2", "revision": 0})
    assert stale_patch.status_code == 409
    assert client.get("/api/v1/companies").json()["companies"][0]["name"] == "甲"


@pytest.mark.parametrize(
    ("make_root", "field"),
    [
        (lambda base: base / "不存在", "root_dir"),
        (lambda base: (base / "文件.txt").write_text("x") and base / "文件.txt", "root_dir"),
    ],
)
def test_root_must_be_an_existing_folder(client, tmp_path, make_root, field):
    root = make_root(tmp_path)
    response = client.post("/api/v1/companies", json={"name": "甲", "root_dir": str(root), "revision": 0})
    assert response.status_code == 422 and response.json()["error"]["field"] == field


def test_names_are_unique_and_roots_cannot_repeat_or_nest(client, tmp_path):
    (tmp_path / "甲" / "分部").mkdir(parents=True)
    (tmp_path / "乙").mkdir()
    _create(client, tmp_path / "甲", name="甲公司")
    for name, root in (("甲公司", tmp_path / "乙"), ("另一家", tmp_path / "甲"), ("分部", tmp_path / "甲" / "分部"), ("上级", tmp_path)):
        response = client.post("/api/v1/companies", json={"name": name, "root_dir": str(root), "revision": 1})
        assert response.status_code == 422, (name, response.text)
    assert client.get("/api/v1/companies").json()["revision"] == 1


@pytest.mark.parametrize(
    "subdirs",
    [
        {"bank_flow_dir": "../外面"},
        {"bank_flow_dir": "/绝对路径"},
        {"bank_flow_dir": "C:/盘符"},
        {"bank_flow_dir": "a/../b"},
        {"bank_flow_dir": "~/家目录"},
        {"bank_flow_dir": "名称?"},
        {"bank_flow_dir": ""},
        {"unknown_dir": "x"},
        {"bank_flow_dir": "成本发票"},
        {"bank_flow_dir": "成本发票/银行"},
    ],
)
def test_subdir_mapping_must_stay_inside_the_root_and_be_distinct(client, tmp_path, subdirs):
    (tmp_path / "甲").mkdir()
    response = client.post("/api/v1/companies", json={"name": "甲", "root_dir": str(tmp_path / "甲"), "revision": 0, "subdirs": subdirs})
    assert response.status_code == 422, response.text
    assert response.json()["error"]["field"].startswith("subdirs")


def test_patch_merges_subdirs_and_replaces_taxpayer_periods(client, tmp_path):
    (tmp_path / "甲").mkdir()
    company_id = _create(client, tmp_path / "甲")["company"]["id"]
    response = client.patch(
        f"/api/v1/companies/{company_id}",
        json={
            "revision": 1,
            "subdirs": {"bank_flow_dir": "资料\\银行/"},
            "taxpayer_periods": [
                {"effective_from": "2026-07", "taxpayer_type": "general"},
                {"effective_from": "2024-01", "taxpayer_type": "small_scale"},
            ],
        },
    )
    assert response.status_code == 200, response.text
    company = response.json()["company"]
    assert {item["key"]: item["relative_path"] for item in company["subdirs"]}["bank_flow_dir"] == "资料/银行"
    assert {item["key"]: item["relative_path"] for item in company["subdirs"]}["cost_invoice_dir"] == "成本发票"
    assert [item["effective_from"] for item in company["taxpayer_periods"]] == ["2024-01", "2026-07"]
    assert response.json()["revision"] == 2
    unchanged = client.patch(f"/api/v1/companies/{company_id}", json={"revision": 2, "name": "甲公司"})
    assert unchanged.json()["revision"] == 2  # same values: no write, no revision bump


@pytest.mark.parametrize(
    "periods",
    [
        [{"effective_from": "2026-13", "taxpayer_type": "general"}],
        [{"effective_from": "2026-01", "taxpayer_type": "exempt"}],
        [{"effective_from": "2026-01", "taxpayer_type": "general"}, {"effective_from": "2026-01", "taxpayer_type": "small_scale"}],
        "general",
    ],
)
def test_invalid_taxpayer_periods_are_rejected(client, tmp_path, periods):
    (tmp_path / "甲").mkdir()
    response = client.post("/api/v1/companies", json={"name": "甲", "root_dir": str(tmp_path / "甲"), "revision": 0, "taxpayer_periods": periods})
    assert response.status_code == 422 and response.json()["error"]["field"].startswith("taxpayer_periods")


def test_taxpayer_type_follows_effective_month():
    periods = [{"effective_from": "2024-01", "taxpayer_type": "small_scale"}, {"effective_from": "2026-07", "taxpayer_type": "general"}]
    assert taxpayer_type_for(periods, "2023-12") is None
    assert taxpayer_type_for(periods, "2024-01") == "small_scale"
    assert taxpayer_type_for(periods, "2026-06") == "small_scale"
    assert taxpayer_type_for(periods, "2026-07") == "general"
    assert taxpayer_type_for([], "2026-07") is None


def test_subdir_creation_is_preview_then_confirm_and_only_makes_empty_folders(client, tmp_path):
    root = tmp_path / "甲"
    (root / "银行流水").mkdir(parents=True)
    (root / "银行流水" / "1月.xlsx").write_bytes(b"bank")
    (root / "工资社保").write_text("同名文件", encoding="utf-8")
    (root / "说明.txt").write_text("保留", encoding="utf-8")
    company_id = _create(client, root)["company"]["id"]
    before = _tree(root)

    plan = client.get(f"/api/v1/companies/{company_id}/subdirs/plan").json()
    actions = {item["key"]: item["action"] for item in plan["items"]}
    assert actions == {
        "cost_invoice_dir": "create", "issued_invoice_dir": "create", "bank_flow_dir": "exists",
        "input_deduction_dir": "create", "payroll_social_dir": "blocked", "expense_reimbursement_dir": "create",
    }
    assert plan["create_count"] == 4 and plan["blocked_count"] == 1
    assert _tree(root) == before  # preview writes nothing

    unconfirmed = client.post(f"/api/v1/companies/{company_id}/subdirs/create", json={"plan_hash": plan["plan_hash"]})
    assert unconfirmed.status_code == 422 and unconfirmed.json()["error"]["code"] == "COMPANY_CONFIRM_REQUIRED"
    (root / "成本发票").mkdir()  # the folder state changed after the preview
    stale = client.post(f"/api/v1/companies/{company_id}/subdirs/create", json={"plan_hash": plan["plan_hash"], "confirm": True})
    assert stale.status_code == 409 and stale.json()["error"]["code"] == "COMPANY_PLAN_STALE"
    assert not (root / "开具发票").exists()

    plan = client.get(f"/api/v1/companies/{company_id}/subdirs/plan").json()
    applied = client.post(f"/api/v1/companies/{company_id}/subdirs/create", json={"plan_hash": plan["plan_hash"], "confirm": True})
    assert applied.status_code == 200, applied.text
    result = applied.json()
    assert result["ok"] is True and sorted(result["created"]) == sorted(["issued_invoice_dir", "input_deduction_dir", "expense_reimbursement_dir"])
    assert _tree(root) == before  # no file moved, rewritten or removed
    for name in ("开具发票", "进项抵扣", "费用报销"):
        assert (root / name).is_dir() and list((root / name).iterdir()) == []
    assert (root / "工资社保").is_file()
    assert result["company"]["missing_subdir_count"] == 0
    assert client.get(f"/api/v1/companies/{company_id}/subdirs/plan").json()["create_count"] == 0


@pytest.mark.skipif(os.name == "nt", reason="symlink creation needs elevated rights on Windows")
def test_linked_parent_that_leaves_the_root_is_blocked(client, tmp_path, tmp_path_factory):
    root = tmp_path / "甲"
    root.mkdir()
    outside = tmp_path_factory.mktemp("外部")
    (root / "链接").symlink_to(outside, target_is_directory=True)
    company_id = _create(client, root, subdirs={"bank_flow_dir": "链接/银行流水"})["company"]["id"]
    plan = client.get(f"/api/v1/companies/{company_id}/subdirs/plan").json()
    bank = next(item for item in plan["items"] if item["key"] == "bank_flow_dir")
    assert bank["action"] == "blocked"
    client.post(f"/api/v1/companies/{company_id}/subdirs/create", json={"plan_hash": plan["plan_hash"], "confirm": True})
    assert list(outside.iterdir()) == []


def test_corrupt_registry_is_kept_and_blocks_writes(app, client, tmp_path):
    path = _registry_path(app)
    path.parent.mkdir(parents=True, exist_ok=True)
    for content in ("{not json", json.dumps({"schema_version": 2, "revision": 1, "companies": []}),
                    json.dumps({"schema_version": 1, "revision": 1, "companies": [{"id": "x"}]})):
        path.write_text(content, encoding="utf-8")
        listed = client.get("/api/v1/companies")
        assert listed.status_code == 409 and listed.json()["error"]["code"] == "COMPANY_REGISTRY_CORRUPT"
        (tmp_path / "甲").mkdir(exist_ok=True)
        write = client.post("/api/v1/companies", json={"name": "甲", "root_dir": str(tmp_path / "甲"), "revision": 1})
        assert write.status_code == 409
        assert path.read_text(encoding="utf-8") == content


def test_delete_removes_only_the_registry_entry(client, tmp_path):
    root = tmp_path / "甲"
    (root / "成本发票").mkdir(parents=True)
    (root / "成本发票" / "票.pdf").write_bytes(b"%PDF")
    company_id = _create(client, root)["company"]["id"]
    before = _tree(root)
    assert client.delete(f"/api/v1/companies/{company_id}").status_code == 422  # revision required
    assert client.delete(f"/api/v1/companies/{company_id}?revision=0").status_code == 409
    deleted = client.delete(f"/api/v1/companies/{company_id}?revision=1").json()
    assert deleted["ok"] is True and deleted["revision"] == 2 and deleted["files_touched"] == 0
    assert _tree(root) == before
    assert client.get("/api/v1/companies").json()["companies"] == []
    assert client.get(f"/api/v1/companies/{company_id}").status_code == 404
    assert client.delete(f"/api/v1/companies/{company_id}?revision=2").status_code == 404


def test_registry_marks_the_monitored_company_without_switching_watch_dir(app, client, tmp_path):
    state = app.state.invoice_hub
    root = tmp_path / "甲"
    (root / "成本发票").mkdir(parents=True)
    (tmp_path / "乙").mkdir()
    profile_before = state.active_profile
    _create(client, root)
    _create(client, tmp_path / "乙", name="乙", revision=1)
    assert state.active_profile is profile_before  # registering never touches the active directory
    assert client.get("/api/v1/companies").json()["monitored_company_id"] is None

    state.update_settings({"watch_dir": str(root / "成本发票")})
    listed = client.get("/api/v1/companies").json()
    monitored = [item for item in listed["companies"] if item["monitored"]]
    assert [item["name"] for item in monitored] == ["甲公司"]
    assert monitored[0]["monitored_subdir_key"] == "cost_invoice_dir"
    assert listed["monitored_company_id"] == monitored[0]["id"]
    assert listed["target_id"] == state.active_profile.id


def test_cross_origin_registry_writes_are_rejected(client, tmp_path):
    (tmp_path / "甲").mkdir()
    response = client.post(
        "/api/v1/companies",
        json={"name": "甲", "root_dir": str(tmp_path / "甲"), "revision": 0},
        headers={"Origin": "http://evil.example"},
    )
    assert response.status_code == 403
    assert client.get("/api/v1/companies").json()["companies"] == []
