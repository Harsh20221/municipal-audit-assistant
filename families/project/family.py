"""Project plugin. The registry loads this module by folder name."""

from __future__ import annotations

from pathlib import Path

from core.config import load_rule_file
from families.base import DocumentFamily, DocumentTypeSpec, ExtractionResult
from families.project.features import FEATURE_FIELDS, build_feature_frame
from families.project.generator import ProjectGenerator
from families.project.models import Invoice, ProgressReport, Project, Tender, WorkOrder
from families.project.persist import clear_case, persist_project
from families.project.rules import registered_rules
from families.project.schemas import InvoiceFields, ProgressFields, TenderFields, WorkOrderFields

_RULES_PATH = Path(__file__).with_name("rules.yaml")


class ProjectFamily(DocumentFamily):
    name = "project"
    version = "0.1.0"
    case_entity_type = "project"

    def document_types(self) -> list[DocumentTypeSpec]:
        return [
            DocumentTypeSpec(
                "tender_award_notice",
                ("tender", "award notice", "tender estimate"),
                TenderFields,
            ),
            DocumentTypeSpec(
                "work_order",
                ("work order", "work-order"),
                WorkOrderFields,
            ),
            DocumentTypeSpec(
                "invoice",
                ("invoice", "tax invoice", "bill for work"),
                InvoiceFields,
            ),
            DocumentTypeSpec(
                "progress_report",
                ("progress report", "physical progress", "financial progress"),
                ProgressFields,
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
        return [Project, Tender, WorkOrder, Invoice, ProgressReport]

    def persist(self, extraction_result: ExtractionResult, session) -> None:
        persist_project(extraction_result, session)

    def clear_case(self, session, case_id: str) -> None:
        clear_case(session, case_id)

    def rules(self) -> list:
        return registered_rules()

    def feature_frame(self, session):
        return build_feature_frame(session, self.rule_params()["values"])

    def feature_fields(self) -> dict[str, str]:
        return dict(FEATURE_FIELDS)

    def generator(self) -> ProjectGenerator:
        return ProjectGenerator(self.rule_params())

    def rule_params(self) -> dict:
        return load_rule_file(_RULES_PATH)

    def case_key_for_finding(self, session, entity_type: str, entity_id: str) -> str | None:
        if entity_type == "project":
            return entity_id
        model = {
            "tender": Tender,
            "work_order": WorkOrder,
            "invoice": Invoice,
            "progress_report": ProgressReport,
        }.get(entity_type)
        if model is None:
            return entity_id
        row = session.get(model, int(entity_id))
        return None if row is None else row.project_id
