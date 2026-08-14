import re
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


def _css_brace_depth_at(source: str, offset: int) -> int:
    """Return the CSS block depth at offset while ignoring comments and strings."""
    depth = 0
    index = 0
    quote = ""
    while index < offset:
        current = source[index]
        following = source[index + 1] if index + 1 < offset else ""
        if quote:
            if current == "\\":
                index += 2
                continue
            if current == quote:
                quote = ""
            index += 1
            continue
        if current == "/" and following == "*":
            closing = source.find("*/", index + 2, offset)
            if closing == -1:
                return depth
            index = closing + 2
            continue
        if current in {"'", '"'}:
            quote = current
        elif current == "{":
            depth += 1
        elif current == "}":
            depth -= 1
        index += 1
    return depth


def _assert_css_selector_is_top_level(source: str, selector_pattern: str) -> None:
    selector = re.search(selector_pattern, source, re.MULTILINE)
    assert selector is not None, selector_pattern
    assert _css_brace_depth_at(source, selector.start()) == 0, selector_pattern


def test_cost_page_keeps_required_controls() -> None:
    html = (ROOT / "web" / "templates" / "costs.html").read_text(encoding="utf-8")
    js = (ROOT / "web" / "static" / "js" / "page-costs.js").read_text(encoding="utf-8")
    css = (ROOT / "web" / "static" / "css" / "app.css").read_text(encoding="utf-8")

    assert "开票参考" in html
    assert "复制当前表格" in html
    assert "保存状态" in html
    assert "批量设为已开具" in html
    assert "批量设为未开具" in html
    assert "打开成本分析表" in html
    assert "系统服务连接状态" in html
    assert "service-status service-status--muted" in html
    assert "list-controls" in html
    assert "cost-actions" in html
    assert "cost-tabs" in html
    assert "cost-view-switcher" in html
    assert "cost-formula-help-wrap" in html
    assert "cost-formula-help" in html
    assert 'aria-label="平均单价算法说明"' in html
    assert 'aria-describedby="costFormulaTooltip"' in html
    assert 'id="costFormulaTooltip" class="cost-formula-tooltip" role="tooltip"' in html
    assert "平均单价算法说明" in html
    assert "平均单价(含税) = (金额(除税) + 税金) / 数量" in html
    assert "库存平均单价(除税) = sum(金额(除税)) / sum(数量)" in html
    assert "库存平均单价(含税) = sum(金额(除税)+税金) / sum(数量)" in html
    assert "采购参考平均单价(含税) = avg(明细行含税原始单价)" in html
    assert "平均单价(含税) = 平均单价(除税) × 1.13" in html
    assert "最近保存的文件夹" in js
    assert "入库总量合计" in html
    assert "已开库存合计金额" in html
    assert "未开库存合计金额" in html
    assert "markupRateInput" not in html
    assert "markupRateLockBtn" not in html
    assert "data-markup-rate-input" not in html
    assert "开票加价率</span>" not in html
    assert "batchMarkupInput" in html
    assert "批量锁定加价率" in html
    assert "批量解锁加价率" in html
    assert "平均单价(含税)" in js
    assert "renderProjectAverageWithTax" in js
    assert "renderProjectPurchaseReferenceWithTax" in js
    assert "formatUnitPrice" in js
    assert '["平均单价(含税)", "平均单价(含税)"]' in js
    assert 'numberValue(row["价税合计"]) / quantity' not in js
    project_columns = re.search(r"const projectColumns = \[(?P<body>.*?)\]\.map", js, re.S)
    assert project_columns is not None
    project_columns_body = project_columns.group("body")
    assert "库存平均单价(含税)" in project_columns_body
    assert "采购参考平均单价(含税)" in project_columns_body
    assert "平均单价(除税)" not in project_columns_body
    reference_columns = re.search(r"const referenceColumns = \[(?P<body>.*?)\];", js, re.S)
    assert reference_columns is not None
    reference_columns_body = reference_columns.group("body")
    assert "reference_average_unit_price_with_tax" in reference_columns_body
    assert "renderReferenceAverageWithTax" in reference_columns_body
    assert '"平均单价(含税)"' in reference_columns_body
    assert "row.reference_average_unit_price_with_tax" in js
    assert "numberValue(row.total_with_tax) / quantity" not in js
    assert "const referenceAverageUnitPrice = numberValue(source.average_unit_price) * multiplier;" in js
    assert "const referenceAmount = referenceAverageUnitPrice * max;" in js
    assert "const referenceTax = referenceAmount * 0.13;" in js
    assert "const referenceTotal = referenceAmount + referenceTax;" in js
    assert "const referenceAverageWithTax = referenceAverageUnitPrice * 1.13;" in js
    assert "const referenceAmount = numberValue(source.amount) * multiplier;" not in js
    assert "referenceAverageWithTax = numberValue(source.average_unit_price) * 1.13 * multiplier" not in js
    assert "inventory_total_with_tax" in js
    assert "invoiced_reference_total_with_tax" in js
    assert "uninvoiced_reference_total_with_tax" in js
    assert '"markup_rate", label: "加价率"' in js
    assert "data-reference-markup-key" in js
    assert "data-reference-markup-toggle" in js
    assert "reference_markup_rate_percent" in js
    assert "reference_markup_locked" in js
    assert "/api/v1/cost-analysis/reference-markup-rate" not in js
    assert "sanitizeMarkupRateText" in js
    assert "shouldAllowMarkupRateInput" in js
    assert "applySelectedMarkup" in js
    assert "锁定" in js
    assert "解锁" in js
    assert "common.js?v=20260729-main-macos-sync" in html
    assert "app.css?v=20260802-release-update-v1" in html
    assert "page-costs.js?v=20260726-invoice-taxonomy" in html
    for token in (
        "发票大类",
        "特定业务类型",
        "类型识别状态",
        "类型识别说明",
        "发票税金",
        "解析税金",
        "差异(税金)",
        "review_count",
    ):
        assert token in js
    assert html.count('class="cost-table-footer"') == 4
    assert 'data-cost-row-count="details"' in html
    assert 'data-cost-row-count="project"' in html
    assert 'data-cost-row-count="reference"' in html
    assert 'data-cost-row-count="checks"' in html
    assert html.count('data-cost-row-limit="30"') == 4
    assert html.count('data-cost-row-limit="60"') == 4
    assert html.count('data-cost-row-limit="100"') == 4
    assert html.count('aria-pressed="true">30</button>') == 4
    assert html.count('aria-pressed="false">60</button>') == 4
    assert html.count('aria-pressed="false">100</button>') == 4
    assert "COST_ROW_LIMITS = [30, 60, 100]" in js
    assert 'COST_ROW_LIMIT_STORAGE_KEY = "invoiceHub.costs.rowLimit"' in js
    assert "rowLimit: loadCostRowLimit()" in js
    assert "Math.min(state.rowLimit, totalRows)" in js
    assert "loadCostPreferences" in js
    assert "saveCostPreferences" in js
    assert "/api/v1/preferences" in js
    assert 'shell.style.setProperty("--cost-table-max-height", `${maxHeight}px`);' in js
    assert "app.renderTable(table, config.rows, config.columns);" in js
    assert "config.rows.slice" not in js
    assert "renderCostView" in js
    assert "resetRenderedCostViews" in js
    assert "renderedViews: new Set()" in js
    assert "renderCostView(state.activeView);" in js
    assert "COST_AUTO_REFRESH_DEBOUNCE_MS = 350" in js
    assert "scheduleCostAutoRefresh(reason);" in js
    assert "runQueuedCostAutoRefresh" in js
    assert "costAutoRefreshInFlight" in js
    assert "async function loadCostsNow" in js
    assert "app.connectEvents(refs.eventState, loadCosts, { refreshOnFirstOpen: false });" in js
    assert '<section class="tabs" role="tablist" aria-label="成本分析视图">' not in html
    assert '<div class="tabs cost-tabs" role="tablist" aria-label="成本分析视图">' in html
    assert '<div class="toolbar cost-actions">' in html
    assert "table-scroll-x" not in html
    assert html.index('<section class="stats-grid">') < html.index('<section class="list-controls"') < html.index('<section class="panel cost-view" data-view="details">')
    assert html.index('<div class="toolbar cost-actions">') < html.index('<div class="cost-view-switcher">') < html.index('<div class="tabs cost-tabs"') < html.index('<section class="panel cost-view" data-view="details">')
    assert 'href="/backend"' not in html
    common = (ROOT / "web" / "static" / "js" / "common.js").read_text(encoding="utf-8")
    assert "cost_analysis.reference_status_updated" in common
    assert 'if (/部分开具/.test(text)) return "partial";' in common
    assert 'if (/未开具/.test(text)) return "pending";' in common
    assert "data-reference-max" in js
    assert 'type="text" inputmode="decimal"' in js
    assert 'pattern="[0-9]*(\\\\.[0-9]*)?"' in js
    assert "data-reference-max-value" in js
    assert "beforeinput" in js
    assert "shouldAllowQuantityInput" in js
    assert "sanitizeQuantityText" in js
    assert "quantityWithinMax" in js
    assert "dataTransfer?.getData" in js
    assert "isCompleteQuantityText" in js
    assert "aria-invalid" in js
    assert "检查开票参考" in js
    assert "已开数量和加价率只能输入数字，已开数量不能超过数量合计" in js
    assert 'input.value = formatQuantity(next)' not in js
    assert 'input.getAttribute("max")' not in js
    assert "state.dirty.set" in js
    assert "captureReferenceFocus" in js
    assert "restoreReferenceFocus" in js
    assert "setSelectionRange" in js
    assert "isAutoRefreshReason" in js
    assert "正在编辑开票数量或加价率，已暂停自动刷新表格" in js
    assert "保存状态（" in js
    assert "updateReferenceControls" in js
    assert "app.setBusy" in js
    assert ".cost-view[hidden]" in css
    assert "@keyframes page-enter" in css
    assert "@keyframes page-exit" in css
    assert "@keyframes view-switch-in" in css
    assert "body.is-page-exiting" in css
    assert "body.is-page-exiting .shell" in css
    assert "animation: page-enter 140ms ease-out both;" in css
    assert "animation: page-exit 80ms ease-in both;" in css
    assert "animation: view-switch-in 120ms ease-out both;" in css
    assert ".cost-view:not([hidden])" in css
    assert ".document-view:not([hidden])" in css
    assert "@media (prefers-reduced-motion: reduce)" in css
    assert ".page-head__actions" in css
    assert "min-width: min(100%, 320px)" in css
    assert ".list-controls" in css
    assert ".cost-actions" in css
    assert ".service-status--success" in css
    assert ".service-status--warning" in css
    assert ".status-pill--partial" in css
    assert ".status-pill--pending" in css
    assert ".cost-view-switcher" in css
    assert ".cost-formula-help" in css
    assert ".cost-formula-tooltip" in css
    assert ".cost-formula-help-wrap:hover .cost-formula-tooltip" in css
    assert ".cost-formula-help-wrap:focus-within .cost-formula-tooltip" in css
    assert "bottom: calc(100% + 10px)" in css
    assert ".cost-tabs" in css
    assert "justify-content: flex-end" in css
    assert ".batch-markup-control" in css
    assert ".reference-markup-control" in css
    assert ".reference-markup-input[readonly]" in css
    assert ".cost-view .table-shell" in css
    assert "max-height: var(--cost-table-max-height, 62vh)" in css
    assert "overflow-y: auto;" in css
    cost_shell_rule = re.search(r'body\[data-page="costs"\]\s+\.cost-view\s+\.table-shell\s*\{(?P<body>[^}]*)\}', css, re.S)
    assert cost_shell_rule
    assert "overflow-y: auto !important;" in cost_shell_rule.group("body")
    ocr_shell_rule = re.search(r'body\[data-page="ocr"\]\s+\.table-shell\s*\{(?P<body>[^}]*)\}', css, re.S)
    assert ocr_shell_rule
    assert "max-height: none" in ocr_shell_rule.group("body")
    assert "overflow-x: auto" in ocr_shell_rule.group("body")
    assert "overflow-y: hidden" in ocr_shell_rule.group("body")
    assert "scrollbar-gutter: auto" in ocr_shell_rule.group("body")
    root_scroll_rule = re.search(r'body\[data-page="documents"\],\s*body\[data-page="ocr"\]\s*\{(?P<body>[^}]*)\}', css, re.S)
    assert root_scroll_rule
    assert "overflow-x: clip" in root_scroll_rule.group("body")
    assert "overflow-y: visible" in root_scroll_rule.group("body")
    assert "overscroll-behavior: contain;" not in css
    assert "overscroll-behavior-x: contain;" in css
    assert "overscroll-behavior-y: auto;" in css
    assert "overscroll-behavior-y: auto !important;" in css
    assert ".cost-table-footer" in css
    assert ".cost-table-count" in css
    assert ".cost-row-limit-control" in css
    assert ".cost-row-limit-btn[aria-pressed=\"true\"]" in css
    assert ".table-scroll-x" not in css
    assert "#referenceTable" in css
    assert "table-layout: fixed" in css
    assert "#detailsTable" in css
    assert "min-width: 1520px" in css
    assert "#projectTable" in css
    assert "min-width: 1420px" in css
    assert "min-width: 1560px" in css
    assert "#referenceTable th:nth-child(14)" in css
    assert ".reference-number" in css
    assert ".reference-text" in css
    assert ".reference-text__inner" in css
    assert "reference-text-marquee" in css
    assert "updateReferenceTextMarquee" in js
    assert 'document.querySelectorAll(".cost-view .reference-text")' in js
    assert "renderCostCell" in js
    assert "costText" in js
    assert "costNumber" in js
    reference_inner_rule = re.search(r"\.reference-text__inner\s*\{(?P<body>[^}]*)\}", css, re.S)
    assert reference_inner_rule is not None
    reference_inner_body = reference_inner_rule.group("body")
    assert "text-overflow: ellipsis" not in reference_inner_body
    assert "text-overflow: clip" in reference_inner_body
    assert "overflow: visible" in reference_inner_body
    assert "min-width: max-content" in reference_inner_body
    assert ".reference-text.has-overflow {\n  text-align: left;" in css
    assert "animation: reference-text-marquee var(--reference-text-scroll-duration, 6s) linear 1 forwards;" in css
    reference_marquee_rule = re.search(r"\.reference-text\.has-overflow:hover \.reference-text__inner,\s*\.reference-text\.has-overflow:focus \.reference-text__inner,\s*\.reference-text\.has-overflow:focus-within \.reference-text__inner\s*\{(?P<body>[^}]*)\}", css, re.S)
    assert reference_marquee_rule is not None
    assert "infinite alternate" not in reference_marquee_rule.group("body")
    assert "updateReferenceStatsFromDrafts" in js
    assert "referenceDraftMetrics" in js
    assert 'await loadCosts("save");' in js
    assert "updateReferenceStatsFromDrafts();" in js
    assert "setMarkupControlState(input, markupButton, nextLocked);\n  updateReferenceRowByKey(key);" in js
    assert 'cells[6].innerHTML = referenceNumber(formatUnitPrice(metrics.referenceAverageWithTax), "average-unit-price-with-tax");' in js
    assert 'cells[8].innerHTML = referenceNumber(formatReferenceAmount(metrics.referenceTotal), "reference-total");' in js
    assert 'cells[13].innerHTML = referenceNumber(formatReferenceAmount(metrics.uninvoicedReferenceAmount), "uninvoiced-reference-amount");' in js
    assert "refs.invoicedReferenceTotal.textContent = app.formatMoney(invoicedTotal);" in js
    assert "refs.uninvoicedReferenceTotal.textContent = app.formatMoney(uninvoicedTotal);" in js
    assert "tabindex=\"0\"" in js
    assert "text-align: center" in css
    assert ".cost-view .data-table" in css
    assert "font-size: 15px" in css
    assert "white-space: nowrap" in css
    assert "overflow-x: auto" in css
    assert "text-overflow: ellipsis" in css
    assert ".quantity-control" in css
    assert "width: 112px" in css
    assert ".reference-quantity-input" in css


