"""Two text layouts. Both keep a real text layer so PyMuPDF can read them."""

from __future__ import annotations

import hashlib
from dataclasses import dataclass
from datetime import date
from pathlib import Path

from reportlab.pdfgen import canvas

from ingestion.normalizers import AMOUNT_FIELDS, format_date, format_inr


@dataclass(frozen=True)
class PdfSpec:
    family: str
    case_id: str
    doc_type: str
    layout: str
    title: str
    fields: dict


def layout_for(case_id: str) -> str:
    digits = "".join(character for character in case_id if character.isdigit())
    return "compact" if digits and int(digits) % 2 else "standard"


def display_value(name: str, value: object) -> str:
    if value is None:
        return ""
    if isinstance(value, date):
        return format_date(value)
    if isinstance(value, bool):
        return str(value)
    if name in AMOUNT_FIELDS and isinstance(value, int | float):
        return format_inr(float(value))
    if isinstance(value, float):
        return f"{value:.2f}"
    return str(value).encode("latin-1", "replace").decode("latin-1")


def field_lines(fields: dict) -> list[str]:
    return [f"{name}: {display_value(name, value)}" for name, value in fields.items()]


def write_pdf(spec: PdfSpec, path: Path) -> str:
    path.parent.mkdir(parents=True, exist_ok=True)
    pen = canvas.Canvas(str(path))
    pen.setTitle(spec.title)
    pen.setFont("Helvetica", 10)
    lines = field_lines(spec.fields)
    if spec.layout == "compact":
        _draw_columns(pen, spec.title, lines)
    else:
        _draw_stack(pen, spec.title, lines)
    pen.save()
    digest = hashlib.sha256(path.read_bytes()).hexdigest()
    return digest


def _draw_stack(pen: canvas.Canvas, title: str, lines: list[str]) -> None:
    y = 800
    pen.drawString(40, y, _latin(title))
    y -= 22
    for line in lines:
        if y < 40:
            pen.showPage()
            pen.setFont("Helvetica", 10)
            y = 800
        pen.drawString(40, y, _latin(line[:110]))
        y -= 16


def _draw_columns(pen: canvas.Canvas, title: str, lines: list[str]) -> None:
    pen.setFont("Helvetica", 8)
    pen.drawString(40, 820, _latin(title))
    midpoint = (len(lines) + 1) // 2
    columns = (lines[:midpoint], lines[midpoint:])
    for column, x in zip(columns, (40, 320), strict=False):
        y = 800
        for line in column:
            pen.drawString(x, y, _latin(line[:48]))
            y -= 14


def _latin(text: str) -> str:
    return text.encode("latin-1", "replace").decode("latin-1")
