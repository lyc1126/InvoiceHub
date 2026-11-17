"""Company bank receipts: bounded read-only discovery and source-bound PNG preview jobs."""

from __future__ import annotations

import hashlib
import hmac
import json
import secrets
import threading
from collections import OrderedDict
from pathlib import Path

from invoice_hub.bank.matching import match_receipts
from invoice_hub.bank.workpaper import discover, file_sha256
from invoice_hub.services.company_bank import CachedFolderReader
from invoice_hub.services.file_preview import FilePreviewError, FilePreviewService, FilePreviewSource, PREVIEW_JOB_TTL_SECONDS


class CompanyReceiptService:
    def __init__(self, registry) -> None:
        self.registry = registry
        self.reader = CachedFolderReader(discover, (".pdf",), "银行回单")
        self.renderer = FilePreviewService()
        self._secret = secrets.token_bytes(32)
        self._lock = threading.RLock()
        self._jobs: OrderedDict[str, tuple] = OrderedDict()

    @staticmethod
    def _changed() -> FilePreviewError:
        return FilePreviewError("公司目录或回单已变化，请重新核对后查看。", code="source_changed", status_code=409)

    def _context(self, company_id: str) -> tuple[Path, list]:
        company = self.registry.get_company(company_id)["company"]
        directory = next(row for row in company["subdirs"] if row["key"] == "bank_flow_dir")
        if company["root_status"] != "present" or directory["status"] != "present":
            raise self._changed()
        root, bank = Path(company["root_path"]), Path(directory["path"])
        try:
            relative = bank.relative_to(root)
            prefixes = [root, *[root.joinpath(*relative.parts[:i]) for i in range(1, len(relative.parts) + 1)]]
            identities = []
            for path in prefixes:
                if path.is_symlink() or getattr(path, "is_junction", lambda: False)() or not path.is_dir():
                    raise self._changed()
                stat = path.stat()
                identities.append((str(path), stat.st_dev, stat.st_ino))
            return bank, identities
        except (OSError, ValueError) as exc:
            raise self._changed() from exc

    def _source(self, bank: Path, source: Path) -> tuple[Path, list]:
        try:
            relative = source.relative_to(bank)
            if source.suffix.lower() != ".pdf" or any(part in ("..", ".") for part in relative.parts):
                raise self._changed()
            signatures = []
            for i in range(1, len(relative.parts) + 1):
                path = bank.joinpath(*relative.parts[:i])
                if path.is_symlink() or getattr(path, "is_junction", lambda: False)():
                    raise self._changed()
                stat = path.stat()
                signatures.append((str(path), stat.st_dev, stat.st_ino, stat.st_size, stat.st_mtime_ns, stat.st_ctime_ns)
                                 if i == len(relative.parts) else (str(path), stat.st_dev, stat.st_ino))
            if not source.is_file():
                raise self._changed()
            return source, signatures
        except (OSError, ValueError) as exc:
            raise self._changed() from exc

    def _token(self, company_id: str, scope: list, receipt, source_signatures: list) -> str:
        raw = json.dumps([company_id, scope, receipt.receipt_id, receipt.source_sha256, receipt.page, source_signatures]).encode()
        return hmac.new(self._secret, raw, hashlib.sha256).hexdigest()

    def _read(self, company_id: str):
        bank, scope = self._context(company_id)
        read = self.reader.read(bank)
        if read.data is None:
            raise FilePreviewError("银行回单无法完整读取，未生成预览。", code="receipts_unreadable", status_code=409)
        # Discovery stores basenames. Resolve only a unique name+content hash in its own
        # source manifest; equal names in two subfolders must never select an arbitrary PDF.
        sources = {}
        for source in read.data.sources:
            if source.kind == "回单":
                sources.setdefault((source.path.name, source.sha256), []).append(source.path)
        if self._context(company_id) != (bank, scope):
            raise self._changed()
        return bank, scope, read.data, sources

    def catalog(self, company_id: str, *, start: str = "", end: str = "") -> dict:
        bank, scope, data, sources = self._read(company_id)
        matches = match_receipts([row for statement in data.statements for row in statement.rows], data.receipts)
        rows = []
        for receipt in data.receipts:
            month = receipt.txn_date.strftime("%Y-%m") if receipt.txn_date else ""
            if (start or end) and (not month or (start and month < start) or (end and month > end)):
                continue
            candidates = sources.get((receipt.source_file, receipt.source_sha256), [])
            preview = None
            if len(candidates) == 1:
                _, signatures = self._source(bank, candidates[0])
                preview = {"kind": "receipt", "company_id": company_id, "receipt_id": receipt.receipt_id,
                           "token": self._token(company_id, scope, receipt, signatures), "page": receipt.page}
            flow_ids = [f"flow:{row_id}" for row_id, receipt_id in matches.row_to_receipt.items() if receipt_id == receipt.receipt_id]
            rows.append({"id": f"receipt:{receipt.receipt_id}", "invoice_number": "", "invoice_date": receipt.txn_date.isoformat() if receipt.txn_date else "",
                         "counterpart": f"{receipt.payer.name} → {receipt.payee.name}", "amount": str(receipt.amount) if receipt.amount is not None else "",
                         "source_file": receipt.source_file, "details": receipt.purpose or receipt.title,
                         "preview": preview, "flow_ids": flow_ids,
                         "steps": [f"回单日期：{receipt.txn_date or '未识别'}；金额：{receipt.amount if receipt.amount is not None else '未识别'}",
                                   f"付款方：{receipt.payer.name or '未识别'}；收款方：{receipt.payee.name or '未识别'}",
                                   f"用途：{receipt.purpose or '未识别'}", f"来源：{receipt.source_file} 第 {receipt.page} 页",
                                   "匹配流水：" + ("、".join(flow_ids) or "未唯一匹配，不猜测对应关系。") ]})
        return {"records": rows, "issues": [{"code": item.code, "message": "银行回单存在未识别内容，请核对来源文件。"} for item in data.issues]}

    def create(self, company_id: str, payload: object) -> dict:
        if (not isinstance(payload, dict) or set(payload) != {"kind", "company_id", "receipt_id", "token", "page"}
                or payload.get("company_id") != company_id or payload.get("kind") != "receipt"
                or type(payload.get("page")) is not int):
            raise self._changed()
        with self._lock:
            bank, scope, data, sources = self._read(company_id)
            receipt = next((row for row in data.receipts if row.receipt_id == payload.get("receipt_id")), None)
            candidates = sources.get((receipt.source_file, receipt.source_sha256), []) if receipt else []
            if len(candidates) != 1:
                raise self._changed()
            source, signatures = self._source(bank, candidates[0])
            token = self._token(company_id, scope, receipt, signatures)
            if not isinstance(payload.get("token"), str) or not hmac.compare_digest(token, payload["token"]) or payload["page"] != receipt.page:
                raise self._changed()
            try:
                if file_sha256(source) != receipt.source_sha256:
                    raise self._changed()
            except OSError as exc:
                raise self._changed() from exc
            job = self.renderer.create_job([FilePreviewSource(source, source.relative_to(bank).as_posix())])
            self._jobs[job.job_id] = (company_id, scope, source, signatures)
            while len(self._jobs) > 8:
                self._jobs.popitem(last=False)
            self._validate(company_id, job.job_id)
            base = f"/api/v1/companies/{company_id}/receipt-preview-jobs/{job.job_id}"
            entry = job.files[0]
            return {"ok": True, "job_id": job.job_id, "keep_alive_url": f"{base}/keep-alive",
                    "idle_timeout_seconds": PREVIEW_JOB_TTL_SECONDS, "initial_page": receipt.page,
                    "files": [{"file_number": 1, "name": entry.display_name, "preview_type": entry.preview_type,
                               "page_count": entry.page_count, "reason": entry.reason,
                               "page_url_template": f"{base}/pages/{{page_number}}", "text_url": ""}]}

    def _validate(self, company_id: str, job_id: str) -> None:
        binding = self._jobs.get(job_id)
        if binding is None or binding[0] != company_id:
            raise FilePreviewError("回单预览已过期，请重新打开。", code="job_expired", status_code=410)
        bank, scope = self._context(company_id)
        if binding[1] != scope or self._source(bank, binding[2])[1] != binding[3]:
            raise self._changed()

    def page(self, company_id: str, job_id: str, page: int):
        with self._lock:
            self._validate(company_id, job_id)
            result = self.renderer.get_page(job_id, 1, page)
            self._validate(company_id, job_id)
            return result

    def keep_alive(self, company_id: str, job_id: str) -> dict:
        with self._lock:
            self._validate(company_id, job_id)
            self.renderer.keep_alive(job_id)
            return {"ok": True, "job_id": job_id}
