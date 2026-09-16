-- giovernence relational schema (foundation sprint)
-- Postgres + pgvector. Review draft — not yet wired to SQLAlchemy/Alembic.

CREATE EXTENSION IF NOT EXISTS vector;
CREATE EXTENSION IF NOT EXISTS "pgcrypto"; -- gen_random_uuid()

-- ─────────────────────────────────────────────────────────────
-- Projects: top-level container a customer creates via "Project Setup"
-- ─────────────────────────────────────────────────────────────
CREATE TABLE projects (
    id          UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    name        TEXT NOT NULL,
    description TEXT,
    owner_email TEXT NOT NULL,
    created_at  TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at  TIMESTAMPTZ NOT NULL DEFAULT now()
);

-- ─────────────────────────────────────────────────────────────
-- ModelEndpoints: the target LLM(s) under governance for a project
-- ─────────────────────────────────────────────────────────────
CREATE TABLE model_endpoints (
    id                UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    project_id        UUID NOT NULL REFERENCES projects(id) ON DELETE CASCADE,
    name              TEXT NOT NULL,
    provider          TEXT NOT NULL,        -- e.g. 'openai', 'grok', 'self-hosted'
    model_identifier  TEXT NOT NULL,        -- provider-side model name/id
    endpoint_url      TEXT,
    credential_ref    TEXT,                 -- pointer to secret store, never the raw key
    created_at        TIMESTAMPTZ NOT NULL DEFAULT now()
);

-- ─────────────────────────────────────────────────────────────
-- OwnershipVerification: must succeed before an endpoint can be red-teamed
-- ─────────────────────────────────────────────────────────────
CREATE TABLE ownership_verifications (
    id                UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    model_endpoint_id UUID NOT NULL REFERENCES model_endpoints(id) ON DELETE CASCADE,
    method            TEXT NOT NULL,        -- e.g. 'dns_txt', 'signed_challenge', 'api_key_scope'
    status            TEXT NOT NULL DEFAULT 'pending', -- pending | verified | failed
    verification_token TEXT,
    evidence          JSONB,
    verified_at       TIMESTAMPTZ,
    created_at        TIMESTAMPTZ NOT NULL DEFAULT now()
);

-- ─────────────────────────────────────────────────────────────
-- SystemPromptVersions: versioned system prompts constraints are extracted from
-- ─────────────────────────────────────────────────────────────
CREATE TABLE system_prompt_versions (
    id              UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    project_id      UUID NOT NULL REFERENCES projects(id) ON DELETE CASCADE,
    version_number  INTEGER NOT NULL,
    prompt_text     TEXT NOT NULL,
    is_active       BOOLEAN NOT NULL DEFAULT true,
    created_at      TIMESTAMPTZ NOT NULL DEFAULT now(),
    UNIQUE (project_id, version_number)
);

-- ─────────────────────────────────────────────────────────────
-- Constraints: individual rules extracted from a system prompt version
-- ─────────────────────────────────────────────────────────────
CREATE TABLE constraints (
    id                        UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    system_prompt_version_id  UUID NOT NULL REFERENCES system_prompt_versions(id) ON DELETE CASCADE,
    description               TEXT NOT NULL,
    category                  TEXT,          -- e.g. 'safety', 'scope', 'tone', 'disclosure'
    weight                    NUMERIC,       -- nullable; customer-configurable, no baked-in composite score
    created_at                TIMESTAMPTZ NOT NULL DEFAULT now()
);

-- ─────────────────────────────────────────────────────────────
-- Jobs: background work units (integrity check / red-team battery / fingerprint)
-- ─────────────────────────────────────────────────────────────
CREATE TABLE jobs (
    id           UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    project_id   UUID NOT NULL REFERENCES projects(id) ON DELETE CASCADE,
    job_type     TEXT NOT NULL,   -- 'integrity_check' | 'red_team_battery' | 'fingerprint_extraction'
    status       TEXT NOT NULL DEFAULT 'queued', -- queued | running | succeeded | failed
    config       JSONB,
    created_at   TIMESTAMPTZ NOT NULL DEFAULT now(),
    started_at   TIMESTAMPTZ,
    completed_at TIMESTAMPTZ
);

