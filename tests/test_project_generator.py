from sqlalchemy import select
from tests.conftest import make_session

from core.db import FindingRow
from engine.runner import run_audit
from families.project.family import ProjectFamily
from families.project.models import Invoice, ProgressReport, Tender, WorkOrder


def _rules_by_case(session, family) -> dict[str, set[str]]:
    grouped: dict[str, set[str]] = {}
    for finding in session.scalars(select(FindingRow).where(FindingRow.family == "project")):
        case_key = family.case_key_for_finding(session, finding.entity_type, finding.entity_id)
        grouped.setdefault(case_key, set()).add(finding.rule_id)
    return grouped


def test_each_injected_project_error_triggers_only_its_rule(tmp_path):
    session = make_session()
    family = ProjectFamily()
    result = family.generator().generate(
        session,
        n=22,
        seed=42,
        error_rate=0.5,
        hard_negative_rate=0.0,
        answer_key_path=tmp_path / "project.csv",
    )
    session.commit()
    run_audit(session, [family])
    grouped = _rules_by_case(session, family)
    errors = [row for row in result.answer_key if row["label"] == "error"]
    assert len(errors) == 11
    assert {row["rule_id"] for row in errors} == {f"PR-{index:03d}" for index in range(1, 12)}
    for row in result.answer_key:
        found = grouped.get(row["case_key"], set())
        if row["label"] == "error":
            assert found == {row["rule_id"]}
        else:
            assert found == set()


def test_project_hard_negatives_stay_clean(tmp_path):
    session = make_session()
    family = ProjectFamily()
    result = family.generator().generate(
        session,
        n=5,
        seed=3,
        error_rate=0.0,
        hard_negative_rate=1.0,
        answer_key_path=tmp_path / "hard.csv",
    )
    session.commit()
    findings = run_audit(session, [family])
    assert result.hard_negatives == 5
    assert findings == []


def test_project_generator_is_deterministic(tmp_path):
    family = ProjectFamily()
    first = make_session()
    second = make_session()
    left = family.generator().generate(
        first,
        n=8,
        seed=42,
        error_rate=0.18,
        hard_negative_rate=0.08,
        answer_key_path=tmp_path / "a.csv",
    )
    right = family.generator().generate(
        second,
        n=8,
        seed=42,
        error_rate=0.18,
        hard_negative_rate=0.08,
        answer_key_path=tmp_path / "b.csv",
    )
    assert left.answer_key == right.answer_key


def test_project_feature_frame_columns(tmp_path):
    session = make_session()
    family = ProjectFamily()
    family.generator().generate(
        session,
        n=4,
        seed=1,
        error_rate=0,
        hard_negative_rate=0,
        answer_key_path=tmp_path / "features.csv",
    )
    frame = family.feature_frame(session)
    assert list(frame.columns) == [
        "case_key",
        "financial_physical_gap",
        "delay_days",
        "invoice_count",
        "spend_budget_ratio",
        "peer_group",
    ]
    assert len(frame) == 4
    assert frame["invoice_count"].between(3, 8).all()
    assert session.scalars(select(Tender)).all()
    assert session.scalars(select(WorkOrder)).all()
    assert session.scalars(select(Invoice)).all()
    assert session.scalars(select(ProgressReport)).all()
