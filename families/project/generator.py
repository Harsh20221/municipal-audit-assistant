"""Synthetic projects with one injected error or one hard negative.

A clean project has one tender, one work order, 3-8 invoices, and monthly
progress. Invoice totals stay under the work order and the budget, progress
percentages match, and names match. Hard negatives are unusual but still valid.
"""

from __future__ import annotations

import calendar
import csv
import hashlib
import json
import logging
import random
from collections import Counter
from dataclasses import dataclass
from datetime import date, timedelta
from pathlib import Path

from faker import Faker
from sqlalchemy import delete, select
from sqlalchemy.orm import Session

from core.config import ROOT, load_settings
from core.db import AuditLog, Document, Extraction, FindingRow, RiskScore, init_db, session_factory
from core.logging import setup_logging
from families.project.models import Invoice, ProgressReport, Project, Tender, WorkOrder

logger = logging.getLogger(__name__)

ERROR_TYPES = (
    ("percent_out_of_range", "PR-001"),
    ("end_before_start", "PR-002"),
    ("negative_amount", "PR-003"),
    ("invoice_total_over_work_order", "PR-004"),
    ("invoice_before_work_order", "PR-005"),
    ("duplicate_invoice", "PR-006"),
    ("progress_gap", "PR-007"),
    ("past_end_incomplete", "PR-008"),
    ("spend_over_budget", "PR-009"),
    ("award_gap", "PR-010"),
    ("vendor_mismatch", "PR-011"),
)
HARD_NEGATIVES = (
    "high_budget",
    "gap_within_threshold",
    "award_within_threshold",
    "completed_after_end",
    "vendor_spacing",
)
ANSWER_KEY_COLUMNS = ("case_key", "label", "error_type", "rule_id")
DEPARTMENTS = ("Public Works", "Water Supply", "Roads", "Health")


@dataclass
class GenerationResult:
    cases: int
    errors: int
    hard_negatives: int
    by_type: dict[str, int]
    answer_key: list[dict[str, str]]
    answer_key_path: Path | None


def default_answer_key_path() -> Path:
    return ROOT / "data" / "synthetic" / "project_answer_key.csv"


def clear_project(session: Session) -> None:
    session.execute(delete(FindingRow).where(FindingRow.family == "project"))
    session.execute(delete(RiskScore).where(RiskScore.family == "project"))
    session.execute(delete(AuditLog).where(AuditLog.action == "generate_project"))
    session.execute(delete(ProgressReport))
    session.execute(delete(Invoice))
    session.execute(delete(WorkOrder))
    session.execute(delete(Tender))
    doc_ids = select(Document.id).where(Document.family == "project")
    session.execute(delete(Extraction).where(Extraction.document_id.in_(doc_ids)))
    session.execute(delete(Document).where(Document.family == "project"))
    session.execute(delete(Project))
    session.flush()


class ProjectGenerator:
    def __init__(self, rule_file: dict):
        self.rule_file = rule_file
        self.params = rule_file["values"]

    def answer_key_file(self) -> Path:
        return default_answer_key_path()

    def generate(
        self,
        session: Session,
        *,
        n: int,
        seed: int,
        error_rate: float,
        hard_negative_rate: float,
        answer_key_path: Path | None = None,
        write_answer_key: bool = True,
        plan: str = "rate",
    ) -> GenerationResult:
        if n < 0:
            raise ValueError("n must be >= 0")
        if plan not in {"rate", "quota"}:
            raise ValueError("plan must be 'rate' or 'quota'")
        if error_rate < 0 or hard_negative_rate < 0:
            raise ValueError("rates must be >= 0")
        if plan == "rate" and error_rate + hard_negative_rate > 1:
            raise ValueError("error_rate + hard_negative_rate must be <= 1")

        clear_project(session)
        rng = random.Random(seed)
        fake = Faker("en_IN")
        fake.seed_instance(seed)
        if plan == "quota":
            assignments = _quota_assignments(n, rng)
        else:
            assignments = _assign_labels(n, error_rate, hard_negative_rate, rng)
        answer_key: list[dict[str, str]] = []
        by_type: dict[str, int] = {}
        for index, assignment in enumerate(assignments, start=1):
            row = _build_project(index, assignment, rng, fake, self.params)
            _insert_project(session, row)
            for item in _answer_rows(row, assignment):
                if item["error_type"]:
                    by_type[item["error_type"]] = by_type.get(item["error_type"], 0) + 1
                answer_key.append(item)
        session.add(
            AuditLog(
                action="generate_project",
                detail_json={"cases": n, "seed": seed, "by_type": by_type},
            )
        )
        session.flush()
        path = None
        if write_answer_key:
            path = answer_key_path or default_answer_key_path()
            _write_answer_key(path, answer_key)
        summary = _label_summary(answer_key)
        logger.info(
            "generated project cases=%s errors=%s hard_negatives=%s categories=%s",
            n,
            summary["errors"],
            summary["hard_negatives"],
            summary["counts"],
        )
        return GenerationResult(
            cases=n,
            errors=summary["errors"],
            hard_negatives=summary["hard_negatives"],
            by_type=by_type,
            answer_key=answer_key,
            answer_key_path=path,
        )


