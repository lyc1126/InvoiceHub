from __future__ import annotations

import io
import re
import secrets
import threading
import time
import warnings
import xml.etree.ElementTree as ET
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta
from pathlib import Path

from invoice_hub.services.document_rendering import (
    MuPDFRendererUnavailableError,
    MuPDFRenderingError,
    open_mupdf_document,
    render_mupdf_page,
)


PREVIEW_DPI = 150
PREVIEW_JOB_TTL_SECONDS = 15 * 60
MAX_PREVIEW_SELECTION_RECORDS = 100
MAX_PREVIEW_PAGES = 200
MAX_PREVIEW_PAGE_PIXELS = 30_000_000
MAX_PREVIEW_JOB_BYTES = 128 * 1024 * 1024
MAX_PREVIEW_CACHE_BYTES = 256 * 1024 * 1024
MAX_PREVIEW_XML_BYTES = 2 * 1024 * 1024
MAX_PREVIEW_JOBS = 8

DOCUMENT_EXTENSIONS = {".pdf", ".ofd"}
RASTER_IMAGE_EXTENSIONS = {".png", ".jpg", ".jpeg", ".bmp", ".tif", ".tiff", ".webp", ".gif"}
PREVIEW_IMAGE_EXTENSIONS = {*RASTER_IMAGE_EXTENSIONS, ".svg"}

_PREVIEW_JOB_ID = re.compile(r"^[A-Za-z0-9_-]{20,80}$")
_XML_DECLARATION_ENCODING = re.compile(br"<\?xml\s+[^>]*encoding\s*=\s*['\"]\s*([^'\"\s]+)", re.I)
_SVG_FORBIDDEN_DECLARATION = re.compile(br"<!\s*(?:DOCTYPE|ENTITY)\b", re.I)
_SVG_EXTERNAL_REFERENCE = re.compile(r"(?:https?:|file:|data:|javascript:|//)", re.I)
_SVG_URL = re.compile(r"url\(\s*(['\"]?)(.*?)\1\s*\)", re.I)


class FilePreviewError(Exception):
    def __init__(self, message: str, *, code: str, status_code: int = 422):
        super().__init__(message)
        self.code = code
        self.status_code = status_code


@dataclass(frozen=True)
class FilePreviewSource:
    path: Path
    display_name: str


@dataclass(frozen=True)
class FileSignature:
    size: int
    mtime_ns: int


@dataclass(frozen=True)
class FilePreviewPage:
    content: bytes
    width_pixels: int
    height_pixels: int
    orientation: str


@dataclass(frozen=True)
class FilePreviewText:
    content: str
    encoding: str
    truncated: bool
    had_replacements: bool

    @property
    def byte_size(self) -> int:
        return len(self.content.encode("utf-8"))


@dataclass
class FilePreviewEntry:
    file_number: int
    path: Path
    display_name: str
    file_name: str
    extension: str
    size: int
    modified_at: str
    signature: FileSignature
    preview_type: str
    page_count: int = 0
    reason: str = ""
    error_code: str = ""
    text_truncated: bool = False
    pages: dict[int, FilePreviewPage] = field(default_factory=dict)
    text: FilePreviewText | None = None

    @property
    def cached_bytes(self) -> int:
        return sum(len(page.content) for page in self.pages.values()) + (self.text.byte_size if self.text else 0)


@dataclass
class FilePreviewJob:
    job_id: str
    created_at: str
    expires_at: str
    expires_monotonic: float
    record_count: int
    files: tuple[FilePreviewEntry, ...]

    @property
    def cached_bytes(self) -> int:
        return sum(item.cached_bytes for item in self.files)

    @property
    def renderable_page_count(self) -> int:
        return sum(item.page_count for item in self.files if item.preview_type == "pages")


def _timestamp_text(value: float) -> str:
    return datetime.fromtimestamp(value, UTC).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def _source_signature(path: Path) -> FileSignature:
    try:
        stat = path.stat()
    except OSError as exc:
        raise FilePreviewError(
            "源文件已被移动或删除，请刷新列表后重新勾选。",
            code="source_changed",
            status_code=409,
        ) from exc
    if not path.is_file():
        raise FilePreviewError(
            "源文件已被移动或删除，请刷新列表后重新勾选。",
            code="source_changed",
            status_code=409,
        )
    return FileSignature(size=stat.st_size, mtime_ns=stat.st_mtime_ns)


