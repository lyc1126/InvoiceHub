from __future__ import annotations

from datetime import UTC, datetime
from decimal import Decimal
from pathlib import Path
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field


class TargetProfile(BaseModel):
    id: str
    watch_dir: str
    workspace_dir: str
    state_dir: str
    localappdata_dir: str


class RuntimePaths(BaseModel):
    root_dir: str
    runtime_dir: str
    db_path: str
    server_pid: str
    server_state: str
    server_stdout: str
    server_stderr: str
    browser_launch_log: str
    startup_preflight_log: str


class InvoiceRecord(BaseModel):
    invoice_key: str
    source_file: str
    source_path: str
    file_type: str = ""
    invoice_number: str = ""
    invoice_type: str = ""
    business_type: str = ""
    classification_status: str = "needs_review"
    classification_issue: str = ""
    invoice_date: str = ""
    seller: str = ""
    buyer: str = ""
    amount: str = ""
    pretax_amount: str = ""
    tax_rate: str = ""
    tax_amount: str = ""
    duplicate: bool = False
    duplicate_label: str = ""
    updated_at: str = ""


class CostSyncStatus(BaseModel):
    source_invoice_count: int = 0
    parsed_invoice_count: int = 0
    checked_invoice_count: int = 0
    missing_count: int = 0
    pending_count: int = 0
    not_parsed_count: int = 0
    review_count: int = 0
    sync_state: Literal["empty", "fresh", "pending", "not_generated", "needs_review"] = "empty"


class InvoiceReferenceRow(BaseModel):
    model_config = ConfigDict(populate_by_name=True)

    key: str
    invoice_code_text: str = Field(default="", alias="发票代码(**内文字)")
    internal_project_name: str = Field(default="", alias="内部项目名称")
    spec: str = Field(default="", alias="规格型号")
    unit: str = Field(default="", alias="单位")
    quantity: Decimal = Decimal("0")
    average_unit_price: Decimal = Decimal("0")
    average_unit_price_with_tax: Decimal = Decimal("0")
    purchase_reference_average_unit_price_with_tax: Decimal = Decimal("0")
    amount: Decimal = Decimal("0")
    tax_amount: Decimal = Decimal("0")
    total_with_tax: Decimal = Decimal("0")
    markup_rate: str = "8%"
    reference_markup_rate: str = "0.08"
    reference_markup_rate_percent: str = "8"
    reference_markup_locked: bool = False
    reference_average_unit_price: Decimal = Decimal("0")
    reference_average_unit_price_with_tax: Decimal = Decimal("0")
    reference_amount: Decimal = Decimal("0")
    reference_tax_amount: Decimal = Decimal("0")
    reference_total_with_tax: Decimal = Decimal("0")
    invoiced_quantity: Decimal = Decimal("0")
    uninvoiced_quantity: Decimal = Decimal("0")
    invoice_status: str = "未开具"
    invoiced_reference_amount: Decimal = Decimal("0")
    invoiced_reference_tax_amount: Decimal = Decimal("0")
    invoiced_reference_total_with_tax: Decimal = Decimal("0")
    uninvoiced_reference_amount: Decimal = Decimal("0")
    status_updated_at: str = ""


class ReferenceStatusPatch(BaseModel):
    items: list[dict[str, Any]] = Field(default_factory=list)


class CostAnalysisSnapshot(BaseModel):
    ok: bool = True
    watch_dir: str
    source_dir: str
    source_label: str = "当前发票目录"
    target_id: str
    output_detail_csv_path: str
    output_summary_xlsx_path: str
    reference_status_path: str
    reference_status_exists: bool = False
    reference_markup_rate: str = "8%"
    detail_count: int = 0
    check_count: int = 0
    mismatch_count: int = 0
    from_cache: bool = False
    items: list[dict[str, Any]] = Field(default_factory=list)
    project_summary: list[dict[str, Any]] = Field(default_factory=list)
    invoice_reference: list[dict[str, Any]] = Field(default_factory=list)
    checks: list[dict[str, Any]] = Field(default_factory=list)
    reference_status_stats: dict[str, Any] = Field(default_factory=dict)
    sync: CostSyncStatus = Field(default_factory=CostSyncStatus)


class TaskStatus(BaseModel):
    task_id: str
    task_type: str
    status: Literal["queued", "running", "success", "failed", "stopped"]
    detail: dict[str, Any] = Field(default_factory=dict)
    requested_at: str
    completed_at: str | None = None


