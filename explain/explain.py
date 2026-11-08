"""Explain a stored finding in two or three sentences.

The model may use only numbers that already appear in the finding. If it
introduces a number, the text is regenerated once and then replaced by a
template. Skipped checks are template text and do not call a model.
"""

from __future__ import annotations

import hashlib
import json
import re
from pathlib import Path

from core.config import ROOT

CACHE_DIR = ROOT / "data" / "cache" / "explanations"
_NUMBER = re.compile(r"\d+(?:\.\d+)?")
_BANNED = ("fraud", "corruption", "illegal", "corrupt")


def explain_finding(finding: dict, client, cache_dir: Path | None = None) -> dict:
    directory = cache_dir or CACHE_DIR
    digest = _hash(finding)
    path = directory / f"{digest}.json"
    if path.exists():
        stored = json.loads(path.read_text(encoding="utf-8"))
        stored["cached"] = True
        return stored
    allowed = _numbers(json.dumps(finding, sort_keys=True, default=str))
    prompt = _prompt(finding)
    text = client.complete_text(prompt).text.strip()
    passed = _grounded(text, allowed)
    if not passed:
        text = client.complete_text(
            prompt + "\nThe previous answer used a number that is not in the finding. Rewrite it."
        ).text.strip()
        passed = _grounded(text, allowed)
    source = "model" if passed else "template"
    if not passed:
        text = template_explanation(finding)
    result = {"text": text, "source": source, "guardrail_passed": passed, "cached": False}
    directory.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(result), encoding="utf-8")
    return result


def explain_skipped(rule_id: str, reason: str) -> str:
    return (
        f"{rule_id} was not run because a required document is missing ({reason}). "
        "This requires manual verification.\n"
        "What to check manually: add the missing document and run the check again."
    )


def template_explanation(finding: dict) -> str:
    rule_id = finding.get("rule_id", "This check")
    actual = finding.get("actual_value")
    expected = finding.get("expected_value")
    difference = finding.get("difference")
    sentences = [
        f"{rule_id} compared the recorded value {actual} with the expected value {expected}."
    ]
    if difference not in (None, ""):
        sentences.append(f"The recorded difference is {difference}.")
    sentences.append("This result requires manual verification.")
    field = ""
    evidence = finding.get("evidence") or []
    if evidence:
        field = str(evidence[0].get("field", ""))
    manual = f"What to check manually: review {field} against the source document."
    return " ".join(sentences) + "\n" + manual


def _prompt(finding: dict) -> str:
    payload = json.dumps(finding, sort_keys=True, default=str)
    return (
        "Explain this audit finding in two or three sentences, then one line that starts "
        "with 'What to check manually:'. Use only numbers that appear in the JSON. "
        "Do not accuse anyone. Include the words 'requires manual verification'.\n"
        f"{payload}"
    )


def _grounded(text: str, allowed: set[str]) -> bool:
    lowered = text.lower()
    if any(word in lowered for word in _BANNED):
        return False
    if "requires manual verification" not in lowered:
        return False
    if "what to check manually" not in lowered:
        return False
    return set(_numbers(text)) <= allowed


def _numbers(text: str) -> set[str]:
    return set(_NUMBER.findall(text))


def _hash(finding: dict) -> str:
    payload = json.dumps(finding, sort_keys=True, default=str)
    return hashlib.sha256(payload.encode()).hexdigest()
