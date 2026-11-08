from datetime import date

from tests.conftest import make_session
from tests.project_helpers import insert_project

from engine.finding import RuleContext
from families.project.family import ProjectFamily


def _findings(session, rule_id: str):
    family = ProjectFamily()
    loaded = family.rule_params()
    selected = {rule.rule_id: rule for rule in family.rules()}
    context = RuleContext(
        session=session,
        family="project",
        params=loaded["values"],
        rule_version=loaded["version"],
        rule=selected[rule_id],
    )
    return selected[rule_id].check(context)


def test_project_rule_catalog_and_wording():
    rules = ProjectFamily().rules()
    assert [rule.rule_id for rule in rules] == [f"PR-{index:03d}" for index in range(1, 12)]
    for rule in rules:
        text = rule.description.lower()
        assert "requires manual verification" in text
        for banned in ("fraud", "corruption", "illegal"):
            assert banned not in text


def test_pr001_flags_percent_above_100():
    session = make_session()
    insert_project(session, physical_pct=130)
    found = _findings(session, "PR-001")
    assert len(found) == 1
    assert found[0].evidence[0].field == "physical_pct"


def test_pr001_percent_at_100_has_no_finding():
    session = make_session()
    insert_project(session, physical_pct=100, financial_pct=100)
    assert _findings(session, "PR-001") == []


def test_pr002_flags_end_before_start():
    session = make_session()
    insert_project(session, start_date=date(2025, 5, 1), expected_end_date=date(2025, 4, 1))
    found = _findings(session, "PR-002")
    assert len(found) == 1
    assert found[0].difference == "-30"


def test_pr002_end_after_start_has_no_finding():
    session = make_session()
    insert_project(session)
    assert _findings(session, "PR-002") == []


def test_pr003_flags_negative_invoice():
    session = make_session()
    insert_project(session, invoice_amounts=[-100.0, 200_000.0])
    found = _findings(session, "PR-003")
    assert len(found) == 1
    assert found[0].evidence[0].field == "amount"


def test_pr003_positive_amounts_have_no_finding():
    session = make_session()
    insert_project(session)
    assert _findings(session, "PR-003") == []


def test_pr004_flags_invoices_above_work_order():
    session = make_session()
    insert_project(session, work_order_value=1_000)
    found = _findings(session, "PR-004")
    assert len(found) == 1
    assert found[0].actual_value == "400000.00"


def test_pr004_invoices_under_work_order_have_no_finding():
    session = make_session()
    insert_project(session)
    assert _findings(session, "PR-004") == []


def test_pr005_flags_invoice_before_work_order():
    session = make_session()
    insert_project(
        session,
        work_order_date=date(2025, 4, 1),
        invoice_dates=[date(2025, 3, 1), date(2025, 6, 1)],
    )
    found = _findings(session, "PR-005")
    assert len(found) == 1
    assert found[0].difference == "-31"


def test_pr005_invoice_on_work_order_date_has_no_finding():
    session = make_session()
    insert_project(
        session,
        work_order_date=date(2025, 3, 1),
        invoice_dates=[date(2025, 3, 1), date(2025, 6, 1)],
    )
    assert _findings(session, "PR-005") == []


def test_pr006_flags_duplicate_invoice_number():
    session = make_session()
    insert_project(session, invoice_numbers=["INV-SAME", "INV-SAME"])
    found = _findings(session, "PR-006")
    assert len(found) == 1
    assert found[0].actual_value == "INV-SAME"


def test_pr006_unique_invoice_numbers_have_no_finding():
    session = make_session()
    insert_project(session)
    assert _findings(session, "PR-006") == []


def test_pr007_flags_gap_above_threshold():
    session = make_session()
    insert_project(session, physical_pct=40, financial_pct=80)
    found = _findings(session, "PR-007")
    assert len(found) == 1
    assert found[0].actual_value == "40.00"


def test_pr007_gap_at_threshold_has_no_finding():
    session = make_session()
    insert_project(session, physical_pct=50, financial_pct=65)
    assert _findings(session, "PR-007") == []


def test_pr008_flags_overdue_incomplete_project():
    session = make_session()
    insert_project(session, expected_end_date=date(2025, 8, 1), physical_pct=70, financial_pct=75)
    found = _findings(session, "PR-008")
    assert len(found) == 1
    assert found[0].rule_id == "PR-008"


def test_pr008_completed_project_after_end_has_no_finding():
    session = make_session()
    insert_project(
        session,
        expected_end_date=date(2025, 8, 1),
        physical_pct=100,
        financial_pct=100,
    )
    assert _findings(session, "PR-008") == []


def test_pr009_flags_spend_above_budget():
    session = make_session()
    insert_project(session, budget=1_000)
    found = _findings(session, "PR-009")
    assert len(found) == 1
    assert found[0].expected_value == "1000.00"


def test_pr009_spend_within_budget_has_no_finding():
    session = make_session()
    insert_project(session)
    assert _findings(session, "PR-009") == []


def test_pr010_flags_award_far_from_estimate():
    session = make_session()
    insert_project(session, tender_estimate=1_000_000, award_value=1_600_000)
    found = _findings(session, "PR-010")
    assert len(found) == 1
    assert found[0].entity_type == "tender"


def test_pr010_award_at_threshold_has_no_finding():
    session = make_session()
    insert_project(session, tender_estimate=1_000_000, award_value=1_200_000)
    assert _findings(session, "PR-010") == []


def test_pr011_flags_different_vendor():
    session = make_session()
    insert_project(session, invoice_vendors=["Mehta Constructions", "Unrelated Vendor ZZZ"])
    found = _findings(session, "PR-011")
    assert len(found) == 1
    assert found[0].difference == "vendor"


def test_pr011_vendor_case_and_spacing_has_no_finding():
    session = make_session()
    insert_project(session, invoice_vendors=["  mehta   constructions  ", "MEHTA CONSTRUCTIONS"])
    assert _findings(session, "PR-011") == []
