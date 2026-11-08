"""Write one clean sample PDF for each document type."""

from __future__ import annotations

from datetime import date
from pathlib import Path

from core.config import ROOT
from core.registry import discover_families
from ingestion.build_pdfs import TITLES
from ingestion.pdf_layouts import PdfSpec, write_pdf

SAMPLE_ROOT = ROOT / "data" / "samples"


def main() -> None:
    written = build_samples()
    print(f"sample_pdfs={len(written)}")
    for path in written:
        print(path)


def build_samples(destination: Path | None = None) -> list[Path]:
    root = destination or SAMPLE_ROOT
    written = []
    for family in discover_families():
        for spec in family.document_types():
            fields = _FIELDS[spec.name]
            path = root / family.name / f"{spec.name}.pdf"
            pdf = PdfSpec(
                family=family.name,
                case_id=str(fields.get("property_id") or fields.get("project_id")),
                doc_type=spec.name,
                layout="standard",
                title=TITLES[spec.name],
                fields=fields,
            )
            write_pdf(pdf, path)
            written.append(path)
    return written


_FIELDS = {
    "assessment_form": {
        "property_id": "PID90001",
        "owner_name": "Sample Owner",
        "address": "1 Sample Street",
        "ward": "Ward 1",
        "zone": "A",
        "category": "residential",
        "built_up_area_sqft": 1000.0,
        "construction_year": 2019,
        "fiscal_year": "2024-25",
        "assessed_tax": 29280.0,
        "exemption_amount": 0.0,
    },
    "tax_bill": {
        "property_id": "PID90001",
        "owner_name": "Sample Owner",
        "fiscal_year": "2024-25",
        "assessed_tax": 29280.0,
        "exemption_amount": 0.0,
        "penalty": 0.0,
        "amount_due": 29280.0,
        "issue_date": date(2024, 4, 1),
        "due_date": date(2024, 4, 30),
        "address": "1 Sample Street",
        "ward": "Ward 1",
        "zone": "A",
        "category": "residential",
        "built_up_area_sqft": 1000.0,
        "construction_year": 2019,
    },
    "payment_receipt": {
        "property_id": "PID90001",
        "owner_name": "Sample Owner",
        "fiscal_year": "2024-25",
        "receipt_id": "RCP90001",
        "amount_paid": 29280.0,
        "paid_date": date(2024, 4, 15),
        "address": "1 Sample Street",
        "ward": "Ward 1",
        "zone": "A",
        "category": "residential",
        "built_up_area_sqft": 1000.0,
        "construction_year": 2019,
    },
    "tender_award_notice": {
        "project_id": "PRJ9001",
        "name": "Sample road repair",
        "city": "Sample City",
        "department": "Roads",
        "contractor": "Sample Contractor",
        "tender_estimate": 1000000.0,
        "award_value": 1000000.0,
        "budget": 1000000.0,
        "start_date": date(2024, 4, 1),
        "expected_end_date": date(2025, 3, 31),
    },
    "work_order": {
        "project_id": "PRJ9001",
        "contractor": "Sample Contractor",
        "work_order_value": 1000000.0,
        "work_order_date": date(2024, 4, 15),
    },
    "invoice": {
        "project_id": "PRJ9001",
        "invoice_no": "INV9001",
        "vendor": "Sample Contractor",
        "amount": 500000.0,
        "invoice_date": date(2024, 6, 1),
    },
    "progress_report": {
        "project_id": "PRJ9001",
        "report_month": "2024-06",
        "physical_pct": 40.0,
        "financial_pct": 40.0,
    },
}


if __name__ == "__main__":
    main()
