"""Ingest one digital PDF into a family."""

from __future__ import annotations

import hashlib
from pathlib import Path

from sqlalchemy import delete, select

from core.db import Document, Extraction
from families.base import DocumentFamily, ExtractionResult
from ingestion.classifier import classify
from ingestion.extractor import extract_document
from ingestion.pdf_reader import read_pdf


def ingest_pdf(
    path: Path,
    family: DocumentFamily,
    client,
    session,
    *,
    case_id: str,
    doc_type_hint: str | None = None,
) -> ExtractionResult:
    pdf = read_pdf(path)
    digest = hashlib.sha256(path.read_bytes()).hexdigest()
    _drop_existing_sha(session, digest)
    if pdf.unsupported_scanned:
        result = ExtractionResult(
            doc_type=doc_type_hint or "unknown",
            fields={},
            field_pages={},
            model_name=client.settings.model,
            validation_errors=["unsupported_scanned"],
            case_id=case_id,
            filename=path.name,
            sha256=digest,
            page_count=len(pdf.pages),
            is_scanned=True,
            status="unsupported_scanned",
            accepted=False,
        )
        family.persist(result, session)
        return result
    doc_type = classify(pdf.text, family.document_types(), client)
    if doc_type is None:
        result = ExtractionResult(
            doc_type=doc_type_hint or "unknown",
            fields={},
            field_pages={},
            model_name=client.settings.model,
            validation_errors=["unclassified"],
            case_id=case_id,
            filename=path.name,
            sha256=digest,
            page_count=len(pdf.pages),
            status="unclassified",
            accepted=False,
        )
        family.persist(result, session)
        return result
    result = extract_document(
        family=family,
        doc_type=doc_type,
        page_text=pdf.text,
        client=client,
        case_id=case_id,
        filename=path.name,
        sha256=digest,
        page_count=len(pdf.pages),
    )
    family.persist(result, session)
    return result


def _drop_existing_sha(session, digest: str) -> None:
    existing = session.scalar(select(Document).where(Document.sha256 == digest))
    if existing is None:
        return
    session.execute(delete(Extraction).where(Extraction.document_id == existing.id))
    session.delete(existing)
    session.flush()
