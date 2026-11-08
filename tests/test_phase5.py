"""Phase 5 checks. These use FakeLLMClient and never call a live model."""

from datetime import date
from pathlib import Path

from core.config import load_settings
from core.llm import FakeLLMClient, cache_dir_from
from core.registry import discover_families
from engine.coverage import coverage
from explain.explain import explain_finding
from families.property_tax.family import PropertyTaxFamily
from ingestion.build_pdfs import TITLES
from ingestion.bundle import validate_bundle
from ingestion.pdf_layouts import PdfSpec, write_pdf


def _client(tmp_path: Path, script=None) -> FakeLLMClient:
    settings = cache_dir_from(load_settings().llm, tmp_path / "cache")
    return FakeLLMClient(settings, script=script)


def _write(path: Path, doc_type: str, case_id: str, fields: dict) -> None:
    write_pdf(
        PdfSpec(
            family="property_tax",
            case_id=case_id,
            doc_type=doc_type,
            layout="standard",
            title=TITLES[doc_type],
            fields=fields,
        ),
        path,
    )


def _bill(property_id: str) -> dict:
    return {
        "property_id": property_id,
        "owner_name": "Sample Owner",
        "fiscal_year": "2024-25",
        "assessed_tax": 29280.0,
        "exemption_amount": 0.0,
        "penalty": 0.0,
        "amount_due": 29280.0,
        "issue_date": date(2024, 4, 1),
        "due_date": date(2024, 4, 30),
        "address": "1 Sample Street",
        "ward": "Ward 1",
        "zone": "A",
        "category": "residential",
        "built_up_area_sqft": 1000.0,
        "construction_year": 2019,
    }


def _assessment(property_id: str) -> dict:
    fields = _bill(property_id)
    for name in ("penalty", "amount_due", "issue_date", "due_date"):
        fields.pop(name)
    return fields


def test_a_rule_is_skipped_when_its_document_is_missing():
    family = PropertyTaxFamily()
    result = coverage(family.rules(), {"assessment_form"})
    skipped = {item["rule_id"]: item["reason"] for item in result["rules_skipped"]}
    assert result["rules_run"] == ["PT-005"]
    assert skipped["PT-003"] == "missing: tax_bill"
    assert "missing: " in skipped["PT-004"]
    assert "tax_bill" in skipped["PT-004"]


def test_bundle_flags_wrong_slot_other_case_duplicate_and_a_missing_slot(tmp_path):
    family = PropertyTaxFamily()
    bill = tmp_path / "bill.pdf"
    other = tmp_path / "other.pdf"
    assessment = tmp_path / "assessment.pdf"
    _write(bill, "tax_bill", "PID90001", _bill("PID90001"))
    _write(other, "tax_bill", "PID90002", _bill("PID90002"))
    _write(assessment, "assessment_form", "PID90001", _assessment("PID90001"))
    client = _client(tmp_path)
    wrong = validate_bundle(
        family, [{"path": bill, "slot": "assessment_form"}], client
    )
    assert wrong["files"][0]["status"] == "error"
    assert "Wrong slot" in wrong["files"][0]["message"]
    mixed = validate_bundle(
        family,
        [
            {"path": bill, "slot": "tax_bill"},
            {"path": other, "slot": "tax_bill"},
        ],
        client,
    )
    assert "belongs to PID90002" in mixed["files"][1]["message"]
    copied = tmp_path / "bill-copy.pdf"
    copied.write_bytes(bill.read_bytes())
    duplicate = validate_bundle(
        family,
        [
            {"path": bill, "slot": "tax_bill"},
            {"path": copied, "slot": "tax_bill"},
        ],
        client,
    )
    assert duplicate["files"][1]["status"] == "warning"
    assert "duplicate" in duplicate["files"][1]["message"]
    incomplete = validate_bundle(
        family,
        [
            {"path": assessment, "slot": "assessment_form"},
            {"path": bill, "slot": "tax_bill"},
        ],
        client,
    )
    receipt = next(slot for slot in incomplete["slots"] if slot["name"] == "payment_receipt")
    assert receipt["status"] == "missing"
    assert incomplete["verdict"] == "incomplete"


def test_an_invented_number_is_replaced_by_the_template(tmp_path):
    finding = {
        "rule_id": "PT-004",
        "expected_value": "100.00",
        "actual_value": "29280.00",
        "difference": "29180.00",
        "evidence": [{"field": "amount_due", "page": 1, "doc_id": None}],
    }
    invented = (
        "The gap is 99999. This requires manual verification.\n"
        "What to check manually: ignore the page."
    )
    client = _client(tmp_path, script=[invented, invented])
    result = explain_finding(finding, client, cache_dir=tmp_path / "explain")
    assert result["guardrail_passed"] is False
    assert result["source"] == "template"
    assert "99999" not in result["text"]
    assert "requires manual verification" in result["text"].lower()
    assert "What to check manually:" in result["text"]
    assert "29280.00" in result["text"]


def test_every_document_slot_has_a_label_description_and_check():
    for family in discover_families():
        for document in family.requirements()["documents"]:
            assert document["label"]
            assert document["description"]
            assert document["needed_for"]
            assert document["sample_pdf_path"]
            assert "digital PDF" in document["accepted_formats"]
