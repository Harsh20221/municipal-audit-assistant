"""Illustrative property-tax arithmetic shared by the generator and the rules.

expected assessed tax = ARV x (general_rate + water_rate + sewer_rate)
ARV = area x monthly_base_rate[zone][category] x construction_factor x age_factor x 12
amount due = assessed tax - exemption + penalty
"""

from __future__ import annotations


def age_years(construction_year: int, fiscal_start_year: int) -> int:
    return max(0, int(fiscal_start_year) - int(construction_year))


def lookup_age_factor(age: int, bands: list[dict]) -> float:
    ordered = sorted(bands, key=lambda band: band["max_age"])
    for band in ordered:
        if age <= band["max_age"]:
            return float(band["factor"])
    return float(ordered[-1]["factor"])


def tolerance_limit(expected: float, params: dict) -> float:
    relative = abs(expected) * float(params["amount_tolerance_pct"])
    return max(float(params["amount_tolerance_abs"]), relative)


def exceeds_tolerance(actual: float, expected: float, params: dict) -> bool:
    return abs(actual - expected) > tolerance_limit(expected, params) + 1e-9


def expected_amounts(
    *,
    built_up_area_sqft: float,
    zone: str,
    category: str,
    construction_year: int,
    exemption_amount: float,
    penalty: float,
    params: dict,
) -> dict[str, float]:
    monthly = float(params["monthly_base_rate"][zone][category])
    age = age_years(construction_year, int(params["fiscal_start_year"]))
    age_factor = lookup_age_factor(age, params["age_factor_bands"])
    construction_factor = float(params["construction_factor"])
    arv = float(built_up_area_sqft) * monthly * construction_factor * age_factor * 12
    combined = (
        float(params["general_rate"]) + float(params["water_rate"]) + float(params["sewer_rate"])
    )
    assessed = round(arv * combined, 2)
    exemption = round(float(exemption_amount), 2)
    pen = round(float(penalty), 2)
    return {
        "arv": round(arv, 2),
        "assessed_tax": assessed,
        "exemption_amount": exemption,
        "penalty": pen,
        "amount_due": round(assessed - exemption + pen, 2),
        "building_age": float(age),
        "age_factor": age_factor,
    }
