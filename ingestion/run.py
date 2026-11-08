"""Ingest a limited set of synthetic PDFs. Live calls require --live."""

from __future__ import annotations

import argparse
import csv
import json
import random
import time
from collections import defaultdict
from pathlib import Path

from sqlalchemy import select

from core.config import load_settings
from core.db import Document, Extraction, init_db, session_factory
from core.llm import make_client
from core.logging import setup_logging
from core.registry import discover_families
from engine.runner import run_audit
from evaluation.generate_data import combined_answer_key_path
from ingestion.build_pdfs import MANIFEST, build_all
from ingestion.pipeline import ingest_pdf
from ingestion.roundtrip import (
    CASE_CATEGORIES,
    agreement_summary,
    field_differences,
    layer_rule_counts,
    render_case_table,
    render_value_diffs,
)

SELECTION_SEED = 42


def main() -> None:
    parser = argparse.ArgumentParser(description="Ingest synthetic digital PDFs.")
    parser.add_argument(
        "--limit",
        type=int,
        default=5,
        help=(
            "Number of cases to ingest. Each case keeps all of its PDFs. "
            "Cases are stratified by family and category with seed 42."
        ),
    )
    parser.add_argument(
        "--live",
        action="store_true",
        help="Call the live provider. The default client is the deterministic fake.",
    )
    args = parser.parse_args()
    if args.limit < 1:
        raise SystemExit("--limit must be at least 1")
    settings = load_settings()
    setup_logging(settings.logging_level)
    init_db()
    client = make_client(live=args.live, settings=settings.llm)
    families = {family.name: family for family in discover_families()}
    with session_factory()() as session:
        if not MANIFEST.exists():
            build_all(session)
        manifest = _read_manifest()
        labels = _read_labels()
        complete_rows = select_cases(manifest, labels, args.limit, seed=SELECTION_SEED)
        case_ids = {row["case_id"] for row in complete_rows}
        meta = {
            row["case_id"]: {
                "family": row["family"],
                "category": labels.get((row["family"], row["case_id"]), ""),
            }
            for row in complete_rows
        }
        provider = getattr(client, "provider", "fake")
        model = client.cache_model() if args.live else "fake"
        print(
            f"limit={args.limit} ingesting={len(complete_rows)} "
            f"cases={len(case_ids)} live={args.live} provider={provider} model={model}"
        )
        run_audit(session, list(families.values()))
        before = layer_rule_counts(session, list(families.values()), case_ids)
        cleared: set[tuple[str, str]] = set()
        ingested = 0
        for row in complete_rows:
            family = families[row["family"]]
            key = (row["family"], row["case_id"])
            if key not in cleared:
                family.clear_case(session, row["case_id"])
                cleared.add(key)
            calls_before = client.totals.calls
            cache_before = client.totals.cache_hits
            ingest_pdf(
                Path(row["pdf_path"]),
                family,
                client,
                session,
                case_id=row["case_id"],
                doc_type_hint=row["doc_type"],
            )
            ingested += 1
            fresh_call = (
                args.live
                and client.totals.calls > calls_before
                and client.totals.cache_hits == cache_before
            )
            if fresh_call:
                time.sleep(3)
        session.commit()
        run_audit(session, list(families.values()))
        after = layer_rule_counts(session, list(families.values()), case_ids)
        print(f"ingested_pdfs={ingested}")
        totals = client.totals
        print(
            "tokens_cached "
            f"input={totals.cached_input_tokens} output={totals.cached_output_tokens} "
            f"calls={totals.cache_hits} cost_usd=0.000000"
        )
        print(
            "tokens_live "
            f"input={totals.fresh_input_tokens} output={totals.fresh_output_tokens} "
            f"calls={totals.fresh_calls} cost_usd={totals.fresh_cost_usd:.6f}"
        )
        summary = agreement_summary(before, after)
        print(
            "Round-trip, layers 1-3 only. "
            f"cases_compared={summary['compared']} agreed={summary['agreed']} "
            f"mismatched={summary['mismatched']}"
        )
        print(render_case_table(before, after, meta))
        mismatched_ids = {item["case_id"] for item in summary["details"]}
        print(render_value_diffs(_value_rows(session, complete_rows, mismatched_ids)))
        for item in summary["details"]:
            print(
                f"mismatch {item['case_id']}: "
                f"structured={item['structured']} pdf={item['pdf']}"
            )


