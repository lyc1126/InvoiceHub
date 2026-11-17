"""B8: independent declaration/payment records and explicit manual VAT scenarios.

No policy bundle is signed yet. Invoice tax or a bank payment cannot silently become a
filing result; only confirmed manual assumptions can run the limited arithmetic below.
"""
from __future__ import annotations

import hashlib
import json
import re
from datetime import date, timedelta
from decimal import Decimal
from pathlib import Path

from invoice_hub.bookkeeping.repository import bookkeeping_write_lock
from invoice_hub.services.company_bank import _months_between
from invoice_hub.services.company_directory_guard import directory_entry
from invoice_hub.services.company_files import check_revision, read_state, write_state
from invoice_hub.services.company_registry import CompanyRegistryError
from invoice_hub.services.company_tax_rules import catalog
from invoice_hub.targets.companies import current_month, taxpayer_type_for

TAX_FILE = "税费记录.json"
TAX_TYPES = {"vat": "增值税", "city": "城市维护建设税", "education": "教育费附加", "local_education": "地方教育附加",
             "stamp": "印花税", "income": "企业所得税"}
MONTH = re.compile(r"\d{4}-(0[1-9]|1[0-2])")
AMOUNT = re.compile(r"\d{1,16}(?:\.\d{1,2})?")
INPUTS = ("output_tax", "input_tax", "transfer_out", "opening_credit")
ALGORITHM = "vat-general-manual-balance-v1"


def amount(value) -> Decimal | None:
    if value is None:
        return None
    if not isinstance(value, str) or not AMOUNT.fullmatch(value):
        raise ValueError("税额须为非负的十进制字符串，最多两位小数；未知填 null。")
    return Decimal(value).quantize(Decimal("0.01"))


def _month(value: str) -> str:
    if not isinstance(value, str) or not MONTH.fullmatch(value) or value[:4] == "0000":
        raise ValueError("月份须为 YYYY-MM。")
    if value > current_month():
        raise ValueError("不能登记未来月份。")
    return value


def _record(raw: object, tax_type: str) -> dict:
    if not isinstance(raw, dict) or set(raw) - {"declared", "paid", "source", "assessment"}:
        raise ValueError("税费记录字段不正确。")
    declared, paid = amount(raw.get("declared")), amount(raw.get("paid"))
    source = raw.get("source", "")
    if not isinstance(source, str) or len(source) > 200 or any(c in source for c in "\n\r"):
        raise ValueError("来源说明须为 200 字以内的单行文本。")
    if (declared is not None or paid is not None) and not source.strip():
        raise ValueError("申报或缴纳金额须填写来源说明；零也须确认。")
    assessment = raw.get("assessment")
    if assessment is not None:
        if (tax_type != "vat" or not isinstance(assessment, dict) or set(assessment) != {*INPUTS, "ordinary_only", "source_kind"}
                or assessment.get("ordinary_only") is not True or assessment.get("source_kind") != "user_assumption"):
            raise ValueError("仅支持明确假设为普通一般计税的手工增值税测算。")
        assessment = {**assessment, **{key: None if (v := amount(assessment[key])) is None else f"{v:.2f}" for key in INPUTS}}
    return {"declared": None if declared is None else f"{declared:.2f}", "paid": None if paid is None else f"{paid:.2f}",
            "source": source.strip(), "assessment": assessment}


