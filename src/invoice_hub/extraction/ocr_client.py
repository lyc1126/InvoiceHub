"""PaddleOCR official API and self-hosted HTTP client, content-hash cache, and invoice field validation.

Core packaging ships no local heavy OCR engine. Users explicitly opt in to either:
- `paddle_api`: PaddleOCR official online HTTP API (requires user Access Token + explicit cloud consent)
- `paddle_self_hosted`: User-operated PaddleOCR HTTP service (local or LAN URL)

Tokens and raw image bytes must never appear in exceptions, logs, or diagnostic payloads.
"""
from __future__ import annotations

import base64
from collections.abc import Callable, Iterator
from contextlib import contextmanager
from dataclasses import dataclass
from decimal import Decimal, InvalidOperation
import hashlib
import json
from pathlib import Path
import re
import socket
import sqlite3
import time
from typing import Any
from urllib.error import HTTPError, URLError
from urllib.parse import urlparse
from urllib.request import Request, urlopen

from invoice_hub.domain.models import utc_now_text
from invoice_hub.extraction.parsers import _record_from_text, is_valid_money

DEFAULT_PADDLE_API_URL = "https://paddleocr.aistudio-app.com/ocr"
VALID_PROVIDER_MODES = ("disabled", "paddle_api", "paddle_self_hosted")
MAX_OCR_IMAGE_BYTES = 20 * 1024 * 1024
MAX_OCR_RESPONSE_BYTES = 8 * 1024 * 1024
DEFAULT_OCR_TIMEOUT_SECONDS = 30
MIN_OCR_TIMEOUT_SECONDS = 3
MAX_OCR_TIMEOUT_SECONDS = 120
DEFAULT_OCR_CACHE_MAX_ROWS = 5000

_LEGAL_TAX_RATES = {
    "0%", "1%", "1.5%", "3%", "5%", "6%", "9%", "10%", "11%", "13%", "16%", "17%",
    "免税", "不征税", "***", "*",
}
_INVOICE_NUMBER_RE = re.compile(r"^\d{8}$|^\d{20}$")


class OcrError(RuntimeError):
    """Structured, credential-safe OCR error."""

    def __init__(self, code: str, message: str, *, status_code: int = 400) -> None:
        super().__init__(message)
        self.code = code
        self.message = message
        self.status_code = status_code


@dataclass(frozen=True)
class OcrRecognitionResult:
    provider: str
    model_version: str
    text: str
    lines: list[dict[str, Any]]
    confidence: float | None
    from_cache: bool
    file_sha256: str


def validate_endpoint_url(url: str, *, allow_empty: bool = False) -> str:
    cleaned = str(url or "").strip()
    if not cleaned:
        if allow_empty:
            return ""
        raise OcrError("invalid_endpoint", "请填写有效的 OCR 服务地址（http:// 或 https://）。")
    if len(cleaned) > 1024 or any(ord(ch) < 32 for ch in cleaned):
        raise OcrError("invalid_endpoint", "OCR 服务地址包含非法字符或过长。")
    parsed = urlparse(cleaned)
    if parsed.scheme not in {"http", "https"} or not parsed.hostname:
        raise OcrError("invalid_endpoint", "OCR 服务地址仅支持 http:// 或 https:// 且必须包含主机名。")
    if parsed.username or parsed.password:
        raise OcrError("invalid_endpoint", "OCR 服务地址不能内嵌账号或密码，请使用令牌栏单独保存。")
    return cleaned


def _file_sha256(path: Path) -> str:
    if not path.is_file() or path.is_symlink():
        raise OcrError("file_unavailable", "待识别文件不存在或不可读取。")
    size = path.lstat().st_size
    if size <= 0:
        raise OcrError("file_unavailable", "待识别文件为空。")
    if size > MAX_OCR_IMAGE_BYTES:
        raise OcrError("file_too_large", "待识别文件超过 20 MiB 上限，未上传或识别。")
    with path.open("rb") as stream:
        return hashlib.file_digest(stream, "sha256").hexdigest()


