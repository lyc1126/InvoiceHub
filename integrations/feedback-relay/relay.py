"""Standalone opt-in feedback relay. Deploy separately; never start with the desktop app."""
from __future__ import annotations

import hashlib
import hmac
import json
import os
import re
import sqlite3
import ssl
import threading
import time
from contextlib import contextmanager
from pathlib import Path
from urllib.error import HTTPError
from urllib.request import HTTPRedirectHandler, HTTPSHandler, Request as URLRequest, build_opener
from uuid import UUID

import certifi
from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import JSONResponse
from starlette.concurrency import run_in_threadpool

REPOSITORY = "lyc1126/InvoiceHub"
KINDS = {"bug": "问题报告", "feature": "功能建议", "other": "其他反馈"}
MAX_BYTES = 32 * 1024


class NoRedirect(HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        return None


def github_create(token: str, payload: dict) -> tuple[int, dict]:
    # Credentials only travel to this fixed GitHub API URL; redirects are never followed.
    request = URLRequest(f"https://api.github.com/repos/{REPOSITORY}/issues", method="POST",
                         data=json.dumps(payload, ensure_ascii=False).encode(), headers={
                             "Authorization": f"Bearer {token}", "Accept": "application/vnd.github+json",
                             "Content-Type": "application/json", "User-Agent": "InvoiceHub-Feedback-Relay/1",
                             "X-GitHub-Api-Version": "2022-11-28"})
    opener = build_opener(NoRedirect(), HTTPSHandler(context=ssl.create_default_context(cafile=certifi.where())))
    try:
        response = opener.open(request, timeout=8)
    except HTTPError as exc:
        response = exc
    with response:
        body = response.read(256 * 1024 + 1)
        if len(body) > 256 * 1024:
            raise ValueError("oversized upstream response")
        return response.code, json.loads(body)


def checked(value: object) -> dict:
    if not isinstance(value, dict) or set(value) != {"request_id", "kind", "title", "description", "public_consent", "environment"}:
        raise ValueError("invalid fields")
    try:
        request_id = str(UUID(value["request_id"]))
    except (ValueError, TypeError, AttributeError):
        raise ValueError("invalid id") from None
    kind, title, description = value["kind"], value["title"], value["description"]
    if not isinstance(kind, str) or kind not in KINDS or value["public_consent"] is not True:
        raise ValueError("invalid consent or kind")
    if not isinstance(title, str) or not 1 <= len(title.strip()) <= 120 or re.search(r"[\x00-\x1f\x7f]", title):
        raise ValueError("invalid title")
    if not isinstance(description, str) or not 1 <= len(description.strip()) <= 6000 or "\x00" in description:
        raise ValueError("invalid description")
    environment = value["environment"]
    if not isinstance(environment, dict) or set(environment) - {"version", "platform", "architecture", "package_type"}:
        raise ValueError("invalid environment")
    if any(not isinstance(item, str) or not re.fullmatch(r"[A-Za-z0-9_.+ -]{1,80}", item) for item in environment.values()):
        raise ValueError("invalid environment values")
    return {**value, "request_id": request_id, "title": title.strip(), "description": description.strip()}


class Relay:
    def __init__(self, db_path: Path, token: str, rate_secret: str, send=github_create):
        self.path, self.token, self.secret, self.send = db_path, token, rate_secret.encode(), send
        self.lock = threading.Lock()
        self.network = threading.BoundedSemaphore(2)
        self.wait_seconds = 10.0

    @contextmanager
    def db(self):
        self.path.parent.mkdir(parents=True, exist_ok=True)
        connection = sqlite3.connect(self.path, timeout=5)
        connection.row_factory = sqlite3.Row
        try:
            connection.execute("CREATE TABLE IF NOT EXISTS submissions (id TEXT PRIMARY KEY, receipt_hash TEXT, payload_hash TEXT, state TEXT, number INTEGER, created REAL, client_hash TEXT)")
            with connection:
                yield connection
        finally:
            connection.close()

    def ready(self):
        return bool(self.token and len(self.secret) >= 32 and self.path.is_absolute())

    @staticmethod
    def view(row):
        state = row["state"] if row["state"] != "sending" else "unknown"
        return {"request_id": row["id"], "state": state, "issue_number": row["number"]}

    def lookup(self, request_id: str, receipt: str):
        if not self.path.exists():
            raise HTTPException(404, "receipt not found")
        with self.db() as db:
            row = db.execute("SELECT * FROM submissions WHERE id=?", (request_id,)).fetchone()
        if not row or not hmac.compare_digest(row["receipt_hash"], hashlib.sha256(receipt.encode()).hexdigest()):
            raise HTTPException(404, "receipt not found")
        return self.view(row)

    def finish(self, request_id: str, result):
        state, number = "unknown", None
        if result:
            code, issue = result
            if code == 201 and isinstance(issue, dict) and type(issue.get("number")) is int and issue["number"] > 0:
                state, number = "submitted", issue["number"]
            elif code in {400, 401, 403, 404, 410, 422, 429}:
                state = "rejected"
        with self.db() as db:
            db.execute("UPDATE submissions SET state=?, number=? WHERE id=? AND state!='submitted'", (state, number, request_id))

    def submit(self, value: dict, receipt: str, client: str):
        data = checked(value)
        now = time.time()
        client_hash = hmac.new(self.secret, f"{int(now // 86400)}:{client}".encode(), hashlib.sha256).hexdigest()
        payload_hash = hashlib.sha256(json.dumps(data, sort_keys=True).encode()).hexdigest()
        receipt_hash = hashlib.sha256(receipt.encode()).hexdigest()
        with self.lock, self.db() as db:
            # BEGIN IMMEDIATE serializes reservation + budgets across processes, not just HTTP threads.
            db.execute("BEGIN IMMEDIATE")
            old = db.execute("SELECT * FROM submissions WHERE id=?", (data["request_id"],)).fetchone()
            if old:
                if old["payload_hash"] != payload_hash or not hmac.compare_digest(old["receipt_hash"], receipt_hash):
                    raise HTTPException(409, "feedback identity conflict")
                return self.view(old)
            hourly = db.execute("SELECT count(*) FROM submissions WHERE client_hash=? AND created>?", (client_hash, now - 3600)).fetchone()[0]
            daily = db.execute("SELECT count(*) FROM submissions WHERE created>=?", (int(now // 86400) * 86400,)).fetchone()[0]
            if hourly >= 5 or daily >= 50:
                return JSONResponse({"request_id": data["request_id"], "state": "rejected", "issue_number": None}, status_code=429, headers={"Retry-After": "3600"})
            db.execute("INSERT INTO submissions VALUES (?,?,?,'sending',NULL,?,?)", (data["request_id"], receipt_hash, payload_hash, now, client_hash))
        # Never persist feedback text or contacts. The receipt stores only hashes/status/issue number.
        # Neutralize mentions: this anonymous public endpoint must not ping arbitrary GitHub users.
        body = data["description"].replace("@", "@\u200b")
        if data["environment"]:
            body += "\n\n### 用户确认附带的环境信息\n" + "\n".join(f"- {key}: {value}" for key, value in data["environment"].items())
        body += f"\n\n---\n来自 InvoiceHub 应用内反馈；内容由提交者提供。\n<!-- invoicehub-feedback:{data['request_id']} -->"
        outbound = {"title": f"[{KINDS[data['kind']]}] {data['title'].replace('@', '@' + chr(0x200b))}", "body": body}
        if self.network.acquire(blocking=False):
            def call():
                result = None
                try:
                    result = self.send(self.token, outbound)
                except Exception:
                    pass  # Do not expose upstream responses, submitted text or tokens in logs/API.
                finally:
                    try:
                        # A late success still becomes queryable even when the original HTTP response timed out.
                        self.finish(data["request_id"], result)
                    finally:
                        self.network.release()
            worker = threading.Thread(target=call, daemon=True)
            worker.start()
            worker.join(self.wait_seconds)
        else:
            # Capacity rejection occurs before any outbound request, so it is safe to return a definitive rejection.
            self.finish(data["request_id"], (429, {}))
        return self.lookup(data["request_id"], receipt)


def create_app(service: Relay | None = None) -> FastAPI:
    service = service or Relay(Path(os.environ.get("FEEDBACK_DB_PATH", "")), os.environ.get("FEEDBACK_GITHUB_TOKEN", ""), os.environ.get("FEEDBACK_RATE_SECRET", ""))
    app = FastAPI(title="InvoiceHub Feedback Relay", docs_url=None, redoc_url=None, openapi_url=None)

    @app.middleware("http")
    async def no_cache(request, next_handler):
        response = await next_handler(request)
        response.headers["Cache-Control"] = "no-store"
        response.headers["X-Content-Type-Options"] = "nosniff"
        return response

    def require_ready():
        if not service.ready():
            raise HTTPException(503, "feedback relay not configured")

    def require_receipt(request):
        receipt = request.headers.get("X-Feedback-Receipt", "")
        if not re.fullmatch(r"[A-Za-z0-9_-]{40,100}", receipt):
            raise HTTPException(400, "invalid receipt")
        return receipt

    @app.get("/health")
    def health():
        require_ready()
        return {"ok": True}

    @app.post("/feedback")
    async def submit(request: Request):
        require_ready()
        receipt = require_receipt(request)
        raw = bytearray()
        async for chunk in request.stream():
            raw.extend(chunk)
            if len(raw) > MAX_BYTES:
                raise HTTPException(413, "feedback too large")
        try:
            value = checked(json.loads(raw))
        except (ValueError, TypeError):
            raise HTTPException(422, "invalid feedback") from None
        return await run_in_threadpool(service.submit, value, receipt, request.client.host if request.client else "unknown")

    @app.get("/feedback/{request_id}")
    def lookup(request_id: str, request: Request):
        require_ready()
        try:
            request_id = str(UUID(request_id))
        except ValueError:
            raise HTTPException(404, "receipt not found") from None
        return service.lookup(request_id, require_receipt(request))

    return app


app = create_app()