class CompanyTaxService:
    def __init__(self, registry):
        self.registry = registry

    def _context(self, company_id: str) -> tuple[dict, Path]:
        company = self.registry.get_company(company_id)["company"]
        if company["root_status"] != "present":
            raise CompanyRegistryError("TAX_SOURCE_CHANGED", "公司资料夹不可用。", status_code=409)
        return company, Path(company["root_path"])

    @staticmethod
    def _state(root: Path) -> dict:
        state = read_state(root, TAX_FILE, "months")
        for month, records in state["months"].items():
            _month(month)
            if not isinstance(records, dict) or set(records) - TAX_TYPES.keys():
                raise ValueError("税费记录损坏，已保留原文件。")
            for tax_type, raw in records.items():
                _record(raw, tax_type)
        return state

    def save(self, company_id: str, body: dict) -> dict:
        changes = body.get("months")
        if not isinstance(changes, dict) or not changes or len(changes) > 120:
            raise ValueError("须提供 1—120 个月份的税费记录。")
        cleaned = {}
        for month, records in changes.items():
            _month(month)
            if not isinstance(records, dict) or not records or set(records) - TAX_TYPES.keys():
                raise ValueError("税种无效。")
            cleaned[month] = {tax: None if raw is None else _record(raw, tax) for tax, raw in records.items()}
        lock_dir = self.registry.registry_path.parent / "company-p2-locks" / company_id
        with bookkeeping_write_lock(lock_dir):
            _, root = self._context(company_id)
            identity = directory_entry(root)
            state = self._state(root)
            check_revision(body, state)
            for month, records in cleaned.items():
                target = state["months"].setdefault(month, {})
                for tax, raw in records.items():
                    if raw is None:
                        target.pop(tax, None)
                    else:
                        target[tax] = raw
            state["revision"] += 1
            write_state(root, TAX_FILE, state, expected_identity=identity)
            return {"ok": True, "revision": state["revision"], "saved": sorted(cleaned)}

    def get(self, company_id: str, *, start: str = "", end: str = "") -> dict:
        company, root = self._context(company_id)
        state = self._state(root)
        first = _month(start) if start else min(state["months"], default=current_month())
        last = _month(end) if end else max(state["months"], default=current_month())
        if first > last:
            raise ValueError("开始月份不能晚于结束月份。")
        if (int(last[:4]) - int(first[:4])) * 12 + int(last[-2:]) - int(first[-2:]) > 119:
            raise ValueError("一次最多查询 120 个月。")
        chain_first = first
        # A shorter query must not bypass a saved preceding carry mismatch.
        while int(chain_first[:4]) > 1 or int(chain_first[-2:]) > 1:
            prior = (date.fromisoformat(chain_first + "-01") - timedelta(days=1)).strftime("%Y-%m")
            if not state["months"].get(prior, {}).get("vat", {}).get("assessment"):
                break
            chain_first = prior
        months = _months_between(chain_first, last)
        snapshot = hashlib.sha256(json.dumps({"state": state, "identity": company["taxpayer_periods"]}, sort_keys=True).encode()).hexdigest()
        rows = []
        previous_credit = None
        for month in months:
            records = state["months"].get(month, {})
            taxpayer_type = taxpayer_type_for(company["taxpayer_periods"], month)
            for tax_type, label in TAX_TYPES.items():
                record = records.get(tax_type, {})
                assessment = record.get("assessment")
                blockers = []
                estimate = None
                steps = []
                basis = None
                basis_label = "计税依据未确认"
                credit = None
                if tax_type != "vat":
                    blockers.append({"code": "TAX_RULE_UNVERIFIED", "message": "该税种尚无已复核规则包，仅展示录入的申报和缴纳记录。"})
                elif taxpayer_type != "general":
                    blockers.append({"code": "TAX_IDENTITY_UNSUPPORTED", "message": "身份未设置或非一般纳税人；当前只支持普通一般计税手工场景。"})
                elif not assessment or any(assessment[key] is None for key in INPUTS):
                    blockers.append({"code": "TAX_EVIDENCE_MISSING", "message": "缺少普通一般计税手工假设；票面税额不自动视作抵扣或应纳。"})
                elif previous_credit is not None and Decimal(assessment["opening_credit"]) != previous_credit:
                    blockers.append({"code": "TAX_CARRY_MISMATCH", "message": "上期留抵与前月测算不一致，请核对后重算。"})
                else:
                    values = {key: Decimal(assessment[key]) for key in INPUTS}
                    net = values["output_tax"] - values["input_tax"] + values["transfer_out"] - values["opening_credit"]
                    # These inputs are tax amounts, not taxable sales. Keep the basis
                    # unknown instead of displaying net tax under the sales-basis column.
                    basis_label = "未提供应税销售额；手工税额抵减见算法说明"
                    estimate, credit = f"{max(net, Decimal(0)):.2f}", f"{max(-net, Decimal(0)):.2f}"
                    steps = [{"formula": "output_tax - input_tax + transfer_out - opening_credit", "inputs": assessment,
                              "net": f"{net:.2f}", "amount": estimate, "closing_credit": credit}]
                if tax_type == "vat":
                    # Monthly liabilities never net against a later month's input tax.
                    # Requiring the next opening to equal this closing preserves the chain.
                    previous_credit = Decimal(credit) if credit is not None else None
                if month < first:
                    continue
                rows.append({"month": month, "tax_type": tax_type, "label": label, "taxpayer_type": taxpayer_type,
                             "declared": record.get("declared"), "paid": record.get("paid"), "source": record.get("source", ""),
                             "assessment": assessment,
                             "rule_candidate": catalog(tax_type),
                             "tax_basis": {"amount": basis, "label": basis_label, "source_kind": "user_assumption" if basis is not None else None},
                             "tax_rate": {"value": None, "label": "不适用（税额抵减）" if tax_type == "vat" else "规则待复核"},
                             "estimate": {"status": "manual" if estimate is not None else "needs_review", "amount": estimate,
                                          "closing_credit": credit, "source_kind": "user_assumption", "algorithm_id": ALGORITHM if tax_type == "vat" else None,
                                          "snapshot_id": snapshot, "trace_id": hashlib.sha256(f"{snapshot}:{month}:{tax_type}:{ALGORITHM}".encode()).hexdigest(), "steps": steps, "blockers": blockers,
                                          "explanation": f"手工假设（普通一般计税）：销项 {assessment['output_tax']} − 已确认进项 {assessment['input_tax']} + 转出 {assessment['transfer_out']} − 上期留抵 {assessment['opening_credit']} = 净额 {steps[0]['net']}；测算 {estimate}，期末留抵 {credit}。" if steps else "资料或规则不足，未计算。"}})
        def total(field):
            selected = [row for row in rows if row["tax_type"] == "vat"]
            values = [row["estimate"]["amount"] if field == "estimated" else row[field] for row in selected]
            return f"{sum((Decimal(value) for value in values), Decimal(0)):.2f}" if values and all(v is not None for v in values) else None
        return {"ok": True, "company_id": company_id, "revision": state["revision"], "snapshot_id": snapshot,
                "start": first, "end": last, "rows": rows,
                "totals": {key: total(key) for key in ("estimated", "declared", "paid")},
                # Never present a known VAT subtotal as all taxes. Every monthly leaf
                # except income tax must be ready, from this same snapshot and period.
                "tax_total": {"amount": None, "status": "needs_review", "excludes": ["income"],
                              "start": first, "end": last, "snapshot_id": snapshot,
                              "missing": [{"month": row["month"], "tax_type": row["tax_type"]} for row in rows
                                          if row["tax_type"] != "income" and row["estimate"]["amount"] is None]},
                "mode": "manual", "rule_bundle": None, "form_mapping": None, "filing_deadline": None,
                "limitations": ["手工测算未核验到申报表行次与舍入样例，不构成税务结论。", "本页申报与缴纳记录独立保存，不会自动更新做账草稿或执行申报。"]}