def test_main_pages_keep_user_visible_controls() -> None:
    index = (ROOT / "web" / "templates" / "index.html").read_text(encoding="utf-8")
    ocr = (ROOT / "web" / "templates" / "ocr.html").read_text(encoding="utf-8")
    detail = (ROOT / "web" / "templates" / "detail.html").read_text(encoding="utf-8")
    page_detail = (ROOT / "web" / "static" / "js" / "page-detail.js").read_text(encoding="utf-8")
    common = (ROOT / "web" / "static" / "js" / "common.js").read_text(encoding="utf-8")
    page_ocr = (ROOT / "web" / "static" / "js" / "page-ocr.js").read_text(encoding="utf-8")

    assert "选择文件夹" in index
    assert "保存目录" in index
    assert "service-status service-status--muted" in index
    assert "watchDirDraft" in index
    assert "watchDirHistory" in index
    assert "businessDossierPanel" in index
    assert "businessDossierLinks" in index
    assert "打开公司资料夹" in index
    assert "业务资料夹快速入口" in index
    assert "当前使用" in index
    assert "过去保存" in index
    assert 'class="inline-panel path-inline" hidden' not in index
    assert 'id="watchDirDraft" class="watch-dir-draft" hidden' in index
    assert "app.css?v=20260802-release-update-v1" in index
    assert "settings-actions.css?v=20260720-shutdown-monitor-choice" in index
    assert "common.js?v=20260729-main-macos-sync" in index
    assert "page-index.js?v=20260803-external-monitor-guard" in index
    assert 'select name="invoice_type"' in index
    assert 'select name="business_type"' in index
    assert 'select name="classification_status"' in index
    assert "增值税专用发票" in index
    assert "增值税普通发票" in index
    assert "标准电子发票" in index
    assert "差额征税全额开票" in index
    assert '<option value="conflict">冲突</option>' in index
    assert "pageOperationNotice" in index
    assert "recentWatchDirs" in index
    assert "watch-dir-options--recent" in index
    page_index = (ROOT / "web" / "static" / "js" / "page-index.js").read_text(encoding="utf-8")
    assert "bridge?.ready !== false" in page_index
    assert "bridge?.observer_active !== false" in page_index
    assert "indexBackendIsExternallyManaged" in page_index
    assert "runOwnedMonitorAction" in page_index
    assert 'bridge.backendOwnership === "externalCompatible"' in page_index
    assert "showOperationNotice" in page_index
    assert "operationNoticeRefs" in page_index
    assert "prepareOperationNotice" in page_index
    assert "document.body.append(root)" in page_index
    assert "--operation-notice-top" in page_index
    assert "renderWatchDirHistory" in page_index
    assert "data-watch-dir-option" in page_index
    assert "data-remove-watch-dir" in page_index
    assert "removeRecentWatchDir" in page_index
    assert "renderBusinessDossier" in page_index
    assert "renderBusinessDossierFailure" in page_index
    assert "loadBusinessDossier" in page_index
    assert "loadBusinessDossierSafely" in page_index
    assert "openBusinessDossier" in page_index
    assert "/api/v1/business-dossier" in page_index
    assert "/api/v1/business-dossier/open" in page_index
    assert "data-business-open-key" in page_index
    assert "cost_invoice_dir" in page_index
    assert "bank_flow_dir" in page_index
    assert "input_deduction_dir" in page_index
    assert "nativePickWatchDir" in page_index
    assert "window.invoiceHubMac.pickWatchDir" in page_index
    assert "/api/v1/settings/pick-watch-dir" in page_index
    assert "payload.message || successMessage" in page_index
    assert "payload.message || \"目录已保存\"" in page_index
    assert "payload.has_supported_files !== false" in page_index
    assert "/api/v1/settings/recent-watch-dirs/remove" in page_index
    assert "updateWatchDirMarquee" in page_index
    assert "requestAnimationFrame" in page_index
    assert "watch-dir-option__remove" in page_index
    assert "watch-dir-option__clip" in page_index
    assert "watch-dir-option__text" in page_index
    assert "暂无过去保存的文件夹" in page_index
    assert "watchDirHistory?.addEventListener" in page_index
    assert "event.stopPropagation()" in page_index
    assert 'role="status" aria-live="polite"' in index
    assert "recognitionStatusMeta" in page_index
    assert "item.invoice_type" in page_index
    assert "item.business_type" in page_index
    assert "item.classification_status" in page_index
    assert "item.classification_issue" in page_index
    assert "classificationIssueHtml" not in page_index
    assert "打开本地文件" in index
    assert "勾选价税合计金额" in index
    assert "selectedInvoiceTotal" in index
    assert "selectedInvoiceCount" in index
    assert "invoice-selection-tools" in index
    assert "invoice-selection-actions" in index
    assert "selectAllInvoicesBtn" in index
    assert "clearSelectedInvoicesBtn" in index
    assert "一键全选" in index
    assert "清除勾选" in index
    assert index.index('class="invoice-selection-actions"') < index.index('id="selectedInvoiceTotal"')
    assert "<th>格式</th>" in index
    assert "<th>勾选</th>" in index
    assert 'id="invoiceDateHeader" aria-sort="none"' in index
    assert 'id="invoiceDateSortBtn" class="sort-toggle" type="button" data-sort-direction="none"' in index
    assert 'aria-label="按开票时间正序排序"' in index
    assert "sort-toggle__icon--asc" in index
    assert "sort-toggle__icon--desc" in index
    assert "监控状态" in index
    assert "当前筛选合计" in index
    assert "仅累计合法金额" in index
    assert 'href="/backend"' not in index
    assert "watchDirDirty" in page_index
    assert "pendingWatchDir" in page_index
    assert "setWatchDirInputValue" in page_index
    assert "scrollLeft" in page_index
    assert "待保存发票目录" in page_index
    assert "待保存目录" in page_index
    assert "目录已选择，请点击“保存目录”生效" in page_index
    assert "selectedInvoices: new Map()" in page_index
    assert "invoiceAmountValue" in page_index
    assert "updateSelectedInvoiceTotal" in page_index
    assert "selectableInvoiceCount" in page_index
    assert "updateSelectionControls" in page_index
    assert "selectAllVisibleInvoices" in page_index
    assert "clearSelectedInvoices" in page_index
    assert 'refs.selectAllInvoicesBtn?.addEventListener("click", selectAllVisibleInvoices)' in page_index
    assert 'refs.clearSelectedInvoicesBtn?.addEventListener("click", clearSelectedInvoices)' in page_index
    assert "pruneSelectedInvoices" in page_index
    assert "dateSort" in page_index
    assert "invoiceDateSortValue" in page_index
    assert "sortedInvoiceItems" in page_index
    assert "updateDateSortControl" in page_index
    assert "renderInvoiceRows" in page_index
    assert 'refs.invoiceDateSortBtn?.addEventListener("click"' in page_index
    assert 'refs.invoiceDateHeader.setAttribute("aria-sort"' in page_index
    assert 'state.dateSort === "asc" ? "desc" : "asc"' in page_index
    assert "fileFormatFromPath" in page_index
    assert "fileFormatLabel" in page_index
    assert "fileFormatFromPath(item.source_file)" in page_index
    assert "fileFormatFromPath(item.file_path)" in page_index
    assert "format-badge format-badge--" in page_index
    assert "data-invoice-select" in page_index
    assert "data-invoice-amount" in page_index
    assert "已勾选 ${invoiceCount} 张（${recordCount} 条记录）" in page_index
    assert 'td colspan="10"' in page_index
    assert 'refs.pickBtn.addEventListener("click", pickWatchDir)' in page_index
    assert 'refs.saveBtn.addEventListener("click", saveWatchDir)' in page_index
    assert "monitor.sync_completed" in common
    assert "cost_analysis.reference_markup_rate_updated" not in common
    assert "系统服务连接状态：已连接" in common
    assert "系统服务连接状态：重连中" in common
    assert "setServiceStatus" in common
    assert "service-status--${tone" in common
    assert "[hidden] { display: none !important; }" in (ROOT / "web" / "static" / "css" / "app.css").read_text(encoding="utf-8")
    css = (ROOT / "web" / "static" / "css" / "app.css").read_text(encoding="utf-8")
    assert ".watch-dir-history" in css
    assert "--watch-dir-option-width" in css
    assert ".watch-dir-options--recent" in css
    assert "overflow-y: auto" in css
    assert "scrollbar-gutter: stable" in css
    assert "scrollbar-gutter: stable both-edges" not in css
    assert ".watch-dir-option-shell" in css
    assert ".watch-dir-option__remove" in css
    assert "width: 18px" in css
    assert "font-size: 12px" in css
    assert ".watch-dir-option__clip" in css
    assert ".watch-dir-option__text" in css
    assert ".watch-dir-option.has-overflow:hover .watch-dir-option__text" in css
    assert "@keyframes watch-dir-marquee" in css
    assert "prefers-reduced-motion" in css
    assert ".business-dossier" in css
    assert ".business-dossier__head" in css
    assert ".business-dossier__links" in css
    assert ".business-dossier__link" in css
    assert ".selection-summary" in css
    assert ".invoice-selection-tools" in css
    assert ".invoice-selection-actions" in css
    assert ".invoice-selection-actions .btn" in css
    assert ".sortable-heading" in css
    assert "button.sort-toggle" in css
    sort_toggle_rule = re.search(r"button\.sort-toggle\s*\{(?P<body>[^}]*)\}", css, re.S)
    assert sort_toggle_rule is not None
    sort_toggle_body = sort_toggle_rule.group("body")
    assert "border: 0" in sort_toggle_body
    assert "background: transparent" in sort_toggle_body
    assert "box-shadow: none" in sort_toggle_body
    assert "color: inherit" in sort_toggle_body
    sort_toggle_hover = re.search(r"button\.sort-toggle:hover:not\(:disabled\),\s*button\.sort-toggle:active:not\(:disabled\)\s*\{(?P<body>[^}]*)\}", css, re.S)
    assert sort_toggle_hover is not None
    assert "background: transparent" in sort_toggle_hover.group("body")
    assert ".sort-toggle__icon--asc" in css
    assert ".sort-toggle__icon--desc" in css
    assert 'button.sort-toggle[data-sort-direction="asc"] .sort-toggle__icon--asc' in css
    assert ".invoice-checkbox" in css
    assert ".table__select" in css
    assert "table-layout: fixed" in css
    assert ".table__seller" in css
    assert ".table__format" in css
    assert ".format-badge--pdf" in css
    assert ".format-badge--ofd" in css
    assert ".format-badge--xml" in css
    assert ".format-badge--unknown" in css
    assert "选择文件" in ocr
    assert 'href="/backend"' not in ocr
    assert "复制结果" in ocr
    assert "page-ocr.js?v=20260717-settings-macos-sync" in ocr
    assert "loadOcrPreferences" in page_ocr
    assert "saveOcrFolderPreference" in page_ocr
    assert "/api/v1/preferences" in page_ocr
    assert "保存修订" in detail
    assert "本票成本明细" in detail
    assert '<h3 id="detailCostTitle">本票成本明细</h3>' in detail
    assert "<h4" not in detail
    assert "detailCostBreakdown" in detail
    assert "detailCostMeta" in detail
    assert 'class="detail-cost-body" role="region" aria-label="本票成本明细"' in detail
    assert "源文件与状态" in detail
    assert "一致性信息" not in detail
    assert "consistencyCard" not in detail
    assert "detail-grid" in detail
    assert "detail-side-column" in detail
    assert "detail-manual-panel" in detail
    assert "detail-cost-panel" in detail
    assert 'class="toolbar detail-file-actions" aria-label="源文件操作"' in detail
    assert 'id="openSourceBtn" class="btn btn--secondary" type="button">打开文件</button>' in detail
    assert 'id="openSourceLocationBtn" class="btn btn--secondary" type="button">打开文件所在位置</button>' in detail
    assert detail.index("<h3>核心字段</h3>") < detail.index("openSourceBtn") < detail.index("openSourceLocationBtn") < detail.index('id="detailSummary"')
    assert detail.index("<h3>手工修订</h3>") < detail.index('<h3 id="detailCostTitle">本票成本明细</h3>')
    assert "page-detail.js?v=20260726-invoice-taxonomy" in detail
    assert "发票大类" in page_detail
    assert "特定业务类型" in page_detail
    assert "类型识别状态" in page_detail
    assert "类型识别说明" in page_detail
    assert "common.js?v=20260729-main-macos-sync" in detail
    assert "app.css?v=20260802-release-update-v1" in detail
    assert ".panel__head .detail-file-actions" in css
    assert ".detail-grid" in css
    assert ".detail-grid .stat-card strong { min-width: 0; overflow-wrap: anywhere; word-break: break-word; }" in css
    assert ".detail-side-column" in css
    assert ".detail-cost-panel" in css
    assert ".detail-cost-breakdown" not in css
    assert ".detail-cost-head" not in css
    assert ".detail-cost-body" in css
    assert "max-height: min(72vh, 760px)" in css
    assert ".detail-cost-scroll" in css
    detail_cost_body_rule = re.search(r"\.detail-cost-body\s*\{(?P<body>[^}]*)\}", css, re.S)
    assert detail_cost_body_rule
    assert "align-content: start" in detail_cost_body_rule.group("body")
    assert "grid-auto-rows: max-content" in detail_cost_body_rule.group("body")
    assert "overflow-y: auto" in detail_cost_body_rule.group("body")
    assert "overscroll-behavior-x: contain" in detail_cost_body_rule.group("body")
    assert "overscroll-behavior-y: auto" in detail_cost_body_rule.group("body")
    detail_cost_scroll_rule = re.search(r"\.detail-cost-scroll\s*\{(?P<body>[^}]*)\}", css, re.S)
    assert detail_cost_scroll_rule
    assert "overflow: auto" in detail_cost_scroll_rule.group("body")
    assert "overscroll-behavior-y: auto" in detail_cost_scroll_rule.group("body")
    assert ".detail-cost-table" in css
    assert "min-width: 860px" in css
    assert "font-variant-numeric: tabular-nums" in css
    assert ".detail-main-column .kv-grid dd" in css
    assert "overflow-wrap: anywhere" in css
    assert "openLocationBtn" in page_detail
    assert "/open-location" in page_detail
    assert "已请求打开文件所在位置" in page_detail
    assert "renderCostBreakdown" in page_detail
    assert "cost_breakdown" in page_detail
    assert "consistencyCard" not in page_detail
    assert "payload.consistency" not in page_detail
    assert "detailNumber(value, decimals = 2)" in page_detail
    assert "算术均价(除税)" in page_detail
    assert "算术均价(含税)" in page_detail
    assert "加权均价(除税)" in page_detail
    assert "加权均价(含税)" in page_detail
    assert "暂无本票成本明细" in page_detail
    assert "detail-cost-table" in page_detail
    assert "detailJson" not in detail
    assert "escapeHtml" in common


