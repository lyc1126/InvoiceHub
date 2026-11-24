"""OCR page and company screenshot OCR use cases (OCR-01).

Core packaging ships no local heavy OCR engine (`provider_mode="disabled"` by default).
Users may configure PaddleOCR official online API (with explicit cloud consent and per-company
opt-in) or a user-operated self-hosted PaddleOCR HTTP service. Access tokens are stored only
in an owner-readable `runtime/.ocr-secrets.json` file, never in `config/app.local.json`, logs,
or diagnostic bundles.
"""
from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Any, Callable

from invoice_hub.domain.models import TargetProfile
from invoice_hub.extraction.ocr_client import (
    DEFAULT_OCR_TIMEOUT_SECONDS,
    DEFAULT_PADDLE_API_URL,
    MAX_OCR_TIMEOUT_SECONDS,
    MIN_OCR_TIMEOUT_SECONDS,
    VALID_PROVIDER_MODES,
    OcrError,
    OcrResultCache,
    call_paddle_ocr,
    default_http_post_json,
    extract_validated_invoice_fields,
    validate_endpoint_url,
)
from invoice_hub.platform import HostRpcCommand, OCR_EXTENSIONS, open_local_path, pick_directory, pick_file
from invoice_hub.storage.files import atomic_write_json
from invoice_hub.targets import AppConfig
from invoice_hub.targets.paths import Layout

OCR_SETTINGS_FILE = "ocr-settings.json"
OCR_SECRETS_FILE = ".ocr-secrets.json"
OCR_CACHE_FILE = "ocr-cache.sqlite3"


