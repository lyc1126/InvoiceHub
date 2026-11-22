"""Synthetic classic-home server. Fault controls exist only in this dev fixture."""
from __future__ import annotations

import argparse
import asyncio
import json
from pathlib import Path
from tempfile import TemporaryDirectory

import uvicorn
from fastapi import Request
from fastapi.responses import JSONResponse, Response

from invoice_hub.api.app import create_app
from invoice_hub.monitoring.state import MonitorState
from invoice_hub.monitoring.sync import MonitorSynchronizer
from invoice_hub.services.background_sync import BackgroundSyncService
from invoice_hub.targets import target_profile_for
from invoice_hub.targets.companies import company_taxpayer_for


def create_fixture(root: Path, *, break_refresh: bool = False):
    watch = root / "合成公司" / "成本发票"
    watch.mkdir(parents=True)
    for index in range(1, 104):
        seller = "合成供应方甲" if index % 2 else "合成供应方乙"
        xml = f"""<?xml version="1.0" encoding="UTF-8"?>
<EInvoice><Header><InvoiceNumber>{index:020d}</InvoiceNumber><IssueDate>2026-06-{index % 28 + 1:02d}</IssueDate>
<SellerName>{seller}</SellerName><BuyerName>合成公司</BuyerName>
<TotalAmWithoutTax>100.00</TotalAmWithoutTax><TotalTaxAm>13.00</TotalTaxAm>
<TotalTaxIncludedAmount>113.00</TotalTaxIncludedAmount></Header>
<IssuItemInformation><ItemName>*材料*螺纹钢</ItemName><SpecMod>12E</SpecMod><MeaUnits>吨</MeaUnits>
<Quantity>1</Quantity><UnPrice>100.00</UnPrice><Amount>100.00</Amount><TaxRate>0.13</TaxRate><ComTaxAm>13.00</ComTaxAm>
<TotalTaxIncludedAmount>113.00</TotalTaxIncludedAmount></IssuItemInformation></EInvoice>"""
        (watch / f"{index:020d}.xml").write_text(xml, encoding="utf-8")
        if index == 1:
            (watch / "同票副本.xml").write_text(xml, encoding="utf-8")
    config = root / "fixture.json"
    config.write_text(json.dumps({"watch_dir": "合成公司/成本发票", "runtime_dir": "runtime"}), encoding="utf-8")
    BackgroundSyncService.run_background_diagnostics = lambda *args, **kwargs: None
    app = create_app(root, config_path=str(config))
    state = app.state.invoice_hub
    cid = state.companies.create_company({"revision": 0, "name": "局部刷新合成公司", "root_dir": str(watch.parent),
        "taxpayer_periods": [{"effective_from": "2020-01", "taxpayer_type": "general"}]})["company"]["id"]
    profile = target_profile_for(state.config, watch)
    MonitorSynchronizer(MonitorState(profile, state.layout.db_path), repo=state.repo,
        company_taxpayer=lambda: company_taxpayer_for(state.config, watch),
        company_outbound=lambda: None).run_sync("E2E", force=True, emit_events=False, notify=False)
    controls = {"fail_next": False, "delay_next": False, "reads": 0}

    @app.middleware("http")
    async def fault_controls(request, call_next):
        if request.url.path == "/static/js/page-index.js" and break_refresh:
            source = Path(__file__).resolve().parents[2] / "web/static/js/page-index.js"
            text = source.read_text(encoding="utf-8")
            marker = "function syncVisibleInvoiceSelection() {\n"
            assert text.count(marker) == 1, "Refresh mutation no longer matches the implementation"
            # Restore the old whole-table repaint only in this isolated server.
            # The negative run must fail its DOM identity assertion, not startup.
            text = text.replace(marker, marker + '  refs.invoiceBody.innerHTML = state.invoiceItems.map(rowHtml).join("");\n')
            return Response(text, media_type="application/javascript", headers={"Cache-Control": "no-store"})
        if request.method == "GET" and request.url.path == "/api/v1/invoices":
            controls["reads"] += 1
            if controls["fail_next"]:
                controls["fail_next"] = False
                return JSONResponse({"detail": "合成故障：读取暂不可用"}, status_code=503)
            delayed = controls["delay_next"] and request.query_params.get("keyword") == "合成供应方甲"
            if delayed:
                controls["delay_next"] = False
                result = await call_next(request)
                await asyncio.sleep(1)
                return result
        return await call_next(request)

    @app.post("/__classic_fixture__/control")
    async def control(request: Request):
        body = await request.json()
        for key in ("fail_next", "delay_next"):
            if key in body:
                controls[key] = body[key] is True
        if body.get("refresh"):
            state.repo.append_event("invoice.changed", {"synthetic": True})
        return {"company_id": cid, **controls}

    return app


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--port", type=int, required=True)
    parser.add_argument("--root", type=Path)
    parser.add_argument("--break-refresh", action="store_true")
    args = parser.parse_args()
    with TemporaryDirectory(prefix="invoicehub-classic-") as temporary:
        root = args.root or Path(temporary)
        if any(root.iterdir()):
            parser.error("Fixture root must be an empty temporary directory")
        app = create_fixture(root, break_refresh=args.break_refresh)
        uvicorn.run(app, host="127.0.0.1", port=args.port, log_level="warning")


if __name__ == "__main__":
    main()
