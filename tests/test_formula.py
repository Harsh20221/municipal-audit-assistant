from families.property_tax.family import PropertyTaxFamily
from families.property_tax.formula import (
    exceeds_tolerance,
    expected_amounts,
    lookup_age_factor,
)


def test_illustrative_rates_and_hand_calculation():
    """Hand arithmetic only. This test does not use the synthetic generator."""
    loaded = PropertyTaxFamily().rule_params()
    params = loaded["values"]
    assert loaded["version"] == "illustrative-v1"
    assert "ILLUSTRATIVE" in loaded["notes"]
    assert params["general_rate"] == 0.15
    assert params["water_rate"] == 0.125
    assert params["sewer_rate"] == 0.03
    assert params["monthly_base_rate"]["A"]["residential"] == 8.0
    assert params["construction_factor"] == 1.0

    # 1000 sqft, zone A residential, built 2019, fiscal start 2024.
    # age 5 falls in the first band, so the age factor is 1.
    area = 1000
    monthly = 8.0
    age_factor = 1.0
    construction_factor = 1.0
    arv = area * monthly * construction_factor * age_factor * 12
    combined = 0.15 + 0.125 + 0.03
    assert arv == 96000
    assert round(combined, 10) == 0.305
    hand_assessed = round(arv * combined, 2)
    assert hand_assessed == 29280.00
    young = expected_amounts(
        built_up_area_sqft=area,
        zone="A",
        category="residential",
        construction_year=2019,
        exemption_amount=0,
        penalty=0,
        params=params,
    )
    assert young["building_age"] == 5
    assert young["age_factor"] == 1.0
    assert young["assessed_tax"] == hand_assessed
    assert young["amount_due"] == hand_assessed

    # Age 30 (built 1994) is in the 26-40 band, factor 0.8.
    assert lookup_age_factor(30, params["age_factor_bands"]) == 0.8
    arv_old = 1000 * 8.0 * 1.0 * 0.8 * 12
    assert arv_old == 76800
    hand_old = round(arv_old * combined, 2)
    assert hand_old == 23424.00
    hand_due = round(hand_old - 1000 + 250, 2)
    assert hand_due == 22674.00
    older = expected_amounts(
        built_up_area_sqft=1000,
        zone="A",
        category="residential",
        construction_year=1994,
        exemption_amount=1000,
        penalty=250,
        params=params,
    )
    assert older["assessed_tax"] == hand_old
    assert older["amount_due"] == hand_due


def test_tolerance_uses_the_larger_of_rupee_and_percent():
    params = PropertyTaxFamily().rule_params()["values"]
    assert exceeds_tolerance(10200, 10000, params) is False
    assert exceeds_tolerance(10200.01, 10000, params) is True
    assert exceeds_tolerance(11.00, 10, params) is False
    assert exceeds_tolerance(11.01, 10, params) is True
