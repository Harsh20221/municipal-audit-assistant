import sys

from core.config import load_settings
from core.registry import discover_families
from families.project.family import ProjectFamily
from families.property_tax.family import PropertyTaxFamily


def test_registry_returns_only_enabled_families():
    settings = load_settings()
    assert settings.enabled_families == ["property_tax", "project"]
    found = discover_families()
    assert [family.name for family in found] == ["project", "property_tax"]
    assert isinstance(found[0], ProjectFamily)
    assert isinstance(found[1], PropertyTaxFamily)
    assert "families._template.family" not in sys.modules


def test_registry_skips_families_that_are_not_enabled():
    assert discover_families(enabled=[]) == []
    assert discover_families(enabled=["building_plan"]) == []


def test_property_tax_exposes_three_document_types():
    family = PropertyTaxFamily()
    names = [spec.name for spec in family.document_types()]
    assert names == ["assessment_form", "tax_bill", "payment_receipt"]
    prompt = family.extraction_prompt("tax_bill")
    assert "amount_due" in prompt
    assert "anomalous" in prompt
