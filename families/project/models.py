"""Project tables. Core tables live in core.db."""

from __future__ import annotations

from datetime import date

from sqlalchemy import Date, Float, ForeignKey, Integer, String
from sqlalchemy.orm import Mapped, mapped_column

from core.db import Base


class Project(Base):
    __tablename__ = "projects"

    project_id: Mapped[str] = mapped_column(String(32), primary_key=True)
    name: Mapped[str] = mapped_column(String(200))
    city: Mapped[str] = mapped_column(String(100))
    department: Mapped[str] = mapped_column(String(100))
    budget: Mapped[float] = mapped_column(Float)
    start_date: Mapped[date] = mapped_column(Date)
    expected_end_date: Mapped[date] = mapped_column(Date)
    contractor: Mapped[str] = mapped_column(String(200))


class Tender(Base):
    __tablename__ = "tenders"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    project_id: Mapped[str] = mapped_column(ForeignKey("projects.project_id"), index=True)
    tender_estimate: Mapped[float | None] = mapped_column(Float, nullable=True)
    award_value: Mapped[float | None] = mapped_column(Float, nullable=True)
    contractor: Mapped[str | None] = mapped_column(String(200), nullable=True)
    document_id: Mapped[int | None] = mapped_column(ForeignKey("documents.id"), nullable=True)


class WorkOrder(Base):
    __tablename__ = "work_orders"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    project_id: Mapped[str] = mapped_column(ForeignKey("projects.project_id"), index=True)
    work_order_value: Mapped[float | None] = mapped_column(Float, nullable=True)
    work_order_date: Mapped[date | None] = mapped_column(Date, nullable=True)
    contractor: Mapped[str | None] = mapped_column(String(200), nullable=True)
    document_id: Mapped[int | None] = mapped_column(ForeignKey("documents.id"), nullable=True)


class Invoice(Base):
    __tablename__ = "invoices"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    project_id: Mapped[str] = mapped_column(ForeignKey("projects.project_id"), index=True)
    invoice_no: Mapped[str | None] = mapped_column(String(64), nullable=True, index=True)
    vendor: Mapped[str | None] = mapped_column(String(200), nullable=True)
    amount: Mapped[float | None] = mapped_column(Float, nullable=True)
    invoice_date: Mapped[date | None] = mapped_column(Date, nullable=True)
    document_id: Mapped[int | None] = mapped_column(ForeignKey("documents.id"), nullable=True)


class ProgressReport(Base):
    __tablename__ = "progress_reports"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    project_id: Mapped[str] = mapped_column(ForeignKey("projects.project_id"), index=True)
    report_month: Mapped[str] = mapped_column(String(7))
    physical_pct: Mapped[float | None] = mapped_column(Float, nullable=True)
    financial_pct: Mapped[float | None] = mapped_column(Float, nullable=True)
    document_id: Mapped[int | None] = mapped_column(ForeignKey("documents.id"), nullable=True)
