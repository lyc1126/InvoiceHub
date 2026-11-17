"""Isolated, synthetic localhost fixture for workspace_p3_e2e.mjs. Never uses local config."""
from __future__ import annotations

import argparse
import json
from pathlib import Path
from tempfile import TemporaryDirectory

import uvicorn
from openpyxl import Workbook

from invoice_hub.api.app import create_app
from invoice_hub.bank.jierui import REVIEW_COLUMNS, REVIEW_SHEET
from invoice_hub.services.background_sync import BackgroundSyncService


def create_fixture(root: Path):
    company = root / "合成公司"
    bank = company / "银行流水"
    bank.mkdir(parents=True)
    csv = "日期,收入,支出,余额\n2026-06-01,10.10,,110.10\n2026-06-02,,20.10,90.00\n2026-06-03,5.25,,95.25\n合计,15.35,20.10,\n"
    (bank / "合成流水.csv").write_text(csv, encoding="utf-8")
    (bank / "断链.csv").write_text(csv.replace("95.25", "95.26"), encoding="utf-8")
    books = company / "凭证"
    books.mkdir()
    (books / "科目表.json").write_text(json.dumps({"accounts": [{"code": "1002", "name": "银行存款", "is_leaf": True}, {"code": "4001", "name": "实收资本", "is_leaf": True}]}), encoding="utf-8")
    drafts = company / "做账草稿"
    drafts.mkdir()
    book = Workbook()
    book.active.title = REVIEW_SHEET
    book.active.append(REVIEW_COLUMNS)
    for code, debit, credit in [("1002", "10.10", None), ("4001", None, "10.10")]:
        row = {"月份": "2026-06", "凭证号": "001", "日期": "2026-06-30", "摘要": "合成出资", "科目编码": code, "借方金额": debit, "贷方金额": credit}
        book.active.append([row.get(col) for col in REVIEW_COLUMNS])
    book.save(drafts / "凭证草稿_2026-06_2026-06.xlsx")
    book.close()
    config = root / "fixture.json"
    config.write_text(json.dumps({"watch_dir": "empty-watch", "runtime_dir": "runtime"}), encoding="utf-8")
    # This fixture deliberately disables startup diagnostics only. All tested HTTP
    # routes, parsers, CAS saves and Vue assets are the real application implementations.
    BackgroundSyncService.run_background_diagnostics = lambda *args, **kwargs: None
    app = create_app(root, config_path=str(config))
    state = app.state.invoice_hub
    created = state.companies.create_company({"revision": 0, "name": "P3 合成公司", "root_dir": str(company), "taxpayer_periods": [{"effective_from": "2026-01", "taxpayer_type": "general"}]})
    company_id = created["company"]["id"]
    state.company_views.tax.save(company_id, {"revision": 0, "months": {"2026-06": {"vat": {"assessment": {"output_tax": "100.00", "input_tax": "20.00", "transfer_out": "0.00", "opening_credit": "0.00", "ordinary_only": True, "source_kind": "user_assumption"}}}}})
    return app, company_id


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--port", type=int, required=True)
    args = parser.parse_args()
    with TemporaryDirectory(prefix="invoicehub-p3-") as temporary:
        app, company_id = create_fixture(Path(temporary))
        print(json.dumps({"company_id": company_id, "port": args.port}), flush=True)
        uvicorn.run(app, host="127.0.0.1", port=args.port, log_level="warning")


if __name__ == "__main__":
    main()
