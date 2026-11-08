from datetime import date

from tests.conftest import make_session
from tests.helpers import insert_case

from engine.finding import RuleContext
from families.property_tax.family import PropertyTaxFamily


def _findings(session, rule_id: str):
    family = PropertyTaxFamily()
    loaded = family.rule_params()
    selected = {rule.rule_id: rule for rule in family.rules()}
    context = RuleContext(
        session=session,
        family="property_tax",
        params=loaded["values"],
        rule_version=loaded["version"],
        rule=selected[rule_id],
    )
    return selected[rule_id].check(context)


def test_rule_catalog_and_wording():
    rules = PropertyTaxFamily().rules()
    assert [rule.rule_id for rule in rules] == [f"PT-00{index}" for index in range(1, 10)]
    for rule in rules:
        text = rule.description.lower()
        assert "requires manual verification" in text
        for banned in ("fraud", "corruption", "illegal"):
            assert banned not in text


def test_pt001_flags_negative_penalty():
    session = make_session()
    inserted = insert_case(session, penalty=-100)
    found = _findings(session, "PT-001")
    assert len(found) == 1
    assert found[0].evidence[0].field == "penalty"
    assert found[0].evidence[0].doc_id == inserted["bill"].document_id
    assert found[0].severity == "high"


def test_pt001_clean_amounts_have_no_finding():
    session = make_session()
    insert_case(session, penalty=250, exemption=500)
    assert _findings(session, "PT-001") == []


def test_pt002_flags_blank_owner():
    session = make_session()
    insert_case(session, bill_owner="  ")
    found = _findings(session, "PT-002")
    assert len(found) == 1
    assert found[0].evidence[0].field == "owner_name"
    assert found[0].entity_type == "tax_bill"


def test_pt002_complete_identity_has_no_finding():
    session = make_session()
    insert_case(session)
    assert _findings(session, "PT-002") == []


def test_pt003_flags_due_before_issue():
    session = make_session()
    insert_case(session, issue_date=date(2024, 8, 10), due_date=date(2024, 8, 1))
    found = _findings(session, "PT-003")
    assert len(found) == 1
    assert found[0].difference == "-9"
    assert found[0].layer == 1


def test_pt003_due_after_issue_has_no_finding():
    session = make_session()
    insert_case(session, issue_date=date(2024, 8, 1), due_date=date(2024, 8, 31))
    assert _findings(session, "PT-003") == []


def test_pt004_flags_bill_that_does_not_match_formula():
    session = make_session()
    inserted = insert_case(session, amount_due=1)
    found = _findings(session, "PT-004")
    assert len(found) == 1
    assert found[0].expected_value == f"{inserted['amounts']['amount_due']:.2f}"
    assert found[0].actual_value == "1.00"
    assert found[0].evidence[0].field == "amount_due"


def test_pt004_matching_bill_has_no_finding():
    session = make_session()
    insert_case(session, exemption=1000, penalty=250)
    assert _findings(session, "PT-004") == []


def test_pt005_flags_assessment_that_does_not_match_formula():
    session = make_session()
    inserted = insert_case(session, assessment_assessed=1)
    found = _findings(session, "PT-005")
    assert len(found) == 1
    assert found[0].expected_value == f"{inserted['amounts']['assessed_tax']:.2f}"
    assert found[0].entity_type == "tax_assessment"


def test_pt005_matching_assessment_has_no_finding():
    session = make_session()
    insert_case(session, zone="C", category="commercial", construction_year=1984)
    assert _findings(session, "PT-005") == []


def test_pt006_flags_receipt_that_differs_from_bill():
    session = make_session()
    insert_case(session, amount_paid=10)
    found = _findings(session, "PT-006")
    assert len(found) == 1
    assert found[0].evidence[0].field == "amount_paid"
    assert found[0].evidence[1].field == "amount_due"


def test_pt006_matching_receipt_has_no_finding():
    session = make_session()
    insert_case(session)
    assert _findings(session, "PT-006") == []


def test_pt007_flags_owner_mismatch():
    session = make_session()
    insert_case(session, receipt_owner="Someone Else")
    found = _findings(session, "PT-007")
    assert len(found) == 1
    assert found[0].difference == "owner_name"
    assert found[0].entity_type == "property"


def test_pt007_matching_identity_has_no_finding():
    session = make_session()
    insert_case(session)
    assert _findings(session, "PT-007") == []


def test_pt008_flags_late_payment_without_penalty():
    session = make_session()
    insert_case(
        session,
        issue_date=date(2024, 6, 1),
        due_date=date(2024, 7, 1),
        paid_date=date(2024, 7, 20),
        penalty=0,
    )
    found = _findings(session, "PT-008")
    assert len(found) == 1
    assert found[0].difference == "19"


def test_pt008_late_payment_with_penalty_has_no_finding():
    session = make_session()
    insert_case(
        session,
        issue_date=date(2024, 6, 1),
        due_date=date(2024, 7, 1),
        paid_date=date(2024, 7, 20),
        penalty=250,
    )
    assert _findings(session, "PT-008") == []


def test_pt009_flags_exemption_without_assessment():
    session = make_session()
    insert_case(session, exemption=1500, include_assessment=False)
    found = _findings(session, "PT-009")
    assert len(found) == 1
    assert found[0].evidence[0].field == "exemption_amount"
    assert found[0].actual_value == "1500.00"


def test_pt009_supported_exemption_has_no_finding():
    session = make_session()
    insert_case(session, exemption=1500, include_assessment=True)
    assert _findings(session, "PT-009") == []
