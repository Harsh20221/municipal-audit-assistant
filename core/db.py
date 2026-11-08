"""SQLite engine and core tables shared by every document family."""

from __future__ import annotations

from datetime import UTC, datetime

from sqlalchemy import JSON, Boolean, DateTime, Float, Integer, String, create_engine, event, text
from sqlalchemy.engine import Engine
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, sessionmaker

_engines: dict[str, Engine] = {}


class Base(DeclarativeBase):
    pass


class Document(Base):
    __tablename__ = "documents"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    sha256: Mapped[str | None] = mapped_column(String(64), unique=True, nullable=True)
    filename: Mapped[str] = mapped_column(String(255))
    family: Mapped[str] = mapped_column(String(64), index=True)
    doc_type: Mapped[str] = mapped_column(String(64))
    source: Mapped[str] = mapped_column(String(64))
    status: Mapped[str] = mapped_column(String(32), default="stored")
    page_count: Mapped[int | None] = mapped_column(Integer, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=lambda: datetime.now(UTC))


class Extraction(Base):
    __tablename__ = "extractions"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    document_id: Mapped[int] = mapped_column(Integer, index=True)
    fields_json: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    field_pages_json: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    model_name: Mapped[str | None] = mapped_column(String(128), nullable=True)
    validation_errors_json: Mapped[list | None] = mapped_column(JSON, nullable=True)
    is_scanned: Mapped[bool] = mapped_column(Boolean, default=False)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=lambda: datetime.now(UTC))


class FindingRow(Base):
    __tablename__ = "findings"

    finding_id: Mapped[str] = mapped_column(String(36), primary_key=True)
    family: Mapped[str] = mapped_column(String(64), index=True)
    rule_id: Mapped[str] = mapped_column(String(32), index=True)
    layer: Mapped[int] = mapped_column(Integer)
    entity_type: Mapped[str] = mapped_column(String(64))
    entity_id: Mapped[str] = mapped_column(String(64), index=True)
    severity: Mapped[str] = mapped_column(String(16), index=True)
    expected_value: Mapped[str | None] = mapped_column(String(500), nullable=True)
    actual_value: Mapped[str | None] = mapped_column(String(500), nullable=True)
    difference: Mapped[str | None] = mapped_column(String(200), nullable=True)
    evidence: Mapped[list] = mapped_column(JSON)
    rule_version: Mapped[str] = mapped_column(String(64))
    created_at: Mapped[datetime] = mapped_column(DateTime)
    review_status: Mapped[str] = mapped_column(String(32), default="open", index=True)


class RiskScore(Base):
    __tablename__ = "risk_scores"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    family: Mapped[str] = mapped_column(String(64), index=True)
    entity_type: Mapped[str] = mapped_column(String(64))
    entity_id: Mapped[str] = mapped_column(String(64), index=True)
    score: Mapped[float] = mapped_column(Float)
    band: Mapped[str] = mapped_column(String(16))
    computed_at: Mapped[datetime] = mapped_column(DateTime)


class AuditLog(Base):
    __tablename__ = "audit_log"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=lambda: datetime.now(UTC))
    action: Mapped[str] = mapped_column(String(64))
    detail_json: Mapped[dict | None] = mapped_column(JSON, nullable=True)


@event.listens_for(Engine, "connect")
def _enable_sqlite_foreign_keys(dbapi_connection, _connection_record) -> None:
    if dbapi_connection.__class__.__module__.startswith("sqlite3"):
        cursor = dbapi_connection.cursor()
        cursor.execute("PRAGMA foreign_keys=ON")
        cursor.close()


def get_engine(url: str | None = None) -> Engine:
    if url is None:
        from core.config import load_settings

        url = load_settings().database_url
    if url not in _engines:
        if url.startswith("sqlite:///") and ":memory:" not in url:
            from pathlib import Path

            Path(url.removeprefix("sqlite:///")).parent.mkdir(parents=True, exist_ok=True)
        connect_args = {"check_same_thread": False} if url.startswith("sqlite") else {}
        _engines[url] = create_engine(url, connect_args=connect_args)
    return _engines[url]


def session_factory(engine: Engine | None = None):
    return sessionmaker(bind=engine or get_engine(), expire_on_commit=False)


def init_db(engine: Engine | None = None) -> Engine:
    """Create core tables and tables for every enabled family."""
    from core.registry import discover_families

    bound = engine or get_engine()
    for family in discover_families():
        family.models()
    Base.metadata.create_all(bound)
    _ensure_extraction_is_scanned(bound)
    return bound


def _ensure_extraction_is_scanned(engine: Engine) -> None:
    """Add is_scanned on databases created before Phase 4."""
    with engine.begin() as connection:
        rows = connection.execute(text("PRAGMA table_info(extractions)")).fetchall()
        if rows and "is_scanned" not in {row[1] for row in rows}:
            connection.execute(
                text("ALTER TABLE extractions ADD COLUMN is_scanned BOOLEAN NOT NULL DEFAULT 0")
            )
