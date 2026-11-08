"""Pydantic field sets for property-tax documents.

Phase 1 validates generator output with these models. LLM extraction uses them
in Phase 4.
"""

from __future__ import annotations

from datetime import date
from typing import Literal

from pydantic import BaseModel, Field


class AssessmentFields(BaseModel):
    property_id: str
    owner_name: str
    address: str
    ward: str
    zone: str
    category: Literal["residential", "commercial"]
    built_up_area_sqft: float = Field(gt=0)
    construction_year: int
    fiscal_year: str
    assessed_tax: float
    exemption_amount: float


class TaxBillFields(BaseModel):
    property_id: str
    owner_name: str
    fiscal_year: str
    assessed_tax: float
    exemption_amount: float
    amount_due: float
    penalty: float
    issue_date: date
    due_date: date
    address: str | None = None
    ward: str | None = None
    zone: str | None = None
    category: Literal["residential", "commercial"] | None = None
    built_up_area_sqft: float | None = None
    construction_year: int | None = None


class ReceiptFields(BaseModel):
    property_id: str
    owner_name: str
    fiscal_year: str
    receipt_id: str
    amount_paid: float
    paid_date: date
    address: str | None = None
    ward: str | None = None
    zone: str | None = None
    category: Literal["residential", "commercial"] | None = None
    built_up_area_sqft: float | None = None
    construction_year: int | None = None
