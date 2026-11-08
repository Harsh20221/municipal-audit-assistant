"""Numeric features for a later Layer 4 pass. Phase 2 only builds the frame."""

from __future__ import annotations

from datetime import date

import pandas as pd
from sqlalchemy import select
from sqlalchemy.orm import Session

from families.project.models import Invoice, ProgressReport, Project

FEATURE_COLUMNS = [
    "case_key",
    "financial_physical_gap",
    "delay_days",
    "invoice_count",
    "spend_budget_ratio",
]


def build_feature_frame(session: Session, params: dict) -> pd.DataFrame:
    as_of = date.fromisoformat(str(params["as_of_date"]))
    projects = session.scalars(select(Project).order_by(Project.project_id)).all()
    invoices: dict[str, list[Invoice]] = {}
    for row in session.scalars(select(Invoice)).all():
        invoices.setdefault(row.project_id, []).append(row)
    reports: dict[str, list[ProgressReport]] = {}
    for row in session.scalars(select(ProgressReport)).all():
        reports.setdefault(row.project_id, []).append(row)
    rows = []
    for project in projects:
        project_invoices = invoices.get(project.project_id, [])
        project_reports = sorted(
            reports.get(project.project_id, []), key=lambda item: item.report_month
        )
        latest = project_reports[-1] if project_reports else None
        gap = None
        if latest and latest.financial_pct is not None and latest.physical_pct is not None:
            gap = latest.financial_pct - latest.physical_pct
        spend = round(sum(item.amount or 0 for item in project_invoices), 2)
        incomplete = latest is None or latest.physical_pct is None or latest.physical_pct < 100
        delay = 0
        if incomplete and project.expected_end_date < as_of:
            delay = (as_of - project.expected_end_date).days
        rows.append(
            {
                "case_key": project.project_id,
                "financial_physical_gap": gap,
                "delay_days": delay,
                "invoice_count": len(project_invoices),
                "spend_budget_ratio": None if not project.budget else spend / project.budget,
            }
        )
    return pd.DataFrame(rows, columns=FEATURE_COLUMNS)
