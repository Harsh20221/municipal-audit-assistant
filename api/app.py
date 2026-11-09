"""FastAPI application. Routes stay thin and read the family registry."""

from __future__ import annotations

import logging

from fastapi import FastAPI, File, Form, HTTPException, Request, UploadFile
from fastapi.exceptions import RequestValidationError
from fastapi.responses import FileResponse, JSONResponse

from api import service
from api.schemas import (
    AuditResponse,
    BundleResponse,
    ErrorResponse,
    EvaluationSummary,
    FamilyList,
    FindingOut,
    FindingPage,
    GuideResponse,
    Health,
    PortfolioResponse,
    RequirementsResponse,
    ReviewUpdate,
    RiskOut,
)
from core.db import FindingRow, init_db, session_factory
from core.llm import make_client
from core.logging import setup_logging
from core.registry import discover_families
from families.base import DocumentFamily

logger = logging.getLogger("api")


def create_app(
    *,
    families: list[DocumentFamily] | None = None,
    client=None,
    engine=None,
) -> FastAPI:
    setup_logging("INFO")
    app = FastAPI(title="Municipal Audit Assistant", version="0.1.0")
    app.state.families = families if families is not None else discover_families()
    app.state.client = client if client is not None else make_client(live=_live_by_default())
    app.state.engine = engine
    init_db(engine)

    @app.middleware("http")
    async def log_request(request: Request, call_next):
        response = await call_next(request)
        logger.info("%s %s -> %s", request.method, request.url.path, response.status_code)
        return response

    @app.exception_handler(HTTPException)
    async def http_error(_request: Request, exc: HTTPException):
        message = exc.detail if isinstance(exc.detail, str) else str(exc.detail)
        return JSONResponse(
            status_code=exc.status_code,
            content={"error": {"code": str(exc.status_code), "message": message}},
        )

    @app.exception_handler(RequestValidationError)
    async def validation_error(_request: Request, exc: RequestValidationError):
        return JSONResponse(
            status_code=422,
            content={"error": {"code": "validation_error", "message": str(exc.errors())}},
        )

    @app.get("/api/v1/health", response_model=Health)
    def health() -> Health:
        return Health()

    @app.get("/api/v1/families", response_model=FamilyList)
    def families_route() -> FamilyList:
        return FamilyList(
            families=[
                {
                    "name": family.name,
                    "description": family.description,
                    "has_portfolio": family.provides_portfolio(),
                }
                for family in app.state.families
            ]
        )

    @app.get(
        "/api/v1/families/{name}/requirements",
        response_model=RequirementsResponse,
        responses={404: {"model": ErrorResponse}},
    )
    def requirements(name: str) -> dict:
        return service.requirements_payload(_family(app, name))

    @app.get(
        "/api/v1/families/{name}/portfolio",
        response_model=PortfolioResponse,
        responses={404: {"model": ErrorResponse}},
    )
    def portfolio(name: str) -> dict:
        family = _family(app, name)
        if not family.provides_portfolio():
            raise HTTPException(status_code=404, detail="This family has no portfolio chart.")
        with _sessions(app)() as session:
            payload = family.portfolio(session) or {"points": []}
        return {"family": family.name, **payload}

    @app.get("/api/v1/samples/{family}/{doc_type}")
    def sample(family: str, doc_type: str):
        path = service.sample_path(_family(app, family), doc_type)
        if path is None:
            raise HTTPException(status_code=404, detail="No sample PDF is available for this slot.")
        return FileResponse(path, media_type="application/pdf", filename=path.name)

    @app.post(
        "/api/v1/cases/{family}/validate",
        response_model=BundleResponse,
        responses={400: {"model": ErrorResponse}, 404: {"model": ErrorResponse}},
    )
    def validate_case(
        family: str,
        files: list[UploadFile] = File(...),
        slots: list[str] = Form(...),
    ) -> dict:
        _check_pairs(files, slots)
        saved = service.save_uploads(files, slots)
        return service.bundle_for(_family(app, family), saved, app.state.client)

    @app.post(
        "/api/v1/cases/{family}/audit",
        response_model=AuditResponse,
        responses={400: {"model": ErrorResponse}, 404: {"model": ErrorResponse}},
    )
    def audit_case(
        family: str,
        files: list[UploadFile] = File(...),
        slots: list[str] = Form(...),
        run_with_available: bool = Form(False),
    ) -> dict:
        _check_pairs(files, slots)
        saved = service.save_uploads(files, slots)
        try:
            with _sessions(app)() as session:
                return service.audit_saved(
                    _family(app, family),
                    saved,
                    app.state.client,
                    session,
                    run_with_available=run_with_available,
                )
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc

    @app.get("/api/v1/findings", response_model=FindingPage)
    def findings(
        family: str | None = None,
        severity: str | None = None,
        rule_id: str | None = None,
        status: str | None = None,
    ) -> dict:
        with _sessions(app)() as session:
            rows = service.list_findings(
                session,
                app.state.families,
                family=family,
                severity=severity,
                rule_id=rule_id,
                status=status,
            )
        return {"findings": rows}

    @app.get(
        "/api/v1/findings/{finding_id}",
        response_model=FindingOut,
        responses={404: {"model": ErrorResponse}},
    )
    def finding(finding_id: str) -> dict:
        with _sessions(app)() as session:
            row = session.get(FindingRow, finding_id)
            if row is None:
                raise HTTPException(status_code=404, detail="Finding not found.")
            return service.finding_dict(session, row)

    @app.patch(
        "/api/v1/findings/{finding_id}",
        response_model=FindingOut,
        responses={404: {"model": ErrorResponse}},
    )
    def review(finding_id: str, body: ReviewUpdate) -> dict:
        with _sessions(app)() as session:
            row = session.get(FindingRow, finding_id)
            if row is None:
                raise HTTPException(status_code=404, detail="Finding not found.")
            row.review_status = body.review_status
            session.commit()
            return service.finding_dict(session, row)

    @app.get(
        "/api/v1/entities/{entity_type}/{entity_id}/risk",
        response_model=RiskOut,
        responses={404: {"model": ErrorResponse}},
    )
    def entity_risk(entity_type: str, entity_id: str, family: str | None = None) -> dict:
        from sqlalchemy import select

        from core.db import RiskScore

        with _sessions(app)() as session:
            query = select(RiskScore).where(
                RiskScore.entity_type == entity_type,
                RiskScore.entity_id == entity_id,
            )
            if family:
                query = query.where(RiskScore.family == family)
            row = session.scalar(query)
            if row is None:
                raise HTTPException(
                    status_code=404, detail="No risk score is stored for this case."
                )
            return {
                "family": row.family,
                "entity_type": row.entity_type,
                "entity_id": row.entity_id,
                "score": row.score,
                "band": row.band,
            }

    @app.get("/api/v1/evaluation/summary", response_model=EvaluationSummary)
    def evaluation() -> dict:
        return service.evaluation_summary()

    @app.get("/api/v1/guide", response_model=GuideResponse)
    def guide() -> dict:
        return service.guide_payload(app.state.families)

    return app


def _family(app: FastAPI, name: str) -> DocumentFamily:
    found = service.family_map(app.state.families).get(name)
    if found is None:
        raise HTTPException(status_code=404, detail=f"Unknown family: {name}")
    return found


def _sessions(app: FastAPI):
    return session_factory(app.state.engine)


def _check_pairs(files: list[UploadFile], slots: list[str]) -> None:
    if len(files) != len(slots):
        raise HTTPException(
            status_code=400,
            detail="Each uploaded file needs one slot name.",
        )


def _live_by_default() -> bool:
    from core.config import load_settings

    provider = load_settings().llm.provider
    return provider in {"groq", "openai"}