def _answer_rows(row: dict, assignment: dict) -> list[dict[str, str]]:
    base = {"case_key": row["project_id"], "label": assignment["label"]}
    errors = assignment.get("errors")
    if errors:
        return [{**base, "error_type": err["type"], "rule_id": err["rule_id"]} for err in errors]
    return [
        {
            **base,
            "error_type": assignment.get("error_type", ""),
            "rule_id": assignment.get("rule_id", ""),
        }
    ]


def _label_summary(rows: list[dict[str, str]]) -> dict:
    labels = {row["case_key"]: row["label"] for row in rows}
    counts = Counter(labels.values())
    errors = sum(counts[name] for name in ("error", "single_error", "multi_error"))
    return {
        "counts": dict(counts),
        "errors": errors,
        "hard_negatives": counts.get("hard_negative", 0),
    }


def _spec(label: str, error_type: str, rule_id: str = "", mutate: dict | None = None, errors=None):
    if errors is None:
        errors = [{"type": error_type, "rule_id": rule_id}] if rule_id else []
    return {
        "label": label,
        "error_type": error_type,
        "rule_id": rule_id,
        "errors": errors,
        "mutate": mutate or {},
    }


def _quota_assignments(n: int, rng: random.Random) -> list[dict]:
    specs: list[dict] = []
    for physical in (100.5, 101, 105, 110, 130, -0.5):
        financial = -0.5 if physical < 0 else None
        specs.append(
            _spec(
                "single_error",
                f"percent_{physical}",
                "PR-001",
                {"physical_pct": physical, "financial_pct": financial},
            )
        )
    for days in (1, 2, 7, 14, 30, 90):
        specs.append(
            _spec("single_error", f"end_before_{days}d", "PR-002", {"end_days_before_start": days})
        )
    for amount in (-0.5, -1, -1000, -100000, -1_000_000, -5_000_000):
        specs.append(
            _spec("single_error", f"negative_{amount}", "PR-003", {"negative_invoice": amount})
        )
    for excess in (1.5, 2, 10, 1000, 100000, 250000):
        specs.append(
            _spec("single_error", f"over_order_{excess}", "PR-004", {"work_order_excess": excess})
        )
        specs.append(
            _spec("single_error", f"over_budget_{excess}", "PR-009", {"budget_excess": excess})
        )
    for days in (1, 2, 7, 14, 30, 60):
        specs.append(
            _spec(
                "single_error", f"invoice_before_{days}d", "PR-005", {"invoice_days_before": days}
            )
        )
    for copies in (2, 2, 2, 2, 3, 3):
        specs.append(
            _spec("single_error", f"duplicate_x{copies}", "PR-006", {"duplicate_copies": copies})
        )
    for gap in (15.5, 16, 20, 25, 30, 40):
        specs.append(_spec("single_error", f"gap_{gap}", "PR-007", {"gap": gap}))
    for physical, days in ((99.5, 1), (99, 2), (90, 10), (70, 40), (50, 60), (10, 90)):
        specs.append(
            _spec(
                "single_error",
                f"overdue_{physical}",
                "PR-008",
                {
                    "physical_pct": physical,
                    "financial_pct": physical,
                    "end_days_before_as_of": days,
                },
            )
        )
    for ratio in (0.205, 0.21, 0.25, 0.40, 0.60, 1.0):
        specs.append(_spec("single_error", f"award_{ratio}", "PR-010", {"award_ratio": ratio}))
    for vendor in (
        "Unrelated Vendor ZZZ",
        "Other Civic Works",
        "North Bridge Traders",
        "Kappa Supplies",
        "Delta Earthmovers",
        "Prime Haulage",
    ):
        specs.append(_spec("single_error", "vendor_mismatch", "PR-011", {"vendor": vendor}))

    specs.extend(
        [
            _spec(
                "hard_negative", "percent_100", mutate={"physical_pct": 100, "financial_pct": 100}
            ),
            _spec(
                "hard_negative",
                "percent_99.5",
                mutate={"physical_pct": 99.5, "financial_pct": 99.5},
            ),
            _spec("hard_negative", "percent_0", mutate={"physical_pct": 0, "financial_pct": 0}),
            _spec("hard_negative", "order_excess_0.50", mutate={"work_order_excess": 0.50}),
            _spec("hard_negative", "order_excess_1.00", mutate={"work_order_excess": 1.00}),
            _spec("hard_negative", "budget_excess_0.50", mutate={"budget_excess": 0.50}),
            _spec("hard_negative", "budget_excess_1.00", mutate={"budget_excess": 1.00}),
            _spec("hard_negative", "gap_14.5", mutate={"gap": 14.5}),
            _spec("hard_negative", "gap_15", mutate={"gap": 15.0}),
            _spec(
                "hard_negative",
                "complete_before_as_of",
                mutate={"physical_pct": 100, "financial_pct": 100, "end_days_before_as_of": 30},
            ),
            _spec(
                "hard_negative",
                "end_on_as_of",
                mutate={"physical_pct": 99, "financial_pct": 99, "end_equals_as_of": True},
            ),
            _spec("hard_negative", "award_0.195", mutate={"award_ratio": 0.195}),
            _spec("hard_negative", "award_0.20", mutate={"award_ratio": 0.20}),
            _spec(
                "hard_negative",
                "end_equals_start",
                mutate={"end_equals_start": True, "physical_pct": 100, "financial_pct": 100},
            ),
            _spec(
                "hard_negative",
                "invoice_on_order_date",
                mutate={"invoice_on_work_order_date": True},
            ),
            _spec("hard_negative", "vendor_spacing", mutate={"vendor_spacing": True}),
        ]
    )
    for index in range(15):
        kind = index % 6
        if kind == 0:
            errors = [("percent_high", "PR-001"), ("wide_gap", "PR-007")]
            mutate = {"physical_pct": 70, "financial_pct": 110}
        elif kind == 1:
            errors = [("negative_invoice", "PR-003"), ("vendor_mismatch", "PR-011")]
            mutate = {
                "negative_invoice": -1000 if index < 6 else -100000,
                "vendor": "Unrelated Vendor ZZZ",
            }
        elif kind == 2:
            errors = [("over_order", "PR-004"), ("duplicate_invoice", "PR-006")]
            mutate = {"work_order_excess": 2 if index < 8 else 5000, "duplicate_copies": 2}
        elif kind == 3:
            errors = [("early_invoice", "PR-005"), ("overdue", "PR-008")]
            mutate = {
                "invoice_days_before": 1 if index < 8 else 14,
                "physical_pct": 80,
                "financial_pct": 80,
                "end_days_before_as_of": 10,
            }
        elif kind == 4:
            errors = [("over_budget", "PR-009"), ("award_gap", "PR-010")]
            mutate = {"budget_excess": 2 if index < 8 else 10000, "award_ratio": 0.30}
        else:
            errors = [("end_before_start", "PR-002"), ("duplicate_invoice", "PR-006")]
            mutate = {"end_days_before_start": 1 if index < 8 else 20, "duplicate_copies": 2}
        specs.append(
            _spec(
                "multi_error",
                "+".join(item[0] for item in errors),
                errors=[{"type": name, "rule_id": rule_id} for name, rule_id in errors],
                mutate=mutate,
            )
        )
    layer4 = [
        ("health_mega", {"department": "Health", "tender_estimate": 400_000_000}),
        ("roads_mega", {"department": "Roads", "tender_estimate": 350_000_000}),
        ("tiny_job", {"department": "Health", "tender_estimate": 80_000}),
        ("many_invoices_20", {"invoice_count": 20, "department": "Water Supply"}),
        ("many_invoices_30", {"invoice_count": 30, "department": "Public Works"}),
        ("long_schedule", {"long_schedule": True, "department": "Roads"}),
        ("one_dominant_invoice", {"dominant_invoice": True, "department": "Health"}),
        ("water_mega", {"department": "Water Supply", "tender_estimate": 500_000_000}),
        ("works_mega", {"department": "Public Works", "tender_estimate": 450_000_000}),
    ]
    for name, mutate in layer4:
        specs.append(_spec("needs_layer4", name, mutate=mutate))
    if len(specs) > n:
        raise ValueError(f"project quota needs at least {len(specs)} cases, got {n}")
    specs.extend(_spec("clean", "") for _ in range(n - len(specs)))
    rng.shuffle(specs)
    return specs