def _require_pillow():
    try:
        from PIL import Image, ImageOps  # type: ignore
    except ImportError as exc:
        raise FilePreviewError(
            "图片预览组件不可用，请重启系统后重试。",
            code="renderer_unavailable",
            status_code=503,
        ) from exc
    return Image, ImageOps


def _image_frame_count(path: Path) -> int:
    Image, _ImageOps = _require_pillow()
    try:
        with warnings.catch_warnings():
            warnings.simplefilter("error", Image.DecompressionBombWarning)
            with Image.open(path) as image:
                frame_count = max(1, int(getattr(image, "n_frames", 1) or 1))
                for frame_index in range(frame_count):
                    image.seek(frame_index)
                    width, height = image.size
                    if width <= 0 or height <= 0 or width * height > MAX_PREVIEW_PAGE_PIXELS:
                        raise FilePreviewError(
                            f"图片第 {frame_index + 1} 帧尺寸超过安全上限。",
                            code="page_size_unsupported",
                            status_code=400,
                        )
                return frame_count
    except FilePreviewError:
        raise
    except Exception as exc:
        raise FilePreviewError("图片文件无法解码。", code="image_render_failed") from exc


def _render_image_frame(path: Path, page_number: int) -> FilePreviewPage:
    Image, ImageOps = _require_pillow()
    try:
        with warnings.catch_warnings():
            warnings.simplefilter("error", Image.DecompressionBombWarning)
            with Image.open(path) as image:
                frame_count = max(1, int(getattr(image, "n_frames", 1) or 1))
                if page_number < 1 or page_number > frame_count:
                    raise FilePreviewError("预览页面不存在。", code="page_not_found", status_code=404)
                image.seek(page_number - 1)
                frame = ImageOps.exif_transpose(image.copy()).convert("RGBA")
                width, height = frame.size
                if width <= 0 or height <= 0 or width * height > MAX_PREVIEW_PAGE_PIXELS:
                    raise FilePreviewError("图片尺寸超过安全上限。", code="page_size_unsupported", status_code=400)
                background = Image.new("RGB", frame.size, "white")
                background.paste(frame, mask=frame.getchannel("A"))
                output = io.BytesIO()
                background.save(output, format="PNG")
                return FilePreviewPage(
                    content=output.getvalue(),
                    width_pixels=width,
                    height_pixels=height,
                    orientation="landscape" if width > height else "portrait",
                )
    except FilePreviewError:
        raise
    except Exception as exc:
        raise FilePreviewError(
            "图片渲染失败，请确认文件可以正常打开后重试。",
            code="image_render_failed",
        ) from exc


def _svg_local_name(value: str) -> str:
    return value.rsplit("}", 1)[-1].casefold()


def _validate_svg_style(value: str) -> None:
    if "@import" in value.casefold() or _SVG_EXTERNAL_REFERENCE.search(value):
        raise FilePreviewError("SVG 包含外部资源引用，已拒绝预览。", code="unsafe_svg")
    for matched in _SVG_URL.finditer(value):
        if not matched.group(2).strip().startswith("#"):
            raise FilePreviewError("SVG 包含外部资源引用，已拒绝预览。", code="unsafe_svg")


