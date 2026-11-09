"""Turn registry objects and stored rows into API payloads."""

from __future__ import annotations

import tempfile
from pathlib import Path

from sqlalchemy import select
from sqlalchemy.orm import Session

from core.config import ROOT
from core.db import Document, FindingRow, RiskScore
from engine.coverage import coverage
from engine.runner import run_audit
from explain.explain import explain_finding, explain_skipped
from families.base import DocumentFamily
from ingestion.bundle import validate_bundle
from ingestion.pipeline import ingest_pdf

LAYER4_NOTE = (
    "Statistical (Layer 4) flags compare this case with the reference baseline "
    "population. They are indicative only and require manual verification."
)
NOTICES = (
    "Digital (text-selectable) PDFs only; scanned documents are not supported.",
    "Document text is sent to the configured LLM provider for extraction; "
    "do not upload documents you are not allowed to share.",
)
EVALUATION_FILES = {
    "tier_b_rules": ROOT / "evaluation" / "results" / "tier_b_rules.md",
    "tier_b_ablation": ROOT / "evaluation" / "results" / "tier_b_ablation.md",
    "tier_b_extraction": ROOT / "evaluation" / "results" / "tier_b_extraction.md",
    "tier_a_extraction": ROOT / "evaluation" / "results" / "tier_a_extraction.md",
    "explanation_guardrail": ROOT / "evaluation" / "results" / "explanation_guardrail.md",
}
EVALUATION_NOTE = (
    "Tier B is the synthetic corpus with a known answer key. "
    "Tier A is hand-labeled public documents. The two tiers are never combined."
)


def family_map(families: list[DocumentFamily]) -> dict[str, DocumentFamily]:
    return {family.name: family for family in families}


def requirements_payload(family: DocumentFamily) -> dict:
    payload = family.requirements()
    documents = []
    for document in payload["documents"]:
        documents.append(
            {
                **document,
                "sample_url": f"/api/v1/samples/{family.name}/{document['name']}",
            }
        )
    return {
        "family": family.name,
        "description": family.description,
        "documents": documents,
        "rules": payload["rules"],
        "notices": list(NOTICES),
    }


def sample_path(family: DocumentFamily, doc_type: str) -> Path | None:
    for spec in family.document_types():
        if spec.name != doc_type or not spec.sample_pdf_path:
            return None
        path = (ROOT / spec.sample_pdf_path).resolve()
        if not path.is_relative_to(ROOT.resolve()) or not path.is_file():
            return None
        return path
    return None


def save_uploads(files: list, slots: list[str]) -> list[dict]:
    directory = Path(tempfile.mkdtemp(prefix="audit-upload-"))
    saved = []
    for upload, slot in zip(files, slots, strict=True):
        name = Path(upload.filename or "upload.pdf").name
        slot_dir = directory / slot
        slot_dir.mkdir(parents=True, exist_ok=True)
        path = slot_dir / name
        path.write_bytes(upload.file.read())
        saved.append({"path": path, "slot": slot, "filename": name})
    return saved


def bundle_for(family: DocumentFamily, saved: list[dict], client) -> dict:
    return validate_bundle(family, saved, client)


def audit_saved(
    family: DocumentFamily,
    saved: list[dict],
    client,
    session: Session,
    *,
    run_with_available: bool,
) -> dict:
    bundle = bundle_for(family, saved, client)
    missing = [slot["label"] for slot in bundle["slots"] if slot["status"] == "missing"]
    if missing and not run_with_available:
        raise ValueError(
            "Required documents are missing: "
            + ", ".join(missing)
            + ". Choose run with available documents to continue."
        )
    accepted = [
        row for row in bundle["files"] if row["status"] != "error" and row["case_id"]
    ]
    if not accepted:
        raise ValueError("No document could be read, so nothing was audited.")
    case_ids = sorted({row["case_id"] for row in accepted})
    if len(case_ids) != 1:
        raise ValueError("These documents do not belong to one case: " + ", ".join(case_ids))
    case_id = case_ids[0]
    by_name = {Path(item["path"]).name: item for item in saved}
    family.clear_case(session, case_id)
    for row in accepted:
        source = _match_saved(saved, row, by_name)
        ingest_pdf(
            Path(source["path"]),
            family,
            client,
            session,
            case_id=case_id,
            doc_type_hint=row["slot"],
        )
    session.commit()
    run_audit(session, [family])
    present = {row["slot"] for row in accepted}
    report = coverage(family.rules(), present)
    findings = _case_findings(session, family, case_id, client)
    risk = _risk(session, family, case_id)
    skipped = [
        {
            "rule_id": item["rule_id"],
            "reason": item["reason"],
            "explanation": explain_skipped(item["rule_id"], item["reason"]),
        }
        for item in report["rules_skipped"]
    ]
    return {
        "case_id": case_id,
        "family": family.name,
        "bundle": bundle,
        "risk": risk,
        "findings": findings,
        "coverage": {"rules_run": report["rules_run"], "rules_skipped": skipped},
        "layer4_note": LAYER4_NOTE,
    }