def test_business_dossier_failure_is_visible_without_blocking_invoice_refresh() -> None:
    index = (ROOT / "web" / "templates" / "index.html").read_text(encoding="utf-8")
    js = (ROOT / "web" / "static" / "js" / "page-index.js").read_text(encoding="utf-8")

    assert 'id="businessDossierSummary" role="status" aria-live="polite"' in index
    failure_renderer = re.search(
        r"function renderBusinessDossierFailure\(error\) \{(?P<body>.*?)\n\}",
        js,
        re.S,
    )
    assert failure_renderer is not None
    failure_body = failure_renderer.group("body")
    assert "refs.businessDossierPanel.hidden = false;" in failure_body
    assert "业务资料夹读取失败：${message}。发票列表仍可使用。" in failure_body
    assert "资料夹快速入口暂不可用，请刷新后重试。" in failure_body

    safe_loader = re.search(
        r"async function loadBusinessDossierSafely\(generation\) \{(?P<body>.*?)\n\}",
        js,
        re.S,
    )
    assert safe_loader is not None
    safe_loader_body = safe_loader.group("body")
    assert "return await loadBusinessDossier(generation);" in safe_loader_body
    assert "console.warn(\"Business dossier refresh failed\", error);" in safe_loader_body
    assert "if (!isCurrentRefresh(generation)) return { status: \"stale\" };" in safe_loader_body
    assert "renderBusinessDossierFailure(error);" in safe_loader_body
    assert "const BUSINESS_DOSSIER_TIMEOUT_MS = 2500;" in js
    assert "const controller = new AbortController();" in js
    assert "window.setTimeout(() => controller.abort(), BUSINESS_DOSSIER_TIMEOUT_MS);" in js
    assert "const [settingsResult, invoicesResult] = await Promise.allSettled([" in js
    assert "const dossierResult = await loadBusinessDossierSafely(generation);" in js
    assert "await Promise.all([loadSettings(), loadInvoices(), loadBusinessDossierSafely()]);" not in js
    assert "await Promise.all([loadSettings(), loadInvoices(), loadBusinessDossier()]);" not in js


