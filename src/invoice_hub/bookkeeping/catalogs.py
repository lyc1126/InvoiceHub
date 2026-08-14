from __future__ import annotations

import hashlib
import json
import re
import unicodedata
from dataclasses import dataclass
from pathlib import Path
from types import MappingProxyType
from typing import Any, Mapping

from pydantic import BaseModel

from invoice_hub.bookkeeping.repository import (
    BookkeepingRevisionConflict,
    atomic_write_json_durable,
    bookkeeping_write_lock,
    canonical_sha256,
    file_sha256,
    raise_bookkeeping_state_corruption,
)
from invoice_hub.domain.models import (
    AccountCatalogEnvelope,
    AccountCatalogRecord,
    AuxiliaryCatalogEnvelope,
    AuxiliaryCatalogRecord,
    CompanyFacts,
    CompanyLedgerProfile,
)


_SHA256_RE = re.compile(r"^[0-9a-f]{64}$")
_PERIOD_RE = re.compile(r"^\d{4}-(0[1-9]|1[0-2])$")


@dataclass(frozen=True)
class LedgerCatalogSnapshot:
    profile: CompanyLedgerProfile
    account_catalog: AccountCatalogEnvelope
    auxiliary_catalog: AuxiliaryCatalogEnvelope
    profile_file_sha256: str
    account_file_sha256: str
    auxiliary_file_sha256: str
    accounts_by_code: Mapping[str, AccountCatalogRecord]
    auxiliary_by_value_id: Mapping[str, AuxiliaryCatalogRecord]
    auxiliary_by_dimension_and_code: Mapping[tuple[str, str], AuxiliaryCatalogRecord]

    @property
    def ledger_profile_sha256(self) -> str:
        return self.profile_file_sha256

    @property
    def account_table_sha256(self) -> str:
        return self.account_file_sha256

    @property
    def aux_catalog_sha256(self) -> str:
        return self.auxiliary_file_sha256

    @property
    def aux_by_value_id(self) -> Mapping[str, AuxiliaryCatalogRecord]:
        return self.auxiliary_by_value_id


def _canonical_text(value: object) -> str:
    return " ".join(unicodedata.normalize("NFKC", str(value or "")).split())


def _payload(value: BaseModel | Mapping[str, Any]) -> dict[str, Any]:
    if isinstance(value, BaseModel):
        return value.model_dump(mode="json")
    return dict(value)


def canonical_ledger_identity(value: CompanyLedgerProfile | Mapping[str, Any]) -> str:
    payload = _payload(value)
    identity_method = _canonical_text(payload.get("identity_method"))
    stable: dict[str, Any] = {
        "identity_schema": 1,
        "company_id": _canonical_text(payload.get("company_id")),
        "ledger_environment": _canonical_text(payload.get("ledger_environment")),
        "ledger_provider": _canonical_text(payload.get("ledger_provider")),
        "identity_method": identity_method,
        "ledger_instance_key": _canonical_text(payload.get("ledger_instance_key")),
    }
    if identity_method == "confirmed_composite":
        stable["company_tax_id"] = _canonical_text(payload.get("company_tax_id"))
        stable["ledger_name"] = _canonical_text(payload.get("ledger_name"))
        stable["accounting_standard"] = _canonical_text(payload.get("accounting_standard"))
        stable["currency"] = _canonical_text(payload.get("currency")).upper()
    elif identity_method != "native_id":
        raise ValueError(f"unsupported ledger identity method: {identity_method or '<empty>'}")
    return canonical_sha256(stable)


def canonical_profile_sha256(profile: CompanyLedgerProfile | Mapping[str, Any]) -> str:
    return canonical_sha256(_payload(profile))


def _read_json_object_with_sha(path: Path) -> tuple[dict[str, Any], str]:
    path = Path(path)
    if not path.is_file():
        raise FileNotFoundError(f"required bookkeeping catalog file does not exist: {path}")
    try:
        raw = path.read_bytes()
        payload = json.loads(raw.decode("utf-8-sig"))
        if not isinstance(payload, dict):
            raise TypeError("root node must be an object")
    except Exception as exc:
        raise_bookkeeping_state_corruption(
            path,
            exc,
            error="bookkeeping_catalog_json_invalid",
            message="做账档案 JSON 损坏，已停止写入",
        )
    return payload, hashlib.sha256(raw).hexdigest()


def _schema_error(path: Path, exc: Exception, *, kind: str) -> None:
    raise_bookkeeping_state_corruption(
        path,
        exc,
        error=f"bookkeeping_{kind}_schema_invalid",
        message=f"做账{kind}档案结构损坏，已停止写入",
    )


