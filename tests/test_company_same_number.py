"""WS-04 same-number check: two invoice folders without a relation, compared by invoice number only.

All invoices are synthetic.
"""

from __future__ import annotations

from pathlib import Path

from invoice_hub.services.company_same_number import build_same_number_check
from test_company_views import _company, _sync, _tree, app, client  # noqa: F401  (fixtures)
from test_summary_and_costs import _xml_invoice

LABELS = {"a": "甲公司 · 成本发票", "b": "甲公司 · 费用报销"}


def _row(number: str, amount: str, fmt: str = "PDF", *, seller: str = "丙丁建材", source: str = "") -> dict:
    return {"invoice_number": number, "amount": amount, "file_format": fmt, "seller": seller, "buyer": "甲公司",
            "invoice_date": "2026-06-01", "source_file": source or f"{number or 'x'}.{fmt.lower()}",
            "source_path": f"/合成/{source or number}.{fmt.lower()}"}


def test_formats_of_one_invoice_count_once_and_shared_numbers_are_listed():
    one, two, three = "1" * 20, "2" * 20, "3" * 20
    a = [_row(one, "1130.00"), _row(one, "1130.00", "XML"), _row(two, "500.00"), _row("", "80.00", source="扫描件")]
    b = [_row(one, "1130.00"), _row(two, "600.00", seller="戊己钢铁"), _row(three, "90.00")]
    result = build_same_number_check(a, b, a_key="cost_invoice_dir", b_key="expense_reimbursement_dir", same_company=True, labels=LABELS)
    assert [item["number"] for item in result["matches"]] == [one, two]
    first, second = result["matches"]
    assert first["kind"] == "duplicate" and first["a"]["formats"] == ["PDF", "XML"] and not first["amount_differs"]
    assert second["amount_differs"] and second["party_differs"]
    assert any("1130.00" in step for step in first["steps"]) and any("重复" in step for step in first["steps"])
    assert result["counts"] == {"a_invoices": 2, "b_invoices": 3, "a_unnumbered": 1, "b_unnumbered": 0,
                                "matched": 2, "duplicate": 2, "pair": 0, "amount_differs": 1}
    assert result["checks_ok"] and [w["code"] for w in result["warnings"]] == ["a_unnumbered"]
    # Side-by-side records: one per invoice (formats merged), the unnumbered one kept apart.
    assert len(result["records"]["a"]) == 3 and result["matches"][0]["record_ids"]["a"] == [f"number:{one}"]


def test_issued_on_one_side_and_received_on_the_other_is_one_transaction_across_companies():
    one = "1" * 20
    labels = {"a": "甲公司 · 成本发票", "b": "乙公司 · 开具发票"}
    result = build_same_number_check([_row(one, "100.00")], [_row(one, "100.00", seller="乙公司")],
                                     a_key="cost_invoice_dir", b_key="issued_invoice_dir", same_company=False, labels=labels)
    assert result["matches"][0]["kind"] == "pair" and result["counts"]["duplicate"] == 0
    # Two companies both booking the same received invoice stays a possible duplicate.
    both_received = build_same_number_check([_row(one, "100.00")], [_row(one, "100.00")],
                                            a_key="cost_invoice_dir", b_key="cost_invoice_dir", same_company=False, labels=labels)
    assert both_received["matches"][0]["kind"] == "duplicate"


def _folder(root: Path, sub: str, files: dict[str, tuple[str, str, str]]) -> Path:
    folder = root / sub
    folder.mkdir(parents=True)
    for name, (number, seller, buyer) in files.items():
        (folder / name).write_text(_xml_invoice(number, seller, buyer, [("12E", "2", "200.00", "26.00", "钢筋")]), encoding="utf-8")
    return folder


def test_same_number_api_across_folders_and_companies_without_writing(app, client, tmp_path):  # noqa: F811
    one, two = "1" * 20, "2" * 20
    jia = tmp_path / "客户" / "甲公司"
    yi = tmp_path / "客户" / "乙公司"
    folders = [
        _folder(jia, "成本发票", {"a.xml": (one, "丙丁建材", "甲公司"), "b.xml": (two, "乙公司", "甲公司")}),
        _folder(jia, "费用报销", {"r.xml": (one, "丙丁建材", "甲公司")}),
        _folder(jia, "开具发票", {}),
        _folder(yi, "开具发票", {"s.xml": (two, "乙公司", "甲公司")}),
    ]
    for folder in folders:
        _sync(app, folder)
    jia_id = _company(client, jia)
    yi_id = _company(client, yi, revision=1, name="乙公司")
    before = {root: _tree(root) for root in (jia, yi)}

    same = client.get(f"/api/v1/companies/{jia_id}/same-number?a=cost_invoice_dir&b=expense_reimbursement_dir").json()
    assert same["state"] == "ok" and same["sides"]["b"]["label"] == "甲公司 · 费用报销"
    assert [(item["number"], item["kind"]) for item in same["matches"]] == [(one, "duplicate")]

    cross = client.get(f"/api/v1/companies/{jia_id}/same-number?a=cost_invoice_dir&b_company={yi_id}&b=issued_invoice_dir").json()
    assert [(item["number"], item["kind"]) for item in cross["matches"]] == [(two, "pair")]
    assert cross["sides"]["b"]["company_name"] == "乙公司"

    related = client.get(f"/api/v1/companies/{jia_id}/same-number?a=cost_invoice_dir&b=issued_invoice_dir")
    assert related.status_code == 422 and related.json()["error"]["code"] == "COMPANY_COMPARE_UNSUPPORTED"
    for query in ("a=cost_invoice_dir&b=bank_flow_dir", "a=cost_invoice_dir&b=cost_invoice_dir"):
        refused = client.get(f"/api/v1/companies/{jia_id}/same-number?{query}")
        assert refused.status_code == 422 and refused.json()["error"]["code"] == "COMPANY_COMPARE_INVALID"
    assert {root: _tree(root) for root in (jia, yi)} == before  # read-only
