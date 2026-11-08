"""Guardrail pass rate for finding explanations. Separate from extraction accuracy."""

from __future__ import annotations

import random

from sqlalchemy import select

from core.config import ROOT, load_settings
from core.db import FindingRow, init_db, session_factory
from core.llm import make_client
from core.logging import setup_logging
from core.registry import discover_families
from engine.coverage import coverage
from explain.explain import explain_finding, explain_skipped

REPORT = ROOT / "evaluation" / "results" / "explanation_guardrail.md"
SAMPLE = 12
SEED = 42


def main() -> None:
    import argparse

    parser = argparse.ArgumentParser(description="Explanation guardrail pass rate.")
    parser.add_argument("--live", action="store_true")
    parser.add_argument("--sample", type=int, default=SAMPLE)
    args = parser.parse_args()
    settings = load_settings()
    setup_logging(settings.logging_level)
    init_db()
    client = make_client(live=args.live, settings=settings.llm)
    text = build_report(client, sample=args.sample)
    REPORT.parent.mkdir(parents=True, exist_ok=True)
    REPORT.write_text(text, encoding="utf-8")
    print(text)
    print(f"wrote={REPORT}")


def build_report(client, sample: int = SAMPLE) -> str:
    findings = _sample_findings(sample)
    passed = 0
    templated = 0
    for finding in findings:
        result = explain_finding(finding, client)
        if result["guardrail_passed"]:
            passed += 1
        if result["source"] == "template":
            templated += 1
    family = discover_families()[0]
    present = {family.document_types()[0].name}
    skipped = coverage(family.rules(), present)["rules_skipped"]
    skipped_text = [explain_skipped(item["rule_id"], item["reason"]) for item in skipped[:2]]
    rate = f"{passed / len(findings):.4f}" if findings else "n/a"
    lines = [
        "# Explanation guardrail",
        "",
        f"Sample of {len(findings)} stored layer 1-3 findings, seed {SEED}.",
        "A pass means every number in the explanation already appears in the finding, "
        "the text says 'requires manual verification', and it includes a manual-check line.",
        "A failure is replaced by a template. Skipped-check text below is a template and "
        "does not call a model.",
        "",
        f"- guardrail_pass_rate={rate}",
        f"- passed={passed}",
        f"- template_fallbacks={templated}",
        "",
        "## Skipped-check examples",
        "",
    ]
    lines.extend(skipped_text or ["No skipped examples."])
    lines.append("")
    return "\n".join(lines)


def _sample_findings(sample: int) -> list[dict]:
    with session_factory()() as session:
        rows = session.scalars(
            select(FindingRow).where(FindingRow.layer < 4).order_by(FindingRow.finding_id)
        ).all()
        payloads = [_payload(row) for row in rows]
    rng = random.Random(SEED)
    rng.shuffle(payloads)
    return payloads[:sample]


def _payload(row: FindingRow) -> dict:
    return {
        "rule_id": row.rule_id,
        "family": row.family,
        "layer": row.layer,
        "entity_type": row.entity_type,
        "entity_id": row.entity_id,
        "severity": row.severity,
        "expected_value": row.expected_value,
        "actual_value": row.actual_value,
        "difference": row.difference,
        "evidence": row.evidence,
    }


if __name__ == "__main__":
    main()
