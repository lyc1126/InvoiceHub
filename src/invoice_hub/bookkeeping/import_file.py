from __future__ import annotations

import json
from decimal import Decimal, InvalidOperation, ROUND_HALF_UP
from pathlib import Path
from typing import Any, Iterable

from openpyxl import Workbook

from invoice_hub.bookkeeping.repository import canonical_sha256
from invoice_hub.domain.models import VoucherDraft

IMPORT_VOUCHER_TYPE = "记"
MONEY_QUANT = Decimal("0.01")
FACT_CAPABILITIES = ("template", "grouping", "voucher_type", "numbering", "decimal", "aux")


def load_jierui_import_facts(path: Path) -> dict[str, Any]:
    if not path.exists() or not path.is_file():
        raise FileNotFoundError(f"捷锐导入模板 facts 文件不存在: {path}")
    try:
        payload = json.loads(path.read_text(encoding="utf-8-sig"))
    except json.JSONDecodeError as exc:
        raise ValueError(f"捷锐导入模板 facts 不是合法 JSON: {path}") from exc
    return _validate_facts(payload)


def write_jierui_import_xlsx(
    drafts: Iterable[VoucherDraft | dict[str, Any]],
    account_table: dict[str, str],
    output_path: Path,
    facts: dict[str, Any],
    *,
    planned_voucher_nos: list[str] | None = None,
) -> dict[str, Any]:
    validated = _validate_facts(facts)
    columns = list(validated["columns"])
    workbook = Workbook()
    worksheet = workbook.active
    worksheet.title = validated["sheet_name"]
    worksheet.append(columns)

    draft_items = [_draft(item) for item in drafts]
    if planned_voucher_nos is not None and len(planned_voucher_nos) != len(draft_items):
        raise ValueError("planned_voucher_nos 数量与凭证数量不一致")
    voucher_count = 0
    line_count = 0
    exported_items: list[dict[str, Any]] = []
    for voucher_count, draft in enumerate(draft_items, start=1):
        voucher_no = planned_voucher_nos[voucher_count - 1] if planned_voucher_nos is not None else f"{voucher_count:03d}"
        first_row = line_count + 2
        for line in draft.lines:
            row = {column: "" for column in columns}
            row["凭证类别"] = IMPORT_VOUCHER_TYPE
            row["凭证号"] = voucher_no
            row["凭证日期"] = draft.voucher_date
            row["附单据数"] = "0"
            row["摘要"] = line.summary
            row["科目编码"] = line.account_code
            if line.direction == "debit":
                row["借方金额"] = _amount_text(line.amount)
            else:
                row["贷方金额"] = _amount_text(line.amount)
            for dimension, value in line.aux.items():
                if dimension in row:
                    row[dimension] = value
            worksheet.append([row[column] for column in columns])
            line_count += 1
        exported_items.append(
            {
                "posting_key": draft.posting_key or draft.voucher_key,
                "proposal_revision_hash": draft.proposal_revision_hash,
                "export_row_no": first_row,
                "export_row_end": line_count + 1,
                "planned_voucher_no": voucher_no,
                "signature_hash": canonical_sha256(
                    {
                        "voucher_date": draft.voucher_date,
                        "lines": [line.model_dump(mode="json") for line in draft.lines],
                    }
                ),
            }
        )

    output_path.parent.mkdir(parents=True, exist_ok=True)
    workbook.save(output_path)
    return {
        "ok": True,
        "path": str(output_path),
        "file_path": str(output_path),
        "file_name": output_path.name,
        "voucher_count": voucher_count,
        "line_count": line_count,
        "account_count": len(account_table or {}),
        "items": exported_items,
        "facts_version": validated["facts_version"],
    }


def write_draft_archive_xlsx(drafts: Iterable[VoucherDraft | dict[str, Any]], output_path: Path) -> dict[str, Any]:
    workbook = Workbook()
    worksheet = workbook.active
    worksheet.title = "凭证草稿"
    headers = ["凭证key", "凭证日期", "review_tier", "状态", "摘要", "科目编码", "科目名称", "借贷方向", "金额", "来源发票", "来源行"]
    worksheet.append(headers)
    row_count = 0
    for raw in drafts:
        draft = _draft(raw)
        for line in draft.lines:
            worksheet.append(
                [
                    draft.voucher_key,
                    draft.voucher_date,
                    draft.review_tier,
                    "draft",
                    line.summary,
                    line.account_code,
                    line.account_name,
                    line.direction,
                    _amount_text(line.amount),
                    ",".join(draft.source_invoice_nos),
                    "\n".join(draft.source_rows),
                ]
            )
            row_count += 1
    output_path.parent.mkdir(parents=True, exist_ok=True)
    workbook.save(output_path)
    return {"ok": True, "path": str(output_path), "file_path": str(output_path), "file_name": output_path.name, "row_count": row_count}


def _validate_facts(payload: dict[str, Any]) -> dict[str, Any]:
    if not isinstance(payload, dict):
        raise ValueError("捷锐导入模板 facts 结构不符：根节点必须是对象")
    sheet_name = payload.get("sheet_name")
    columns = payload.get("columns")
    if not isinstance(sheet_name, str) or not sheet_name.strip():
        raise ValueError("捷锐导入模板 facts 结构不符：sheet_name 缺失")
    if not isinstance(columns, list) or len(columns) != 22 or not all(isinstance(item, str) and item.strip() for item in columns):
        raise ValueError("捷锐导入模板 facts 结构不符：columns 必须是 22 个非空列名")
    required = {"凭证类别", "凭证号", "凭证日期", "附单据数", "摘要", "科目编码", "借方金额", "贷方金额"}
    missing = sorted(required.difference(columns))
    if missing:
        raise ValueError(f"捷锐导入模板 facts 结构不符：缺少必需列 {', '.join(missing)}")
    normalized = dict(payload)
    normalized["sheet_name"] = sheet_name.strip()
    normalized["columns"] = list(columns)
    raw_readiness = payload.get("readiness") if isinstance(payload.get("readiness"), dict) else {}
    readiness: dict[str, dict[str, Any]] = {}
    for capability in FACT_CAPABILITIES:
        item = raw_readiness.get(capability, {}) if isinstance(raw_readiness, dict) else {}
        if not isinstance(item, dict):
            item = {}
        status = str(item.get("status") or "not_tested")
        if status not in {"ready", "not_tested", "unsupported", "failed"}:
            raise ValueError(f"捷锐导入模板 facts readiness 状态无效: {capability}={status}")
        readiness[capability] = {**item, "status": status}
    normalized["readiness"] = readiness
    content = {key: value for key, value in normalized.items() if key not in {"facts_version", "facts_content_sha256"}}
    normalized["facts_content_sha256"] = canonical_sha256(content)
    normalized["facts_version"] = str(payload.get("facts_version") or normalized["facts_content_sha256"])
    normalized["schema_version"] = int(payload.get("schema_version") or 1)
    return normalized


def facts_readiness(payload: dict[str, Any]) -> dict[str, dict[str, Any]]:
    return dict(_validate_facts(payload)["readiness"])


def _draft(value: VoucherDraft | dict[str, Any]) -> VoucherDraft:
    return value if isinstance(value, VoucherDraft) else VoucherDraft.model_validate(value)


def _amount_text(value: object) -> str:
    try:
        number = Decimal(str(value or "0"))
    except (InvalidOperation, ValueError) as exc:
        raise ValueError(f"凭证金额不是合法 Decimal: {value}") from exc
    return format(number.quantize(MONEY_QUANT, rounding=ROUND_HALF_UP), "f")
