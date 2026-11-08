"""Synthetic property-tax cases with named errors and hard negatives.

Clean records are calculated from rules.yaml. About 18 percent then receive one
injected error mapped to a rule id. Hard negatives are unusual but still valid,
so layer 1-3 rules should not flag them. Fixed seeds keep the corpus stable.
"""

from __future__ import annotations

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
from families.property_tax.formula import expected_amounts, tolerance_limit
from families.property_tax.models import Property, TaxAssessment, TaxBill, TaxReceipt

logger = logging.getLogger(__name__)

ERROR_TYPES = (
    ("negative_penalty", "PT-001"),
    ("missing_owner", "PT-002"),
    ("due_before_issue", "PT-003"),
    ("bill_amount_wrong", "PT-004"),
    ("assessed_tax_wrong", "PT-005"),
    ("receipt_amount_mismatch", "PT-006"),
    ("owner_mismatch", "PT-007"),
    ("late_payment_no_penalty", "PT-008"),
    ("exemption_without_assessment", "PT-009"),
)
HARD_NEGATIVES = (
    "large_area",
    "old_building",
    "exemption_with_support",
    "late_payment_with_penalty",
    "within_tolerance",
)
ANSWER_KEY_COLUMNS = (
    "case_key",
    "property_id",
    "fiscal_year",
    "label",
    "error_type",
    "rule_id",
)


@dataclass
class GenerationResult:
    cases: int
    errors: int
    hard_negatives: int
    by_type: dict[str, int]
    answer_key: list[dict[str, str]]
    answer_key_path: Path | None


def default_answer_key_path() -> Path:
    return ROOT / "data" / "synthetic" / "property_tax_answer_key.csv"


def clear_property_tax(session: Session) -> None:
    session.execute(delete(FindingRow).where(FindingRow.family == "property_tax"))
    session.execute(delete(RiskScore).where(RiskScore.family == "property_tax"))
    session.execute(delete(AuditLog).where(AuditLog.action == "generate_property_tax"))
    session.execute(delete(TaxReceipt))
    session.execute(delete(TaxBill))
    session.execute(delete(TaxAssessment))
    doc_ids = select(Document.id).where(Document.family == "property_tax")
    session.execute(delete(Extraction).where(Extraction.document_id.in_(doc_ids)))
    session.execute(delete(Document).where(Document.family == "property_tax"))
    session.execute(delete(Property))
    session.flush()


