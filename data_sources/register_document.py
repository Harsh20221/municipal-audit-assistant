"""Append one public document to data_sources/manifest.yaml. Does not download it."""

from __future__ import annotations

import argparse
import hashlib
from datetime import date
from pathlib import Path

import yaml

from ingestion.pdf_reader import read_pdf

MANIFEST = Path(__file__).with_name("manifest.yaml")
FIELDS = (
    "source_url",
    "retrieved_at",
    "publisher",
    "doc_type",
    "language",
    "is_scanned",
    "license_note",
    "contains_personal_data",
    "sha256",
)


def main() -> None:
    parser = argparse.ArgumentParser(description="Register a public document.")
    parser.add_argument("--pdf", required=True, type=Path)
    parser.add_argument("--source-url", required=True)
    parser.add_argument("--publisher", required=True)
    parser.add_argument("--doc-type", required=True)
    parser.add_argument("--language", default="en")
    parser.add_argument("--retrieved-at", default=date.today().isoformat())
    parser.add_argument("--license-note", default="")
    parser.add_argument("--contains-personal-data", action="store_true")
    args = parser.parse_args()
    record = register(args)
    print(f"sha256={record['sha256']} is_scanned={record['is_scanned']}")


def register(args) -> dict:
    pdf_path = Path(args.pdf)
    digest = hashlib.sha256(pdf_path.read_bytes()).hexdigest()
    scanned = read_pdf(pdf_path).unsupported_scanned
    record = {
        "source_url": args.source_url,
        "retrieved_at": args.retrieved_at,
        "publisher": args.publisher,
        "doc_type": args.doc_type,
        "language": args.language,
        "is_scanned": bool(scanned),
        "license_note": args.license_note,
        "contains_personal_data": bool(args.contains_personal_data),
        "sha256": digest,
    }
    loaded = {}
    if MANIFEST.exists():
        loaded = yaml.safe_load(MANIFEST.read_text(encoding="utf-8")) or {}
    documents = list(loaded.get("documents") or [])
    documents = [item for item in documents if item.get("sha256") != digest]
    documents.append(record)
    MANIFEST.write_text(
        yaml.safe_dump({"documents": documents}, sort_keys=False),
        encoding="utf-8",
    )
    return record


if __name__ == "__main__":
    main()
