const detailKey = decodeURIComponent(location.pathname.split("/").pop() || "");
const detailRefs = {
  path: document.getElementById("detailPath"),
  banner: document.getElementById("detailBanner"),
  summary: document.getElementById("detailSummary"),
  sourceMeta: document.getElementById("sourceMeta"),
  costBreakdown: document.getElementById("detailCostBreakdown"),
  costMeta: document.getElementById("detailCostMeta"),
  form: document.getElementById("manualForm"),
  seller: document.getElementById("manualSeller"),
  amount: document.getElementById("manualAmount"),
  number: document.getElementById("manualNumber"),
  openBtn: document.getElementById("openSourceBtn"),
  openLocationBtn: document.getElementById("openSourceLocationBtn"),
  saveBtn: document.getElementById("saveManualBtn"),
};
let detailPayload = null;

function detailNumber(value, decimals = 2) {
  if (value === null || value === undefined || value === "") return "--";
  const number = Number(value);
  if (!Number.isFinite(number)) return "--";
  return number.toLocaleString("zh-CN", { minimumFractionDigits: decimals, maximumFractionDigits: decimals });
}

function detailText(value) {
  return value === null || value === undefined || value === "" ? "--" : String(value);
}

function detailTextCell(value, extraClass = "") {
  const text = detailText(value);
  return `<span class="detail-cost-text ${extraClass}" title="${app.escapeHtml(text)}">${app.escapeHtml(text)}</span>`;
}

function detailNumberCell(value, decimals = 2) {
  return `<span class="detail-cost-number">${app.escapeHtml(detailNumber(value, decimals))}</span>`;
}

function detailCostMetric(label, value, decimals) {
  return `
    <div class="detail-cost-metric">
      <span>${app.escapeHtml(label)}</span>
      <strong>${app.escapeHtml(detailNumber(value, decimals))}</strong>
    </div>
  `;
}

function detailCostMatchLabel(strategy) {
  if (strategy === "invoice_number") return "发票号匹配";
  if (strategy === "source_file") return "源文件匹配";
  return "未匹配";
}

function detailClassificationMeta(value) {
  const normalized = String(value || "").trim();
  if (normalized === "ok") return { label: "已识别", tone: "success" };
  if (normalized === "conflict") return { label: "冲突", tone: "danger" };
  return { label: "待核对", tone: "warning" };
}

function renderCostBreakdown(breakdown = {}) {
  const projects = Array.isArray(breakdown.projects) ? breakdown.projects : [];
  if (detailRefs.costMeta) {
    const countText = projects.length ? `${detailCostMatchLabel(breakdown.match_strategy)}，${breakdown.detail_count || 0} 条明细` : "当前发票暂无匹配成本明细";
    detailRefs.costMeta.textContent = countText;
  }
  if (!detailRefs.costBreakdown) return;
  if (!projects.length) {
    detailRefs.costBreakdown.innerHTML = `<div class="detail-cost-empty">暂无本票成本明细</div>`;
    return;
  }
  detailRefs.costBreakdown.innerHTML = projects.map((project) => {
    const projectName = project.display_project_name || project.project_name || "未识别项目";
    const specs = Array.isArray(project.specs) ? project.specs : [];
    const rows = specs.length
      ? specs.map((spec) => `
        <tr>
          <td>${detailTextCell(spec.specification, "detail-cost-spec")}</td>
          <td>${detailTextCell(spec.unit, "detail-cost-unit")}</td>
          <td>${detailNumberCell(spec.quantity_total, 3)}</td>
          <td>${detailNumberCell(spec.arithmetic_average_unit_price_pretax, 2)}</td>
          <td>${detailNumberCell(spec.arithmetic_average_unit_price_with_tax, 2)}</td>
          <td>${detailNumberCell(spec.weighted_average_unit_price_pretax, 2)}</td>
          <td>${detailNumberCell(spec.weighted_average_unit_price_with_tax, 2)}</td>
        </tr>
      `).join("")
      : `<tr><td colspan="7">暂无规格明细</td></tr>`;
    return `
      <article class="detail-cost-project">
        <div class="detail-cost-project-head">
          <strong class="detail-cost-name" title="${app.escapeHtml(projectName)}">${app.escapeHtml(projectName)}</strong>
          <span class="detail-cost-count">${specs.length} 个规格</span>
        </div>
        <div class="detail-cost-metrics">
          ${detailCostMetric("数量合计", project.quantity_total, 3)}
          ${detailCostMetric("除税总计", project.amount_pretax_total, 2)}
          ${detailCostMetric("价税合计", project.total_with_tax, 2)}
        </div>
        <div class="detail-cost-scroll">
          <table class="data-table detail-cost-table">
            <thead>
              <tr>
                <th>规格型号</th>
                <th>单位</th>
                <th>数量</th>
                <th>算术均价(除税)</th>
                <th>算术均价(含税)</th>
                <th>加权均价(除税)</th>
                <th>加权均价(含税)</th>
              </tr>
            </thead>
            <tbody>${rows}</tbody>
          </table>
        </div>
      </article>
    `;
  }).join("");
}

