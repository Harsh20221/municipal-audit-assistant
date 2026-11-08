"""Project checks. Thresholds come from rules.yaml, not from literals here."""

from __future__ import annotations

from collections import defaultdict
from dataclasses import dataclass
from datetime import date

from sqlalchemy import select
from sqlalchemy.orm import Session

from engine.finding import Evidence, Finding, Rule, RuleContext
from families.project.models import Invoice, ProgressReport, Project, Tender, WorkOrder

_RULES: list[Rule] = []
BANNED_WORDS = ("fraud", "corruption", "illegal")
REQUIRES = {
    "PR-001": ("progress_report",),
    "PR-002": ("tender_award_notice",),
    "PR-003": ("tender_award_notice", "work_order", "invoice"),
    "PR-004": ("work_order", "invoice"),
    "PR-005": ("work_order", "invoice"),
    "PR-006": ("invoice",),
    "PR-007": ("progress_report",),
    "PR-008": ("tender_award_notice", "progress_report"),
    "PR-009": ("tender_award_notice", "invoice"),
    "PR-010": ("tender_award_notice",),
    "PR-011": ("tender_award_notice", "invoice"),
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
            family="project",
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
    project: Project
    tender: Tender | None
    work_order: WorkOrder | None
    invoices: list[Invoice]
    reports: list[ProgressReport]


def _bundles(session: Session) -> list[_Bundle]:
    projects = session.scalars(select(Project).order_by(Project.project_id)).all()
    tenders = _first(session.scalars(select(Tender).order_by(Tender.id)).all())
    orders = _first(session.scalars(select(WorkOrder).order_by(WorkOrder.id)).all())
    invoices: dict[str, list[Invoice]] = defaultdict(list)
    for row in session.scalars(select(Invoice).order_by(Invoice.id)).all():
        invoices[row.project_id].append(row)
    reports: dict[str, list[ProgressReport]] = defaultdict(list)
    for row in session.scalars(select(ProgressReport).order_by(ProgressReport.id)).all():
        reports[row.project_id].append(row)
    return [
        _Bundle(
            project=project,
            tender=tenders.get(project.project_id),
            work_order=orders.get(project.project_id),
            invoices=invoices.get(project.project_id, []),
            reports=reports.get(project.project_id, []),
        )
        for project in projects
    ]


def _first(rows) -> dict:
    found = {}
    for row in rows:
        found.setdefault(row.project_id, row)
    return found


def _money(value: float) -> str:
    return f"{value:.2f}"


def _points(value: float) -> str:
    return f"{value:.2f}"


def _norm_name(value: str | None) -> str | None:
    if value is None:
        return None
    text = " ".join(value.split()).casefold()
    return text or None


def _sum_invoices(invoices: list[Invoice]) -> float:
    return round(sum(row.amount or 0 for row in invoices), 2)


def _as_of(params: dict) -> date:
    return date.fromisoformat(str(params["as_of_date"]))


@rule(
    "PR-001",
    1,
    "medium",
    "A progress percent outside 0 to 100 requires manual verification.",
)
def check_percent_range(ctx: RuleContext) -> list[Finding]:
    low = float(ctx.params["percent_min"])
    high = float(ctx.params["percent_max"])
    findings: list[Finding] = []
    for bundle in _bundles(ctx.session):
        for report in bundle.reports:
            for field_name in ("physical_pct", "financial_pct"):
                value = getattr(report, field_name)
                if value is None or low <= value <= high:
                    continue
                findings.append(
                    ctx.emit(
                        entity_type="progress_report",
                        entity_id=report.id,
                        expected_value=f"{_points(low)} to {_points(high)}",
                        actual_value=_points(value),
                        difference=_points(value),
                        evidence=[Evidence(report.document_id, 1, field_name)],
                    )
                )
    return findings


@rule(
    "PR-002",
    1,
    "medium",
    "An expected end date before the start date requires manual verification.",
)
def check_end_before_start(ctx: RuleContext) -> list[Finding]:
    findings: list[Finding] = []
    for bundle in _bundles(ctx.session):
        project = bundle.project
        if project.expected_end_date < project.start_date:
            days = (project.expected_end_date - project.start_date).days
            findings.append(
                ctx.emit(
                    entity_type="project",
                    entity_id=project.project_id,
                    expected_value=project.start_date.isoformat(),
                    actual_value=project.expected_end_date.isoformat(),
                    difference=str(days),
                    evidence=[Evidence(None, 1, "expected_end_date")],
                )
            )
    return findings


@rule(
    "PR-003",
    1,
    "high",
    "A negative project amount requires manual verification.",
)
def check_negative_amounts(ctx: RuleContext) -> list[Finding]:
    findings: list[Finding] = []
    for bundle in _bundles(ctx.session):
        project = bundle.project
        sources: list[tuple] = [
            ("project", project.project_id, None, (("budget", project.budget),)),
        ]
        if bundle.tender is not None:
            sources.append(
                (
                    "tender",
                    bundle.tender.id,
                    bundle.tender.document_id,
                    (
                        ("tender_estimate", bundle.tender.tender_estimate),
                        ("award_value", bundle.tender.award_value),
                    ),
                )
            )
        if bundle.work_order is not None:
            sources.append(
                (
                    "work_order",
                    bundle.work_order.id,
                    bundle.work_order.document_id,
                    (("work_order_value", bundle.work_order.work_order_value),),
                )
            )
        for invoice in bundle.invoices:
            sources.append(
                (
                    "invoice",
                    invoice.id,
                    invoice.document_id,
                    (("amount", invoice.amount),),
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
    "PR-004",
    3,
    "high",
    "An invoice total above the work order value requires manual verification.",
)
def check_invoice_total(ctx: RuleContext) -> list[Finding]:
    tolerance = float(ctx.params["amount_tolerance_abs"])
    findings: list[Finding] = []
    for bundle in _bundles(ctx.session):
        order = bundle.work_order
        if order is None or order.work_order_value is None or not bundle.invoices:
            continue
        total = _sum_invoices(bundle.invoices)
        if total - order.work_order_value > tolerance + 1e-6:
            findings.append(
                ctx.emit(
                    entity_type="project",
                    entity_id=bundle.project.project_id,
                    expected_value=_money(order.work_order_value),
                    actual_value=_money(total),
                    difference=_money(total - order.work_order_value),
                    evidence=[Evidence(order.document_id, 1, "work_order_value")]
                    + [Evidence(row.document_id, 1, "amount") for row in bundle.invoices],
                )
            )
    return findings


@rule(
    "PR-005",
    3,
    "medium",
    "An invoice dated before the work order requires manual verification.",
)
def check_invoice_before_work_order(ctx: RuleContext) -> list[Finding]:
    findings: list[Finding] = []
    for bundle in _bundles(ctx.session):
        order = bundle.work_order
        if order is None or order.work_order_date is None:
            continue
        for invoice in bundle.invoices:
            if invoice.invoice_date is None or invoice.invoice_date >= order.work_order_date:
                continue
            days = (invoice.invoice_date - order.work_order_date).days
            findings.append(
                ctx.emit(
                    entity_type="invoice",
                    entity_id=invoice.id,
                    expected_value=order.work_order_date.isoformat(),
                    actual_value=invoice.invoice_date.isoformat(),
                    difference=str(days),
                    evidence=[
                        Evidence(invoice.document_id, 1, "invoice_date"),
                        Evidence(order.document_id, 1, "work_order_date"),
                    ],
                )
            )
    return findings


@rule(
    "PR-006",
    3,
    "medium",
    "A duplicated invoice number requires manual verification.",
)
def check_duplicate_invoices(ctx: RuleContext) -> list[Finding]:
    grouped: dict[str, list[Invoice]] = defaultdict(list)
    for invoice in ctx.session.scalars(select(Invoice).order_by(Invoice.id)).all():
        number = (invoice.invoice_no or "").strip()
        if number:
            grouped[number].append(invoice)
    findings: list[Finding] = []
    seen: set[str] = set()
    for number, rows in grouped.items():
        if len(rows) < 2:
            continue
        for project_id in sorted({row.project_id for row in rows}):
            if project_id in seen:
                continue
            seen.add(project_id)
            matched = [row for row in rows if row.project_id == project_id]
            findings.append(
                ctx.emit(
                    entity_type="project",
                    entity_id=project_id,
                    expected_value="unique invoice number",
                    actual_value=number,
                    difference=str(len(rows)),
                    evidence=[Evidence(row.document_id, 1, "invoice_no") for row in matched],
                )
            )
    return findings


@rule(
    "PR-007",
    3,
    "medium",
    "A financial percent far above the physical percent requires manual verification.",
)
def check_progress_gap(ctx: RuleContext) -> list[Finding]:
    limit = float(ctx.params["financial_physical_gap_points"])
    findings: list[Finding] = []
    for bundle in _bundles(ctx.session):
        for report in bundle.reports:
            if report.financial_pct is None or report.physical_pct is None:
                continue
            gap = report.financial_pct - report.physical_pct
            if gap > limit + 1e-6:
                findings.append(
                    ctx.emit(
                        entity_type="progress_report",
                        entity_id=report.id,
                        expected_value=f"gap <= {_points(limit)}",
                        actual_value=_points(gap),
                        difference=_points(gap - limit),
                        evidence=[
                            Evidence(report.document_id, 1, "financial_pct"),
                            Evidence(report.document_id, 1, "physical_pct"),
                        ],
                    )
                )
    return findings


@rule(
    "PR-008",
    3,
    "medium",
    "A project past its expected end date and still under 100 percent "
    "requires manual verification.",
)
def check_overdue_incomplete(ctx: RuleContext) -> list[Finding]:
    as_of = _as_of(ctx.params)
    complete_at = float(ctx.params["percent_max"])
    findings: list[Finding] = []
    for bundle in _bundles(ctx.session):
        project = bundle.project
        if project.expected_end_date < project.start_date:
            continue
        if project.expected_end_date >= as_of or not bundle.reports:
            continue
        latest = max(bundle.reports, key=lambda row: row.report_month)
        if latest.physical_pct is None or latest.physical_pct >= complete_at:
            continue
        days = (as_of - project.expected_end_date).days
        findings.append(
            ctx.emit(
                entity_type="project",
                entity_id=project.project_id,
                expected_value=(
                    f"physical_pct >= {_points(complete_at)} "
                    f"or end on/after {as_of.isoformat()}"
                ),
                actual_value=f"{latest.physical_pct:.2f} as of {as_of.isoformat()}",
                difference=str(days),
                evidence=[
                    Evidence(latest.document_id, 1, "physical_pct"),
                    Evidence(None, 1, "expected_end_date"),
                ],
            )
        )
    return findings


@rule(
    "PR-009",
    3,
    "high",
    "Invoice spend above the project budget requires manual verification.",
)
def check_spend_above_budget(ctx: RuleContext) -> list[Finding]:
    tolerance = float(ctx.params["amount_tolerance_abs"])
    findings: list[Finding] = []
    for bundle in _bundles(ctx.session):
        if not bundle.invoices:
            continue
        total = _sum_invoices(bundle.invoices)
        budget = bundle.project.budget
        if total - budget > tolerance + 1e-6:
            findings.append(
                ctx.emit(
                    entity_type="project",
                    entity_id=bundle.project.project_id,
                    expected_value=_money(budget),
                    actual_value=_money(total),
                    difference=_money(total - budget),
                    evidence=[Evidence(None, 1, "budget")]
                    + [Evidence(row.document_id, 1, "amount") for row in bundle.invoices],
                )
            )
    return findings


@rule(
    "PR-010",
    3,
    "medium",
    "An award value far from the tender estimate requires manual verification.",
)
def check_award_gap(ctx: RuleContext) -> list[Finding]:
    limit = float(ctx.params["award_gap_pct"])
    findings: list[Finding] = []
    for bundle in _bundles(ctx.session):
        tender = bundle.tender
        if tender is None or not tender.tender_estimate or tender.award_value is None:
            continue
        ratio = abs(tender.award_value - tender.tender_estimate) / abs(tender.tender_estimate)
        if ratio > limit + 1e-6:
            findings.append(
                ctx.emit(
                    entity_type="tender",
                    entity_id=tender.id,
                    expected_value=_money(tender.tender_estimate),
                    actual_value=_money(tender.award_value),
                    difference=f"{ratio:.4f}",
                    evidence=[
                        Evidence(tender.document_id, 1, "award_value"),
                        Evidence(tender.document_id, 1, "tender_estimate"),
                    ],
                )
            )
    return findings


@rule(
    "PR-011",
    3,
    "medium",
    "An invoice vendor that differs from the awarded contractor requires manual verification.",
)
def check_vendor_mismatch(ctx: RuleContext) -> list[Finding]:
    findings: list[Finding] = []
    for bundle in _bundles(ctx.session):
        contractor = _norm_name(bundle.project.contractor)
        if contractor is None:
            continue
        for invoice in bundle.invoices:
            vendor = _norm_name(invoice.vendor)
            if vendor is None or vendor == contractor:
                continue
            findings.append(
                ctx.emit(
                    entity_type="invoice",
                    entity_id=invoice.id,
                    expected_value=bundle.project.contractor,
                    actual_value=invoice.vendor,
                    difference="vendor",
                    evidence=[Evidence(invoice.document_id, 1, "vendor")],
                )
            )
    return findings
