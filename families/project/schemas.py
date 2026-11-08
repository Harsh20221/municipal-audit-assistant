"""Pydantic field sets for project documents. LLM extraction uses them in Phase 4."""

from __future__ import annotations

from datetime import date

from pydantic import BaseModel, Field


class TenderFields(BaseModel):
    project_id: str
    name: str
    city: str
    department: str
    contractor: str
    tender_estimate: float
    award_value: float


class WorkOrderFields(BaseModel):
    project_id: str
    contractor: str
    work_order_value: float = Field(alias="value")
    work_order_date: date = Field(alias="date")

    model_config = {"populate_by_name": True}


class InvoiceFields(BaseModel):
    project_id: str
    invoice_no: str
    vendor: str
    amount: float
    invoice_date: date


class ProgressFields(BaseModel):
    project_id: str
    report_month: str
    physical_pct: float
    financial_pct: float
