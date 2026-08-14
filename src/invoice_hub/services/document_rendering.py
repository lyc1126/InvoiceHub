from __future__ import annotations

import math
from contextlib import contextmanager
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Iterator


class MuPDFRenderingError(Exception):
    def __init__(self, code: str):
        super().__init__(code)
        self.code = code


class MuPDFRendererUnavailableError(MuPDFRenderingError):
    def __init__(self) -> None:
        super().__init__("renderer_unavailable")


@dataclass(frozen=True)
class MuPDFPageImage:
    content: bytes
    width_pixels: int
    height_pixels: int
    orientation: str


def _fitz() -> Any:
    try:
        import fitz  # type: ignore
    except ImportError as exc:
        raise MuPDFRendererUnavailableError() from exc
    return fitz


@contextmanager
def open_mupdf_document(
    path: Path | None = None,
    *,
    content: bytes | None = None,
    file_type: str | None = None,
) -> Iterator[Any]:
    fitz = _fitz()
    try:
        if content is None:
            if path is None:
                raise MuPDFRenderingError("document_open_failed")
            document = fitz.open(str(path))
        else:
            document = fitz.open(stream=content, filetype=file_type)
    except MuPDFRenderingError:
        raise
    except Exception as exc:
        raise MuPDFRenderingError("document_open_failed") from exc

    try:
        if document.needs_pass:
            raise MuPDFRenderingError("document_encrypted")
        if document.page_count < 1:
            raise MuPDFRenderingError("document_empty")
        yield document
    finally:
        document.close()


def render_mupdf_page(
    document: Any,
    page_index: int,
    *,
    dpi: int,
    max_pixels: int,
) -> MuPDFPageImage:
    fitz = _fitz()
    try:
        if page_index < 0 or page_index >= document.page_count:
            raise MuPDFRenderingError("page_not_found")
        page = document.load_page(page_index)
        rect = page.rect
        scale = dpi / 72
        width_pixels = math.ceil(rect.width * scale)
        height_pixels = math.ceil(rect.height * scale)
        if width_pixels <= 0 or height_pixels <= 0 or width_pixels * height_pixels > max_pixels:
            raise MuPDFRenderingError("page_size_unsupported")
        pixmap = page.get_pixmap(
            matrix=fitz.Matrix(scale, scale),
            colorspace=fitz.csRGB,
            alpha=False,
            annots=True,
        )
        return MuPDFPageImage(
            content=pixmap.tobytes("png"),
            width_pixels=pixmap.width,
            height_pixels=pixmap.height,
            orientation="landscape" if rect.width > rect.height else "portrait",
        )
    except MuPDFRenderingError:
        raise
    except Exception as exc:
        raise MuPDFRenderingError("page_render_failed") from exc
