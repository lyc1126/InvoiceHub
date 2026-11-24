"""Opt-in product feedback. No invoice/config/log data enters this transport."""
from __future__ import annotations

import hashlib
import ipaddress
import json
import re
import secrets
import sqlite3
import ssl
import threading
import time
from contextlib import contextmanager
from pathlib import Path
from urllib.error import HTTPError
from urllib.parse import urlsplit
from urllib.request import HTTPRedirectHandler, HTTPSHandler, Request, build_opener
from uuid import UUID

import certifi

from invoice_hub.version import PUBLIC_SOURCE_URL

KINDS = {"bug": "问题报告", "feature": "功能建议", "other": "其他反馈"}
MAX_BODY = 32 * 1024


class NoRedirect(HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        return None


def validate_feedback(value: dict) -> dict:
    if not isinstance(value, dict) or set(value) - {"request_id", "kind", "title", "description", "include_environment", "public_consent"}:
        raise ValueError("反馈字段无效")
    try:
        request_id = str(UUID(value.get("request_id", "")))
    except (ValueError, TypeError, AttributeError):
        raise ValueError("反馈编号无效") from None
    if not isinstance(value.get("kind"), str) or value.get("kind") not in KINDS:
        raise ValueError("请选择反馈类型")
    title, description = value.get("title"), value.get("description")
    if not isinstance(title, str) or not 1 <= len(title.strip()) <= 120 or re.search(r"[\x00-\x1f\x7f]", title):
        raise ValueError("标题需为 1—120 个字符且不能换行")
    if not isinstance(description, str) or not 1 <= len(description.strip()) <= 6000 or "\x00" in description:
        raise ValueError("反馈内容需为 1—6000 个字符")
    if value.get("public_consent") is not True or type(value.get("include_environment")) is not bool:
        raise ValueError("请确认公开反馈并检查环境信息选项")
    return {"request_id": request_id, "kind": value["kind"], "title": title.strip(), "description": description.strip(),
            "include_environment": value["include_environment"], "public_consent": True}


def relay_address(raw: str) -> str:
    value = raw.strip().rstrip("/")
    if not value:
        return ""
    parsed = urlsplit(value)
    if parsed.scheme != "https" or not parsed.hostname or parsed.username or parsed.password or parsed.query or parsed.fragment:
        raise ValueError("反馈中转地址必须是无凭据、无查询参数的 HTTPS 地址")
    host = parsed.hostname.lower()
    if host == "localhost" or host.endswith((".localhost", ".local")):
        raise ValueError("反馈中转地址必须是公网 HTTPS 地址")
    try:
        address = ipaddress.ip_address(host)
    except ValueError:
        pass
    else:
        if not address.is_global:
            raise ValueError("反馈中转地址必须是公网 HTTPS 地址")
    return value


def relay_request(method: str, url: str, receipt: str, payload: dict | None) -> tuple[int, dict]:
    data = None if payload is None else json.dumps(payload, ensure_ascii=False).encode()
    request = Request(url, data=data, method=method, headers={"Content-Type": "application/json", "Accept": "application/json",
                      "X-Feedback-Receipt": receipt, "User-Agent": "InvoiceHub-Feedback/1"})
    opener = build_opener(NoRedirect(), HTTPSHandler(context=ssl.create_default_context(cafile=certifi.where())))
    try:
        response = opener.open(request, timeout=8)
    except HTTPError as exc:
        response = exc
    with response:
        raw = response.read(MAX_BODY + 1)
        if len(raw) > MAX_BODY:
            raise ValueError("反馈中转响应过大")
        return response.code, json.loads(raw)


class FeedbackService:
    def __init__(self, path: Path, relay_url: str, about, transport=relay_request):
        self.path, self.about, self.transport = path, about, transport
        self.config_error = ""
        try:
            self.url = relay_address(relay_url)
        except ValueError:
            self.url = ""
            self.config_error = "在线反馈服务配置无效，请联系维护者。"
        self._gate = threading.Lock()
        self._db_lock = threading.Lock()

    @contextmanager
    def _db(self):
        self.path.parent.mkdir(parents=True, exist_ok=True)
        connection = sqlite3.connect(self.path, timeout=5)
        connection.row_factory = sqlite3.Row
        try:
            connection.execute("CREATE TABLE IF NOT EXISTS feedback_jobs (id TEXT PRIMARY KEY, fingerprint TEXT, receipt TEXT, state TEXT, number INTEGER, created REAL, relay TEXT)")
            with connection:
                yield connection
        finally:
            connection.close()

    def _view(self, row) -> dict:
        number = row["number"]
        state = row["state"] if row["state"] != "sending" else "unknown"
        messages = {"submitted": "反馈已提交，已创建 GitHub Issue。", "rejected": "反馈未被接收，可修改后重新提交。",
                    "unknown": "提交结果尚未确认，请查询结果，不要重复提交。"}
        return {"request_id": row["id"], "state": state, "issue_number": number,
                "issue_url": f"{PUBLIC_SOURCE_URL}/issues/{number}" if number else "", "message": messages[state]}

    def configuration(self) -> dict:
        package = self.about()
        # Explicit allowlist: never reuse diagnostics, paths, company records or the full About response.
        environment = {"version": package["product"]["version"], "platform": package["package"]["platform"],
                       "architecture": package["package"]["architecture"], "package_type": package["package"]["type"]}
        pending = None
        if self.path.exists():
            with self._db() as db:
                row = db.execute("SELECT * FROM feedback_jobs WHERE state IN ('sending','unknown') ORDER BY created DESC LIMIT 1").fetchone()
                pending = self._view(row) if row else None
        return {
            "enabled": bool(self.url),
            "message": self.config_error or ("" if self.url else "当前版本未部署在线直连反馈中转，可一键复制脱敏内容后前往 GitHub Issue 提交。"),
            "issue_tracker_url": f"{PUBLIC_SOURCE_URL}/issues/new",
            "environment": environment,
            "pending": pending,
        }

    def _network(self, method: str, url: str, receipt: str, payload: dict | None):
        if not self._gate.acquire(blocking=False):
            return None
        result = {}
        # DNS may ignore socket timeouts. A single daemon slot bounds both wall time and stuck resolvers.
        def fetch():
            try:
                result["response"] = self.transport(method, url, receipt, payload)
            except Exception:
                pass  # Transport details may include URLs/credentials; only the durable unknown state is public.
            finally:
                self._gate.release()
        worker = threading.Thread(target=fetch, daemon=True, name="invoicehub-feedback")
        worker.start()
        worker.join(10)
        return result.get("response") if not worker.is_alive() else None

    def _apply(self, request_id: str, response) -> dict:
        state, number = "unknown", None
        if response:
            code, body = response
            if isinstance(body, dict) and body.get("request_id") == request_id:
                if code == 200 and body.get("state") == "submitted" and type(body.get("issue_number")) is int and body["issue_number"] > 0:
                    state, number = "submitted", body["issue_number"]
                elif body.get("state") == "rejected" and code in (200, 400, 403, 422, 429):
                    state = "rejected"
        with self._db_lock, self._db() as db:
            # A late lookup cannot downgrade a previously confirmed successful submission.
            db.execute("UPDATE feedback_jobs SET state=?, number=? WHERE id=? AND state!='submitted'", (state, number, request_id))
            row = db.execute("SELECT * FROM feedback_jobs WHERE id=?", (request_id,)).fetchone()
        return self._view(row)

    def submit(self, value: dict) -> dict:
        data = validate_feedback(value)
        if not self.url:
            raise ValueError("在线反馈尚未开通或配置无效，请先复制反馈内容")
        payload = {key: data[key] for key in ("request_id", "kind", "title", "description", "public_consent")}
        payload["environment"] = self.configuration()["environment"] if data["include_environment"] else {}
        fingerprint = hashlib.sha256(json.dumps({key: val for key, val in payload.items() if key != "request_id"}, sort_keys=True).encode()).hexdigest()
        with self._db_lock, self._db() as db:
            db.execute("BEGIN IMMEDIATE")
            existing = db.execute("SELECT * FROM feedback_jobs WHERE id=?", (data["request_id"],)).fetchone()
            if existing:
                if existing["fingerprint"] != fingerprint:
                    raise ValueError("反馈编号已使用，请先查询原提交结果")
                return self._view(existing)
            existing = db.execute("SELECT * FROM feedback_jobs WHERE state IN ('sending','unknown') OR (fingerprint=? AND state='submitted') ORDER BY created DESC LIMIT 1", (fingerprint,)).fetchone()
            if existing:
                return self._view(existing)
            receipt = secrets.token_urlsafe(32)
            # Persist intent BEFORE network I/O; repeating POST or restarting must never resend an uncertain write.
            db.execute("INSERT INTO feedback_jobs VALUES (?,?,?,'sending',NULL,?,?)", (data["request_id"], fingerprint, receipt, time.time(), self.url))
        response = self._network("POST", f"{self.url}/feedback", receipt, payload)
        return self._apply(data["request_id"], response)

    def lookup(self, request_id: str) -> dict:
        try:
            request_id = str(UUID(request_id))
        except (ValueError, TypeError):
            raise ValueError("反馈编号无效") from None
        if not self.path.exists():
            raise ValueError("没有找到这条反馈")
        with self._db() as db:
            row = db.execute("SELECT * FROM feedback_jobs WHERE id=?", (request_id,)).fetchone()
        if not row:
            raise ValueError("没有找到这条反馈")
        if row["state"] in {"submitted", "rejected"}:
            return self._view(row)
        # Bind the receipt to its original relay even after configuration changes; lookup never creates an issue.
        return self._apply(request_id, self._network("GET", f"{row['relay']}/feedback/{request_id}", row["receipt"], None))
