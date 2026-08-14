from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
APP_CSS_VERSION = "20260802-release-update-v1"
PAGE_INDEX_VERSION = "20260803-external-monitor-guard"


def _assets() -> tuple[str, str, str]:
    html = (ROOT / "web" / "templates" / "index.html").read_text(encoding="utf-8")
    js = (ROOT / "web" / "static" / "js" / "page-index.js").read_text(encoding="utf-8")
    css = (ROOT / "web" / "static" / "css" / "app.css").read_text(encoding="utf-8")
    return html, js, css


def test_preview_menu_order_and_two_item_keyboard_loop() -> None:
    html, js, _css = _assets()

    preview_index = html.index('id="previewSelectedInvoicesBtn"')
    print_index = html.index('id="printSelectedInvoicesBtn"')
    assert preview_index < print_index
    assert html.index("预览", preview_index) < print_index
    assert "return [refs.previewSelectedInvoicesBtn, refs.printSelectedInvoicesBtn].filter(Boolean);" in js
    assert 'if (event.key === "ArrowDown") nextIndex = (currentIndex + 1) % items.length;' in js
    assert 'if (event.key === "ArrowUp") nextIndex = (currentIndex - 1 + items.length) % items.length;' in js
    assert 'if (event.key === "Home") nextIndex = 0;' in js
    assert 'if (event.key === "End") nextIndex = items.length - 1;' in js
    assert 'setInvoiceActionMenuOpen(false, { returnFocus: true });' in js


def test_preview_dialog_focus_close_and_stable_states() -> None:
    html, js, css = _assets()

    assert 'id="filePreviewDialog"' in html
    assert 'role="dialog"' in html
    assert 'aria-modal="true"' in html
    for element_id in (
        "filePreviewLoading",
        "filePreviewError",
        "filePreviewImageStage",
        "filePreviewTextPanel",
        "filePreviewMetadata",
        "filePreviewRetryBtn",
    ):
        assert f'id="{element_id}"' in html
    assert 'if (event.target === refs.filePreviewModal) closeFilePreview();' in js
    assert 'if (event.key === "Escape")' in js
    assert "dialogFocusableElements(refs.filePreviewDialog)" in js
    assert "state.filePreviewReturnFocus = refs.invoiceSelectionMoreBtn;" in js
    assert "window.setTimeout(() => returnFocus.focus(), 0);" in js
    assert 'document.documentElement.classList.toggle("selection-summary-modal-open", modalOpen);' in js
    assert 'document.body.classList.toggle("selection-summary-modal-open", modalOpen);' in js
    assert "html.selection-summary-modal-open," in css
    assert "refs.filePreviewRetryBtn?.addEventListener(\"click\", loadFilePreviewJob);" in js
    assert "stopFilePreviewKeepAlive();" in js
    assert ".file-preview-viewport" in css
    assert "min-height: 0;" in css


def test_preview_file_page_zoom_and_open_controls() -> None:
    html, js, css = _assets()

    for element_id in (
        "filePreviewFileSelect",
        "filePreviewPreviousFileBtn",
        "filePreviewNextFileBtn",
        "filePreviewPreviousPageBtn",
        "filePreviewPageSelect",
        "filePreviewNextPageBtn",
        "filePreviewZoomRange",
        "filePreviewFitWidthBtn",
        "filePreviewOpenFileBtn",
        "filePreviewOpenLocationBtn",
    ):
        assert f'id="{element_id}"' in html
    assert 'type="range" min="50" max="200"' in html
    assert "function changeFilePreview(delta)" in js
    assert "function changeFilePreviewPage(delta)" in js
    assert 'refs.filePreviewImage.style.width = state.filePreviewFitWidth ? "auto" : `${zoom}%`;' in js
    assert 'dataset.fitWidth = state.filePreviewFitWidth ? "true" : "false"' in js
    assert 'openCurrentFilePreviewTarget(refs.filePreviewOpenFileBtn, "open_file_url"' in js
    assert 'openCurrentFilePreviewTarget(refs.filePreviewOpenLocationBtn, "open_location_url"' in js
    assert ".file-preview-toolbar .btn" in css
    assert "min-height: 44px;" in css


def test_preview_xml_is_text_only_and_failures_do_not_block_switching() -> None:
    _html, js, _css = _assets()
    preview_block = js[js.index("async function loadFilePreviewContent"):js.index("async function loadFilePreviewJob")]

    assert "refs.filePreviewText.textContent = text;" in preview_block
    assert "filePreviewText.innerHTML" not in js
    assert 'file.preview_type === "metadata"' in preview_block
    assert 'file.preview_type === "error"' in preview_block
    assert "showFilePreviewError(error);" in preview_block
    assert "refs.filePreviewPreviousFileBtn?.addEventListener" in js
    assert "refs.filePreviewNextFileBtn?.addEventListener" in js
    assert "requestId !== state.filePreviewContentRequestId" in preview_block


def test_preview_api_urls_responsive_modal_and_cache_versions() -> None:
    html, js, css = _assets()

    assert 'app.api("/api/v1/invoices/preview-jobs"' in js
    assert "keep_alive_url" in js
    assert "function scheduleFilePreviewKeepAlive" in js
    assert "function keepFilePreviewAlive" in js
    assert "status === 404 || status === 410" in js
    assert 'loadFilePreviewJob({ preservePosition: true, automatic: true })' in js
    assert "state.filePreviewSelectionItems = selectedSummaryRequestItems();" in js
    assert "const previousFileName = previousFile?.name || previousFile?.file_name || \"\";" in js
    assert "Math.min(activePageCount, Math.max(1, options.preservePosition ? previousPageNumber : 1))" in js
    assert "state.filePreviewSelectionItems = [];" in js
    assert 'document.addEventListener("visibilitychange"' in js
    assert "/files/${encodeURIComponent(file.file_number)}/pages/${pageNumber}" in js
    assert "file.text_url" in js
    assert '@media (max-width: 640px)' in css
    assert ".file-preview-dialog" in css
    assert "height: 100dvh;" in css
    assert "flex-wrap: wrap;" in css
    assert "@media (prefers-reduced-motion: reduce)" in css
    assert f"app.css?v={APP_CSS_VERSION}" in html
    assert f"page-index.js?v={PAGE_INDEX_VERSION}" in html

    for template in (ROOT / "web" / "templates").glob("*.html"):
        source = template.read_text(encoding="utf-8")
        if "app.css?v=" in source:
            assert f"app.css?v={APP_CSS_VERSION}" in source
