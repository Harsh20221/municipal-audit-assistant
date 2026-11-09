"""API tests. The client is the fake model, and the database is temporary."""

from datetime import date

from fastapi.testclient import TestClient
from pydantic import BaseModel
from sqlalchemy import create_engine

from api.app import create_app
from core.config import load_settings
from core.db import init_db
from core.llm import FakeLLMClient, cache_dir_from
from core.registry import discover_families
from families.base import DocumentFamily, DocumentTypeSpec
from ingestion.build_pdfs import TITLES
from ingestion.pdf_layouts import PdfSpec, write_pdf


class _Note(BaseModel):
    note_id: str


class DummyFamily(DocumentFamily):
    name = "dummy_runtime"
    version = "0"
    description = "Registered in the test, not in config."

    def document_types(self):
        return [
            DocumentTypeSpec(
                "note",
                ("note",),
                _Note,
                label="Note",
                description="A short note for the runtime family.",
                key_fields_it_must_contain=("Note id",),
                needed_for=("A sample check",),
                what_to_look_for="The note id.",
                sample_pdf_path="data/samples/dummy_runtime/note.pdf",
            )
        ]

    def extraction_prompt(self, doc_type: str) -> str:
        return "Extract note_id."

    def models(self):
        return []

    def persist(self, extraction_result, session) -> None:
        return None

    def rules(self):
        return []

    def feature_frame(self, session):
        return None

    def generator(self):
        return None


def _engine(tmp_path):
    url = "sqlite:///" + tmp_path.joinpath("api.db").as_posix()
    engine = create_engine(url, connect_args={"check_same_thread": False})
    init_db(engine)
    return engine


def _client(tmp_path) -> FakeLLMClient:
    settings = cache_dir_from(load_settings().llm, tmp_path / "llm-cache")
    return FakeLLMClient(settings)


def _app(tmp_path, families=None):
    return create_app(
        families=families if families is not None else discover_families(),
        client=_client(tmp_path),
        engine=_engine(tmp_path),
    )


def _assessment(path) -> None:
    write_pdf(
        PdfSpec(
            family="property_tax",
            case_id="PID90001",
            doc_type="assessment_form",
            layout="standard",
            title=TITLES["assessment_form"],
            fields={
                "property_id": "PID90001",
                "owner_name": "Sample Owner",
                "address": "1 Sample Street",
                "ward": "Ward 1",
                "zone": "A",
                "category": "residential",
                "built_up_area_sqft": 1000.0,
                "construction_year": 2019,
                "fiscal_year": "2024-25",
                "assessed_tax": 29280.0,
                "exemption_amount": 0.0,
            },
        ),
        path,
    )


def _bill(path) -> None:
    write_pdf(
        PdfSpec(
            family="property_tax",
            case_id="PID90001",
            doc_type="tax_bill",
            layout="standard",
            title=TITLES["tax_bill"],
            fields={
                "property_id": "PID90001",
                "owner_name": "Sample Owner",
                "fiscal_year": "2024-25",
                "assessed_tax": 29280.0,
                "exemption_amount": 0.0,
                "penalty": 0.0,
                "amount_due": 29280.0,
                "issue_date": date(2024, 4, 1),
                "due_date": date(2024, 4, 30),
                "zone": "A",
                "category": "residential",
                "built_up_area_sqft": 1000.0,
                "construction_year": 2019,
            },
        ),
        path,
    )


def test_requirements_list_every_slot(tmp_path):
    client = TestClient(_app(tmp_path))
    response = client.get("/api/v1/families/property_tax/requirements")
    assert response.status_code == 200
    body = response.json()
    names = [item["name"] for item in body["documents"]]
    assert names == ["assessment_form", "tax_bill", "payment_receipt"]
    assert all(item["label"] and item["needed_for"] for item in body["documents"])
    assert "scanned documents are not supported" in " ".join(body["notices"]).lower()


def test_validate_flags_a_file_in_the_wrong_slot(tmp_path):
    bill = tmp_path / "bill.pdf"
    _bill(bill)
    client = TestClient(_app(tmp_path))
    response = client.post(
        "/api/v1/cases/property_tax/validate",
        files=[
            ("files", ("bill.pdf", bill.read_bytes(), "application/pdf")),
            ("slots", (None, "assessment_form")),
        ],
    )
    assert response.status_code == 200
    row = response.json()["files"][0]
    assert row["status"] == "error"
    assert "looks like" in row["message"].lower()
    assert "assessment" in row["message"].lower()


def test_audit_reports_skipped_rules_when_a_document_is_missing(tmp_path, monkeypatch):
    monkeypatch.setattr("explain.explain.CACHE_DIR", tmp_path / "explanations")
    assessment = tmp_path / "assessment.pdf"
    _assessment(assessment)
    client = TestClient(_app(tmp_path))
    response = client.post(
        "/api/v1/cases/property_tax/audit",
        files=[
            ("files", ("assessment.pdf", assessment.read_bytes(), "application/pdf")),
            ("slots", (None, "assessment_form")),
            ("run_with_available", (None, "true")),
        ],
    )
    assert response.status_code == 200, response.text
    body = response.json()
    assert body["case_id"] == "PID90001"
    skipped = {item["rule_id"]: item["reason"] for item in body["coverage"]["rules_skipped"]}
    assert "PT-005" in body["coverage"]["rules_run"]
    assert skipped["PT-003"] == "missing: tax_bill"
    explanation = body["coverage"]["rules_skipped"][0]["explanation"].lower()
    assert "requires manual verification" in explanation
    assert body["risk"]["band"] == "low"


def test_a_runtime_family_appears_without_a_core_change(tmp_path):
    families = [*discover_families(), DummyFamily()]
    client = TestClient(_app(tmp_path, families))
    names = [item["name"] for item in client.get("/api/v1/families").json()["families"]]
    assert "dummy_runtime" in names
    requirements = client.get("/api/v1/families/dummy_runtime/requirements")
    assert requirements.status_code == 200
    document = requirements.json()["documents"][0]
    assert document["label"] == "Note"
    assert document["needed_for"] == ["A sample check"]
