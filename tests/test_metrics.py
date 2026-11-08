from evaluation.metrics import score_cases
from tests.conftest import make_session

from families.project.family import ProjectFamily
from families.property_tax.family import PropertyTaxFamily


def test_multi_error_and_layer4_are_scored_independently():
    rows = [
        {"case_key": "M", "label": "multi_error", "rule_id": "PT-001", "error_type": "a"},
        {"case_key": "M", "label": "multi_error", "rule_id": "PT-004", "error_type": "b"},
        {"case_key": "L", "label": "needs_layer4", "rule_id": "", "error_type": "huge_area"},
        {"case_key": "C", "label": "clean", "rule_id": "", "error_type": ""},
    ]
    summary = score_cases(rows, {"PT-001": {"M"}, "PT-004": {"M"}})
    by_rule = {row["rule_id"]: row for row in summary["rules"]}
    assert by_rule["PT-001"]["tp"] == 1
    assert by_rule["PT-001"]["fn"] == 0
    assert by_rule["PT-004"]["tp"] == 1
    assert summary["fn"] == 0
    assert summary["needs_layer4_cases"] == 1
    assert summary["needs_layer4_expected_misses"] == 1
    assert summary["needs_layer4_unexpected_hits"] == 0
    assert summary["categories"]["multi_error"] == 1
    assert summary["categories"]["needs_layer4"] == 1


def test_score_cases_counts_false_positives_on_clean_rows():
    rows = [
        {"case_key": "A", "label": "error", "rule_id": "PR-001", "error_type": "x"},
        {"case_key": "B", "label": "error", "rule_id": "PR-001", "error_type": "x"},
        {"case_key": "C", "label": "clean", "rule_id": "", "error_type": ""},
        {"case_key": "D", "label": "hard_negative", "rule_id": "", "error_type": "old"},
    ]
    summary = score_cases(rows, {"PR-001": {"A", "C"}})
    assert summary["rules"][0]["tp"] == 1
    assert summary["rules"][0]["fp"] == 1
    assert summary["rules"][0]["fn"] == 1
    assert summary["rules"][0]["precision"] == 0.5
    assert summary["rules"][0]["recall"] == 0.5
    assert summary["false_positive_cases"] == 1
    assert summary["negative_cases"] == 2
    assert summary["false_positive_rate"] == 0.5


def test_quota_corpus_is_not_trivial(tmp_path):
    from collections import defaultdict

    from evaluation.metrics import score_cases
    from evaluation.score import hits_for_family, load_answer_key

    from engine.runner import run_audit

    session = make_session()
    property_family = PropertyTaxFamily()
    project_family = ProjectFamily()
    property_family.generator().generate(
        session,
        n=300,
        seed=42,
        error_rate=0,
        hard_negative_rate=0,
        plan="quota",
        answer_key_path=tmp_path / "property.csv",
    )
    project_family.generator().generate(
        session,
        n=150,
        seed=42,
        error_rate=0,
        hard_negative_rate=0,
        plan="quota",
        answer_key_path=tmp_path / "project.csv",
    )
    session.commit()
    run_audit(session, [property_family, project_family])
    for family, path, minimum in (
        (property_family, tmp_path / "property.csv", 6),
        (project_family, tmp_path / "project.csv", 6),
    ):
        rows = load_answer_key(path)
        summary = score_cases(rows, hits_for_family(session, family))
        assert summary["micro_precision"] == 1
        assert summary["micro_recall"] == 1
        assert summary["false_positive_rate"] == 0
        assert summary["needs_layer4_unexpected_hits"] == 0
        assert 8 <= summary["needs_layer4_cases"] <= 10
        assert summary["needs_layer4_expected_misses"] == summary["needs_layer4_cases"]
        total_cases = sum(summary["categories"].values())
        multi = summary["categories"]["multi_error"]
        assert abs(multi / total_cases - 0.10) < 0.02
        assert summary["categories"]["hard_negative"] > 0
        assert summary["categories"]["single_error"] > 0
        labeled = defaultdict(set)
        for row in rows:
            if row["rule_id"]:
                labeled[row["rule_id"]].add(row["case_key"])
        assert labeled
        assert min(len(case_ids) for case_ids in labeled.values()) >= minimum
    property_rows = (tmp_path / "property.csv").read_text(encoding="utf-8")
    assert "bill_over_1.25" in property_rows
    assert "bill_inside_0.75" in property_rows
    project_rows = (tmp_path / "project.csv").read_text(encoding="utf-8")
    assert "over_order_1.5" in project_rows
    assert "order_excess_0.50" in project_rows
    assert "gap_15.5" in project_rows
    assert "gap_14.5" in project_rows


def test_small_tier_b_corpora_score_exactly(tmp_path):
    from evaluation.metrics import score_cases
    from evaluation.score import hits_for_family, load_answer_key

    from engine.runner import run_audit

    session = make_session()
    property_family = PropertyTaxFamily()
    project_family = ProjectFamily()
    property_family.generator().generate(
        session,
        n=18,
        seed=42,
        error_rate=0.5,
        hard_negative_rate=0,
        answer_key_path=tmp_path / "property.csv",
    )
    project_family.generator().generate(
        session,
        n=22,
        seed=42,
        error_rate=0.5,
        hard_negative_rate=0,
        answer_key_path=tmp_path / "project.csv",
    )
    session.commit()
    run_audit(session, [property_family, project_family])
    for family, path in (
        (property_family, tmp_path / "property.csv"),
        (project_family, tmp_path / "project.csv"),
    ):
        summary = score_cases(load_answer_key(path), hits_for_family(session, family))
        assert summary["micro_precision"] == 1
        assert summary["micro_recall"] == 1
        assert summary["false_positive_rate"] == 0
        assert all(row["fp"] == 0 and row["fn"] == 0 for row in summary["rules"])
