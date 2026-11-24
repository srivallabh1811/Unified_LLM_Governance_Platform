"""Flask REST API.

Endpoints (all JSON):

  POST   /projects
  GET    /projects/<id>
  POST   /projects/<id>/endpoints
  POST   /endpoints/<id>/ownership            {method}           → challenge token
  POST   /ownership/<id>/confirm              {evidence?}
  POST   /projects/<id>/system-prompts        {prompt_text}      → version + extracted constraints
  GET    /projects/<id>/system-prompts/active
  POST   /projects/<id>/jobs                  {job_type, config} → runs synchronously (for now)
  GET    /jobs/<id>
  GET    /jobs/<id>/test-cases
  POST   /red-team/compare                    {baseline_job_id, candidate_job_id, tolerance?}
  POST   /fingerprints/compare                {reference_signature_id, candidate_signature_id, threshold?}
  GET    /health

Auth is not implemented yet (schema.md open question #4).
"""

from __future__ import annotations

import uuid
from typing import Any

from flask import Flask, g, jsonify, request
from pydantic import BaseModel, Field, ValidationError
from sqlalchemy import select

from sentinel.db import init_db, make_engine, make_session_factory
from sentinel.db.models import (
    Job,
    ModelEndpoint,
    OwnershipVerification,
    Project,
    TestCase,
)
from sentinel.services import jobs as job_svc
from sentinel.services import ownership as own_svc

# ───────────────────────────── request schemas ─────────────────────────────


class ProjectIn(BaseModel):
    name: str = Field(min_length=1)
    owner_email: str = Field(min_length=3)
    description: str | None = None


class EndpointIn(BaseModel):
    name: str
    provider: str
    model_identifier: str
    version_label: str | None = None
    endpoint_url: str | None = None
    credential_ref: str | None = None


class OwnershipIn(BaseModel):
    method: str


class ConfirmIn(BaseModel):
    evidence: dict[str, Any] | None = None


class PromptIn(BaseModel):
    prompt_text: str = Field(min_length=1)


class JobIn(BaseModel):
    job_type: str
    config: dict[str, Any]


class RedTeamCompareIn(BaseModel):
    baseline_job_id: uuid.UUID
    candidate_job_id: uuid.UUID
    tolerance: float | None = None


class FingerprintCompareIn(BaseModel):
    reference_signature_id: uuid.UUID
    candidate_signature_id: uuid.UUID
    threshold: float | None = None


# ───────────────────────────── serializers ─────────────────────────────


def _project(p: Project) -> dict:
    return {
        "id": str(p.id),
        "name": p.name,
        "description": p.description,
        "owner_email": p.owner_email,
        "created_at": p.created_at.isoformat(),
    }


def _endpoint(e: ModelEndpoint) -> dict:
    return {
        "id": str(e.id),
        "project_id": str(e.project_id),
        "name": e.name,
        "provider": e.provider,
        "model_identifier": e.model_identifier,
        "version_label": e.version_label,
        "endpoint_url": e.endpoint_url,
        "ownership_verified": any(v.status == "verified" for v in e.ownership_verifications),
    }


def _verification(v: OwnershipVerification) -> dict:
    return {
        "id": str(v.id),
        "model_endpoint_id": str(v.model_endpoint_id),
        "method": v.method,
        "status": v.status,
        "verification_token": v.verification_token,
        "evidence": v.evidence,
        "verified_at": v.verified_at.isoformat() if v.verified_at else None,
    }


def _job(j: Job) -> dict:
    cfg = dict(j.config or {})
    result = cfg.pop("result", None)
    return {
        "id": str(j.id),
        "project_id": str(j.project_id),
        "job_type": j.job_type,
        "status": j.status,
        "config": cfg,
        "result": result,
        "error": j.error,
        "created_at": j.created_at.isoformat() if j.created_at else None,
        "started_at": j.started_at.isoformat() if j.started_at else None,
        "completed_at": j.completed_at.isoformat() if j.completed_at else None,
    }


# ───────────────────────────── app factory ─────────────────────────────


class ApiError(Exception):
    def __init__(self, status: int, message: str, details: Any = None) -> None:
        super().__init__(message)
        self.status, self.message, self.details = status, message, details


def _body(model: type[BaseModel]):
    try:
        return model.model_validate(request.get_json(force=True, silent=False) or {})
    except ValidationError as e:
        raise ApiError(422, "validation error", e.errors(include_url=False)) from e
    except Exception as e:  # malformed JSON
        raise ApiError(400, "request body must be JSON") from e


def _get(model, raw_id: str):
    try:
        obj = g.db.get(model, uuid.UUID(raw_id))
    except ValueError:
        obj = None
    if obj is None:
        raise ApiError(404, f"{model.__name__} not found")
    return obj


