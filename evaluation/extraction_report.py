"""Tier B field accuracy for the stratified PDF subset. Not mixed with Tier A."""

from __future__ import annotations

import json
from collections import Counter, defaultdict
from pathlib import Path

from core.config import ROOT, load_settings
from core.llm import make_client
from core.logging import setup_logging
from core.registry import discover_families
from ingestion.extractor import extract_document
from ingestion.pdf_reader import read_pdf
from ingestion.roundtrip import same_value
from ingestion.run import SELECTION_SEED, _read_labels, _read_manifest, select_cases

REPORT = ROOT / "evaluation" / "results" / "tier_b_extraction.md"
SKIP = {"document_copy"}


def main() -> None:
    import argparse

    parser = argparse.ArgumentParser(description="Tier B extraction accuracy.")
    parser.add_argument("--limit", type=int, default=30)
    parser.add_argument("--live", action="store_true")
    args = parser.parse_args()
    settings = load_settings()
    setup_logging(settings.logging_level)
    client = make_client(live=args.live, settings=settings.llm)
    text = build_report(client, limit=args.limit)
    REPORT.parent.mkdir(parents=True, exist_ok=True)
    REPORT.write_text(text, encoding="utf-8")
    print(text)
    print(f"wrote={REPORT}")


def build_report(client, limit: int = 30) -> str:
    families = {family.name: family for family in discover_families()}
    rows = select_cases(_read_manifest(), _read_labels(), limit, seed=SELECTION_SEED)
    stats: dict[tuple[str, str], Counter] = defaultdict(Counter)
    reasons: Counter = Counter()
    examples: list[str] = []
    for row in rows:
        family = families[row["family"]]
        outcome = _compare(family, row, client)
        bucket = stats[(row["family"], row["doc_type"])]
        bucket["fields"] += outcome["fields"]
        bucket["correct"] += outcome["correct"]
        bucket["documents"] += 1
        reasons.update(outcome["reasons"])
        for example in outcome["examples"]:
            if len(examples) < 10:
                examples.append(example)
    return _render(stats, reasons, client, limit, examples)


def _compare(family, row: dict, client) -> dict:
    path = Path(row["pdf_path"])
    pdf = read_pdf(path)
    ground = json.loads(row["ground_truth_json"])
    if pdf.unsupported_scanned:
        return {
            "fields": len(_ground_fields(ground)),
            "correct": 0,
            "reasons": Counter({"unsupported_scanned": len(_ground_fields(ground))}),
            "examples": [],
        }
    extracted = extract_document(
        family=family,
        doc_type=row["doc_type"],
        page_text=pdf.text,
        client=client,
        case_id=row["case_id"],
        filename=path.name,
        sha256=row["sha256"],
        page_count=len(pdf.pages),
    )
    low = {
        item.split(":", 1)[-1]
        for item in extracted.validation_errors
        if str(item).startswith("low_confidence")
    }
    fields = 0
    correct = 0
    reasons: Counter = Counter()
    examples: list[str] = []
    if not extracted.accepted:
        reasons["validation_failed"] += 1
    for name, expected in _ground_fields(ground).items():
        fields += 1
        actual = None if extracted.fields is None else extracted.fields.get(name)
        if same_value(actual, expected):
            correct += 1
            continue
        if actual in (None, ""):
            reasons["missing_field"] += 1
        else:
            reasons["value_mismatch"] += 1
        if name in low:
            reasons["low_confidence"] += 1
        examples.append(
            f"{row['family']} {row['case_id']} {row['doc_type']} {name}: "
            f"extracted={actual!r} ground_truth={expected!r}"
        )
    return {"fields": fields, "correct": correct, "reasons": reasons, "examples": examples}


def _ground_fields(ground: dict) -> dict:
    return {key: value for key, value in ground.items() if key not in SKIP}


def _render(stats, reasons: Counter, client, limit: int, examples: list[str]) -> str:
    totals = client.totals
    lines = [
        "# Tier B extraction accuracy",
        "",
        "Synthetic PDFs only. This report is not combined with Tier A.",
        f"Subset: {limit} cases, stratified by family and category, seed {SELECTION_SEED}.",
        "document_copy is ignored. A field is correct when the extracted value matches "
        "the manifest ground truth.",
        "",
        "family | doc_type | documents | fields | correct | accuracy",
        "--- | --- | --- | --- | --- | ---",
    ]
    grand_fields = 0
    grand_correct = 0
    for (family, doc_type), bucket in sorted(stats.items()):
        accuracy = _rate(bucket["correct"], bucket["fields"])
        lines.append(
            f"{family} | {doc_type} | {bucket['documents']} | {bucket['fields']} | "
            f"{bucket['correct']} | {accuracy}"
        )
        grand_fields += bucket["fields"]
        grand_correct += bucket["correct"]
    lines.append(
        f"all | all |  | {grand_fields} | {grand_correct} | {_rate(grand_correct, grand_fields)}"
    )
    lines.extend(["", "## Failure reasons", ""])
    if not reasons:
        lines.append("No field failures.")
    else:
        for name, count in reasons.most_common():
            lines.append(f"- {name}: {count}")
        lines.extend(["", "## Examples", ""])
        lines.extend(f"- {example}" for example in examples)
    lines.extend(
        [
            "",
            "## Tokens",
            "",
            "Cached calls were not sent to the provider. Live cost uses the configured "
            "per-million rates, which are the OpenAI rates and are not a Groq bill.",
            "",
            f"- cached calls={totals.cache_hits} input={totals.cached_input_tokens} "
            f"output={totals.cached_output_tokens} cost_usd=0.000000",
            f"- live calls={totals.fresh_calls} input={totals.fresh_input_tokens} "
            f"output={totals.fresh_output_tokens} cost_usd={totals.fresh_cost_usd:.6f}",
            "",
        ]
    )
    return "\n".join(lines)


def _rate(correct: int, fields: int) -> str:
    if not fields:
        return "n/a"
    return f"{correct / fields:.4f}"


if __name__ == "__main__":
    main()