def _money_cap(total: float, excess: float, *, outside: bool) -> float:
    cap = round(total - excess, 2)
    actual = round(total - cap, 2)
    if outside and actual <= 1:
        return round(total - 1.01, 2)
    if not outside and actual > 1:
        return round(total - 1.00, 2)
    return cap


def _build_project_mutate(
    *, index: int, assignment: dict, rng: random.Random, fake: Faker, params: dict
):
    mutate = assignment["mutate"]
    as_of = date.fromisoformat(str(params["as_of_date"]))
    outside = assignment["label"] in {"single_error", "multi_error", "error"}
    tender_estimate = float(
        mutate.get("tender_estimate", rng.randrange(5_000_000, 50_000_000, 100_000))
    )
    ratio = float(mutate.get("award_ratio", 0))
    award = round(tender_estimate * (1 + ratio), 2)
    work_order_value = award
    budget = round(award * 1.15, 2)
    if mutate.get("long_schedule"):
        start = date(2023, 1, 1)
        end = date(2028, 6, 1)
    elif mutate.get("end_equals_as_of"):
        end = as_of
        start = _add_months(end, -8)
    elif "end_days_before_as_of" in mutate:
        end = as_of - timedelta(days=int(mutate["end_days_before_as_of"]))
        start = _add_months(end, -8)
    else:
        start = _add_months(as_of, -rng.randint(6, 12))
        end = _add_months(as_of, rng.randint(4, 10))
    if mutate.get("end_equals_start"):
        end = start
    if "end_days_before_start" in mutate:
        end = start - timedelta(days=int(mutate["end_days_before_start"]))
    report_until = end if end < as_of else as_of
    if report_until < start:
        report_until = start

    contractor = fake.company().replace("\n", " ")
    months = _month_starts(start, report_until)
    reports = []
    for position, month in enumerate(months, start=1):
        physical = round(30 + 25 * position / len(months), 2)
        reports.append(
            {
                "report_month": f"{month.year:04d}-{month.month:02d}",
                "physical_pct": physical,
                "financial_pct": physical,
            }
        )
    if (
        mutate.get("physical_pct") is not None
        or "gap" in mutate
        or mutate.get("financial_pct") is not None
    ):
        physical = (
            reports[-1]["physical_pct"]
            if mutate.get("physical_pct") is None
            else float(mutate["physical_pct"])
        )
        if "gap" in mutate:
            financial = round(physical + float(mutate["gap"]), 2)
        elif mutate.get("financial_pct") is None:
            financial = physical
        else:
            financial = float(mutate["financial_pct"])
        reports[-1]["physical_pct"] = physical
        reports[-1]["financial_pct"] = financial

    invoice_count = int(mutate.get("invoice_count", rng.randint(3, 8)))
    invoice_total = round(tender_estimate * 0.45, 2)
    amounts = _split_amount(invoice_total, invoice_count)
    if mutate.get("dominant_invoice") and invoice_count >= 3:
        amounts = _split_amount(round(invoice_total * 0.10, 2), invoice_count - 1)
        amounts.append(round(invoice_total - sum(amounts), 2))
    if "negative_invoice" in mutate:
        amounts[-1] = float(mutate["negative_invoice"])
    if "work_order_excess" in mutate:
        work_order_value = _money_cap(
            round(sum(amounts), 2), float(mutate["work_order_excess"]), outside=outside
        )
    if "budget_excess" in mutate:
        budget = _money_cap(round(sum(amounts), 2), float(mutate["budget_excess"]), outside=outside)

    work_order_date = start + timedelta(days=10)
    span_start = work_order_date + timedelta(days=5)
    span_end = report_until if report_until > span_start else span_start + timedelta(days=30)
    step = max(1, (span_end - span_start).days // invoice_count)
    invoice_dates = [span_start + timedelta(days=step * item) for item in range(invoice_count)]
    if mutate.get("invoice_on_work_order_date"):
        invoice_dates[0] = work_order_date
    if "invoice_days_before" in mutate:
        invoice_dates[0] = work_order_date - timedelta(days=int(mutate["invoice_days_before"]))
    numbers = [f"INV-{index:04d}-{item:02d}" for item in range(1, invoice_count + 1)]
    copies = int(mutate.get("duplicate_copies", 1))
    for copy in range(1, min(copies, invoice_count)):
        numbers[copy] = numbers[0]
    vendors = [contractor] * invoice_count
    if "vendor" in mutate:
        vendors[0] = mutate["vendor"]
    if mutate.get("vendor_spacing"):
        vendors[0] = "  " + "  ".join(contractor.split()) + "  "

    return {
        "project_id": f"PRJ{index:04d}",
        "name": f"{mutate.get('department', rng.choice(DEPARTMENTS))} works {index}",
        "city": fake.city().replace("\n", " "),
        "department": mutate.get("department", rng.choice(DEPARTMENTS)),
        "budget": budget,
        "start_date": start,
        "expected_end_date": end,
        "contractor": contractor,
        "tender_estimate": tender_estimate,
        "award_value": award,
        "work_order_value": work_order_value,
        "work_order_date": work_order_date,
        "invoices": [
            {
                "invoice_no": numbers[item],
                "vendor": vendors[item],
                "amount": amounts[item],
                "invoice_date": invoice_dates[item],
            }
            for item in range(invoice_count)
        ],
        "reports": reports,
        "label": assignment["label"],
        "error_type": assignment.get("error_type", ""),
        "rule_id": assignment.get("rule_id", ""),
    }


def _assign_labels(n: int, error_rate: float, hard_negative_rate: float, rng: random.Random):
    indexes = list(range(n))
    rng.shuffle(indexes)
    n_errors = int(round(n * error_rate))
    n_hard = int(round(n * hard_negative_rate))
    labels: list[dict] = [{"label": "clean", "error_type": "", "rule_id": ""} for _ in range(n)]
    for slot, index in enumerate(indexes[:n_errors]):
        error_type, rule_id = ERROR_TYPES[slot % len(ERROR_TYPES)]
        labels[index] = {"label": "error", "error_type": error_type, "rule_id": rule_id}
    for slot, index in enumerate(indexes[n_errors : n_errors + n_hard]):
        labels[index] = {
            "label": "hard_negative",
            "error_type": HARD_NEGATIVES[slot % len(HARD_NEGATIVES)],
            "rule_id": "",
        }
    return labels


def _build_project(index: int, assignment: dict, rng: random.Random, fake: Faker, params: dict):
    if "mutate" in assignment:
        return _build_project_mutate(
            index=index, assignment=assignment, rng=rng, fake=fake, params=params
        )
    error_type = assignment["error_type"]
    as_of = date.fromisoformat(str(params["as_of_date"]))
    if error_type == "high_budget":
        tender_estimate = 80_000_000.0
    else:
        tender_estimate = float(rng.randrange(5_000_000, 50_000_000, 100_000))
    award = tender_estimate
    work_order_value = tender_estimate
    budget = round(tender_estimate * 1.15, 2)
    if error_type == "award_within_threshold":
        award = round(tender_estimate * 1.10, 2)
        work_order_value = award
        budget = round(award * 1.15, 2)
    if error_type == "award_gap":
        award = round(tender_estimate * 1.60, 2)
        work_order_value = award
        budget = round(award * 1.15, 2)

    start = _add_months(as_of, -rng.randint(6, 12))
    end = _add_months(as_of, rng.randint(4, 10))
    report_until = as_of
    if error_type in {"past_end_incomplete", "completed_after_end"}:
        end = as_of - timedelta(days=40)
        start = _add_months(end, -8)
        report_until = end
    if error_type == "end_before_start":
        end = start - timedelta(days=20)
        report_until = as_of

    contractor = fake.company().replace("\n", " ")
    months = _month_starts(start, report_until if report_until >= start else start)
    reports = []
    count_months = len(months)
    for position, month in enumerate(months, start=1):
        physical = round(30 + 25 * position / count_months, 2)
        reports.append(
            {
                "report_month": f"{month.year:04d}-{month.month:02d}",
                "physical_pct": physical,
                "financial_pct": physical,
            }
        )
    if error_type == "percent_out_of_range":
        reports[-1]["physical_pct"] = 130.0
        reports[-1]["financial_pct"] = 100.0
    elif error_type == "progress_gap":
        reports[-1]["financial_pct"] = round(reports[-1]["physical_pct"] + 30, 2)
    elif error_type == "gap_within_threshold":
        reports[-1]["financial_pct"] = round(reports[-1]["physical_pct"] + 10, 2)
    elif error_type == "past_end_incomplete":
        reports[-1]["physical_pct"] = 70.0
        reports[-1]["financial_pct"] = 78.0
    elif error_type == "completed_after_end":
        reports[-1]["physical_pct"] = 100.0
        reports[-1]["financial_pct"] = 100.0

    invoice_count = rng.randint(3, 8)
    invoice_total = round(tender_estimate * 0.45, 2)
    amounts = _split_amount(invoice_total, invoice_count)
    work_order_date = start + timedelta(days=10)
    span_start = work_order_date + timedelta(days=5)
    span_end = report_until if report_until > span_start else span_start + timedelta(days=30)
    step = max(1, (span_end - span_start).days // invoice_count)
    invoice_dates = [span_start + timedelta(days=step * item) for item in range(invoice_count)]
    numbers = [f"INV-{index:04d}-{item:02d}" for item in range(1, invoice_count + 1)]
    vendors = [contractor] * invoice_count

    if error_type == "negative_amount":
        amounts[-1] = -10000.0
    elif error_type == "invoice_total_over_work_order":
        work_order_value = round(invoice_total * 0.7, 2)
    elif error_type == "invoice_before_work_order":
        invoice_dates[0] = work_order_date - timedelta(days=12)
    elif error_type == "duplicate_invoice":
        numbers[1] = numbers[0]
    elif error_type == "spend_over_budget":
        budget = round(invoice_total * 0.8, 2)
    elif error_type == "vendor_mismatch":
        vendors[0] = "Unrelated Vendor ZZZ"
    elif error_type == "vendor_spacing":
        vendors[0] = "  " + "  ".join(contractor.split()) + "  "

    return {
        "project_id": f"PRJ{index:04d}",
        "name": f"{rng.choice(DEPARTMENTS)} works {index}",
        "city": fake.city().replace("\n", " "),
        "department": rng.choice(DEPARTMENTS),
        "budget": budget,
        "start_date": start,
        "expected_end_date": end,
        "contractor": contractor,
        "tender_estimate": tender_estimate,
        "award_value": award,
        "work_order_value": work_order_value,
        "work_order_date": work_order_date,
        "invoices": [
            {
                "invoice_no": numbers[item],
                "vendor": vendors[item],
                "amount": amounts[item],
                "invoice_date": invoice_dates[item],
            }
            for item in range(invoice_count)
        ],
        "reports": reports,
        "label": assignment["label"],
        "error_type": error_type,
        "rule_id": assignment["rule_id"],
    }


def _insert_project(session: Session, row: dict) -> None:
    session.add(
        Project(
            project_id=row["project_id"],
            name=row["name"],
            city=row["city"],
            department=row["department"],
            budget=row["budget"],
            start_date=row["start_date"],
            expected_end_date=row["expected_end_date"],
            contractor=row["contractor"],
        )
    )
    tender_doc = _document(row["project_id"], "tender_award_notice", "tender")
    order_doc = _document(row["project_id"], "work_order", "work-order")
    session.add_all([tender_doc, order_doc])
    session.flush()
    session.add(
        Tender(
            project_id=row["project_id"],
            tender_estimate=row["tender_estimate"],
            award_value=row["award_value"],
            contractor=row["contractor"],
            document_id=tender_doc.id,
        )
    )
    session.add(
        WorkOrder(
            project_id=row["project_id"],
            work_order_value=row["work_order_value"],
            work_order_date=row["work_order_date"],
            contractor=row["contractor"],
            document_id=order_doc.id,
        )
    )
    for position, invoice in enumerate(row["invoices"], start=1):
        document = _document(row["project_id"], "invoice", f"{position}-{invoice['invoice_no']}")
        session.add(document)
        session.flush()
        session.add(
            Invoice(
                project_id=row["project_id"],
                invoice_no=invoice["invoice_no"],
                vendor=invoice["vendor"],
                amount=invoice["amount"],
                invoice_date=invoice["invoice_date"],
                document_id=document.id,
            )
        )
    for report in row["reports"]:
        document = _document(row["project_id"], "progress_report", report["report_month"])
        session.add(document)
        session.flush()
        session.add(
            ProgressReport(
                project_id=row["project_id"],
                report_month=report["report_month"],
                physical_pct=report["physical_pct"],
                financial_pct=report["financial_pct"],
                document_id=document.id,
            )
        )


def _document(project_id: str, doc_type: str, key: str) -> Document:
    payload = {"project_id": project_id, "doc_type": doc_type, "key": key}
    digest = hashlib.sha256(json.dumps(payload, sort_keys=True).encode("utf-8")).hexdigest()
    return Document(
        sha256=digest,
        filename=f"{project_id}_{doc_type}_{key}.txt",
        family="project",
        doc_type=doc_type,
        source="synthetic_structured",
        status="stored",
        page_count=1,
    )


def _split_amount(total: float, count: int) -> list[float]:
    amounts = []
    remaining = round(total, 2)
    part = round(total / count, 2)
    for _ in range(count - 1):
        amounts.append(part)
        remaining = round(remaining - part, 2)
    amounts.append(remaining)
    return amounts


def _add_months(day: date, months: int) -> date:
    month_index = day.month - 1 + months
    year = day.year + month_index // 12
    month = month_index % 12 + 1
    last_day = calendar.monthrange(year, month)[1]
    return date(year, month, min(day.day, last_day))


def _month_starts(first: date, last: date) -> list[date]:
    year, month = first.year, first.month
    found = []
    while (year, month) <= (last.year, last.month):
        found.append(date(year, month, 1))
        month += 1
        if month == 13:
            year += 1
            month = 1
    return found


def _write_answer_key(path: Path, rows: list[dict[str, str]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    ordered = sorted(rows, key=lambda item: (item["case_key"], item.get("rule_id", "")))
    with path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=ANSWER_KEY_COLUMNS)
        writer.writeheader()
        writer.writerows(ordered)


def main() -> None:
    from families.project.family import ProjectFamily

    settings = load_settings()
    setup_logging(settings.logging_level)
    init_db()
    family = ProjectFamily()
    with session_factory()() as session:
        result = family.generator().generate(
            session,
            n=settings.generator.counts["project"],
            seed=settings.generator.seed,
            error_rate=settings.generator.error_rate,
            hard_negative_rate=settings.generator.hard_negative_rate,
            plan="quota",
        )
        session.commit()
    print(
        f"cases={result.cases} errors={result.errors} "
        f"hard_negatives={result.hard_negatives} answer_key={result.answer_key_path}"
    )
    for name, count in sorted(result.by_type.items()):
        print(f"  {name}: {count}")


if __name__ == "__main__":
    main()
