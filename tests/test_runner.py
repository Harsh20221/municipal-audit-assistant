from sqlalchemy import func, select
from tests.conftest import make_session
from tests.helpers import insert_case

from core.db import AuditLog, FindingRow
from engine.runner import run_audit
from families.property_tax.family import PropertyTaxFamily


def test_runner_persists_evidence_and_replaces_previous_findings():
    session = make_session()
    inserted = insert_case(session, amount_due=1)
    family = PropertyTaxFamily()
    first = run_audit(session, [family])
    assert len(first) == 1
    assert first[0].rule_id == "PT-004"
    assert first[0].review_status == "open"
    assert first[0].rule_version == "illustrative-v1"
    row = session.scalar(select(FindingRow))
    assert row.evidence[0]["doc_id"] == inserted["docs"]["tax_bill"].id
    assert row.evidence[0]["page"] == 1
    assert row.evidence[0]["field"] == "amount_due"
    second = run_audit(session, [family])
    assert len(second) == 1
    assert session.scalar(select(func.count()).select_from(FindingRow)) == 1
    logs = session.scalars(select(AuditLog).where(AuditLog.action == "audit_run")).all()
    assert len(logs) == 2
    assert logs[-1].detail_json["by_rule"]["PT-004"] == 1
