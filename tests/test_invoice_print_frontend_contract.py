import re
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


def test_invoice_selection_menu_exposes_batch_print_action() -> None:
    html = (ROOT / "web" / "templates" / "index.html").read_text(encoding="utf-8")
    js = (ROOT / "web" / "static" / "js" / "page-index.js").read_text(encoding="utf-8")
    css = (ROOT / "web" / "static" / "css" / "app.css").read_text(encoding="utf-8")

    assert 'id="invoiceSelectionMoreBtn"' in html
    assert 'aria-haspopup="menu"' in html
    assert 'aria-controls="invoiceSelectionActionMenu"' in html
    assert 'id="invoiceSelectionActionMenu" class="invoice-action-menu" role="menu"' in html
    assert 'id="printSelectedInvoicesBtn"' in html
    assert "打印已勾选发票" in html
    assert "&gt;&gt;" in html
    assert ".invoice-action-menu[hidden]" in css
    assert ".invoice-action-menu__item:focus-visible" in css
    assert "width: 44px;" in css

    print_function = re.search(
        r"async function printSelectedInvoices\(\) \{(?P<body>.*?)\n\}",
        js,
        re.S,
    )
    assert print_function is not None
    body = print_function.group("body")
    assert 'window.open("about:blank", "_blank")' in body
    assert body.index('window.open("about:blank", "_blank")') < body.index(
        'await app.api("/api/v1/invoices/print-jobs"'
    )
    assert "浏览器阻止了打印窗口" in js
    assert "setInvoiceActionMenuOpen" in js
    assert "handleInvoiceActionMenuKeydown" in js
    assert 'event.key === "Escape"' in js


def test_invoice_print_page_uses_native_print_and_one_sheet_per_source_page() -> None:
    html = (ROOT / "web" / "templates" / "invoice_print.html").read_text(encoding="utf-8")
    api = (ROOT / "src" / "invoice_hub" / "api" / "app.py").read_text(encoding="utf-8")
    service = (ROOT / "src" / "invoice_hub" / "services" / "invoice_printing.py").read_text(encoding="utf-8")

    assert "@page invoice-landscape { size: landscape; margin: 0; }" in html
    assert "@page invoice-portrait { size: portrait; margin: 0; }" in html
    assert "size: A4" not in html
    assert "html, body, main { width: 100%; height: 100%; min-height: 0;" in html
    assert ".print-sheet {\n        width: 100%;\n        height: 100%;" in html
    assert "width: 100vw;" not in html
    assert "height: 100vh;" not in html
    assert ".print-sheet + .print-sheet" in html
    assert "break-before: page" in html
    assert "page-break-before: always" in html
    assert "break-inside: avoid" in html
    assert "page-break-inside: avoid" in html
    assert "width: 297mm;" not in html
    assert "height: 210mm;" not in html
    assert 'typeof image.decode === "function"' in html
    assert "await image.decode()" in html
    assert html.count("window.requestAnimationFrame(") == 2
    assert "await waitForPrintableFrame()" in html
    assert html.index("await image.decode()") < html.index("await waitForPrintableFrame()")
    assert html.index("await waitForPrintableFrame()") < html.index("requestBrowserPrint();")
    assert "window.print()" in html
    assert 'window.addEventListener("beforeprint"' in html
    assert 'window.addEventListener("afterprint"' in html
    assert 'id="printAgainBtn"' in html
    assert "当前浏览器不提供打印功能" in html
    assert '@app.post("/api/v1/invoices/print-jobs")' in api
    assert '@app.get("/invoices/print/{job_id}"' in api
    assert '@app.get("/api/v1/invoices/print-jobs/{job_id}/pages/{page_number}")' in api
    assert "MAX_PRINT_SELECTION_RECORDS = 100" in service
    assert "MAX_PRINT_PAGES = 200" in service
    assert "MAX_PRINT_JOB_BYTES" in service
    assert "PRINT_JOB_TTL_SECONDS" in service


def test_invoice_print_static_asset_versions_are_current() -> None:
    templates = list((ROOT / "web" / "templates").glob("*.html"))
    for template in templates:
        html = template.read_text(encoding="utf-8")
        if "app.css?v=" in html:
            assert "app.css?v=20260802-release-update-v1" in html
    index = (ROOT / "web" / "templates" / "index.html").read_text(encoding="utf-8")
    assert "page-index.js?v=20260803-external-monitor-guard" in index
