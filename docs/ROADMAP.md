# Roadmap & progress

Target: the full Sentinel Layer platform. This branch delivers roughly **60%**.

## Done

### Foundation
- [x] Relational schema (`db/schema.sql`) → SQLAlchemy 2.0 models (`sentinel/db/models.py`)
- [x] Portable types (JSONB/pgvector on Postgres, JSON on SQLite)
- [x] First Alembic migration (`migrations/versions/0001_initial_schema.py`), verified up/down + `alembic check`
- [x] Provider abstraction: OpenAI-compatible HTTP client, deterministic simulated models
- [x] `credential_ref` resolution (`env:` scheme)

### Red-teaming
- [x] Attack generator: 4 categories × templates × objectives × mutators, deterministic/seeded
- [x] Objectives derived from a project's prohibitive constraints
- [x] Success detectors: refusal detection, n-gram system-prompt leakage
- [x] Battery runner with per-category attack-success rate (ASR)
- [x] Regression tracking between runs/model versions (per-category deltas, newly failing cases)
- [x] Ownership-verification gate enforced before any red-team job

### Output integrity
- [x] Rule-based constraint extraction with category + polarity
- [x] Heuristic judge (explainable, evidence spans, severities)
- [x] LLM-as-judge (any `ModelClient`, structured JSON verdicts)
- [x] Ensemble judge (majority vote, fail-closed on ties)
- [x] Judge-accuracy harness (precision / recall / F1 vs. labeled examples)
- [x] Verdicts persisted relationally (`judge_runs` + `violations`)

### Fingerprinting
- [x] Sentence-transformer embedder + offline hashing fallback
- [x] Versioned probe set (16 probes across 8 behavioral categories)
- [x] Signatures: per-probe embeddings, centroid, stylometrics; persisted in `fingerprint_signatures`
- [x] Clone detection: per-probe + centroid cosine, thresholded; audit rows in `fingerprint_comparisons`

### Interfaces
- [x] Flask REST API covering projects, endpoints, ownership, prompts, jobs, comparisons
- [x] CLI: `demo`, `redteam`, `serve`
- [x] 27 tests (unit + service + API)

## Remaining (~40%)

1. **Async execution** — Celery + Redis workers calling `services.jobs.run_job`; API returns
   `202` + polling. Retry/timeout policy per job type.
2. **Ownership verifiers** — `dns_txt` (dnspython) and `api_key_scope`; `signed_challenge`
   exists but needs an end-to-end test against a real endpoint.
3. **Auth & multi-tenancy** — users/orgs tables, API keys, per-project authorization
   (schema.md open question #4).
4. **Smarter red-teaming** — LLM-driven attack mutation (attacker model iterates on failed
   attempts), multi-turn attacks, LLM judge for ambiguous "non-refusal" detections
   (current detector over-flags deflections).
5. **Constraint extraction via LLM** for free-prose system prompts; customer-editable
   constraint weights + read-time weighted scoring.
6. **Fingerprinting calibration** — benchmark thresholds on real model families with
   `all-MiniLM-L6-v2`/larger encoders, ROC on known clone/non-clone pairs; pgvector ANN
   index for "find nearest known model" search across signatures; reconcile the
   `model_responses.embedding` 1536-dim column with the 384-dim encoder (schema.md Q2).
7. **Production traffic ingestion** for integrity checks (`test_cases.source = 'production'`).
8. **Dashboard** — regression trends over model versions, violation heatmaps, clone alerts.
9. **Ops** — Dockerfile/compose (Postgres+pgvector, Redis), CI, structured logging, rate
   limiting on outbound model calls.
