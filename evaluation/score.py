"""Print Tier B precision and recall. Families are reported separately."""

from __future__ import annotations

import csv
from collections import defaultdict

from sqlalchemy import select
from sqlalchemy.orm import Session

from core.config import ROOT, load_settings
from core.db import FindingRow, init_db, session_factory
from core.logging import setup_logging
from core.registry import discover_families
from engine.runner import run_audit
from evaluation.metrics import render_family, score_cases
from families.base import DocumentFamily

HEADER = """# Tier B rule metrics

Synthetic structured data only. This file does not use real documents,
and real documents have no anomaly ground truth. Property-tax rates
are illustrative. Each family is scored on its own answer key and the
families are not averaged together.

Each rule is scored independently, including cases with two or more
injected errors. needs_layer4 cases obey the rules and are reported as
expected misses, not as false negatives. This table is layers 1-3 only.
Layer 4 and the ablation table are in tier_b_ablation.md.
"""


def load_answer_key(path) -> list[dict[str, str]]:
    with path.open(newline="", encoding="utf-8") as handle:
        return list(csv.DictReader(handle))


def hits_for_family(session: Session, family: DocumentFamily) -> dict[str, set[str]]:
    hits: dict[str, set[str]] = defaultdict(set)
    rows = session.scalars(select(FindingRow).where(FindingRow.family == family.name)).all()
    for finding in rows:
        if finding.layer >= 4:
            continue
        case_key = family.case_key_for_finding(session, finding.entity_type, finding.entity_id)
        if case_key is not None:
            hits[finding.rule_id].add(case_key)
    return hits


def build_report(session: Session) -> str:
    parts = [HEADER.strip(), ""]
    for family in discover_families():
        path = family.generator().answer_key_file()
        if not path.exists():
            parts.append(f"## {family.name}")
            parts.append("")
            parts.append(f"No answer key at {path}. Run generate-data first.")
            parts.append("")
            continue
        summary = score_cases(load_answer_key(path), hits_for_family(session, family))
        parts.append(render_family(family.name, summary).rstrip())
        parts.append("")
    return "\n".join(parts).rstrip() + "\n"


def main() -> None:
    settings = load_settings()
    setup_logging(settings.logging_level)
    init_db()
    with session_factory()() as session:
        run_audit(session)
        report = build_report(session)
    out = ROOT / "evaluation" / "results" / "tier_b_rules.md"
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(report, encoding="utf-8")
    print(report)
    print(f"wrote {out}")


if __name__ == "__main__":
    main()
