"""Property-tax checks. Thresholds come from rules.yaml, not from literals here."""

from __future__ import annotations

from dataclasses import dataclass

from sqlalchemy import select
from sqlalchemy.orm import Session

from engine.finding import Evidence, Finding, Rule, RuleContext
from families.property_tax.formula import exceeds_tolerance, expected_amounts
from families.property_tax.models import Property, TaxAssessment, TaxBill, TaxReceipt

_RULES: list[Rule] = []
BANNED_WORDS = ("fraud", "corruption", "illegal")
REQUIRES = {
    "PT-001": ("assessment_form", "tax_bill", "payment_receipt"),
    "PT-002": ("assessment_form", "tax_bill", "payment_receipt"),
    "PT-003": ("tax_bill",),
    "PT-004": ("assessment_form", "tax_bill"),
    "PT-005": ("assessment_form",),
    "PT-006": ("tax_bill", "payment_receipt"),
    "PT-007": ("assessment_form", "tax_bill", "payment_receipt"),
    "PT-008": ("tax_bill", "payment_receipt"),
    "PT-009": ("assessment_form", "tax_bill"),
}


def rule(rule_id: str, layer: int, severity: str, description: str):
    lowered = description.lower()
    for word in BANNED_WORDS:
        if word in lowered:
            raise ValueError(f"{rule_id} description contains a banned word")
    if "requires manual verification" not in lowered:
        raise ValueError(f"{rule_id} must say 'requires manual verification'")

    def decorator(fn):
        item = Rule(
            rule_id=rule_id,
            family="property_tax",
            layer=layer,
            severity=severity,
            description=description,
            check=fn,
            requires_doc_types=REQUIRES[rule_id],
        )
        _RULES[:] = [existing for existing in _RULES if existing.rule_id != rule_id]
        _RULES.append(item)
        return fn

    return decorator


def registered_rules() -> list[Rule]:
    return list(_RULES)


@dataclass
class _Bundle:
    prop: Property
    assessment: TaxAssessment | None
    bill: TaxBill | None
    receipt: TaxReceipt | None


def _bundles(session: Session) -> list[_Bundle]:
    props = session.scalars(select(Property).order_by(Property.case_key)).all()
    assessments = _first_by_case(
        session.scalars(select(TaxAssessment).order_by(TaxAssessment.id)).all()
    )
    bills = _first_by_case(session.scalars(select(TaxBill).order_by(TaxBill.id)).all())
    receipts = _first_by_case(session.scalars(select(TaxReceipt).order_by(TaxReceipt.id)).all())
    return [
        _Bundle(
            prop=prop,
            assessment=assessments.get(prop.case_key),
            bill=bills.get(prop.case_key),
            receipt=receipts.get(prop.case_key),
        )
        for prop in props
    ]


def _first_by_case(rows) -> dict:
    found = {}
    for row in rows:
        found.setdefault(row.case_key, row)
    return found


def _text(value: str | None) -> str | None:
    if value is None:
        return None
    stripped = value.strip()
    return stripped or None


def _money(value: float) -> str:
    return f"{value:.2f}"


def _expected_for_bill(bundle: _Bundle, params: dict) -> dict[str, float] | None:
    bill = bundle.bill
    prop = bundle.prop
    if bill is None or bill.amount_due is None:
        return None
    if prop.zone not in params["monthly_base_rate"]:
        return None
    if prop.category not in params["monthly_base_rate"][prop.zone]:
        return None
    return expected_amounts(
        built_up_area_sqft=prop.built_up_area_sqft,
        zone=prop.zone,
        category=prop.category,
        construction_year=prop.construction_year,
        exemption_amount=bill.exemption_amount or 0.0,
        penalty=bill.penalty or 0.0,
        params=params,
    )


