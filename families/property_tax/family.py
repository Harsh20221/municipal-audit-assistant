"""Property-tax plugin. The registry loads this module by folder name."""

from __future__ import annotations

from pathlib import Path

from sqlalchemy import select

from core.config import load_rule_file
from families.base import DocumentFamily, DocumentTypeSpec, ExtractionResult
from families.property_tax.features import FEATURE_FIELDS, build_feature_frame
from families.property_tax.generator import PropertyTaxGenerator
from families.property_tax.models import Property, TaxAssessment, TaxBill, TaxReceipt
from families.property_tax.persist import clear_case, persist_property
from families.property_tax.rules import registered_rules
from families.property_tax.schemas import AssessmentFields, ReceiptFields, TaxBillFields

_RULES_PATH = Path(__file__).with_name("rules.yaml")


class PropertyTaxFamily(DocumentFamily):
    name = "property_tax"
    version = "0.1.0"
    case_entity_type = "property"

    def document_types(self) -> list[DocumentTypeSpec]:
        return [
            DocumentTypeSpec(
                "assessment_form",
                ("property tax assessment", "assessment form", "assessed tax"),
                AssessmentFields,
            ),
            DocumentTypeSpec(
                "tax_bill",
                ("property tax bill", "tax bill", "amount due"),
                TaxBillFields,
            ),
            DocumentTypeSpec(
                "payment_receipt",
                ("payment receipt", "amount paid", "receipt no"),
                ReceiptFields,
            ),
        ]

    def extraction_prompt(self, doc_type: str) -> str:
        spec = next(item for item in self.document_types() if item.name == doc_type)
        fields = ", ".join(spec.schema.model_fields)
        return (
            "Extract only the requested fields from the document text into one JSON object. "
            "Copy values that are written in the text. Use null when a field is absent. "
            "Do not decide whether any value is anomalous. "
            f"Document type: {doc_type}. Fields: {fields}."
        )

    def models(self) -> list[type]:
        return [Property, TaxAssessment, TaxBill, TaxReceipt]

    def persist(self, extraction_result: ExtractionResult, session) -> None:
        persist_property(extraction_result, session)

    def clear_case(self, session, case_id: str) -> None:
        clear_case(session, case_id)

    def rules(self) -> list:
        return registered_rules()

    def feature_frame(self, session):
        return build_feature_frame(session, self.rule_params()["values"])

    def feature_fields(self) -> dict[str, str]:
        return dict(FEATURE_FIELDS)

    def generator(self) -> PropertyTaxGenerator:
        return PropertyTaxGenerator(self.rule_params())

    def case_key_for_finding(self, session, entity_type: str, entity_id: str) -> str | None:
        if entity_type == "property":
            return entity_id
        if entity_type == "tax_bill":
            row = session.get(TaxBill, int(entity_id))
        elif entity_type == "tax_assessment":
            row = session.get(TaxAssessment, int(entity_id))
        elif entity_type == "tax_receipt":
            row = session.scalar(select(TaxReceipt).where(TaxReceipt.receipt_id == entity_id))
        else:
            return entity_id
        return None if row is None else row.case_key

    def rule_params(self) -> dict:
        return load_rule_file(_RULES_PATH)
