"""Rename source invoices in watch_dir to ``YY-MM-DD_销售方&购买方_金额元.ext``.

Split out of ``AppState`` (ENG-03); routes call it as ``state.rename`` (ENG-08). Phase one moves every source to a temporary name first so planned
targets never collide with each other; any staging failure rolls back in reverse. Existing
non-planned files are never overwritten, manual overrides follow their renamed source, and a
rebuild refreshes the projections afterwards. Collaborators (invoice list, monitor state,
rebuild, cache, directory check) are other services' methods passed in under the same names
and looked up through AppState on every call, so patches on those services apply.
"""

from __future__ import annotations

import re
import threading
import uuid
from datetime import datetime
from decimal import Decimal, InvalidOperation
from pathlib import Path
from typing import Callable

from invoice_hub.domain.models import TargetProfile, utc_now_text
from invoice_hub.extraction import is_valid_money, supported_invoice_files
from invoice_hub.extraction.parsers import SUPPORTED_EXTS as SOURCE_INVOICE_EXTENSIONS
from invoice_hub.monitoring.state import MonitorState
from invoice_hub.storage import SQLiteRepository, atomic_write_json, read_json_object

INVOICE_RENAME_FORMAT = "YY-MM-DD_\u9500\u552e\u65b9&\u8d2d\u4e70\u65b9_\u91d1\u989d\u5143.ext"
INVOICE_RENAME_DETAILS_LIMIT = 80
WINDOWS_FILENAME_FORBIDDEN = re.compile(r'[<>:"/\\|?*\x00-\x1f]+')


