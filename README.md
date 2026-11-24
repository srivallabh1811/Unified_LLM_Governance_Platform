# Sentinel Layer — Unified LLM Governance Platform

Sentinel Layer puts three LLM-governance capabilities behind one evaluation framework,
one data model and one API:

| Pillar | What it does | Module |
|---|---|---|
| **Red-teaming** | Generates adversarial test batteries (prompt injection, role-play jailbreaks, system-prompt extraction, obfuscation), scores attack success, and flags **safety regressions** between model versions | `sentinel/redteam` |
| **Output integrity** | Extracts checkable constraints from a system prompt, judges responses against them (heuristic / LLM-as-judge / ensemble), stores per-constraint violations with evidence | `sentinel/integrity` |
| **Model fingerprinting** | Builds behavioral signatures from **sentence-transformer embeddings** of responses to a versioned probe set and compares them to detect likely **model cloning** | `sentinel/fingerprint` |

All three run as **jobs** against a registered **model endpoint**. Red-teaming is gated on
**verified ownership** of that endpoint.

> Status: ~60% of the planned platform. See [docs/ROADMAP.md](docs/ROADMAP.md) for what's
> done and what's left.

## Quick start

```bash
pip install -e ".[dev]"
```

```bash
sentinel demo
```

```bash
python -m pytest
```

`sentinel demo` runs all three pillars offline against simulated models. For real
semantic fingerprints install the embeddings extra (pulls in PyTorch):

```bash
pip install -e ".[embeddings]"
```

```bash
sentinel demo --embedding-model all-MiniLM-L6-v2
```

### Red-team a real endpoint you own

```bash
OPENAI_API_KEY=... sentinel redteam --model gpt-4o-mini --system-prompt-file prompt.txt --out report.json
```

Any OpenAI-compatible `/chat/completions` server works (`--base-url`).

### API

```bash
sentinel serve --port 8000
```

| Method | Path | |
|---|---|---|
| POST | `/projects` | create project |
| POST | `/projects/<id>/endpoints` | register a model endpoint |
| POST | `/endpoints/<id>/ownership` | start ownership verification (returns token) |
| POST | `/ownership/<id>/confirm` | confirm verification |
| POST | `/projects/<id>/system-prompts` | new prompt version → constraints extracted |
| POST | `/projects/<id>/jobs` | `red_team_battery` / `integrity_check` / `fingerprint_extraction` |
| GET | `/jobs/<id>`, `/jobs/<id>/test-cases` | results, responses, violations |
| POST | `/red-team/compare` | regression report between two red-team jobs |
| POST | `/fingerprints/compare` | clone-likelihood between two signatures |

Jobs currently execute synchronously inside the request; moving them to Celery workers is
on the roadmap.

## Configuration

| Env var | Default | |
|---|---|---|
| `SENTINEL_DATABASE_URL` | `sqlite:///sentinel.db` | Postgres + pgvector in production |
| `SENTINEL_EMBEDDING_MODEL` | `all-MiniLM-L6-v2` | `hashing` = offline fallback embedder |
| `SENTINEL_CLONE_THRESHOLD` | `0.92` | mean per-probe cosine at/above which a pair is flagged |
| `SENTINEL_REGRESSION_TOLERANCE` | `0.05` | allowed attack-success-rate increase per category |

Endpoint credentials are referenced, never stored: `credential_ref = "env:MY_API_KEY"`.

## Database

```bash
SENTINEL_DATABASE_URL=postgresql+psycopg://... alembic upgrade head
```

Models in `sentinel/db/models.py` mirror the reviewed DDL in `db/schema.sql`
(see [docs/schema.md](docs/schema.md)); types are portable so tests run on SQLite.

## Layout

```
sentinel/
  providers/    model clients (OpenAI-compatible HTTP, simulated personas)
  redteam/      attack generator, success detectors, battery runner, regression compare
  integrity/    constraint extraction, judges, judge-accuracy eval harness
  fingerprint/  embedders, probe sets, signatures, clone comparison
  services/     DB-backed job orchestration + ownership gate
  api/          Flask app
  db/           SQLAlchemy models + session helpers
migrations/     Alembic
tests/          pytest suite
```