class EventEnvelope(BaseModel):
    seq: int = 0
    event_type: str
    payload: dict[str, Any] = Field(default_factory=dict)
    error: dict[str, Any] = Field(default_factory=dict)
    task_id: str | None = None
    ts: str = ""


def utc_now_text() -> str:
    return datetime.now(UTC).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def path_text(path: str | Path) -> str:
    return str(Path(path))


class AccountMappingRule(BaseModel):
    model_config = ConfigDict(extra="forbid")

    rule_id: str
    match_seller: str
    match_source_type: str = "purchase_invoice"
    match_item: str = ""
    match_internal_project: str = ""
    effective_from: str = ""
    effective_to: str = ""
    priority: int = 0
    business_class: str = ""
    debit_account_code: str
    debit_account_name: str
    credit_account_code: str
    credit_account_name: str
    tax_account_code: str = ""
    aux_dimensions: dict[str, str] = Field(default_factory=dict)
    activation_state: Literal["pending_reconfirmation", "active", "disabled"] = "active"
    legacy_rule_ids: list[str] = Field(default_factory=list)
    source: Literal["manual", "ai_confirmed"]
    confirmed_at: str
    confirmed_by: str = ""


class VoucherLine(BaseModel):
    line_id: str = ""
    line_role: Literal["cost", "input_tax", "payable", "settlement", "other"] = "other"
    summary: str
    account_code: str
    account_name: str
    direction: Literal["debit", "credit"]
    amount: str
    aux: dict[str, str] = Field(default_factory=dict)
    source_line_ids: list[str] = Field(default_factory=list)
    allocation_ids: list[str] = Field(default_factory=list)


class VoucherSourceLine(BaseModel):
    model_config = ConfigDict(extra="forbid")

    source_line_id: str
    source_row_no: int
    source_type: str = "purchase_invoice"
    invoice_no: str
    seller: str
    item_name: str = ""
    item_key: str = ""
    project_name: str = ""
    quantity: str = ""
    pretax_amount: str
    tax_amount: str
    total_amount: str
    source_file: str = ""
    source_file_sha256: str = ""


class VoucherProjectAllocation(BaseModel):
    model_config = ConfigDict(extra="forbid")

    allocation_id: str
    source_line_id: str
    project_id: str = ""
    project_name: str
    pretax_amount: str
    tax_amount: str
    total_amount: str


class VoucherRuleResolution(BaseModel):
    model_config = ConfigDict(extra="forbid")

    source_line_id: str
    outcome: Literal["matched", "unmatched", "ambiguous"]
    rule_id: str = ""
    rule_fingerprint: str = ""
    candidate_rule_ids: list[str] = Field(default_factory=list)
    candidate_rule_fingerprints: list[str] = Field(default_factory=list)


class VoucherEvidenceReference(BaseModel):
    model_config = ConfigDict(extra="forbid")

    evidence_id: str
    evidence_type: Literal[
        "tax_usage_confirmation",
        "bank_match",
        "inventory_receipt",
        "acceptance_record",
        "manual_confirmation",
    ]
    subject_id: str
    source_path: str = ""
    source_sha256: str = ""
    source_revision: str = ""
    amount: str = ""
    quantity: str = ""
    coverage_state: Literal["full", "partial", "not_applicable"] = "full"
    confirmed_by: str
    confirmed_at: str
    reason: str = ""


class VoucherLineDecision(BaseModel):
    model_config = ConfigDict(extra="forbid")

    line_id: str
    account_code: str
    aux: dict[str, str] = Field(default_factory=dict)
    line_role: Literal["cost", "input_tax", "payable", "settlement", "other"] = "other"
    summary: str = ""
    direction: Literal["debit", "credit", ""] = ""
    amount: str = ""
    source_line_ids: list[str] = Field(default_factory=list)
    allocation_ids: list[str] = Field(default_factory=list)