def _parse_paddle_response(payload: Any) -> tuple[list[dict[str, Any]], str]:
    """Normalize PaddleOCR official API and self-hosted JSON responses into lines + model version."""
    if not isinstance(payload, dict):
        raise OcrError("provider_error", "OCR 服务返回格式不是 JSON 对象。", status_code=502)
    if payload.get("errorCode") not in (None, 0, "0"):
        raise OcrError("provider_error", "OCR 服务返回业务错误，请检查服务状态或配额。", status_code=502)

    lines: list[dict[str, Any]] = []
    model_version = str(payload.get("model_version") or payload.get("model") or "").strip()

    # Format 1: PaddleOCR AI Studio / PP-OCRv5 / PaddleX pipeline response
    result_obj = payload.get("result")
    if isinstance(result_obj, dict) and isinstance(result_obj.get("ocrResults"), list):
        for page in result_obj["ocrResults"]:
            if not isinstance(page, dict):
                continue
            pruned = page.get("prunedResult") if isinstance(page.get("prunedResult"), dict) else page
            texts = pruned.get("rec_texts") or []
            scores = pruned.get("rec_scores") or []
            boxes = pruned.get("dt_polys") or pruned.get("rec_boxes") or []
            if isinstance(texts, list):
                for idx, item in enumerate(texts):
                    text = str(item or "").strip()
                    if not text:
                        continue
                    score = None
                    if isinstance(scores, list) and idx < len(scores):
                        try:
                            score = round(float(scores[idx]), 4)
                        except (TypeError, ValueError):
                            score = None
                    box = boxes[idx] if isinstance(boxes, list) and idx < len(boxes) else None
                    lines.append({"text": text, "score": score, "box": box})
        return lines, model_version or "paddleocr-api"

    # Format 2: PaddleHub / self-hosted `results: [[{"text": ..., "confidence": ..., "text_region": ...}]]`
    results_list = payload.get("results")
    if isinstance(results_list, list):
        for group in results_list:
            items = group if isinstance(group, list) else [group]
            for item in items:
                if isinstance(item, dict):
                    text = str(item.get("text") or "").strip()
                    if not text:
                        continue
                    score = None
                    raw_score = item.get("confidence", item.get("score"))
                    if raw_score is not None:
                        try:
                            score = round(float(raw_score), 4)
                        except (TypeError, ValueError):
                            score = None
                    lines.append({"text": text, "score": score, "box": item.get("text_region") or item.get("box")})
                elif isinstance(item, list) and len(item) >= 2:
                    box = item[0]
                    rec = item[1]
                    if isinstance(rec, (list, tuple)) and rec:
                        text = str(rec[0] or "").strip()
                        score = None
                        if len(rec) > 1:
                            try:
                                score = round(float(rec[1]), 4)
                            except (TypeError, ValueError):
                                score = None
                        if text:
                            lines.append({"text": text, "score": score, "box": box})
        return lines, model_version or "paddleocr-self-hosted"

    # Format 3: Simple self-hosted wrapper `{"lines": [...], "text": "..."}`
    raw_lines = payload.get("lines")
    if isinstance(raw_lines, list):
        for item in raw_lines:
            if isinstance(item, str) and item.strip():
                lines.append({"text": item.strip(), "score": None, "box": None})
            elif isinstance(item, dict) and str(item.get("text") or "").strip():
                score = None
                if item.get("score") is not None:
                    try:
                        score = round(float(item["score"]), 4)
                    except (TypeError, ValueError):
                        score = None
                lines.append({"text": str(item["text"]).strip(), "score": score, "box": item.get("box")})
        return lines, model_version or "paddleocr-self-hosted"

    raw_text = payload.get("text")
    if isinstance(raw_text, str):
        for part in raw_text.splitlines():
            if part.strip():
                lines.append({"text": part.strip(), "score": None, "box": None})
        return lines, model_version or "paddleocr-self-hosted"

    raise OcrError("provider_error", "OCR 服务返回结果缺少可识别文本字段。", status_code=502)


