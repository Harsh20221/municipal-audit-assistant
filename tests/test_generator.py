from sqlalchemy import select
from tests.conftest import make_session

from core.db import Document
from engine.runner import run_audit
from families.property_tax.family import PropertyTaxFamily
from families.property_tax.models import Property, TaxBill


def _rules_by_case(session) -> dict[str, set[str]]:
    from core.db import FindingRow
    from families.property_tax.models import TaxAssessment, TaxReceipt

    bills = {str(row.id): row.case_key for row in session.scalars(select(TaxBill))}
    assessments = {str(row.id): row.case_key for row in session.scalars(select(TaxAssessment))}
    receipts = {row.receipt_id: row.case_key for row in session.scalars(select(TaxReceipt))}
    grouped: dict[str, set[str]] = {}
    for finding in session.scalars(select(FindingRow)):
        if finding.entity_type == "tax_bill":
            case_key = bills[finding.entity_id]
        elif finding.entity_type == "tax_assessment":
            case_key = assessments[finding.entity_id]
        elif finding.entity_type == "tax_receipt":
            case_key = receipts[finding.entity_id]
        else:
            case_key = finding.entity_id
        grouped.setdefault(case_key, set()).add(finding.rule_id)
    return grouped


def test_injected_errors_match_answer_key_and_hard_negatives_stay_clean(tmp_path):
    session = make_session()
    family = PropertyTaxFamily()
    result = family.generator().generate(
        session,
        n=18,
        seed=42,
        error_rate=0.5,
        hard_negative_rate=0.0,
        answer_key_path=tmp_path / "answer_key.csv",
    )
    session.commit()
    run_audit(session, [family])
    grouped = _rules_by_case(session)
    errors = [row for row in result.answer_key if row["label"] == "error"]
    assert len(errors) == 9
    assert {row["rule_id"] for row in errors} == {f"PT-00{index}" for index in range(1, 10)}
    for row in result.answer_key:
        found = grouped.get(row["case_key"], set())
        if row["label"] == "error":
            assert found == {row["rule_id"]}
        else:
            assert found == set()
    saved = (tmp_path / "answer_key.csv").read_text(encoding="utf-8")
    assert "negative_penalty,PT-001" in saved or "negative_penalty" in saved


def test_hard_negatives_do_not_trip_layer_1_to_3(tmp_path):
    session = make_session()
    family = PropertyTaxFamily()
    result = family.generator().generate(
        session,
        n=10,
        seed=7,
        error_rate=0.0,
        hard_negative_rate=1.0,
        answer_key_path=tmp_path / "hard.csv",
    )
    session.commit()
    findings = run_audit(session, [family])
    assert result.hard_negatives == 10
    assert findings == []


def test_generator_is_deterministic(tmp_path):
    family = PropertyTaxFamily()
    first = make_session()
    second = make_session()
    left = family.generator().generate(
        first,
        n=12,
        seed=42,
        error_rate=0.18,
        hard_negative_rate=0.08,
        answer_key_path=tmp_path / "a.csv",
    )
    right = family.generator().generate(
        second,
        n=12,
        seed=42,
        error_rate=0.18,
        hard_negative_rate=0.08,
        answer_key_path=tmp_path / "b.csv",
    )
    assert left.answer_key == right.answer_key
    left_bill = first.scalars(select(TaxBill).order_by(TaxBill.case_key)).first()
    right_bill = second.scalars(select(TaxBill).where(TaxBill.case_key == left_bill.case_key)).one()
    assert left_bill.amount_due == right_bill.amount_due
    assert first.scalar(select(Document).where(Document.family == "property_tax")) is not None


def test_feature_frame_has_layer4_columns(tmp_path):
    session = make_session()
    family = PropertyTaxFamily()
    family.generator().generate(
        session,
        n=3,
        seed=1,
        error_rate=0,
        hard_negative_rate=0,
        answer_key_path=tmp_path / "features.csv",
    )
    frame = family.feature_frame(session)
    assert list(frame.columns) == [
        "case_key",
        "tax_per_sqft",
        "built_up_area_sqft",
        "building_age",
        "paid_expected_ratio",
    ]
    assert len(frame) == 3
    assert frame["paid_expected_ratio"].notna().all()
    assert session.scalars(select(Property)).all()