def _safe_svg_bytes(path: Path) -> bytes:
    try:
        with path.open("rb") as handle:
            content = handle.read(MAX_PREVIEW_JOB_BYTES + 1)
    except OSError as exc:
        raise FilePreviewError("SVG 文件无法读取。", code="svg_render_failed") from exc
    if len(content) > MAX_PREVIEW_JOB_BYTES:
        raise FilePreviewError("SVG 文件超过安全大小上限。", code="job_too_large", status_code=400)
    if _SVG_FORBIDDEN_DECLARATION.search(content):
        raise FilePreviewError("SVG 包含 DTD 或实体声明，已拒绝预览。", code="unsafe_svg")
    try:
        root = ET.fromstring(content)
    except ET.ParseError as exc:
        raise FilePreviewError("SVG 结构无效，无法预览。", code="svg_render_failed") from exc
    if _svg_local_name(root.tag) != "svg":
        raise FilePreviewError("文件不是有效 SVG。", code="svg_render_failed")
    for element in root.iter():
        name = _svg_local_name(element.tag)
        if name in {"script", "foreignobject", "iframe", "object", "embed"}:
            raise FilePreviewError("SVG 包含主动内容，已拒绝预览。", code="unsafe_svg")
        if name == "style":
            _validate_svg_style(element.text or "")
        for raw_name, raw_value in element.attrib.items():
            attr_name = _svg_local_name(raw_name)
            value = str(raw_value or "").strip()
            if attr_name.startswith("on"):
                raise FilePreviewError("SVG 包含脚本事件，已拒绝预览。", code="unsafe_svg")
            if attr_name in {"href", "src"} and value and not value.startswith("#"):
                raise FilePreviewError("SVG 包含外部资源引用，已拒绝预览。", code="unsafe_svg")
            if attr_name == "style":
                _validate_svg_style(value)
            elif _SVG_EXTERNAL_REFERENCE.search(value):
                raise FilePreviewError("SVG 包含外部资源引用，已拒绝预览。", code="unsafe_svg")
    return content


def _mupdf_page_count(path: Path, extension: str) -> int:
    try:
        if extension == ".svg":
            with open_mupdf_document(content=_safe_svg_bytes(path), file_type="svg") as document:
                return int(document.page_count)
        with open_mupdf_document(path) as document:
            return int(document.page_count)
    except MuPDFRendererUnavailableError as exc:
        raise FilePreviewError(
            "文件预览组件不可用，请重启系统后重试。",
            code="renderer_unavailable",
            status_code=503,
        ) from exc
    except MuPDFRenderingError as exc:
        messages = {
            "document_encrypted": "文件已加密，无法生成预览。",
            "document_empty": "文件没有可预览页面。",
        }
        raise FilePreviewError(messages.get(exc.code, "文件无法读取或格式已损坏。"), code=exc.code) from exc


def _render_mupdf_source(path: Path, extension: str, page_number: int) -> FilePreviewPage:
    try:
        manager = (
            open_mupdf_document(content=_safe_svg_bytes(path), file_type="svg")
            if extension == ".svg"
            else open_mupdf_document(path)
        )
        with manager as document:
            if page_number < 1 or page_number > document.page_count:
                raise FilePreviewError("预览页面不存在。", code="page_not_found", status_code=404)
            page = render_mupdf_page(
                document,
                page_number - 1,
                dpi=PREVIEW_DPI,
                max_pixels=MAX_PREVIEW_PAGE_PIXELS,
            )
            return FilePreviewPage(
                content=page.content,
                width_pixels=page.width_pixels,
                height_pixels=page.height_pixels,
                orientation=page.orientation,
            )
    except FilePreviewError:
        raise
    except MuPDFRendererUnavailableError as exc:
        raise FilePreviewError(
            "文件预览组件不可用，请重启系统后重试。",
            code="renderer_unavailable",
            status_code=503,
        ) from exc
    except MuPDFRenderingError as exc:
        if exc.code == "page_size_unsupported":
            raise FilePreviewError("页面尺寸超过安全上限。", code=exc.code, status_code=400) from exc
        if exc.code == "page_not_found":
            raise FilePreviewError("预览页面不存在。", code=exc.code, status_code=404) from exc
        message = "文件已加密，无法生成预览。" if exc.code == "document_encrypted" else "文件渲染失败，请确认文件可以正常打开后重试。"
        raise FilePreviewError(message, code=exc.code) from exc


def _declared_xml_encoding(content: bytes) -> str:
    sample = content[:512].replace(b"\x00", b"")
    matched = _XML_DECLARATION_ENCODING.search(sample)
    if not matched:
        return ""
    try:
        return matched.group(1).decode("ascii").strip().casefold()
    except UnicodeDecodeError:
        return ""


