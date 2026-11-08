"""Write a property-tax extraction into the family tables."""

from __future__ import annotations

from datetime import date

from sqlalchemy import delete, select

from core.db import Document, Extraction
from families.base import ExtractionResult
from families.property_tax.models import Property, TaxAssessment, TaxBill, TaxReceipt


def clear_case(session, case_id: str) -> None:
    session.execute(delete(TaxReceipt).where(TaxReceipt.case_key == case_id))
    session.execute(delete(TaxBill).where(TaxBill.case_key == case_id))
    session.execute(delete(TaxAssessment).where(TaxAssessment.case_key == case_id))
    prefix = f"{case_id}_"
    stale = session.scalars(
        select(Document).where(
            Document.family == "property_tax", Document.filename.startswith(prefix)
        )
    ).all()
    doc_ids = [row.id for row in stale]
    if doc_ids:
        session.execute(delete(Extraction).where(Extraction.document_id.in_(doc_ids)))
        session.execute(delete(Document).where(Document.id.in_(doc_ids)))
    session.execute(delete(Property).where(Property.case_key == case_id))


def persist_property(result: ExtractionResult, session) -> None:
    document = _document(result)
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
    case_id = result.case_id or str(values.get("property_id") or "")
    if not case_id:
        return
    _upsert_property(session, case_id, values)
    if result.doc_type == "assessment_form":
        session.add(
            TaxAssessment(
                case_key=case_id,
                fiscal_year=str(values.get("fiscal_year") or ""),
                property_id=_blank(values.get("property_id")),
                owner_name=_blank(values.get("owner_name")),
                assessed_tax=_float(values.get("assessed_tax")),
                exemption_amount=_float(values.get("exemption_amount")),
                document_id=document.id,
            )
        )
    elif result.doc_type == "tax_bill":
        session.add(
            TaxBill(
                case_key=case_id,
                fiscal_year=str(values.get("fiscal_year") or ""),
                property_id=_blank(values.get("property_id")),
                owner_name=_blank(values.get("owner_name")),
                assessed_tax=_float(values.get("assessed_tax")),
                exemption_amount=_float(values.get("exemption_amount")),
                penalty=_float(values.get("penalty")),
                amount_due=_float(values.get("amount_due")),
                issue_date=_date(values.get("issue_date")),
                due_date=_date(values.get("due_date")),
                document_id=document.id,
            )
        )
    elif result.doc_type == "payment_receipt":
        session.add(
            TaxReceipt(
                receipt_id=str(values.get("receipt_id") or f"{case_id}-receipt"),
                case_key=case_id,
                fiscal_year=str(values.get("fiscal_year") or ""),
                property_id=_blank(values.get("property_id")),
                owner_name=_blank(values.get("owner_name")),
                amount_paid=_float(values.get("amount_paid")),
                paid_date=_date(values.get("paid_date")),
                document_id=document.id,
            )
        )


def _upsert_property(session, case_id: str, values: dict) -> None:
    row = session.get(Property, case_id)
    if row is None:
        row = Property(
            case_key=case_id,
            property_id=case_id,
            owner_name=_text(values.get("owner_name")) or "Unknown",
            address=str(values.get("address") or ""),
            ward=str(values.get("ward") or ""),
            zone=str(values.get("zone") or ""),
            category=str(values.get("category") or ""),
            built_up_area_sqft=_float(values.get("built_up_area_sqft")) or 0.0,
            construction_year=int(values.get("construction_year") or 0),
            fiscal_year=str(values.get("fiscal_year") or ""),
        )
        session.add(row)
        return
    for name in ("address", "ward", "zone", "category", "fiscal_year"):
        incoming = values.get(name)
        if incoming:
            setattr(row, name, str(incoming))
    if values.get("built_up_area_sqft") not in (None, ""):
        row.built_up_area_sqft = _float(values.get("built_up_area_sqft")) or row.built_up_area_sqft
    if values.get("construction_year") not in (None, ""):
        row.construction_year = int(values["construction_year"])
    owner = _text(values.get("owner_name"))
    if owner and row.owner_name in {"", "Unknown"}:
        row.owner_name = owner


def _document(result: ExtractionResult) -> Document:
    return Document(
        sha256=result.sha256,
        filename=result.filename,
        family="property_tax",
        doc_type=result.doc_type,
        source="synthetic_pdf",
        status="unsupported_scanned" if result.is_scanned else result.status,
        page_count=result.page_count,
    )


def _blank(value: object) -> str | None:
    if value is None:
        return None
    text = str(value).strip()
    return text or None


def _text(value: object) -> str:
    return "" if value is None else str(value).strip()


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
