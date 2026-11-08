"""Run layer 1-3 rules for every enabled family and store findings."""

from __future__ import annotations

import logging
from collections import Counter
from datetime import UTC, datetime
from uuid import uuid4

from sqlalchemy import delete, select
from sqlalchemy.orm import Session

from core.db import AuditLog, FindingRow, init_db, session_factory
from core.logging import setup_logging
from core.registry import discover_families
from engine.finding import Finding, RuleContext
from families.base import DocumentFamily

logger = logging.getLogger("engine.runner")


def run_audit(
    session: Session,
    families: list[DocumentFamily] | None = None,
) -> list[Finding]:
    """Replace stored findings for each family, then insert the new set."""
    selected = families if families is not None else discover_families()
    stored: list[Finding] = []
    for family in selected:
        session.execute(delete(FindingRow).where(FindingRow.family == family.name))
        loaded = family.rule_params()
        context = RuleContext(
            session=session,
            family=family.name,
            params=loaded["values"],
            rule_version=loaded["version"],
        )
        family_findings: list[Finding] = []
        for rule in family.rules():
            context.rule = rule
            family_findings.extend(rule.check(context))
        created_at = datetime.now(UTC)
        for item in family_findings:
            item.finding_id = str(uuid4())
            item.created_at = created_at
            session.add(
                FindingRow(
                    finding_id=item.finding_id,
                    family=item.family,
                    rule_id=item.rule_id,
                    layer=item.layer,
                    entity_type=item.entity_type,
                    entity_id=item.entity_id,
                    severity=item.severity,
                    expected_value=item.expected_value,
                    actual_value=item.actual_value,
                    difference=item.difference,
                    evidence=[piece.as_dict() for piece in item.evidence],
                    rule_version=item.rule_version,
                    created_at=created_at,
                    review_status=item.review_status,
                )
            )
        counts = Counter(item.rule_id for item in family_findings)
        session.add(
            AuditLog(
                created_at=created_at,
                action="audit_run",
                detail_json={
                    "family": family.name,
                    "finding_count": len(family_findings),
                    "by_rule": dict(sorted(counts.items())),
                },
            )
        )
        stored.extend(family_findings)
        logger.info("%s findings=%s by_rule=%s", family.name, len(family_findings), dict(counts))
    session.commit()
    return stored


def load_findings(session: Session, family: str | None = None) -> list[FindingRow]:
    query = select(FindingRow)
    if family is not None:
        query = query.where(FindingRow.family == family)
    return list(session.scalars(query.order_by(FindingRow.rule_id, FindingRow.entity_id)).all())


def main() -> None:
    from core.config import load_settings

    settings = load_settings()
    setup_logging(settings.logging_level)
    init_db()
    with session_factory()() as session:
        findings = run_audit(session)
    counts = Counter(item.rule_id for item in findings)
    print(f"findings={len(findings)}")
    for rule_id, count in sorted(counts.items()):
        print(f"  {rule_id}: {count}")


if __name__ == "__main__":
    main()
