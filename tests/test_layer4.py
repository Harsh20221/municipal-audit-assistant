"""Hand-checked layer 4 statistics and the risk-score formula."""

import numpy as np
import pandas as pd

from engine.layer4_stats import (
    StatFlag,
    iqr_fences,
    iqr_flags,
    isolation_forest_flags,
    population_zscores,
    scale_columns,
    suppress_rule_overlaps,
    zscore_flags,
)
from engine.scoring import band_for_score, risk_from_severities

WEIGHTS = {"low": 0.10, "medium": 0.30, "high": 0.60}


def test_population_zscores_match_hand_calculation():
    # mean = 10 / 5 = 2
    # population variance = (4 + 4 + 4 + 4 + 64) / 5 = 16, std = 4
    # z = (x - 2) / 4
    scores = population_zscores(np.array([0, 0, 0, 0, 10], dtype=float))
    assert scores.tolist() == [-0.5, -0.5, -0.5, -0.5, 2.0]


def test_zscore_flags_only_the_value_past_the_threshold():
    frame = pd.DataFrame(
        {
            "case_key": [f"C{i}" for i in range(5)],
            "peer_group": ["A|residential"] * 5,
            "built_up_area_sqft": [0, 0, 0, 0, 10],
        }
    )
    flags = zscore_flags(frame, threshold=1.5, min_peer_group=5)
    assert [flag.case_key for flag in flags] == ["C4"]
    assert flags[0].features == ("built_up_area_sqft",)
    assert "z=2.00" in flags[0].note
    assert "manual verification" in flags[0].note
    assert zscore_flags(frame, threshold=3, min_peer_group=5) == []


def test_iqr_fences_match_hand_percentiles():
    # n = 9. Linear percentile index is (n - 1) * q.
    # q = 0.25 -> index 2, Q1 = 3. q = 0.75 -> index 6, Q3 = 7.
    # IQR = 4. k = 1.5. Fences are 3 - 6 = -3 and 7 + 6 = 13.
    values = np.array([1, 2, 3, 4, 5, 6, 7, 8, 20], dtype=float)
    assert iqr_fences(values, 1.5) == (-3.0, 13.0)


def test_iqr_flags_the_point_outside_the_fences():
    frame = pd.DataFrame(
        {
            "case_key": [f"C{i}" for i in range(9)],
            "peer_group": ["Roads"] * 9,
            "invoice_count": [1, 2, 3, 4, 5, 6, 7, 8, 20],
        }
    )
    flags = iqr_flags(frame, k=1.5, min_peer_group=9)
    assert [flag.case_key for flag in flags] == ["C8"]
    assert "invoice_count" in flags[0].note


def test_zero_iqr_does_not_flag_a_constant_feature():
    frame = pd.DataFrame(
        {
            "case_key": [f"C{i}" for i in range(8)],
            "peer_group": ["Health"] * 8,
            "financial_physical_gap": [0, 0, 0, 0, 0, 0, 0, 15],
        }
    )
    assert iqr_flags(frame, k=1.5, min_peer_group=8) == []


def test_scale_columns_matches_hand_mean_and_population_std():
    # mean = 2, population variance = 2/3, std = sqrt(2/3)
    std = (2 / 3) ** 0.5
    scaled = scale_columns(np.array([[1.0], [2.0], [3.0]])).ravel()
    assert np.allclose(scaled, [(1 - 2) / std, 0.0, (3 - 2) / std])


def test_isolation_forest_flags_the_extreme_row_and_ignores_affine_scale():
    rows = [
        {"case_key": f"C{i}", "peer_group": "Health", "area": 0.0, "age": 0.0} for i in range(40)
    ]
    rows[0]["area"] = 100.0
    rows[0]["age"] = 100.0
    frame = pd.DataFrame(rows)
    flags = isolation_forest_flags(frame, contamination=0.05, min_peer_group=8, random_state=0)
    flagged = {flag.case_key for flag in flags}
    assert "C0" in flagged
    assert len(flagged) <= 4
    note = next(flag.note for flag in flags if flag.case_key == "C0")
    assert "area scaled=" in note or "age scaled=" in note
    shifted = frame.copy()
    shifted["area"] = shifted["area"] * 50 + 1000
    again = isolation_forest_flags(shifted, contamination=0.05, min_peer_group=8, random_state=0)
    assert flagged == {flag.case_key for flag in again}


def test_peer_groups_are_scored_separately_and_small_groups_are_skipped():
    frame = pd.DataFrame(
        {
            "case_key": [f"C{i}" for i in range(6)],
            "peer_group": ["A|residential"] * 5 + ["C|residential"],
            "built_up_area_sqft": [0, 0, 0, 0, 10, 10_000],
        }
    )
    flags = zscore_flags(frame, threshold=1.5, min_peer_group=5)
    assert [flag.case_key for flag in flags] == ["C4"]
    assert zscore_flags(frame.iloc[:1], threshold=1, min_peer_group=8) == []


def test_layer4_drops_a_feature_a_rule_already_cited():
    flag = StatFlag(
        case_key="PID00001",
        method="zscore",
        details=(
            ("tax_per_sqft", "tax_per_sqft z=5.00"),
            ("built_up_area_sqft", "built_up_area_sqft z=9.00"),
        ),
        strength=9,
    )
    kept = suppress_rule_overlaps(
        [flag],
        {("PID00001", "amount_due")},
        {"tax_per_sqft": "amount_due", "built_up_area_sqft": "built_up_area_sqft"},
    )
    assert len(kept) == 1
    assert kept[0].features == ("built_up_area_sqft",)
    assert "tax_per_sqft" not in kept[0].note
    dropped = suppress_rule_overlaps(
        [flag],
        {("PID00001", "amount_due"), ("PID00001", "built_up_area_sqft")},
        {"tax_per_sqft": "amount_due", "built_up_area_sqft": "built_up_area_sqft"},
    )
    assert dropped == []


def test_risk_formula_and_bands_match_hand_products():
    # 100 * (1 - product(1 - w))
    assert risk_from_severities([], WEIGHTS) == 0
    assert risk_from_severities(["low"], WEIGHTS) == 10
    assert risk_from_severities(["medium"], WEIGHTS) == 30
    assert risk_from_severities(["high"], WEIGHTS) == 60
    # two high findings: 100 * (1 - 0.4 * 0.4) = 84
    assert risk_from_severities(["high", "high"], WEIGHTS) == 84
    # medium then high: 100 * (1 - 0.7 * 0.4) = 72
    assert risk_from_severities(["medium", "high"], WEIGHTS) == 72
    assert band_for_score(0, low_below=30, high_above=60) == "low"
    assert band_for_score(29.9999, low_below=30, high_above=60) == "low"
    assert band_for_score(30, low_below=30, high_above=60) == "medium"
    assert band_for_score(60, low_below=30, high_above=60) == "medium"
    assert band_for_score(60.0001, low_below=30, high_above=60) == "high"
    assert band_for_score(84, low_below=30, high_above=60) == "high"
