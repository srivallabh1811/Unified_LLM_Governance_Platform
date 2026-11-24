# Schema Review Draft

Foundation-sprint relational schema for giovernence. DDL lives in
[`db/schema.sql`](../db/schema.sql). This doc is the reviewable summary —
SQLAlchemy models + the first Alembic migration are the next step once this
is signed off.

## Entity overview

| Table | Purpose |
|---|---|
| `projects` | Top-level container created via "Project Setup" |
| `model_endpoints` | Target LLM(s) under governance for a project |
| `ownership_verifications` | Proof a customer owns an endpoint — gates red-teaming |
| `system_prompt_versions` | Versioned system prompts constraints are extracted from |
| `constraints` | Individual rules extracted from a system prompt version |
| `jobs` | Background work units: integrity check / red-team battery / fingerprint extraction |
| `test_cases` | Inputs sent to the target model (red-team-generated or real traffic) |
| `model_responses` | What the target model returned for a test case |
| `judge_runs` | One LLM-as-judge evaluation of a model response |
| `violations` | Per-constraint judge verdict for a judge run |
| `eval_examples` | Labeled examples for benchmarking judge accuracy |

## Relationships

```
projects
 ├─< model_endpoints ──< ownership_verifications
 ├─< system_prompt_versions ──< constraints
 └─< jobs ──< test_cases ──< model_responses ──< judge_runs ──< violations >── constraints
```

`eval_examples` is standalone — it isn't tied to a project; it's a shared
labeled set for measuring judge accuracy across the eval harness.

## Design decisions carried into the DDL

- **`violations` and `judge_runs` are separate relational rows, not JSON
  blobs.** `judge_runs.raw_output` keeps the full structured judge response
  for audit, but each constraint verdict is also broken out into its own
  `violations` row so violations can be queried/filtered/aggregated across
  system prompt versions without parsing JSON.
- **No baked-in composite score.** `constraints.weight` is nullable;
  aggregate scores are computed at read time from `violations` + weights,
  so customers can configure their own weighting instead of us hand-tuning
  a formula.
- **Explainability by construction.** `violations.evidence_span` and
  `violations.reasoning` are first-class columns, not optional metadata.
- **Ownership gate is structural.** `ownership_verifications.status` must be
  `verified` before a `jobs` row of type `red_team_battery` should be
  allowed to run against that endpoint — enforced at the application/Celery
  layer, not a DB constraint (status transitions need auditability via
  `evidence` JSONB, not just a boolean).
- **`model_responses.embedding` (pgvector, `VECTOR(1536)`)** is wired in but
  unused this sprint — reserved for the deferred Fingerprint Extractor /
  Signature table work.
- **UUID primary keys + `pgcrypto`** for `gen_random_uuid()`, consistent
  with multi-service access (Flask API + Celery workers) generating IDs
  without a round trip.

## Open questions for review

1. **`credential_ref` on `model_endpoints`** — assumes a secret store
   exists; confirm what that is (env-based, Vault, AWS Secrets Manager) so
   we know if this is a lookup key or something else.
2. **Embedding dimensionality (1536)** — placeholder matching a common
   OpenAI embedding size. Since fingerprinting is deferred, worth deciding
   whether to lock this now or leave it adjustable via migration later
   (pgvector requires a fixed dimension per column).
3. **`test_cases.attack_type`** — currently a free-text column. Should this
   be an enum/lookup table once the red-team generator's 4 initial attack
   categories are finalized in Week 2?
4. **Multi-tenancy / auth** — no `users`/`accounts` table yet;
   `projects.owner_email` is a placeholder. Worth confirming before the
   Alembic migration whether auth is in scope for this sprint or bolted on
   later.

If this looks right, next step is SQLAlchemy models mirroring this DDL plus
the first Alembic migration.

## Sprint 2 additions (implemented in the SQLAlchemy models / migration 0001)

- `model_endpoints.version_label` — human version tag so red-team runs can be compared
  across model updates (regression tracking).
- `jobs.error` — failure message for `failed` jobs.
- `test_cases.attack_succeeded`, `test_cases.detector_notes` — red-team detector verdict.
- `fingerprint_signatures` — the deferred Signature table: per-probe embeddings (JSONB),
  normalised centroid (pgvector, dimension set by the encoder, e.g. 384 for
  `all-MiniLM-L6-v2`), probe-set version, embedder name, stylometrics.
- `fingerprint_comparisons` — audit trail for every clone-detection comparison.
- Open question #3 resolved provisionally: the four attack categories are
  `prompt_injection`, `jailbreak_roleplay`, `system_prompt_extraction`, `obfuscation`
  (a Python enum; `attack_type` stays TEXT in the DB).
