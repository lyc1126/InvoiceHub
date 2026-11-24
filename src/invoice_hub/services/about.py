"""About page and update lifecycle: build identity, public links, update checks and install.

Split out of ``AppState`` (ENG-03); routes call it as ``state.about`` (ENG-08). Feed fetching, caching and version approval stay in ``UpdateService``.

Inside a configured Tauri host every check is an install preflight: strict fresh metadata and
the host's own candidate must agree before a one-shot, process-local approval is recorded,
and ``install_update`` consumes it. ``_host_update_lock`` serialises that lifecycle without
blocking; a contended check returns the busy result immediately and writes no event. The
approval never reaches the Web API.
"""

from __future__ import annotations

import threading
from typing import Callable

from invoice_hub.platform import host_rpc, open_external_url
from invoice_hub.services.update_service import UpdateService
from invoice_hub.storage import SQLiteRepository
from invoice_hub.version import CHANGELOG_URL, LOCAL_WEBSITE_PATH, PRODUCT_DISPLAY_NAME, PRODUCT_NAME, PUBLIC_SOURCE_URL

ABOUT_EXTERNAL_LINKS = {
    "github": PUBLIC_SOURCE_URL,
    "changelog": CHANGELOG_URL,
}


class AboutService:
    def __init__(
        self,
        *,
        lock: threading.RLock,
        repo: SQLiteRepository,
        update_service: UpdateService,
        build_manifest: dict,
        package_manifest: dict,
        preferences: Callable[[], dict],
    ) -> None:
        self._lock = lock
        self.repo = repo
        self._update_service = update_service
        self._build_manifest = build_manifest
        self._package_manifest = package_manifest
        self._preferences = preferences
        self._update_check_timer: threading.Timer | None = None
        self._host_update_lock = threading.Lock()
        self._host_update_approval_version = ""
        self._host_update_check_generation = 0

    def _tauri_desktop_host_enabled(self) -> bool:
        return host_rpc.desktop_host_mode_enabled()

    def preferences(self) -> dict:
        return self._preferences()

    def append_event(self, event_type: str, payload: dict | None = None, error: dict | None = None, task_id: str | None = None) -> dict:
        return self.repo.append_event(event_type, payload=payload, error=error, task_id=task_id)

    def about(self) -> dict:
        package = self._package_manifest
        build = self._build_manifest
        return {
            "ok": True,
            "product": {
                "name": PRODUCT_NAME,
                "display_name": PRODUCT_DISPLAY_NAME,
                "version": package["product_version"],
            },
            "package": {
                "id": package["package_id"],
                "platform": package["platform"],
                "architecture": package["architecture"],
                "type": package["package_type"],
                "manifest_status": package["manifest_status"],
            },
            "build": {
                "id": build["build_id"],
                "source_commit": build["source_commit"],
                "built_at": build["built_at"],
                "api_contract_version": build["api_contract_version"],
            },
            "links": {
                "website": LOCAL_WEBSITE_PATH,
                "github": PUBLIC_SOURCE_URL,
                "release_notes": CHANGELOG_URL,
            },
            "update": self._update_service.state(),
        }

    def open_about_link(self, link_key: str) -> dict:
        """Open a fixed public project link through the operating system shell."""

        key = str(link_key or "").strip().casefold()
        try:
            url = ABOUT_EXTERNAL_LINKS[key]
        except KeyError as exc:
            raise ValueError("公开链接不可用") from exc
        open_external_url(url)
        return {"ok": True, "link_key": key}

    def check_for_updates(self, *, force: bool = False) -> dict:
        # API, settings, and scheduled checks share this method. In a configured
        # Tauri host process they are all delegated-install preflight, not an
        # ordinary cache-only public check.
        host_approval_requested = (
            self._tauri_desktop_host_enabled()
            and host_rpc.is_configured()
            and host_rpc.updater_enabled()
        )
        if not host_approval_requested:
            # Only a non-host process has no delegated install preflight. Keep
            # its ordinary cache/ETag and independent nonblocking busy behavior.
            result = self._update_service.check(force=force)
        elif not self._host_update_lock.acquire(blocking=False):
            # Do not reset a valid approval, touch host metadata, or write an
            # event while an owned host check/install lifecycle is in progress.
            result = self._update_service.busy_result()
            return {"ok": bool(result.get("ok")), "update": result}
        else:
            # Keep the strict metadata approval and host-owned candidate in one
            # serialized session. The approval is process-local and never
            # reaches the Web API.
            try:
                with self._lock:
                    self._host_update_approval_version = ""
                    self._host_update_check_generation += 1
                    approval_generation = self._host_update_check_generation
                result = self._update_service.check(force=force, require_fresh_body=True)
                if (
                    result.get("ok") is True
                    and result.get("status") == "available"
                ):
                    latest_version = str(result.get("latest_version") or "").strip()
                    if latest_version:
                        try:
                            host_candidate_version = host_rpc.update_check()
                        except host_rpc.HostRpcError:
                            host_candidate_version = None
                        if host_candidate_version == latest_version:
                            with self._lock:
                                if approval_generation == self._host_update_check_generation:
                                    self._host_update_approval_version = latest_version
            finally:
                self._host_update_lock.release()
        self.append_event(
            "updates.checked",
            {
                "status": result.get("status"),
                "latest_version": result.get("latest_version"),
                "error_code": result.get("error_code"),
                "force": bool(force),
            },
        )
        return {"ok": bool(result.get("ok")), "update": result}

    def install_update(self) -> dict:
        """Delegate an already metadata-approved update to the owned Tauri host."""

        if not self._host_update_lock.acquire(blocking=False):
            # A competing lifecycle operation owns the one-shot approval. Do
            # not consume it or make a second private RPC while it is active.
            raise host_rpc.HostRpcError("Tauri host updater is unavailable")
        try:
            with self._lock:
                approval = self._host_update_approval_version
                # Install is one-shot even if the host rejects a stale candidate.
                self._host_update_approval_version = ""
            if not (
                approval
                and self._tauri_desktop_host_enabled()
                and host_rpc.is_configured()
                and host_rpc.updater_enabled()
            ):
                raise host_rpc.HostRpcError("Tauri host updater is unavailable")
            host_rpc.update_install()
        finally:
            self._host_update_lock.release()
        self.append_event("updates.install_requested", {"version": approval})
        return {"ok": True}

    def schedule_background_update_check(self, delay_seconds: float = 15.0) -> bool:
        if not self._package_manifest.get("manifest_valid"):
            return False
        if not self.preferences()["preferences"].get("auto_check_updates", True):
            return False
        with self._lock:
            if self._update_check_timer is not None:
                return False

            def run() -> None:
                try:
                    self.check_for_updates(force=False)
                except Exception as exc:
                    self.append_event("updates.background_failed", error={"message": str(exc)})

            timer = threading.Timer(max(0.0, float(delay_seconds)), run)
            timer.daemon = True
            self._update_check_timer = timer
            timer.start()
        return True
