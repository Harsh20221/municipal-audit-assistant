"""Response models for /api/v1."""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, Field


class ErrorBody(BaseModel):
    code: str
    message: str


class ErrorResponse(BaseModel):
    error: ErrorBody


class FamilySummary(BaseModel):
    name: str
    description: str
    has_portfolio: bool


class FamilyList(BaseModel):
    families: list[FamilySummary]


class DocumentRequirement(BaseModel):
    name: str
    label: str
    description: str
    required: bool
    allow_multiple: bool
    accepted_formats: list[str]
    key_fields_it_must_contain: list[str]
    needed_for: list[str]
    sample_pdf_path: str
    sample_url: str
    what_to_look_for: str


class RuleRequirement(BaseModel):
    rule_id: str
    requires_doc_types: list[str]


class RequirementsResponse(BaseModel):
    family: str
    description: str
    documents: list[DocumentRequirement]
    rules: list[RuleRequirement]
    notices: list[str]


class FileResult(BaseModel):
    filename: str
    slot: str
    status: Literal["ok", "warning", "error"]
    message: str
    case_id: str = ""
    classified: str | None = None


class SlotResult(BaseModel):
    name: str
    label: str
    required: bool
    allow_multiple: bool
    count: int
    status: str


class BundleResponse(BaseModel):
    files: list[FileResult]
    slots: list[SlotResult]
    verdict: Literal["ready", "ready with warnings", "incomplete"]


class EvidenceOut(BaseModel):
    doc_id: int | None = None
    filename: str | None = None
    page: int | None = None
    field: str


class FindingOut(BaseModel):
    finding_id: str
    family: str
    rule_id: str
    layer: int
    entity_type: str
    entity_id: str
    severity: str
    expected_value: str | None = None
    actual_value: str | None = None
    difference: str | None = None
    evidence: list[EvidenceOut]
    review_status: str
    explanation: str = ""


class SkippedRule(BaseModel):
    rule_id: str
    reason: str
    explanation: str


class CoverageOut(BaseModel):
    rules_run: list[str]
    rules_skipped: list[SkippedRule]


class RiskOut(BaseModel):
    family: str
    entity_type: str
    entity_id: str
    score: float
    band: str


class AuditResponse(BaseModel):
    case_id: str
    family: str
    bundle: BundleResponse
    risk: RiskOut | None = None
    findings: list[FindingOut]
    coverage: CoverageOut
    layer4_note: str


class FindingPage(BaseModel):
    findings: list[FindingOut]


class ReviewUpdate(BaseModel):
    review_status: Literal["open", "confirmed", "false_positive"]


class PortfolioPoint(BaseModel):
    case_id: str
    label: str
    physical_pct: float
    financial_pct: float


class PortfolioResponse(BaseModel):
    family: str
    x_label: str
    y_label: str
    note: str
    points: list[PortfolioPoint]


class EvaluationSummary(BaseModel):
    note: str
    tier_b_rules: str = ""
    tier_b_ablation: str = ""
    tier_b_extraction: str = ""
    tier_a_extraction: str = ""
    explanation_guardrail: str = ""


class GuideResponse(BaseModel):
    limitations: list[str]
    sources_markdown: str
    families: list[RequirementsResponse]


class Health(BaseModel):
    status: str = Field(default="ok")