def test_selected_invoice_summary_frontend_contract() -> None:
    index = (ROOT / "web" / "templates" / "index.html").read_text(encoding="utf-8")
    js = (ROOT / "web" / "static" / "js" / "page-index.js").read_text(encoding="utf-8")
    css = (ROOT / "web" / "static" / "css" / "app.css").read_text(encoding="utf-8")

    assert 'id="selectedInvoiceSummaryBtn"' in index
    assert 'class="selection-summary__button"' in index
    assert 'aria-haspopup="dialog"' in index
    assert 'aria-controls="selectedInvoiceSummaryModal"' in index
    assert 'aria-expanded="false"' in index
    assert "disabled></button>" in index
    summary_button = re.search(
        r'<button[^>]*id="selectedInvoiceSummaryBtn"[^>]*>(?P<label>.*?)</button>',
        index,
        re.S,
    )
    assert summary_button is not None
    assert summary_button.group("label").strip() == ""
    assert "查看合计" not in index
    assert 'id="selectedInvoiceSummaryModal" class="modal-backdrop selection-summary-modal" hidden' in index
    assert 'role="dialog"' in index
    assert 'aria-modal="true"' in index
    assert 'aria-labelledby="selectedInvoiceSummaryTitle"' in index
    assert 'aria-describedby="selectedInvoiceSummarySubtitle"' in index
    assert "合计发票金额（除税）" in index
    assert "合计税金" in index
    assert "合计发票金额（价税合计）" in index
    assert "合计发票明细" in index
    assert "selectedInvoiceSummaryLoading" in index
    assert "selectedInvoiceSummaryError" in index
    assert "selectedInvoiceSummaryRetryBtn" in index
    assert 'role="region" aria-label="合计发票明细规格列表"' in index

    assert '"/api/v1/invoices/selection-summary"' in js
    assert "invoiceSelectionRecord" in js
    assert "invoiceFamilyKey" in js
    assert "invoiceFilenameNumber" in js
    assert "invoiceSourceIdentity" in js
    assert 'if (invoiceNumber) return `number:${invoiceNumber}`;' in js
    assert 'if (filenameNumber) return `number:${filenameNumber}`;' in js
    assert "source_identity" in js
    assert "bySource.get(selected.source_identity)" in js
    assert "selectedSummaryRequestItems" in js
    assert "invoice_key: item.invoice_key" in js
    assert "source_path: item.source_path" in js
    assert "selectionProjectHtml" in js
    assert "selection-tax-rate-badge" in js
    assert "税率未识别" in js
    assert '<table class="data-table detail-cost-table">' in js
    assert "算术均价(除税)" in js
    assert "算术均价(含税)" in js
    assert "加权均价(除税)" in js
    assert "加权均价(含税)" in js
    assert "本次勾选发票暂无可用成本明细" in js
    assert "同票金额冲突" in js
    assert "重复格式记录" in js
    assert "openSelectedInvoiceSummary" in js
    assert "closeSelectedInvoiceSummary" in js
    assert "event.target === refs.selectionSummaryModal" in js
    assert 'event.key === "Escape"' in js
    assert 'event.key !== "Tab"' in js
    assert "selectionSummaryFocusableElements" in js
    assert "selectionSummaryReturnFocus" in js
    assert "returnFocus.focus()" in js
    assert "selectionSummaryRetryBtn?.addEventListener" in js
    assert 'setSelectionSummaryState("loading")' in js
    assert 'setSelectionSummaryState("error")' in js
    assert 'setSelectionSummaryState("success")' in js

    summary_button_states = re.search(
        r"\.selection-summary__button,\s*\.selection-summary__button:hover:not\(:disabled\),\s*\.selection-summary__button:active:not\(:disabled\)\s*\{(?P<body>[^}]*)\}",
        css,
        re.S,
    )
    assert summary_button_states is not None
    state_body = summary_button_states.group("body")
    assert "position: absolute !important" in state_body
    assert "z-index: 2 !important" in state_body
    assert "border: 0 !important" in state_body
    assert "background: transparent !important" in state_body
    assert "box-shadow: none !important" in state_body
    assert "transform: none !important" in state_body
    disabled_button = re.search(
        r"\.selection-summary__button:disabled\s*\{(?P<body>[^}]*)\}",
        css,
        re.S,
    )
    assert disabled_button is not None
    assert "cursor: default" in disabled_button.group("body")
    settings_phone_media = re.search(
        r"@media\s*\(max-width:\s*640px\)\s*\{\s*"
        r"\.settings-health-item\s*\{\s*grid-template-columns:\s*1fr;\s*\}\s*\}",
        css,
        re.S,
    )
    assert settings_phone_media is not None
    for selector_pattern in (
        r"^\s*\.bookkeeping-shell\s*\{",
        r"/\* Selected invoice summary \*/\s*\.selection-summary\s*\{",
        r"^\s*\.selection-summary__button,\s*$",
        r"^\s*\.selection-summary-dialog\s*\{",
    ):
        _assert_css_selector_is_top_level(css, selector_pattern)
    summary_dialog = re.search(
        r"\.selection-summary-dialog\s*\{(?P<body>[^}]*)\}",
        css,
        re.S,
    )
    assert summary_dialog is not None
    assert "display: grid" in summary_dialog.group("body")
    assert "width: min(1160px, 100%)" in summary_dialog.group("body")
    selection_totals = re.search(
        r"\.selection-summary-totals\s*\{(?P<body>[^}]*)\}",
        css,
        re.S,
    )
    assert selection_totals is not None
    assert "grid-template-columns: repeat(3, minmax(0, 1fr))" in selection_totals.group("body")
    assert ".selection-summary__button:focus-visible" in css
    assert "outline-offset: -4px" in css
    assert ".selection-summary-dialog__scroll" in css
    assert "overscroll-behavior-y: auto" in css
    assert ".selection-summary-totals" in css
    assert "position: sticky" in css
    assert ".selection-tax-rate-badge--missing" in css
    assert "@media (max-width: 420px)" in css
    reduced_motion = re.search(
        r"@media \(prefers-reduced-motion: reduce\)\s*\{\s*\.selection-summary-spinner\s*\{(?P<body>[^}]*)\}",
        css,
        re.S,
    )
    assert reduced_motion is not None
    assert "animation: none" in reduced_motion.group("body")

    for template_name in ("backend.html", "base_head.html", "consistency.html", "costs.html", "detail.html", "documents.html", "index.html", "ocr.html", "settings.html", "skins.html"):
        template = (ROOT / "web" / "templates" / template_name).read_text(encoding="utf-8")
        assert "app.css?v=20260802-release-update-v1" in template
    assert "page-index.js?v=20260803-external-monitor-guard" in index


def test_consistency_page_is_user_facing_not_raw_json() -> None:
    html = (ROOT / "web" / "templates" / "consistency.html").read_text(encoding="utf-8")
    js = (ROOT / "web" / "static" / "js" / "page-consistency.js").read_text(encoding="utf-8")

    assert "仅看存在差异" in html
    assert "consistencyStats" in html
    assert "consistencyGroups" in html
    assert "json-panel" not in html
    assert "page-consistency.js?v=20260726-invoice-taxonomy" in html
    assert "/api/v1/consistency-report" in js
    assert "mismatch_fields" in js
    assert "only_mismatch=true" in js
    assert "发票大类" in js
    assert "特定业务类型" in js
    assert "classification_status" in js
    assert "classification_issue" in js
    assert "const issueHtml = issue" in js


def test_documents_page_contract() -> None:
    html = (ROOT / "web" / "templates" / "documents.html").read_text(encoding="utf-8")
    js = (ROOT / "web" / "static" / "js" / "page-documents.js").read_text(encoding="utf-8")
    css = (ROOT / "web" / "static" / "css" / "app.css").read_text(encoding="utf-8")
    skin_css = (ROOT / "web" / "static" / "skins" / "animal-island" / "skin.css").read_text(encoding="utf-8")
    api_app = (ROOT / "src" / "invoice_hub" / "api" / "app.py").read_text(encoding="utf-8")

    assert 'body data-page="documents"' in html
    assert 'aria-current="page" href="/documents"' in html
    assert "入库单" in html
    assert "出库单" in html
    assert 'role="tablist" aria-label="单据类型"' in html
    assert 'data-document-view="inbound"' in html
    assert 'data-document-view="outbound" hidden' in html
    assert "outboundDirDraft" in html
    assert "待保存目录" in js
    assert "inboundInvoiceSelect" in html
    assert "outboundInvoiceSelect" in html
    assert "inboundPreviewTable" in html
    assert "outboundPreviewTable" in html
    assert '<table id="inboundPreviewTable" class="document-table document-table--inbound"></table>' in html
    assert '<table id="outboundPreviewTable" class="document-table document-table--outbound"></table>' in html
    assert "保存默认信息" in html
    assert "导出入库单" in html
    assert "打开入库单" in html
    assert "openInboundLocationBtn" in html
    assert "打开文件所在位置" in html
    assert "导出出库单" in html
    assert "打开出库单" in html
    assert "openOutboundLocationBtn" in html
    assert "收货单位" in html
    assert "项目负责人" in html
    assert html.count('class="panel document-defaults-panel"') == 2
    assert "documentExportDialog" in html
    assert 'role="dialog"' in html
    assert "documentDialogYesBtn" in html
    assert "documentDialogNoBtn" in html
    assert "documentDialogOpenBtn" in html
    assert ">是</button>" in html
    assert ">否</button>" in html
    assert ">打开该文件</button>" in html
    assert "app.css?v=20260802-release-update-v1" in html
    assert "common.js?v=20260729-main-macos-sync" in html
    assert "page-documents.js?v=20260729-main-macos-sync" in html
    assert "loadDocumentPreferences" in js
    assert "document_export_existing_strategy" in js
    assert "settings.preferences_updated" in js
    assert "app.connectEvents(refs.eventState" in js
    assert "{ refreshOnFirstOpen: false }" in js
    assert "nativePickOutboundDir" in js
    assert "window.invoiceHubMac.pickOutboundDir" in js
    assert "/api/v1/documents/validate-outbound-dir" in js
    assert "pendingOutboundValidation" in js
    assert "renderOutboundDirValidation" in js
    assert "const validation = state.pendingOutboundDir" in js
    assert "? state.pendingOutboundValidation" in js
    assert ": state.payload?.outbound_dir_validation" in js
    assert "validateOutboundDirDraftDebounced" in js

    assert '@app.get("/documents", response_class=HTMLResponse)' in api_app
    for endpoint in (
        "/api/v1/documents/state",
        "/api/v1/documents/validate-outbound-dir",
        "/api/v1/documents/pick-outbound-dir",
        "/api/v1/documents/outbound-dir",
        "/api/v1/documents/recent-outbound-dirs/remove",
        "/api/v1/documents/defaults",
        "/api/v1/documents/${kind}/preview",
        "/api/v1/documents/${kind}/export-status",
        "/api/v1/documents/${kind}/export",
        "/api/v1/documents/${kind}/${action}",
        "/api/v1/documents/inbound/open-location",
        "/api/v1/documents/outbound/open-location",
    ):
        assert endpoint in js or endpoint in api_app
    assert "app.setBusy" in js
    assert "refreshExportStatus" in js
    assert "showExportDialog" in js
    assert "该单据已导出在${status.folder_path || \"\"}路径的文件夹内，是否继续导出副本" in js
    assert "resolveDialog(\"copy\")" in js
    assert "resolveDialog(\"cancel\")" in js
    assert "resolveDialog(\"open\")" in js
    assert "文件被占用，请关闭后再操作" in js
    assert "已取消导出" in js
    assert 'openDocument("inbound", true)' in js
    assert 'openDocument("outbound", true)' in js
    assert "renderInboundPreview" in js
    assert "renderOutboundPreview" in js
    assert "合计（大写）" in js
    assert "合计(大写)" in js
    assert "合计（小写）" in js
    assert "document-total-amount" in js
    assert "preview.total_with_tax_upper" in js
    assert "renderOutboundHistory" in js
    assert "saveDefaults" in js
    assert "exportDocument" in js
    assert "openDocument" in js
    assert "state.lastExport" in js

    assert ".document-preview-scroll" in css
    assert ".document-table" in css
    assert ".document-total-amount" in css
    assert "text-align: left" in css
    assert ".document-view[hidden]" in css
    assert ".document-table--inbound" in css
    assert ".document-table--outbound" in css
    assert "overflow-x: auto" in css
    assert "container: document-defaults / inline-size;" in css
    assert "@container document-defaults (max-width: 720px)" in css
    assert "@container document-defaults (max-width: 360px)" in css
    assert ".document-defaults-panel .document-form .field" in css
    document_scroll_rule = re.search(r'body\[data-page="documents"\]\s+\.document-preview-scroll\s*\{(?P<body>[^}]*)\}', css, re.S)
    assert document_scroll_rule
    assert "max-height: none" in document_scroll_rule.group("body")
    assert "overflow-x: auto" in document_scroll_rule.group("body")
    assert "overflow-y: hidden" in document_scroll_rule.group("body")
    assert "scrollbar-gutter: auto" in document_scroll_rule.group("body")
    assert "table-layout: fixed" in css
    assert ".modal-backdrop" in css
    assert "backdrop-filter: blur(4px)" in css
    assert ".modal-card" in css
    assert ".modal-path" in css
    assert ".modal-actions" in css

    assert ".modal-backdrop" in skin_css
    assert ".modal-card" in skin_css
    assert ".modal-path" in skin_css
    assert ".modal-actions" in skin_css
    assert "url(\"textures/paper-grain.png\")" in skin_css


