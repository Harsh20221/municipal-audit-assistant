"""Project plugin. The registry loads this module by folder name."""

from __future__ import annotations

from pathlib import Path

from sqlalchemy import select

from core.config import load_rule_file
from families.base import DocumentFamily, DocumentTypeSpec, ExtractionResult
from families.project.features import FEATURE_FIELDS, build_feature_frame
from families.project.generator import ProjectGenerator
from families.project.models import Invoice, ProgressReport, Project, Tender, WorkOrder
from families.project.persist import clear_case, persist_project
from families.project.rules import registered_rules
from families.project.schemas import InvoiceFields, ProgressFields, TenderFields, WorkOrderFields

_RULES_PATH = Path(__file__).with_name("rules.yaml")


class ProjectFamily(DocumentFamily):
    name = "project"
    version = "0.1.0"
    description = (
        "Compare a tender, work order, invoices, and progress reports for one works project."
    )
    case_entity_type = "project"

    def document_types(self) -> list[DocumentTypeSpec]:
        return [
            _slot(
                "tender_award_notice",
                ("tender", "award notice", "tender estimate"),
                TenderFields,
                label="Tender and award notice",
                description=(
                    "One notice for the project. It records the estimate, award, "
                    "budget, contractor, and schedule."
                ),
                key_fields=(
                    "Project ID",
                    "Contractor",
                    "Tender estimate",
                    "Award value",
                    "Budget",
                    "Start date",
                    "Expected end date",
                ),
                needed_for=(
                    "PR-002 end date before the start date",
                    "PR-008 overdue and incomplete",
                    "PR-009 spend above budget",
                    "PR-010 award far from the estimate",
                    "PR-011 vendor differs from the contractor",
                ),
                what_to_look_for=(
                    "Project ID, contractor, estimate, award value, budget, and both dates."
                ),
            ),
            _slot(
                "work_order",
                ("work order", "work-order"),
                WorkOrderFields,
                label="Work order",
                description="One work order stating the contractor, value, and order date.",
                key_fields=("Project ID", "Contractor", "Work order value", "Work order date"),
                needed_for=(
                    "PR-003 negative amounts",
                    "PR-004 invoices above the work order",
                    "PR-005 invoice dated before the work order",
                ),
                what_to_look_for="Work order value and work order date.",
            ),
            _slot(
                "invoice",
                ("invoice", "tax invoice", "bill for work"),
                InvoiceFields,
                label="Invoice",
                description="One or more invoices. A project can have several.",
                allow_multiple=True,
                key_fields=("Project ID", "Invoice number", "Vendor", "Amount", "Invoice date"),
                needed_for=(
                    "PR-004 invoices above the work order",
                    "PR-005 invoice dated before the work order",
                    "PR-006 duplicated invoice number",
                    "PR-009 spend above budget",
                    "PR-011 vendor differs from the contractor",
                ),
                what_to_look_for="Invoice number, vendor, amount, and invoice date.",
            ),
            _slot(
                "progress_report",
                ("progress report", "physical progress", "financial progress"),
                ProgressFields,
                label="Progress report",
                description="One report per month, with physical and financial percent.",
                allow_multiple=True,
                key_fields=("Project ID", "Report month", "Physical percent", "Financial percent"),
                needed_for=(
                    "PR-001 percent outside 0 to 100",
                    "PR-007 financial percent far above physical percent",
                    "PR-008 overdue and incomplete",
                ),
                what_to_look_for="Report month, physical percent, and financial percent.",
            ),
        ]

    def case_id_field(self) -> str:
        return "project_id"

    def provides_portfolio(self) -> bool:
        return True

    def portfolio(self, session) -> dict | None:
        projects = session.scalars(select(Project).order_by(Project.project_id)).all()
        reports: dict[str, list[ProgressReport]] = {}
        for row in session.scalars(select(ProgressReport).order_by(ProgressReport.id)).all():
            reports.setdefault(row.project_id, []).append(row)
        points = []
        for project in projects:
            series = reports.get(project.project_id) or []
            if not series:
                continue
            latest = max(series, key=lambda item: item.report_month)
            if latest.physical_pct is None or latest.financial_pct is None:
                continue
            points.append(
                {
                    "case_id": project.project_id,
                    "label": project.name,
                    "physical_pct": latest.physical_pct,
                    "financial_pct": latest.financial_pct,
                }
            )
        return {
            "x_label": "Physical progress (%)",
            "y_label": "Financial progress (%)",
            "note": (
                "Each point is the latest progress report for a project. "
                "It requires manual verification."
            ),
            "points": points,
        }

    def extraction_prompt(self, doc_type: str) -> str:
        spec = next(item for item in self.document_types() if item.name == doc_type)
        fields = ", ".join(spec.schema.model_fields)
        return (
            "Extract only the requested fields from the document text into one JSON object. "
            "Copy values that are written in the text. Use null when a field is absent. "
            "Do not decide whether any value is anomalous. "
            f"Document type: {doc_type}. Fields: {fields}."
        )

    def models(self) -> list[type]:
        return [Project, Tender, WorkOrder, Invoice, ProgressReport]

    def persist(self, extraction_result: ExtractionResult, session) -> None:
        persist_project(extraction_result, session)

    def clear_case(self, session, case_id: str) -> None:
        clear_case(session, case_id)

    def rules(self) -> list:
        return registered_rules()

    def feature_frame(self, session):
        return build_feature_frame(session, self.rule_params()["values"])

    def feature_fields(self) -> dict[str, str]:
        return dict(FEATURE_FIELDS)

    def generator(self) -> ProjectGenerator:
        return ProjectGenerator(self.rule_params())

    def rule_params(self) -> dict:
        return load_rule_file(_RULES_PATH)

    def case_key_for_finding(self, session, entity_type: str, entity_id: str) -> str | None:
        if entity_type == "project":
            return entity_id
        model = {
            "tender": Tender,
            "work_order": WorkOrder,
            "invoice": Invoice,
            "progress_report": ProgressReport,
        }.get(entity_type)
        if model is None:
            return entity_id
        row = session.get(model, int(entity_id))
        return None if row is None else row.project_id


def _slot(name, keywords, schema, **kwargs) -> DocumentTypeSpec:
    if "key_fields" in kwargs:
        kwargs["key_fields_it_must_contain"] = kwargs.pop("key_fields")
    return DocumentTypeSpec(
        name,
        keywords,
        schema,
        sample_pdf_path=f"data/samples/project/{name}.pdf",
        accepted_formats=("digital PDF",),
        required=True,
        allow_multiple=kwargs.pop("allow_multiple", False),
        **kwargs,
    )