def _decode_xml(content: bytes, *, truncated: bool) -> FilePreviewText:
    authoritative_encoding = True
    if content.startswith(b"\xef\xbb\xbf"):
        candidates = ["utf-8-sig"]
    elif content.startswith((b"\xff\xfe", b"\xfe\xff")):
        candidates = ["utf-16"]
    elif content.startswith(b"\x00<\x00?"):
        candidates = ["utf-16-be"]
    elif content.startswith(b"<\x00?\x00"):
        candidates = ["utf-16-le"]
    else:
        declared = _declared_xml_encoding(content)
        aliases = {
            "utf8": "utf-8",
            "utf_8": "utf-8",
            "utf-8": "utf-8",
            "utf-8-sig": "utf-8-sig",
            "utf16": "utf-16",
            "utf-16": "utf-16",
            "utf-16le": "utf-16-le",
            "utf-16-le": "utf-16-le",
            "utf-16be": "utf-16-be",
            "utf-16-be": "utf-16-be",
            "gb2312": "gb18030",
            "gbk": "gb18030",
            "gb18030": "gb18030",
            "gb_2312-80": "gb18030",
        }
        if declared:
            candidates = [aliases.get(declared, "utf-8")]
        else:
            authoritative_encoding = False
            candidates = ["utf-8", "gb18030"]

    unique_candidates: list[str] = []
    for candidate in candidates:
        if candidate and candidate not in unique_candidates:
            unique_candidates.append(candidate)
    for encoding in unique_candidates:
        try:
            return FilePreviewText(content.decode(encoding), encoding, truncated, False)
        except (LookupError, UnicodeDecodeError):
            continue
    fallback = unique_candidates[0] if authoritative_encoding and unique_candidates else "utf-8"
    try:
        text = content.decode(fallback, errors="replace")
    except (LookupError, UnicodeError):
        fallback = "utf-8"
        text = content.decode(fallback, errors="replace")
    return FilePreviewText(text, fallback, truncated, True)


