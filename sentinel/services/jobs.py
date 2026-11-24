"""DB-backed job execution for the three pillars.

Jobs currently run synchronously in-process via :func:`run_job`. The Celery
worker tier (see docs/ROADMAP.md) will call the same ``run_job`` function, so
the job logic does not change when execution moves off the request path.
"""

from __future__ import annotations

import uuid
from datetime import datetime, timezone
from typing import Callable

from sqlalchemy import select
from sqlalchemy.orm import Session

from sentinel.config import get_settings
from sentinel.db.models import (
    Constraint,
    FingerprintComparison,
    FingerprintSignature,
    Job,
    JudgeRun,
    ModelEndpoint,
    ModelResponse,
    SystemPromptVersion,
    TestCase,
    Violation,
)
from sentinel.fingerprint import Signature, build_signature, compare_signatures, get_embedder
from sentinel.fingerprint.embedders import Embedder
from sentinel.integrity import ConstraintRef, HeuristicJudge, Judge, extract_constraints
from sentinel.providers import ModelClient, client_for_endpoint
from sentinel.redteam import AttackCategory, AttackGenerator, detect
from sentinel.redteam.regression import case_key, compare_summaries
from sentinel.services.ownership import require_verified

JOB_TYPES = {"integrity_check", "red_team_battery", "fingerprint_extraction"}

ClientFactory = Callable[[ModelEndpoint], ModelClient]


def _now() -> datetime:
    return datetime.now(timezone.utc)


# ───────────────────────── system prompts / constraints ─────────────────────────


def add_system_prompt_version(
    session: Session, project_id: uuid.UUID, prompt_text: str, extract: bool = True
) -> SystemPromptVersion:
    """Create the next prompt version, deactivate older ones, and extract constraints."""
    existing = session.scalars(
        select(SystemPromptVersion).where(SystemPromptVersion.project_id == project_id)
    ).all()
    for v in existing:
        v.is_active = False
    version = SystemPromptVersion(
        project_id=project_id,
        version_number=max((v.version_number for v in existing), default=0) + 1,
        prompt_text=prompt_text,
        is_active=True,
    )
    session.add(version)
    session.flush()
    if extract:
        for c in extract_constraints(prompt_text):
            session.add(
                Constraint(
                    system_prompt_version_id=version.id,
                    description=c.description,
                    category=c.category,
                )
            )
        session.flush()
    return version


def active_prompt(session: Session, project_id: uuid.UUID) -> SystemPromptVersion | None:
    return session.scalars(
        select(SystemPromptVersion).where(
            SystemPromptVersion.project_id == project_id, SystemPromptVersion.is_active.is_(True)
        )
    ).first()


# ───────────────────────────────── jobs ─────────────────────────────────


def create_job(session: Session, project_id: uuid.UUID, job_type: str, config: dict) -> Job:
    if job_type not in JOB_TYPES:
        raise ValueError(f"unknown job_type {job_type!r}")
    if "model_endpoint_id" not in config:
        raise ValueError("config.model_endpoint_id is required")
    job = Job(project_id=project_id, job_type=job_type, status="queued", config=config)
    session.add(job)
    session.flush()
    return job


def run_job(
    session: Session,
    job: Job,
    client_factory: ClientFactory = client_for_endpoint,
    judge: Judge | None = None,
    embedder: Embedder | None = None,
) -> dict:
    """Execute a job and persist all artefacts. Returns the job's result summary."""
    endpoint = session.get(ModelEndpoint, uuid.UUID(str(job.config["model_endpoint_id"])))
    if endpoint is None or endpoint.project_id != job.project_id:
        return _fail(session, job, "model endpoint not found in this project")

    job.status, job.started_at = "running", _now()
    session.flush()
    try:
        if job.job_type == "red_team_battery":
            require_verified(session, endpoint.id)
            result = _run_red_team(session, job, endpoint, client_factory(endpoint))
        elif job.job_type == "integrity_check":
            result = _run_integrity(session, job, endpoint, client_factory(endpoint), judge)
        else:
            result = _run_fingerprint(session, job, endpoint, client_factory(endpoint), embedder)
    except Exception as e:  # noqa: BLE001 - job failures are recorded, not raised
        return _fail(session, job, f"{type(e).__name__}: {e}")

    job.status, job.completed_at = "succeeded", _now()
    job.config = {**job.config, "result": result}
    session.flush()
    return result


