"""Case-level precision and recall for one family's answer key.

Each rule is scored on its own. A case may be a positive for more than one
rule. needs_layer4 rows are statistical outliers that obey the rules, so a
miss there is expected and is not a false negative.
"""

from __future__ import annotations

from collections import Counter, defaultdict

CATEGORY_ORDER = (
    "clean",
    "hard_negative",
    "single_error",
    "multi_error",
    "needs_layer4",
    "error",
)
RULE_LABELS = {"error", "single_error", "multi_error"}
FPR_LABELS = {"clean", "hard_negative"}


def category_counts(rows: list[dict[str, str]]) -> dict[str, int]:
    labels = {}
    for row in rows:
        labels[row["case_key"]] = row["label"]
    counts = Counter(labels.values())
    return {
        name: counts.get(name, 0)
        for name in CATEGORY_ORDER
        if counts.get(name, 0) or name != "error"
    }


def score_cases(rows: list[dict[str, str]], hits: dict[str, set[str]]) -> dict:
    labels: dict[str, str] = {}
    expected: dict[str, set[str]] = defaultdict(set)
    for row in rows:
        labels[row["case_key"]] = row["label"]
        rule_id = row.get("rule_id") or ""
        if rule_id and labels[row["case_key"]] != "needs_layer4":
            expected[row["case_key"]].add(rule_id)
    known_rules = {rule_id for rules in expected.values() for rule_id in rules}
    rule_ids = sorted(known_rules | set(hits))
    per_rule = []
    totals = {"tp": 0, "fp": 0, "fn": 0}
    for rule_id in rule_ids:
        predicted = hits.get(rule_id, set())
        labeled = {case_key for case_key, rules in expected.items() if rule_id in rules}
        tp = len(predicted & labeled)
        fp = len(predicted - labeled)
        fn = len(labeled - predicted)
        totals["tp"] += tp
        totals["fp"] += fp
        totals["fn"] += fn
        per_rule.append(
            {
                "rule_id": rule_id,
                "tp": tp,
                "fp": fp,
                "fn": fn,
                "precision": _rate(tp, tp + fp),
                "recall": _rate(tp, tp + fn),
            }
        )
    flagged = set().union(*hits.values()) if hits else set()
    fpr_pool = [case_key for case_key, label in labels.items() if label in FPR_LABELS]
    false_cases = [case_key for case_key in fpr_pool if case_key in flagged]
    layer4 = [case_key for case_key, label in labels.items() if label == "needs_layer4"]
    layer4_flagged = [case_key for case_key in layer4 if case_key in flagged]
    return {
        "rules": per_rule,
        "categories": category_counts(rows),
        "micro_precision": _rate(totals["tp"], totals["tp"] + totals["fp"]),
        "micro_recall": _rate(totals["tp"], totals["tp"] + totals["fn"]),
        "false_positive_cases": len(false_cases),
        "negative_cases": len(fpr_pool),
        "false_positive_rate": _rate(len(false_cases), len(fpr_pool)),
        "needs_layer4_cases": len(layer4),
        "needs_layer4_expected_misses": len(layer4) - len(layer4_flagged),
        "needs_layer4_unexpected_hits": len(layer4_flagged),
        "tp": totals["tp"],
        "fp": totals["fp"],
        "fn": totals["fn"],
    }


def _rate(numerator: int, denominator: int) -> float | None:
    if denominator == 0:
        return None
    return numerator / denominator


def render_family(family: str, summary: dict) -> str:
    lines = [
        f"## {family}",
        "",
        "| rule_id | tp | fp | fn | precision | recall |",
        "| --- | ---: | ---: | ---: | ---: | ---: |",
    ]
    for row in summary["rules"]:
        lines.append(
            "| {rule_id} | {tp} | {fp} | {fn} | {precision} | {recall} |".format(
                rule_id=row["rule_id"],
                tp=row["tp"],
                fp=row["fp"],
                fn=row["fn"],
                precision=_format_rate(row["precision"]),
                recall=_format_rate(row["recall"]),
            )
        )
    category_text = ", ".join(
        f"{name} {summary['categories'].get(name, 0)}" for name in summary.get("categories", {})
    )
    lines.extend(
        [
            "",
            f"Categories: {category_text}.",
            (
                f"Micro precision: {_format_rate(summary['micro_precision'])}. "
                f"Micro recall: {_format_rate(summary['micro_recall'])}."
            ),
            (
                "False-positive rate on clean and hard-negative cases: "
                f"{summary['false_positive_cases']}/{summary['negative_cases']} "
                f"= {_format_rate(summary['false_positive_rate'])}."
            ),
            (
                "Expected misses by rules: "
                f"{summary['needs_layer4_expected_misses']}/{summary['needs_layer4_cases']} "
                "needs_layer4 cases had no rule finding."
            ),
            (
                "Unexpected rule hits on needs_layer4: "
                f"{summary['needs_layer4_unexpected_hits']}."
            ),
            "",
        ]
    )
    return "\n".join(lines)


def _format_rate(value: float | None) -> str:
    if value is None:
        return "n/a"
    return f"{value:.3f}"
