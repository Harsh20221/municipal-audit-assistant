"""English amount and date normalizers. These do not translate other languages."""

from __future__ import annotations

import re
from datetime import date

_CURRENCY = re.compile(r"₹|rs\.?|inr", re.IGNORECASE)
_AMOUNT = re.compile(r"^(-?\d+(?:\.\d+)?)(?:(lakh|lac|crore|cr))?$")
_DATE = re.compile(r"^(\d{1,2})[/-](\d{1,2})[/-](\d{2}|\d{4})$")

DATE_FIELDS = {
    "issue_date",
    "due_date",
    "paid_date",
    "invoice_date",
    "work_order_date",
    "start_date",
    "expected_end_date",
}
AMOUNT_FIELDS = {
    "assessed_tax",
    "exemption_amount",
    "amount_due",
    "penalty",
    "amount_paid",
    "tender_estimate",
    "award_value",
    "work_order_value",
    "amount",
    "budget",
}
INT_FIELDS = {"construction_year"}
FLOAT_FIELDS = {"built_up_area_sqft", "physical_pct", "financial_pct"}


def normalize_amount(value: object) -> float:
    if isinstance(value, bool) or value is None:
        raise ValueError(f"Not an amount: {value!r}")
    if isinstance(value, int | float):
        return float(value)
    text = _CURRENCY.sub("", str(value)).replace(",", "").replace(" ", "").lower()
    match = _AMOUNT.fullmatch(text)
    if match is None:
        raise ValueError(f"Not an amount: {value!r}")
    number = float(match.group(1))
    unit = match.group(2)
    if unit in {"lakh", "lac"}:
        number *= 100_000
    elif unit in {"crore", "cr"}:
        number *= 10_000_000
    return number


def normalize_date(value: object) -> date:
    if isinstance(value, date):
        return value
    text = str(value).strip()
    iso = _iso_date(text)
    if iso is not None:
        return iso
    match = _DATE.fullmatch(text)
    if match is None:
        raise ValueError(f"Not a date: {value!r}")
    day = int(match.group(1))
    month = int(match.group(2))
    year = _expand_year(match.group(3))
    return date(year, month, day)


def normalize_fields(fields: dict) -> dict:
    """Convert known amount and date strings. Leave anything else unchanged."""
    normalized = {}
    for key, value in fields.items():
        if value == "" or value is None:
            numeric = DATE_FIELDS | AMOUNT_FIELDS | INT_FIELDS | FLOAT_FIELDS
            normalized[key] = None if key in numeric else value
            continue
        try:
            if key in DATE_FIELDS:
                normalized[key] = normalize_date(value)
            elif key in AMOUNT_FIELDS or key in FLOAT_FIELDS:
                normalized[key] = normalize_amount(value)
            elif key in INT_FIELDS:
                normalized[key] = int(float(normalize_amount(value)))
            else:
                normalized[key] = value
        except ValueError:
            normalized[key] = value
    return normalized


def format_inr(value: float) -> str:
    """Indian grouping, prefixed with Rs so the PDF text stays in Latin-1."""
    sign = "-" if value < 0 else ""
    whole, frac = f"{abs(float(value)):.2f}".split(".")
    if len(whole) <= 3:
        grouped = whole
    else:
        head, tail = whole[:-3], whole[-3:]
        parts: list[str] = []
        while len(head) > 2:
            parts.append(head[-2:])
            head = head[:-2]
        if head:
            parts.append(head)
        grouped = ",".join(reversed(parts)) + "," + tail
    return f"{sign}Rs {grouped}.{frac}"


def format_date(value: date) -> str:
    return f"{value.day:02d}/{value.month:02d}/{value.year:04d}"


def _expand_year(text: str) -> int:
    year = int(text)
    if len(text) == 4:
        return year
    return 2000 + year if year < 70 else 1900 + year


def _iso_date(text: str) -> date | None:
    match = re.fullmatch(r"(\d{4})-(\d{2})-(\d{2})", text)
    if match is None:
        return None
    return date(int(match.group(1)), int(match.group(2)), int(match.group(3)))