def _require_text(value: object, field: str) -> str:
    text = str(value or "")
    if not text.strip():
        raise ValueError(f"{field} must not be empty")
    if text != text.strip():
        raise ValueError(f"{field} must not contain leading or trailing whitespace")
    return text


def _require_sha256(value: object, field: str) -> str:
    text = str(value or "")
    if not _SHA256_RE.fullmatch(text):
        raise ValueError(f"{field} must be a lowercase SHA-256 hex digest")
    return text


def _validate_company_facts(facts: CompanyFacts) -> None:
    for field in ("company_id", "company_name", "company_tax_id", "confirmed_by", "confirmed_at"):
        _require_text(getattr(facts, field), field)


def _validate_profile(profile: CompanyLedgerProfile) -> None:
    for field in (
        "company_id",
        "company_name",
        "company_tax_id",
        "ledger_provider",
        "ledger_instance_key",
        "ledger_name",
        "capture_id",
        "accounting_standard",
        "taxpayer_profile",
        "currency",
        "default_voucher_type",
        "confirmed_by",
        "confirmed_at",
    ):
        _require_text(getattr(profile, field), field)
    _require_sha256(profile.ledger_identity_sha256, "ledger_identity_sha256")
    _require_sha256(profile.account_table_sha256, "account_table_sha256")
    _require_sha256(profile.aux_catalog_sha256, "aux_catalog_sha256")
    if profile.ledger_identity_sha256 != canonical_ledger_identity(profile):
        raise ValueError("ledger_identity_sha256 does not match the canonical ledger identity")
    if len(set(profile.open_periods)) != len(profile.open_periods):
        raise ValueError("open_periods must not contain duplicates")
    if profile.open_periods != sorted(profile.open_periods):
        raise ValueError("open_periods must be sorted")
    for period in profile.open_periods:
        if not _PERIOD_RE.fullmatch(period):
            raise ValueError(f"invalid open period: {period}")
    if profile.closed_through and not _PERIOD_RE.fullmatch(profile.closed_through):
        raise ValueError(f"invalid closed_through period: {profile.closed_through}")
    if profile.closed_through and any(period <= profile.closed_through for period in profile.open_periods):
        raise ValueError("open_periods cannot include a period at or before closed_through")


def _validate_envelope_identity(envelope: AccountCatalogEnvelope | AuxiliaryCatalogEnvelope) -> None:
    for field in ("company_id", "capture_id", "captured_at", "captured_by"):
        _require_text(getattr(envelope, field), field)
    _require_sha256(envelope.ledger_identity_sha256, "ledger_identity_sha256")
    _require_sha256(envelope.content_sha256, "content_sha256")


def _validate_account_catalog(catalog: AccountCatalogEnvelope) -> dict[str, AccountCatalogRecord]:
    _validate_envelope_identity(catalog)
    by_code: dict[str, AccountCatalogRecord] = {}
    for record in catalog.records:
        code = _require_text(record.code, "records[].code")
        _require_text(record.name, f"account {code} name")
        if code in by_code:
            raise ValueError(f"duplicate account code: {code}")
        if len(set(record.required_aux_dimensions)) != len(record.required_aux_dimensions):
            raise ValueError(f"account {code} contains duplicate required auxiliary dimensions")
        for dimension in record.required_aux_dimensions:
            _require_text(dimension, f"account {code} required auxiliary dimension")
        by_code[code] = record
    return by_code


def _validate_auxiliary_catalog(
    catalog: AuxiliaryCatalogEnvelope,
) -> tuple[dict[str, AuxiliaryCatalogRecord], dict[tuple[str, str], AuxiliaryCatalogRecord]]:
    _validate_envelope_identity(catalog)
    by_value_id: dict[str, AuxiliaryCatalogRecord] = {}
    by_dimension_and_code: dict[tuple[str, str], AuxiliaryCatalogRecord] = {}
    for record in catalog.records:
        dimension = _require_text(record.dimension, "records[].dimension")
        value_id = _require_text(record.value_id, f"auxiliary {dimension} value_id")
        _require_text(record.name, f"auxiliary {value_id} name")
        if value_id in by_value_id:
            raise ValueError(f"duplicate auxiliary value_id: {value_id}")
        by_value_id[value_id] = record
        if record.code:
            code = _require_text(record.code, f"auxiliary {value_id} code")
            key = (dimension, code)
            if key in by_dimension_and_code:
                raise ValueError(f"duplicate auxiliary code in dimension {dimension}: {code}")
            by_dimension_and_code[key] = record
    return by_value_id, by_dimension_and_code


