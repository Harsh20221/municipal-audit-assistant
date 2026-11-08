"""Generate structured data for every enabled family and write answer_key.csv."""

from __future__ import annotations

import csv
from pathlib import Path

from core.config import ROOT, load_settings
from core.db import init_db, session_factory
from core.logging import setup_logging
from core.registry import discover_families
from evaluation.metrics import category_counts

COMBINED_COLUMNS = ("family", "case_key", "label", "error_type", "rule_id")


def combined_answer_key_path() -> Path:
    return ROOT / "data" / "synthetic" / "answer_key.csv"


def main() -> None:
    settings = load_settings()
    setup_logging(settings.logging_level)
    init_db()
    combined: list[dict[str, str]] = []
    with session_factory()() as session:
        for family in discover_families():
            if family.name not in settings.generator.counts:
                raise KeyError(f"config generator.counts is missing {family.name}")
            result = family.generator().generate(
                session,
                n=settings.generator.counts[family.name],
                seed=settings.generator.seed,
                error_rate=settings.generator.error_rate,
                hard_negative_rate=settings.generator.hard_negative_rate,
                plan="quota",
            )
            for row in result.answer_key:
                combined.append(
                    {
                        "family": family.name,
                        "case_key": row["case_key"],
                        "label": row["label"],
                        "error_type": row["error_type"],
                        "rule_id": row["rule_id"],
                    }
                )
            counts = category_counts(result.answer_key)
            print(
                f"{family.name}: cases={result.cases} "
                + ", ".join(f"{name}={count}" for name, count in counts.items())
            )
        session.commit()
    path = combined_answer_key_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    ordered = sorted(combined, key=lambda item: (item["family"], item["case_key"], item["rule_id"]))
    with path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=COMBINED_COLUMNS)
        writer.writeheader()
        writer.writerows(ordered)
    print(f"answer_key={path}")


if __name__ == "__main__":
    main()
