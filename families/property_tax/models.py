"""Property-tax tables. Core tables live in core.db."""

from __future__ import annotations

from datetime import date

from sqlalchemy import Float, ForeignKey, Integer, String
from sqlalchemy.orm import Mapped, mapped_column

from core.db import Base


class Property(Base):
    __tablename__ = "properties"

    case_key: Mapped[str] = mapped_column(String(32), primary_key=True)
    property_id: Mapped[str] = mapped_column(String(32), index=True)
    owner_name: Mapped[str] = mapped_column(String(200))
    address: Mapped[str] = mapped_column(String(400))
    ward: Mapped[str] = mapped_column(String(50))
    zone: Mapped[str] = mapped_column(String(8))
    category: Mapped[str] = mapped_column(String(32))
    built_up_area_sqft: Mapped[float] = mapped_column(Float)
    construction_year: Mapped[int] = mapped_column(Integer)
    fiscal_year: Mapped[str] = mapped_column(String(16))


class TaxAssessment(Base):
    __tablename__ = "tax_assessments"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    case_key: Mapped[str] = mapped_column(ForeignKey("properties.case_key"), index=True)
    fiscal_year: Mapped[str] = mapped_column(String(16))
    property_id: Mapped[str | None] = mapped_column(String(32), nullable=True)
    owner_name: Mapped[str | None] = mapped_column(String(200), nullable=True)
    assessed_tax: Mapped[float | None] = mapped_column(Float, nullable=True)
    exemption_amount: Mapped[float | None] = mapped_column(Float, nullable=True)
    document_id: Mapped[int | None] = mapped_column(ForeignKey("documents.id"), nullable=True)


class TaxBill(Base):
    __tablename__ = "tax_bills"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    case_key: Mapped[str] = mapped_column(ForeignKey("properties.case_key"), index=True)
    fiscal_year: Mapped[str] = mapped_column(String(16))
    property_id: Mapped[str | None] = mapped_column(String(32), nullable=True)
    owner_name: Mapped[str | None] = mapped_column(String(200), nullable=True)
    assessed_tax: Mapped[float | None] = mapped_column(Float, nullable=True)
    exemption_amount: Mapped[float | None] = mapped_column(Float, nullable=True)
    penalty: Mapped[float | None] = mapped_column(Float, nullable=True)
    amount_due: Mapped[float | None] = mapped_column(Float, nullable=True)
    issue_date: Mapped[date | None] = mapped_column(nullable=True)
    due_date: Mapped[date | None] = mapped_column(nullable=True)
    document_id: Mapped[int | None] = mapped_column(ForeignKey("documents.id"), nullable=True)


class TaxReceipt(Base):
    __tablename__ = "tax_receipts"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    receipt_id: Mapped[str] = mapped_column(String(32), unique=True)
    case_key: Mapped[str] = mapped_column(ForeignKey("properties.case_key"), index=True)
    fiscal_year: Mapped[str] = mapped_column(String(16))
    property_id: Mapped[str | None] = mapped_column(String(32), nullable=True)
    owner_name: Mapped[str | None] = mapped_column(String(200), nullable=True)
    amount_paid: Mapped[float | None] = mapped_column(Float, nullable=True)
    paid_date: Mapped[date | None] = mapped_column(nullable=True)
    document_id: Mapped[int | None] = mapped_column(ForeignKey("documents.id"), nullable=True)
