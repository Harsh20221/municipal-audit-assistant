# Municipal Audit Assistant

Phase 2 of a student project. It generates synthetic property-tax and project cases, runs deterministic layer 1–3 checks, and prints Tier B precision and recall per rule. It does not read PDFs or call a language model.

Rates in `families/property_tax/rules.yaml` and thresholds in `families/project/rules.yaml` are **ILLUSTRATIVE**. They are not an official schedule. The project “as of” date is fixed in that YAML so overdue checks do not depend on today’s date.

## What this phase does

- Discovers document families from `families/<name>/` and keeps only names listed in `config/settings.yaml`.
- Stores property-tax and project tables in SQLite.
- Generates about 300 properties and 150 projects. Cases are clean, near-threshold hard negatives, single-rule errors, multi-rule errors, or `needs_layer4` outliers that obey every rule.
- Scores each family on its own answer key. The two families are not averaged together. These numbers are Tier B only.

## Setup (from this folder)

```powershell
python -m venv .venv
.\.venv\Scripts\python -m pip install -e ".[dev]"
copy .env.example .env
.\.venv\Scripts\python -m pytest
.\.venv\Scripts\python -m evaluation.generate_data
.\.venv\Scripts\python -m engine.runner
.\.venv\Scripts\python -m evaluation.score
```

`evaluation.score` reruns the audit and writes `evaluation/results/tier_b_rules.md`. If `make` is installed and `python` is this environment, the targets are `setup`, `generate-data`, `test`, and `evaluate`.

## Layout

- `core/` — settings, SQLite, family registry
- `families/property_tax/` — illustrative tax rulebook and generator
- `families/project/` — tender, work order, invoice, progress report
- `families/_template/` — commented skeleton, not loaded
- `engine/` — runs layer 1–3 rules for every enabled family
- `evaluation/` — Tier B precision and recall
- `tests/` — one passing and one failing test per rule