def test_bookkeeping_page_static_contract() -> None:
    html = (ROOT / "web" / "templates" / "bookkeeping.html").read_text(encoding="utf-8")
    base_head = (ROOT / "web" / "templates" / "base_head.html").read_text(encoding="utf-8")
    js = (ROOT / "web" / "static" / "js" / "page-bookkeeping.js").read_text(encoding="utf-8")
    css = (ROOT / "web" / "static" / "css" / "app.css").read_text(encoding="utf-8")
    api_app = (ROOT / "src" / "invoice_hub" / "api" / "app.py").read_text(encoding="utf-8")
    backend = (ROOT / "web" / "templates" / "backend.html").read_text(encoding="utf-8")

    assert 'body data-page="bookkeeping"' in html
    assert "{{BASE_HEAD}}" in html
    assert "{{BOOTSTRAP_JSON}}" in html
    assert "app.css?v=20260802-release-update-v1" in base_head
    assert "page-bookkeeping.js?v=20260711-w9-ledger-review-v3" in html
    assert 'id="voucherBlockers"' in html
    assert "item.can_approve === true" in js
    assert "expected_store_revision" in js
    assert "proposal_revision_hash" in js
    assert "error?.payload?.error?.blockers" in js
    assert 'aria-current="page" href="/bookkeeping"' in html
    assert '<table id="voucherTable" class="data-table bookkeeping-table">' in html
    assert '<table id="voucherLinesTable" class="data-table bookkeeping-lines-table">' in html
    assert '<table id="voucherAuditTable" class="data-table bookkeeping-audit-table">' in html
    assert "生成凭证草稿" in html
    assert "导出捷锐导入文件" in html
    assert "复制凭证表" in html
    assert "review_tier" in html
    assert "驳回原因" in js
    assert "审核详细信息" in html
    assert "balance_ok" in html
    assert "来源行" in html
    assert "审核记录" in html
    for element_id in (
        "bookkeepingReviewTab",
        "bookkeepingMappingTab",
        "bookkeepingSetupTab",
        "bookkeepingReviewView",
        "bookkeepingMappingView",
        "bookkeepingSetupView",
        "voucherDecisionForm",
        "recomputeVoucherBtn",
        "taxEvidenceRowsBody",
        "paymentEvidenceRowsBody",
        "decisionSourceLinesBody",
        "decisionReceivingRowsBody",
        "mappingRuleForm",
        "mappingAuxFields",
        "ledgerProfileForm",
        "voucherMigrationStatus",
        "previewVoucherMigrationBtn",
        "applyVoucherMigrationBtn",
        "mappingMigrationStatus",
        "previewMappingMigrationBtn",
        "applyMappingMigrationBtn",
    ):
        assert f'id="{element_id}"' in html
    assert "凭证人审" in html
    assert "映射规则" in html
    assert "账套设置" in html
    assert 'data-bookkeeping-view="mapping"' in html
    assert 'data-bookkeeping-view="setup"' in html
    assert "inventory_receipt" in js
    assert "acceptance_record" in js
    assert 'data-receiving-coverage' in js
    assert 'data-add-allocation' in js
    assert 'data-remove-allocation' in js
    assert 'data-project-id' in js
    assert 'data-project-name' in js
    assert 'snapshot.line_decision_templates' in js
    assert "科目模板" in js
    assert 'data-tax-evidence-row' in js
    assert 'data-payment-evidence-row' in js
    assert 'data-remove-evidence' in js
    assert '@app.get("/bookkeeping", response_class=HTMLResponse)' in api_app
    assert '"bookkeeping.html"' in api_app
    assert "active_skin_link(request)" in api_app
    assert "base_head.html" in api_app

    for endpoint in (
        "/api/v1/bookkeeping/state",
        "/api/v1/bookkeeping/setup",
        "/api/v1/bookkeeping/profile",
        "/api/v1/bookkeeping/accounts?limit=500",
        "/api/v1/bookkeeping/aux-values?limit=500",
        "/api/v1/bookkeeping/vouchers",
        "/api/v1/bookkeeping/generate",
        "/api/v1/bookkeeping/vouchers/${encodeURIComponent(item.voucher_key)}/decision",
        "/api/v1/bookkeeping/mapping-rules",
        "/api/v1/bookkeeping/mapping-rules/preview",
        "/api/v1/bookkeeping/mapping-migration/preview",
        "/api/v1/bookkeeping/mapping-migration/apply",
        "/api/v1/bookkeeping/migration/preview",
        "/api/v1/bookkeeping/migration/apply",
        "/api/v1/bookkeeping/recompute",
        "/api/v1/bookkeeping/export-import-file",
        "/api/v1/bookkeeping/export-status",
        "/api/v1/bookkeeping/vouchers/${encodeURIComponent(voucherKey)}/review",
        "/api/v1/events/stream",
    ):
        assert endpoint in js
    for endpoint in (
        "/api/v1/bookkeeping/import-batches/{batch_id}/dry-run",
        "/api/v1/bookkeeping/import-batches/{batch_id}/begin",
        "/api/v1/bookkeeping/import-batches/{batch_id}/finalize",
    ):
        assert endpoint in api_app
    assert "new EventSource" in js
    assert "source.onopen" in js
    assert "source.onerror" in js
    assert "openedOnce || sawError" in js
    assert "Promise.all([loadSetup(), loadState(), loadAccounts(), loadAuxValues()])" in js
    assert "app.tableToTsv" in js
    assert "驳回凭证必须填写原因" in js
    assert "data-review-action=\"approve\"" in js
    assert "data-review-action=\"reject\"" in js
    assert "state.decisionDirty && voucherKey === state.selectedKey" in js
    assert "当前凭证决定尚未保存" in js
    assert "dirtySelected || item?.can_approve !== true" in js
    assert "state.decisionBaseline?.storeRevision" in js
    assert "state.decisionBaseline?.proposalRevisionHash" in js
    assert "profileBaselineFrom" in js
    assert "profileBaselineChanged" in js
    assert "state.profileConflict = true" in js
    assert "state.profileBaseline?.profileRevision" in js
    assert "state.profileBaseline?.accountSha256" in js
    assert "state.profileBaseline?.auxSha256" in js
    assert "busy || state.profileConflict" in js
    assert "state.decisionDirty || !selected || !recomputableStatuses.has(selected.status)" in js
    assert "state.voucherMigrationPreview?.ok !== true" in js
    assert "state.mappingMigrationPreview?.ok !== true" in js
    assert "state.setup?.ready_for_state_migration !== true" in js
    assert 'window.confirm("确认按当前 SHA 执行凭证状态迁移？")' in js
    assert 'window.confirm("确认按当前 SHA 和账套档案执行科目映射迁移？")' in js
    assert "expected_profile_sha256" in js
    assert "expected_rules_version" in js
    assert "expected_account_table_sha256" in js
    assert "expected_aux_catalog_sha256" in js
    assert "!state.decisionDirty && !state.profileDirty" in js
    assert "mappingAuxValuesFromForm" in js
    assert "mappingRequiredAuxDimensions" in js
    assert "renderMappingAuxFields(rule.aux_dimensions || {})" in js
    assert "aux_dimensions: mappingAuxValuesFromForm()" in js
    assert "review-tier-badge--${safe}" in js
    assert '"auto", "ai_suggested", "forced_manual", "manual_confirmed"' in js
    assert '<option value="manual_confirmed">manual_confirmed</option>' in html

    assert ".bookkeeping-table" in css
    assert ".page-title { min-width: 0; max-width: 100%; }" in css
    assert ".bookkeeping-row-actions" in css
    assert ".review-tier-badge--auto" in css
    assert ".review-tier-badge--ai_suggested" in css
    assert ".review-tier-badge--forced_manual" in css
    assert ".review-tier-badge--manual_confirmed" in css
    assert ".bookkeeping-detail-grid" in css
    assert "grid-template-columns: minmax(0, 0.8fr) minmax(0, 1.2fr);" in css
    assert "grid-template-columns: minmax(0, 1fr);" in css
    assert "overflow-wrap: anywhere;" in css
    assert ".bookkeeping-audit-table" in css
    assert ".bookkeeping-mapping-aux-fields" in css
    assert ".bookkeeping-icon-btn" in css
    assert ".bookkeeping-inline-actions" in css
    assert ".bookkeeping-decision-actions" in css
    assert ".bookkeeping-migration-row" in css
    assert '.bookkeeping-editor-table tr[data-line-template="true"]' in css
    assert 'href="/bookkeeping"' not in backend


def test_settings_nav_entry_is_rightmost_on_normal_pages() -> None:
    normal_pages = ["index.html", "costs.html", "ocr.html", "consistency.html", "detail.html", "documents.html", "skins.html", "settings.html", "bookkeeping.html"]
    expected_hrefs = ["/", "/costs", "/documents", "/bookkeeping", "/ocr", "/consistency", "/settings"]
    for name in normal_pages:
        html = (ROOT / "web" / "templates" / name).read_text(encoding="utf-8")
        nav = re.search(r'<nav aria-label="主导航">(?P<body>.*?)</nav>', html, re.S)
        assert nav is not None, name
        nav_body = nav.group("body")
        hrefs = re.findall(r'href="([^"]+)"', nav_body)
        assert hrefs == expected_hrefs, name
        assert ">设置</a>" in nav_body
        assert 'href="/skins"' not in nav_body
        assert 'href="/backend"' not in nav_body

    backend = (ROOT / "web" / "templates" / "backend.html").read_text(encoding="utf-8")
    assert 'href="/skins"' not in backend
    assert 'href="/documents"' not in backend
    assert 'href="/bookkeeping"' not in backend