def _parse_company_facts(path: Path) -> tuple[CompanyFacts, str]:
    payload, digest = _read_json_object_with_sha(path)
    try:
        facts = CompanyFacts.model_validate(payload, strict=True)
        _validate_company_facts(facts)
    except Exception as exc:
        _schema_error(path, exc, kind="company_facts")
    return facts, digest


def _parse_ledger_profile(path: Path) -> tuple[CompanyLedgerProfile, str]:
    payload, digest = _read_json_object_with_sha(path)
    try:
        profile = CompanyLedgerProfile.model_validate(payload, strict=True)
        _validate_profile(profile)
    except Exception as exc:
        _schema_error(path, exc, kind="ledger_profile")
    return profile, digest


def _parse_account_catalog(path: Path) -> tuple[AccountCatalogEnvelope, str, dict[str, AccountCatalogRecord]]:
    payload, digest = _read_json_object_with_sha(path)
    try:
        raw_records = payload.get("records")
        if not isinstance(raw_records, list):
            raise TypeError("records must be an array")
        if payload.get("content_sha256") != canonical_sha256(raw_records):
            raise ValueError("account catalog content_sha256 mismatch")
        catalog = AccountCatalogEnvelope.model_validate(payload, strict=True)
        by_code = _validate_account_catalog(catalog)
    except Exception as exc:
        _schema_error(path, exc, kind="account_catalog")
    return catalog, digest, by_code


def _parse_auxiliary_catalog(
    path: Path,
) -> tuple[
    AuxiliaryCatalogEnvelope,
    str,
    dict[str, AuxiliaryCatalogRecord],
    dict[tuple[str, str], AuxiliaryCatalogRecord],
]:
    payload, digest = _read_json_object_with_sha(path)
    try:
        raw_records = payload.get("records")
        if not isinstance(raw_records, list):
            raise TypeError("records must be an array")
        if payload.get("content_sha256") != canonical_sha256(raw_records):
            raise ValueError("auxiliary catalog content_sha256 mismatch")
        catalog = AuxiliaryCatalogEnvelope.model_validate(payload, strict=True)
        by_value_id, by_dimension_and_code = _validate_auxiliary_catalog(catalog)
    except Exception as exc:
        _schema_error(path, exc, kind="auxiliary_catalog")
    return catalog, digest, by_value_id, by_dimension_and_code


def load_company_facts(path: Path) -> CompanyFacts:
    return _parse_company_facts(Path(path))[0]


def load_ledger_profile(path: Path) -> CompanyLedgerProfile:
    return _parse_ledger_profile(Path(path))[0]


def load_account_catalog(path: Path) -> AccountCatalogEnvelope:
    return _parse_account_catalog(Path(path))[0]


def load_auxiliary_catalog(path: Path) -> AuxiliaryCatalogEnvelope:
    return _parse_auxiliary_catalog(Path(path))[0]


def load_aux_catalog(path: Path) -> AuxiliaryCatalogEnvelope:
    return load_auxiliary_catalog(path)


def validate_profile_catalog_binding(
    profile: CompanyLedgerProfile,
    account_catalog: AccountCatalogEnvelope,
    auxiliary_catalog: AuxiliaryCatalogEnvelope,
    *,
    company_facts: CompanyFacts | None = None,
    account_file_sha256: str | None = None,
    auxiliary_file_sha256: str | None = None,
) -> None:
    expected = (
        profile.company_id,
        profile.ledger_environment,
        profile.ledger_identity_sha256,
        profile.capture_id,
    )
    for kind, catalog in (("account", account_catalog), ("auxiliary", auxiliary_catalog)):
        actual = (
            catalog.company_id,
            catalog.ledger_environment,
            catalog.ledger_identity_sha256,
            catalog.capture_id,
        )
        if actual != expected:
            raise ValueError(
                f"{kind} catalog identity mismatch: expected company/environment/ledger/capture {expected!r}, got {actual!r}"
            )
    if account_file_sha256 is not None and profile.account_table_sha256 != account_file_sha256:
        raise ValueError("profile account_table_sha256 does not match the account catalog file")
    if auxiliary_file_sha256 is not None and profile.aux_catalog_sha256 != auxiliary_file_sha256:
        raise ValueError("profile aux_catalog_sha256 does not match the auxiliary catalog file")
    if company_facts is not None:
        _validate_company_facts(company_facts)
        facts_identity = (company_facts.company_id, company_facts.company_name, company_facts.company_tax_id)
        profile_identity = (profile.company_id, profile.company_name, profile.company_tax_id)
        if facts_identity != profile_identity:
            raise ValueError(f"company facts mismatch: expected {facts_identity!r}, got profile {profile_identity!r}")


