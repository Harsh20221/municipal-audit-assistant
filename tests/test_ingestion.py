"""PDF ingestion tests. These use FakeLLMClient and never call a live model."""

from collections import Counter
from datetime import date
from pathlib import Path

from reportlab.pdfgen import canvas
from sqlalchemy import select
from tests.conftest import make_session
from tests.helpers import insert_case

from core.config import load_settings
from core.db import Extraction, FindingRow
from core.llm import FakeLLMClient, cache_dir_from
from engine.runner import run_audit
from families.property_tax.family import PropertyTaxFamily
from ingestion.build_pdfs import property_specs
from ingestion.classifier import classify
from ingestion.extractor import extract_document
from ingestion.grounding import ground_fields, value_in_text
from ingestion.normalizers import normalize_amount, normalize_date
from ingestion.pdf_layouts import write_pdf
from ingestion.pdf_reader import read_pdf
from ingestion.pipeline import ingest_pdf
from ingestion.roundtrip import agreement_summary, field_differences, same_value
from ingestion.run import select_cases


def _client(tmp_path, script=None) -> FakeLLMClient:
    settings = cache_dir_from(load_settings().llm, tmp_path / "cache")
    return FakeLLMClient(settings, script=script)


def test_a_spent_credit_balance_is_not_retried():
    from core.llm import _should_retry

    class RateLimitError(Exception):
        pass

    spent = RateLimitError("429 credit_balance_exhausted insufficient_quota")
    assert _should_retry(spent, 0, 3) is False


def test_normalizers_cover_rupees_lakh_crore_and_dates():
    assert normalize_amount("Rs 1,23,456.50") == 123456.50
    assert normalize_amount("₹1,23,456.50") == 123456.50
    assert normalize_amount("INR 1000") == 1000
    assert normalize_amount("1.5 lakh") == 150000
    assert normalize_amount("2 crore") == 20000000
    assert normalize_amount("-Rs 100.00") == -100
    assert normalize_date("15/04/2024") == date(2024, 4, 15)
    assert normalize_date("15-04-24") == date(2024, 4, 15)


def test_grounding_rejects_a_number_the_model_invented():
    page = "Property tax bill\namount_due: Rs 10.00\nproperty_id: PID00001"
    assert value_in_text(10, page) is True
    assert value_in_text(99999, page) is False
    assert value_in_text("PID00001", page) is True
    assert value_in_text("PID99999", page) is False
    _pages, errors = ground_fields({"amount_due": 99999, "property_id": "PID00001"}, page)
    assert errors == ["low_confidence:amount_due"]


def test_classifier_uses_keywords_before_the_llm(tmp_path):
    family = PropertyTaxFamily()
    client = _client(tmp_path, script=["should-not-be-used"])
    assert classify("Property tax bill\nproperty_id: PID1", family.document_types(), client) == (
        "tax_bill"
    )
    assert client.totals.calls == 0
    assert (
        classify(
            "this page has no known heading",
            family.document_types(),
            _client(tmp_path, ["tax_bill"]),
        )
        == "tax_bill"
    )


def test_extractor_retries_once_after_invalid_json(tmp_path):
    family = PropertyTaxFamily()
    page = "\n".join(
        [
            "Property tax bill",
            "property_id: PID00001",
            "owner_name: Asha Rao",
            "fiscal_year: 2024-25",
            "assessed_tax: Rs 100.00",
            "exemption_amount: Rs 0.00",
            "amount_due: Rs 100.00",
            "penalty: Rs 0.00",
            "issue_date: 01/06/2024",
            "due_date: 01/07/2024",
            "zone: A",
            "category: residential",
            "built_up_area_sqft: 1000.00",
            "construction_year: 2019",
            "address: 12 Lake Road",
            "ward: Ward 3",
        ]
    )
    valid = (
        '{"property_id":"PID00001","owner_name":"Asha Rao","fiscal_year":"2024-25",'
        '"assessed_tax":"Rs 100.00","exemption_amount":"Rs 0.00","amount_due":"Rs 100.00",'
        '"penalty":"Rs 0.00","issue_date":"01/06/2024","due_date":"01/07/2024",'
        '"zone":"A","category":"residential","built_up_area_sqft":"1000.00",'
        '"construction_year":"2019","address":"12 Lake Road","ward":"Ward 3"}'
    )
    client = _client(tmp_path, script=["{not json", valid])
    result = extract_document(
        family=family,
        doc_type="tax_bill",
        page_text=page,
        client=client,
        case_id="PID00001",
        filename="bill.pdf",
        sha256="abc",
        page_count=1,
    )
    assert result.accepted is True
    assert result.fields["amount_due"] == 100
    assert client.totals.calls == 2


