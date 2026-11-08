"""Build text PDFs from the structured rows already stored for each family."""

from __future__ import annotations

import csv
import json
from datetime import date
from pathlib import Path

from sqlalchemy import select
from sqlalchemy.orm import Session

from core.config import ROOT
from families.project.models import Invoice, ProgressReport, Project, Tender, WorkOrder
from families.property_tax.models import Property, TaxAssessment, TaxBill, TaxReceipt
from ingestion.pdf_layouts import PdfSpec, layout_for, write_pdf

PDF_ROOT = ROOT / "data" / "synthetic" / "pdfs"
MANIFEST = PDF_ROOT / "manifest.csv"
MANIFEST_COLUMNS = (
    "family",
    "case_id",
    "doc_type",
    "layout",
    "pdf_path",
    "sha256",
    "ground_truth_json",
)
TITLES = {
    "assessment_form": "Property tax assessment",
    "tax_bill": "Property tax bill",
    "payment_receipt": "Payment receipt",
    "tender_award_notice": "Tender award notice",
    "work_order": "Work order",
    "invoice": "Tax invoice",
    "progress_report": "Progress report",
}


def build_all(session: Session, destination: Path | None = None) -> Path:
    root = destination or PDF_ROOT
    root.mkdir(parents=True, exist_ok=True)
    specs = property_specs(session) + project_specs(session)
    if not specs:
        raise RuntimeError(
            "No structured cases are loaded. Run python -m evaluation.generate_data first."
        )
    rows = []
    for spec in specs:
        path = root / spec.family / f"{_filename(spec)}"
        digest = write_pdf(spec, path)
        rows.append(
            {
                "family": spec.family,
                "case_id": spec.case_id,
                "doc_type": spec.doc_type,
                "layout": spec.layout,
                "pdf_path": path.resolve().as_posix(),
                "sha256": digest,
                "ground_truth_json": json.dumps(_jsonable(spec.fields), sort_keys=True),
            }
        )
    manifest = root / "manifest.csv"
    with manifest.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=MANIFEST_COLUMNS)
        writer.writeheader()
        writer.writerows(rows)
    return manifest


def property_specs(session: Session) -> list[PdfSpec]:
    properties = {row.case_key: row for row in session.scalars(select(Property)).all()}
    specs: list[PdfSpec] = []
    for row in session.scalars(select(TaxAssessment).order_by(TaxAssessment.case_key)).all():
        prop = properties[row.case_key]
        specs.append(
            _spec("property_tax", row.case_key, "assessment_form", _assessment_fields(prop, row))
        )
    for row in session.scalars(select(TaxBill).order_by(TaxBill.case_key)).all():
        prop = properties[row.case_key]
        specs.append(_spec("property_tax", row.case_key, "tax_bill", _bill_fields(prop, row)))
    for row in session.scalars(select(TaxReceipt).order_by(TaxReceipt.case_key)).all():
        prop = properties[row.case_key]
        specs.append(
            _spec("property_tax", row.case_key, "payment_receipt", _receipt_fields(prop, row))
        )
    return specs


def project_specs(session: Session) -> list[PdfSpec]:
    projects = {row.project_id: row for row in session.scalars(select(Project)).all()}
    specs: list[PdfSpec] = []
    for row in session.scalars(select(Tender).order_by(Tender.project_id)).all():
        specs.append(
            _spec(
                "project",
                row.project_id,
                "tender_award_notice",
                _tender_fields(projects[row.project_id], row),
            )
        )
    for row in session.scalars(select(WorkOrder).order_by(WorkOrder.project_id)).all():
        specs.append(_spec("project", row.project_id, "work_order", _work_order_fields(row)))
    invoices: dict[str, int] = {}
    for row in session.scalars(select(Invoice).order_by(Invoice.project_id, Invoice.id)).all():
        invoices[row.project_id] = invoices.get(row.project_id, 0) + 1
        specs.append(
            _spec(
                "project",
                row.project_id,
                "invoice",
                _invoice_fields(row),
                copy=invoices[row.project_id],
            )
        )
    reports: dict[str, int] = {}
    for row in session.scalars(
        select(ProgressReport).order_by(ProgressReport.project_id, ProgressReport.id)
    ).all():
        reports[row.project_id] = reports.get(row.project_id, 0) + 1
        specs.append(
            _spec(
                "project",
                row.project_id,
                "progress_report",
                _progress_fields(row),
                copy=reports[row.project_id],
            )
        )
    return specs