def load_bookkeeping_catalogs(
    profile_path: Path,
    account_catalog_path: Path,
    auxiliary_catalog_path: Path,
    *,
    company_facts_path: Path | None = None,
) -> LedgerCatalogSnapshot:
    profile_path = Path(profile_path)
    account_catalog_path = Path(account_catalog_path)
    auxiliary_catalog_path = Path(auxiliary_catalog_path)
    profile, profile_sha = _parse_ledger_profile(profile_path)
    account_catalog, account_sha, accounts_by_code = _parse_account_catalog(account_catalog_path)
    auxiliary_catalog, auxiliary_sha, aux_by_value_id, aux_by_dimension_and_code = _parse_auxiliary_catalog(
        auxiliary_catalog_path
    )
    company_facts = load_company_facts(Path(company_facts_path)) if company_facts_path is not None else None
    validate_profile_catalog_binding(
        profile,
        account_catalog,
        auxiliary_catalog,
        company_facts=company_facts,
        account_file_sha256=account_sha,
        auxiliary_file_sha256=auxiliary_sha,
    )
    observed = (profile_sha, account_sha, auxiliary_sha)
    current = (file_sha256(profile_path), file_sha256(account_catalog_path), file_sha256(auxiliary_catalog_path))
    if current != observed:
        raise RuntimeError("bookkeeping profile or catalog changed while the snapshot was being loaded")
    return LedgerCatalogSnapshot(
        profile=profile,
        account_catalog=account_catalog,
        auxiliary_catalog=auxiliary_catalog,
        profile_file_sha256=profile_sha,
        account_file_sha256=account_sha,
        auxiliary_file_sha256=auxiliary_sha,
        accounts_by_code=MappingProxyType(accounts_by_code),
        auxiliary_by_value_id=MappingProxyType(aux_by_value_id),
        auxiliary_by_dimension_and_code=MappingProxyType(aux_by_dimension_and_code),
    )


def _revision_conflict(expected: int, current: int) -> BookkeepingRevisionConflict:
    try:
        return BookkeepingRevisionConflict(expected, current, resource="profile")  # type: ignore[call-arg]
    except TypeError:
        try:
            return BookkeepingRevisionConflict(expected, current, "profile")  # type: ignore[call-arg]
        except TypeError:
            conflict = BookkeepingRevisionConflict(expected, current)
            conflict.resource = "profile"  # type: ignore[attr-defined]
            return conflict


def write_ledger_profile(
    path: Path,
    profile: CompanyLedgerProfile | Mapping[str, Any],
    account_catalog_path: Path,
    auxiliary_catalog_path: Path,
    *,
    expected_revision: int,
    company_facts: CompanyFacts | None = None,
    company_facts_path: Path | None = None,
) -> CompanyLedgerProfile:
    path = Path(path)
    if company_facts is not None and company_facts_path is not None:
        raise ValueError("provide company_facts or company_facts_path, not both")
    with bookkeeping_write_lock(path.parent):
        current_revision = load_ledger_profile(path).revision if path.exists() else 0
        if current_revision != expected_revision:
            raise _revision_conflict(expected_revision, current_revision)
        account_catalog, account_sha, _ = _parse_account_catalog(Path(account_catalog_path))
        auxiliary_catalog, auxiliary_sha, _, _ = _parse_auxiliary_catalog(Path(auxiliary_catalog_path))
        resolved_facts = company_facts
        if company_facts_path is not None:
            resolved_facts = load_company_facts(Path(company_facts_path))

        data = _payload(profile)
        data.update(
            {
                "schema_version": 2,
                "revision": current_revision + 1,
                "ledger_identity_sha256": canonical_ledger_identity(data),
                "account_table_sha256": account_sha,
                "aux_catalog_sha256": auxiliary_sha,
            }
        )
        prepared = CompanyLedgerProfile.model_validate(data, strict=True)
        _validate_profile(prepared)
        validate_profile_catalog_binding(
            prepared,
            account_catalog,
            auxiliary_catalog,
            company_facts=resolved_facts,
            account_file_sha256=account_sha,
            auxiliary_file_sha256=auxiliary_sha,
        )
        if (
            file_sha256(Path(account_catalog_path)) != account_sha
            or file_sha256(Path(auxiliary_catalog_path)) != auxiliary_sha
        ):
            raise RuntimeError("bookkeeping catalog changed while the profile was being prepared")
        atomic_write_json_durable(path, prepared.model_dump(mode="json"))
        return prepared
