from pathlib import Path

import pytest

from invoice_hub.bookkeeping.vouchers import generate_voucher_drafts
from invoice_hub.bookkeeping.repository import file_sha256
from invoice_hub.domain.models import AccountMappingRule, utc_now_text


def _rule(seller: str = "供应商 A", tax_code: str = "222101") -> AccountMappingRule:
    return AccountMappingRule(
        rule_id="will-be-normalized-by-store",
        match_seller=seller,
        debit_account_code="1405",
        debit_account_name="库存商品",
        credit_account_code="2202",
        credit_account_name="应付账款",
        tax_account_code=tax_code,
        source="manual",
        confirmed_at=utc_now_text(),
    )


def _row(
    invoice_no: str = "12345678901234567890",
    seller: str = "供应商 A",
    amount: str = "100.00",
    tax: str = "13.00",
    total: str = "113.00",
    tax_rate: str = "13%",
    project: str = "项目 A",
) -> dict[str, str]:
    return {
        "销售方": seller,
        "购买方": "本公司",
        "发票号码": invoice_no,
        "开票日期": "2026-07-06",
        "备注项目名称": project,
        "内部项目名称": project,
        "规格型号": "M1",
        "单位": "吨",
        "数量": "1",
        "单价(除税)": amount,
        "平均单价(含税)": total,
        "金额(除税)": amount,
        "税率": tax_rate,
        "税金": tax,
        "价税合计": total,
        "发票代码(**内文字)": "钢材",
        "源文件": "a.pdf",
    }


def _accounts() -> dict[str, str]:
    return {"1405": "库存商品", "2202": "应付账款", "222101": "应交税费-进项税额"}


def test_mapping_hit_and_miss_set_review_tiers() -> None:
    drafts = generate_voucher_drafts(
        [_row(seller="供应商 A"), _row(invoice_no="22345678901234567890", seller="供应商 B")],
        [_rule("供应商 A")],
        _accounts(),
        "1",
    )

    assert drafts[0].review_tier == "auto"
    assert drafts[0].balance_ok is True
    assert drafts[1].review_tier == "ai_suggested"
    assert drafts[1].balance_ok is True


def test_tax_line_stays_explicit_until_human_tax_decision() -> None:
    split = generate_voucher_drafts([_row()], [_rule(tax_code="222101")], _accounts(), "1")[0]
    merged = generate_voucher_drafts([_row()], [_rule(tax_code="")], _accounts(), "1")[0]

    assert [(line.direction, line.account_code, line.amount) for line in split.lines] == [
        ("debit", "1405", "100.00"),
        ("debit", "222101", "13.00"),
        ("credit", "2202", "113.00"),
    ]
    assert [(line.line_role, line.direction, line.account_code, line.amount) for line in merged.lines] == [
        ("cost", "debit", "1405", "100.00"),
        ("input_tax", "debit", "", "13.00"),
        ("payable", "credit", "2202", "113.00"),
    ]


@pytest.mark.parametrize(
    "row",
    [
        _row(total="113.02"),
        _row(amount="-100.00", tax="-13.00", total="-113.00"),
        _row(tax_rate=""),
    ],
)
def test_invalid_amount_negative_and_missing_tax_rate_force_manual(row: dict[str, str]) -> None:
    draft = generate_voucher_drafts([row], [_rule()], _accounts(), "1")[0]

    assert draft.review_tier == "forced_manual"
    assert draft.balance_ok is False
    assert any("原因:" in item for item in draft.source_rows)


def test_decimal_precision_uses_decimal_not_float() -> None:
    draft = generate_voucher_drafts([_row(amount="0.10", tax="0.20", total="0.30")], [_rule(tax_code="")], _accounts(), "1")[0]

    assert [line.amount for line in draft.lines] == ["0.10", "0.20", "0.30"]
    assert draft.balance_ok is True


def test_missing_account_code_forces_manual_and_records_reason() -> None:
    draft = generate_voucher_drafts([_row()], [_rule(tax_code="222101")], {"1405": "库存商品", "2202": "应付账款"}, "1")[0]

    assert draft.review_tier == "forced_manual"
    assert any("222101" in item for item in draft.source_rows)


def test_multi_line_invoice_keeps_each_source_line_separate() -> None:
    drafts = generate_voucher_drafts(
        [_row(amount="100.00", tax="13.00", total="113.00"), _row(amount="50.00", tax="6.50", total="56.50")],
        [_rule()],
        _accounts(),
        "1",
    )

    assert len(drafts) == 1
    assert [(line.line_role, line.direction, line.amount) for line in drafts[0].lines] == [
        ("cost", "debit", "100.00"),
        ("input_tax", "debit", "13.00"),
        ("payable", "credit", "113.00"),
        ("cost", "debit", "50.00"),
        ("input_tax", "debit", "6.50"),
        ("payable", "credit", "56.50"),
    ]
    assert len([item for item in drafts[0].source_rows if item.startswith("row:")]) == 2
    assert len(drafts[0].source_lines) == 2
    assert len(drafts[0].project_allocations) == 2


def test_missing_invoice_uses_source_evidence_hash_as_isolated_weak_key(tmp_path: Path) -> None:
    (tmp_path / "a.pdf").write_bytes(b"invoice-a")
    (tmp_path / "b.pdf").write_bytes(b"invoice-b")
    first = _row(invoice_no="")
    second = _row(invoice_no="")
    second["源文件"] = "b.pdf"

    drafts = generate_voucher_drafts(
        [first, second],
        [_rule()],
        _accounts(),
        "1",
        company_id="company-id",
        source_dir=tmp_path,
    )

    assert len(drafts) == 2
    assert {draft.anchor_business_key for draft in drafts} == {
        f"sha256:{file_sha256(tmp_path / 'a.pdf')}",
        f"sha256:{file_sha256(tmp_path / 'b.pdf')}",
    }
    assert {draft.key_strength for draft in drafts} == {"weak"}
    assert len({draft.posting_key for draft in drafts}) == 2


def test_source_hashing_does_not_escape_active_invoice_directory(tmp_path: Path) -> None:
    source_dir = tmp_path / "source"
    source_dir.mkdir()
    (tmp_path / "outside.pdf").write_bytes(b"outside")
    row = _row(invoice_no="")
    row["源文件"] = "../outside.pdf"

    draft = generate_voucher_drafts(
        [row],
        [_rule()],
        _accounts(),
        "1",
        company_id="company-id",
        source_dir=source_dir,
    )[0]

    assert draft.anchor_business_key == "path:../outside.pdf"
    assert draft.source_file_hashes == {"../outside.pdf": ""}
