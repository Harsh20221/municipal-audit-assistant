"""Insert one consistent property-tax case for rule tests."""

from __future__ import annotations

import hashlib
from datetime import date

from sqlalchemy.orm import Session

from core.db import Document
from families.property_tax.family import PropertyTaxFamily
from families.property_tax.formula import expected_amounts
from families.property_tax.models import Property, TaxAssessment, TaxBill, TaxReceipt

_CASE = 0


def rule_params() -> dict:
    return PropertyTaxFamily().rule_params()["values"]


def insert_case(session: Session, **changes):
    global _CASE
    _CASE += 1
    params = rule_params()
    area = changes.pop("area", 1000.0)
    zone = changes.pop("zone", "A")
    category = changes.pop("category", "residential")
    construction_year = changes.pop("construction_year", 2019)
    exemption = changes.pop("exemption", 0.0)
    penalty = changes.pop("penalty", 0.0)
    include_assessment = changes.pop("include_assessment", True)
    case_key = changes.pop("case_key", f"CASE{_CASE:05d}")
    property_id = changes.pop("property_id", f"PID{_CASE:05d}")
    owner = changes.pop("owner_name", "Asha Rao")
    amounts = expected_amounts(
        built_up_area_sqft=area,
        zone=zone,
        category=category,
        construction_year=construction_year,
        exemption_amount=exemption,
        penalty=penalty,
        params=params,
    )
    issue = changes.pop("issue_date", date(2024, 6, 1))
    due = changes.pop("due_date", date(2024, 7, 1))
    paid = changes.pop("paid_date", date(2024, 6, 15))
    amount_due = changes.pop("amount_due", amounts["amount_due"])
    amount_paid = changes.pop("amount_paid", amount_due)
    assessment_assessed = changes.pop("assessment_assessed", amounts["assessed_tax"])
    bill_assessed = changes.pop("bill_assessed", amounts["assessed_tax"])
    bill_owner = changes.pop("bill_owner", owner)
    receipt_owner = changes.pop("receipt_owner", owner)
    assessment_owner = changes.pop("assessment_owner", owner)
    bill_property_id = changes.pop("bill_property_id", property_id)
    receipt_property_id = changes.pop("receipt_property_id", property_id)
    assessment_property_id = changes.pop("assessment_property_id", property_id)
    if changes:
        unknown = ", ".join(sorted(changes))
        raise ValueError(f"Unknown insert_case arguments: {unknown}")

    session.add(
        Property(
            case_key=case_key,
            property_id=property_id,
            owner_name=owner,
            address="12 Lake Road, Pune",
            ward="Ward 3",
            zone=zone,
            category=category,
            built_up_area_sqft=area,
            construction_year=construction_year,
            fiscal_year=params["fiscal_year"],
        )
    )
    docs = {}
    doc_types = ["tax_bill", "payment_receipt"]
    if include_assessment:
        doc_types.insert(0, "assessment_form")
    for doc_type in doc_types:
        digest = hashlib.sha256(f"{case_key}:{doc_type}".encode()).hexdigest()
        docs[doc_type] = Document(
            sha256=digest,
            filename=f"{case_key}_{doc_type}.txt",
            family="property_tax",
            doc_type=doc_type,
            source="unit_test",
            status="stored",
            page_count=1,
        )
    session.add_all(docs.values())
    session.flush()
    assessment = None
    if include_assessment:
        assessment = TaxAssessment(
            case_key=case_key,
            fiscal_year=params["fiscal_year"],
            property_id=assessment_property_id,
            owner_name=assessment_owner,
            assessed_tax=assessment_assessed,
            exemption_amount=exemption,
            document_id=docs["assessment_form"].id,
        )
        session.add(assessment)
    bill = TaxBill(
        case_key=case_key,
        fiscal_year=params["fiscal_year"],
        property_id=bill_property_id,
        owner_name=bill_owner,
        assessed_tax=bill_assessed,
        exemption_amount=exemption,
        penalty=penalty,
        amount_due=amount_due,
        issue_date=issue,
        due_date=due,
        document_id=docs["tax_bill"].id,
    )
    receipt = TaxReceipt(
        receipt_id=f"RCPT{_CASE:05d}",
        case_key=case_key,
        fiscal_year=params["fiscal_year"],
        property_id=receipt_property_id,
        owner_name=receipt_owner,
        amount_paid=amount_paid,
        paid_date=paid,
        document_id=docs["payment_receipt"].id,
    )
    session.add(bill)
    session.add(receipt)
    session.flush()
    return {
        "case_key": case_key,
        "property_id": property_id,
        "amounts": amounts,
        "assessment": assessment,
        "bill": bill,
        "receipt": receipt,
        "docs": docs,
    }