def list_findings(
    session: Session,
    families: list[DocumentFamily],
    *,
    family: str | None,
    severity: str | None,
    rule_id: str | None,
    status: str | None,
) -> list[dict]:
    query = select(FindingRow)
    if family:
        query = query.where(FindingRow.family == family)
    if severity:
        query = query.where(FindingRow.severity == severity)
    if rule_id:
        query = query.where(FindingRow.rule_id == rule_id)
    if status:
        query = query.where(FindingRow.review_status == status)
    rows = session.scalars(query.order_by(FindingRow.family, FindingRow.rule_id)).all()
    names = _filenames(session, rows)
    return [_finding_dict(row, names) for row in rows]


def finding_dict(session: Session, row: FindingRow) -> dict:
    names = _filenames(session, [row])
    return _finding_dict(row, names)


def evaluation_summary() -> dict:
    payload = {"note": EVALUATION_NOTE}
    for key, path in EVALUATION_FILES.items():
        payload[key] = path.read_text(encoding="utf-8") if path.exists() else ""
    return payload


def guide_payload(families: list[DocumentFamily]) -> dict:
    sources = ROOT / "docs" / "DATA_SOURCES.md"
    return {
        "limitations": [
            "Only digital PDFs with a text layer are supported. Scanned pages are skipped.",
            "Property-tax rates and project thresholds are illustrative, not an official schedule.",
            "Tier B measures synthetic documents. Tier A measures hand-labeled public documents. "
            "They are never combined.",
            "Every finding requires manual verification.",
        ],
        "sources_markdown": sources.read_text(encoding="utf-8") if sources.exists() else "",
        "families": [requirements_payload(family) for family in families],
    }


def _case_findings(session, family: DocumentFamily, case_id: str, client) -> list[dict]:
    rows = session.scalars(select(FindingRow).where(FindingRow.family == family.name)).all()
    names = _filenames(session, rows)
    matched = []
    for row in rows:
        key = family.case_key_for_finding(session, row.entity_type, row.entity_id)
        if key != case_id:
            continue
        payload = _finding_dict(row, names)
        explained = explain_finding(payload, client)
        payload["explanation"] = explained["text"]
        matched.append(payload)
    return matched


def _risk(session, family: DocumentFamily, case_id: str) -> dict | None:
    row = session.scalar(
        select(RiskScore).where(
            RiskScore.family == family.name,
            RiskScore.entity_type == family.case_entity_type,
            RiskScore.entity_id == case_id,
        )
    )
    if row is None:
        return None
    return {
        "family": row.family,
        "entity_type": row.entity_type,
        "entity_id": row.entity_id,
        "score": row.score,
        "band": row.band,
    }


def _finding_dict(row: FindingRow, names: dict[int, str]) -> dict:
    evidence = []
    for item in row.evidence or []:
        doc_id = item.get("doc_id")
        evidence.append(
            {
                "doc_id": doc_id,
                "filename": names.get(doc_id) if doc_id is not None else None,
                "page": item.get("page"),
                "field": item.get("field") or "",
            }
        )
    return {
        "finding_id": row.finding_id,
        "family": row.family,
        "rule_id": row.rule_id,
        "layer": row.layer,
        "entity_type": row.entity_type,
        "entity_id": row.entity_id,
        "severity": row.severity,
        "expected_value": row.expected_value,
        "actual_value": row.actual_value,
        "difference": row.difference,
        "evidence": evidence,
        "review_status": row.review_status,
        "explanation": "",
    }


def _filenames(session, rows: list[FindingRow]) -> dict[int, str]:
    ids = set()
    for row in rows:
        for item in row.evidence or []:
            if item.get("doc_id") is not None:
                ids.add(item["doc_id"])
    if not ids:
        return {}
    documents = session.scalars(select(Document).where(Document.id.in_(ids))).all()
    return {document.id: document.filename for document in documents}


def _match_saved(saved: list[dict], result: dict, by_name: dict) -> dict:
    for item in saved:
        if item["slot"] == result["slot"] and item["filename"] == result["filename"]:
            return item
    return by_name.get(result["filename"], saved[0])
