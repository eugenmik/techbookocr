"""Render DjVu through ctypes against the system libdjvulibre (no sudo, no binding build)."""
from __future__ import annotations

import ctypes as C
import logging
from pathlib import Path

from PIL import Image

_log = logging.getLogger("techbookocr.ingest")
_vp = C.c_void_p
_JOB_OK = 2  # DDJVU_JOB_OK; 3 = FAILED, 4 = STOPPED
_FORMAT_RGB24 = 1  # DDJVU_FORMAT_RGB24 (3 = RGBMASK32 needs masks -> segfault)
_RENDER_COLOR = 0

_SIGNATURES: dict[str, tuple[object, list]] = {
    "ddjvu_context_create": (_vp, [C.c_char_p]),
    "ddjvu_context_release": (None, [_vp]),
    "ddjvu_document_create_by_filename_utf8": (_vp, [_vp, C.c_char_p, C.c_int]),
    "ddjvu_document_job": (_vp, [_vp]),
    "ddjvu_document_get_pagenum": (C.c_int, [_vp]),
    "ddjvu_job_status": (C.c_int, [_vp]),
    "ddjvu_job_release": (None, [_vp]),
    "ddjvu_message_wait": (_vp, [_vp]),
    "ddjvu_message_peek": (_vp, [_vp]),
    "ddjvu_message_pop": (None, [_vp]),
    "ddjvu_page_create_by_pageno": (_vp, [_vp, C.c_int]),
    "ddjvu_page_job": (_vp, [_vp]),
    "ddjvu_page_get_width": (C.c_int, [_vp]),
    "ddjvu_page_get_height": (C.c_int, [_vp]),
    "ddjvu_page_get_resolution": (C.c_int, [_vp]),
    "ddjvu_format_create": (_vp, [C.c_int, C.c_int, _vp]),
    "ddjvu_format_set_row_order": (None, [_vp, C.c_int]),
    "ddjvu_format_release": (None, [_vp]),
    "ddjvu_page_render": (C.c_int, [_vp, C.c_int, _vp, _vp, _vp, C.c_ulong, C.c_char_p]),
}


class DjvuError(RuntimeError):
    """Failed to open or decode the DjVu."""


class _Rect(C.Structure):
    _fields_ = [("x", C.c_int), ("y", C.c_int), ("w", C.c_uint), ("h", C.c_uint)]


_lib: C.CDLL | None = None


def _L() -> C.CDLL:
    global _lib
    if _lib is None:
        lib = C.CDLL("libdjvulibre.so.21")
        for name, (restype, argtypes) in _SIGNATURES.items():
            fn = getattr(lib, name)
            fn.restype = restype
            fn.argtypes = argtypes
        _lib = lib
    return _lib


class DjvuDocument:
    def __init__(self, path: Path):
        L = _L()
        self.path = Path(path)
        self._ctx = L.ddjvu_context_create(b"techbookocr")
        self._doc = L.ddjvu_document_create_by_filename_utf8(self._ctx, str(self.path).encode(), 1)
        if not self._doc:
            L.ddjvu_context_release(self._ctx)
            raise DjvuError(f"cannot open {self.path}")
        try:
            self._wait(L.ddjvu_document_job(self._doc), f"document {self.path.name}")
        except DjvuError:
            self.close()
            raise
        self.page_count: int = L.ddjvu_document_get_pagenum(self._doc)
        self.last_render_blank = False

    def _wait(self, job, what: str) -> None:
        L = _L()
        while (status := L.ddjvu_job_status(job)) < _JOB_OK:
            L.ddjvu_message_wait(self._ctx)
            while L.ddjvu_message_peek(self._ctx):
                L.ddjvu_message_pop(self._ctx)
        if status > _JOB_OK:
            raise DjvuError(f"decoding failed: {what} (status {status})")

    def render(self, index: int, max_dpi: int = 600) -> tuple[Image.Image, int]:
        if not 0 <= index < self.page_count:
            raise IndexError(f"page {index} out of range 0..{self.page_count - 1}")
        L = _L()
        self.last_render_blank = False
        page = L.ddjvu_page_create_by_pageno(self._doc, index)
        if not page:
            raise DjvuError(f"cannot create page {index}")
        try:
            self._wait(L.ddjvu_page_job(page), f"page {index}")
            w, h = L.ddjvu_page_get_width(page), L.ddjvu_page_get_height(page)
            dpi = L.ddjvu_page_get_resolution(page) or 300
            if dpi > max_dpi:
                w, h, dpi = round(w * max_dpi / dpi), round(h * max_dpi / dpi), max_dpi
            rect = _Rect(0, 0, w, h)
            fmt = L.ddjvu_format_create(_FORMAT_RGB24, 0, None)
            L.ddjvu_format_set_row_order(fmt, 1)
            buf = C.create_string_buffer(w * h * 3)
            ok = L.ddjvu_page_render(page, _RENDER_COLOR, C.byref(rect), C.byref(rect), fmt, w * 3, buf)
            L.ddjvu_format_release(fmt)
            if not ok:  # empty page: nothing to render
                self.last_render_blank = True
                _log.warning("djvu page %d: ddjvu_page_render returned 0, substituting a white page", index)
                return Image.new("RGB", (w, h), "white"), dpi
            return Image.frombytes("RGB", (w, h), buf.raw), dpi
        finally:
            L.ddjvu_job_release(L.ddjvu_page_job(page))

    def close(self) -> None:
        L = _L()
        if self._doc:
            L.ddjvu_job_release(L.ddjvu_document_job(self._doc))
            self._doc = None
        if self._ctx:
            L.ddjvu_context_release(self._ctx)
            self._ctx = None

    def __enter__(self) -> "DjvuDocument":
        return self

    def __exit__(self, *exc) -> None:
        self.close()
