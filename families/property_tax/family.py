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
    description = "Compare an assessment, a bill, and a receipt with the illustrative tax formula."
    case_entity_type = "property"

    def document_types(self) -> list[DocumentTypeSpec]:
        return [
            _slot(
                "assessment_form",
                ("property tax assessment", "assessment form", "assessed tax"),
                AssessmentFields,
                label="Assessment form",
                description=(
                    "One assessment for a property and fiscal year. "
                    "It records the area, zone, category, and assessed tax."
                ),
                key_fields=(
                    "Property ID",
                    "Owner name",
                    "Zone",
                    "Category",
                    "Built-up area",
                    "Construction year",
                    "Fiscal year",
                    "Assessed tax",
                    "Exemption amount",
                ),
                needed_for=(
                    "PT-001 negative amounts",
                    "PT-002 missing identity",
                    "PT-004 billed amount",
                    "PT-005 assessed tax",
                    "PT-007 identity match across documents",
                    "PT-009 exemption support",
                ),
                what_to_look_for=(
                    "Zone, category, built-up area, and construction year. "
                    "The tax formula reads those fields."
                ),
            ),
            _slot(
                "tax_bill",
                ("property tax bill", "tax bill", "amount due"),
                TaxBillFields,
                label="Tax bill",
                description="One bill for the same property and fiscal year, with the amount due.",
                key_fields=(
                    "Property ID",
                    "Owner name",
                    "Fiscal year",
                    "Assessed tax",
                    "Exemption amount",
                    "Penalty",
                    "Amount due",
                    "Issue date",
                    "Due date",
                ),
                needed_for=(
                    "PT-003 due date before issue date",
                    "PT-004 billed amount",
                    "PT-006 receipt matches the bill",
                    "PT-008 late payment without a penalty",
                    "PT-009 exemption support",
                ),
                what_to_look_for="Amount due, issue date, due date, exemption, and penalty.",
            ),
            _slot(
                "payment_receipt",
                ("payment receipt", "amount paid", "receipt no"),
                ReceiptFields,
                label="Payment receipt",
                description="One receipt for the amount paid against that bill.",
                key_fields=(
                    "Property ID",
                    "Owner name",
                    "Fiscal year",
                    "Receipt number",
                    "Amount paid",
                    "Paid date",
                ),
                needed_for=(
                    "PT-001 negative amounts",
                    "PT-006 receipt matches the bill",
                    "PT-008 late payment without a penalty",
                ),
                what_to_look_for=(
                    "Amount paid, paid date, and the property ID printed on the receipt."
                ),
            ),
        ]

    def case_id_field(self) -> str:
        return "property_id"

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


def _slot(name, keywords, schema, **kwargs) -> DocumentTypeSpec:
    if "key_fields" in kwargs:
        kwargs["key_fields_it_must_contain"] = kwargs.pop("key_fields")
    return DocumentTypeSpec(
        name,
        keywords,
        schema,
        sample_pdf_path=f"data/samples/property_tax/{name}.pdf",
        accepted_formats=("digital PDF",),
        required=True,
        allow_multiple=False,
        **kwargs,
    )
