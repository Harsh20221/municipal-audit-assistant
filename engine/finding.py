"""Rule and Finding types. Decisions are made by rule code, not by a model."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import datetime

SEVERITIES = ("low", "medium", "high")
REVIEW_STATUSES = ("open", "confirmed", "false_positive")


@dataclass(frozen=True)
class Evidence:
    doc_id: int | None
    page: int | None
    field: str

    def as_dict(self) -> dict:
        return {"doc_id": self.doc_id, "page": self.page, "field": self.field}


@dataclass
class Finding:
    family: str
    rule_id: str
    layer: int
    entity_type: str
    entity_id: str
    severity: str
    expected_value: str | None
    actual_value: str | None
    difference: str | None
    evidence: list[Evidence]
    rule_version: str
    review_status: str = "open"
    finding_id: str | None = None
    created_at: datetime | None = None

    def __post_init__(self) -> None:
        if self.severity not in SEVERITIES:
            raise ValueError(f"Unknown severity: {self.severity}")
        if self.review_status not in REVIEW_STATUSES:
            raise ValueError(f"Unknown review_status: {self.review_status}")


@dataclass
class Rule:
    rule_id: str
    family: str
    layer: int
    severity: str
    description: str
    check: Callable[[RuleContext], list[Finding]]
    requires_doc_types: tuple[str, ...] = ()

    def __post_init__(self) -> None:
        if self.layer not in (1, 2, 3, 4):
            raise ValueError(f"Layer must be 1-4, got {self.layer}")
        if self.severity not in SEVERITIES:
            raise ValueError(f"Unknown severity: {self.severity}")


@dataclass
class RuleContext:
    session: object
    family: str
    params: dict
    rule_version: str
    rule: Rule | None = field(default=None)

    def emit(
        self,
        *,
        entity_type: str,
        entity_id: object,
        expected_value: object | None,
        actual_value: object | None,
        difference: object | None,
        evidence: list[Evidence],
    ) -> Finding:
        if self.rule is None:
            raise RuntimeError("RuleContext.rule is not set")
        return Finding(
            family=self.family,
            rule_id=self.rule.rule_id,
            layer=self.rule.layer,
            entity_type=entity_type,
            entity_id=str(entity_id),
            severity=self.rule.severity,
            expected_value=None if expected_value is None else str(expected_value),
            actual_value=None if actual_value is None else str(actual_value),
            difference=None if difference is None else str(difference),
            evidence=evidence,
            rule_version=self.rule_version,
        )