class OcrService:
    def __init__(
        self,
        *,
        layout: Layout,
        config: Callable[[], AppConfig],
        active_profile: Callable[[], TargetProfile],
        http_post: Callable[[str, dict[str, Any], dict[str, str], int], tuple[int, bytes]] = default_http_post_json,
    ) -> None:
        self.layout = layout
        self._config = config
        self._active_profile = active_profile
        self._http_post = http_post

    @property
    def config(self) -> AppConfig:
        return self._config()

    @property
    def active_profile(self) -> TargetProfile:
        return self._active_profile()

    @property
    def _settings_path(self) -> Path:
        return self.layout.runtime_dir / OCR_SETTINGS_FILE

    @property
    def _secrets_path(self) -> Path:
        return self.layout.runtime_dir / OCR_SECRETS_FILE

    @property
    def _cache_path(self) -> Path:
        return self.layout.runtime_dir / OCR_CACHE_FILE

    def _load_raw_settings(self) -> dict[str, Any]:
        default = {
            "provider_mode": "disabled",
            "endpoint_url": "",
            "timeout_seconds": DEFAULT_OCR_TIMEOUT_SECONDS,
            "cloud_consent_acknowledged": False,
            "enabled_companies": [],
        }
        path = self._settings_path
        if not path.is_file() or path.is_symlink():
            return default
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            return default
        if not isinstance(data, dict):
            return default
        mode = str(data.get("provider_mode") or "disabled").strip()
        if mode not in VALID_PROVIDER_MODES:
            mode = "disabled"
        companies = data.get("enabled_companies")
        clean_companies = [str(c).strip() for c in companies if isinstance(c, str) and c.strip()] if isinstance(companies, list) else []
        try:
            timeout = int(data.get("timeout_seconds", DEFAULT_OCR_TIMEOUT_SECONDS))
        except (TypeError, ValueError):
            timeout = DEFAULT_OCR_TIMEOUT_SECONDS
        timeout = max(MIN_OCR_TIMEOUT_SECONDS, min(MAX_OCR_TIMEOUT_SECONDS, timeout))
        return {
            "provider_mode": mode,
            "endpoint_url": str(data.get("endpoint_url") or "").strip(),
            "timeout_seconds": timeout,
            "cloud_consent_acknowledged": bool(data.get("cloud_consent_acknowledged", False)),
            "enabled_companies": list(dict.fromkeys(clean_companies)),
        }

    def _load_token(self) -> str:
        path = self._secrets_path
        if not path.is_file() or path.is_symlink():
            return ""
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            return ""
        if not isinstance(data, dict):
            return ""
        return str(data.get("access_token") or "").strip()

    def _save_token(self, token: str) -> None:
        path = self._secrets_path
        path.parent.mkdir(parents=True, exist_ok=True)
        if not token:
            path.unlink(missing_ok=True)
            return
        atomic_write_json(path, {"version": 1, "access_token": token})
        try:
            os.chmod(path, 0o600)
        except OSError:
            pass

    def _effective_endpoint(self, settings: dict[str, Any]) -> str:
        if settings["provider_mode"] == "paddle_api":
            return settings["endpoint_url"] or DEFAULT_PADDLE_API_URL
        return settings["endpoint_url"]

    def _readiness(self, settings: dict[str, Any], has_token: bool) -> tuple[bool, str, str]:
        mode = settings["provider_mode"]
        if mode == "disabled":
            return False, "disabled", "当前发布包未内置本地 OCR；如需识别扫描件/截图，可配置 PaddleOCR 官方 API 或自建服务。"
        if mode == "paddle_api":
            if not settings["cloud_consent_acknowledged"]:
                return False, "unconfigured", "PaddleOCR 官方 API 会将图片上传至云端，请先确认隐私说明后再启用。"
            if not has_token:
                return False, "unconfigured", "PaddleOCR 官方 API 尚未填写 Access Token。"
            return True, "ready", "PaddleOCR 官方 API 已就绪（图片将按内容哈希缓存，云端仅对已勾选公司自动生效）。"
        endpoint = settings["endpoint_url"]
        if not endpoint:
            return False, "unconfigured", "自建 PaddleOCR 服务尚未填写服务地址。"
        return True, "ready", f"自建 PaddleOCR 服务已配置（{endpoint}）。"

    def ocr_settings(self) -> dict:
        settings = self._load_raw_settings()
        has_token = bool(self._load_token())
        ready, status, message = self._readiness(settings, has_token)
        return {
            "ok": True,
            "provider_mode": settings["provider_mode"],
            "endpoint_url": settings["endpoint_url"],
            "default_paddle_api_url": DEFAULT_PADDLE_API_URL,
            "timeout_seconds": settings["timeout_seconds"],
            "token_configured": has_token,
            "cloud_consent_acknowledged": settings["cloud_consent_acknowledged"],
            "enabled_companies": list(settings["enabled_companies"]),
            "ready": ready,
            "status": status,
            "local_ocr_supported": bool(self.config.release_capabilities.get("local_ocr", False)),
            "message": message,
        }

    def update_ocr_settings(self, payload: dict | None) -> dict:
        if not isinstance(payload, dict):
            raise ValueError("OCR 设置格式无效。")
        current = self._load_raw_settings()
        mode = str(payload.get("provider_mode", current["provider_mode"]) or "disabled").strip()
        if mode not in VALID_PROVIDER_MODES:
            raise ValueError("不支持的 OCR 提供方模式。")

        raw_endpoint = payload.get("endpoint_url", current["endpoint_url"])
        endpoint_url = validate_endpoint_url(
            str(raw_endpoint or "").strip(),
            allow_empty=(mode != "paddle_self_hosted"),
        ) if mode != "disabled" else str(raw_endpoint or "").strip()

        raw_timeout = payload.get("timeout_seconds", current["timeout_seconds"])
        try:
            timeout_seconds = int(raw_timeout)
        except (TypeError, ValueError):
            raise ValueError("超时时间须为整数秒。") from None
        if not MIN_OCR_TIMEOUT_SECONDS <= timeout_seconds <= MAX_OCR_TIMEOUT_SECONDS:
            raise ValueError(f"超时时间须在 {MIN_OCR_TIMEOUT_SECONDS}—{MAX_OCR_TIMEOUT_SECONDS} 秒。")

        cloud_consent = bool(payload.get("cloud_consent_acknowledged", current["cloud_consent_acknowledged"]))
        raw_companies = payload.get("enabled_companies", current["enabled_companies"])
        if not isinstance(raw_companies, list):
            raise ValueError("enabled_companies 须为公司 ID 列表。")
        enabled_companies = list(dict.fromkeys(str(c).strip() for c in raw_companies if isinstance(c, str) and c.strip()))

        if payload.get("clear_token") is True:
            self._save_token("")
        elif "access_token" in payload:
            token = str(payload.get("access_token") or "").strip()
            if token:
                if len(token) > 2048 or any(ord(ch) < 32 for ch in token):
                    raise ValueError("Access Token 格式无效。")
                self._save_token(token)

        saved = {
            "version": 1,
            "provider_mode": mode,
            "endpoint_url": endpoint_url,
            "timeout_seconds": timeout_seconds,
            "cloud_consent_acknowledged": cloud_consent,
            "enabled_companies": enabled_companies,
        }
        atomic_write_json(self._settings_path, saved)
        return self.ocr_settings()

    def ocr_service_status(self) -> dict:
        settings = self._load_raw_settings()
        has_token = bool(self._load_token())
        ready, status, message = self._readiness(settings, has_token)
        return {
            "ok": True,
            "running": ready,
            "status": status,
            "provider_mode": settings["provider_mode"],
            "token_configured": has_token,
            "message": message,
        }

    def pick_ocr_file(self) -> dict:
        payload = pick_file(
            Path(self.active_profile.watch_dir),
            "选择 OCR 识别文件",
            host_command=HostRpcCommand.PICK_OCR_FILE,
        )
        selected_path = str(payload.get("path") or "").strip()
        return {"ok": True, "selected": bool(selected_path), "path": selected_path}

    def pick_ocr_folder(self) -> dict:
        payload = pick_directory(
            Path(self.active_profile.watch_dir),
            "选择 OCR 文件夹",
            host_command=HostRpcCommand.PICK_OCR_DIRECTORY,
        )
        selected_path = str(payload.get("path") or "").strip()
        return {"ok": True, "selected": bool(selected_path), "path": selected_path}

    def list_ocr_files(self, payload: dict | None = None) -> dict:
        folder = Path(str((payload or {}).get("folder") or self.active_profile.watch_dir)).expanduser()
        if not folder.exists() or not folder.is_dir():
            return {"ok": False, "items": [], "message": f"目录不可用: {folder}"}
        items = [
            {"path": str(path), "name": path.name, "suffix": path.suffix.lower(), "size": path.stat().st_size}
            for path in sorted(folder.iterdir(), key=lambda item: item.name.casefold())
            if path.is_file() and path.suffix.lower() in OCR_EXTENSIONS
        ]
        return {"ok": True, "items": items}

    def recognize_file(self, path: Path, *, company_id: str = "", require_company_opt_in: bool = False) -> dict[str, Any]:
        settings = self._load_raw_settings()
        mode = settings["provider_mode"]
        if mode == "disabled":
            raise OcrError("ocr_disabled", "当前未启用 OCR 服务，请先在 OCR 页面配置 PaddleOCR 官方 API 或自建服务。")
        if mode == "paddle_api":
            if not settings["cloud_consent_acknowledged"]:
                raise OcrError("cloud_consent_required", "云端 PaddleOCR 会上传图片，请先在 OCR 页面勾选隐私确认。")
            if require_company_opt_in and company_id not in settings["enabled_companies"]:
                raise OcrError("cloud_consent_required", "该公司尚未开启云端 OCR 授权，请在 OCR 页面为该公司单独开启。")
        token = self._load_token()
        endpoint = self._effective_endpoint(settings)
        cache = OcrResultCache(self._cache_path)
        result = call_paddle_ocr(
            path,
            provider_mode=mode,
            endpoint_url=endpoint,
            access_token=token,
            timeout_seconds=settings["timeout_seconds"],
            cache=cache,
            http_post=self._http_post,
        )
        extracted = extract_validated_invoice_fields(path, result.text)
        return {
            "provider": result.provider,
            "model_version": result.model_version,
            "confidence": result.confidence,
            "from_cache": result.from_cache,
            "file_sha256": result.file_sha256,
            "text": result.text,
            "lines": result.lines,
            "invoice_fields": extracted["fields"],
            "validation_issues": extracted["validation_issues"],
            "validation_ok": extracted["valid"],
        }

    def payroll_reader_for_company(self, company_id: str) -> Callable[[Path], tuple[str, dict[str, Any]]] | None:
        """Return a company-scoped OCR callback for social-security screenshot parsing, or None if not enabled."""
        settings = self._load_raw_settings()
        mode = settings["provider_mode"]
        if mode == "disabled":
            return None
        if mode == "paddle_api":
            if not settings["cloud_consent_acknowledged"] or not self._load_token():
                return None
            if company_id not in settings["enabled_companies"]:
                return None
        elif mode == "paddle_self_hosted":
            if not settings["endpoint_url"]:
                return None

        def _read(path: Path) -> tuple[str, dict[str, Any]]:
            res = self.recognize_file(path, company_id=company_id, require_company_opt_in=True)
            return res["text"], {
                "provider": res["provider"],
                "model_version": res["model_version"],
                "confidence": res["confidence"],
                "from_cache": res["from_cache"],
            }

        return _read

    def ocr_extract_text(self, payload: dict | None = None) -> dict:
        raw_path = str((payload or {}).get("path") or "").strip()
        company_id = str((payload or {}).get("company_id") or "").strip()
        if not raw_path:
            return {"ok": False, "text": "", "message": "请先选择需要识别的文件。", "path": ""}
        target = Path(raw_path).expanduser()
        try:
            recognized = self.recognize_file(target, company_id=company_id, require_company_opt_in=bool(company_id))
        except OcrError as exc:
            return {
                "ok": False,
                "error_code": exc.code,
                "text": "",
                "message": exc.message,
                "path": raw_path,
            }
        cache_note = "（命中缓存）" if recognized["from_cache"] else ""
        issue_note = f"；有 {len(recognized['validation_issues'])} 项字段校验未通过已留空" if recognized["validation_issues"] else ""
        return {
            "ok": True,
            "path": raw_path,
            "message": f"识别完成（{recognized['provider']} / {recognized['model_version']}）{cache_note}{issue_note}",
            **recognized,
        }

    def open_ocr_log_dir(self) -> dict:
        open_local_path(self.layout.runtime_dir)
        return {"ok": True, "opened": True, "path": str(self.layout.runtime_dir)}