def _sort_lines_by_coordinates(lines: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Order OCR lines top-to-bottom, left-to-right when bounding boxes are provided."""
    def sort_key(item: tuple[int, dict[str, Any]]) -> tuple[int, float, float, int]:
        idx, line = item
        box = line.get("box")
        try:
            if isinstance(box, list) and len(box) == 4 and all(isinstance(v, (int, float)) for v in box):
                x0, y0 = float(box[0]), float(box[1])
                return (0, round(y0 / 12.0), x0, idx)
            if isinstance(box, list) and box and isinstance(box[0], list) and len(box[0]) >= 2:
                xs = [float(pt[0]) for pt in box if isinstance(pt, list) and len(pt) >= 2]
                ys = [float(pt[1]) for pt in box if isinstance(pt, list) and len(pt) >= 2]
                if xs and ys:
                    return (0, round(min(ys) / 12.0), min(xs), idx)
        except (TypeError, ValueError):
            pass
        return (1, float(idx), 0.0, idx)

    return [line for _idx, line in sorted(enumerate(lines), key=sort_key)]


def _mean_confidence(lines: list[dict[str, Any]]) -> float | None:
    scores = [float(line["score"]) for line in lines if isinstance(line.get("score"), (int, float))]
    if not scores:
        return None
    return round(sum(scores) / len(scores), 4)


def default_http_post_json(
    url: str,
    body: dict[str, Any],
    headers: dict[str, str],
    timeout: int,
) -> tuple[int, bytes]:
    raw = json.dumps(body, ensure_ascii=False).encode("utf-8")
    req = Request(url, data=raw, method="POST", headers={"Content-Type": "application/json", **headers})
    try:
        with urlopen(req, timeout=timeout) as resp:
            data = resp.read(MAX_OCR_RESPONSE_BYTES + 1)
            if len(data) > MAX_OCR_RESPONSE_BYTES:
                raise OcrError("provider_error", "OCR 服务返回内容超过 8 MiB 上限。", status_code=502)
            return int(resp.status), data
    except HTTPError as exc:
        status = int(exc.code)
        if status in (401, 403):
            raise OcrError("auth_failed", f"PaddleOCR 认证失败（HTTP {status}），请检查 Access Token 是否正确或已过期。", status_code=502) from None
        if status == 429:
            raise OcrError("rate_limited", "PaddleOCR 请求过于频繁或额度不足（HTTP 429），请稍后重试。", status_code=429) from None
        raise OcrError("provider_error", f"OCR 服务返回异常状态（HTTP {status}），请稍后重试。", status_code=502) from None
    except (TimeoutError, socket.timeout):
        raise OcrError("timeout", "OCR 服务响应超时，请检查网络连接或服务状态。", status_code=504) from None
    except URLError as exc:
        if isinstance(exc.reason, (TimeoutError, socket.timeout)):
            raise OcrError("timeout", "OCR 服务响应超时，请检查网络连接或服务状态。", status_code=504) from None
        raise OcrError("network_error", "无法连接 OCR 服务，请检查网络或自建服务地址。", status_code=502) from None
    except OSError:
        raise OcrError("network_error", "无法连接 OCR 服务，请检查网络或自建服务地址。", status_code=502) from None


class OcrResultCache:
    """Content-hash SQLite cache for OCR responses so identical images are never re-billed."""

    def __init__(self, path: Path, *, max_rows: int = DEFAULT_OCR_CACHE_MAX_ROWS) -> None:
        self.path = Path(path)
        self.max_rows = max(1, int(max_rows))
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self._init_db()

    @contextmanager
    def _connect(self) -> Iterator[sqlite3.Connection]:
        # Always close explicitly so Windows never retains open locks on ocr-cache.sqlite3.
        con = sqlite3.connect(self.path, timeout=5)
        try:
            with con:
                yield con
        finally:
            con.close()

    def _init_db(self) -> None:
        with self._connect() as con:
            con.execute(
                "CREATE TABLE IF NOT EXISTS ocr_results ("
                "cache_key TEXT PRIMARY KEY, "
                "file_sha256 TEXT NOT NULL, "
                "provider TEXT NOT NULL, "
                "model_version TEXT NOT NULL, "
                "confidence REAL, "
                "text TEXT NOT NULL, "
                "lines_json TEXT NOT NULL, "
                "cached_at TEXT NOT NULL, "
                "last_used REAL NOT NULL"
                ")"
            )

    @staticmethod
    def make_key(file_sha256: str, provider_mode: str, endpoint_url: str) -> str:
        ep_hash = hashlib.sha256(endpoint_url.encode("utf-8")).hexdigest()[:16]
        return f"{file_sha256}:{provider_mode}:{ep_hash}"

    def get(self, cache_key: str) -> OcrRecognitionResult | None:
        with self._connect() as con:
            row = con.execute(
                "SELECT file_sha256, provider, model_version, confidence, text, lines_json "
                "FROM ocr_results WHERE cache_key=?",
                (cache_key,),
            ).fetchone()
            if not row:
                return None
            try:
                lines = json.loads(row[5])
                if not isinstance(lines, list):
                    return None
            except (ValueError, TypeError):
                return None
            con.execute("UPDATE ocr_results SET last_used=? WHERE cache_key=?", (time.time(), cache_key))
            return OcrRecognitionResult(
                provider=str(row[1]),
                model_version=str(row[2]),
                text=str(row[4]),
                lines=lines,
                confidence=float(row[3]) if row[3] is not None else None,
                from_cache=True,
                file_sha256=str(row[0]),
            )

    def put(self, cache_key: str, result: OcrRecognitionResult) -> None:
        now = time.time()
        with self._connect() as con:
            con.execute(
                "INSERT OR REPLACE INTO ocr_results "
                "(cache_key, file_sha256, provider, model_version, confidence, text, lines_json, cached_at, last_used) "
                "VALUES (?,?,?,?,?,?,?,?,?)",
                (
                    cache_key,
                    result.file_sha256,
                    result.provider,
                    result.model_version,
                    result.confidence,
                    result.text,
                    json.dumps(result.lines, ensure_ascii=False),
                    utc_now_text(),
                    now,
                ),
            )
            count = int((con.execute("SELECT COUNT(*) FROM ocr_results").fetchone() or (0,))[0] or 0)
            if count > self.max_rows:
                excess = count - max(1, int(self.max_rows * 0.8))
                con.execute(
                    "DELETE FROM ocr_results WHERE cache_key IN "
                    "(SELECT cache_key FROM ocr_results ORDER BY last_used ASC, cache_key ASC LIMIT ?)",
                    (excess,),
                )


def call_paddle_ocr(
    path: Path,
    *,
    provider_mode: str,
    endpoint_url: str,
    access_token: str = "",
    timeout_seconds: int = DEFAULT_OCR_TIMEOUT_SECONDS,
    cache: OcrResultCache | None = None,
    http_post: Callable[[str, dict[str, Any], dict[str, str], int], tuple[int, bytes]] = default_http_post_json,
) -> OcrRecognitionResult:
    """Recognize an image or PDF via PaddleOCR official API or self-hosted HTTP service."""
    if provider_mode not in {"paddle_api", "paddle_self_hosted"}:
        raise OcrError("ocr_disabled", "当前未启用 OCR 服务。")
    url = validate_endpoint_url(endpoint_url or (DEFAULT_PADDLE_API_URL if provider_mode == "paddle_api" else ""))
    if provider_mode == "paddle_api" and not access_token.strip():
        raise OcrError("missing_token", "未配置 PaddleOCR Access Token，请先在 OCR 设置中填写。")

    file_sha = _file_sha256(path)
    cache_key = OcrResultCache.make_key(file_sha, provider_mode, url)
    if cache is not None:
        cached = cache.get(cache_key)
        if cached is not None:
            return cached

    raw_bytes = path.read_bytes()
    encoded = base64.b64encode(raw_bytes).decode("ascii")
    file_type = 0 if path.suffix.lower() == ".pdf" else 1
    body: dict[str, Any] = {"file": encoded, "fileType": file_type}
    if provider_mode == "paddle_self_hosted":
        # Include `images` alias compatibility only when needed? Keep payload clean and standard.
        body["useDocOrientationClassify"] = False
        body["useDocUnwarping"] = False
    headers: dict[str, str] = {}
    if access_token.strip():
        headers["Authorization"] = f"token {access_token.strip()}"

    try:
        status, resp_bytes = http_post(
            url,
            body,
            headers,
            max(MIN_OCR_TIMEOUT_SECONDS, min(MAX_OCR_TIMEOUT_SECONDS, int(timeout_seconds))),
        )
    except OcrError:
        raise
    except HTTPError as exc:
        code = int(exc.code)
        if code in (401, 403):
            raise OcrError("auth_failed", f"PaddleOCR 认证失败（HTTP {code}），请检查 Access Token 是否正确或已过期。", status_code=502) from None
        if code == 429:
            raise OcrError("rate_limited", "PaddleOCR 请求过于频繁或额度不足（HTTP 429），请稍后重试。", status_code=429) from None
        raise OcrError("provider_error", f"OCR 服务返回异常状态（HTTP {code}），请稍后重试。", status_code=502) from None
    except (TimeoutError, socket.timeout):
        raise OcrError("timeout", "OCR 服务响应超时，请检查网络连接或服务状态。", status_code=504) from None
    except URLError as exc:
        if isinstance(exc.reason, (TimeoutError, socket.timeout)):
            raise OcrError("timeout", "OCR 服务响应超时，请检查网络连接或服务状态。", status_code=504) from None
        raise OcrError("network_error", "无法连接 OCR 服务，请检查网络或自建服务地址。", status_code=502) from None
    except OSError:
        raise OcrError("network_error", "无法连接 OCR 服务，请检查网络或自建服务地址。", status_code=502) from None
    if status != 200:
        raise OcrError("provider_error", f"OCR 服务返回异常状态（HTTP {status}）。", status_code=502)
    try:
        payload = json.loads(resp_bytes.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError):
        raise OcrError("provider_error", "OCR 服务返回内容不是合法 JSON。", status_code=502) from None

    lines, model_version = _parse_paddle_response(payload)
    ordered = _sort_lines_by_coordinates(lines)
    text = "\n".join(item["text"] for item in ordered)
    result = OcrRecognitionResult(
        provider=provider_mode,
        model_version=model_version,
        text=text,
        lines=ordered,
        confidence=_mean_confidence(ordered),
        from_cache=False,
        file_sha256=file_sha,
    )
    if cache is not None:
        cache.put(cache_key, result)
    return result


def extract_validated_invoice_fields(path: Path, text: str) -> dict[str, Any]:
    """Apply PDF invoice extraction rules + strict arithmetic/format validation ("宁可空，不要脏值")."""
    # `_record_from_text` enables full triplet/anchor extraction for PDF-layout text; pass a virtual
    # `.pdf` suffix for image inputs so scanned invoice images follow the exact same rules.
    virtual_path = path if path.suffix.lower() in {".pdf", ".ofd"} else path.with_suffix(".pdf")
    record = _record_from_text(virtual_path, text)
    issues: list[str] = []

    invoice_number = str(record.invoice_number or "").strip()
    if invoice_number and not _INVOICE_NUMBER_RE.fullmatch(invoice_number):
        issues.append("发票号码位数不符合 8 位或 20 位规范，已留空待核")
        invoice_number = ""

    tax_rate = str(record.tax_rate or "").strip()
    if tax_rate and tax_rate not in _LEGAL_TAX_RATES:
        issues.append(f"税率 {tax_rate} 不在常见合法税率范围内，已留空待核")
        tax_rate = ""

    amount = str(record.amount or "").strip()
    pretax_amount = str(record.pretax_amount or "").strip()
    tax_amount = str(record.tax_amount or "").strip()

    for label, val in (("价税合计", amount), ("除税金额", pretax_amount), ("税额", tax_amount)):
        if val and not is_valid_money(val):
            issues.append(f"{label}格式不合法，已留空待核")
            if label == "价税合计":
                amount = ""
            elif label == "除税金额":
                pretax_amount = ""
            else:
                tax_amount = ""

    if amount and pretax_amount and tax_amount:
        try:
            d_amt = Decimal(amount)
            d_pre = Decimal(pretax_amount)
            d_tax = Decimal(tax_amount)
            if abs((d_pre + d_tax) - d_amt) > Decimal("0.02"):
                issues.append("金额 + 税额 ≠ 价税合计（超过 0.02 容差），金额组已留空待核")
                amount = ""
                pretax_amount = ""
                tax_amount = ""
        except InvalidOperation:
            issues.append("金额数值无法解析，金额组已留空待核")
            amount = ""
            pretax_amount = ""
            tax_amount = ""

    fields = {
        "invoice_number": invoice_number,
        "invoice_type": str(record.invoice_type or ""),
        "business_type": str(record.business_type or ""),
        "invoice_date": str(record.invoice_date or ""),
        "seller": str(record.seller or ""),
        "buyer": str(record.buyer or ""),
        "amount": amount,
        "pretax_amount": pretax_amount,
        "tax_rate": tax_rate,
        "tax_amount": tax_amount,
    }
    return {"fields": fields, "validation_issues": issues, "valid": len(issues) == 0}
