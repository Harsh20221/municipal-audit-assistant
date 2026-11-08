"""Read a digital PDF. Pages with no text layer are marked and skipped."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

import fitz


@dataclass(frozen=True)
class PageText:
    page: int
    text: str
    skipped: bool


@dataclass(frozen=True)
class PdfText:
    pages: list[PageText]
    text: str
    unsupported_scanned: bool


def read_pdf(path: Path) -> PdfText:
    document = fitz.open(path)
    try:
        pages = []
        for index, page in enumerate(document, start=1):
            text = page.get_text("text").strip()
            pages.append(PageText(page=index, text=text, skipped=text == ""))
        kept = [page.text for page in pages if not page.skipped]
        return PdfText(
            pages=pages,
            text="\n".join(kept),
            unsupported_scanned=not kept,
        )
    finally:
        document.close()