class InvoiceRenameService:
    def __init__(
        self,
        *,
        lock: threading.RLock,
        repo: SQLiteRepository,
        active_profile: Callable[[], TargetProfile],
        list_invoices: Callable[..., dict],
        monitor_state: Callable[[], MonitorState],
        bridge_rebuild: Callable[[], dict],
        inspect_watch_dir: Callable[[Path], dict],
        manual_overrides_path: Callable[[], Path],
        clear_invoice_cache: Callable[[], None],
    ) -> None:
        self._lock = lock
        self.repo = repo
        self._profile_provider = active_profile
        self.list_invoices = list_invoices
        self._monitor_state = monitor_state
        self.bridge_rebuild = bridge_rebuild
        self.inspect_watch_dir = inspect_watch_dir
        self._manual_overrides_path = manual_overrides_path
        self._clear_invoice_cache = clear_invoice_cache

    @property
    def active_profile(self) -> TargetProfile:
        return self._profile_provider()

    def append_event(self, event_type: str, payload: dict | None = None, error: dict | None = None, task_id: str | None = None) -> dict:
        return self.repo.append_event(event_type, payload=payload, error=error, task_id=task_id)

    @staticmethod
    def _rename_path_key(path: Path) -> str:
        try:
            return str(path.resolve()).casefold()
        except OSError:
            return str(path).casefold()

    @staticmethod
    def _rename_date_component(value: object) -> str:
        text = str(value or "").strip()
        digits = re.sub(r"\D", "", text)
        match = re.fullmatch(r"(\d{4})(\d{2})(\d{2})", digits) if len(digits) == 8 else None
        if match:
            year, month, day = (int(match.group(index)) for index in range(1, 4))
        else:
            match = re.search(r"(\d{4})\D+(\d{1,2})\D+(\d{1,2})", text)
            if not match:
                return ""
            year, month, day = (int(match.group(index)) for index in range(1, 4))
        try:
            return datetime(year, month, day).strftime("%y-%m-%d")
        except ValueError:
            return ""

    @staticmethod
    def _rename_party_component(value: object) -> str:
        text = WINDOWS_FILENAME_FORBIDDEN.sub(" ", str(value or ""))
        text = re.sub(r"\s+", " ", text).strip(" .")
        compact = re.sub(r"\s+", "", text)
        blocked = {
            "\u9500\u552e\u65b9",
            "\u8d2d\u4e70\u65b9",
            "\u9500\u552e\u65b9\u540d\u79f0",
            "\u8d2d\u4e70\u65b9\u540d\u79f0",
            "\u540d\u79f0",
            "\u53d1\u7968",
            "\u5730\u5740\u7535\u8bdd",
            "\u9879\u76ee\u540d\u79f0",
            "\u8d27\u7269\u6216\u5e94\u7a0e\u52b3\u52a1\u670d\u52a1\u540d\u79f0",
        }
        if not compact or compact in blocked or compact.isdigit() or len(compact) < 2:
            return ""
        return text[:60].rstrip(" .")

    @staticmethod
    def _rename_amount_component(value: object) -> str:
        raw = str(value or "").strip()
        if not is_valid_money(raw):
            return ""
        normalized = raw.replace(",", "")
        if not re.fullmatch(r"-?\d+(?:\.\d+)?", normalized):
            return ""
        try:
            amount = Decimal(normalized)
        except InvalidOperation:
            return ""
        text = format(amount.quantize(Decimal("0.01")), "f")
        return text.rstrip("0").rstrip(".") if "." in text else text

    def _invoice_rename_filename(self, invoice: dict, suffix: str) -> tuple[str, str]:
        file_type = suffix.lower()
        if file_type not in SOURCE_INVOICE_EXTENSIONS:
            return "", "unsupported_type"
        invoice_date = self._rename_date_component(invoice.get("invoice_date"))
        if not invoice_date:
            return "", "invalid_invoice_date"
        seller = self._rename_party_component(invoice.get("seller"))
        if not seller:
            return "", "invalid_seller"
        buyer = self._rename_party_component(invoice.get("buyer"))
        if not buyer:
            return "", "invalid_buyer"
        amount = self._rename_amount_component(invoice.get("amount"))
        if not amount:
            return "", "invalid_amount"
        return f"{invoice_date}_{seller}&{buyer}_{amount}\u5143{file_type}", ""

    def _migrate_renamed_manual_overrides(self, renamed_paths: list[tuple[Path, Path]]) -> int:
        if not renamed_paths:
            return 0
        rename_map = {self._rename_path_key(source): target for source, target in renamed_paths}
        payload = read_json_object(self._manual_overrides_path(), {"items": {}})
        entries = payload.get("items")
        if not isinstance(entries, dict):
            return 0

        changed = False
        moved = 0
        migrated: dict[str, object] = {}
        for identity, entry in entries.items():
            try:
                target = rename_map.get(self._rename_path_key(Path(str(identity))))
            except (OSError, TypeError, ValueError):
                target = None
            if target is None:
                migrated[str(identity)] = entry
                continue
            copied = dict(entry) if isinstance(entry, dict) else entry
            if isinstance(copied, dict):
                copied["source_path"] = str(target)
                copied["invoice_key"] = ""
                copied["renamed_at"] = utc_now_text()
            migrated[str(target)] = copied
            changed = True
            moved += 1
        if changed:
            payload["items"] = migrated
            atomic_write_json(self._manual_overrides_path(), payload)
        return moved

    @staticmethod
    def _rename_summary_message(renamed: int, unchanged: int, skipped: int) -> str:
        message = f"\u5df2\u91cd\u547d\u540d {renamed} \u4e2a\u53d1\u7968\u6587\u4ef6\u3002"
        if unchanged:
            message += f" {unchanged} \u4e2a\u6587\u4ef6\u5df2\u7b26\u5408\u547d\u540d\u683c\u5f0f\u3002"
        if skipped:
            message += f" {skipped} \u4e2a\u6587\u4ef6\u672a\u4fee\u6539\uff0c\u8bf7\u67e5\u770b\u8df3\u8fc7\u539f\u56e0\u3002"
        return message

    def rename_invoice_files(self) -> dict:
        watch_dir = Path(self.active_profile.watch_dir).expanduser().resolve()
        task_id = str(uuid.uuid4())
        base = {
            "task_id": task_id,
            "target_id": self.active_profile.id,
            "watch_dir": str(watch_dir),
            "format": INVOICE_RENAME_FORMAT,
            "supported_extensions": sorted(extension.lstrip(".") for extension in SOURCE_INVOICE_EXTENSIONS),
            "renamed": 0,
            "unchanged": 0,
            "skipped": 0,
            "skipped_by_reason": {},
            "files": [],
            "manual_overrides_migrated": 0,
        }
        self.repo.create_task(task_id, "settings.rename_invoice_files", "running", {"watch_dir": str(watch_dir)})

        def finish(ok: bool, message: str, **extra) -> dict:
            result = {**base, **extra, "ok": ok, "message": message}
            self.repo.update_task(task_id, "success" if ok else "failed", result, completed=True)
            return result

        validation = self.inspect_watch_dir(watch_dir)
        if not validation.get("can_monitor"):
            return finish(False, validation.get("summary") or "\u5f53\u524d\u53d1\u7968\u76ee\u5f55\u4e0d\u53ef\u7528\u3002", validation=validation)

        preflight = self.bridge_rebuild()
        if not preflight.get("ok"):
            return finish(False, f"\u91cd\u547d\u540d\u524d\u7684\u6c47\u603b\u5237\u65b0\u5931\u8d25\uff1a{preflight.get('error') or '\u672a\u77e5\u9519\u8bef'}", validation=validation, preflight=preflight)

        skipped_by_reason: dict[str, int] = {}
        outcomes: list[dict] = []

        def skip(source: Path, reason: str) -> None:
            skipped_by_reason[reason] = skipped_by_reason.get(reason, 0) + 1
            outcomes.append({"status": "skipped", "reason": reason, "old_path": str(source), "old_name": source.name})

        try:
            with self._lock:
                items_by_source = {
                    self._rename_path_key(Path(str(item.get("source_path") or item.get("file_path") or ""))): item
                    for item in self.list_invoices().get("items", [])
                    if str(item.get("source_path") or item.get("file_path") or "").strip()
                }
                source_files = supported_invoice_files(watch_dir)
                candidates: list[dict] = []
                unchanged = 0
                for source in source_files:
                    invoice = items_by_source.get(self._rename_path_key(source))
                    if not invoice:
                        skip(source, "invoice_not_in_summary")
                        continue
                    file_name, reason = self._invoice_rename_filename(invoice, source.suffix)
                    if reason:
                        skip(source, reason)
                        continue
                    target = source.with_name(file_name)
                    if self._rename_path_key(source) == self._rename_path_key(target):
                        unchanged += 1
                        outcomes.append({"status": "unchanged", "old_path": str(source), "old_name": source.name})
                        continue
                    candidates.append({"source": source, "target": target})

                target_groups: dict[str, list[dict]] = {}
                for candidate in candidates:
                    target_groups.setdefault(self._rename_path_key(candidate["target"]), []).append(candidate)
                planned: list[dict] = []
                for group in target_groups.values():
                    if len(group) > 1:
                        for candidate in group:
                            skip(candidate["source"], "duplicate_target_name")
                    else:
                        planned.append(group[0])

                changed = True
                while changed:
                    changed = False
                    source_keys = {self._rename_path_key(candidate["source"]) for candidate in planned}
                    kept: list[dict] = []
                    for candidate in planned:
                        target = candidate["target"]
                        if target.exists() and self._rename_path_key(target) not in source_keys:
                            skip(candidate["source"], "target_already_exists")
                            changed = True
                        else:
                            kept.append(candidate)
                    planned = kept

                if not planned:
                    skipped = sum(skipped_by_reason.values())
                    message = self._rename_summary_message(0, unchanged, skipped)
                    self._monitor_state().log_event("MANUAL_FILE_RENAME", f"renamed=0 unchanged={unchanged} skipped={skipped}")
                    self.append_event(
                        "invoice.files_renamed",
                        {"target_id": self.active_profile.id, "renamed": 0, "unchanged": unchanged, "skipped": skipped, "format": INVOICE_RENAME_FORMAT},
                        task_id=task_id,
                    )
                    return finish(
                        True,
                        message,
                        validation=validation,
                        preflight=preflight,
                        scanned=len(source_files),
                        unchanged=unchanged,
                        skipped=skipped,
                        skipped_by_reason=skipped_by_reason,
                        files=outcomes[:INVOICE_RENAME_DETAILS_LIMIT],
                    )

                staged: list[dict] = []
                try:
                    for index, candidate in enumerate(planned, start=1):
                        source = candidate["source"]
                        temporary = source.with_name(f".invoice-hub-rename-{task_id[:8]}-{index}{source.suffix.lower()}")
                        collision = 1
                        while temporary.exists():
                            temporary = source.with_name(f".invoice-hub-rename-{task_id[:8]}-{index}-{collision}{source.suffix.lower()}")
                            collision += 1
                        source.rename(temporary)
                        staged.append({**candidate, "temporary": temporary})
                except OSError as exc:
                    rollback_errors = []
                    for candidate in reversed(staged):
                        try:
                            candidate["temporary"].rename(candidate["source"])
                        except OSError as rollback_error:
                            rollback_errors.append(str(rollback_error))
                    detail = f"\u6682\u5b58\u91cd\u547d\u540d\u5931\u8d25\uff1a{exc}"
                    if rollback_errors:
                        detail += f"\uff1b\u56de\u6eda\u5931\u8d25\uff1a{' | '.join(rollback_errors)}"
                    return finish(False, detail, validation=validation, preflight=preflight, scanned=len(source_files), unchanged=unchanged, skipped=sum(skipped_by_reason.values()), skipped_by_reason=skipped_by_reason, files=outcomes[:INVOICE_RENAME_DETAILS_LIMIT])

                committed: list[dict] = []
                try:
                    for candidate in staged:
                        candidate["temporary"].rename(candidate["target"])
                        committed.append(candidate)
                except OSError as exc:
                    rollback_errors = []
                    for candidate in reversed(committed):
                        try:
                            candidate["target"].rename(candidate["source"])
                        except OSError as rollback_error:
                            rollback_errors.append(str(rollback_error))
                    for candidate in reversed(staged[len(committed):]):
                        try:
                            candidate["temporary"].rename(candidate["source"])
                        except OSError as rollback_error:
                            rollback_errors.append(str(rollback_error))
                    detail = f"\u5199\u5165\u65b0\u6587\u4ef6\u540d\u5931\u8d25\uff1a{exc}"
                    if rollback_errors:
                        detail += f"\uff1b\u56de\u6eda\u5931\u8d25\uff1a{' | '.join(rollback_errors)}"
                    return finish(False, detail, validation=validation, preflight=preflight, scanned=len(source_files), unchanged=unchanged, skipped=sum(skipped_by_reason.values()), skipped_by_reason=skipped_by_reason, files=outcomes[:INVOICE_RENAME_DETAILS_LIMIT])

                renamed_paths = [(candidate["source"], candidate["target"]) for candidate in committed]
                overrides_migrated = self._migrate_renamed_manual_overrides(renamed_paths)
                for source, target in renamed_paths:
                    outcomes.append({"status": "renamed", "old_path": str(source), "old_name": source.name, "new_path": str(target), "new_name": target.name})
                self._clear_invoice_cache()
                rebuilt = self.bridge_rebuild()
                renamed = len(renamed_paths)
                skipped = sum(skipped_by_reason.values())
                message = self._rename_summary_message(renamed, unchanged, skipped)
                self._monitor_state().log_event("MANUAL_FILE_RENAME", f"renamed={renamed} unchanged={unchanged} skipped={skipped} manual_overrides_migrated={overrides_migrated}")
                self.append_event(
                    "invoice.files_renamed",
                    {
                        "target_id": self.active_profile.id,
                        "renamed": renamed,
                        "unchanged": unchanged,
                        "skipped": skipped,
                        "manual_overrides_migrated": overrides_migrated,
                        "format": INVOICE_RENAME_FORMAT,
                    },
                    task_id=task_id,
                )
                if not rebuilt.get("ok"):
                    return finish(
                        False,
                        f"{message} \u4f46\u91cd\u547d\u540d\u540e\u7684\u91cd\u65b0\u6c47\u603b\u5931\u8d25\uff1a{rebuilt.get('error') or '\u672a\u77e5\u9519\u8bef'}",
                        validation=validation,
                        preflight=preflight,
                        rebuild=rebuilt,
                        scanned=len(source_files),
                        renamed=renamed,
                        unchanged=unchanged,
                        skipped=skipped,
                        skipped_by_reason=skipped_by_reason,
                        files=outcomes[:INVOICE_RENAME_DETAILS_LIMIT],
                        manual_overrides_migrated=overrides_migrated,
                    )
                return finish(
                    True,
                    message,
                    validation=validation,
                    preflight=preflight,
                    rebuild=rebuilt,
                    scanned=len(source_files),
                    renamed=renamed,
                    unchanged=unchanged,
                    skipped=skipped,
                    skipped_by_reason=skipped_by_reason,
                    files=outcomes[:INVOICE_RENAME_DETAILS_LIMIT],
                    manual_overrides_migrated=overrides_migrated,
                )
        except Exception as exc:
            return finish(False, f"\u53d1\u7968\u6587\u4ef6\u91cd\u547d\u540d\u5931\u8d25\uff1a{exc}", validation=validation, preflight=preflight, skipped_by_reason=skipped_by_reason, files=outcomes[:INVOICE_RENAME_DETAILS_LIMIT])