class VoucherDecisionPatch(BaseModel):
    model_config = ConfigDict(extra="forbid")

    voucher_key: str
    expected_store_revision: int
    expected_proposal_revision_hash: str
    command_id: str
    decided_by: str
    business_class: Literal[
        "inventory_purchase",
        "raw_material_purchase",
        "project_cost",
        "period_expense",
        "fixed_asset_purchase",
    ]
    payment_state: Literal["unknown", "unmatched", "partial", "matched"]
    payment_evidence_refs: list[VoucherEvidenceReference] = Field(default_factory=list)
    tax_treatment: Literal["deductible", "non_deductible", "pending"]
    tax_evidence_refs: list[VoucherEvidenceReference] = Field(default_factory=list)
    receiving_state: Literal["missing", "partial", "full", "not_applicable"]
    receiving_evidence_refs: list[VoucherEvidenceReference] = Field(default_factory=list)
    project_allocations: list[VoucherProjectAllocation] = Field(default_factory=list)
    lines: list[VoucherLineDecision] = Field(default_factory=list)


class VoucherDraft(BaseModel):
    voucher_key: str
    voucher_date: str
    voucher_type: str = "记"
    lines: list[VoucherLine]
    source_invoice_nos: list[str]
    source_rows: list[str]
    balance_ok: bool
    review_tier: Literal["auto", "ai_suggested", "forced_manual", "manual_confirmed"]
    generated_at: str
    posting_key: str = ""
    legacy_key: str = ""
    proposal_revision_hash: str = ""
    company_id: str = ""
    ledger_environment: Literal["production", "test", ""] = ""
    ledger_identity_sha256: str = ""
    ledger_profile_revision: int = 0
    ledger_profile_sha256: str = ""
    event_type: str = "purchase_recognition"
    source_type: str = "purchase_invoice"
    period: str = ""
    anchor_business_key: str = ""
    key_strength: Literal["strong", "weak"] = "strong"
    source_file_hashes: dict[str, str] = Field(default_factory=dict)
    source_lines: list[VoucherSourceLine] = Field(default_factory=list)
    counterparty_id: str = ""
    counterparty_name: str = ""
    business_class: str = ""
    payment_state: str = "unknown"
    payment_evidence_refs: list[VoucherEvidenceReference | str] = Field(default_factory=list)
    tax_treatment: Literal["deductible", "non_deductible", "pending"] = "pending"
    tax_evidence_refs: list[VoucherEvidenceReference | str] = Field(default_factory=list)
    receiving_state: Literal["missing", "partial", "full", "not_applicable"] = "missing"
    receiving_evidence_refs: list[VoucherEvidenceReference | str] = Field(default_factory=list)
    project_allocations: list[VoucherProjectAllocation] = Field(default_factory=list)
    line_decision_templates: list[VoucherLineDecision] = Field(default_factory=list)
    decision_confirmed_by: str = ""
    decision_confirmed_at: str = ""
    proposal_hash_version: int = 2
    rule_ids: list[str] = Field(default_factory=list)
    rule_fingerprints: list[str] = Field(default_factory=list)
    rules_version: str = ""
    rule_resolutions: list[VoucherRuleResolution] = Field(default_factory=list)
    mapping_resolution_sha256: str = ""
    account_table_sha256: str = ""
    aux_catalog_sha256: str = ""
    suggestion_source: Literal["deterministic", "ai", "manual"] = "deterministic"
    execution_readiness: Literal["ready", "needs_review", "blocked"] = "needs_review"
    blockers: list[dict[str, Any]] = Field(default_factory=list)


class VoucherStatusItem(BaseModel):
    status: Literal[
        "draft",
        "blocked",
        "review_pending",
        "approved",
        "rejected",
        "exported",
        "importing",
        "imported",
        "import_failed",
        "import_failed_confirmed",
        "import_unknown",
        "reconciled",
        "manual_entry",
    ]
    snapshot: dict[str, Any]
    voucher_no: str = ""
    approved_at: str = ""
    approved_by: str = ""
    approved_revision_hash: str = ""
    imported_at: str = ""
    reject_reason: str = ""
    export_file: str = ""
    batch_id: str = ""
    item_revision: int = 0
    legacy_keys: list[str] = Field(default_factory=list)
    last_observation_hash: str = ""
    audit: list[dict[str, Any]] = Field(default_factory=list)


class VoucherReviewPatch(BaseModel):
    voucher_key: str
    action: Literal["approve", "reject"]
    reason: str = ""
    proposal_revision_hash: str = ""
    expected_store_revision: int | None = None
    reviewed_by: str = ""
    command_id: str = ""


