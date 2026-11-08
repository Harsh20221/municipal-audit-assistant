"""JSON extraction against a document schema, with one validation retry."""

from __future__ import annotations

from pydantic import ValidationError

from families.base import DocumentFamily, ExtractionResult
from ingestion.grounding import ground_fields
from ingestion.normalizers import normalize_fields


def extract_document(
    *,
    family: DocumentFamily,
    doc_type: str,
    page_text: str,
    client,
    case_id: str,
    filename: str,
    sha256: str,
    page_count: int,
) -> ExtractionResult:
    spec = next(item for item in family.document_types() if item.name == doc_type)
    prompt = _prompt(family, doc_type, page_text)
    errors: list[str] = []
    payload: dict = {}
    model_name = client.settings.model
    for attempt in range(2):
        try:
            response = client.complete_json(prompt)
            model_name = response.model
            payload = normalize_fields(response.json_data or {})
            model = spec.schema.model_validate(payload)
        except (ValidationError, ValueError, TypeError) as exc:
            errors = [f"validation:{exc}"]
            if attempt == 0:
                prompt = _prompt(family, doc_type, page_text) + (
                    "\nThe previous JSON failed validation. Fix it and return one JSON object.\n"
                    f"{exc}"
                )
                continue
            return ExtractionResult(
                doc_type=doc_type,
                fields=payload,
                field_pages={key: 1 for key in payload},
                model_name=model_name,
                validation_errors=errors,
                case_id=case_id,
                filename=filename,
                sha256=sha256,
                page_count=page_count,
                accepted=False,
            )
        dumped = model.model_dump(mode="json")
        pages, low_confidence = ground_fields(model.model_dump(), page_text)
        return ExtractionResult(
            doc_type=doc_type,
            fields=dumped,
            field_pages=pages,
            model_name=model_name,
            validation_errors=low_confidence,
            case_id=case_id,
            filename=filename,
            sha256=sha256,
            page_count=page_count,
            accepted=True,
        )
    raise RuntimeError("extraction loop ended without a result")


def _prompt(family: DocumentFamily, doc_type: str, page_text: str) -> str:
    return (
        family.extraction_prompt(doc_type)
        + "\nReturn one JSON object and nothing else. Use null when a field is absent.\n"
        + "DOCUMENT_TEXT_START\n"
        + page_text
        + "\nDOCUMENT_TEXT_END\n"
    )