def _read_manifest() -> list[dict[str, str]]:
    with MANIFEST.open(newline="", encoding="utf-8") as handle:
        return list(csv.DictReader(handle))


def _read_labels() -> dict[tuple[str, str], str]:
    path = combined_answer_key_path()
    labels: dict[tuple[str, str], str] = {}
    with path.open(newline="", encoding="utf-8") as handle:
        for row in csv.DictReader(handle):
            labels.setdefault((row["family"], row["case_key"]), row["label"])
    return labels


def select_cases(
    rows: list[dict[str, str]],
    labels: dict[tuple[str, str], str],
    limit: int,
    seed: int = SELECTION_SEED,
) -> list[dict[str, str]]:
    """Choose whole cases, stratified by family and category.

    Round-robin across every family and every answer-key category, in a fixed
    order, after shuffling each bucket with seed. A case is returned with all
    of its PDFs. The walk stops at `limit` cases.
    """
    grouped: dict[tuple[str, str], list[dict[str, str]]] = defaultdict(list)
    order: list[tuple[str, str]] = []
    for row in rows:
        key = (row["family"], row["case_id"])
        if key not in grouped:
            order.append(key)
        grouped[key].append(row)
    buckets: dict[tuple[str, str], list[tuple[str, str]]] = defaultdict(list)
    for key in order:
        category = labels.get(key, "")
        if category in CASE_CATEGORIES:
            buckets[(key[0], category)].append(key)
    rng = random.Random(seed)
    for key in buckets:
        rng.shuffle(buckets[key])
    families = sorted({family for family, _category in buckets})
    strata = [
        (family, category)
        for family in families
        for category in CASE_CATEGORIES
        if buckets[(family, category)]
    ]
    chosen_keys: list[tuple[str, str]] = []
    while len(chosen_keys) < limit:
        progressed = False
        for stratum in strata:
            bucket = buckets[stratum]
            if not bucket:
                continue
            chosen_keys.append(bucket.pop())
            progressed = True
            if len(chosen_keys) >= limit:
                break
        if not progressed:
            break
    chosen_set = set(chosen_keys)
    chosen: list[dict[str, str]] = []
    for key in order:
        if key in chosen_set:
            chosen.extend(grouped[key])
    return chosen


def _value_rows(session, manifest_rows: list[dict[str, str]], case_ids: set[str]) -> list[dict]:
    relevant = [row for row in manifest_rows if row["case_id"] in case_ids]
    shas = [row["sha256"] for row in relevant]
    documents = session.scalars(select(Document).where(Document.sha256.in_(shas))).all()
    by_sha = {row.sha256: row for row in documents}
    extracted: dict[str, dict | None] = {}
    if documents:
        doc_ids = [row.id for row in documents]
        for item in session.scalars(
            select(Extraction).where(Extraction.document_id.in_(doc_ids))
        ).all():
            document = next(row for row in documents if row.id == item.document_id)
            extracted[document.sha256] = item.fields_json
    diffs = []
    for row in relevant:
        ground_truth = json.loads(row["ground_truth_json"])
        fields = extracted.get(row["sha256"]) if row["sha256"] in by_sha else None
        for field, actual, expected in field_differences(fields, ground_truth):
            diffs.append(
                {
                    "case_id": row["case_id"],
                    "doc_type": row["doc_type"],
                    "field": field,
                    "extracted": actual,
                    "ground_truth": expected,
                }
            )
    return diffs


if __name__ == "__main__":
    try:
        main()
    except Exception as exc:
        from core.llm import _is_quota_error

        if _is_quota_error(exc):
            print(
                "The live provider has no credits left, so this run stopped. "
                "OpenAI returned credit_balance_exhausted. "
                "Set LLM_PROVIDER=groq in .env to use Groq, or add OpenAI billing."
            )
            raise SystemExit(1) from None
        raise
