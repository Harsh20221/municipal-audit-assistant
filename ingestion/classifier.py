"""Keyword classification, with an LLM fallback when no keyword matches."""

from __future__ import annotations

from families.base import DocumentTypeSpec


def classify(text: str, specs: list[DocumentTypeSpec], client=None) -> str | None:
    lowered = text.lower()
    scored = []
    for spec in specs:
        score = sum(len(keyword) for keyword in spec.keywords if keyword.lower() in lowered)
        if score:
            scored.append((score, spec.name))
    if scored:
        scored.sort(reverse=True)
        return scored[0][1]
    if client is None:
        return None
    names = ", ".join(spec.name for spec in specs)
    prompt = "Choose the document type. Reply with only the type name.\n" f"Types: {names}\n{text}"
    answer = client.complete_text(prompt).text.strip().split()[0]
    known = {spec.name for spec in specs}
    return answer if answer in known else None
