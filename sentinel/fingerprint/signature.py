"""Build and compare behavioral fingerprints.

A *signature* is the set of response embeddings a model produces for a
versioned probe set, plus their normalised centroid and a few stylometric
features. Two endpoints are flagged as a likely clone when their signatures
are more similar than the configured threshold.

Comparison uses two views:

* **centroid similarity** — cosine between centroids (overall voice), and
* **mean per-probe similarity** — average cosine between responses to the
  *same* probe (behavioral agreement), which is the primary signal; centroid
  alone saturates for models that share a register.
"""

from __future__ import annotations

import re
import statistics
from dataclasses import dataclass, field
from typing import Sequence

import numpy as np

from sentinel.fingerprint.embedders import Embedder, l2_normalize
from sentinel.fingerprint.probes import PROBE_SET_VERSION, Probe, get_probe_set
from sentinel.providers.base import ModelClient
from sentinel.redteam.detectors import is_refusal


@dataclass
class Signature:
    model_name: str
    embedder_name: str
    probe_set_version: str
    probe_ids: list[str]
    embeddings: np.ndarray  # (n_probes, dim), L2-normalised
    responses: list[str] = field(default_factory=list)
    stylometrics: dict = field(default_factory=dict)

    @property
    def dimension(self) -> int:
        return int(self.embeddings.shape[1])

    @property
    def centroid(self) -> np.ndarray:
        return l2_normalize(self.embeddings.mean(axis=0, keepdims=True))[0]

    def probe_embeddings_dict(self) -> dict[str, list[float]]:
        return {pid: self.embeddings[i].tolist() for i, pid in enumerate(self.probe_ids)}

    @classmethod
    def from_stored(
        cls,
        model_name: str,
        embedder_name: str,
        probe_set_version: str,
        probe_embeddings: dict[str, list[float]],
        stylometrics: dict | None = None,
    ) -> "Signature":
        ids = list(probe_embeddings)
        return cls(
            model_name=model_name,
            embedder_name=embedder_name,
            probe_set_version=probe_set_version,
            probe_ids=ids,
            embeddings=np.asarray([probe_embeddings[i] for i in ids], dtype=np.float32),
            stylometrics=stylometrics or {},
        )


def compute_stylometrics(responses: Sequence[str]) -> dict:
    lengths = [len(r.split()) for r in responses]
    return {
        "mean_words": round(statistics.fmean(lengths), 2) if lengths else 0.0,
        "refusal_rate": round(sum(is_refusal(r) for r in responses) / len(responses), 4)
        if responses
        else 0.0,
        "markdown_rate": round(
            sum(bool(re.search(r"(^|\n)\s*(?:[-*]|\d+\.)\s|\*\*|```", r)) for r in responses)
            / len(responses),
            4,
        )
        if responses
        else 0.0,
        "exclamation_rate": round(sum("!" in r for r in responses) / len(responses), 4)
        if responses
        else 0.0,
    }


def build_signature(
    client: ModelClient,
    embedder: Embedder,
    probes: Sequence[Probe] | None = None,
    probe_set_version: str = PROBE_SET_VERSION,
    system_prompt: str | None = None,
) -> Signature:
    probes = list(probes or get_probe_set(probe_set_version))
    responses = [client.generate(system_prompt, p.text).text for p in probes]
    return Signature(
        model_name=client.name,
        embedder_name=embedder.name,
        probe_set_version=probe_set_version,
        probe_ids=[p.id for p in probes],
        embeddings=embedder.embed(responses),
        responses=responses,
        stylometrics=compute_stylometrics(responses),
    )


@dataclass(frozen=True)
class ComparisonResult:
    reference: str
    candidate: str
    centroid_similarity: float
    mean_probe_similarity: float
    per_probe: dict[str, float]
    threshold: float

    @property
    def likely_clone(self) -> bool:
        return self.mean_probe_similarity >= self.threshold

    def to_dict(self) -> dict:
        return {
            "reference": self.reference,
            "candidate": self.candidate,
            "centroid_similarity": round(self.centroid_similarity, 4),
            "mean_probe_similarity": round(self.mean_probe_similarity, 4),
            "threshold": self.threshold,
            "likely_clone": self.likely_clone,
            "per_probe": {k: round(v, 4) for k, v in self.per_probe.items()},
        }


def compare_signatures(ref: Signature, cand: Signature, threshold: float = 0.92) -> ComparisonResult:
    if ref.probe_set_version != cand.probe_set_version:
        raise ValueError("signatures use different probe set versions")
    if ref.embedder_name != cand.embedder_name:
        raise ValueError("signatures use different embedders")
    shared = [pid for pid in ref.probe_ids if pid in set(cand.probe_ids)]
    if not shared:
        raise ValueError("signatures share no probes")
    ri = {pid: i for i, pid in enumerate(ref.probe_ids)}
    ci = {pid: i for i, pid in enumerate(cand.probe_ids)}
    per_probe = {
        pid: float(np.dot(ref.embeddings[ri[pid]], cand.embeddings[ci[pid]])) for pid in shared
    }
    return ComparisonResult(
        reference=ref.model_name,
        candidate=cand.model_name,
        centroid_similarity=float(np.dot(ref.centroid, cand.centroid)),
        mean_probe_similarity=float(np.mean(list(per_probe.values()))),
        per_probe=per_probe,
        threshold=threshold,
    )


def rank_candidates(
    ref: Signature, candidates: Sequence[Signature], threshold: float = 0.92
) -> list[ComparisonResult]:
    """Compare one reference against many; most similar first."""
    results = [compare_signatures(ref, c, threshold) for c in candidates]
    return sorted(results, key=lambda r: r.mean_probe_similarity, reverse=True)