class FilePreviewService:
    def __init__(self) -> None:
        self._lock = threading.RLock()
        self._jobs: dict[str, FilePreviewJob] = {}
        self._tombstones: dict[str, float] = {}

    def _mark_expired_locked(self, job_id: str, now: float) -> None:
        self._jobs.pop(job_id, None)
        self._tombstones[job_id] = now + PREVIEW_JOB_TTL_SECONDS

    def _remove_expired_locked(self, now: float) -> None:
        for job_id, job in list(self._jobs.items()):
            if job.expires_monotonic <= now:
                self._mark_expired_locked(job_id, now)
        for job_id, tombstone_expiry in list(self._tombstones.items()):
            if tombstone_expiry <= now:
                self._tombstones.pop(job_id, None)

    @staticmethod
    def _renew_job_locked(job: FilePreviewJob, now_monotonic: float) -> None:
        # The preview dialog can remain open while the user reads a page. Treat the
        # TTL as an idle timeout so active viewers are not disconnected mid-session.
        now_datetime = datetime.now(UTC)
        job.expires_at = (
            now_datetime + timedelta(seconds=PREVIEW_JOB_TTL_SECONDS)
        ).replace(microsecond=0).isoformat().replace("+00:00", "Z")
        job.expires_monotonic = now_monotonic + PREVIEW_JOB_TTL_SECONDS

    def _make_job_capacity_locked(self, now: float) -> None:
        while len(self._jobs) >= MAX_PREVIEW_JOBS:
            oldest_id = min(self._jobs, key=lambda item: self._jobs[item].expires_monotonic)
            self._mark_expired_locked(oldest_id, now)

    def _make_byte_capacity_locked(self, incoming_bytes: int, *, protected_job_id: str) -> None:
        def total_bytes() -> int:
            return sum(job.cached_bytes for job in self._jobs.values())

        candidates = [job_id for job_id in self._jobs if job_id != protected_job_id]
        while candidates and total_bytes() + incoming_bytes > MAX_PREVIEW_CACHE_BYTES:
            oldest_id = min(candidates, key=lambda item: self._jobs[item].expires_monotonic)
            self._mark_expired_locked(oldest_id, time.monotonic())
            candidates.remove(oldest_id)
        if total_bytes() + incoming_bytes > MAX_PREVIEW_CACHE_BYTES:
            raise FilePreviewError(
                "预览缓存已达到容量上限，请关闭其它预览后重试。",
                code="cache_capacity_exceeded",
                status_code=400,
            )

    @staticmethod
    def _entry_for_source(source: FilePreviewSource, file_number: int) -> FilePreviewEntry:
        path = source.path
        signature = _source_signature(path)
        extension = path.suffix.casefold()
        preview_type = "metadata"
        page_count = 0
        reason = ""
        error_code = ""
        text_truncated = extension == ".xml" and signature.size > MAX_PREVIEW_XML_BYTES
        try:
            if extension in DOCUMENT_EXTENSIONS or extension == ".svg":
                preview_type = "pages"
                page_count = _mupdf_page_count(path, extension)
            elif extension in RASTER_IMAGE_EXTENSIONS:
                preview_type = "pages"
                page_count = _image_frame_count(path)
            elif extension == ".xml":
                preview_type = "text"
            else:
                reason = "此格式不支持在页面内显示内容，可使用系统打开。"
        except FilePreviewError as exc:
            if exc.status_code in {400, 503}:
                raise
            preview_type = "error"
            reason = str(exc)
            error_code = exc.code
        return FilePreviewEntry(
            file_number=file_number,
            path=path,
            display_name=source.display_name,
            file_name=path.name,
            extension=extension.lstrip(".") or "unknown",
            size=signature.size,
            modified_at=_timestamp_text(signature.mtime_ns / 1_000_000_000),
            signature=signature,
            preview_type=preview_type,
            page_count=page_count,
            reason=reason,
            error_code=error_code,
            text_truncated=text_truncated,
        )

    def create_job(self, sources: list[FilePreviewSource]) -> FilePreviewJob:
        if not sources:
            raise FilePreviewError("请至少勾选一个源文件。", code="empty_selection", status_code=400)
        if len(sources) > MAX_PREVIEW_SELECTION_RECORDS:
            raise FilePreviewError(
                f"单次最多预览 {MAX_PREVIEW_SELECTION_RECORDS} 条文件记录。",
                code="too_many_records",
                status_code=400,
            )
        entries: list[FilePreviewEntry] = []
        renderable_pages = 0
        for file_number, source in enumerate(sources, start=1):
            entry = self._entry_for_source(source, file_number)
            renderable_pages += entry.page_count if entry.preview_type == "pages" else 0
            if renderable_pages > MAX_PREVIEW_PAGES:
                raise FilePreviewError(
                    f"本次预览超过 {MAX_PREVIEW_PAGES} 个可渲染页面，请减少勾选数量后重试。",
                    code="too_many_pages",
                    status_code=400,
                )
            entries.append(entry)
        now_datetime = datetime.now(UTC)
        now_monotonic = time.monotonic()
        job = FilePreviewJob(
            job_id=secrets.token_urlsafe(24),
            created_at=now_datetime.replace(microsecond=0).isoformat().replace("+00:00", "Z"),
            expires_at=(now_datetime + timedelta(seconds=PREVIEW_JOB_TTL_SECONDS))
            .replace(microsecond=0)
            .isoformat()
            .replace("+00:00", "Z"),
            expires_monotonic=now_monotonic + PREVIEW_JOB_TTL_SECONDS,
            record_count=len(sources),
            files=tuple(entries),
        )
        with self._lock:
            self._remove_expired_locked(now_monotonic)
            self._make_job_capacity_locked(now_monotonic)
            self._jobs[job.job_id] = job
        return job

    def get_job(self, job_id: str, *, renew: bool = True) -> FilePreviewJob:
        if not _PREVIEW_JOB_ID.fullmatch(str(job_id or "")):
            raise FilePreviewError("预览作业不存在。", code="job_not_found", status_code=404)
        now = time.monotonic()
        with self._lock:
            self._remove_expired_locked(now)
            job = self._jobs.get(job_id)
            expired = job_id in self._tombstones
            if job is not None and renew:
                self._renew_job_locked(job, now)
        if job is not None:
            return job
        if expired:
            raise FilePreviewError("预览作业已过期，请重新打开预览。", code="job_expired", status_code=410)
        raise FilePreviewError("预览作业不存在。", code="job_not_found", status_code=404)

    def keep_alive(self, job_id: str) -> FilePreviewJob:
        return self.get_job(job_id, renew=True)

    def get_file(self, job_id: str, file_number: int, *, verify_source: bool = True) -> FilePreviewEntry:
        job = self.get_job(job_id)
        if file_number < 1 or file_number > len(job.files):
            raise FilePreviewError("预览文件不存在。", code="file_not_found", status_code=404)
        entry = job.files[file_number - 1]
        if verify_source and _source_signature(entry.path) != entry.signature:
            raise FilePreviewError(
                "源文件已发生变化，请关闭弹窗后重新勾选。",
                code="source_changed",
                status_code=409,
            )
        return entry

    def _store_page(self, job_id: str, entry: FilePreviewEntry, page_number: int, page: FilePreviewPage) -> FilePreviewPage:
        incoming_bytes = len(page.content)
        with self._lock:
            job = self.get_job(job_id)
            current_entry = job.files[entry.file_number - 1]
            cached = current_entry.pages.get(page_number)
            if cached is not None:
                return cached
            if job.cached_bytes + incoming_bytes > MAX_PREVIEW_JOB_BYTES:
                raise FilePreviewError(
                    "本次预览数据超过容量上限，请减少勾选数量后重试。",
                    code="job_too_large",
                    status_code=400,
                )
            self._make_byte_capacity_locked(incoming_bytes, protected_job_id=job_id)
            current_entry.pages[page_number] = page
            return page

    def get_page(self, job_id: str, file_number: int, page_number: int) -> FilePreviewPage:
        entry = self.get_file(job_id, file_number)
        if entry.preview_type == "error":
            raise FilePreviewError(entry.reason or "文件无法渲染。", code=entry.error_code or "render_failed")
        if entry.preview_type != "pages" or page_number < 1 or page_number > entry.page_count:
            raise FilePreviewError("预览页面不存在。", code="page_not_found", status_code=404)
        with self._lock:
            cached = entry.pages.get(page_number)
        if cached is not None:
            return cached
        if entry.path.suffix.casefold() in RASTER_IMAGE_EXTENSIONS:
            page = _render_image_frame(entry.path, page_number)
        else:
            page = _render_mupdf_source(entry.path, entry.path.suffix.casefold(), page_number)
        if _source_signature(entry.path) != entry.signature:
            raise FilePreviewError(
                "源文件已发生变化，请关闭弹窗后重新勾选。",
                code="source_changed",
                status_code=409,
            )
        return self._store_page(job_id, entry, page_number, page)

    def get_text(self, job_id: str, file_number: int) -> FilePreviewText:
        entry = self.get_file(job_id, file_number)
        if entry.preview_type != "text":
            raise FilePreviewError("此文件没有文本预览。", code="text_not_found", status_code=404)
        with self._lock:
            cached = entry.text
        if cached is not None:
            return cached
        try:
            with entry.path.open("rb") as handle:
                raw = handle.read(MAX_PREVIEW_XML_BYTES + 1)
        except OSError as exc:
            raise FilePreviewError(
                "源文件已被移动或删除，请重新打开预览。",
                code="source_changed",
                status_code=409,
            ) from exc
        truncated = len(raw) > MAX_PREVIEW_XML_BYTES
        text = _decode_xml(raw[:MAX_PREVIEW_XML_BYTES], truncated=truncated)
        if _source_signature(entry.path) != entry.signature:
            raise FilePreviewError(
                "源文件已发生变化，请关闭弹窗后重新勾选。",
                code="source_changed",
                status_code=409,
            )
        with self._lock:
            job = self.get_job(job_id)
            current_entry = job.files[file_number - 1]
            if current_entry.text is not None:
                return current_entry.text
            if job.cached_bytes + text.byte_size > MAX_PREVIEW_JOB_BYTES:
                raise FilePreviewError(
                    "本次预览数据超过容量上限，请减少勾选数量后重试。",
                    code="job_too_large",
                    status_code=400,
                )
            self._make_byte_capacity_locked(text.byte_size, protected_job_id=job_id)
            current_entry.text = text
        return text

    def clear(self) -> None:
        with self._lock:
            self._jobs.clear()
            self._tombstones.clear()
