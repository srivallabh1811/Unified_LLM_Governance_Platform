"""Runtime configuration, read from environment variables."""

from __future__ import annotations

import os
from dataclasses import dataclass, field


def _env_float(name: str, default: float) -> float:
    raw = os.getenv(name)
    return float(raw) if raw else default


@dataclass(frozen=True)
class Settings:
    database_url: str = field(
        default_factory=lambda: os.getenv("SENTINEL_DATABASE_URL", "sqlite:///sentinel.db")
    )
    # Sentence-transformer used for behavioral fingerprints. ``hashing`` selects the
    # dependency-free fallback embedder (useful for CI / offline dev).
    embedding_model: str = field(
        default_factory=lambda: os.getenv("SENTINEL_EMBEDDING_MODEL", "all-MiniLM-L6-v2")
    )
    # Cosine similarity at or above which two fingerprints are flagged as a likely clone.
    clone_threshold: float = field(
        default_factory=lambda: _env_float("SENTINEL_CLONE_THRESHOLD", 0.92)
    )
    # A red-team attack-success-rate increase larger than this between two runs is a regression.
    regression_tolerance: float = field(
        default_factory=lambda: _env_float("SENTINEL_REGRESSION_TOLERANCE", 0.05)
    )


def get_settings() -> Settings:
    return Settings()
