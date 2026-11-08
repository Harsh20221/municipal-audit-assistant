"""Score hand-labeled public documents. Never mixed with the Tier B report."""

from __future__ import annotations

import csv
from collections import Counter
from pathlib import Path

import yaml

from core.config import ROOT
from core.llm import make_client
from core.registry import discover_families
from ingestion.extractor import extract_document
from ingestion.pdf_reader import read_pdf
from ingestion.roundtrip import same_value

MANIFEST = ROOT / "data_sources" / "manifest.yaml"
LABELS = ROOT / "data" / "gold" / "gold_labels.csv"
REPORT = ROOT / "evaluation" / "results" / "tier_a_extraction.md"


def main() -> None:
    text = build_report(client=make_client(live=False))
    REPORT.parent.mkdir(parents=True, exist_ok=True)
    REPORT.write_text(text, encoding="utf-8")
    print(text)
    print(f"wrote={REPORT}")


def build_report(
    manifest_path: Path = MANIFEST,
    labels_path: Path = LABELS,
    client=None,
    pdf_root: Path | None = None,
) -> str:
    documents = _documents(manifest_path)
    labels = _labels(labels_path)
    by_sha = {item["sha256"]: item for item in documents}
    root = pdf_root or (ROOT / "data" / "real")
    families = discover_families()
    compared = 0
    correct = 0
    reasons: Counter = Counter()
    for row in labels:
        sha = row["sha256"].strip()
        if not sha:
            continue
        document = by_sha.get(sha)
        if document is None:
            reasons["not_in_manifest"] += 1
            continue
        if document.get("is_scanned"):
            reasons["unsupported_scanned"] += 1
            compared += 1
            continue
        pdf_path = root / f"{sha}.pdf"
        if not pdf_path.exists():
            reasons["file_not_available"] += 1
            continue
        family = _family_for(families, row["doc_type"])
        if family is None or client is None:
            reasons["no_family_for_doc_type"] += 1
            continue
        compared += 1
        if _field_matches(family, pdf_path, row, client):
            correct += 1
        else:
            reasons["value_mismatch"] += 1
    lines = [
        "# Tier A extraction",
        "",
        "Public documents with hand labels only. These numbers are not combined "
        "with the Tier B synthetic report.",
        "",
        f"- manifest_documents={len(documents)}",
        f"- gold_rows={len(labels)}",
        f"- rows_with_a_manifest_match={compared}",
        f"- correct={correct}",
        "",
        "## Notes",
        "",
    ]
    if not labels:
        lines.append("No hand labels yet. Fill data/gold/gold_labels.csv and rerun.")
    elif compared == 0:
        lines.append(
            "Labels are present, but no matching text PDF was found under data/real. "
            "Place each file at data/real/<sha256>.pdf. Scanned pages are not scored."
        )
    if reasons:
        lines.append("")
        for name, count in reasons.most_common():
            lines.append(f"- {name}: {count}")
    lines.append("")
    return "\n".join(lines)


def _documents(path: Path) -> list[dict]:
    if not path.exists():
        return []
    loaded = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    return list(loaded.get("documents") or [])


def _family_for(families, doc_type: str):
    for family in families:
        if any(spec.name == doc_type for spec in family.document_types()):
            return family
    return None


def _field_matches(family, pdf_path: Path, row: dict, client) -> bool:
    pdf = read_pdf(pdf_path)
    extracted = extract_document(
        family=family,
        doc_type=row["doc_type"],
        page_text=pdf.text,
        client=client,
        case_id="",
        filename=pdf_path.name,
        sha256=row["sha256"],
        page_count=len(pdf.pages),
    )
    actual = None if not extracted.fields else extracted.fields.get(row["field"])
    return same_value(actual, row["value"])


def _labels(path: Path) -> list[dict[str, str]]:
    if not path.exists():
        return []
    with path.open(newline="", encoding="utf-8") as handle:
        return [row for row in csv.DictReader(handle) if any(row.values())]


if __name__ == "__main__":
    main()
