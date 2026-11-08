"""Write a project extraction into the family tables."""

from __future__ import annotations

from datetime import date

from sqlalchemy import delete, select

from core.db import Document, Extraction
from families.base import ExtractionResult
from families.project.models import Invoice, ProgressReport, Project, Tender, WorkOrder


def clear_case(session, case_id: str) -> None:
    session.execute(delete(Invoice).where(Invoice.project_id == case_id))
    session.execute(delete(ProgressReport).where(ProgressReport.project_id == case_id))
    session.execute(delete(WorkOrder).where(WorkOrder.project_id == case_id))
    session.execute(delete(Tender).where(Tender.project_id == case_id))
    prefix = f"{case_id}_"
    stale = session.scalars(
        select(Document).where(Document.family == "project", Document.filename.startswith(prefix))
    ).all()
    doc_ids = [row.id for row in stale]
    if doc_ids:
        session.execute(delete(Extraction).where(Extraction.document_id.in_(doc_ids)))
        session.execute(delete(Document).where(Document.id.in_(doc_ids)))
    session.execute(delete(Project).where(Project.project_id == case_id))


def persist_project(result: ExtractionResult, session) -> None:
    document = Document(
        sha256=result.sha256,
        filename=result.filename,
        family="project",
        doc_type=result.doc_type,
        source="synthetic_pdf",
        status="unsupported_scanned" if result.is_scanned else result.status,
        page_count=result.page_count,
    )
    session.add(document)
    session.flush()
    result.document_id = document.id
    session.add(
        Extraction(
            document_id=document.id,
            fields_json=result.fields,
            field_pages_json=result.field_pages,
            model_name=result.model_name,
            validation_errors_json=result.validation_errors,
            is_scanned=result.is_scanned,
        )
    )
    if not result.accepted or result.is_scanned:
        return
    values = result.fields
    case_id = result.case_id or str(values.get("project_id") or "")
    if not case_id:
        return
    _ensure_project(session, case_id, values)
    if result.doc_type == "tender_award_notice":
        session.add(
            Tender(
                project_id=case_id,
                tender_estimate=_float(values.get("tender_estimate")),
                award_value=_float(values.get("award_value")),
                contractor=_text(values.get("contractor")),
                document_id=document.id,
            )
        )
    elif result.doc_type == "work_order":
        session.add(
            WorkOrder(
                project_id=case_id,
                work_order_value=_float(values.get("work_order_value")),
                work_order_date=_date(values.get("work_order_date")),
                contractor=_text(values.get("contractor")),
                document_id=document.id,
            )
        )
    elif result.doc_type == "invoice":
        session.add(
            Invoice(
                project_id=case_id,
                invoice_no=_text(values.get("invoice_no")),
                vendor=_text(values.get("vendor")),
                amount=_float(values.get("amount")),
                invoice_date=_date(values.get("invoice_date")),
                document_id=document.id,
            )
        )
    elif result.doc_type == "progress_report":
        session.add(
            ProgressReport(
                project_id=case_id,
                report_month=str(values.get("report_month") or ""),
                physical_pct=_float(values.get("physical_pct")),
                financial_pct=_float(values.get("financial_pct")),
                document_id=document.id,
            )
        )


def _ensure_project(session, case_id: str, values: dict) -> None:
    row = session.get(Project, case_id)
    if row is None:
        row = Project(
            project_id=case_id,
            name=str(values.get("name") or case_id),
            city=str(values.get("city") or ""),
            department=str(values.get("department") or ""),
            budget=_float(values.get("budget")) or 0.0,
            start_date=_date(values.get("start_date")) or date(2024, 4, 1),
            expected_end_date=_date(values.get("expected_end_date")) or date(2025, 4, 1),
            contractor=str(values.get("contractor") or ""),
        )
        session.add(row)
        session.flush()
        return
    for name in ("name", "city", "department", "contractor"):
        incoming = values.get(name)
        if incoming:
            setattr(row, name, str(incoming))
    if values.get("budget") not in (None, ""):
        row.budget = _float(values.get("budget")) or row.budget
    if values.get("start_date"):
        row.start_date = _date(values.get("start_date")) or row.start_date
    if values.get("expected_end_date"):
        row.expected_end_date = _date(values.get("expected_end_date")) or row.expected_end_date


def _text(value: object) -> str | None:
    if value is None:
        return None
    text = str(value).strip()
    return text or None


def _float(value: object) -> float | None:
    if value is None or value == "":
        return None
    return float(value)


def _date(value: object) -> date | None:
    if value is None or value == "":
        return None
    if isinstance(value, date):
        return value
    return date.fromisoformat(str(value))
