"""Report which rules can run for the documents a case actually has.

A rule whose documents are missing is skipped. It is not treated as a pass.
"""

from __future__ import annotations

from engine.finding import Rule


def coverage(rules: list[Rule], present_doc_types: set[str] | list[str]) -> dict:
    present = set(present_doc_types)
    rules_run: list[str] = []
    rules_skipped: list[dict[str, str]] = []
    for rule in rules:
        missing = [name for name in rule.requires_doc_types if name not in present]
        if missing:
            rules_skipped.append(
                {"rule_id": rule.rule_id, "reason": "missing: " + ", ".join(missing)}
            )
        else:
            rules_run.append(rule.rule_id)
    return {"rules_run": rules_run, "rules_skipped": rules_skipped}