class PropertyTaxGenerator:
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

        clear_property_tax(session)
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
            row = _build_case(
                index=index,
                assignment=assignment,
                rng=rng,
                fake=fake,
                params=self.params,
            )
            _insert_case(session, row)
            for item in _answer_rows(row, assignment):
                if item["error_type"]:
                    by_type[item["error_type"]] = by_type.get(item["error_type"], 0) + 1
                answer_key.append(item)

        session.add(
            AuditLog(
                action="generate_property_tax",
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
            "generated property_tax cases=%s errors=%s hard_negatives=%s categories=%s",
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
    base = {
        "case_key": row["case_key"],
        "property_id": row["property_id"],
        "fiscal_year": row["fiscal_year"],
        "label": assignment["label"],
    }
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
    for factor in (1.25, 1.25, 2.5, 5, 12.5, 25):
        specs.append(
            _spec("single_error", f"bill_over_{factor}", "PT-004", {"bill_over_limit": factor})
        )
        specs.append(
            _spec(
                "single_error", f"assessed_over_{factor}", "PT-005", {"assessed_over_limit": factor}
            )
        )
        specs.append(
            _spec(
                "single_error", f"receipt_over_{factor}", "PT-006", {"receipt_over_limit": factor}
            )
        )
    for penalty in (-0.5, -1, -100, -1000, -10000, -250000):
        specs.append(_spec("single_error", f"penalty_{penalty}", "PT-001", {"penalty": penalty}))
    blanks = (
        {"blank_owner_on": "bill"},
        {"blank_owner_on": "receipt"},
        {"blank_owner_on": "assessment"},
        {"blank_property_on": "bill"},
        {"blank_property_on": "receipt"},
        {"blank_property_on": "assessment"},
    )
    for mutate in blanks:
        specs.append(_spec("single_error", "missing_identity", "PT-002", mutate))
    for days in (1, 2, 7, 30, 90, 180):
        specs.append(
            _spec("single_error", f"due_before_{days}d", "PT-003", {"due_days_before_issue": days})
        )
    mismatches = (
        {"owner_mismatch_on": "receipt"},
        {"owner_mismatch_on": "bill"},
        {"owner_mismatch_on": "assessment"},
        {"property_mismatch_on": "receipt"},
        {"property_mismatch_on": "bill"},
        {"property_mismatch_on": "assessment"},
    )
    for mutate in mismatches:
        specs.append(_spec("single_error", "identity_mismatch", "PT-007", mutate))
    for days in (1, 2, 5, 15, 40, 90):
        specs.append(
            _spec(
                "single_error",
                f"late_{days}d",
                "PT-008",
                {"paid_days_after_due": days},
            )
        )
    for amount in (100, 250, 500, 1000, 2000, 4000):
        specs.append(
            _spec(
                "single_error",
                f"exemption_{amount}",
                "PT-009",
                {"drop_assessment": True, "exemption": amount},
            )
        )
    for factor in (0.75, 0.75, 1.0, 1.0):
        specs.append(
            _spec("hard_negative", f"bill_inside_{factor}", mutate={"bill_over_limit": factor})
        )
        specs.append(
            _spec(
                "hard_negative", f"assessed_inside_{factor}", mutate={"assessed_over_limit": factor}
            )
        )
        specs.append(
            _spec(
                "hard_negative", f"receipt_inside_{factor}", mutate={"receipt_over_limit": factor}
            )
        )
    specs.extend(
        [
            _spec("hard_negative", "due_equals_issue", mutate={"due_equals_issue": True}),
            _spec("hard_negative", "due_equals_issue", mutate={"due_equals_issue": True}),
            _spec("hard_negative", "paid_on_due", mutate={"paid_on_due": True}),
            _spec("hard_negative", "paid_on_due", mutate={"paid_on_due": True}),
            _spec("hard_negative", "exemption_with_support", mutate={"exemption": 2000}),
            _spec("hard_negative", "exemption_with_support", mutate={"exemption": 1000}),
            _spec(
                "hard_negative",
                "late_with_penalty",
                mutate={"paid_days_after_due": 10, "use_late_penalty": True},
            ),
            _spec(
                "hard_negative",
                "late_with_penalty",
                mutate={"paid_days_after_due": 25, "use_late_penalty": True},
            ),
        ]
    )
    pair_factors = (1.25, 5, 12.5)
    pair_days = (1, 7, 30)
    pair_penalties = (-0.5, -100, -10000)
    for index in range(30):
        kind = index % 10
        factor = pair_factors[index % 3]
        days = pair_days[index % 3]
        penalty = pair_penalties[index % 3]
        if kind == 0:
            errors = [("negative_penalty", "PT-001"), ("due_before_issue", "PT-003")]
            mutate = {"penalty": penalty, "due_days_before_issue": days}
        elif kind == 1:
            errors = [("missing_owner", "PT-002"), ("receipt_mismatch", "PT-006")]
            mutate = {"blank_owner_on": "bill", "receipt_over_limit": factor}
        elif kind == 2:
            errors = [("bill_mismatch", "PT-004"), ("late_unpenalized", "PT-008")]
            mutate = {"bill_over_limit": factor, "paid_days_after_due": days}
        elif kind == 3:
            errors = [("assessed_mismatch", "PT-005"), ("owner_mismatch", "PT-007")]
            mutate = {"assessed_over_limit": factor, "owner_mismatch_on": "receipt"}
        elif kind == 4:
            errors = [("negative_penalty", "PT-001"), ("owner_mismatch", "PT-007")]
            mutate = {"penalty": penalty, "owner_mismatch_on": "bill"}
        elif kind == 5:
            errors = [("receipt_mismatch", "PT-006"), ("late_unpenalized", "PT-008")]
            mutate = {"receipt_over_limit": factor, "paid_days_after_due": days}
        elif kind == 6:
            errors = [("missing_property", "PT-002"), ("due_before_issue", "PT-003")]
            mutate = {"blank_property_on": "receipt", "due_days_before_issue": days}
        elif kind == 7:
            errors = [("bill_mismatch", "PT-004"), ("assessed_mismatch", "PT-005")]
            mutate = {"bill_over_limit": factor, "assessed_over_limit": factor}
        elif kind == 8:
            errors = [("unsupported_exemption", "PT-009"), ("late_unpenalized", "PT-008")]
            mutate = {"drop_assessment": True, "exemption": 1000, "paid_days_after_due": days}
        else:
            errors = [("owner_mismatch", "PT-007"), ("receipt_mismatch", "PT-006")]
            mutate = {"owner_mismatch_on": "assessment", "receipt_over_limit": factor}
        specs.append(
            _spec(
                "multi_error",
                "+".join(item[0] for item in errors),
                errors=[{"type": name, "rule_id": rule_id} for name, rule_id in errors],
                mutate=mutate,
            )
        )
    layer4 = [
        ("huge_area", {"area": 100000, "zone": "A", "category": "residential"}),
        ("huge_commercial", {"area": 80000, "zone": "A", "category": "commercial"}),
        ("tiny_area", {"area": 40, "zone": "C", "category": "residential"}),
        ("extreme_age", {"construction_year": 1890, "area": 1800}),
        ("old_large", {"construction_year": 1905, "area": 60000, "zone": "B"}),
        ("new_huge", {"age_years": 0, "area": 90000, "zone": "A", "category": "commercial"}),
        ("high_supported_exemption", {"exemption_share": 0.4, "area": 3500}),
        ("large_late_penalty", {"penalty_share": 0.8, "paid_days_after_due": 20, "area": 4200}),
        ("huge_zone_c", {"area": 120000, "zone": "C", "category": "residential"}),
    ]
    for name, mutate in layer4:
        specs.append(_spec("needs_layer4", name, mutate=mutate))
    if len(specs) > n:
        raise ValueError(f"property quota needs at least {len(specs)} cases, got {n}")
    specs.extend(_spec("clean", "") for _ in range(n - len(specs)))
    rng.shuffle(specs)
    return specs


def _nudge(base: float, factor: float, params: dict, *, outside: bool) -> float:
    limit = tolerance_limit(base, params)
    raw = round(base + limit * factor, 2)
    gap = abs(raw - base)
    if outside and gap <= limit:
        return round(base + limit + 0.01, 2)
    if not outside and gap > limit:
        return round(base + limit - 0.01, 2)
    return raw


def _build_case_mutate(
    *, index: int, assignment: dict, rng: random.Random, fake: Faker, params: dict
):
    fiscal_year = str(params["fiscal_year"])
    fiscal_start = int(params["fiscal_start_year"])
    mutate = assignment["mutate"]
    zone = mutate.get("zone", rng.choice(["A", "B", "C"]))
    category = mutate.get("category", rng.choice(["residential", "commercial"]))
    if "area" in mutate:
        area = float(mutate["area"])
    elif category == "residential":
        area = float(rng.randint(500, 2500))
    else:
        area = float(rng.randint(800, 6000))
    if "construction_year" in mutate:
        construction_year = int(mutate["construction_year"])
    elif "age_years" in mutate:
        construction_year = fiscal_start - int(mutate["age_years"])
    else:
        construction_year = rng.randint(1990, fiscal_start - 1)

    owner = fake.name()
    property_id = f"PID{index:05d}"
    issue = date(fiscal_start, 4, 1) + timedelta(days=rng.randint(0, 200))
    if mutate.get("due_equals_issue"):
        due = issue
    elif "due_days_before_issue" in mutate:
        due = issue - timedelta(days=int(mutate["due_days_before_issue"]))
    else:
        due = issue + timedelta(days=30)
    if mutate.get("paid_on_due"):
        paid = due
    elif "paid_days_after_due" in mutate:
        paid = due + timedelta(days=int(mutate["paid_days_after_due"]))
    else:
        paid = issue + timedelta(days=min(10, max(1, (due - issue).days // 2)))
        if paid > due:
            paid = due

    exemption = float(mutate.get("exemption", 0))
    penalty = float(mutate.get("penalty", 0))
    if mutate.get("use_late_penalty"):
        penalty = float(params["late_penalty"])
    include_assessment = not mutate.get("drop_assessment", False)
    bill_owner = owner
    receipt_owner = owner
    assessment_owner = owner
    bill_property_id = property_id
    receipt_property_id = property_id
    assessment_property_id = property_id
    if mutate.get("blank_owner_on") == "bill":
        bill_owner = ""
    elif mutate.get("blank_owner_on") == "receipt":
        receipt_owner = ""
    elif mutate.get("blank_owner_on") == "assessment":
        assessment_owner = ""
    if mutate.get("blank_property_on") == "bill":
        bill_property_id = ""
    elif mutate.get("blank_property_on") == "receipt":
        receipt_property_id = ""
    elif mutate.get("blank_property_on") == "assessment":
        assessment_property_id = ""
    if mutate.get("owner_mismatch_on") == "bill":
        bill_owner = f"{owner} Jr"
    elif mutate.get("owner_mismatch_on") == "receipt":
        receipt_owner = f"{owner} Jr"
    elif mutate.get("owner_mismatch_on") == "assessment":
        assessment_owner = f"{owner} Jr"
    if mutate.get("property_mismatch_on") == "bill":
        bill_property_id = f"{property_id}X"
    elif mutate.get("property_mismatch_on") == "receipt":
        receipt_property_id = f"{property_id}X"
    elif mutate.get("property_mismatch_on") == "assessment":
        assessment_property_id = f"{property_id}X"

    def compute(current_exemption: float, current_penalty: float) -> dict:
        return expected_amounts(
            built_up_area_sqft=area,
            zone=zone,
            category=category,
            construction_year=construction_year,
            exemption_amount=current_exemption,
            penalty=current_penalty,
            params=params,
        )

    amounts = compute(exemption, penalty)
    if "exemption_share" in mutate:
        exemption = round(amounts["assessed_tax"] * float(mutate["exemption_share"]), 2)
        amounts = compute(exemption, penalty)
    if "penalty_share" in mutate:
        penalty = round(amounts["assessed_tax"] * float(mutate["penalty_share"]), 2)
        amounts = compute(exemption, penalty)
    if exemption >= amounts["assessed_tax"] * 0.5 and "exemption_share" not in mutate:
        exemption = round(amounts["assessed_tax"] * 0.1, 2)
        if exemption <= 0 and mutate.get("drop_assessment"):
            exemption = 100.0
        amounts = compute(exemption, penalty)

    assessed = amounts["assessed_tax"]
    amount_due = amounts["amount_due"]
    outside = assignment["label"] in {"single_error", "multi_error", "error"}
    if "bill_over_limit" in mutate:
        amount_due = _nudge(
            amounts["amount_due"], float(mutate["bill_over_limit"]), params, outside=outside
        )
    if "bill_rupee_nudge" in mutate:
        amount_due = round(amounts["amount_due"] + float(mutate["bill_rupee_nudge"]), 2)
    amount_paid = amount_due
    if "receipt_over_limit" in mutate:
        amount_paid = _nudge(
            amount_due, float(mutate["receipt_over_limit"]), params, outside=outside
        )
    assessment_assessed = assessed
    if "assessed_over_limit" in mutate:
        assessment_assessed = _nudge(
            assessed, float(mutate["assessed_over_limit"]), params, outside=outside
        )

    return {
        "case_key": property_id,
        "property_id": property_id,
        "owner_name": owner,
        "address": fake.address().replace("\n", ", "),
        "ward": f"Ward {rng.randint(1, 15)}",
        "zone": zone,
        "category": category,
        "built_up_area_sqft": area,
        "construction_year": construction_year,
        "fiscal_year": fiscal_year,
        "assessed_tax": assessed,
        "assessment_assessed": assessment_assessed,
        "exemption_amount": amounts["exemption_amount"],
        "penalty": amounts["penalty"],
        "amount_due": amount_due,
        "amount_paid": amount_paid,
        "issue_date": issue,
        "due_date": due,
        "paid_date": paid,
        "receipt_id": f"RCPT{index:05d}",
        "include_assessment": include_assessment,
        "bill_owner": bill_owner,
        "receipt_owner": receipt_owner,
        "assessment_owner": assessment_owner,
        "bill_property_id": bill_property_id,
        "receipt_property_id": receipt_property_id,
        "assessment_property_id": assessment_property_id,
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


def _build_case(*, index: int, assignment: dict, rng: random.Random, fake: Faker, params: dict):
    if "mutate" in assignment:
        return _build_case_mutate(
            index=index, assignment=assignment, rng=rng, fake=fake, params=params
        )
    fiscal_year = str(params["fiscal_year"])
    fiscal_start = int(params["fiscal_start_year"])
    error_type = assignment["error_type"]
    zone = rng.choice(["A", "B", "C"])
    category = rng.choice(["residential", "commercial"])
    if error_type == "large_area":
        area = 25000.0
    elif category == "residential":
        area = float(rng.randint(500, 2500))
    else:
        area = float(rng.randint(800, 6000))
    if error_type == "old_building":
        construction_year = fiscal_start - 55
    else:
        construction_year = rng.randint(1990, fiscal_start - 1)

    owner = fake.name()
    property_id = f"PID{index:05d}"
    case_key = property_id
    issue = date(fiscal_start, 4, 1) + timedelta(days=rng.randint(0, 300))
    due = issue + timedelta(days=30)
    paid = issue + timedelta(days=rng.randint(1, 20))
    exemption = 0.0
    penalty = 0.0
    include_assessment = True
    bill_owner = owner
    receipt_owner = owner
    assessment_owner = owner
    bill_property_id = property_id
    receipt_property_id = property_id
    assessment_property_id = property_id

    if error_type == "exemption_with_support" or (
        assignment["label"] == "clean" and rng.random() < 0.10
    ):
        exemption = float(rng.choice([500, 1000, 2000]))
    if error_type == "late_payment_with_penalty":
        paid = due + timedelta(days=rng.randint(5, 40))
        penalty = float(params["late_penalty"])
    if error_type == "negative_penalty":
        penalty = -100.0
    if error_type == "due_before_issue":
        due = issue - timedelta(days=7)
    if error_type == "late_payment_no_penalty":
        paid = due + timedelta(days=12)
        penalty = 0.0
    if error_type == "exemption_without_assessment":
        exemption = 1500.0
        include_assessment = False
    if error_type == "missing_owner":
        bill_owner = ""
    if error_type == "owner_mismatch":
        receipt_owner = f"{owner} Jr"

    amounts = expected_amounts(
        built_up_area_sqft=area,
        zone=zone,
        category=category,
        construction_year=construction_year,
        exemption_amount=exemption,
        penalty=penalty,
        params=params,
    )
    if exemption >= amounts["assessed_tax"] * 0.5:
        exemption = round(amounts["assessed_tax"] * 0.1, 2)
        amounts = expected_amounts(
            built_up_area_sqft=area,
            zone=zone,
            category=category,
            construction_year=construction_year,
            exemption_amount=exemption,
            penalty=penalty,
            params=params,
        )

    assessed = amounts["assessed_tax"]
    amount_due = amounts["amount_due"]
    amount_paid = amount_due
    assessment_assessed = assessed
    if error_type == "assessed_tax_wrong":
        assessment_assessed = round(assessed * 1.35, 2)
    if error_type == "bill_amount_wrong":
        amount_due = round(amounts["amount_due"] * 1.3 + 250, 2)
        amount_paid = amount_due
    if error_type == "receipt_amount_mismatch":
        amount_paid = round(amounts["amount_due"] * 0.4, 2)
    if error_type == "within_tolerance":
        amount_due = round(amounts["amount_due"] + 0.5, 2)
        amount_paid = amount_due

    address = fake.address().replace("\n", ", ")
    return {
        "case_key": case_key,
        "property_id": property_id,
        "owner_name": owner,
        "address": address,
        "ward": f"Ward {rng.randint(1, 15)}",
        "zone": zone,
        "category": category,
        "built_up_area_sqft": area,
        "construction_year": construction_year,
        "fiscal_year": fiscal_year,
        "assessed_tax": assessed,
        "assessment_assessed": assessment_assessed,
        "exemption_amount": amounts["exemption_amount"],
        "penalty": amounts["penalty"],
        "amount_due": amount_due,
        "amount_paid": amount_paid,
        "issue_date": issue,
        "due_date": due,
        "paid_date": paid,
        "receipt_id": f"RCPT{index:05d}",
        "include_assessment": include_assessment,
        "bill_owner": bill_owner,
        "receipt_owner": receipt_owner,
        "assessment_owner": assessment_owner,
        "bill_property_id": bill_property_id,
        "receipt_property_id": receipt_property_id,
        "assessment_property_id": assessment_property_id,
        "label": assignment["label"],
        "error_type": error_type,
        "rule_id": assignment["rule_id"],
    }


def _insert_case(session: Session, row: dict) -> None:
    session.add(
        Property(
            case_key=row["case_key"],
            property_id=row["property_id"],
            owner_name=row["owner_name"],
            address=row["address"],
            ward=row["ward"],
            zone=row["zone"],
            category=row["category"],
            built_up_area_sqft=row["built_up_area_sqft"],
            construction_year=row["construction_year"],
            fiscal_year=row["fiscal_year"],
        )
    )
    documents = {}
    doc_types = ["tax_bill", "payment_receipt"]
    if row["include_assessment"]:
        doc_types.insert(0, "assessment_form")
    for doc_type in doc_types:
        documents[doc_type] = _document(row, doc_type)
    session.add_all(documents.values())
    session.flush()

    if row["include_assessment"]:
        session.add(
            TaxAssessment(
                case_key=row["case_key"],
                fiscal_year=row["fiscal_year"],
                property_id=row["assessment_property_id"],
                owner_name=row["assessment_owner"],
                assessed_tax=row["assessment_assessed"],
                exemption_amount=row["exemption_amount"],
                document_id=documents["assessment_form"].id,
            )
        )
    session.add(
        TaxBill(
            case_key=row["case_key"],
            fiscal_year=row["fiscal_year"],
            property_id=row["bill_property_id"],
            owner_name=row["bill_owner"],
            assessed_tax=row["assessed_tax"],
            exemption_amount=row["exemption_amount"],
            penalty=row["penalty"],
            amount_due=row["amount_due"],
            issue_date=row["issue_date"],
            due_date=row["due_date"],
            document_id=documents["tax_bill"].id,
        )
    )
    session.add(
        TaxReceipt(
            receipt_id=row["receipt_id"],
            case_key=row["case_key"],
            fiscal_year=row["fiscal_year"],
            property_id=row["receipt_property_id"],
            owner_name=row["receipt_owner"],
            amount_paid=row["amount_paid"],
            paid_date=row["paid_date"],
            document_id=documents["payment_receipt"].id,
        )
    )


def _document(row: dict, doc_type: str) -> Document:
    payload = {
        "case_key": row["case_key"],
        "doc_type": doc_type,
        "fiscal_year": row["fiscal_year"],
        "error_type": row["error_type"],
    }
    digest = hashlib.sha256(json.dumps(payload, sort_keys=True).encode("utf-8")).hexdigest()
    return Document(
        sha256=digest,
        filename=f"{row['case_key']}_{doc_type}.txt",
        family="property_tax",
        doc_type=doc_type,
        source="synthetic_structured",
        status="stored",
        page_count=1,
    )


def _write_answer_key(path: Path, rows: list[dict[str, str]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    ordered = sorted(rows, key=lambda item: (item["case_key"], item.get("rule_id", "")))
    with path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=ANSWER_KEY_COLUMNS)
        writer.writeheader()
        writer.writerows(ordered)


def main() -> None:
    from families.property_tax.family import PropertyTaxFamily

    settings = load_settings()
    setup_logging(settings.logging_level)
    init_db()
    family = PropertyTaxFamily()
    generator = family.generator()
    with session_factory()() as session:
        result = generator.generate(
            session,
            n=settings.generator.counts["property_tax"],
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
