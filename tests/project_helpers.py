"""Insert one consistent project for rule tests."""

from __future__ import annotations

import hashlib
from datetime import date

from sqlalchemy.orm import Session

from core.db import Document
from families.project.models import Invoice, ProgressReport, Project, Tender, WorkOrder

_CASE = 0


def insert_project(session: Session, **changes):
    global _CASE
    _CASE += 1
    project_id = changes.pop("project_id", f"PRJ{_CASE:04d}")
    contractor = changes.pop("contractor", "Mehta Constructions")
    start = changes.pop("start_date", date(2025, 1, 1))
    end = changes.pop("expected_end_date", date(2026, 6, 30))
    work_order_date = changes.pop("work_order_date", date(2025, 1, 20))
    budget = changes.pop("budget", 1_150_000.0)
    tender_estimate = changes.pop("tender_estimate", 1_000_000.0)
    award = changes.pop("award_value", 1_000_000.0)
    work_order_value = changes.pop("work_order_value", 1_000_000.0)
    amounts = list(changes.pop("invoice_amounts", [200_000.0, 200_000.0]))
    dates = list(changes.pop("invoice_dates", [date(2025, 3, 1), date(2025, 6, 1)]))
    numbers = list(changes.pop("invoice_numbers", [f"INV-{_CASE}-1", f"INV-{_CASE}-2"]))
    vendors = list(changes.pop("invoice_vendors", [contractor, contractor]))
    physical = changes.pop("physical_pct", 50.0)
    financial = changes.pop("financial_pct", 50.0)
    if changes:
        unknown = ", ".join(sorted(changes))
        raise ValueError(f"Unknown insert_project arguments: {unknown}")
    if not (len(amounts) == len(dates) == len(numbers) == len(vendors)):
        raise ValueError("Invoice override lists must be the same length")

    session.add(
        Project(
            project_id=project_id,
            name=f"Road works {_CASE}",
            city="Pune",
            department="Roads",
            budget=budget,
            start_date=start,
            expected_end_date=end,
            contractor=contractor,
        )
    )
    tender_doc = _doc(project_id, "tender_award_notice", "tender")
    order_doc = _doc(project_id, "work_order", "order")
    session.add_all([tender_doc, order_doc])
    session.flush()
    tender = Tender(
        project_id=project_id,
        tender_estimate=tender_estimate,
        award_value=award,
        contractor=contractor,
        document_id=tender_doc.id,
    )
    order = WorkOrder(
        project_id=project_id,
        work_order_value=work_order_value,
        work_order_date=work_order_date,
        contractor=contractor,
        document_id=order_doc.id,
    )
    session.add_all([tender, order])
    invoices = []
    for index, amount in enumerate(amounts):
        document = _doc(project_id, "invoice", f"{index}-{numbers[index]}")
        session.add(document)
        session.flush()
        invoice = Invoice(
            project_id=project_id,
            invoice_no=numbers[index],
            vendor=vendors[index],
            amount=amount,
            invoice_date=dates[index],
            document_id=document.id,
        )
        session.add(invoice)
        invoices.append(invoice)
    report_doc = _doc(project_id, "progress_report", "2025-09")
    session.add(report_doc)
    session.flush()
    report = ProgressReport(
        project_id=project_id,
        report_month="2025-09",
        physical_pct=physical,
        financial_pct=financial,
        document_id=report_doc.id,
    )
    session.add(report)
    session.flush()
    return {
        "project_id": project_id,
        "tender": tender,
        "work_order": order,
        "invoices": invoices,
        "report": report,
    }


def _doc(project_id: str, doc_type: str, key: str) -> Document:
    digest = hashlib.sha256(f"{project_id}:{doc_type}:{key}".encode()).hexdigest()
    return Document(
        sha256=digest,
        filename=f"{project_id}_{doc_type}_{key}.txt",
        family="project",
        doc_type=doc_type,
        source="unit_test",
        status="stored",
        page_count=1,
    )
