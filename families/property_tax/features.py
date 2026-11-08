"""Numeric features for a later Layer 4 pass. Phase 1 only builds the frame."""

from __future__ import annotations

import pandas as pd
from sqlalchemy import select
from sqlalchemy.orm import Session

from families.property_tax.formula import expected_amounts
from families.property_tax.models import Property, TaxBill, TaxReceipt

FEATURE_COLUMNS = [
    "case_key",
    "tax_per_sqft",
    "built_up_area_sqft",
    "building_age",
    "paid_expected_ratio",
]


def build_feature_frame(session: Session, params: dict) -> pd.DataFrame:
    props = session.scalars(select(Property).order_by(Property.case_key)).all()
    bills = {row.case_key: row for row in session.scalars(select(TaxBill)).all()}
    receipts = {row.case_key: row for row in session.scalars(select(TaxReceipt)).all()}
    rows = []
    for prop in props:
        bill = bills.get(prop.case_key)
        receipt = receipts.get(prop.case_key)
        expected = None
        if bill is not None and prop.zone in params["monthly_base_rate"]:
            expected = expected_amounts(
                built_up_area_sqft=prop.built_up_area_sqft,
                zone=prop.zone,
                category=prop.category,
                construction_year=prop.construction_year,
                exemption_amount=bill.exemption_amount or 0.0,
                penalty=bill.penalty or 0.0,
                params=params,
            )
        area = prop.built_up_area_sqft
        amount_due = None if bill is None else bill.amount_due
        amount_paid = None if receipt is None else receipt.amount_paid
        expected_due = None if expected is None else expected["amount_due"]
        rows.append(
            {
                "case_key": prop.case_key,
                "tax_per_sqft": None if not area or amount_due is None else amount_due / area,
                "built_up_area_sqft": area,
                "building_age": None if expected is None else expected["building_age"],
                "paid_expected_ratio": (
                    None if amount_paid is None or not expected_due else amount_paid / expected_due
                ),
            }
        )
    return pd.DataFrame(rows, columns=FEATURE_COLUMNS)