def create_app(database_url: str | None = None, client_factory=None, create_tables: bool = True) -> Flask:
    app = Flask(__name__)
    engine = make_engine(database_url)
    if create_tables:
        init_db(engine)
    factory = make_session_factory(engine)
    app.config["SESSION_FACTORY"] = factory
    run_kwargs = {"client_factory": client_factory} if client_factory else {}

    @app.before_request
    def _open_session():
        g.db = factory()

    @app.teardown_request
    def _close_session(exc):
        db = g.pop("db", None)
        if db is None:
            return
        if exc is None:
            db.commit()
        else:
            db.rollback()
        db.close()

    @app.errorhandler(ApiError)
    def _api_error(e: ApiError):
        g.db.rollback()
        payload = {"error": e.message}
        if e.details is not None:
            payload["details"] = e.details
        return jsonify(payload), e.status

    @app.get("/health")
    def health():
        return {"status": "ok"}

    @app.post("/projects")
    def create_project():
        data = _body(ProjectIn)
        p = Project(**data.model_dump())
        g.db.add(p)
        g.db.flush()
        return _project(p), 201

    @app.get("/projects/<pid>")
    def get_project(pid):
        p = _get(Project, pid)
        return {**_project(p), "endpoints": [_endpoint(e) for e in p.model_endpoints]}

    @app.post("/projects/<pid>/endpoints")
    def create_endpoint(pid):
        p = _get(Project, pid)
        data = _body(EndpointIn)
        e = ModelEndpoint(project_id=p.id, **data.model_dump())
        g.db.add(e)
        g.db.flush()
        g.db.refresh(e)
        return _endpoint(e), 201

    @app.post("/endpoints/<eid>/ownership")
    def start_verification(eid):
        e = _get(ModelEndpoint, eid)
        data = _body(OwnershipIn)
        try:
            v = own_svc.issue_challenge(g.db, e, data.method)
        except ValueError as err:
            raise ApiError(422, str(err)) from err
        return _verification(v), 201

    @app.post("/ownership/<vid>/confirm")
    def confirm_verification(vid):
        v = _get(OwnershipVerification, vid)
        data = _body(ConfirmIn)
        try:
            v = own_svc.confirm(g.db, v, evidence=data.evidence)
        except NotImplementedError as err:
            raise ApiError(501, str(err)) from err
        return _verification(v)

    @app.post("/projects/<pid>/system-prompts")
    def add_prompt(pid):
        p = _get(Project, pid)
        data = _body(PromptIn)
        v = job_svc.add_system_prompt_version(g.db, p.id, data.prompt_text)
        g.db.refresh(v)
        return _prompt(v), 201

    @app.get("/projects/<pid>/system-prompts/active")
    def get_active_prompt(pid):
        p = _get(Project, pid)
        v = job_svc.active_prompt(g.db, p.id)
        if v is None:
            raise ApiError(404, "no active system prompt")
        return _prompt(v)

    def _prompt(v):
        return {
            "id": str(v.id),
            "version_number": v.version_number,
            "prompt_text": v.prompt_text,
            "is_active": v.is_active,
            "constraints": [
                {"id": str(c.id), "description": c.description, "category": c.category,
                 "weight": float(c.weight) if c.weight is not None else None}
                for c in v.constraints
            ],
        }

    @app.post("/projects/<pid>/jobs")
    def create_and_run_job(pid):
        p = _get(Project, pid)
        data = _body(JobIn)
        try:
            job = job_svc.create_job(g.db, p.id, data.job_type, data.config)
        except ValueError as err:
            raise ApiError(422, str(err)) from err
        job_svc.run_job(g.db, job, **run_kwargs)
        return _job(job), 201

    @app.get("/jobs/<jid>")
    def get_job(jid):
        return _job(_get(Job, jid))

    @app.get("/jobs/<jid>/test-cases")
    def get_test_cases(jid):
        j = _get(Job, jid)
        rows = g.db.scalars(select(TestCase).where(TestCase.job_id == j.id)).all()
        return {
            "job_id": str(j.id),
            "test_cases": [
                {
                    "id": str(t.id),
                    "source": t.source,
                    "attack_type": t.attack_type,
                    "input_text": t.input_text,
                    "attack_succeeded": t.attack_succeeded,
                    "detector_notes": t.detector_notes,
                    "responses": [
                        {
                            "response_text": r.response_text,
                            "latency_ms": r.latency_ms,
                            "violations": [
                                {
                                    "constraint_id": str(v.constraint_id),
                                    "violated": v.violated,
                                    "severity": v.severity,
                                    "evidence_span": v.evidence_span,
                                    "reasoning": v.reasoning,
                                }
                                for run in r.judge_runs
                                for v in run.violations
                            ],
                        }
                        for r in t.responses
                    ],
                }
                for t in rows
            ],
        }

    @app.post("/red-team/compare")
    def compare_red_team():
        data = _body(RedTeamCompareIn)
        try:
            return job_svc.compare_red_team_jobs(
                g.db, data.baseline_job_id, data.candidate_job_id, data.tolerance
            )
        except ValueError as err:
            raise ApiError(422, str(err)) from err

    @app.post("/fingerprints/compare")
    def compare_fp():
        data = _body(FingerprintCompareIn)
        try:
            return job_svc.compare_fingerprints(
                g.db, data.reference_signature_id, data.candidate_signature_id, data.threshold
            )
        except ValueError as err:
            raise ApiError(422, str(err)) from err

    return app