def test_settings_page_contract() -> None:
    html = (ROOT / "web" / "templates" / "settings.html").read_text(encoding="utf-8")
    js = (ROOT / "web" / "static" / "js" / "page-settings.js").read_text(encoding="utf-8")
    css = (ROOT / "web" / "static" / "css" / "app.css").read_text(encoding="utf-8")
    settings_actions_css = (ROOT / "web" / "static" / "css" / "settings-actions.css").read_text(encoding="utf-8")
    api_app = (ROOT / "src" / "invoice_hub" / "api" / "app.py").read_text(encoding="utf-8")
    app_state = (ROOT / "src" / "invoice_hub" / "services" / "app_state.py").read_text(encoding="utf-8")
    bridge = (ROOT / "src" / "invoice_hub" / "services" / "monitor_bridge.py").read_text(encoding="utf-8")

    assert 'body data-page="settings"' in html
    assert 'aria-current="page" href="/settings"' in html
    assert "settingsTabOverview" in html
    assert "settingsTabPaths" in html
    assert "settingsTabRuntime" in html
    assert "settingsTabDocuments" in html
    assert "settingsTabAppearance" in html
    assert "settingsTabPreferences" in html
    assert "settingsTabDiagnostics" in html
    assert 'role="tablist"' in html
    assert 'data-settings-section="overview"' in html
    assert 'data-settings-panel="diagnostics"' in html
    assert 'data-settings-section="preferences"' in html
    assert 'data-settings-panel="preferences"' in html
    assert "settingsPanelPaths" in html
    assert "settings-action-row" in html
    assert 'class="settings-edit-card settings-defaults-card"' in html
    assert 'href="/skins"' in html
    assert 'href="/backend"' in html
    assert "app.css?v=20260802-release-update-v1" in html
    assert "settings-actions.css?v=20260720-shutdown-monitor-choice" in html
    assert "common.js?v=20260729-main-macos-sync" in html
    assert "page-settings.js?v=20260803-external-monitor-guard" in html
    assert "/api/v1/settings/rename-invoice-files" in api_app
    assert '@app.get("/settings", response_class=HTMLResponse)' in api_app
    assert 'render_page(request, "settings.html"' in api_app

    for endpoint in (
        "/api/v1/health",
        "/api/v1/settings",
        "/api/v1/bridge/status",
        "/api/v1/cost-analysis",
        "/api/v1/documents/state",
        "/api/v1/skins",
        "/api/v1/ocr/settings",
        "/api/v1/ocr/service-status",
        "/api/v1/preferences",
        "/api/v1/diagnostics/summary",
        "/api/v1/diagnostics/config-health",
        "/api/v1/diagnostics/support-package",
        "/api/v1/server/shutdown",
    ):
        assert endpoint in js
    assert "Promise.allSettled" in js
    assert "app.connectEvents(settingsRefs.eventState" in js
    assert "refreshOnFirstOpen: false" in js
    for html_token in (
        "settingsWatchDirInput",
        "settingsPickWatchDirBtn",
        "settingsValidateWatchDirBtn",
        "settingsSaveWatchDirBtn",
        "settingsRenameInvoiceFilesBtn",
        "settingsOperationNotice",
        "settingsOperationNoticeCloseBtn",
        "settingsWatchDirDraft",
        "settingsRecentWatchDirOptions",
        "settingsOutboundDirInput",
        "settingsPickOutboundDirBtn",
        "settingsSaveOutboundDirBtn",
        "settingsOutboundDirDraft",
        "settingsRecentOutboundDirOptions",
        "settingsInboundDefaultsForm",
        "settingsOutboundDefaultsForm",
        "settingsSaveInboundDefaultsBtn",
        "settingsSaveOutboundDefaultsBtn",
        "settingsSkinList",
        "settingsEnableSkinBtn",
        "settingsResetSkinBtn",
        "settingsRefreshRuntimeBtn",
        "settingsStartMonitorBtn",
        "settingsStopMonitorBtn",
        "settingsRebuildBtn",
        "settingsOpenMonitorLogBtn",
        "settingsOpenRuntimeDirBtn",
        "settingsRuntimeActionStatus",
        "settingsShutdownBtn",
        "settingsShutdownBehaviorCurrent",
        "settingsShutdownActionStatus",
        "settingsShutdownDialog",
        "settingsShutdownDialogCard",
        "settingsShutdownKeepMonitor",
        "settingsShutdownStopMonitor",
        "settingsShutdownRemember",
        "settingsShutdownCancelBtn",
        "settingsShutdownConfirmBtn",
        "settingsShutdownProgress",
        "settingsRuntimeLastTrigger",
        "settingsPreferencesList",
        "settingsOcrCandidateDirInput",
        "settingsPickOcrCandidateDirBtn",
        "settingsUseWatchDirForOcrBtn",
        "settingsSaveOcrCandidateDirBtn",
        "settingsOcrCandidateDirStatus",
        "settingsAdvancedDiagnostics",
        "settingsDiagnosticSummaryText",
        "settingsCopyDiagnosticSummaryBtn",
        "settingsRunConfigHealthBtn",
        "settingsExportSupportPackageBtn",
        "settingsDiagnosticHealthList",
        "settingsSupportPackagePath",
        "settingsDiagnosticActionStatus",
    ):
        assert html_token in html
    for js_token in (
        "watchDirDirty",
        "outboundDirDirty",
        "defaultsDirty",
        "markWatchDirDirty",
        "markOutboundDirDirty",
        "renderWatchDirEditor",
        "renderOutboundEditor",
        "renderDefaultsEditor",
        "待保存目录：",
        "if (!state.watchDirDirty)",
        "if (!state.outboundDirDirty)",
        "if (!state.defaultsDirty.inbound)",
        "if (!state.defaultsDirty.outbound)",
        "/api/v1/settings/pick-watch-dir",
        "window.invoiceHubMac.pickWatchDir",
        "/api/v1/settings/validate-watch-dir",
        "/api/v1/settings/recent-watch-dirs/remove",
        "/api/v1/settings/rename-invoice-files",
        "renameInvoiceFiles",
        "showSettingsOperationNotice",
        "prepareSettingsOperationNotice",
        "document.body.append(root)",
        "--operation-notice-top",
        "actionNotices",
        "/api/v1/documents/pick-outbound-dir",
        "window.invoiceHubMac.pickOutboundDir",
        "/api/v1/documents/outbound-dir",
        "/api/v1/documents/recent-outbound-dirs/remove",
        "/api/v1/documents/defaults",
        "/api/v1/skins/reset",
        "/api/v1/skins/${encodeURIComponent(id)}/enable",
        "method: \"POST\"",
        "method: \"PUT\"",
        "app.setBusy",
        "app.applySkinPayload",
        "loadPhase3Runtime",
        "refreshRuntimeStatus",
        "postRuntimeAction",
        "last_trigger",
        "observer_active",
        "启动中",
        "周期兜底",
        "/api/v1/bridge/start",
        "/api/v1/bridge/stop",
        "/api/v1/bridge/rebuild",
        "/api/v1/bridge/open-log",
        "/api/v1/bridge/open-runtime-dir",
        "loadPhase4Preferences",
        "savePreferencePatch",
        "updatesOcrCandidate",
        "data-settings-cost-row-limit",
        "data-settings-long-path-display",
        "data-settings-document-strategy",
        "data-settings-shutdown-behavior",
        "system_shutdown_behavior",
        "normalizeSettingsShutdownBehavior",
        "publishSettingsShutdownBehavior",
        "settingsBackendIsExternallyManaged",
        'bridge.backendOwnership === "externalCompatible"',
        "bridge.canManageBackend !== true",
        "externallyManaged || busy || running",
        "externallyManaged || busy || !running",
        "不能改变其持续监控",
        "由外部服务管理",
        "decisionFocusableElements",
        "executeShutdown",
        "settings:shutdown-behavior",
        "shutdown_behavior: normalized",
        "remember: Boolean(remember)",
        "payload?.ok === true",
        "payload.scheduled === true || payload.idempotent === true",
        "payload.shutdown_behavior === normalized",
        "后端未确认关闭请求，请重试。",
        "/api/v1/ocr/pick-folder",
        "window.invoiceHubMac.pickOcrCandidateDir",
        "loadPhase5Diagnostics",
        "copyDiagnosticSummary",
        "runConfigHealth",
        "exportSupportPackage",
        "/api/v1/diagnostics/summary",
        "/api/v1/diagnostics/config-health",
        "/api/v1/diagnostics/support-package",
        "contains_source_invoices",
    ):
        assert js_token in js
    assert "/api/v1/skins/import" not in js
    assert 'role="dialog"' in html
    assert 'aria-modal="true"' in html
    assert html.index("settingsShutdownStopMonitor") < html.index("settingsShutdownRemember") < html.index("settingsShutdownConfirmBtn")
    assert ".settings-layout" in css
    assert ".settings-sidebar" in css
    assert ".settings-category-list" in css
    settings_edit_card = re.search(
        r"\.settings-edit-card \{(?P<body>.*?)\}",
        css,
        re.S,
    )
    assert settings_edit_card
    assert "background: var(--surface);" in settings_edit_card.group("body")
    assert "var(--ink)" not in css
    assert '.settings-tab[aria-selected="true"]' in css
    assert ".settings-summary-grid" in css
    assert ".settings-path" in css
    assert ".settings-edit-card" in css
    assert ".settings-defaults-grid" in css
    assert "container: settings-defaults / inline-size;" in css
    assert "@container settings-defaults (max-width: 900px)" in css
    assert "@container document-defaults (max-width: 720px)" in css
    assert ".settings-defaults-block .document-form .field" in css
    assert ".settings-skin-list" in css
    assert ".settings-runtime-snapshot" in css
    assert ".settings-action-status" in css
    assert ".settings-invoice-rename" in settings_actions_css
    assert "#settingsRenameInvoiceFilesBtn" in settings_actions_css
    assert "background: #f4c654;" in settings_actions_css
    assert "color: #3d2a00 !important;" in settings_actions_css
    assert ".operation-notice" in settings_actions_css
    assert "--operation-notice-top" in settings_actions_css
    assert "button.operation-notice__close" in settings_actions_css
    assert "min-height: 20px;" in settings_actions_css
    assert ".settings-shutdown-card" in settings_actions_css
    assert ".settings-shutdown-dialog__card" in settings_actions_css
    assert ".settings-shutdown-choice" in settings_actions_css
    assert ".settings-shutdown-remember" in settings_actions_css
    assert ".settings-shutdown-progress" in settings_actions_css
    assert "min-height: 44px;" in settings_actions_css
    assert "max-height: calc(100dvh - 32px);" in settings_actions_css
    assert ".settings-segmented" in css
    assert ".settings-diagnostic-summary" in css
    assert ".settings-health-list" in css
    assert "settings-health-item--danger" in css
    assert 'html[data-long-path-display="wrap"]' in css
    assert 'body[data-page="settings"] .watch-dir-history' in css
    assert "grid-template-columns: 240px minmax(0, 1fr)" in css
    assert "overflow-x: auto" in css
    assert "overscroll-behavior-x: contain" in css
    assert "summary_xlsx_path" in app_state
    assert "output_detail_csv_exists" in app_state
    assert "diagnostics" in app_state
    assert "db_path" in app_state
    assert "lock_path" in bridge
    assert "last_trigger" in bridge
    assert "ready_marker" in bridge
    assert "observer_active" in bridge
    assert "open_monitor_log" in app_state
    assert "open_runtime_dir" in app_state
    assert "DEFAULT_PREFERENCES" in app_state
    assert "save_preferences" in app_state
    assert "diagnostic_summary" in app_state
    assert "PREFERENCE_SYSTEM_SHUTDOWN_BEHAVIORS" in app_state
    assert "request_server_shutdown" in app_state
    assert "finalize_server_shutdown" in app_state
    assert "config_health" in app_state
    assert "export_support_package" in app_state
    assert "contains_source_invoices" in app_state
    assert "preferences_path" in app_state
    assert "rename_invoice_files" in app_state
    assert "INVOICE_RENAME_FORMAT" in app_state
    assert "MANUAL_FILE_RENAME" in app_state
    assert "/api/v1/bridge/open-log" in api_app
    assert "/api/v1/bridge/open-runtime-dir" in api_app
    assert "/api/v1/preferences" in api_app
    assert "/api/v1/diagnostics/summary" in api_app
    assert "/api/v1/diagnostics/config-health" in api_app
    assert "/api/v1/diagnostics/support-package" in api_app
    assert "/api/v1/server/shutdown" in api_app
    assert "shutdown_scheduler" in api_app


