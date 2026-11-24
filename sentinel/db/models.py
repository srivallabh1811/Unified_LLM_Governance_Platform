"""SQLAlchemy models mirroring ``db/schema.sql``.

Types are kept portable so the same models run on Postgres (production) and
SQLite (tests / local dev):

* ``JSONB`` columns use ``JSON`` with a Postgres ``JSONB`` variant.
* Embedding columns use :class:`EmbeddingType`, which maps to ``pgvector``'s
  ``VECTOR`` on Postgres when the ``pgvector`` package is installed and to a
  JSON float list everywhere else.

Additions beyond the reviewed DDL (see docs/schema.md "Sprint 2 additions"):

* ``model_endpoints.version_label`` — lets red-team runs be compared across
  model updates for regression tracking.
* ``test_cases.attack_succeeded`` / ``test_cases.detector_notes`` — the
  red-team detector verdict for the response.
* ``fingerprint_signatures`` — the deferred Signature table.
"""

from __future__ import annotations

import uuid
from datetime import datetime, timezone
from typing import Any, Optional

from sqlalchemy import (
    JSON,
    Boolean,
    DateTime,
    Float,
    ForeignKey,
    Integer,
    Numeric,
    String,
    Text,
    TypeDecorator,
    UniqueConstraint,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, relationship

JSONType = JSON().with_variant(JSONB(), "postgresql")


def _now() -> datetime:
    return datetime.now(timezone.utc)


class EmbeddingType(TypeDecorator):
    """Float vector stored as pgvector on Postgres, JSON elsewhere."""

    impl = JSON
    cache_ok = True

    def __init__(self, dim: int | None = None, *args: Any, **kwargs: Any) -> None:
        super().__init__(*args, **kwargs)
        self.dim = dim

    def load_dialect_impl(self, dialect):  # pragma: no cover - dialect specific
        if dialect.name == "postgresql":
            try:
                from pgvector.sqlalchemy import Vector

                return dialect.type_descriptor(Vector(self.dim))
            except ImportError:
                pass
        return dialect.type_descriptor(JSON())

    def process_bind_param(self, value, dialect):
        if value is None:
            return None
        return [float(x) for x in value]

    def process_result_value(self, value, dialect):
        if value is None:
            return None
        return [float(x) for x in value]


class Base(DeclarativeBase):
    pass


class Project(Base):
    __tablename__ = "projects"

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    name: Mapped[str] = mapped_column(Text, nullable=False)
    description: Mapped[Optional[str]] = mapped_column(Text)
    owner_email: Mapped[str] = mapped_column(Text, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_now)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=_now, onupdate=_now
    )

    model_endpoints: Mapped[list["ModelEndpoint"]] = relationship(
        back_populates="project", cascade="all, delete-orphan"
    )
    system_prompt_versions: Mapped[list["SystemPromptVersion"]] = relationship(
        back_populates="project", cascade="all, delete-orphan"
    )
    jobs: Mapped[list["Job"]] = relationship(back_populates="project", cascade="all, delete-orphan")


class ModelEndpoint(Base):
    __tablename__ = "model_endpoints"

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    project_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("projects.id", ondelete="CASCADE"), nullable=False, index=True
    )
    name: Mapped[str] = mapped_column(Text, nullable=False)
    provider: Mapped[str] = mapped_column(Text, nullable=False)
    model_identifier: Mapped[str] = mapped_column(Text, nullable=False)
    version_label: Mapped[Optional[str]] = mapped_column(Text)
    endpoint_url: Mapped[Optional[str]] = mapped_column(Text)
    credential_ref: Mapped[Optional[str]] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_now)

    project: Mapped[Project] = relationship(back_populates="model_endpoints")
    ownership_verifications: Mapped[list["OwnershipVerification"]] = relationship(
        back_populates="model_endpoint", cascade="all, delete-orphan"
    )


class OwnershipVerification(Base):
    __tablename__ = "ownership_verifications"

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    model_endpoint_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("model_endpoints.id", ondelete="CASCADE"), nullable=False, index=True
    )
    method: Mapped[str] = mapped_column(Text, nullable=False)
    status: Mapped[str] = mapped_column(Text, nullable=False, default="pending")
    verification_token: Mapped[Optional[str]] = mapped_column(Text)
    evidence: Mapped[Optional[dict]] = mapped_column(JSONType)
    verified_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_now)

    model_endpoint: Mapped[ModelEndpoint] = relationship(back_populates="ownership_verifications")


class SystemPromptVersion(Base):
    __tablename__ = "system_prompt_versions"
    __table_args__ = (UniqueConstraint("project_id", "version_number"),)

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    project_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("projects.id", ondelete="CASCADE"), nullable=False, index=True
    )
    version_number: Mapped[int] = mapped_column(Integer, nullable=False)
    prompt_text: Mapped[str] = mapped_column(Text, nullable=False)
    is_active: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_now)

    project: Mapped[Project] = relationship(back_populates="system_prompt_versions")
    constraints: Mapped[list["Constraint"]] = relationship(
        back_populates="system_prompt_version", cascade="all, delete-orphan"
    )


class Constraint(Base):
    __tablename__ = "constraints"

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    system_prompt_version_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("system_prompt_versions.id", ondelete="CASCADE"), nullable=False, index=True
    )
    description: Mapped[str] = mapped_column(Text, nullable=False)
    category: Mapped[Optional[str]] = mapped_column(Text)
    weight: Mapped[Optional[float]] = mapped_column(Numeric)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_now)

    system_prompt_version: Mapped[SystemPromptVersion] = relationship(back_populates="constraints")


