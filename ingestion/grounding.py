"""Check that extracted numbers and IDs were actually printed on the page."""

from __future__ import annotations

import re
from datetime import date

from ingestion.normalizers import format_date, normalize_amount

_NUMBER = re.compile(r"-?\d+(?:\.\d+)?")


def ground_fields(
    fields: dict,
    page_text: str,
) -> tuple[dict[str, int], list[str]]:
    """Return a field->page map and low_confidence errors for invented values."""
    pages: dict[str, int] = {}
    errors: list[str] = []
    for name, value in fields.items():
        pages[name] = 1
        if value is None or value == "":
            continue
        if not value_in_text(value, page_text):
            errors.append(f"low_confidence:{name}")
    return pages, errors


def value_in_text(value: object, page_text: str) -> bool:
    if isinstance(value, date):
        return format_date(value) in page_text or value.isoformat() in page_text
    if isinstance(value, bool):
        return False
    if isinstance(value, int | float):
        return number_in_text(float(value), page_text)
    text = str(value).strip()
    if text == "":
        return True
    if text in page_text:
        return True
    try:
        return number_in_text(normalize_amount(text), page_text)
    except ValueError:
        return False


def number_in_text(value: float, page_text: str) -> bool:
    compact = page_text.replace(",", "")
    for token in _NUMBER.findall(compact):
        try:
            if abs(float(token) - value) <= 0.001:
                return True
        except ValueError:
            continue
    return False
