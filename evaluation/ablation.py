"""Layer ablation on synthetic data. Families are not pooled.

Parameters in config were chosen on generator seed 42. Seed 43 is generated
with the same generator and is not used to pick thresholds. Both seeds are
printed. Each method is scored on its own, before the stored-finding rule
that drops a layer 4 feature already cited by a layer 1-3 finding.
"""

from __future__ import annotations

from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from core.config import ROOT, load_settings
from core.db import init_db
from core.logging import setup_logging
from core.registry import discover_families
from engine.finding import RuleContext
from engine.layer4_stats import iqr_flags, isolation_forest_flags, zscore_flags
from evaluation.metrics import _format_rate, _rate

TUNING_SEED = 42
REPORT_SEED = 43
METHODS = ("rules only", "z-score+IQR only", "Isolation Forest only", "combined")
INJECTED = {"single_error", "multi_error", "error"}
NEGATIVES = {"clean", "hard_negative"}


def rule_cases(family, session) -> set[str]:
    loaded = family.rule_params()
    context = RuleContext(
        session=session,
        family=family.name,
        params=loaded["values"],
        rule_version=loaded["version"],
    )
    cases: set[str] = set()
    for rule in family.rules():
        context.rule = rule
        for finding in rule.check(context):
            case_key = family.case_key_for_finding(session, finding.entity_type, finding.entity_id)
            if case_key is not None:
                cases.add(case_key)
    return cases


def method_cases(family, session, layer4) -> dict[str, set[str]]:
    frame = family.feature_frame(session)
    rules = rule_cases(family, session)
    stats = _cases(
        zscore_flags(frame, threshold=layer4.z_threshold, min_peer_group=layer4.min_peer_group)
    ) | _cases(iqr_flags(frame, k=layer4.iqr_k, min_peer_group=layer4.min_peer_group))
    forest = _cases(
        isolation_forest_flags(
            frame,
            contamination=layer4.contamination,
            min_peer_group=layer4.min_peer_group,
            random_state=layer4.random_state,
        )
    )
    return {
        "rules only": rules,
        "z-score+IQR only": stats,
        "Isolation Forest only": forest,
        "combined": rules | stats | forest,
    }


def score_methods(answer_key: list[dict[str, str]], methods: dict[str, set[str]]) -> list[dict]:
    labels = {row["case_key"]: row["label"] for row in answer_key}
    injected = {case for case, label in labels.items() if label in INJECTED}
    layer4 = {case for case, label in labels.items() if label == "needs_layer4"}
    negatives = {case for case, label in labels.items() if label in NEGATIVES}
    rows = []
    for name in METHODS:
        flagged = methods[name]
        false_cases = flagged & negatives
        rows.append(
            {
                "method": name,
                "injected_recall": _rate(len(flagged & injected), len(injected)),
                "layer4_recall": _rate(len(flagged & layer4), len(layer4)),
                "false_positives": len(false_cases),
                "negatives": len(negatives),
                "false_positive_rate": _rate(len(false_cases), len(negatives)),
                "injected_hits": len(flagged & injected),
                "injected": len(injected),
                "layer4_hits": len(flagged & layer4),
                "layer4": len(layer4),
            }
        )
    return rows


def render_report(sections: list[tuple[int, dict[str, list[dict]]]], settings) -> str:
    layer4 = settings.layer4
    lines = [
        "# Tier B layer ablation",
        "",
        "Synthetic structured data only. Families are scored separately and are",
        "not averaged into one number. Real documents have no anomaly ground truth.",
        "",
        f"Tuning seed: {TUNING_SEED}. Held-out seed: {REPORT_SEED}.",
        "The held-out corpus is a new draw from the same quota generator.",
        "Thresholds were chosen on the tuning seed only.",
        "",
        "Chosen parameters:",
        f"- z_threshold: {layer4.z_threshold:g}",
        f"- iqr_k: {layer4.iqr_k:g}",
        f"- contamination: {layer4.contamination:g}",
        f"- min_peer_group: {layer4.min_peer_group}",
        f"- Isolation Forest random_state: {layer4.random_state}",
        "",
        "Recall on injected errors is the share of single-error and multi-error",
        "cases flagged. Recall on needs_layer4 is the share of those statistical",
        "cases flagged. The false-positive rate uses clean and hard-negative",
        "cases only. A needs_layer4 miss is not counted as a false negative here.",
        "Layer 4 false positives are shown as counts, not removed.",
        "",
        "Selection rule on seed 42: among z_threshold in {3, 4, 5}, iqr_k in",
        "{1.5, 2.5, 3}, and contamination in {0.02, 0.03, 0.05}, keep settings",
        "whose z-score+IQR and Isolation Forest false-positive rates are each",
        "at or below 0.10 in both families, then take the highest average",
        "needs_layer4 recall. Ties prefer the lower average false-positive rate.",
        "",
    ]
    for seed, families in sections:
        role = "tuning result" if seed == TUNING_SEED else "held-out result"
        lines.append(f"# Seed {seed} ({role})")
        lines.append("")
        for family, rows in families.items():
            lines.append(f"## {family}")
            lines.append("")
            lines.append(
                "| method | injected recall | needs_layer4 recall | "
                "false positives | false-positive rate |"
            )
            lines.append("| --- | ---: | ---: | ---: | ---: |")
            for row in rows:
                lines.append(
                    "| {method} | {injected} | {layer4} | {fp} | {fpr} |".format(
                        method=row["method"],
                        injected=(
                            f"{row['injected_hits']}/{row['injected']} = "
                            f"{_format_rate(row['injected_recall'])}"
                        ),
                        layer4=(
                            f"{row['layer4_hits']}/{row['layer4']} = "
                            f"{_format_rate(row['layer4_recall'])}"
                        ),
                        fp=f"{row['false_positives']}/{row['negatives']}",
                        fpr=_format_rate(row["false_positive_rate"]),
                    )
                )
            lines.append("")
    return "\n".join(lines).rstrip() + "\n"


def build_sections(settings) -> list[tuple[int, dict[str, list[dict]]]]:
    sections = []
    for seed in (TUNING_SEED, REPORT_SEED):
        session = _session()
        families = discover_families()
        scored: dict[str, list[dict]] = {}
        for family in families:
            if family.name not in settings.generator.counts:
                raise KeyError(f"config generator.counts is missing {family.name}")
            result = family.generator().generate(
                session,
                n=settings.generator.counts[family.name],
                seed=seed,
                error_rate=settings.generator.error_rate,
                hard_negative_rate=settings.generator.hard_negative_rate,
                plan="quota",
                write_answer_key=False,
            )
            scored[family.name] = score_methods(
                result.answer_key, method_cases(family, session, settings.layer4)
            )
        sections.append((seed, scored))
    return sections


def main() -> None:
    settings = load_settings()
    setup_logging(settings.logging_level)
    report = render_report(build_sections(settings), settings)
    out = ROOT / "evaluation" / "results" / "tier_b_ablation.md"
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(report, encoding="utf-8")
    print(report)
    print(f"wrote {out}")


def _cases(flags) -> set[str]:
    return {flag.case_key for flag in flags}


def _session():
    engine = create_engine("sqlite://")
    init_db(engine)
    return sessionmaker(bind=engine, expire_on_commit=False)()


if __name__ == "__main__":
    main()