function renderDetail(payload) {
  detailPayload = payload;
  const item = payload.invoice || payload.item || {};
  detailRefs.path.textContent = item.file_path || item.source_path || "--";
  detailRefs.path.title = item.file_path || item.source_path || "";
  detailRefs.seller.value = item.seller || "";
  detailRefs.amount.value = item.amount || "";
  detailRefs.number.value = item.invoice_number || "";
  const classification = detailClassificationMeta(item.classification_status);
  const cards = [
    ["销售方", item.seller || "--", "seller"],
    ["购买方", item.buyer || "--", "buyer"],
    ["发票号码", item.invoice_number || "--", "number"],
    ["发票大类", item.invoice_type || "--", "invoice_type"],
    ["特定业务类型", item.business_type || "--", "business_type"],
    ["类型识别状态", app.statusPill(classification.label, classification.tone), "classification_status"],
    ["类型识别说明", item.classification_issue || "无", "classification_issue"],
    ["开票金额", item.amount || "--", "amount"],
    ["税额", item.tax_amount || "--", "tax"],
    ["除税价", item.pretax_amount || "--", "pretax"],
    ["税率", item.tax_rate || "--", "rate"],
    ["汇总状态", app.statusPill(item.status || "--", app.toneFromStatus(item.status || "")), "status"],
    ["手改状态", item.has_manual_override ? app.statusPill("已手改", "warning") : app.statusPill("原始识别", "muted"), "manual"],
  ];
  detailRefs.summary.innerHTML = cards.map(([label, value, meta]) => `<div class="stat-card"><span>${app.escapeHtml(label)}</span><strong>${String(value).startsWith("<span") ? value : app.escapeHtml(value)}</strong><small>${app.escapeHtml(meta)}</small></div>`).join("");
  detailRefs.sourceMeta.innerHTML = `
    <div><dt>源文件路径</dt><dd class="path-cell" tabindex="0" title="${app.escapeHtml(item.file_path || item.source_path || "")}">${app.escapeHtml(item.file_path || item.source_path || "--")}</dd></div>
    <div><dt>文件名</dt><dd>${app.escapeHtml(item.file_name || item.source_file || "--")}</dd></div>
    <div><dt>文件存在</dt><dd>${item.source_exists ? "是" : "否"}</dd></div>
    <div><dt>文件大小</dt><dd>${app.escapeHtml(app.formatBytes(item.source_size_bytes))}</dd></div>
    <div><dt>最后修改</dt><dd>${app.escapeHtml(item.source_modified_at || "--")}</dd></div>
    <div><dt>汇总来源</dt><dd>${app.escapeHtml(payload.snapshot?.source_label || "--")}</dd></div>
  `;
  renderCostBreakdown(payload.cost_breakdown || item.cost_breakdown || {});
}

async function loadDetail() {
  renderDetail(await app.api(`/api/v1/invoices/${encodeURIComponent(detailKey)}`));
}

detailRefs.form.addEventListener("submit", async (event) => {
  event.preventDefault();
  app.setBusy(detailRefs.saveBtn, true, "保存中...");
  try {
    await app.api(`/api/v1/invoices/${encodeURIComponent(detailKey)}/manual-fields`, {
      method: "PATCH",
      body: { fields: { "销售方": detailRefs.seller.value, "开票金额": detailRefs.amount.value, "发票号码": detailRefs.number.value } },
    });
    await loadDetail();
    app.setBanner(detailRefs.banner, "success", "手工修订已保存");
  } finally {
    app.setBusy(detailRefs.saveBtn, false);
  }
});
async function runOpenAction(button, url, successText, displayField) {
  app.setBusy(button, true, "打开中...");
  try {
    const payload = await app.api(url, { method: "POST", body: {} });
    const displayValue = displayField ? payload[displayField] : "";
    app.setBanner(detailRefs.banner, payload.ok ? "success" : "warning", displayValue || payload.message || successText);
  } catch (error) {
    app.setBanner(detailRefs.banner, "danger", error.message);
  } finally {
    app.setBusy(button, false);
  }
}

detailRefs.openBtn.addEventListener("click", () => {
  runOpenAction(detailRefs.openBtn, `/api/v1/invoices/${encodeURIComponent(detailKey)}/open-file`, "已请求打开文件", "file_name");
});

detailRefs.openLocationBtn.addEventListener("click", () => {
  runOpenAction(detailRefs.openLocationBtn, `/api/v1/invoices/${encodeURIComponent(detailKey)}/open-location`, "已请求打开文件所在位置", "folder_path");
});

loadDetail().catch((error) => app.setBanner(detailRefs.banner, "danger", error.message));
