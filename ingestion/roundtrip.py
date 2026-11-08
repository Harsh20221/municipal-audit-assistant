"""Compare layer 1-3 findings for the same cases before and after PDF ingest."""

from __future__ import annotations

from collections import Counter

from sqlalchemy import select
from sqlalchemy.orm import Session

from core.db import FindingRow
from families.base import DocumentFamily

CASE_CATEGORIES = (
    "clean",
    "hard_negative",
    "single_error",
    "multi_error",
    "needs_layer4",
)


def layer_rule_counts(
    session: Session,
    families: list[DocumentFamily],
    case_ids: set[str],
) -> dict[str, Counter]:
    counts = {case_id: Counter() for case_id in case_ids}
    for family in families:
        rows = session.scalars(
            select(FindingRow).where(FindingRow.family == family.name, FindingRow.layer < 4)
        ).all()
        for finding in rows:
            case_id = family.case_key_for_finding(session, finding.entity_type, finding.entity_id)
            if case_id in counts:
                counts[case_id][finding.rule_id] += 1
    return counts


def agreement_summary(before: dict[str, Counter], after: dict[str, Counter]) -> dict:
    agreed = []
    mismatched = []
    for case_id in sorted(before):
        if before[case_id] == after.get(case_id, Counter()):
            agreed.append(case_id)
        else:
            mismatched.append(
                {
                    "case_id": case_id,
                    "structured": dict(before[case_id]),
                    "pdf": dict(after.get(case_id, Counter())),
                }
            )
    return {
        "compared": len(before),
        "agreed": len(agreed),
        "mismatched": len(mismatched),
        "details": mismatched,
    }


def format_rules(counts: Counter) -> str:
    if not counts:
        return "-"
    parts = []
    for rule_id in sorted(counts):
        count = counts[rule_id]
        parts.append(rule_id if count == 1 else f"{rule_id}x{count}")
    return ",".join(parts)


def render_case_table(
    before: dict[str, Counter],
    after: dict[str, Counter],
    meta: dict[str, dict[str, str]],
) -> str:
    """One row per case. meta maps case_id to family and category."""
    header = ("case_id", "family", "category", "structured_rules", "pdf_rules", "agree")
    body = []
    for case_id in sorted(before, key=lambda item: _table_sort(item, meta)):
        info = meta.get(case_id, {})
        structured = format_rules(before[case_id])
        pdf = format_rules(after.get(case_id, Counter()))
        agree = "yes" if before[case_id] == after.get(case_id, Counter()) else "no"
        body.append(
            (
                case_id,
                info.get("family", ""),
                info.get("category", ""),
                structured,
                pdf,
                agree,
            )
        )
    widths = [
        max(len(header[index]), *(len(row[index]) for row in body)) if body else len(header[index])
        for index in range(len(header))
    ]
    lines = [_join(header, widths), _join(tuple("-" * width for width in widths), widths)]
    lines.extend(_join(row, widths) for row in body)
    return "\n".join(lines)


def same_value(left: object, right: object) -> bool:
    if left == right:
        return True
    if isinstance(left, bool) or isinstance(right, bool):
        return False
    try:
        return abs(float(left) - float(right)) <= 0.001
    except (TypeError, ValueError):
        return str(left).strip() == str(right).strip()


def field_differences(
    extracted: dict | None, ground_truth: dict
) -> list[tuple[str, object, object]]:
    """Pairs of (field, extracted, ground_truth) that do not match.

    document_copy is printed on the PDF so duplicate files hash differently.
    It is not an extracted field.
    """
    if extracted is None:
        return [("*", None, "no extraction stored")]
    keys = sorted((set(extracted) | set(ground_truth)) - {"document_copy"})
    return [
        (key, extracted.get(key), ground_truth.get(key))
        for key in keys
        if not same_value(extracted.get(key), ground_truth.get(key))
    ]


def render_value_diffs(rows: list[dict]) -> str:
    if not rows:
        return "value_differences=0"
    lines = ["value_differences:"]
    for row in rows:
        lines.append(
            f"  {row['case_id']} {row['doc_type']} {row['field']}: "
            f"extracted={row['extracted']!r} ground_truth={row['ground_truth']!r}"
        )
    return "\n".join(lines)


def _table_sort(case_id: str, meta: dict[str, dict[str, str]]) -> tuple:
    info = meta.get(case_id, {})
    category = info.get("category", "")
    rank = CASE_CATEGORIES.index(category) if category in CASE_CATEGORIES else len(CASE_CATEGORIES)
    return (info.get("family", ""), rank, case_id)


def _join(columns: tuple[str, ...], widths: list[int]) -> str:
    return "  ".join(column.ljust(widths[index]) for index, column in enumerate(columns))