def test_limit_is_a_stratified_case_count():
    categories = ("clean", "hard_negative", "single_error", "multi_error", "needs_layer4")
    families = ("project", "property_tax")
    rows = []
    labels = {}
    for family in families:
        for category in categories:
            for index in range(4):
                case_id = f"{family[:3]}-{category[:4]}-{index}"
                labels[(family, case_id)] = category
                for doc_type in ("a", "b"):
                    rows.append({"family": family, "case_id": case_id, "doc_type": doc_type})
    chosen = select_cases(rows, labels, 30, seed=42)
    cases = {(row["family"], row["case_id"]) for row in chosen}
    assert len(cases) == 30
    assert len(chosen) == 60
    counts = Counter((family, labels[(family, case_id)]) for family, case_id in cases)
    assert set(counts) == {(family, category) for family in families for category in categories}
    assert set(counts.values()) == {3}
    assert select_cases(rows, labels, 30, seed=42) == chosen


def test_field_differences_ignore_the_copy_marker_and_equal_numbers():
    assert same_value("29280.00", 29280) is True
    diffs = field_differences(
        {"amount_due": 100, "owner_name": "A"},
        {"amount_due": 29280, "owner_name": "A", "document_copy": 2},
    )
    assert diffs == [("amount_due", 100, 29280)]


def test_blank_pdf_is_unsupported_scanned(tmp_path):
    path = tmp_path / "blank.pdf"
    pen = canvas.Canvas(str(path))
    pen.showPage()
    pen.save()
    read = read_pdf(path)
    assert read.unsupported_scanned is True
    session = make_session()
    result = ingest_pdf(
        path,
        PropertyTaxFamily(),
        _client(tmp_path),
        session,
        case_id="PID00001",
        doc_type_hint="tax_bill",
    )
    assert result.is_scanned is True
    stored = session.scalar(select(Extraction))
    assert stored.is_scanned is True
    assert stored.validation_errors_json == ["unsupported_scanned"]


def test_pdf_ingest_fires_the_same_rule_as_the_structured_case(tmp_path):
    source = make_session()
    inserted = insert_case(source, amount_due=1)
    case_id = inserted["case_key"]
    specs = [spec for spec in property_specs(source) if spec.case_id == case_id]
    assert len(specs) == 3
    for spec in specs:
        write_pdf(spec, tmp_path / f"{spec.doc_type}.pdf")
    family = PropertyTaxFamily()
    run_audit(source, [family])
    structured = Counter(
        row.rule_id for row in source.scalars(select(FindingRow).where(FindingRow.layer < 4)).all()
    )
    assert structured == Counter({"PT-004": 1})

    target = make_session()
    client = _client(tmp_path)
    for spec in specs:
        text = read_pdf(tmp_path / f"{spec.doc_type}.pdf")
        assert text.unsupported_scanned is False
        ingest_pdf(
            tmp_path / f"{spec.doc_type}.pdf",
            family,
            client,
            target,
            case_id=case_id,
            doc_type_hint=spec.doc_type,
        )
    target.commit()
    run_audit(target, [family])
    extracted = Counter(
        row.rule_id for row in target.scalars(select(FindingRow).where(FindingRow.layer < 4)).all()
    )
    assert extracted == structured
    summary = agreement_summary({case_id: structured}, {case_id: extracted})
    assert summary["agreed"] == 1
    assert summary["mismatched"] == 0
    assert client.totals.cost_usd == 0
    assert Path(tmp_path / "tax_bill.pdf").exists()