class Job(Base):
    __tablename__ = "jobs"

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    project_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("projects.id", ondelete="CASCADE"), nullable=False, index=True
    )
    job_type: Mapped[str] = mapped_column(Text, nullable=False)
    status: Mapped[str] = mapped_column(Text, nullable=False, default="queued")
    config: Mapped[Optional[dict]] = mapped_column(JSONType)
    error: Mapped[Optional[str]] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_now)
    started_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True))
    completed_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True))

    project: Mapped[Project] = relationship(back_populates="jobs")
    test_cases: Mapped[list["TestCase"]] = relationship(
        back_populates="job", cascade="all, delete-orphan"
    )


class TestCase(Base):
    __tablename__ = "test_cases"
    __test__ = False  # keep pytest from collecting this class

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    job_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("jobs.id", ondelete="CASCADE"), nullable=False, index=True
    )
    source: Mapped[str] = mapped_column(Text, nullable=False)
    attack_type: Mapped[Optional[str]] = mapped_column(Text)
    input_text: Mapped[str] = mapped_column(Text, nullable=False)
    attack_succeeded: Mapped[Optional[bool]] = mapped_column(Boolean)
    detector_notes: Mapped[Optional[str]] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_now)

    job: Mapped[Job] = relationship(back_populates="test_cases")
    responses: Mapped[list["ModelResponse"]] = relationship(
        back_populates="test_case", cascade="all, delete-orphan"
    )


class ModelResponse(Base):
    __tablename__ = "model_responses"

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    test_case_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("test_cases.id", ondelete="CASCADE"), nullable=False, index=True
    )
    model_endpoint_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("model_endpoints.id", ondelete="CASCADE"), nullable=False, index=True
    )
    response_text: Mapped[str] = mapped_column(Text, nullable=False)
    embedding: Mapped[Optional[list[float]]] = mapped_column(EmbeddingType(1536))
    latency_ms: Mapped[Optional[int]] = mapped_column(Integer)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_now)

    test_case: Mapped[TestCase] = relationship(back_populates="responses")
    judge_runs: Mapped[list["JudgeRun"]] = relationship(
        back_populates="model_response", cascade="all, delete-orphan"
    )


class JudgeRun(Base):
    __tablename__ = "judge_runs"

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    model_response_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("model_responses.id", ondelete="CASCADE"), nullable=False, index=True
    )
    judge_model: Mapped[str] = mapped_column(Text, nullable=False)
    raw_output: Mapped[dict] = mapped_column(JSONType, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_now)

    model_response: Mapped[ModelResponse] = relationship(back_populates="judge_runs")
    violations: Mapped[list["Violation"]] = relationship(
        back_populates="judge_run", cascade="all, delete-orphan"
    )


class Violation(Base):
    __tablename__ = "violations"

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    judge_run_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("judge_runs.id", ondelete="CASCADE"), nullable=False, index=True
    )
    constraint_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("constraints.id", ondelete="CASCADE"), nullable=False, index=True
    )
    violated: Mapped[bool] = mapped_column(Boolean, nullable=False)
    evidence_span: Mapped[Optional[str]] = mapped_column(Text)
    reasoning: Mapped[Optional[str]] = mapped_column(Text)
    severity: Mapped[Optional[str]] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_now)

    judge_run: Mapped[JudgeRun] = relationship(back_populates="violations")
    constraint: Mapped[Constraint] = relationship()


class EvalExample(Base):
    __tablename__ = "eval_examples"

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    input_text: Mapped[str] = mapped_column(Text, nullable=False)
    response_text: Mapped[str] = mapped_column(Text, nullable=False)
    expected_label: Mapped[bool] = mapped_column(Boolean, nullable=False)
    category: Mapped[Optional[str]] = mapped_column(Text)
    notes: Mapped[Optional[str]] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_now)


class FingerprintSignature(Base):
    """Behavioral fingerprint of one model endpoint at a point in time."""

    __tablename__ = "fingerprint_signatures"

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    model_endpoint_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("model_endpoints.id", ondelete="CASCADE"), nullable=False, index=True
    )
    job_id: Mapped[Optional[uuid.UUID]] = mapped_column(ForeignKey("jobs.id", ondelete="SET NULL"))
    embedding_model: Mapped[str] = mapped_column(String(200), nullable=False)
    probe_set_version: Mapped[str] = mapped_column(String(50), nullable=False)
    dimension: Mapped[int] = mapped_column(Integer, nullable=False)
    # Mean of the per-probe response embeddings (L2-normalised).
    centroid: Mapped[list[float]] = mapped_column(EmbeddingType(), nullable=False)
    # {probe_id: [floats]} — per-probe embeddings for fine-grained comparison.
    probe_embeddings: Mapped[dict] = mapped_column(JSONType, nullable=False)
    stylometrics: Mapped[Optional[dict]] = mapped_column(JSONType)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_now)


class FingerprintComparison(Base):
    """Result of comparing two signatures (audit trail for clone-detection calls)."""

    __tablename__ = "fingerprint_comparisons"

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    reference_signature_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("fingerprint_signatures.id", ondelete="CASCADE"), nullable=False
    )
    candidate_signature_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("fingerprint_signatures.id", ondelete="CASCADE"), nullable=False
    )
    centroid_similarity: Mapped[float] = mapped_column(Float, nullable=False)
    mean_probe_similarity: Mapped[float] = mapped_column(Float, nullable=False)
    threshold: Mapped[float] = mapped_column(Float, nullable=False)
    likely_clone: Mapped[bool] = mapped_column(Boolean, nullable=False)
    details: Mapped[Optional[dict]] = mapped_column(JSONType)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_now)