def _fail(session: Session, job: Job, msg: str) -> dict:
    job.status, job.error, job.completed_at = "failed", msg, _now()
    session.flush()
    return {"error": msg}


def _run_red_team(session, job, endpoint, client) -> dict:
    prompt = active_prompt(session, job.project_id)
    sp_text = prompt.prompt_text if prompt else None
    cfg = job.config
    objectives = None
    if cfg.get("objectives_from_constraints") and prompt:
        objectives = AttackGenerator.objectives_from_constraints(
            c.description for c in prompt.constraints
        ) or None
    gen = AttackGenerator(
        categories=[AttackCategory(c) for c in cfg["categories"]] if cfg.get("categories") else None,
        objectives=cfg.get("objectives") or objectives,
        mutators=cfg.get("mutators"),
        seed=cfg.get("seed", 0),
    )
    stats: dict[str, dict] = {}
    failures: list[str] = []
    for case in gen.generate(cfg.get("max_cases")):
        completion = client.generate(sp_text, case.text)
        det = detect(case, completion.text, sp_text)
        tc = TestCase(
            job_id=job.id,
            source="red_team",
            attack_type=case.category.value,
            input_text=case.text,
            attack_succeeded=det.attack_succeeded,
            detector_notes=det.notes,
        )
        session.add(tc)
        session.flush()
        session.add(
            ModelResponse(
                test_case_id=tc.id,
                model_endpoint_id=endpoint.id,
                response_text=completion.text,
                latency_ms=completion.latency_ms,
            )
        )
        s = stats.setdefault(case.category.value, {"total": 0, "succeeded": 0})
        s["total"] += 1
        s["succeeded"] += int(det.attack_succeeded)
        if det.attack_succeeded:
            failures.append(case_key(case.template_id, case.mutator, case.objective))
    total = sum(s["total"] for s in stats.values())
    succeeded = sum(s["succeeded"] for s in stats.values())
    for s in stats.values():
        s["attack_success_rate"] = round(s["succeeded"] / s["total"], 4) if s["total"] else 0.0
    session.flush()
    return {
        "model": f"{endpoint.name}@{endpoint.version_label or endpoint.model_identifier}",
        "model_endpoint_id": str(endpoint.id),
        "system_prompt_version": prompt.version_number if prompt else None,
        "total_cases": total,
        "attack_success_rate": round(succeeded / total, 4) if total else 0.0,
        "by_category": dict(sorted(stats.items())),
        "failing_cases": sorted(failures),
    }


def _run_integrity(session, job, endpoint, client, judge: Judge | None) -> dict:
    prompt = active_prompt(session, job.project_id)
    if prompt is None:
        raise ValueError("project has no active system prompt version")
    inputs: list[str] = job.config.get("inputs") or []
    if not inputs:
        raise ValueError("integrity_check requires config.inputs (list of user inputs)")
    judge = judge or HeuristicJudge()
    constraints = list(prompt.constraints)
    refs = [ConstraintRef(str(c.id), c.description, c.category) for c in constraints]
    violation_counts: dict[str, int] = {str(c.id): 0 for c in constraints}
    for text in inputs:
        tc = TestCase(job_id=job.id, source=job.config.get("source", "manual"), input_text=text)
        session.add(tc)
        session.flush()
        completion = client.generate(prompt.prompt_text, text)
        resp = ModelResponse(
            test_case_id=tc.id,
            model_endpoint_id=endpoint.id,
            response_text=completion.text,
            latency_ms=completion.latency_ms,
        )
        session.add(resp)
        session.flush()
        verdicts = judge.judge(text, completion.text, refs, prompt.prompt_text)
        run = JudgeRun(model_response_id=resp.id, judge_model=judge.name, raw_output=judge.raw_output(verdicts))
        session.add(run)
        session.flush()
        for v in verdicts:
            session.add(
                Violation(
                    judge_run_id=run.id,
                    constraint_id=uuid.UUID(v.constraint_id),
                    violated=v.violated,
                    evidence_span=v.evidence_span,
                    reasoning=v.reasoning,
                    severity=v.severity,
                )
            )
            violation_counts[v.constraint_id] += int(v.violated)
    session.flush()
    return {
        "system_prompt_version": prompt.version_number,
        "judge": judge.name,
        "responses_judged": len(inputs),
        "constraints": [
            {
                "constraint_id": str(c.id),
                "description": c.description,
                "category": c.category,
                "violations": violation_counts[str(c.id)],
                "violation_rate": round(violation_counts[str(c.id)] / len(inputs), 4),
            }
            for c in constraints
        ],
        "total_violations": sum(violation_counts.values()),
    }


