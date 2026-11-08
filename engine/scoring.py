"""Entity risk score from finding severities.

risk = round(100 * (1 - product(1 - w_i)), 4)
Weights and bands come from config. Default bands are low below 30,
medium from 30 through 60, and high above 60.
"""

from __future__ import annotations

from collections import defaultdict
from datetime import UTC, datetime

from sqlalchemy import delete, select
from sqlalchemy.orm import Session

from core.db import FindingRow, RiskScore

SEVERITY_ORDER = ("low", "medium", "high")


def risk_from_severities(severities: list[str], weights: dict[str, float]) -> float:
    product = 1.0
    for severity in severities:
        weight = float(weights[severity])
        if weight < 0 or weight > 1:
            raise ValueError(f"Risk weight for {severity} must be between 0 and 1")
        product *= 1.0 - weight
    return round(100.0 * (1.0 - product), 4)


def band_for_score(score: float, *, low_below: float, high_above: float) -> str:
    if score < low_below:
        return "low"
    if score > high_above:
        return "high"
    return "medium"


def write_risk_scores(session: Session, family, risk_settings) -> list[RiskScore]:
    """Replace this family's risk rows. One row per case, using every finding on that case."""
    session.execute(delete(RiskScore).where(RiskScore.family == family.name))
    frame = family.feature_frame(session)
    findings = session.scalars(select(FindingRow).where(FindingRow.family == family.name)).all()
    by_case: dict[str, list[str]] = defaultdict(list)
    for finding in findings:
        case_key = family.case_key_for_finding(session, finding.entity_type, finding.entity_id)
        if case_key is not None:
            by_case[str(case_key)].append(finding.severity)
    case_keys = [str(value) for value in frame[CASE_COLUMN]]
    for case_key in by_case:
        if case_key not in case_keys:
            case_keys.append(case_key)
    computed_at = datetime.now(UTC)
    stored: list[RiskScore] = []
    for case_key in case_keys:
        score = risk_from_severities(by_case.get(case_key, []), risk_settings.weights)
        row = RiskScore(
            family=family.name,
            entity_type=family.case_entity_type,
            entity_id=case_key,
            score=score,
            band=band_for_score(
                score,
                low_below=risk_settings.low_below,
                high_above=risk_settings.high_above,
            ),
            computed_at=computed_at,
        )
        session.add(row)
        stored.append(row)
    return stored


CASE_COLUMN = "case_key"
