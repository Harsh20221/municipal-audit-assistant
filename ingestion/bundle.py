"""Check a set of uploaded files before they are stored. No interface yet."""

from __future__ import annotations

import hashlib
from pathlib import Path

from families.base import DocumentFamily
from ingestion.classifier import classify
from ingestion.extractor import extract_document
from ingestion.pdf_reader import read_pdf


def validate_bundle(family: DocumentFamily, files: list[dict], client) -> dict:
    """files items have path and slot (the document type the user chose)."""
    specs = family.document_types()
    by_name = {spec.name: spec for spec in specs}
    file_results = []
    seen_sha: dict[str, str] = {}
    case_ids: list[str] = []
    slot_counts: dict[str, int] = {}
    for item in files:
        path = Path(item["path"])
        slot = item["slot"]
        result = _check_file(
            family, path, slot, by_name, client, seen_sha, case_ids, slot_counts
        )
        file_results.append(result)
        if result["status"] != "error" and slot in by_name:
            slot_counts[slot] = slot_counts.get(slot, 0) + 1
    slots = _slots(specs, file_results)
    return {
        "files": file_results,
        "slots": slots,
        "verdict": _verdict(file_results, slots),
    }


def _check_file(
    family, path: Path, slot: str, by_name: dict, client, seen_sha, case_ids, slot_counts
) -> dict:
    messages: list[str] = []
    statuses: list[str] = []
    digest = hashlib.sha256(path.read_bytes()).hexdigest()
    if digest in seen_sha:
        return _file(
            path,
            slot,
            "warning",
            f"This file is a duplicate of {seen_sha[digest]}.",
            case_id="",
            classified=None,
        )
    seen_sha[digest] = path.name
    pdf = read_pdf(path)
    if pdf.unsupported_scanned:
        return _file(
            path,
            slot,
            "error",
            "This PDF has no text layer, so it is an unsupported scanned page.",
            case_id="",
            classified=None,
        )
    classified = classify(pdf.text, family.document_types(), client)
    if classified is None:
        statuses.append("error")
        messages.append("The document type could not be recognised.")
    elif classified != slot:
        statuses.append("error")
        label = by_name[slot].label if slot in by_name else slot
        found = by_name[classified].label if classified in by_name else classified
        messages.append(f"Wrong slot. This file looks like a {found}, not a {label}.")
    extract_type = classified if classified in by_name else slot if slot in by_name else None
    case_id = ""
    if extract_type is not None and not pdf.unsupported_scanned:
        extracted = extract_document(
            family=family,
            doc_type=extract_type,
            page_text=pdf.text,
            client=client,
            case_id="",
            filename=path.name,
            sha256=digest,
            page_count=len(pdf.pages),
        )
        raw = extracted.fields.get(family.case_id_field())
        case_id = "" if raw is None else str(raw).strip()
        if not extracted.accepted or not case_id:
            statuses.append("error")
            messages.append("The case identifier could not be read.")
        elif case_ids and case_id not in case_ids:
            statuses.append("error")
            messages.append(f"This document belongs to {case_id}, not {case_ids[0]}.")
        elif case_id:
            case_ids.append(case_id)
        low = [
            item
            for item in extracted.validation_errors
            if str(item).startswith("low_confidence")
        ]
        if low:
            statuses.append("warning")
            fields = ", ".join(item.split(":", 1)[-1] for item in low)
            messages.append(f"Low confidence on {fields}. Compare those fields with the page.")
    spec = by_name.get(slot)
    if spec is not None and not spec.allow_multiple and slot_counts.get(slot, 0) >= 1:
        statuses.append("error")
        messages.append(f"{spec.label} accepts one document for the case.")
    status = _worst(statuses)
    if status == "ok" and not messages:
        messages.append("Accepted.")
    return _file(path, slot, status, " ".join(messages), case_id=case_id, classified=classified)


def _slots(specs, file_results: list[dict]) -> list[dict]:
    counts: dict[str, int] = {spec.name: 0 for spec in specs}
    for row in file_results:
        if row["status"] == "error":
            continue
        if row["slot"] in counts:
            counts[row["slot"]] += 1
    slots = []
    for spec in specs:
        count = counts[spec.name]
        if count == 0 and spec.required:
            state = "missing"
        elif count > 1 and not spec.allow_multiple:
            state = "extra"
        else:
            state = "complete"
        slots.append(
            {
                "name": spec.name,
                "label": spec.label,
                "required": spec.required,
                "allow_multiple": spec.allow_multiple,
                "count": count,
                "status": state,
            }
        )
    return slots


def _verdict(file_results: list[dict], slots: list[dict]) -> str:
    if any(row["status"] == "error" for row in file_results):
        return "incomplete"
    if any(slot["status"] in {"missing", "extra"} for slot in slots):
        return "incomplete"
    if any(row["status"] == "warning" for row in file_results):
        return "ready with warnings"
    return "ready"


def _worst(statuses: list[str]) -> str:
    if "error" in statuses:
        return "error"
    if "warning" in statuses:
        return "warning"
    return "ok"


def _file(path: Path, slot: str, status: str, message: str, *, case_id: str, classified) -> dict:
    return {
        "filename": path.name,
        "slot": slot,
        "status": status,
        "message": message,
        "case_id": case_id,
        "classified": classified,
    }
