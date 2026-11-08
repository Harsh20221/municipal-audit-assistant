# Municipal Audit Assistant

Phase 5 of a student project. It generates synthetic property-tax and project cases, checks them with layers 1–3 and peer-group layer 4, extracts digital PDFs, and can explain a finding that was already computed. It does not run OCR, and it does not call a language model unless you pass `--live`.

Rates in `families/property_tax/rules.yaml` and thresholds in `families/project/rules.yaml` are **ILLUSTRATIVE**. They are not an official schedule. The project “as of” date is fixed in that YAML so overdue checks do not depend on today’s date.

## What this phase does

- Discovers document families from `families/<name>/` and keeps only names listed in `config/settings.yaml`.
- Stores property-tax and project tables in SQLite.
- Generates about 300 properties and 150 projects. Cases are clean, near-threshold hard negatives, single-rule errors, multi-rule errors, or `needs_layer4` outliers that obey every rule.
- Scores each family on its own answer key. The two families are not averaged together. These numbers are Tier B only.
- Layer 4 compares each case with its peer group (property tax: zone and category; project: department). Findings are layer 4, severity low or medium, and do not repeat a rule finding on the same case and field.
- Risk score per case is `100 * (1 - product(1 - weight))`, rounded to 4 decimals. Weights are low 0.10, medium 0.30, high 0.60. Bands are low below 30, medium from 30 through 60, and high above 60.
- Ablation thresholds were chosen on generator seed 42 and reported again on seed 43.

## Setup (from this folder)

```powershell
python -m venv .venv
.\.venv\Scripts\python -m pip install -e ".[dev]"
copy .env.example .env
.\.venv\Scripts\python -m pytest
.\.venv\Scripts\python -m evaluation.generate_data
.\.venv\Scripts\python -m engine.runner
.\.venv\Scripts\python -m evaluation.score
.\.venv\Scripts\python -m evaluation.ablation
.\.venv\Scripts\python -m ingestion.build_pdfs
.\.venv\Scripts\python -m ingestion.run --limit 5
```

`--limit` is a case count. The run keeps every PDF for each chosen case and spreads the cases across both families and every answer-key category, using seed 42. A live extraction, with `LLM_PROVIDER` and the matching key set in `.env`:

```powershell
.\.venv\Scripts\python -m ingestion.run --live --limit 30
```

`evaluation.score` reruns the audit and writes `evaluation/results/tier_b_rules.md` (layers 1–3 only). `evaluation.ablation` writes `evaluation/results/tier_b_ablation.md` for seeds 42 and 43.

Phase 5 commands:

```powershell
.\.venv\Scripts\python -m ingestion.build_samples
.\.venv\Scripts\python -m evaluation.extraction_report --limit 30
.\.venv\Scripts\python -m evaluation.extraction_report --live --limit 30
.\.venv\Scripts\python -m evaluation.explain_eval
.\.venv\Scripts\python -m evaluation.explain_eval --live
.\.venv\Scripts\python -m evaluation.tier_a
```

Tier B and Tier A are written to different files and are not averaged. Hand labels go in `data/gold/gold_labels.csv`. Register a public PDF with `python -m data_sources.register_document`. If `make` is installed and `python` is this environment, the targets are `setup`, `generate-data`, `test`, and `evaluate`.

## Layout

- `core/` — settings, SQLite, family registry
- `families/property_tax/` — illustrative tax rulebook and generator
- `families/project/` — tender, work order, invoice, progress report
- `families/_template/` — commented skeleton, not loaded
- `engine/` — layer 1–3 rules, layer 4 stats, and risk scores
- `evaluation/` — Tier B precision, recall, ablation, and extraction accuracy; Tier A is a separate report
- `ingestion/` — digital PDF text, classification, extraction, bundle checks, and sample PDFs
- `explain/` — short finding explanations with a number guardrail
- `data_sources/` — public-document register for Tier A
- `core/llm.py` — fake client by default; a live provider only when `--live` is passed
- `tests/` — one passing and one failing test per rule