def test_skin_page_contract_and_common_skin_loader() -> None:
    html = (ROOT / "web" / "templates" / "skins.html").read_text(encoding="utf-8")
    js = (ROOT / "web" / "static" / "js" / "page-skins.js").read_text(encoding="utf-8")
    common = (ROOT / "web" / "static" / "js" / "common.js").read_text(encoding="utf-8")
    css = (ROOT / "web" / "static" / "css" / "app.css").read_text(encoding="utf-8")
    api_app = (ROOT / "src" / "invoice_hub" / "api" / "app.py").read_text(encoding="utf-8")

    assert 'body data-page="skins"' in html
    assert 'href="/settings"' in html
    assert "skinZipInput" in html
    assert 'type="file"' in html
    assert "accept=\".zip,application/zip,application/x-zip-compressed\"" in html
    assert "importSkinBtn" in html
    assert "enableSkinBtn" in html
    assert "resetSkinBtn" in html
    assert "replaceSkinBtn" in html
    assert "disabled>导入" in html
    assert "disabled>启用" in html
    assert "disabled>重置" in html
    assert "disabled>替换" in html
    assert "skinList" in html
    assert 'role="radiogroup"' in html
    assert "app.css?v=20260802-release-update-v1" in html
    assert "common.js?v=20260729-main-macos-sync" in html
    assert "page-skins.js?v=20260717-settings-macos-sync" in html
    assert '@app.get("/skins", response_class=HTMLResponse)' in api_app
    assert 'render_page(request, "skins.html"' in api_app
    assert "activeSkinStylesheet" in api_app
    assert "no_skin" in api_app
    assert "application/zip" in api_app
    assert "multipart/form-data" not in api_app

    assert "/api/v1/skins" in js
    assert "/api/v1/skins/import" in js
    assert "/api/v1/skins/reset" in js
    assert "/api/v1/skins/enable" not in js
    assert '/api/v1/skins/${encodeURIComponent(id)}/replace' not in js
    assert '"/api/v1/skins/replace"' in js
    assert "fetch(url" in js
    assert '"Content-Type": "application/zip"' in js
    assert '"X-Skin-Filename": encodeURIComponent' in js
    assert "body: file" in js
    assert "app.setBusy" in js
    assert "skinState.busy" in js
    assert "updateSkinControls" in js
    assert "app.applySkinPayload" in js
    assert "app.skinItems" in js
    assert "app.isSkinReadOnly" in js
    assert "内置皮肤不可替换" not in js
    assert "替换并启用" in js
    assert ".skin-list" in css
    assert ".skin-card" in css
    assert ".skin-card.is-active" in css
    assert ".skin-card__preview" in css
    assert ".skin-actions" in css

    assert "skinItems(payload)" in common
    assert "activeSkinId(payload)" in common
    assert "enabled_skin_id" in common
    assert "applySkinPayload(payload)" in common
    assert "loadCurrentSkin" in common
    assert "hydrateServerSkin" in common
    assert "skinBypassRequested" in common
    assert "no_skin" in common
    assert "activeSkinStylesheet" in common
    assert 'window.app.loadCurrentSkin({ fetchIfMissing: false })' in common
    assert "bindNavigationTransitions" in common
    assert "shouldAnimateNavigation" in common
    assert "refreshOnFirstOpen = options.refreshOnFirstOpen !== false" in common
    assert "openedOnce" in common
    assert "sawError" in common
    assert 'document.body?.dataset.page === "backend"' in common
    assert '"/static/skins/animal-island/skin.css"' in common
    assert 'app.skinId(skin) === "ink-pulse"' in js
    assert "source.onopen" in common
    assert "source.onerror" in common


def test_animal_island_skin_is_css_only_and_token_driven() -> None:
    skin_dir = ROOT / "web" / "static" / "skins" / "animal-island"
    skin_css = (skin_dir / "skin.css").read_text(encoding="utf-8")
    manifest = (skin_dir / "skin.json").read_text(encoding="utf-8")

    assert ":root" in skin_css
    assert "--bg:" in skin_css
    assert "--surface:" in skin_css
    assert "--primary:" in skin_css
    assert "--island-mint:" in skin_css
    assert "--island-coral:" in skin_css
    assert "body" in skin_css
    assert ".topbar" in skin_css
    assert ".brand-mark" in skin_css
    assert ".nav-link" in skin_css
    assert ".btn--primary" in skin_css
    assert ".input" in skin_css
    assert ".invoice-checkbox" in skin_css
    assert ".status-pill--success" in skin_css
    assert ".status-pill--partial" in skin_css
    assert ".status-pill--pending" in skin_css
    assert ".service-status::before" in skin_css
    assert ".tab[aria-selected=\"true\"]" in skin_css
    assert ".data-table th" in skin_css
    assert ".cost-view .data-table td" in skin_css
    assert ".data-table tbody tr:nth-child(even) td" in skin_css
    assert ".table-shell" in skin_css
    assert ".table-scroll-x" not in skin_css
    assert "max-height: var(--cost-table-max-height, 62vh)" in skin_css
    assert "overflow-y: auto;" in skin_css
    assert ".cost-table-footer" in skin_css
    assert ".detail-cost-panel" in skin_css
    assert ".detail-cost-breakdown" not in skin_css
    assert ".detail-cost-head" not in skin_css
    assert ".detail-cost-body" in skin_css
    assert ".detail-cost-scroll" in skin_css
    assert ".detail-cost-table" in skin_css
    assert ".detail-cost-number" in skin_css
    assert ".cost-row-limit-control" in skin_css
    assert ".cost-row-limit-btn[aria-pressed=\"true\"]" in skin_css
    assert "scrollbar-gutter: stable;" in skin_css
    assert 'body[data-page="index"] .watch-dir-history__label' in skin_css
    assert "#fff7ea" in skin_css
    assert 'body[data-page="costs"] .markup-rate-percent' in skin_css
    assert ".cost-number" in skin_css
    assert ".reference-quantity-input" in skin_css
    assert ".skin-card" in skin_css
    assert 'body[data-page="settings"] .settings-sidebar' in skin_css
    assert '.settings-tab[aria-selected="true"]' in skin_css
    assert '.settings-segment[aria-pressed="true"]' in skin_css
    assert ".settings-diagnostic-summary" in skin_css
    assert "@font-face" in skin_css
    assert "AnimalIslandNunito" in skin_css
    assert "AnimalIslandMaru" in skin_css
    assert "AnimalIslandNotoSC" in skin_css
    assert "@keyframes island-page-in" in skin_css
    assert "animation: island-page-in 150ms ease-out both;" in skin_css
    assert "overscroll-behavior: contain;" not in skin_css
    assert "overscroll-behavior-y: auto;" in skin_css
    assert "background-attachment: scroll" in skin_css
    assert "@keyframes island-wiggle" in skin_css
    assert "@keyframes island-status-pulse" in skin_css
    assert "@media (prefers-reduced-motion: reduce)" in skin_css
    assert "@import" not in skin_css
    assert "<script" not in skin_css.lower()
    assert "javascript:" not in skin_css.lower()
    assert "data:" not in skin_css.lower()
    assert "http://" not in skin_css.lower()
    assert "https://" not in skin_css.lower()
    assert "nintendo" not in skin_css.lower()
    assert "animal crossing" not in skin_css.lower()
    assert "2.0.8" in manifest

    urls = re.findall(r"url\(\s*['\"]?([^'\")]+)['\"]?\s*\)", skin_css)
    assert urls
    assert all(url.startswith(("fonts/", "textures/")) for url in urls)
    for url in urls:
        assert ".." not in url
        assert "\\" not in url
        assert (skin_dir / url).is_file(), url
    assert (skin_dir / "fonts" / "nunito-ui.woff2").stat().st_size > 0
    assert (skin_dir / "fonts" / "zen-maru-ui-400.woff2").stat().st_size > 0
    assert (skin_dir / "fonts" / "zen-maru-ui-700.woff2").stat().st_size > 0
    assert (skin_dir / "fonts" / "noto-sans-sc-ui.woff2").stat().st_size > 0
    assert (skin_dir / "textures" / "paper-grain.png").stat().st_size > 0
    assert (skin_dir / "textures" / "leaf-confetti.png").stat().st_size > 0


def test_home_invoice_list_centers_content_and_uses_one_status_badge() -> None:
    page_index = (ROOT / "web" / "static" / "js" / "page-index.js").read_text(encoding="utf-8")
    css = (ROOT / "web" / "static" / "css" / "app.css").read_text(encoding="utf-8")

    for helper in ("invoiceTypePill", "classificationIssueStatus", "recognitionStatusMeta", "recognitionStatusPill"):
        assert helper in page_index
    for label in (
        "大类未识别",
        "大类冲突",
        "业务类型未识别",
        "业务类型错误",
        "业务类型冲突",
        "多项类型错误",
        "类型冲突",
        "类型识别错误",
        "识别失败",
        "重复发票",
        "已识别",
    ):
        assert f'label: "{label}"' in page_index
    assert page_index.count("invoice-recognition-status__pill") == 1
    assert 'title="${app.escapeHtml(title)}"' in page_index
    assert 'aria-label="${app.escapeHtml(ariaLabel)}"' in page_index
    assert "classificationIssueHtml" not in page_index
    assert "app.statusPill(item.status" not in page_index
    assert ">大类：" not in page_index
    assert "业务：${app.escapeHtml(businessType)}" in page_index
    assert 'class="status-pill invoice-type-pill invoice-type-pill--${tone}"' in page_index
    assert '<span class="invoice-classification__empty">--</span>' in page_index

    centered_cells = re.search(
        r'body\[data-page="index"\] \.table--invoice-list\.data-table th,\s*'
        r'body\[data-page="index"\] \.table--invoice-list\.data-table td\s*\{(?P<body>[^}]*)\}',
        css,
        re.S,
    )
    assert centered_cells is not None
    assert "text-align: center" in centered_cells.group("body")
    assert "vertical-align: middle" in centered_cells.group("body")

    aligned_badge_rows = re.search(
        r"\.invoice-classification,\s*"
        r"\.invoice-recognition-status\s*\{(?P<body>[^}]*)\}",
        css,
        re.S,
    )
    assert aligned_badge_rows is not None
    assert "display: grid" in aligned_badge_rows.group("body")
    assert "grid-template-rows: 28px minmax(15px, auto)" in aligned_badge_rows.group("body")
    assert "min-height: 62px" in aligned_badge_rows.group("body")

    business_text = re.search(
        r"\.invoice-classification__business\s*\{(?P<body>[^}]*)\}",
        css,
        re.S,
    )
    assert business_text is not None
    assert "font-size: 70%" in business_text.group("body")
    assert "line-height: 1.4" in business_text.group("body")

    assert 'body[data-page="index"] .table--invoice-list .table__amount' in css
    assert 'body[data-page="index"] .table--invoice-list .table__actions' in css
    assert 'body[data-page="index"] .table--invoice-list .sortable-heading' in css
    assert ".invoice-classification" in css
    assert ".invoice-recognition-status" in css
    assert ".invoice-recognition-status__pill" in css
    for token in (
        "#1e3a8a",
        "#dbeafe",
        "#93c5fd",
        "#6b21a8",
        "#f3e8ff",
        "#d8b4fe",
    ):
        assert token in css
    assert "border-color: #93c5fd" in css
    assert "border-color: #d8b4fe" in css
    assert "border: 1px solid #93c5fd" not in css
    assert "border: 1px solid #d8b4fe" not in css

    templates_dir = ROOT / "web" / "templates"
    for template_path in templates_dir.glob("*.html"):
        html = template_path.read_text(encoding="utf-8")
        if "app.css?v=" not in html:
            continue
        assert "app.css?v=20260802-release-update-v1" in html
        assert "app.css?v=20260727-invoice-list-status-layout" not in html
        assert "app.css?v=20260726-invoice-taxonomy" not in html
    index = (templates_dir / "index.html").read_text(encoding="utf-8")
    assert "page-index.js?v=20260803-external-monitor-guard" in index


