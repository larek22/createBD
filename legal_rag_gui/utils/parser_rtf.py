"""Document parsing helpers.

The actual vectorization pipeline supports several formats.  Here we implement a
minimal-yet-robust fallback approach – if optional dependencies are missing the
code still returns text instead of crashing.  This keeps the demo runnable in
restricted environments.
"""
from __future__ import annotations

from pathlib import Path
from typing import Callable, Dict


def _read_txt(path: Path) -> str:
    return path.read_text("utf-8", errors="ignore")


def _read_rtf(path: Path) -> str:
    try:
        from striprtf import rtf_to_text  # type: ignore

        return rtf_to_text(path.read_text("utf-8", errors="ignore"))
    except Exception:
        # Super-naive fallback
        return path.read_text("utf-8", errors="ignore").replace("\\par", "\n")


def _read_pdf(path: Path) -> str:
    try:
        from pdfminer.high_level import extract_text  # type: ignore

        return extract_text(str(path))
    except Exception:
        return ""


def _read_docx(path: Path) -> str:
    try:
        from docx import Document  # type: ignore

        doc = Document(str(path))
        return "\n".join(p.text for p in doc.paragraphs)
    except Exception:
        return ""


PARSERS: Dict[str, Callable[[Path], str]] = {
    ".txt": _read_txt,
    ".rtf": _read_rtf,
    ".pdf": _read_pdf,
    ".docx": _read_docx,
}


def extract_text(path: Path) -> str:
    """Return plain text for ``path``.

    Unknown extensions fall back to UTF-8 text read, again prioritising graceful
    degradation over strict failures.
    """

    parser = PARSERS.get(path.suffix.lower())
    if not parser:
        return _read_txt(path)
    return parser(path)


__all__ = ["extract_text", "PARSERS"]