def _spec(family: str, case_id: str, doc_type: str, fields: dict, copy: int = 1) -> PdfSpec:
    fields = {"document_copy": copy, **fields}
    return PdfSpec(
        family=family,
        case_id=case_id,
        doc_type=doc_type,
        layout=layout_for(case_id),
        title=TITLES[doc_type],
        fields=fields,
    )


def _filename(spec: PdfSpec) -> str:
    copy = spec.fields.get("document_copy", 1)
    return f"{spec.case_id}_{spec.doc_type}_{spec.layout}_{copy}.pdf"


def _context(prop: Property) -> dict:
    return {
        "address": prop.address,
        "ward": prop.ward,
        "zone": prop.zone,
        "category": prop.category,
        "built_up_area_sqft": prop.built_up_area_sqft,
        "construction_year": prop.construction_year,
    }


def _assessment_fields(prop: Property, row: TaxAssessment) -> dict:
    return {
        "property_id": row.property_id or "",
        "owner_name": row.owner_name or "",
        "fiscal_year": row.fiscal_year,
        "assessed_tax": row.assessed_tax,
        "exemption_amount": row.exemption_amount,
        **_context(prop),
    }


def _bill_fields(prop: Property, row: TaxBill) -> dict:
    return {
        "property_id": row.property_id or "",
        "owner_name": row.owner_name or "",
        "fiscal_year": row.fiscal_year,
        "assessed_tax": row.assessed_tax,
        "exemption_amount": row.exemption_amount,
        "penalty": row.penalty,
        "amount_due": row.amount_due,
        "issue_date": row.issue_date,
        "due_date": row.due_date,
        **_context(prop),
    }


def _receipt_fields(prop: Property, row: TaxReceipt) -> dict:
    return {
        "property_id": row.property_id or "",
        "owner_name": row.owner_name or "",
        "fiscal_year": row.fiscal_year,
        "receipt_id": row.receipt_id,
        "amount_paid": row.amount_paid,
        "paid_date": row.paid_date,
        **_context(prop),
    }


def _tender_fields(project: Project, row: Tender) -> dict:
    return {
        "project_id": project.project_id,
        "name": project.name,
        "city": project.city,
        "department": project.department,
        "contractor": row.contractor or project.contractor,
        "tender_estimate": row.tender_estimate,
        "award_value": row.award_value,
        "budget": project.budget,
        "start_date": project.start_date,
        "expected_end_date": project.expected_end_date,
    }


def _work_order_fields(row: WorkOrder) -> dict:
    return {
        "project_id": row.project_id,
        "contractor": row.contractor or "",
        "work_order_value": row.work_order_value,
        "work_order_date": row.work_order_date,
    }


def _invoice_fields(row: Invoice) -> dict:
    return {
        "project_id": row.project_id,
        "invoice_no": row.invoice_no or "",
        "vendor": row.vendor or "",
        "amount": row.amount,
        "invoice_date": row.invoice_date,
    }


def _progress_fields(row: ProgressReport) -> dict:
    return {
        "project_id": row.project_id,
        "report_month": row.report_month,
        "physical_pct": row.physical_pct,
        "financial_pct": row.financial_pct,
    }


def _jsonable(fields: dict) -> dict:
    payload = {}
    for key, value in fields.items():
        if isinstance(value, date):
            payload[key] = value.isoformat()
        else:
            payload[key] = value
    return payload


def main() -> None:
    from core.config import load_settings
    from core.db import init_db, session_factory
    from core.logging import setup_logging

    settings = load_settings()
    setup_logging(settings.logging_level)
    init_db()
    with session_factory()() as session:
        path = build_all(session)
    print(f"manifest={path}")


if __name__ == "__main__":
    main()
