const consistencyRefs = {
  banner: document.getElementById("pageBanner"),
  onlyMismatch: document.getElementById("onlyMismatchToggle"),
  stats: document.getElementById("consistencyStats"),
  groups: document.getElementById("consistencyGroups"),
};

function renderConsistencyStats(stats = {}) {
  const cards = [
    ["总组数", stats.total_groups || 0],
    ["一致", stats.consistent_groups || 0],
    ["存在差异", stats.inconsistent_groups || 0],
  ];
  consistencyRefs.stats.innerHTML = cards.map(([label, value]) => `<div class="stat-card"><span>${app.escapeHtml(label)}</span><strong>${app.escapeHtml(value)}</strong></div>`).join("");
}

function consistencyClassificationMeta(value) {
  const normalized = String(value || "").trim();
  if (normalized === "ok") return { label: "已识别", tone: "success" };
  if (normalized === "conflict") return { label: "冲突", tone: "danger" };
  return { label: "待核对", tone: "warning" };
}

function renderConsistencyGroups(groups = []) {
  consistencyRefs.groups.innerHTML = groups.length
    ? groups.map((group) => {
        const mismatches = (group.mismatch_fields || [])
          .map((item) => `<li><strong>${app.escapeHtml(item.field)}</strong>：${app.escapeHtml((item.values || []).join(" / "))}</li>`)
          .join("");
        const rows = (group.items || [])
          .map((item) => {
            const classification = consistencyClassificationMeta(item.classification_status);
            const issue = String(item.classification_issue || "").trim();
            const issueHtml = issue
              ? `<span class="path-cell" tabindex="0" title="${app.escapeHtml(issue)}">${app.escapeHtml(issue)}</span>`
              : "";
            return `
              <tr>
                <td>${app.escapeHtml(item.file_type || "--")}</td>
                <td><a href="${app.escapeHtml(item.detail_url || "#")}">${app.escapeHtml(item.file_name || "--")}</a></td>
                <td>${app.escapeHtml(item.invoice_number || "--")}</td>
                <td>${app.escapeHtml(item.invoice_type || "--")}</td>
                <td>${app.escapeHtml(item.business_type || "--")}</td>
                <td>
                  ${app.statusPill(classification.label, classification.tone)}
                  ${issueHtml}
                </td>
                <td>${app.escapeHtml(item.amount || "--")}</td>
                <td>${app.escapeHtml(item.seller || "--")}</td>
                <td>${app.escapeHtml(item.buyer || "--")}</td>
              </tr>
            `;
          })
          .join("");
        return `
          <section class="panel">
            <div class="panel__head">
              <div>
                <h3>${app.escapeHtml(group.invoice_number || group.pair_key || "--")}</h3>
                <p>格式：${app.escapeHtml((group.formats || []).join(" / ") || "--")}，文件 ${app.escapeHtml(group.file_count || 0)} 个</p>
              </div>
              ${app.statusPill(group.consistent ? "一致" : "存在差异", group.consistent ? "success" : "warning")}
            </div>
            <div class="table-shell">
              <table class="data-table">
                <thead><tr><th>格式</th><th>文件名</th><th>发票号码</th><th>发票大类</th><th>特定业务类型</th><th>类型识别</th><th>金额</th><th>销售方</th><th>购买方</th></tr></thead>
                <tbody>${rows}</tbody>
              </table>
            </div>
            <ul class="mismatch-list">${mismatches || "<li>无差异字段</li>"}</ul>
          </section>
        `;
      }).join("")
    : '<section class="panel empty-state">暂无多格式同票组。</section>';
}

async function loadConsistencyReport() {
  const query = consistencyRefs.onlyMismatch.checked ? "?only_mismatch=true" : "";
  const payload = await app.api(`/api/v1/consistency-report${query}`);
  renderConsistencyStats(payload.stats || {});
  renderConsistencyGroups(payload.groups || []);
}

consistencyRefs.onlyMismatch.addEventListener("change", () => {
  loadConsistencyReport().catch((error) => app.setBanner(consistencyRefs.banner, "danger", error.message || "加载一致性报告失败"));
});

loadConsistencyReport().catch((error) => app.setBanner(consistencyRefs.banner, "danger", error.message || "加载一致性报告失败"));
