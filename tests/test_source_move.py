"""WS-05 stage 2: period folder check (content period vs. folder name) and confirmed moves of misfiled files.

Synthetic deduction exports only.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from invoice_hub.services.source_move import SourceMoveError, SourceMoveService, folder_period, period_folder_check
from test_company_deduction import N, row, write_list
from test_company_views import _company, _tree, app, client  # noqa: F401  (fixtures)


def test_folder_names_only_hint_a_period():
    assert folder_period("2026-07") == (2026, 7)
    assert folder_period("2026年7月") == (2026, 7)
    assert folder_period("6月") == (None, 6)
    assert folder_period("10月份属期抵扣项") == (None, 10)
    assert folder_period("博凯哲资料") is None and folder_period("银行回单") is None


def _deduction(root: Path) -> Path:
    folder = root / "进项抵扣"
    write_list(folder / "5月" / "用途确认信息.xlsx", [row(N[1], 100.0, 13.0)], period="202605")
    write_list(folder / "6月" / "用途确认信息 (1).xlsx", [row(N[2], 100.0, 13.0)], period="202607")  # misfiled
    write_list(folder / "loose.xlsx", [row(N[3], 100.0, 13.0)], period="202606")
    write_list(folder / "5月" / "empty.xlsx", [], empty=True)
    return folder


def test_check_compares_the_content_period_with_the_folder(tmp_path: Path):
    folder = _deduction(tmp_path)
    result = period_folder_check(folder, "input_deduction_dir")
    by_file = {item["file"]: item for item in result["items"]}
    assert result["mismatched"] == 1 and result["items"][0]["file"] == "6月/用途确认信息 (1).xlsx"
    misfiled = by_file["6月/用途确认信息 (1).xlsx"]
    assert (misfiled["folder_period"], misfiled["content_period"], misfiled["target"], misfiled["target_exists"]) == ("6 月", "2026-07", "2026-07", False)
    assert by_file["5月/用途确认信息.xlsx"]["status"] == "ok"
    assert by_file["loose.xlsx"]["status"] == "outside" and by_file["loose.xlsx"]["target"] == "6月"  # an existing folder for June
    assert by_file["5月/empty.xlsx"]["status"] == "unknown"  # no 所属期 in an empty export: never guessed from the folder
    assert [item["name"] for item in result["folders"]] == ["5月", "6月"]


def test_a_confirmed_move_creates_the_period_folder_and_never_overwrites(tmp_path: Path):
    folder = _deduction(tmp_path)
    moves = SourceMoveService(tmp_path / "state")
    job = moves.prepare(company_id="c1", key="input_deduction_dir", root=folder, guard=tmp_path / "成本发票",
                        items=[{"file": "6月/用途确认信息 (1).xlsx", "target": "2026-07"}])
    assert job["state"] == "prepared" and (folder / "6月" / "用途确认信息 (1).xlsx").exists()  # nothing moves before the confirm
    with pytest.raises(SourceMoveError):
        moves.commit(job["job_id"], company_id="c1", confirmed=False)
    done = moves.commit(job["job_id"], company_id="c1", confirmed=True)
    assert done["state"] == "completed" and done["moved_count"] == 1
    assert (folder / "2026-07" / "用途确认信息 (1).xlsx").is_file() and not (folder / "6月" / "用途确认信息 (1).xlsx").exists()
    assert moves.commit(job["job_id"], company_id="c1", confirmed=True)["moved_count"] == 1  # a replay redoes nothing
    assert period_folder_check(folder, "input_deduction_dir")["mismatched"] == 0

    # Never overwrite, never leave the subfolder, never an odd new folder name, never follow a link.
    write_list(folder / "2026-07" / "loose.xlsx", [row(N[4], 1.0, 0.1)], period="202607")
    refusals = [
        {"file": "loose.xlsx", "target": "2026-07"},          # same name already there
        {"file": "../成本发票/x.xlsx", "target": "2026-07"},   # outside the subfolder
        {"file": "loose.xlsx", "target": "七月"},              # new folders are YYYY-MM only
        {"file": "5月/用途确认信息.xlsx", "target": "5月"},    # already there
    ]
    for item in refusals:
        with pytest.raises(SourceMoveError):
            moves.prepare(company_id="c1", key="input_deduction_dir", root=folder, guard=None, items=[item])
    (folder / "linked").symlink_to(folder / "5月", target_is_directory=True)
    with pytest.raises(SourceMoveError):
        moves.prepare(company_id="c1", key="input_deduction_dir", root=folder, guard=None,
                      items=[{"file": "linked/用途确认信息.xlsx", "target": "6月"}])


def test_a_file_changed_after_the_plan_is_not_moved(tmp_path: Path):
    folder = _deduction(tmp_path)
    moves = SourceMoveService(tmp_path / "state")
    job = moves.prepare(company_id="c1", key="input_deduction_dir", root=folder, guard=None,
                        items=[{"file": "6月/用途确认信息 (1).xlsx", "target": "2026-07"}])
    write_list(folder / "6月" / "用途确认信息 (1).xlsx", [row(N[5], 200.0, 26.0)], period="202607")
    with pytest.raises(SourceMoveError) as stale:
        moves.commit(job["job_id"], company_id="c1", confirmed=True)
    assert stale.value.code == "SOURCE_MOVE_STALE" and (folder / "6月" / "用途确认信息 (1).xlsx").exists()
    # The monitored invoice folder is not this flow's to touch.
    with pytest.raises(SourceMoveError):
        moves.prepare(company_id="c1", key="input_deduction_dir", root=folder, guard=folder,
                      items=[{"file": "6月/用途确认信息 (1).xlsx", "target": "2026-07"}])


def test_period_folder_api_checks_prepares_and_confirms(client, tmp_path: Path):  # noqa: F811
    root = tmp_path / "客户" / "甲公司"
    (root / "成本发票").mkdir(parents=True)
    _deduction(root)
    company_id = _company(client, root)
    base = f"/api/v1/companies/{company_id}/period-folders"
    check = client.get(f"{base}?key=input_deduction_dir").json()
    assert check["mismatched"] == 1
    assert client.get(f"{base}?key=cost_invoice_dir").status_code == 422
    before = _tree(root)
    job = client.post(f"{base}/moves", json={"key": "input_deduction_dir", "items": [{"file": "6月/用途确认信息 (1).xlsx", "target": "2026-07"}]}).json()
    assert job["files"] == [{"file": "6月/用途确认信息 (1).xlsx", "target": "2026-07", "new_folder": True, "status": "pending", "message": ""}]
    assert _tree(root) == before  # prepare writes nothing in the company folder
    done = client.post(f"{base}/moves/{job['job_id']}/confirm", json={"confirmed": True}).json()
    assert done["state"] == "completed" and client.get(f"{base}/moves/{job['job_id']}").json()["moved_count"] == 1
    assert not any(str(root) in str(value) for value in done.values())  # no absolute paths to the page
