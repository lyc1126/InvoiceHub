"""Synthetic cost V2 server, with one lost archive response; no local configuration."""
from __future__ import annotations

import argparse
import json
from decimal import Decimal
from pathlib import Path
from tempfile import TemporaryDirectory

import uvicorn
from fastapi.responses import JSONResponse

from invoice_hub.api.app import create_app
from invoice_hub.monitoring.sync import MonitorSynchronizer
from invoice_hub.monitoring.state import MonitorState
from invoice_hub.services.background_sync import BackgroundSyncService
from invoice_hub.targets import target_profile_for


def invoice(folder, number, day, qty, net, name="螺纹钢", spec="12E"):
    number = str(number).zfill(20)
    tax = Decimal(net) * Decimal("0.13")
    seller = "合成公司" if folder.name == "开具发票" else "合成供应方"
    (folder / f"{number}.xml").write_text(f"""<?xml version="1.0" encoding="UTF-8"?>
<EInvoice><Header><InvoiceNumber>{number}</InvoiceNumber><IssueDate>{day}</IssueDate>
<SellerName>{seller}</SellerName><BuyerName>合成公司</BuyerName>
<TotalAmWithoutTax>{net}</TotalAmWithoutTax><TotalTaxAm>{tax}</TotalTaxAm>
<TotalTaxIncludedAmount>{Decimal(net) + tax}</TotalTaxIncludedAmount></Header>
<IssuItemInformation><ItemName>*材料*{name}</ItemName><SpecMod>{spec}</SpecMod><MeaUnits>吨</MeaUnits>
<Quantity>{qty}</Quantity><UnPrice></UnPrice><Amount>{net}</Amount><TaxRate>0.13</TaxRate><ComTaxAm>{tax}</ComTaxAm>
<TotalTaxIncludedAmount>{Decimal(net) + tax}</TotalTaxIncludedAmount></IssuItemInformation></EInvoice>""", encoding="utf-8")


def create_fixture(root):
    company = root / "合成公司"
    for folder in ("成本发票", "开具发票"):
        (company / folder).mkdir(parents=True)
    config = root / "fixture.json"
    config.write_text(json.dumps({"watch_dir": "empty-watch", "runtime_dir": "runtime"}), encoding="utf-8")
    BackgroundSyncService.run_background_diagnostics = lambda *args, **kwargs: None
    app = create_app(root, config_path=str(config))
    state = app.state.invoice_hub
    cid = state.companies.create_company({"revision": 0, "name": "成本V2合成公司", "root_dir": str(company),
        "taxpayer_periods": [{"effective_from": "2020-01", "taxpayer_type": "general"}]})["company"]["id"]
    for number, day, qty, net in [(1, "2026-06-03", "10", "1000"), (2, "2026-07-02", "10", "2000")]:
        invoice(company / "成本发票", number, day, qty, net)
    invoice(company / "成本发票", 9, "2026-07-03", "1", "100", name="抗震螺纹钢")
    for number, day, qty, net in [(3, "2026-06-20", "5", "700"), (4, "2026-07-20", "3", "800"),
                                 (5, "2026-06-22", "1", "140"), (6, "2026-06-23", "1", "140")]:
        invoice(company / "开具发票", number, day, qty, net)
    for number, net in [(11, "1000"), (12, "2000")]:
        invoice(company / "开具发票", number, "2026-07-15", "", net, name="合成施工服务", spec="")
    (company / "项目归属.json").write_text(json.dumps({"version": 1, "revision": 1, "invoices": {
        str(11).zfill(20): {"project": "项目甲"}, str(12).zfill(20): {"project": "项目乙"}}}), encoding="utf-8")
    for folder in ("成本发票", "开具发票"):
        profile = target_profile_for(state.config, company / folder)
        MonitorSynchronizer(MonitorState(profile, state.layout.db_path), repo=state.repo,
            company_taxpayer=lambda: {"taxpayer_type": "general", "company_id": cid, "company_name": "合成公司",
                "taxpayer_periods": [{"effective_from": "2020-01", "taxpayer_type": "general"}]},
            company_outbound=lambda: str(company / "开具发票")).run_sync("E2E", force=True, emit_events=False, notify=False)
    counter = {"archive_put": 0, "item_type_put": 0, "service_put": 0}
    lost = False

    @app.middleware("http")
    async def lose_one_response(request, call_next):
        nonlocal lost
        path = request.url.path
        if request.method == "PUT":
            if "/records/" in path:
                counter["archive_put"] += 1
            elif path.endswith("/item-types"):
                counter["item_type_put"] += 1
            elif path.endswith("/service-costs"):
                counter["service_put"] += 1
        result = await call_next(request)
        # Fail only the response after the real archive has committed. The
        # frontend must query the same ID, never create a replacement archive.
        if request.method == "PUT" and "/records/" in path and result.status_code == 200 and not lost:
            lost = True
            return JSONResponse({"detail": "合成故障：已保存但响应丢失"}, status_code=503)
        return result

    @app.get("/__cost_v2_fixture__/state")
    async def fixture_state():
        return {"company_id": cid, "counts": counter}
    return app


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--port", type=int, required=True)
    parser.add_argument("--root", type=Path)
    args = parser.parse_args()
    with TemporaryDirectory(prefix="invoicehub-cost-v2-") as temporary:
        root = args.root or Path(temporary)
        if any(root.iterdir()):
            parser.error("Fixture root must be an empty temporary directory")
        app = create_fixture(root)
        uvicorn.run(app, host="127.0.0.1", port=args.port, log_level="warning")


if __name__ == "__main__":
    main()