@rule(
    "PT-001",
    1,
    "high",
    "A negative amount on a property-tax document requires manual verification.",
)
def check_negative_amounts(ctx: RuleContext) -> list[Finding]:
    findings: list[Finding] = []
    for bundle in _bundles(ctx.session):
        sources = []
        if bundle.assessment is not None:
            sources.append(
                (
                    "tax_assessment",
                    bundle.assessment.id,
                    bundle.assessment.document_id,
                    (
                        ("assessed_tax", bundle.assessment.assessed_tax),
                        ("exemption_amount", bundle.assessment.exemption_amount),
                    ),
                )
            )
        if bundle.bill is not None:
            sources.append(
                (
                    "tax_bill",
                    bundle.bill.id,
                    bundle.bill.document_id,
                    (
                        ("assessed_tax", bundle.bill.assessed_tax),
                        ("exemption_amount", bundle.bill.exemption_amount),
                        ("penalty", bundle.bill.penalty),
                        ("amount_due", bundle.bill.amount_due),
                    ),
                )
            )
        if bundle.receipt is not None:
            sources.append(
                (
                    "tax_receipt",
                    bundle.receipt.receipt_id,
                    bundle.receipt.document_id,
                    (("amount_paid", bundle.receipt.amount_paid),),
                )
            )
        for entity_type, entity_id, doc_id, fields in sources:
            for field_name, value in fields:
                if value is not None and value < 0:
                    findings.append(
                        ctx.emit(
                            entity_type=entity_type,
                            entity_id=entity_id,
                            expected_value=">= 0",
                            actual_value=_money(value),
                            difference=_money(value),
                            evidence=[Evidence(doc_id, 1, field_name)],
                        )
                    )
    return findings


@rule(
    "PT-002",
    1,
    "high",
    "A missing owner name or property ID requires manual verification.",
)
def check_missing_identity(ctx: RuleContext) -> list[Finding]:
    findings: list[Finding] = []
    for bundle in _bundles(ctx.session):
        documents = []
        if bundle.assessment is not None:
            documents.append(("tax_assessment", bundle.assessment.id, bundle.assessment))
        if bundle.bill is not None:
            documents.append(("tax_bill", bundle.bill.id, bundle.bill))
        if bundle.receipt is not None:
            documents.append(("tax_receipt", bundle.receipt.receipt_id, bundle.receipt))
        for entity_type, entity_id, record in documents:
            for field_name in ("owner_name", "property_id"):
                if _text(getattr(record, field_name)) is None:
                    findings.append(
                        ctx.emit(
                            entity_type=entity_type,
                            entity_id=entity_id,
                            expected_value="non-empty",
                            actual_value="",
                            difference=None,
                            evidence=[Evidence(record.document_id, 1, field_name)],
                        )
                    )
    return findings


@rule(
    "PT-003",
    1,
    "medium",
    "A due date before the issue date requires manual verification.",
)
def check_due_before_issue(ctx: RuleContext) -> list[Finding]:
    findings: list[Finding] = []
    for bundle in _bundles(ctx.session):
        bill = bundle.bill
        if bill is None or bill.issue_date is None or bill.due_date is None:
            continue
        if bill.due_date < bill.issue_date:
            days = (bill.due_date - bill.issue_date).days
            findings.append(
                ctx.emit(
                    entity_type="tax_bill",
                    entity_id=bill.id,
                    expected_value=bill.issue_date.isoformat(),
                    actual_value=bill.due_date.isoformat(),
                    difference=str(days),
                    evidence=[Evidence(bill.document_id, 1, "due_date")],
                )
            )
    return findings


@rule(
    "PT-004",
    2,
    "high",
    "A billed amount that differs from the recalculated expected amount "
    "requires manual verification.",
)
def check_billed_amount(ctx: RuleContext) -> list[Finding]:
    findings: list[Finding] = []
    for bundle in _bundles(ctx.session):
        expected = _expected_for_bill(bundle, ctx.params)
        bill = bundle.bill
        if expected is None or bill is None or bill.amount_due is None:
            continue
        if exceeds_tolerance(bill.amount_due, expected["amount_due"], ctx.params):
            findings.append(
                ctx.emit(
                    entity_type="tax_bill",
                    entity_id=bill.id,
                    expected_value=_money(expected["amount_due"]),
                    actual_value=_money(bill.amount_due),
                    difference=_money(bill.amount_due - expected["amount_due"]),
                    evidence=[Evidence(bill.document_id, 1, "amount_due")],
                )
            )
    return findings


@rule(
    "PT-005",
    2,
    "medium",
    "An assessed tax that differs from the recalculated expected tax requires manual verification.",
)
def check_assessed_tax(ctx: RuleContext) -> list[Finding]:
    findings: list[Finding] = []
    for bundle in _bundles(ctx.session):
        assessment = bundle.assessment
        if assessment is None or assessment.assessed_tax is None:
            continue
        prop = bundle.prop
        if prop.zone not in ctx.params["monthly_base_rate"]:
            continue
        expected = expected_amounts(
            built_up_area_sqft=prop.built_up_area_sqft,
            zone=prop.zone,
            category=prop.category,
            construction_year=prop.construction_year,
            exemption_amount=0.0,
            penalty=0.0,
            params=ctx.params,
        )
        if exceeds_tolerance(assessment.assessed_tax, expected["assessed_tax"], ctx.params):
            findings.append(
                ctx.emit(
                    entity_type="tax_assessment",
                    entity_id=assessment.id,
                    expected_value=_money(expected["assessed_tax"]),
                    actual_value=_money(assessment.assessed_tax),
                    difference=_money(assessment.assessed_tax - expected["assessed_tax"]),
                    evidence=[Evidence(assessment.document_id, 1, "assessed_tax")],
                )
            )
    return findings


