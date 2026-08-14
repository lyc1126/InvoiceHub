(() => {
  const state = {
    setup: null,
    bookkeeping: null,
    vouchers: [],
    exportStatus: null,
    accounts: [],
    auxValues: [],
    mappings: null,
    mappingImpact: null,
    voucherMigrationPreview: null,
    mappingMigrationPreview: null,
    selectedKey: "",
    busyAction: "",
    decisionDirty: false,
    decisionBaseline: null,
    profileDirty: false,
    profileBaseline: null,
    profileConflict: false,
    activeTab: "review",
  };

  const refs = {
    banner: app.qs("#bookkeepingBanner"),
    path: app.qs("#bookkeepingPath"),
    eventState: app.qs("#eventState"),
    tabs: Array.from(document.querySelectorAll("[data-bookkeeping-tab]")),
    views: Array.from(document.querySelectorAll("[data-bookkeeping-view]")),
    ledgerIdentityState: app.qs("#ledgerIdentityState"),
    accountCatalogState: app.qs("#accountCatalogState"),
    auxCatalogState: app.qs("#auxCatalogState"),
    reviewReadinessState: app.qs("#reviewReadinessState"),
    approvalReadinessState: app.qs("#approvalReadinessState"),
    exportReadinessState: app.qs("#exportReadinessState"),
    draftCount: app.qs("#draftCount"),
    approvedCount: app.qs("#approvedCount"),
    exportedCount: app.qs("#exportedCount"),
    mappingRuleCount: app.qs("#mappingRuleCount"),
    generateBtn: app.qs("#generateDraftsBtn"),
    exportBtn: app.qs("#exportImportFileBtn"),
    refreshBtn: app.qs("#refreshBookkeepingBtn"),
    copyBtn: app.qs("#copyVoucherTableBtn"),
    statusFilter: app.qs("#statusFilter"),
    tierFilter: app.qs("#tierFilter"),
    exportStatusPanel: app.qs("#exportStatusPanel"),
    table: app.qs("#voucherTable"),
    tbody: app.qs("#voucherTableBody"),
    tableMeta: app.qs("#voucherTableMeta"),
    detailPanel: app.qs("#voucherDetailPanel"),
    detailMeta: app.qs("#voucherDetailMeta"),
    balanceState: app.qs("#voucherBalanceState"),
    linesBody: app.qs("#voucherLinesBody"),
    blockerList: app.qs("#voucherBlockers"),
    sourceRows: app.qs("#voucherSourceRows"),
    auditBody: app.qs("#voucherAuditBody"),
    decisionForm: app.qs("#voucherDecisionForm"),
    decisionRevision: app.qs("#voucherDecisionRevision"),
    decisionBusinessClass: app.qs("#decisionBusinessClass"),
    decisionPaymentState: app.qs("#decisionPaymentState"),
    decisionTaxTreatment: app.qs("#decisionTaxTreatment"),
    decisionReceivingState: app.qs("#decisionReceivingState"),
    taxEvidenceRowsBody: app.qs("#taxEvidenceRowsBody"),
    addTaxEvidenceBtn: app.qs("#addTaxEvidenceBtn"),
    paymentEvidenceRowsBody: app.qs("#paymentEvidenceRowsBody"),
    addPaymentEvidenceBtn: app.qs("#addPaymentEvidenceBtn"),
    receivingReason: app.qs("#receivingNotApplicableReason"),
    decisionSourceLinesBody: app.qs("#decisionSourceLinesBody"),
    decisionReceivingRowsBody: app.qs("#decisionReceivingRowsBody"),
    decisionLinesBody: app.qs("#decisionLinesBody"),
    decisionStatus: app.qs("#voucherDecisionStatus"),
    recomputeVoucherBtn: app.qs("#recomputeVoucherBtn"),
    saveDecisionBtn: app.qs("#saveVoucherDecisionBtn"),
    mappingForm: app.qs("#mappingRuleForm"),
    mappingRevisionMeta: app.qs("#mappingRevisionMeta"),
    mappingSourceType: app.qs("#mappingSourceType"),
    mappingSeller: app.qs("#mappingSeller"),
    mappingItem: app.qs("#mappingItem"),
    mappingProject: app.qs("#mappingProject"),
    mappingEffectiveFrom: app.qs("#mappingEffectiveFrom"),
    mappingEffectiveTo: app.qs("#mappingEffectiveTo"),
    mappingPriority: app.qs("#mappingPriority"),
    mappingBusinessClass: app.qs("#mappingBusinessClass"),
    mappingDebitAccount: app.qs("#mappingDebitAccount"),
    mappingCreditAccount: app.qs("#mappingCreditAccount"),
    mappingTaxAccount: app.qs("#mappingTaxAccount"),
    mappingReplacesRuleId: app.qs("#mappingReplacesRuleId"),
    mappingAuxFields: app.qs("#mappingAuxFields"),
    previewMappingBtn: app.qs("#previewMappingRuleBtn"),
    saveMappingBtn: app.qs("#saveMappingRuleBtn"),
    mappingImpactPanel: app.qs("#mappingImpactPanel"),
    mappingTableMeta: app.qs("#mappingTableMeta"),
    mappingRulesBody: app.qs("#mappingRulesBody"),
    setupProfileMeta: app.qs("#setupProfileMeta"),
    setupCatalogDetails: app.qs("#setupCatalogDetails"),
    voucherMigrationStatus: app.qs("#voucherMigrationStatus"),
    previewVoucherMigrationBtn: app.qs("#previewVoucherMigrationBtn"),
    applyVoucherMigrationBtn: app.qs("#applyVoucherMigrationBtn"),
    mappingMigrationStatus: app.qs("#mappingMigrationStatus"),
    previewMappingMigrationBtn: app.qs("#previewMappingMigrationBtn"),
    applyMappingMigrationBtn: app.qs("#applyMappingMigrationBtn"),
    profileForm: app.qs("#ledgerProfileForm"),
    profileCompanyName: app.qs("#profileCompanyName"),
    profileCompanyTaxId: app.qs("#profileCompanyTaxId"),
    profileEnvironment: app.qs("#profileEnvironment"),
    profileInstanceKey: app.qs("#profileInstanceKey"),
    profileLedgerName: app.qs("#profileLedgerName"),
    profileIdentityMethod: app.qs("#profileIdentityMethod"),
    profileCaptureId: app.qs("#profileCaptureId"),
    profileAccountingStandard: app.qs("#profileAccountingStandard"),
    profileTaxpayerProfile: app.qs("#profileTaxpayerProfile"),
    profileCurrency: app.qs("#profileCurrency"),
    profileOpenPeriods: app.qs("#profileOpenPeriods"),
    profileClosedThrough: app.qs("#profileClosedThrough"),
    profileVoucherType: app.qs("#profileVoucherType"),
    profileWritePermission: app.qs("#profileWritePermission"),
    profileStatus: app.qs("#ledgerProfileStatus"),
    saveProfileBtn: app.qs("#saveLedgerProfileBtn"),
  };

  const editableStatuses = new Set(["draft", "blocked", "review_pending", "rejected"]);
  const recomputableStatuses = new Set(["draft", "blocked", "rejected"]);
  const statusTone = {
    draft: "muted", blocked: "danger", review_pending: "warning", approved: "success",
    exported: "warning", importing: "warning", imported: "success", import_failed: "danger",
    import_failed_confirmed: "danger", import_unknown: "danger", reconciled: "success",
    rejected: "danger", manual_entry: "muted",
  };

  function setBanner(tone, message) {
    app.setBanner(refs.banner, tone, message);
  }

  function localReviewerId() {
    const key = "invoicehub.bookkeeping.localReviewerId";
    try {
      const existing = window.localStorage.getItem(key);
      if (existing) return existing;
      const created = `local-${crypto.randomUUID()}`;
      window.localStorage.setItem(key, created);
      return created;
    } catch (_error) {
      return "local-browser";
    }
  }

  function commandId() {
    return typeof crypto?.randomUUID === "function" ? crypto.randomUUID() : `cmd-${Date.now()}`;
  }

  function selectedItem() {
    return state.vouchers.find((item) => item.voucher_key === state.selectedKey) || null;
  }

  function snapshotOf(item) {
    return item?.snapshot || {};
  }

  function asNumber(value) {
    const number = Number(value || 0);
    return Number.isFinite(number) ? number : 0;
  }

  function amountText(value) {
    return app.formatMoney(asNumber(value));
  }

  function voucherLines(snapshot) {
    return Array.isArray(snapshot?.lines) ? snapshot.lines : [];
  }

  function sourceInvoiceText(snapshot) {
    const values = Array.isArray(snapshot?.source_invoice_nos) ? snapshot.source_invoice_nos : [];
    return values.length ? values.join("、") : "--";
  }

  function lineTotal(snapshot, direction) {
    return voucherLines(snapshot)
      .filter((line) => line.direction === direction)
      .reduce((total, line) => total + asNumber(line.amount), 0);
  }

  function lineSummary(snapshot) {
    const lines = voucherLines(snapshot);
    return `${lines.length} 行 · ${lines[0]?.summary || "--"}`;
  }

  function tierBadge(tier) {
    const value = String(tier || "forced_manual");
    const safe = ["auto", "ai_suggested", "forced_manual", "manual_confirmed"].includes(value) ? value : "forced_manual";
    return `<span class="review-tier-badge review-tier-badge--${safe}">${app.escapeHtml(value)}</span>`;
  }

  function statusPill(status) {
    return app.statusPill(String(status || "--"), statusTone[status] || "muted");
  }

  function switchTab(tab) {
    state.activeTab = tab;
    refs.tabs.forEach((button) => {
      const active = button.dataset.bookkeepingTab === tab;
      button.classList.toggle("is-active", active);
      button.setAttribute("aria-selected", active ? "true" : "false");
      button.tabIndex = active ? 0 : -1;
    });
    refs.views.forEach((view) => { view.hidden = view.dataset.bookkeepingView !== tab; });
    if (tab === "mapping") Promise.all([loadMappings(), loadAccounts(), loadAuxValues()]);
    if (tab === "setup") loadSetup();
  }

  function readinessText(value) {
    return value ? "就绪" : "阻断";
  }

  function profileBaselineFrom(payload) {
    return {
      profileRevision: Number(payload?.profile_revision || 0),
      profileSha256: String(payload?.profile_sha256 || ""),
      accountSha256: String(payload?.account_catalog?.sha256 || ""),
      auxSha256: String(payload?.aux_catalog?.sha256 || ""),
    };
  }

  function profileBaselineChanged(payload) {
    if (!state.profileBaseline) return false;
    const incoming = profileBaselineFrom(payload);
    return Object.keys(incoming).some((key) => incoming[key] !== state.profileBaseline[key]);
  }

  function renderMigrationStatus() {
    const voucherState = state.setup?.migration || {};
    const mappingState = state.setup?.mapping_migration || {};
    const voucherPreview = state.voucherMigrationPreview;
    const mappingPreview = state.mappingMigrationPreview;
    if (!voucherState.migration_required) {
      refs.voucherMigrationStatus.textContent = "schema v2 · 无需迁移";
    } else if (voucherPreview) {
      refs.voucherMigrationStatus.textContent = `schema v1 → v2 · ${voucherPreview.mappings?.length || 0} 项 · 冲突 ${voucherPreview.conflicts?.length || 0} 项 · SHA ${String(voucherPreview.source_sha256 || "").slice(0, 12)}`;
    } else {
      refs.voucherMigrationStatus.textContent = `schema v1 · 待预览 · SHA ${String(voucherState.source_sha256 || "").slice(0, 12)}`;
    }
    if (!mappingState.migration_required) {
      refs.mappingMigrationStatus.textContent = "schema v2 · 无需迁移";
    } else if (mappingPreview) {
      refs.mappingMigrationStatus.textContent = `schema v1 → v2 · ${mappingPreview.rule_mappings?.length || 0} 条 · 冲突 ${mappingPreview.conflicts?.length || 0} 项 · SHA ${String(mappingPreview.source_sha256 || "").slice(0, 12)}`;
    } else {
      refs.mappingMigrationStatus.textContent = `schema v1 · 待预览 · SHA ${String(mappingState.source_sha256 || "").slice(0, 12)}`;
    }
  }

  function renderSetup(payload) {
    if (state.profileDirty && profileBaselineChanged(payload)) {
      state.profileConflict = true;
      refs.profileStatus.textContent = "服务端账套或档案 revision 已变化，请刷新后重新确认。";
      setBanner("warning", "账套设置已发生并发更新，当前未保存内容仍保留，但不能覆盖新 revision。");
    }
    if (state.voucherMigrationPreview?.source_sha256 !== payload?.migration?.source_sha256) {
      state.voucherMigrationPreview = null;
    }
    if (state.mappingMigrationPreview?.source_sha256 !== payload?.mapping_migration?.source_sha256) {
      state.mappingMigrationPreview = null;
    }
    state.setup = payload;
    const profile = payload?.profile;
    refs.ledgerIdentityState.textContent = profile
      ? `${profile.ledger_environment === "production" ? "正式" : "测试"} · ${profile.ledger_name}`
      : "未确认";
    refs.accountCatalogState.textContent = payload?.account_catalog?.error
      ? "无效"
      : `${payload?.account_catalog?.count || 0} 科目`;
    refs.auxCatalogState.textContent = payload?.aux_catalog?.error
      ? "无效"
      : `${payload?.aux_catalog?.count || 0} 档案`;
    refs.reviewReadinessState.textContent = readinessText(payload?.ready_for_review === true);
    refs.approvalReadinessState.textContent = readinessText(payload?.ready_for_approval === true);
    refs.exportReadinessState.textContent = readinessText(payload?.ready_for_export === true);
    refs.setupProfileMeta.textContent = `profile revision: ${payload?.profile_revision || 0}`;
    const details = [
      ["公司 ID", payload?.company_id || profile?.company_id || "--"],
      ["账套身份", profile?.ledger_identity_sha256 || "--"],
      ["科目 SHA256", payload?.account_catalog?.sha256 || "--"],
      ["辅助 SHA256", payload?.aux_catalog?.sha256 || "--"],
      ["映射 revision", payload?.mapping_revision ?? 0],
      ["映射待确认", payload?.mapping_pending_reconfirmation_count ?? 0],
      ["状态 revision", payload?.store_revision ?? 0],
      ["凭证状态迁移", payload?.migration?.migration_required ? "待显式迁移" : "无需迁移"],
      ["科目映射迁移", payload?.mapping_migration?.migration_required ? "待显式迁移" : "无需迁移"],
    ];
    refs.setupCatalogDetails.innerHTML = details
      .map(([key, value]) => `<dt>${app.escapeHtml(key)}</dt><dd>${app.escapeHtml(String(value))}</dd>`)
      .join("");
    renderMigrationStatus();
    if (!state.profileDirty) hydrateProfileForm(profile || {}, payload);
    updateControls();
  }

  function hydrateProfileForm(profile, setup = state.setup) {
    refs.profileCompanyName.value = profile.company_name || "";
    refs.profileCompanyTaxId.value = profile.company_tax_id || "";
    refs.profileEnvironment.value = profile.ledger_environment || "production";
    refs.profileInstanceKey.value = profile.ledger_instance_key || "";
    refs.profileLedgerName.value = profile.ledger_name || "";
    refs.profileIdentityMethod.value = profile.identity_method || "native_id";
    refs.profileCaptureId.value = profile.capture_id || "";
    refs.profileAccountingStandard.value = profile.accounting_standard || "";
    refs.profileTaxpayerProfile.value = profile.taxpayer_profile || "";
    refs.profileCurrency.value = profile.currency || "CNY";
    refs.profileOpenPeriods.value = Array.isArray(profile.open_periods) ? profile.open_periods.join(", ") : "";
    refs.profileClosedThrough.value = profile.closed_through || "";
    refs.profileVoucherType.value = profile.default_voucher_type || "记";
    refs.profileWritePermission.checked = profile.voucher_write_permission_confirmed === true;
    state.profileBaseline = profileBaselineFrom(setup);
    state.profileDirty = false;
    state.profileConflict = false;
  }

  function renderState(payload) {
    state.bookkeeping = payload;
    const counts = payload?.voucher_status_counts || {};
    refs.draftCount.textContent = String((counts.draft || 0) + (counts.blocked || 0) + (counts.review_pending || 0));
    refs.approvedCount.textContent = String(counts.approved || 0);
    refs.exportedCount.textContent = String(counts.exported || 0);
    refs.mappingRuleCount.textContent = String(payload?.mapping_rule_count || 0);
    refs.path.textContent = payload?.available
      ? `公司资料夹：${payload.company_dir || "--"} · 当前发票目录：${payload.watch_dir || "--"}`
      : `做账不可用：${payload?.reason || "未识别公司资料夹"}`;
    if (payload?.available === false) setBanner("warning", payload.reason || "当前目录无法定位做账资料夹。");
    updateControls();
  }

  function renderExportStatus(payload, result = null) {
    state.exportStatus = payload || state.exportStatus || {};
    const files = Array.isArray(state.exportStatus.files) ? state.exportStatus.files : [];
    const latest = files.at(-1);
    const pieces = [
      `导入目录：${state.exportStatus.import_dir || "--"}`,
      `待导出：${state.exportStatus.pending_export_count || 0} 张`,
      `可执行：${state.exportStatus.exportable_count || 0} 张`,
      `批次：${Array.isArray(state.exportStatus.batches) ? state.exportStatus.batches.length : 0}`,
      `文件数：${files.length}`,
    ];
    if (latest) pieces.push(`最新文件：${latest.file_name || latest.path || "--"}`);
    if (result?.message) pieces.push(result.message);
    refs.exportStatusPanel.textContent = pieces.join(" · ");
    updateControls();
  }

  function renderBlockers(blockers) {
    const items = Array.isArray(blockers) ? blockers : [];
    refs.blockerList.innerHTML = items.length
      ? items.map((blocker) => `<li tabindex="0"><strong>${app.escapeHtml(blocker.code || "BLOCKED")}</strong> ${app.escapeHtml(blocker.message || "存在执行阻断项")}</li>`).join("")
      : "<li>当前未发现执行阻断项</li>";
  }

  function applyErrorBlockers(error, voucherKey = state.selectedKey) {
    const blockers = error?.payload?.error?.blockers;
    if (!Array.isArray(blockers) || !blockers.length) return false;
    const item = state.vouchers.find((value) => value.voucher_key === voucherKey);
    if (item) {
      item.blockers = blockers;
      item.can_approve = false;
    }
    if (voucherKey === state.selectedKey) renderBlockers(blockers);
    updateControls();
    return true;
  }

  function renderVouchers(payload) {
    const items = Array.isArray(payload?.items) ? payload.items : [];
    state.vouchers = items;
    refs.tableMeta.textContent = `当前筛选 ${items.length} 张凭证`;
    if (!items.length) {
      refs.tbody.innerHTML = '<tr><td colspan="8">暂无凭证草稿</td></tr>';
      hideDetail();
      updateControls();
      return;
    }
    refs.tbody.innerHTML = items.map((item) => {
      const snapshot = snapshotOf(item);
      const blockers = Array.isArray(item.blockers) ? item.blockers : [];
      const canReject = ["draft", "review_pending"].includes(item.status);
      const dirtySelected = state.decisionDirty && item.voucher_key === state.selectedKey;
      return `<tr class="bookkeeping-row${item.voucher_key === state.selectedKey ? " is-selected" : ""}" data-voucher-row="${app.escapeHtml(item.voucher_key)}">
        <td>${app.escapeHtml(snapshot.voucher_date || "--")}</td>
        <td class="path-cell">${app.escapeHtml(sourceInvoiceText(snapshot))}</td>
        <td>${app.escapeHtml(lineSummary(snapshot))}</td>
        <td class="bookkeeping-number">${amountText(lineTotal(snapshot, "debit"))}</td>
        <td class="bookkeeping-number">${amountText(lineTotal(snapshot, "credit"))}</td>
        <td>${tierBadge(snapshot.review_tier)}${blockers.length ? `<small>${blockers.length} 项阻断</small>` : ""}</td>
        <td>${statusPill(item.status)}</td>
        <td><div class="bookkeeping-row-actions">
          <button class="btn btn--ghost" type="button" data-view-voucher aria-controls="voucherDetailPanel" aria-expanded="${item.voucher_key === state.selectedKey ? "true" : "false"}">查看/编辑</button>
          <input class="input bookkeeping-reject-reason" type="text" data-reject-reason placeholder="驳回原因" value="${app.escapeHtml(item.reject_reason || "")}" ${canReject ? "" : "disabled"} aria-label="驳回原因">
          <button class="btn btn--secondary" type="button" data-review-action="approve" ${item.can_approve === true && !dirtySelected ? "" : "disabled"}>通过</button>
          <button class="btn btn--ghost" type="button" data-review-action="reject" ${canReject && !dirtySelected ? "" : "disabled"}>驳回</button>
        </div></td>
      </tr>`;
    }).join("");
    const item = selectedItem();
    if (item) renderDetail(item, state.decisionDirty);
    else hideDetail(false);
    updateControls();
  }

  function hideDetail(clearSelection = true) {
    if (clearSelection) {
      state.selectedKey = "";
      state.decisionBaseline = null;
    }
    refs.detailPanel.hidden = true;
    refs.linesBody.innerHTML = "";
    refs.sourceRows.innerHTML = "";
    refs.blockerList.innerHTML = "";
    refs.auditBody.innerHTML = "";
  }

  function accountOptions(selected, allowEmpty = false) {
    const prefix = allowEmpty ? '<option value="">不使用</option>' : '<option value="">请选择科目</option>';
    return prefix + state.accounts.map((account) => `<option value="${app.escapeHtml(account.code)}" ${account.code === selected ? "selected" : ""}>${app.escapeHtml(`${account.code} ${account.name}`)}</option>`).join("");
  }

  function renderAuxCell(cell, accountCode, currentAux = {}) {
    const account = state.accounts.find((value) => value.code === accountCode);
    const dimensions = Array.isArray(account?.required_aux_dimensions) ? account.required_aux_dimensions : [];
    if (!dimensions.length) {
      cell.innerHTML = '<span class="muted">无需辅助核算</span>';
      return;
    }
    cell.innerHTML = dimensions.map((dimension) => {
      const values = state.auxValues.filter((value) => value.dimension === dimension && value.enabled === true);
      return `<label class="field bookkeeping-aux-field"><span class="field__label">${app.escapeHtml(dimension)}</span><select class="input" data-aux-dimension="${app.escapeHtml(dimension)}"><option value="">请选择</option>${values.map((value) => `<option value="${app.escapeHtml(value.value_id)}" ${currentAux[dimension] === value.value_id ? "selected" : ""}>${app.escapeHtml(`${value.code || value.value_id} ${value.name}`)}</option>`).join("")}</select></label>`;
    }).join("");
  }

  function mappingAuxValuesFromForm() {
    return Object.fromEntries(
      Array.from(refs.mappingAuxFields.querySelectorAll("[data-mapping-aux-dimension]"))
        .filter((control) => control.value)
        .map((control) => [control.dataset.mappingAuxDimension, control.value]),
    );
  }

  function mappingRequiredAuxDimensions() {
    const codes = [refs.mappingDebitAccount.value, refs.mappingCreditAccount.value, refs.mappingTaxAccount.value].filter(Boolean);
    return [...new Set(codes.flatMap((code) => {
      const account = state.accounts.find((value) => value.code === code);
      return Array.isArray(account?.required_aux_dimensions) ? account.required_aux_dimensions : [];
    }))];
  }

  function renderMappingAuxFields(seed = {}, includeSeedDimensions = true) {
    const dimensions = mappingRequiredAuxDimensions();
    if (includeSeedDimensions) {
      Object.keys(seed || {}).forEach((dimension) => {
        if (!dimensions.includes(dimension)) dimensions.push(dimension);
      });
    }
    if (!dimensions.length) {
      refs.mappingAuxFields.innerHTML = '<span class="muted">当前科目无需辅助核算</span>';
      return;
    }
    refs.mappingAuxFields.innerHTML = dimensions.map((dimension) => {
      const selected = String(seed?.[dimension] || "");
      const values = state.auxValues.filter((value) => value.dimension === dimension && value.enabled === true);
      const known = values.some((value) => value.value_id === selected);
      const unknown = selected && !known ? `<option value="${app.escapeHtml(selected)}" selected>${app.escapeHtml(selected)}（当前档案不可用）</option>` : "";
      return `<label class="field"><span class="field__label">${app.escapeHtml(dimension)}</span><select class="input" data-mapping-aux-dimension="${app.escapeHtml(dimension)}"><option value="">请选择</option>${unknown}${values.map((value) => `<option value="${app.escapeHtml(value.value_id)}" ${value.value_id === selected ? "selected" : ""}>${app.escapeHtml(`${value.code || value.value_id} ${value.name}`)}</option>`).join("")}</select></label>`;
    }).join("");
  }

  function evidenceItems(snapshot, field) {
    return Array.isArray(snapshot[field]) ? snapshot[field].filter((value) => value && typeof value === "object") : [];
  }

  function evidenceRowAttrs(evidence = {}) {
    return `data-confirmed-by="${app.escapeHtml(evidence.confirmed_by || "")}" data-confirmed-at="${app.escapeHtml(evidence.confirmed_at || "")}" data-coverage-state="${app.escapeHtml(evidence.coverage_state || "full")}" data-quantity="${app.escapeHtml(evidence.quantity || "")}"`;
  }

  function taxEvidenceRow(evidence = {}, defaultSubject = "") {
    const evidenceType = evidence.evidence_type || (refs.decisionTaxTreatment.value === "non_deductible" ? "manual_confirmation" : "tax_usage_confirmation");
    return `<tr data-tax-evidence-row ${evidenceRowAttrs(evidence)}>
      <td><select class="input" data-evidence-type><option value="tax_usage_confirmation" ${evidenceType === "tax_usage_confirmation" ? "selected" : ""}>用途/勾选确认</option><option value="manual_confirmation" ${evidenceType === "manual_confirmation" ? "selected" : ""}>人工确认</option></select></td>
      <td><input class="input" data-evidence-id type="text" value="${app.escapeHtml(evidence.evidence_id || "")}"></td>
      <td><input class="input" data-evidence-subject type="text" value="${app.escapeHtml(evidence.subject_id || defaultSubject)}"></td>
      <td><input class="input" data-evidence-path type="text" value="${app.escapeHtml(evidence.source_path || "")}"></td>
      <td><input class="input" data-evidence-sha type="text" value="${app.escapeHtml(evidence.source_sha256 || "")}"></td>
      <td><input class="input" data-evidence-revision type="text" value="${app.escapeHtml(evidence.source_revision || "")}"></td>
      <td><input class="input" data-evidence-reason type="text" value="${app.escapeHtml(evidence.reason || "")}"></td>
      <td><button class="btn btn--ghost bookkeeping-icon-btn" type="button" data-remove-evidence title="删除证据" aria-label="删除税务证据">−</button></td>
    </tr>`;
  }

  function paymentEvidenceRow(evidence = {}, defaultSubject = "") {
    return `<tr data-payment-evidence-row ${evidenceRowAttrs(evidence)}>
      <td><input class="input" data-evidence-id type="text" value="${app.escapeHtml(evidence.evidence_id || "")}"></td>
      <td><input class="input" data-evidence-subject type="text" value="${app.escapeHtml(evidence.subject_id || defaultSubject)}"></td>
      <td><input class="input" data-evidence-path type="text" value="${app.escapeHtml(evidence.source_path || "")}"></td>
      <td><input class="input" data-evidence-sha type="text" value="${app.escapeHtml(evidence.source_sha256 || "")}"></td>
      <td><input class="input" data-evidence-revision type="text" value="${app.escapeHtml(evidence.source_revision || "")}"></td>
      <td><input class="input" data-evidence-amount type="text" inputmode="decimal" value="${app.escapeHtml(evidence.amount || "")}"></td>
      <td><button class="btn btn--ghost bookkeeping-icon-btn" type="button" data-remove-evidence title="删除证据" aria-label="删除付款证据">−</button></td>
    </tr>`;
  }

  function projectAuxValues() {
    return state.auxValues.filter((value) => {
      const dimension = String(value.dimension || "").trim().toLowerCase();
      return value.enabled === true && (dimension.includes("project") || dimension.includes("项目"));
    });
  }

  function projectEditor(allocation = {}, fallbackName = "") {
    const values = projectAuxValues();
    const projectName = allocation.project_name || fallbackName || "";
    if (!values.length) {
      return `<input class="input" data-project-name type="text" value="${app.escapeHtml(projectName)}" aria-label="项目名称">`;
    }
    const selected = allocation.project_id || "";
    const known = values.some((value) => value.value_id === selected);
    const unboundLabel = projectName ? `未绑定：${projectName}` : "请选择项目";
    const unknown = selected && !known
      ? `<option value="${app.escapeHtml(selected)}" selected>${app.escapeHtml(projectName || selected)}</option>`
      : "";
    return `<select class="input" data-project-id aria-label="项目档案"><option value="">${app.escapeHtml(unboundLabel)}</option>${unknown}${values.map((value) => `<option value="${app.escapeHtml(value.value_id)}" ${value.value_id === selected ? "selected" : ""}>${app.escapeHtml(`${value.code || value.value_id} ${value.name}`)}</option>`).join("")}</select>`;
  }

  function allocationRowHtml(sourceLine, allocation = {}) {
    const allocationId = allocation.allocation_id || `allocation-${commandId()}`;
    const projectName = allocation.project_name || sourceLine.project_name || "";
    return `<tr data-source-line-id="${app.escapeHtml(sourceLine.source_line_id)}" data-allocation-id="${app.escapeHtml(allocationId)}" data-project-name="${app.escapeHtml(projectName)}">
      <td>${app.escapeHtml(`${sourceLine.source_row_no} · ${sourceLine.item_name || "--"}`)}</td>
      <td>${projectEditor(allocation, sourceLine.project_name || "")}</td>
      <td><input class="input bookkeeping-amount-input" data-allocation-pretax type="text" inputmode="decimal" value="${app.escapeHtml(allocation.pretax_amount ?? sourceLine.pretax_amount ?? "0.00")}" aria-label="分配除税额"></td>
      <td><input class="input bookkeeping-amount-input" data-allocation-tax type="text" inputmode="decimal" value="${app.escapeHtml(allocation.tax_amount ?? sourceLine.tax_amount ?? "0.00")}" aria-label="分配税额"></td>
      <td><input class="input bookkeeping-amount-input" data-allocation-total type="text" inputmode="decimal" value="${app.escapeHtml(allocation.total_amount ?? sourceLine.total_amount ?? "0.00")}" aria-label="分配价税合计"></td>
      <td><div class="bookkeeping-inline-actions"><button class="btn btn--ghost bookkeeping-icon-btn" type="button" data-add-allocation title="新增项目分配" aria-label="新增项目分配">+</button><button class="btn btn--ghost bookkeeping-icon-btn" type="button" data-remove-allocation title="删除项目分配" aria-label="删除项目分配">−</button></div></td>
    </tr>`;
  }

  function renderProjectAllocations(snapshot) {
    const allocations = Array.isArray(snapshot.project_allocations) ? snapshot.project_allocations : [];
    const html = (snapshot.source_lines || []).flatMap((sourceLine) => {
      const matches = allocations.filter((value) => value.source_line_id === sourceLine.source_line_id);
      return (matches.length ? matches : [{}]).map((allocation) => allocationRowHtml(sourceLine, allocation));
    }).join("");
    refs.decisionSourceLinesBody.innerHTML = html || '<tr><td colspan="6">暂无来源行</td></tr>';
  }

  function renderReceivingEvidence(snapshot) {
    const references = evidenceItems(snapshot, "receiving_evidence_refs");
    const bySource = new Map(references.filter((value) => value.evidence_type !== "manual_confirmation").map((value) => [value.subject_id, value]));
    const manual = references.find((value) => value.evidence_type === "manual_confirmation") || {};
    refs.receivingReason.value = manual.reason || "";
    refs.decisionReceivingRowsBody.innerHTML = (snapshot.source_lines || []).map((sourceLine) => {
      const evidence = bySource.get(sourceLine.source_line_id) || {};
      const defaultType = ["project_cost", "fixed_asset_purchase"].includes(snapshot.business_class) ? "acceptance_record" : "inventory_receipt";
      const evidenceType = evidence.evidence_type || defaultType;
      const coverageState = evidence.coverage_state || (snapshot.receiving_state === "partial" ? "partial" : "full");
      return `<tr data-receiving-source-line-id="${app.escapeHtml(sourceLine.source_line_id)}" ${evidenceRowAttrs(evidence)}>
        <td>${app.escapeHtml(`${sourceLine.source_row_no} · ${sourceLine.item_name || "--"}`)}</td>
        <td><select class="input" data-receiving-type><option value="inventory_receipt" ${evidenceType === "inventory_receipt" ? "selected" : ""}>入库单</option><option value="acceptance_record" ${evidenceType === "acceptance_record" ? "selected" : ""}>验收记录</option></select></td>
        <td><select class="input" data-receiving-coverage><option value="full" ${coverageState === "full" ? "selected" : ""}>完整</option><option value="partial" ${coverageState === "partial" ? "selected" : ""}>部分</option></select></td>
        <td><input class="input" data-receiving-id type="text" value="${app.escapeHtml(evidence.evidence_id || "")}"></td>
        <td><input class="input" data-receiving-path type="text" value="${app.escapeHtml(evidence.source_path || "")}"></td>
        <td><input class="input" data-receiving-sha type="text" value="${app.escapeHtml(evidence.source_sha256 || "")}"></td>
        <td><input class="input" data-receiving-revision type="text" value="${app.escapeHtml(evidence.source_revision || "")}"></td>
      </tr>`;
    }).join("") || '<tr><td colspan="7">暂无来源行</td></tr>';
  }

  function decisionLineCandidates(snapshot) {
    const candidates = new Map();
    [...(snapshot.line_decision_templates || []), ...voucherLines(snapshot)].forEach((line) => {
      const key = String(line?.line_id || "");
      if (!key) return;
      candidates.set(key, { ...(candidates.get(key) || {}), ...line });
    });
    return [...candidates.values()];
  }

  function renderDecisionLines(snapshot) {
    const candidates = decisionLineCandidates(snapshot);
    const currentLineIds = new Set(voucherLines(snapshot).map((line) => line.line_id));
    refs.decisionLinesBody.innerHTML = candidates.map((line) => {
      const isTemplate = !currentLineIds.has(line.line_id);
      return `<tr data-line-id="${app.escapeHtml(line.line_id || "")}" data-line-template="${isTemplate ? "true" : "false"}">
      <td>${app.escapeHtml(`${line.line_role || "other"}${isTemplate ? "（科目模板）" : ""}`)}</td>
      <td>${app.escapeHtml(line.summary || "")}</td>
      <td>${app.escapeHtml(line.direction || "")}</td>
      <td class="bookkeeping-number">${amountText(line.amount)}</td>
      <td><select class="input" data-line-account>${accountOptions(line.account_code, line.line_role === "input_tax")}</select></td>
      <td data-line-aux></td>
    </tr>`;
    }).join("") || '<tr><td colspan="6">暂无分录</td></tr>';
    refs.decisionLinesBody.querySelectorAll("[data-line-id]").forEach((row) => {
      const line = candidates.find((value) => value.line_id === row.dataset.lineId) || {};
      renderAuxCell(row.querySelector("[data-line-aux]"), line.account_code || "", line.aux || {});
    });
  }

  function renderDecisionEditor(item) {
    const snapshot = snapshotOf(item);
    const invoiceNo = snapshot.source_invoice_nos?.[0] || item.posting_key;
    refs.decisionRevision.textContent = `proposal revision: ${item.proposal_revision_hash || "--"}`;
    refs.decisionBusinessClass.value = snapshot.business_class || "";
    refs.decisionPaymentState.value = snapshot.payment_state || "unknown";
    refs.decisionTaxTreatment.value = snapshot.tax_treatment || "pending";
    refs.decisionReceivingState.value = snapshot.receiving_state || "missing";
    const taxReferences = evidenceItems(snapshot, "tax_evidence_refs");
    const paymentReferences = evidenceItems(snapshot, "payment_evidence_refs");
    refs.taxEvidenceRowsBody.innerHTML = (taxReferences.length ? taxReferences : [{}]).map((value) => taxEvidenceRow(value, invoiceNo)).join("");
    refs.paymentEvidenceRowsBody.innerHTML = (paymentReferences.length ? paymentReferences : [{}]).map((value) => paymentEvidenceRow(value, invoiceNo)).join("");
    renderProjectAllocations(snapshot);
    renderReceivingEvidence(snapshot);
    renderDecisionLines(snapshot);
    const editable = editableStatuses.has(item.status);
    refs.decisionForm.querySelectorAll("input, select, button").forEach((control) => { control.disabled = !editable; });
    refs.decisionStatus.textContent = editable ? "" : `当前状态 ${item.status} 不允许修改决定。`;
    state.decisionBaseline = {
      voucherKey: item.voucher_key,
      storeRevision: item.store_revision,
      proposalRevisionHash: item.proposal_revision_hash,
    };
    state.decisionDirty = false;
  }

  function renderDetail(item, preserveEditor = false) {
    const snapshot = snapshotOf(item);
    const lines = voucherLines(snapshot);
    refs.detailPanel.hidden = false;
    refs.detailMeta.textContent = `${snapshot.voucher_date || "--"} · ${sourceInvoiceText(snapshot)} · ${lines.length} 行分录`;
    refs.balanceState.className = `status-pill status-pill--${snapshot.balance_ok === true ? "success" : "danger"}`;
    refs.balanceState.textContent = `balance_ok: ${snapshot.balance_ok === true ? "true" : "false"}`;
    refs.linesBody.innerHTML = lines.map((line) => `<tr><td>${app.escapeHtml(line.summary || "")}</td><td>${app.escapeHtml([line.account_code, line.account_name].filter(Boolean).join(" "))}</td><td>${app.escapeHtml(line.direction || "")}</td><td class="bookkeeping-number">${amountText(line.amount)}</td><td>${app.escapeHtml(Object.entries(line.aux || {}).map(([key, value]) => `${key}:${value}`).join("；") || "--")}</td></tr>`).join("") || '<tr><td colspan="5">暂无分录</td></tr>';
    refs.sourceRows.innerHTML = (snapshot.source_rows || []).map((value) => `<li>${app.escapeHtml(value)}</li>`).join("") || "<li>暂无来源行</li>";
    renderBlockers(item.blockers);
    refs.auditBody.innerHTML = (item.audit || []).map((entry) => `<tr><td>${app.escapeHtml(entry.ts || "")}</td><td>${app.escapeHtml(entry.action || "")}</td><td>${app.escapeHtml(entry.actor || "")}</td><td>${app.escapeHtml(typeof entry.detail === "object" ? JSON.stringify(entry.detail) : (entry.detail || ""))}</td></tr>`).join("") || '<tr><td colspan="4">暂无审核记录</td></tr>';
    if (!preserveEditor) renderDecisionEditor(item);
  }

  function selectVoucher(voucherKey) {
    if (state.decisionDirty && voucherKey !== state.selectedKey) {
      setBanner("warning", "当前凭证决定尚未保存。请先保存或刷新后再切换。");
      return;
    }
    const item = state.vouchers.find((candidate) => candidate.voucher_key === voucherKey);
    if (!item) return;
    state.selectedKey = voucherKey;
    state.decisionDirty = false;
    renderVouchers({ items: state.vouchers });
    refs.detailPanel.scrollIntoView({ block: "start", behavior: "smooth" });
  }

  function markDecisionDirty() {
    state.decisionDirty = true;
    updateControls();
  }

  function updateControls() {
    const available = state.bookkeeping?.available !== false;
    const busy = Boolean(state.busyAction);
    const selected = selectedItem();
    refs.generateBtn.disabled = busy || !available || state.setup?.ready_for_review !== true;
    refs.exportBtn.disabled = busy || !available || !state.exportStatus?.export_plan;
    refs.refreshBtn.disabled = busy;
    refs.copyBtn.disabled = busy || !state.vouchers.length;
    refs.saveMappingBtn.disabled = busy || !state.mappingImpact;
    refs.saveProfileBtn.disabled = busy || state.profileConflict || state.setup?.account_catalog?.exists !== true || state.setup?.aux_catalog?.exists !== true;
    refs.recomputeVoucherBtn.disabled = busy || state.decisionDirty || !selected || !recomputableStatuses.has(selected.status);
    refs.previewVoucherMigrationBtn.disabled = busy || state.setup?.migration?.migration_required !== true;
    refs.applyVoucherMigrationBtn.disabled = busy
      || state.setup?.migration?.migration_required !== true
      || state.setup?.ready_for_state_migration !== true
      || state.voucherMigrationPreview?.ok !== true
      || state.voucherMigrationPreview?.migration_required !== true
      || (state.voucherMigrationPreview?.conflicts?.length || 0) > 0;
    refs.previewMappingMigrationBtn.disabled = busy || state.setup?.mapping_migration?.migration_required !== true;
    refs.applyMappingMigrationBtn.disabled = busy
      || state.setup?.mapping_migration?.migration_required !== true
      || state.mappingMigrationPreview?.ok !== true
      || state.mappingMigrationPreview?.migration_required !== true
      || (state.mappingMigrationPreview?.conflicts?.length || 0) > 0;
    refs.table.querySelectorAll("[data-voucher-row]").forEach((row) => {
      const item = state.vouchers.find((value) => value.voucher_key === row.dataset.voucherRow);
      const dirtySelected = state.decisionDirty && row.dataset.voucherRow === state.selectedKey;
      const approve = row.querySelector('[data-review-action="approve"]');
      const reject = row.querySelector('[data-review-action="reject"]');
      if (approve) approve.disabled = busy || dirtySelected || item?.can_approve !== true;
      if (reject) reject.disabled = busy || dirtySelected || !["draft", "review_pending"].includes(item?.status);
    });
  }

  async function loadSetup() {
    try { renderSetup(await app.api("/api/v1/bookkeeping/setup")); }
    catch (error) { setBanner("danger", `读取账套设置失败：${error.message}`); }
  }

  async function loadState() {
    try { renderState(await app.api("/api/v1/bookkeeping/state")); }
    catch (error) { setBanner("danger", `读取做账状态失败：${error.message}`); }
  }

  async function loadVouchers() {
    const params = new URLSearchParams();
    if (refs.statusFilter.value) params.set("status", refs.statusFilter.value);
    if (refs.tierFilter.value) params.set("tier", refs.tierFilter.value);
    try { renderVouchers(await app.api(`/api/v1/bookkeeping/vouchers${params.size ? `?${params}` : ""}`)); }
    catch (error) {
      refs.tbody.innerHTML = `<tr><td colspan="8">读取凭证失败：${app.escapeHtml(error.message)}</td></tr>`;
      setBanner("danger", `读取凭证失败：${error.message}`);
    }
  }

  async function loadExportStatus() {
    try { renderExportStatus(await app.api("/api/v1/bookkeeping/export-status")); }
    catch (error) { refs.exportStatusPanel.textContent = `读取导出状态失败：${error.message}`; }
  }

  async function loadAccounts() {
    try {
      const currentAux = mappingAuxValuesFromForm();
      const payload = await app.api("/api/v1/bookkeeping/accounts?limit=500");
      state.accounts = Array.isArray(payload.items) ? payload.items : [];
      refs.mappingDebitAccount.innerHTML = accountOptions(refs.mappingDebitAccount.value);
      refs.mappingCreditAccount.innerHTML = accountOptions(refs.mappingCreditAccount.value);
      refs.mappingTaxAccount.innerHTML = accountOptions(refs.mappingTaxAccount.value, true);
      renderMappingAuxFields(currentAux);
    } catch (_error) {
      state.accounts = [];
      renderMappingAuxFields({});
    }
  }

  async function loadAuxValues() {
    try {
      const payload = await app.api("/api/v1/bookkeeping/aux-values?limit=500");
      state.auxValues = Array.isArray(payload.items) ? payload.items : [];
      renderMappingAuxFields(mappingAuxValuesFromForm());
    } catch (_error) {
      state.auxValues = [];
      renderMappingAuxFields(mappingAuxValuesFromForm());
    }
  }

  function renderMappings(payload) {
    state.mappings = payload;
    refs.mappingRevisionMeta.textContent = `mapping revision: ${payload?.mapping_revision || 0} · rules version: ${payload?.rules_version || "--"}`;
    const items = Array.isArray(payload?.items) ? payload.items : [];
    refs.mappingTableMeta.textContent = `${items.length} 条`;
    refs.mappingRulesBody.innerHTML = items.map((rule) => `<tr><td>${app.escapeHtml(rule.match_seller || "*")}</td><td>${app.escapeHtml(rule.match_item || "*")}</td><td>${app.escapeHtml(rule.match_internal_project || "*")}</td><td>${app.escapeHtml(`${rule.debit_account_code} ${rule.debit_account_name}`)}</td><td>${app.escapeHtml(`${rule.credit_account_code} ${rule.credit_account_name}`)}</td><td>${app.escapeHtml(rule.tax_account_code || "--")}</td><td>${app.escapeHtml(Object.entries(rule.aux_dimensions || {}).map(([key, value]) => `${key}:${value}`).join("；") || "--")}</td><td>${app.escapeHtml(rule.source || "")}</td><td>${app.escapeHtml(String(rule.priority || 0))}</td><td><button class="btn btn--ghost" type="button" data-edit-mapping-rule="${app.escapeHtml(rule.rule_id)}">编辑</button></td></tr>`).join("") || '<tr><td colspan="10">暂无映射规则</td></tr>';
  }

  function editMappingRule(ruleId) {
    const rule = state.mappings?.items?.find((value) => value.rule_id === ruleId);
    if (!rule) return;
    refs.mappingSourceType.value = rule.match_source_type || "purchase_invoice";
    refs.mappingSeller.value = rule.match_seller || "";
    refs.mappingItem.value = rule.match_item || "";
    refs.mappingProject.value = rule.match_internal_project || "";
    refs.mappingEffectiveFrom.value = rule.effective_from || "";
    refs.mappingEffectiveTo.value = rule.effective_to || "";
    refs.mappingPriority.value = String(rule.priority || 0);
    refs.mappingBusinessClass.value = rule.business_class || "";
    refs.mappingDebitAccount.value = rule.debit_account_code || "";
    refs.mappingCreditAccount.value = rule.credit_account_code || "";
    refs.mappingTaxAccount.value = rule.tax_account_code || "";
    refs.mappingReplacesRuleId.value = rule.rule_id;
    renderMappingAuxFields(rule.aux_dimensions || {});
    state.mappingImpact = null;
    refs.saveMappingBtn.disabled = true;
    refs.mappingSeller.focus();
  }

  async function loadMappings() {
    try { renderMappings(await app.api("/api/v1/bookkeeping/mapping-rules")); }
    catch (error) { refs.mappingRulesBody.innerHTML = `<tr><td colspan="10">读取映射失败：${app.escapeHtml(error.message)}</td></tr>`; }
  }

  async function refreshAll(reason = "manual") {
    await Promise.all([loadSetup(), loadState()]);
    if (!state.decisionDirty) await loadVouchers();
    await loadExportStatus();
    if (state.activeTab === "mapping") await Promise.all([loadMappings(), loadAccounts(), loadAuxValues()]);
    if (reason !== "initial" && reason !== "eventsource.open" && !state.decisionDirty && !state.profileDirty) setBanner("muted", "");
  }

  async function generateDrafts() {
    state.busyAction = "generate";
    app.setBusy(refs.generateBtn, true, "生成中");
    try {
      const payload = await app.api("/api/v1/bookkeeping/generate", { method: "POST", body: {} });
      setBanner(payload.ok === false ? "danger" : "success", payload.message || "凭证草稿已生成。");
      await refreshAll("generate");
    } catch (error) { setBanner("danger", `生成凭证草稿失败：${error.message}`); }
    finally { state.busyAction = ""; app.setBusy(refs.generateBtn, false); updateControls(); }
  }

  async function recomputeCurrentVoucher() {
    const item = selectedItem();
    if (!item || state.decisionDirty || !recomputableStatuses.has(item.status)) return;
    state.busyAction = "recompute";
    app.setBusy(refs.recomputeVoucherBtn, true, "重算中");
    try {
      const payload = await app.api("/api/v1/bookkeeping/recompute", {
        method: "POST",
        body: {
          posting_keys: [item.posting_key || item.voucher_key],
          expected_store_revision: item.store_revision,
          expected_mapping_revision: state.mappings?.mapping_revision ?? state.setup?.mapping_revision ?? 0,
          expected_profile_revision: state.setup?.profile_revision ?? 0,
          expected_profile_sha256: state.setup?.profile_sha256 || "",
          expected_account_table_sha256: state.setup?.account_catalog?.sha256 || "",
          expected_aux_catalog_sha256: state.setup?.aux_catalog?.sha256 || "",
          requested_by: localReviewerId(),
          command_id: commandId(),
          reason: "bookkeeping-review-recovery",
        },
      });
      const changed = payload.changed?.length || 0;
      setBanner(changed ? "success" : "muted", changed ? "当前凭证已重算，请重新核对决定。" : "当前凭证与来源及映射一致，无需更新。");
      await refreshAll("recompute");
    } catch (error) {
      applyErrorBlockers(error, item.voucher_key);
      setBanner("danger", `定向重算失败：${error.message}`);
    } finally {
      state.busyAction = "";
      app.setBusy(refs.recomputeVoucherBtn, false);
      updateControls();
    }
  }

  async function previewVoucherMigration() {
    state.busyAction = "voucher-migration-preview";
    app.setBusy(refs.previewVoucherMigrationBtn, true, "预览中");
    try {
      state.voucherMigrationPreview = await app.api("/api/v1/bookkeeping/migration/preview", { method: "POST", body: {} });
      renderMigrationStatus();
    } catch (error) {
      state.voucherMigrationPreview = null;
      refs.voucherMigrationStatus.textContent = `预览失败：${error.message}`;
    } finally {
      state.busyAction = "";
      app.setBusy(refs.previewVoucherMigrationBtn, false);
      updateControls();
    }
  }

  async function applyVoucherMigration() {
    const preview = state.voucherMigrationPreview;
    if (!preview || preview.ok !== true || preview.migration_required !== true) return;
    if (!window.confirm("确认按当前 SHA 执行凭证状态迁移？")) return;
    state.busyAction = "voucher-migration-apply";
    app.setBusy(refs.applyVoucherMigrationBtn, true, "迁移中");
    try {
      const payload = await app.api("/api/v1/bookkeeping/migration/apply", {
        method: "POST",
        body: {
          confirm: true,
          source_sha256: preview.source_sha256,
          preview_hash: preview.preview_hash,
          expected_store_revision: preview.source_revision,
          expected_mapping_revision: state.setup?.mapping_revision ?? 0,
          expected_rules_version: state.setup?.rules_version || "",
          expected_profile_revision: state.setup?.profile_revision ?? 0,
          expected_profile_sha256: state.setup?.profile_sha256 || "",
          expected_account_table_sha256: state.setup?.account_catalog?.sha256 || "",
          expected_aux_catalog_sha256: state.setup?.aux_catalog?.sha256 || "",
          confirmed_by: localReviewerId(),
          command_id: commandId(),
        },
      });
      state.voucherMigrationPreview = null;
      setBanner("success", `凭证状态已迁移 · revision ${payload.store_revision}`);
      await refreshAll("voucher-migration");
    } catch (error) {
      refs.voucherMigrationStatus.textContent = `迁移失败：${error.message}`;
      setBanner("danger", refs.voucherMigrationStatus.textContent);
    } finally {
      state.busyAction = "";
      app.setBusy(refs.applyVoucherMigrationBtn, false);
      updateControls();
    }
  }

  async function previewMappingMigration() {
    state.busyAction = "mapping-migration-preview";
    app.setBusy(refs.previewMappingMigrationBtn, true, "预览中");
    try {
      state.mappingMigrationPreview = await app.api("/api/v1/bookkeeping/mapping-migration/preview", { method: "POST", body: {} });
      renderMigrationStatus();
    } catch (error) {
      state.mappingMigrationPreview = null;
      refs.mappingMigrationStatus.textContent = `预览失败：${error.message}`;
    } finally {
      state.busyAction = "";
      app.setBusy(refs.previewMappingMigrationBtn, false);
      updateControls();
    }
  }

  async function applyMappingMigration() {
    const preview = state.mappingMigrationPreview;
    if (!preview || preview.ok !== true || preview.migration_required !== true) return;
    if (!window.confirm("确认按当前 SHA 和账套档案执行科目映射迁移？")) return;
    state.busyAction = "mapping-migration-apply";
    app.setBusy(refs.applyMappingMigrationBtn, true, "迁移中");
    try {
      const payload = await app.api("/api/v1/bookkeeping/mapping-migration/apply", {
        method: "POST",
        body: {
          confirm: true,
          source_sha256: preview.source_sha256,
          preview_hash: preview.preview_hash,
          expected_mapping_revision: preview.source_revision,
          expected_profile_sha256: state.setup?.profile_sha256 || "",
          expected_account_table_sha256: state.setup?.account_catalog?.sha256 || "",
          expected_aux_catalog_sha256: state.setup?.aux_catalog?.sha256 || "",
          confirmed_by: localReviewerId(),
          command_id: commandId(),
        },
      });
      state.mappingMigrationPreview = null;
      setBanner("success", `科目映射已迁移 · revision ${payload.mapping_revision}`);
      await Promise.all([refreshAll("mapping-migration"), loadMappings()]);
    } catch (error) {
      refs.mappingMigrationStatus.textContent = `迁移失败：${error.message}`;
      setBanner("danger", refs.mappingMigrationStatus.textContent);
    } finally {
      state.busyAction = "";
      app.setBusy(refs.applyMappingMigrationBtn, false);
      updateControls();
    }
  }

  function evidenceBase(type, id, subject, sourcePath, sha, revision, extra = {}) {
    return {
      evidence_id: id,
      evidence_type: type,
      subject_id: subject,
      source_path: sourcePath,
      source_sha256: sha,
      source_revision: revision,
      confirmed_by: localReviewerId(),
      confirmed_at: new Date().toISOString(),
      ...extra,
    };
  }

  function evidenceRowHasContent(row) {
    return Array.from(row.querySelectorAll("input:not([data-evidence-subject])")).some((control) => control.value.trim());
  }

  function evidenceFromRow(row, type, defaultSubject, extra = {}) {
    return evidenceBase(
      type,
      row.querySelector("[data-evidence-id]")?.value.trim() || "",
      row.querySelector("[data-evidence-subject]")?.value.trim() || defaultSubject,
      row.querySelector("[data-evidence-path]")?.value.trim() || "",
      row.querySelector("[data-evidence-sha]")?.value.trim() || "",
      row.querySelector("[data-evidence-revision]")?.value.trim() || "",
      {
        coverage_state: row.dataset.coverageState || "full",
        quantity: row.dataset.quantity || "",
        confirmed_by: row.dataset.confirmedBy || localReviewerId(),
        confirmed_at: row.dataset.confirmedAt || new Date().toISOString(),
        ...extra,
      },
    );
  }

  function collectDecisionPayload(item) {
    const snapshot = snapshotOf(item);
    const invoiceNo = snapshot.source_invoice_nos?.[0] || item.posting_key;
    const projectAllocations = Array.from(refs.decisionSourceLinesBody.querySelectorAll("[data-source-line-id]")).map((row) => {
      const projectId = row.querySelector("[data-project-id]")?.value || "";
      const project = state.auxValues.find((value) => value.value_id === projectId);
      return {
        allocation_id: row.dataset.allocationId,
        source_line_id: row.dataset.sourceLineId,
        project_id: projectId,
        project_name: row.querySelector("[data-project-name]")?.value.trim() || project?.name || row.dataset.projectName || "",
        pretax_amount: row.querySelector("[data-allocation-pretax]").value.trim(),
        tax_amount: row.querySelector("[data-allocation-tax]").value.trim(),
        total_amount: row.querySelector("[data-allocation-total]").value.trim(),
      };
    });
    const receivingState = refs.decisionReceivingState.value;
    let receivingEvidence = [];
    if (receivingState === "not_applicable") {
      receivingEvidence = [evidenceBase(
        "manual_confirmation", `receiving-na-${item.posting_key}`, item.posting_key, "", "", "",
        { coverage_state: "not_applicable", reason: refs.receivingReason.value.trim() },
      )];
    } else {
      receivingEvidence = Array.from(refs.decisionReceivingRowsBody.querySelectorAll("[data-receiving-source-line-id]"))
        .filter((row) => evidenceRowHasContent(row))
        .map((row) => evidenceBase(
          row.querySelector("[data-receiving-type]").value,
          row.querySelector("[data-receiving-id]").value.trim(),
          row.dataset.receivingSourceLineId,
          row.querySelector("[data-receiving-path]").value.trim(),
          row.querySelector("[data-receiving-sha]").value.trim(),
          row.querySelector("[data-receiving-revision]").value.trim(),
          {
            coverage_state: row.querySelector("[data-receiving-coverage]").value,
            confirmed_by: row.dataset.confirmedBy || localReviewerId(),
            confirmed_at: row.dataset.confirmedAt || new Date().toISOString(),
          },
        ));
    }
    const taxTreatment = refs.decisionTaxTreatment.value;
    const taxEvidence = Array.from(refs.taxEvidenceRowsBody.querySelectorAll("[data-tax-evidence-row]"))
      .filter((row) => evidenceRowHasContent(row))
      .map((row, index) => {
        const type = row.querySelector("[data-evidence-type]").value;
        const evidence = evidenceFromRow(
          row,
          type,
          invoiceNo,
          { reason: row.querySelector("[data-evidence-reason]").value.trim() },
        );
        if (type === "manual_confirmation" && !evidence.evidence_id) evidence.evidence_id = `tax-na-${item.posting_key}-${index + 1}`;
        return evidence;
      });
    const paymentState = refs.decisionPaymentState.value;
    const paymentEvidence = Array.from(refs.paymentEvidenceRowsBody.querySelectorAll("[data-payment-evidence-row]"))
      .filter((row) => evidenceRowHasContent(row))
      .map((row) => evidenceFromRow(
        row,
        "bank_match",
        invoiceNo,
        { amount: row.querySelector("[data-evidence-amount]").value.trim() },
      ));
    const lines = Array.from(refs.decisionLinesBody.querySelectorAll("[data-line-id]")).map((row) => ({
      line_id: row.dataset.lineId,
      account_code: row.querySelector("[data-line-account]").value,
      aux: Object.fromEntries(Array.from(row.querySelectorAll("[data-aux-dimension]")).filter((control) => control.value).map((control) => [control.dataset.auxDimension, control.value])),
    }));
    return {
      voucher_key: item.voucher_key,
      expected_store_revision: state.decisionBaseline?.storeRevision ?? item.store_revision,
      expected_proposal_revision_hash: state.decisionBaseline?.proposalRevisionHash || item.proposal_revision_hash,
      command_id: commandId(),
      decided_by: localReviewerId(),
      business_class: refs.decisionBusinessClass.value,
      payment_state: paymentState,
      payment_evidence_refs: paymentEvidence,
      tax_treatment: taxTreatment,
      tax_evidence_refs: taxEvidence,
      receiving_state: receivingState,
      receiving_evidence_refs: receivingEvidence,
      project_allocations: projectAllocations,
      lines,
    };
  }

  async function saveDecision(event) {
    event.preventDefault();
    const item = selectedItem();
    if (!item) return;
    state.busyAction = "decision";
    app.setBusy(refs.saveDecisionBtn, true, "保存中");
    refs.decisionStatus.textContent = "";
    try {
      const payload = await app.api(`/api/v1/bookkeeping/vouchers/${encodeURIComponent(item.voucher_key)}/decision`, {
        method: "PUT", body: collectDecisionPayload(item),
      });
      state.decisionDirty = false;
      refs.decisionStatus.textContent = payload.blockers?.length ? `已保存，仍有 ${payload.blockers.length} 项阻断。` : "已保存，可提交审核。";
      setBanner(payload.blockers?.length ? "warning" : "success", refs.decisionStatus.textContent);
      await Promise.all([loadState(), loadVouchers(), loadExportStatus()]);
    } catch (error) {
      applyErrorBlockers(error, item.voucher_key);
      refs.decisionStatus.textContent = `保存失败：${error.message}`;
      setBanner("danger", refs.decisionStatus.textContent);
    } finally {
      state.busyAction = "";
      app.setBusy(refs.saveDecisionBtn, false);
      updateControls();
    }
  }

  async function reviewVoucher(row, action, button) {
    const voucherKey = row?.dataset.voucherRow || "";
    const item = state.vouchers.find((candidate) => candidate.voucher_key === voucherKey);
    if (state.decisionDirty && voucherKey === state.selectedKey) {
      setBanner("warning", "当前凭证决定尚未保存，保存或刷新后才能审核。");
      refs.saveDecisionBtn.focus();
      return;
    }
    const reasonInput = row?.querySelector("[data-reject-reason]");
    const reason = (reasonInput?.value || "").trim();
    if (action === "reject" && !reason) {
      setBanner("warning", "驳回凭证必须填写原因。");
      reasonInput?.focus();
      return;
    }
    app.setBusy(button, true, action === "approve" ? "通过中" : "驳回中");
    try {
      const payload = await app.api(`/api/v1/bookkeeping/vouchers/${encodeURIComponent(voucherKey)}/review`, {
        method: "POST",
        body: {
          voucher_key: voucherKey, action, reason,
          proposal_revision_hash: item?.proposal_revision_hash || "",
          expected_store_revision: item?.store_revision,
          reviewed_by: localReviewerId(), command_id: commandId(),
        },
      });
      setBanner("success", `凭证已${action === "approve" ? "通过" : "驳回"}：${payload.voucher_key || voucherKey}`);
      state.selectedKey = voucherKey;
      state.decisionDirty = false;
      await refreshAll("review");
    } catch (error) {
      applyErrorBlockers(error, voucherKey);
      setBanner("danger", `审核凭证失败：${error.message}`);
    }
    finally { app.setBusy(button, false); updateControls(); }
  }

  async function exportImportFile() {
    state.busyAction = "export";
    app.setBusy(refs.exportBtn, true, "导出中");
    try {
      const plan = state.exportStatus?.export_plan;
      if (!plan) throw new Error("当前没有单期间且通过全部门禁的导出计划");
      const payload = await app.api("/api/v1/bookkeeping/export-import-file", {
        method: "POST", body: { ...plan, requested_by: localReviewerId(), command_id: commandId() },
      });
      setBanner("success", payload.message || "导出已完成。");
      await refreshAll("export");
      renderExportStatus(await app.api("/api/v1/bookkeeping/export-status"), payload);
    } catch (error) {
      applyErrorBlockers(error);
      setBanner("danger", `导出捷锐导入文件失败：${error.message}`);
    }
    finally { state.busyAction = ""; app.setBusy(refs.exportBtn, false); updateControls(); }
  }

  function mappingPayload() {
    return {
      expected_mapping_revision: state.mappings?.mapping_revision ?? state.setup?.mapping_revision ?? 0,
      match_source_type: refs.mappingSourceType.value,
      match_seller: refs.mappingSeller.value.trim(),
      match_item: refs.mappingItem.value.trim(),
      match_internal_project: refs.mappingProject.value.trim(),
      effective_from: refs.mappingEffectiveFrom.value,
      effective_to: refs.mappingEffectiveTo.value,
      priority: Number(refs.mappingPriority.value || 0),
      business_class: refs.mappingBusinessClass.value,
      debit_account_code: refs.mappingDebitAccount.value,
      credit_account_code: refs.mappingCreditAccount.value,
      tax_account_code: refs.mappingTaxAccount.value,
      aux_dimensions: mappingAuxValuesFromForm(),
      replaces_rule_id: refs.mappingReplacesRuleId.value.trim(),
      confirmed_by: localReviewerId(),
    };
  }

  async function previewMapping() {
    state.busyAction = "mapping-preview";
    app.setBusy(refs.previewMappingBtn, true, "预览中");
    try {
      state.mappingImpact = await app.api("/api/v1/bookkeeping/mapping-rules/preview", { method: "POST", body: mappingPayload() });
      const affected = state.mappingImpact.affected_posting_keys?.length || 0;
      const locked = state.mappingImpact.locked_posting_keys?.length || 0;
      refs.mappingImpactPanel.textContent = `影响草稿 ${affected} 张 · 锁定冲突 ${locked} 张 · impact ${state.mappingImpact.impact_hash}`;
    } catch (error) {
      state.mappingImpact = null;
      refs.mappingImpactPanel.textContent = `预览失败：${error.message}`;
    } finally {
      state.busyAction = "";
      app.setBusy(refs.previewMappingBtn, false);
      updateControls();
    }
  }

  async function saveMapping(event) {
    event.preventDefault();
    if (!state.mappingImpact) return;
    state.busyAction = "mapping-save";
    app.setBusy(refs.saveMappingBtn, true, "保存中");
    try {
      const payload = await app.api("/api/v1/bookkeeping/mapping-rules", {
        method: "POST",
        body: { ...mappingPayload(), impact_hash: state.mappingImpact.impact_hash, command_id: commandId() },
      });
      state.mappingImpact = null;
      refs.mappingImpactPanel.textContent = `规则已保存 · 重算 ${payload.recompute?.changed?.length || 0} 张 · 锁定 ${payload.recompute?.locked_conflicts?.length || 0} 张`;
      setBanner("success", "映射规则已保存，受影响草稿已定向重算。");
      await Promise.all([loadMappings(), loadSetup(), loadState(), loadVouchers()]);
    } catch (error) {
      refs.mappingImpactPanel.textContent = `保存失败：${error.message}`;
      setBanner("danger", refs.mappingImpactPanel.textContent);
    } finally {
      state.busyAction = "";
      app.setBusy(refs.saveMappingBtn, false);
      updateControls();
    }
  }

  async function saveProfile(event) {
    event.preventDefault();
    if (state.profileConflict) {
      setBanner("warning", "账套设置基线已变化，请刷新后重新确认。");
      return;
    }
    state.busyAction = "profile-save";
    app.setBusy(refs.saveProfileBtn, true, "确认中");
    const periods = refs.profileOpenPeriods.value.split(/[，,\s]+/).map((value) => value.trim()).filter(Boolean).sort();
    try {
      const payload = await app.api("/api/v1/bookkeeping/profile", {
        method: "PUT",
        body: {
          expected_profile_revision: state.profileBaseline?.profileRevision ?? 0,
          expected_account_table_sha256: state.profileBaseline?.accountSha256 || "",
          expected_aux_catalog_sha256: state.profileBaseline?.auxSha256 || "",
          company_name: refs.profileCompanyName.value.trim(),
          company_tax_id: refs.profileCompanyTaxId.value.trim(),
          ledger_environment: refs.profileEnvironment.value,
          ledger_instance_key: refs.profileInstanceKey.value.trim(),
          ledger_name: refs.profileLedgerName.value.trim(),
          identity_method: refs.profileIdentityMethod.value,
          capture_id: refs.profileCaptureId.value.trim(),
          accounting_standard: refs.profileAccountingStandard.value.trim(),
          taxpayer_profile: refs.profileTaxpayerProfile.value.trim(),
          currency: refs.profileCurrency.value.trim(),
          open_periods: periods,
          closed_through: refs.profileClosedThrough.value,
          default_voucher_type: refs.profileVoucherType.value.trim(),
          voucher_write_permission_confirmed: refs.profileWritePermission.checked,
          confirmed_by: localReviewerId(),
          command_id: commandId(),
        },
      });
      state.profileDirty = false;
      state.profileConflict = false;
      refs.profileStatus.textContent = `profile revision ${payload.profile.revision} 已确认。`;
      setBanner("success", refs.profileStatus.textContent);
      renderSetup(payload.setup);
      await loadState();
    } catch (error) {
      if (error?.payload?.error?.code === "REVISION_CONFLICT" || error?.payload?.error?.resource === "profile") {
        state.profileConflict = true;
      }
      refs.profileStatus.textContent = `确认失败：${error.message}`;
      setBanner("danger", refs.profileStatus.textContent);
    } finally {
      state.busyAction = "";
      app.setBusy(refs.saveProfileBtn, false);
      updateControls();
    }
  }

  async function copyVoucherTable() {
    try { await navigator.clipboard.writeText(app.tableToTsv(refs.table)); setBanner("success", "凭证表已复制为 TSV。"); }
    catch (error) { setBanner("danger", `复制失败：${error.message}`); }
  }

  function connectBookkeepingEvents() {
    const source = new EventSource("/api/v1/events/stream");
    let openedOnce = false;
    let sawError = false;
    app.setServiceStatus(refs.eventState, "muted", "系统服务连接状态：初始化中");
    source.onopen = () => {
      app.setServiceStatus(refs.eventState, "success", "系统服务连接状态：已连接");
      const shouldRefresh = openedOnce || sawError;
      openedOnce = true;
      sawError = false;
      if (shouldRefresh) {
        if (state.decisionDirty || state.profileDirty) setBanner("warning", "服务端已有新 revision，当前未保存内容未被覆盖。");
        refreshAll("eventsource.open");
      }
    };
    source.onerror = () => {
      sawError = true;
      app.setServiceStatus(refs.eventState, "warning", "系统服务连接状态：重连中");
    };
    [
      "bookkeeping.generated", "bookkeeping.generate_failed", "bookkeeping.decision_saved",
      "bookkeeping.reviewed", "bookkeeping.mapping_rule_added", "bookkeeping.profile_confirmed",
      "bookkeeping.recomputed", "bookkeeping.mapping_migrated", "bookkeeping.state_migrated",
      "bookkeeping.exported", "bookkeeping.batch_finalized", "settings.watch_dir_updated",
      "monitor.sync_completed", "cost_analysis.updated",
    ].forEach((name) => source.addEventListener(name, () => {
      if (state.decisionDirty || state.profileDirty) setBanner("warning", "服务端已有新 revision，当前未保存内容未被覆盖。");
      refreshAll(name);
    }));
    return source;
  }

  function bindEvents() {
    refs.tabs.forEach((button) => button.addEventListener("click", () => switchTab(button.dataset.bookkeepingTab)));
    refs.generateBtn.addEventListener("click", generateDrafts);
    refs.exportBtn.addEventListener("click", exportImportFile);
    refs.refreshBtn.addEventListener("click", () => {
      state.decisionDirty = false;
      state.profileDirty = false;
      state.profileConflict = false;
      refreshAll("manual");
    });
    refs.copyBtn.addEventListener("click", copyVoucherTable);
    refs.statusFilter.addEventListener("change", loadVouchers);
    refs.tierFilter.addEventListener("change", loadVouchers);
    refs.table.addEventListener("click", (event) => {
      const reviewButton = event.target.closest("[data-review-action]");
      if (reviewButton) return reviewVoucher(reviewButton.closest("[data-voucher-row]"), reviewButton.dataset.reviewAction, reviewButton);
      const viewButton = event.target.closest("[data-view-voucher]");
      if (viewButton) selectVoucher(viewButton.closest("[data-voucher-row]").dataset.voucherRow);
    });
    refs.decisionForm.addEventListener("submit", saveDecision);
    refs.decisionForm.addEventListener("input", markDecisionDirty);
    refs.recomputeVoucherBtn.addEventListener("click", recomputeCurrentVoucher);
    refs.decisionTaxTreatment.addEventListener("change", () => {
      const type = refs.decisionTaxTreatment.value === "non_deductible" ? "manual_confirmation" : "tax_usage_confirmation";
      refs.taxEvidenceRowsBody.querySelectorAll("[data-tax-evidence-row]").forEach((row) => {
        if (!evidenceRowHasContent(row)) row.querySelector("[data-evidence-type]").value = type;
      });
    });
    refs.addTaxEvidenceBtn.addEventListener("click", () => {
      const item = selectedItem();
      const snapshot = snapshotOf(item);
      refs.taxEvidenceRowsBody.insertAdjacentHTML("beforeend", taxEvidenceRow({}, snapshot.source_invoice_nos?.[0] || item?.posting_key || ""));
      markDecisionDirty();
    });
    refs.addPaymentEvidenceBtn.addEventListener("click", () => {
      const item = selectedItem();
      const snapshot = snapshotOf(item);
      refs.paymentEvidenceRowsBody.insertAdjacentHTML("beforeend", paymentEvidenceRow({}, snapshot.source_invoice_nos?.[0] || item?.posting_key || ""));
      markDecisionDirty();
    });
    [refs.taxEvidenceRowsBody, refs.paymentEvidenceRowsBody].forEach((body) => body.addEventListener("click", (event) => {
      const button = event.target.closest("[data-remove-evidence]");
      if (!button) return;
      button.closest("tr")?.remove();
      markDecisionDirty();
    }));
    refs.decisionSourceLinesBody.addEventListener("click", (event) => {
      const row = event.target.closest("[data-source-line-id]");
      if (!row) return;
      const sourceLine = (snapshotOf(selectedItem()).source_lines || []).find((value) => value.source_line_id === row.dataset.sourceLineId);
      if (!sourceLine) return;
      if (event.target.closest("[data-add-allocation]")) {
        const matches = Array.from(refs.decisionSourceLinesBody.querySelectorAll(`[data-source-line-id="${CSS.escape(row.dataset.sourceLineId)}"]`));
        matches.at(-1).insertAdjacentHTML("afterend", allocationRowHtml(sourceLine, { pretax_amount: "0.00", tax_amount: "0.00", total_amount: "0.00" }));
        markDecisionDirty();
        return;
      }
      if (event.target.closest("[data-remove-allocation]")) {
        const matches = refs.decisionSourceLinesBody.querySelectorAll(`[data-source-line-id="${CSS.escape(row.dataset.sourceLineId)}"]`);
        if (matches.length <= 1) {
          setBanner("warning", "每个来源行至少保留一条项目分配。");
          return;
        }
        row.remove();
        markDecisionDirty();
      }
    });
    refs.decisionSourceLinesBody.addEventListener("change", (event) => {
      const control = event.target.closest("[data-project-id]");
      if (!control) return;
      const row = control.closest("[data-source-line-id]");
      row.dataset.projectName = state.auxValues.find((value) => value.value_id === control.value)?.name || row.dataset.projectName || "";
    });
    refs.decisionLinesBody.addEventListener("change", (event) => {
      const account = event.target.closest("[data-line-account]");
      if (!account) return;
      const row = account.closest("[data-line-id]");
      renderAuxCell(row.querySelector("[data-line-aux]"), account.value, {});
      markDecisionDirty();
    });
    refs.mappingForm.addEventListener("input", () => { state.mappingImpact = null; refs.saveMappingBtn.disabled = true; });
    [refs.mappingDebitAccount, refs.mappingCreditAccount, refs.mappingTaxAccount].forEach((control) => control.addEventListener("change", () => {
      renderMappingAuxFields(mappingAuxValuesFromForm(), false);
    }));
    refs.mappingForm.addEventListener("submit", saveMapping);
    refs.previewMappingBtn.addEventListener("click", previewMapping);
    refs.mappingRulesBody.addEventListener("click", (event) => {
      const button = event.target.closest("[data-edit-mapping-rule]");
      if (button) editMappingRule(button.dataset.editMappingRule);
    });
    refs.profileForm.addEventListener("input", () => { state.profileDirty = true; updateControls(); });
    refs.profileForm.addEventListener("submit", saveProfile);
    refs.previewVoucherMigrationBtn.addEventListener("click", previewVoucherMigration);
    refs.applyVoucherMigrationBtn.addEventListener("click", applyVoucherMigration);
    refs.previewMappingMigrationBtn.addEventListener("click", previewMappingMigration);
    refs.applyMappingMigrationBtn.addEventListener("click", applyMappingMigration);
  }

  bindEvents();
  Promise.all([loadSetup(), loadState(), loadAccounts(), loadAuxValues()])
    .then(() => Promise.all([loadVouchers(), loadExportStatus(), loadMappings()]));
  connectBookkeepingEvents();
})();