class CompanyFacts(BaseModel):
    model_config = ConfigDict(extra="forbid")

    schema_version: Literal[1] = 1
    revision: int = Field(default=1, ge=1)
    company_id: str
    company_name: str
    company_tax_id: str
    confirmed_by: str
    confirmed_at: str


class AccountCatalogRecord(BaseModel):
    model_config = ConfigDict(extra="forbid")

    code: str
    name: str
    enabled: bool
    is_leaf: bool
    balance_direction: Literal["debit", "credit"]
    required_aux_dimensions: list[str]
    quantity_enabled: bool
    foreign_currency_enabled: bool


class AccountCatalogEnvelope(BaseModel):
    model_config = ConfigDict(extra="forbid")

    schema_version: Literal[2] = 2
    catalog_kind: Literal["accounts"] = "accounts"
    company_id: str
    ledger_environment: Literal["production", "test"]
    ledger_identity_sha256: str
    capture_id: str
    captured_at: str
    captured_by: str
    content_sha256: str
    records: list[AccountCatalogRecord]


class AuxiliaryCatalogRecord(BaseModel):
    model_config = ConfigDict(extra="forbid")

    dimension: str
    value_id: str
    code: str = ""
    name: str
    enabled: bool


class AuxiliaryCatalogEnvelope(BaseModel):
    model_config = ConfigDict(extra="forbid")

    schema_version: Literal[2] = 2
    catalog_kind: Literal["auxiliary"] = "auxiliary"
    company_id: str
    ledger_environment: Literal["production", "test"]
    ledger_identity_sha256: str
    capture_id: str
    captured_at: str
    captured_by: str
    content_sha256: str
    records: list[AuxiliaryCatalogRecord]


class CompanyLedgerProfile(BaseModel):
    model_config = ConfigDict(extra="forbid")

    schema_version: Literal[2] = 2
    revision: int = Field(default=1, ge=1)
    company_id: str
    company_name: str
    company_tax_id: str = ""
    ledger_environment: Literal["production", "test"]
    ledger_provider: Literal["jierui"] = "jierui"
    ledger_instance_key: str
    ledger_name: str
    identity_method: Literal["native_id", "confirmed_composite"]
    ledger_identity_sha256: str
    capture_id: str
    accounting_standard: str
    taxpayer_profile: str
    currency: str = "CNY"
    open_periods: list[str] = Field(default_factory=list)
    closed_through: str = ""
    default_voucher_type: str = "记"
    voucher_write_permission_confirmed: bool = False
    account_table_sha256: str
    aux_catalog_sha256: str = ""
    confirmed_by: str
    confirmed_at: str


class ValidationBlocker(BaseModel):
    code: str
    message: str
    scope: Literal["voucher", "line", "source", "profile", "batch", "facts", "mapping", "evidence"] = "voucher"
    field: str = ""
    line_index: int | None = None
    remediation: str = ""
    detail: dict[str, Any] = Field(default_factory=dict)


class ImportBatchItem(BaseModel):
    posting_key: str
    proposal_revision_hash: str
    export_row_no: int
    export_row_end: int
    planned_voucher_no: str
    signature_hash: str


class ImportBatch(BaseModel):
    schema_version: int = 1
    revision: int = 1
    batch_id: str
    company_id: str
    ledger_environment: Literal["production", "test", ""] = ""
    ledger_identity_sha256: str = ""
    ledger_profile_sha256: str = ""
    ledger_name: str
    period: str
    template_facts_version: str
    template_facts_sha256: str
    account_table_sha256: str = ""
    aux_catalog_sha256: str = ""
    file_path: str
    file_sha256: str
    manifest_path: str
    items: list[ImportBatchItem]
    expected_count: int
    expected_debit_total: str
    expected_credit_total: str
    baseline: dict[str, Any] = Field(default_factory=dict)
    state: Literal[
        "prepared",
        "dry_run_passed",
        "awaiting_authorization",
        "applying",
        "observed",
        "reconciled",
        "failed_before_commit",
        "partial",
        "unknown",
    ] = "prepared"
    created_at: str = ""
    dry_run_at: str = ""
    authorized_at: str = ""
    finalized_at: str = ""
    authorization_hash: str = ""
    observation_hash: str = ""
    finalize_result: dict[str, Any] = Field(default_factory=dict)
    observation_receipts: dict[str, dict[str, Any]] = Field(default_factory=dict)
    audit: list[dict[str, Any]] = Field(default_factory=list)
