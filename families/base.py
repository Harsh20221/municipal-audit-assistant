"""Abstract document family. Core code depends only on this interface."""

from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass
from typing import Any

from pydantic import BaseModel


@dataclass(frozen=True)
class DocumentTypeSpec:
    name: str
    keywords: tuple[str, ...]
    schema: type[BaseModel]


@dataclass
class ExtractionResult:
    """Validated PDF extraction. persist() writes the extraction row and family tables."""

    doc_type: str
    fields: dict[str, Any]
    field_pages: dict[str, int]
    model_name: str
    validation_errors: list[str]
    case_id: str = ""
    document_id: int | None = None
    filename: str = ""
    sha256: str = ""
    page_count: int = 1
    is_scanned: bool = False
    status: str = "extracted"
    accepted: bool = False


class DocumentFamily(ABC):
    name: str
    version: str
    case_entity_type: str = "case"

    @abstractmethod
    def document_types(self) -> list[DocumentTypeSpec]:
        """Doc types, classification keywords, and extraction schemas."""

    @abstractmethod
    def extraction_prompt(self, doc_type: str) -> str:
        """Prompt text for a later LLM extraction call. Not used in Phase 1."""

    @abstractmethod
    def models(self) -> list[type]:
        """SQLAlchemy models for this family's tables."""

    @abstractmethod
    def persist(self, extraction_result: ExtractionResult, session) -> None:
        """Write the extraction row and the family tables."""

    def clear_case(self, session, case_id: str) -> None:
        """Remove one case so a PDF ingest can replace the structured rows."""
        return None

    @abstractmethod
    def rules(self) -> list:
        """Registered Rule objects for layers 1-3."""

    @abstractmethod
    def feature_frame(self, session):
        """Numeric feature rows for Layer 4, including a peer_group column."""

    def feature_fields(self) -> dict[str, str]:
        """Map a feature name to the source field a rule finding would cite."""
        return {}

    @abstractmethod
    def generator(self):
        """Synthetic structured-data generator for this family."""

    def case_key_for_finding(self, session, entity_type: str, entity_id: str) -> str | None:
        """Map a stored finding back to the generator's answer-key case.

        The default assumes entity_id is already the case key. Families whose
        findings point at child rows override this.
        """
        return entity_id

    def rule_params(self) -> dict:
        return {"version": self.version, "notes": "", "values": {}}