def _run_fingerprint(session, job, endpoint, client, embedder: Embedder | None) -> dict:
    embedder = embedder or get_embedder(job.config.get("embedding_model"))
    version = job.config.get("probe_set_version", "v1")
    sig = build_signature(client, embedder, probe_set_version=version)
    row = FingerprintSignature(
        model_endpoint_id=endpoint.id,
        job_id=job.id,
        embedding_model=embedder.name,
        probe_set_version=version,
        dimension=sig.dimension,
        centroid=sig.centroid.tolist(),
        probe_embeddings=sig.probe_embeddings_dict(),
        stylometrics=sig.stylometrics,
    )
    session.add(row)
    session.flush()
    return {
        "signature_id": str(row.id),
        "embedding_model": embedder.name,
        "probe_set_version": version,
        "dimension": sig.dimension,
        "stylometrics": sig.stylometrics,
    }


# ─────────────────────────── cross-run analytics ───────────────────────────


def compare_red_team_jobs(session: Session, baseline_job_id, candidate_job_id, tolerance=None) -> dict:
    base, cand = session.get(Job, baseline_job_id), session.get(Job, candidate_job_id)
    for j in (base, cand):
        if j is None or j.job_type != "red_team_battery" or j.status != "succeeded":
            raise ValueError("both jobs must be succeeded red_team_battery jobs")
    b, c = base.config["result"], cand.config["result"]
    report = compare_summaries(
        b,
        c,
        tolerance=get_settings().regression_tolerance if tolerance is None else tolerance,
        baseline_failures=set(b.get("failing_cases", [])),
        candidate_failures=set(c.get("failing_cases", [])),
    )
    return report.to_dict()


def _signature_from_row(session: Session, row: FingerprintSignature) -> Signature:
    ep = session.get(ModelEndpoint, row.model_endpoint_id)
    return Signature.from_stored(
        model_name=ep.name if ep else str(row.model_endpoint_id),
        embedder_name=row.embedding_model,
        probe_set_version=row.probe_set_version,
        probe_embeddings=row.probe_embeddings,
        stylometrics=row.stylometrics,
    )


def compare_fingerprints(session: Session, reference_id, candidate_id, threshold=None) -> dict:
    ref_row = session.get(FingerprintSignature, reference_id)
    cand_row = session.get(FingerprintSignature, candidate_id)
    if ref_row is None or cand_row is None:
        raise ValueError("signature not found")
    threshold = get_settings().clone_threshold if threshold is None else threshold
    result = compare_signatures(
        _signature_from_row(session, ref_row), _signature_from_row(session, cand_row), threshold
    )
    d = result.to_dict()
    session.add(
        FingerprintComparison(
            reference_signature_id=ref_row.id,
            candidate_signature_id=cand_row.id,
            centroid_similarity=result.centroid_similarity,
            mean_probe_similarity=result.mean_probe_similarity,
            threshold=threshold,
            likely_clone=result.likely_clone,
            details={"per_probe": d["per_probe"]},
        )
    )
    session.flush()
    return d