-- ─────────────────────────────────────────────────────────────
-- TestCases: inputs sent to the target model (red-team-generated, or real traffic)
-- ─────────────────────────────────────────────────────────────
CREATE TABLE test_cases (
    id           UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    job_id       UUID NOT NULL REFERENCES jobs(id) ON DELETE CASCADE,
    source       TEXT NOT NULL,   -- 'red_team' | 'production' | 'manual'
    attack_type  TEXT,            -- populated when source = 'red_team'
    input_text   TEXT NOT NULL,
    created_at   TIMESTAMPTZ NOT NULL DEFAULT now()
);

-- ─────────────────────────────────────────────────────────────
-- ModelResponses: what the target model returned for a test case
-- ─────────────────────────────────────────────────────────────
CREATE TABLE model_responses (
    id                UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    test_case_id      UUID NOT NULL REFERENCES test_cases(id) ON DELETE CASCADE,
    model_endpoint_id UUID NOT NULL REFERENCES model_endpoints(id) ON DELETE CASCADE,
    response_text     TEXT NOT NULL,
    embedding         VECTOR(1536), -- reserved for fingerprinting; unused this sprint
    latency_ms        INTEGER,
    created_at        TIMESTAMPTZ NOT NULL DEFAULT now()
);

-- ─────────────────────────────────────────────────────────────
-- JudgeRuns: one LLM-as-judge evaluation of a model response
-- ─────────────────────────────────────────────────────────────
CREATE TABLE judge_runs (
    id                UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    model_response_id UUID NOT NULL REFERENCES model_responses(id) ON DELETE CASCADE,
    judge_model       TEXT NOT NULL,
    raw_output        JSONB NOT NULL,   -- full structured judge output, for auditability
    created_at        TIMESTAMPTZ NOT NULL DEFAULT now()
);

-- ─────────────────────────────────────────────────────────────
-- Violations: per-constraint judge verdict for a JudgeRun (relational, not JSON blob)
-- ─────────────────────────────────────────────────────────────
CREATE TABLE violations (
    id            UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    judge_run_id  UUID NOT NULL REFERENCES judge_runs(id) ON DELETE CASCADE,
    constraint_id UUID NOT NULL REFERENCES constraints(id) ON DELETE CASCADE,
    violated      BOOLEAN NOT NULL,
    evidence_span TEXT,
    reasoning     TEXT,
    severity      TEXT,   -- e.g. 'low' | 'medium' | 'high' | 'critical'
    created_at    TIMESTAMPTZ NOT NULL DEFAULT now()
);

-- ─────────────────────────────────────────────────────────────
-- EvalExamples: labeled examples for benchmarking judge accuracy (ensemble/eval harness)
-- ─────────────────────────────────────────────────────────────
CREATE TABLE eval_examples (
    id             UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    input_text     TEXT NOT NULL,
    response_text  TEXT NOT NULL,
    expected_label BOOLEAN NOT NULL,  -- ground-truth: does this violate the paired constraint?
    category       TEXT,
    notes          TEXT,
    created_at     TIMESTAMPTZ NOT NULL DEFAULT now()
);

-- ─────────────────────────────────────────────────────────────
-- Indexes for common access patterns
-- ─────────────────────────────────────────────────────────────
CREATE INDEX idx_model_endpoints_project_id ON model_endpoints(project_id);
CREATE INDEX idx_ownership_verifications_endpoint_id ON ownership_verifications(model_endpoint_id);
CREATE INDEX idx_system_prompt_versions_project_id ON system_prompt_versions(project_id);
CREATE INDEX idx_constraints_prompt_version_id ON constraints(system_prompt_version_id);
CREATE INDEX idx_jobs_project_id ON jobs(project_id);
CREATE INDEX idx_test_cases_job_id ON test_cases(job_id);
CREATE INDEX idx_model_responses_test_case_id ON model_responses(test_case_id);
CREATE INDEX idx_model_responses_endpoint_id ON model_responses(model_endpoint_id);
CREATE INDEX idx_judge_runs_model_response_id ON judge_runs(model_response_id);
CREATE INDEX idx_violations_judge_run_id ON violations(judge_run_id);
CREATE INDEX idx_violations_constraint_id ON violations(constraint_id);
