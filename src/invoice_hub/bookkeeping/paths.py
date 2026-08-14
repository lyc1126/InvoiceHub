from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from invoice_hub.targets.paths import AppConfig

VOUCHER_DIR_NAME = "凭证"
VOUCHER_IMPORT_DIR_NAME = "导入"
VOUCHER_LOG_DIR_NAME = "日志"
VOUCHER_BATCH_DIR_NAME = "批次"
ACCOUNT_MAPPING_FILE_NAME = "科目映射.json"
ACCOUNT_TABLE_FILE_NAME = "科目表.json"
LEDGER_PROFILE_FILE_NAME = "账套配置.json"
AUX_CATALOG_FILE_NAME = "辅助核算档案.json"
VOUCHER_STATUS_FILE_NAME = "凭证生成状态.json"
COMPANY_FACTS_FILE_NAME = "公司事实.json"


@dataclass(frozen=True)
class BookkeepingPaths:
    company_dir: Path
    company_facts_json: Path
    voucher_dir: Path
    import_dir: Path
    log_dir: Path
    batch_dir: Path
    account_mapping_json: Path
    account_table_json: Path
    ledger_profile_json: Path
    aux_catalog_json: Path
    voucher_status_json: Path

    def as_dict(self) -> dict[str, str]:
        return {
            "company_dir": str(self.company_dir),
            "company_facts_json": str(self.company_facts_json),
            "voucher_dir": str(self.voucher_dir),
            "import_dir": str(self.import_dir),
            "log_dir": str(self.log_dir),
            "batch_dir": str(self.batch_dir),
            "account_mapping_json": str(self.account_mapping_json),
            "account_table_json": str(self.account_table_json),
            "ledger_profile_json": str(self.ledger_profile_json),
            "aux_catalog_json": str(self.aux_catalog_json),
            "voucher_status_json": str(self.voucher_status_json),
        }


def bookkeeping_root_for(config: AppConfig) -> Path | None:
    return Path(config.bookkeeping_root) if config.bookkeeping_root else None


def company_bookkeeping_paths(company_dir: str | Path) -> BookkeepingPaths:
    company = Path(company_dir)
    voucher_dir = company / VOUCHER_DIR_NAME
    return BookkeepingPaths(
        company_dir=company,
        company_facts_json=company / COMPANY_FACTS_FILE_NAME,
        voucher_dir=voucher_dir,
        import_dir=voucher_dir / VOUCHER_IMPORT_DIR_NAME,
        log_dir=voucher_dir / VOUCHER_LOG_DIR_NAME,
        batch_dir=voucher_dir / VOUCHER_BATCH_DIR_NAME,
        account_mapping_json=voucher_dir / ACCOUNT_MAPPING_FILE_NAME,
        account_table_json=voucher_dir / ACCOUNT_TABLE_FILE_NAME,
        ledger_profile_json=voucher_dir / LEDGER_PROFILE_FILE_NAME,
        aux_catalog_json=voucher_dir / AUX_CATALOG_FILE_NAME,
        voucher_status_json=voucher_dir / VOUCHER_STATUS_FILE_NAME,
    )


def ensure_bookkeeping_layout(paths_or_company_dir: BookkeepingPaths | str | Path) -> BookkeepingPaths:
    paths = paths_or_company_dir if isinstance(paths_or_company_dir, BookkeepingPaths) else company_bookkeeping_paths(paths_or_company_dir)
    for directory in (paths.voucher_dir, paths.import_dir, paths.log_dir, paths.batch_dir):
        directory.mkdir(parents=True, exist_ok=True)
    return paths