def test_ink_pulse_body_page_entry_never_creates_fixed_modal_containing_block() -> None:
    skin_css = (ROOT / "web" / "static" / "skins" / "ink-pulse" / "skin.css").read_text(encoding="utf-8")

    def declaration_map(block: str) -> dict[str, str]:
        declarations: dict[str, str] = {}
        for item in block.split(";"):
            property_name, separator, value = item.partition(":")
            if separator:
                declarations[property_name.strip().lower()] = value.strip().lower()
        return declarations

    def nested_block_contents(source: str, opening_brace: int) -> str:
        depth = 0
        for index in range(opening_brace, len(source)):
            if source[index] == "{":
                depth += 1
            elif source[index] == "}":
                depth -= 1
                if depth == 0:
                    return source[opening_brace + 1 : index]
        raise AssertionError("Unclosed CSS block")

    body_rule = re.search(r"(?m)^body\s*\{(?P<declarations>[^{}]*)\}", skin_css)
    assert body_rule is not None
    body_declarations = declaration_map(body_rule.group("declarations"))
    assert body_declarations.get("transform", "none") == "none"

    animation = body_declarations.get("animation", "")
    keyframe_names = re.findall(r"@keyframes\s+([a-zA-Z_][\w-]*)", skin_css)
    body_keyframes = [name for name in keyframe_names if re.search(rf"\b{re.escape(name)}\b", animation)]
    assert body_keyframes == ["ink-pulse-page-in"]

    keyframes_header = re.search(
        rf"@keyframes\s+{re.escape(body_keyframes[0])}\s*\{{",
        skin_css,
    )
    assert keyframes_header is not None
    keyframes_body = nested_block_contents(skin_css, keyframes_header.end() - 1)
    frame_blocks = re.findall(r"\{(?P<declarations>[^{}]*)\}", keyframes_body)
    assert frame_blocks
    animated_properties = {
        property_name
        for frame_block in frame_blocks
        for property_name in declaration_map(frame_block)
    }
    assert animated_properties == {"opacity"}, (
        "Ink Pulse body entry must stay opacity-only so fixed dialogs remain viewport-relative throughout the animation"
    )


def test_ink_pulse_selection_summary_project_metrics_stack_at_phone_width() -> None:
    skin_css = (ROOT / "web" / "static" / "skins" / "ink-pulse" / "skin.css").read_text(encoding="utf-8")

    def nested_block_contents(source: str, opening_brace: int) -> str:
        depth = 0
        for index in range(opening_brace, len(source)):
            if source[index] == "{":
                depth += 1
            elif source[index] == "}":
                depth -= 1
                if depth == 0:
                    return source[opening_brace + 1 : index]
        raise AssertionError("Unclosed CSS block")

    phone_media_headers = list(
        re.finditer(r"@media\s*\(\s*max-width\s*:\s*420px\s*\)\s*\{", skin_css)
    )
    assert len(phone_media_headers) == 1
    phone_css = nested_block_contents(skin_css, phone_media_headers[0].end() - 1)
    project_metrics_rule = re.search(
        r"(?m)^\s*\.selection-summary-project\s+\.detail-cost-metrics\s*\{(?P<declarations>[^{}]*)\}",
        phone_css,
    )
    assert project_metrics_rule is not None, (
        "Ink Pulse selection-summary project metrics must have a phone-width override"
    )

    declarations = {
        property_name.strip().lower(): value.strip().lower()
        for item in project_metrics_rule.group("declarations").split(";")
        for property_name, separator, value in [item.partition(":")]
        if separator
    }
    columns = re.sub(r"\s+", " ", declarations.get("grid-template-columns", ""))
    assert columns == "minmax(0, 1fr)"


def test_ink_pulse_skin_is_original_css_only_and_token_driven() -> None:
    skin_dir = ROOT / "web" / "static" / "skins" / "ink-pulse"
    skin_css = (skin_dir / "skin.css").read_text(encoding="utf-8")
    manifest = (skin_dir / "skin.json").read_text(encoding="utf-8")
    sources = (skin_dir / "asset-sources.json").read_text(encoding="utf-8")

    for token in (
        "--bg:",
        "--surface:",
        "--primary:",
        "--ink-lime:",
        "--ink-violet:",
        "--ink-pink:",
        "--ink-cyan:",
    ):
        assert token in skin_css
    for selector in (
        "body",
        ".topbar",
        ".brand-mark",
        ".nav-link",
        ".btn--primary",
        ".input",
        ".status-pill--success",
        ".status-pill--partial",
        ".status-pill--pending",
        ".service-status::before",
        '.tab[aria-selected="true"]',
        ".data-table th",
        ".data-table tbody tr:nth-child(even) td",
        ".table-shell",
        ".selection-summary",
        ".selection-summary-dialog",
        ".selection-summary-total",
        ".selection-summary-project",
        ".selection-tax-rate-badge",
        ".cost-view .data-table td",
        'body[data-page="detail"] .detail-cost-project',
        'body[data-page="detail"] .detail-cost-project-head',
        'body[data-page="detail"] .detail-cost-metric',
        'body[data-page="detail"] .detail-cost-table th',
        'body[data-page="detail"] .detail-cost-number',
        ".reference-quantity-input",
        ".skin-card",
        ".modal-backdrop",
        ".document-table--inbound th",
        'body[data-page="index"] .watch-dir-history__label',
        'body[data-page="documents"] .watch-dir-history__label',
        'body[data-page="costs"] .markup-rate-percent',
        'body[data-page="costs"] .cost-formula-help',
        'body[data-page="costs"] .cost-row-limit-btn[aria-pressed="true"]',
        'body[data-page="consistency"] .mismatch-list',
        'body[data-page="index"] .invoice-classification__business',
        'body[data-page="settings"] .settings-shutdown-card',
        'body[data-page="settings"] .settings-shutdown-choice',
        'body[data-page="settings"] .settings-shutdown-progress',
        'body[data-page="settings"] .settings-tab[aria-selected="true"]',
        'body[data-page="settings"] .settings-segment[aria-pressed="true"]',
    ):
        assert selector in skin_css
    assert "scrollbar-gutter: stable;" in skin_css
    assert "@keyframes ink-pulse-page-in" in skin_css
    assert "animation: ink-pulse-page-in 190ms ease-out both;" in skin_css
    assert "@media (prefers-reduced-motion: reduce)" in skin_css
    assert "1.3.0" in manifest
    assert '"version": "1.3.0"' in sources
    assert 'body[data-page="settings"] .watch-dir-option' in skin_css
    assert 'body[data-page="costs"] .reference-markup-input[readonly]' in skin_css
    assert "color: var(--ink-white);" in skin_css[skin_css.index('body[data-page="costs"] .markup-rate-percent'):]
    assert 'var(--ink-cyan)' in skin_css[skin_css.index('body[data-page="detail"] .detail-cost-table th'):]
    assert 'var(--ink-lime)' in skin_css[skin_css.index('body[data-page="detail"] .detail-cost-number'):]
    assert 'body[data-page="detail"] .detail-cost-scroll::-webkit-scrollbar-thumb' in skin_css
    assert "@media (max-width: 420px)" in skin_css
    assert 'body[data-page="detail"] .detail-cost-metrics' in skin_css[skin_css.index("@media (max-width: 420px)"):]
    assert '"SIL Open Font License 1.1"' in sources
    assert '"texture_method"' in sources
    assert "No third-party code" in sources
    assert '@font-face' in skin_css
    assert 'font-family: "Ink Pulse Dela"' in skin_css
    assert 'font-family: "Ink Pulse KuaiLe"' in skin_css
    assert 'url("textures/ink-field-v1.webp")' in skin_css
    assert 'url("textures/panel-print-v1.webp")' in skin_css
    assert 'url("textures/ink-splatter-atlas-v1.png")' in skin_css
    assert "-webkit-mask-image:" in skin_css
    assert "mask-size: 200% 200%;" in skin_css
    assert ".stat-card:nth-child(4n + 1)::after" in skin_css
    assert ".stat-card:nth-child(4n + 2)::after" in skin_css
    assert ".stat-card:nth-child(4n + 3)::after" in skin_css
    assert ".stat-card:nth-child(4n)::after" in skin_css
    assert "--ink-card-splash" not in skin_css

    index_html = (ROOT / "web" / "templates" / "index.html").read_text(encoding="utf-8")
    dashboard_end = index_html.index("</section>", index_html.index('class="dashboard-grid"'))
    dossier_index = index_html.index('id="businessDossierPanel"')
    filter_index = index_html.index("<h3>筛选</h3>")
    assert dashboard_end < dossier_index < filter_index
    assert 'class="panel business-dossier business-dossier--wide"' in index_html
    assert 'body[data-page="index"] .business-dossier--wide' in skin_css
    assert "color: var(--ink-white);" in skin_css[skin_css.index(".cost-view .data-table td {"):]

    lowered = skin_css.lower()
    for blocked in ("@import", "<script", "javascript:", "data:", "http://", "https://", "nintendo", "splatoon"):
        assert blocked not in lowered

    urls = re.findall(r"url\(\s*['\"]?([^'\")]+)['\"]?\s*\)", skin_css)
    assert set(urls) == {
        "fonts/dela-gothic-one-latin.woff",
        "fonts/zcool-kuaile-ui.woff",
        "textures/ink-field-v1.webp",
        "textures/panel-print-v1.webp",
        "textures/ink-splatter-atlas-v1.png",
    }
    for url in urls:
        assert ".." not in url
        assert "\\" not in url
        assert (skin_dir / url).is_file(), url
        assert (skin_dir / url).stat().st_size > 0
    assert (skin_dir / "fonts" / "OFL-DelaGothicOne.txt").stat().st_size > 0
    assert (skin_dir / "fonts" / "OFL-ZCOOLKuaiLe.txt").stat().st_size > 0
    for texture in (
        skin_dir / "textures" / "ink-field-v1.webp",
        skin_dir / "textures" / "panel-print-v1.webp",
        skin_dir / "textures" / "ink-splatter-atlas-v1.png",
    ):
        assert texture.stat().st_size < 2 * 1024 * 1024
    assert (skin_dir / "textures" / "ink-field-v1.webp").read_bytes()[:4] == b"RIFF"
    assert (skin_dir / "textures" / "panel-print-v1.webp").read_bytes()[:4] == b"RIFF"
    assert (skin_dir / "textures" / "ink-splatter-atlas-v1.png").read_bytes()[:8] == b"\x89PNG\r\n\x1a\n"