@rule(
    "PT-006",
    3,
    "high",
    "A receipt amount that differs from the bill amount requires manual verification.",
)
def check_receipt_matches_bill(ctx: RuleContext) -> list[Finding]:
    findings: list[Finding] = []
    for bundle in _bundles(ctx.session):
        bill = bundle.bill
        receipt = bundle.receipt
        if (
            bill is None
            or receipt is None
            or bill.amount_due is None
            or receipt.amount_paid is None
        ):
            continue
        if exceeds_tolerance(receipt.amount_paid, bill.amount_due, ctx.params):
            findings.append(
                ctx.emit(
                    entity_type="tax_receipt",
                    entity_id=receipt.receipt_id,
                    expected_value=_money(bill.amount_due),
                    actual_value=_money(receipt.amount_paid),
                    difference=_money(receipt.amount_paid - bill.amount_due),
                    evidence=[
                        Evidence(receipt.document_id, 1, "amount_paid"),
                        Evidence(bill.document_id, 1, "amount_due"),
                    ],
                )
            )
    return findings


@rule(
    "PT-007",
    3,
    "high",
    "An owner name or property ID that differs across related documents "
    "requires manual verification.",
)
def check_identity_mismatch(ctx: RuleContext) -> list[Finding]:
    findings: list[Finding] = []
    for bundle in _bundles(ctx.session):
        records = [bundle.assessment, bundle.bill, bundle.receipt]
        for field_name in ("owner_name", "property_id"):
            present = []
            for record in records:
                if record is None:
                    continue
                value = _text(getattr(record, field_name))
                if value is not None:
                    present.append(value)
            if len(present) >= 2 and len(set(present)) > 1:
                findings.append(
                    ctx.emit(
                        entity_type="property",
                        entity_id=bundle.prop.case_key,
                        expected_value=getattr(bundle.prop, field_name),
                        actual_value=" | ".join(present),
                        difference=field_name,
                        evidence=[
                            Evidence(record.document_id, 1, field_name)
                            for record in records
                            if record is not None
                        ],
                    )
                )
    return findings


@rule(
    "PT-008",
    3,
    "medium",
    "A payment after the due date with no penalty recorded requires manual verification.",
)
def check_late_payment_without_penalty(ctx: RuleContext) -> list[Finding]:
    findings: list[Finding] = []
    for bundle in _bundles(ctx.session):
        bill = bundle.bill
        receipt = bundle.receipt
        if (
            bill is None
            or receipt is None
            or bill.issue_date is None
            or bill.due_date is None
            or receipt.paid_date is None
        ):
            continue
        if bill.due_date < bill.issue_date:
            continue
        penalty = bill.penalty if bill.penalty is not None else 0.0
        if receipt.paid_date > bill.due_date and penalty <= 0:
            days = (receipt.paid_date - bill.due_date).days
            findings.append(
                ctx.emit(
                    entity_type="tax_receipt",
                    entity_id=receipt.receipt_id,
                    expected_value=f"paid on or before {bill.due_date.isoformat()} or penalty > 0",
                    actual_value=f"{receipt.paid_date.isoformat()} penalty={_money(penalty)}",
                    difference=str(days),
                    evidence=[
                        Evidence(receipt.document_id, 1, "paid_date"),
                        Evidence(bill.document_id, 1, "penalty"),
                    ],
                )
            )
    return findings


@rule(
    "PT-009",
    3,
    "medium",
    "An exemption without a supporting assessment entry requires manual verification.",
)
def check_exemption_support(ctx: RuleContext) -> list[Finding]:
    findings: list[Finding] = []
    for bundle in _bundles(ctx.session):
        bill = bundle.bill
        if bill is None or bill.exemption_amount is None or bill.exemption_amount <= 0:
            continue
        supported = (
            bundle.assessment is not None
            and bundle.assessment.exemption_amount is not None
            and bundle.assessment.exemption_amount > 0
        )
        if not supported:
            findings.append(
                ctx.emit(
                    entity_type="tax_bill",
                    entity_id=bill.id,
                    expected_value="assessment exemption > 0",
                    actual_value=_money(bill.exemption_amount),
                    difference=None,
                    evidence=[Evidence(bill.document_id, 1, "exemption_amount")],
                )
            )
    return findings
