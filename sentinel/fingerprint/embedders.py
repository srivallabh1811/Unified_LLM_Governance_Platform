"""Text embedders for behavioral fingerprints.

``SentenceTransformerEmbedder`` is the production embedder (install the
``embeddings`` extra). ``HashingEmbedder`` is a dependency-free fallback based
on hashed character n-grams — good enough to distinguish writing styles in
tests and offline demos, but not semantically aware.
"""

from __future__ import annotations

import hashlib
import re
from abc import ABC, abstractmethod
from typing import Sequence

import numpy as np


def l2_normalize(m: np.ndarray) -> np.ndarray:
    norms = np.linalg.norm(m, axis=-1, keepdims=True)
    norms[norms == 0] = 1.0
    return m / norms


class Embedder(ABC):
    name: str
    dimension: int

    @abstractmethod
    def embed(self, texts: Sequence[str]) -> np.ndarray:
        """Return an (n, dimension) float32 array of L2-normalised embeddings."""


class HashingEmbedder(Embedder):
    def __init__(self, dimension: int = 384, ngram_range: tuple[int, int] = (3, 5)) -> None:
        self.dimension = dimension
        self.ngram_range = ngram_range
        self.name = f"hashing-{dimension}"

    def _bucket(self, gram: str) -> tuple[int, float]:
        h = int.from_bytes(hashlib.blake2b(gram.encode(), digest_size=8).digest(), "little")
        return h % self.dimension, 1.0 if (h >> 63) & 1 else -1.0

    def embed(self, texts: Sequence[str]) -> np.ndarray:
        out = np.zeros((len(texts), self.dimension), dtype=np.float32)
        lo, hi = self.ngram_range
        for i, text in enumerate(texts):
            t = re.sub(r"\s+", " ", text.lower()).strip()
            padded = f" {t} "
            for n in range(lo, hi + 1):
                for j in range(len(padded) - n + 1):
                    idx, sign = self._bucket(padded[j : j + n])
                    out[i, idx] += sign
        return l2_normalize(out)


class SentenceTransformerEmbedder(Embedder):
    def __init__(self, model_name: str = "all-MiniLM-L6-v2", device: str | None = None) -> None:
        try:
            from sentence_transformers import SentenceTransformer
        except ImportError as e:  # pragma: no cover - depends on optional extra
            raise ImportError(
                "sentence-transformers is not installed; `pip install sentinel-layer[embeddings]` "
                "or set SENTINEL_EMBEDDING_MODEL=hashing"
            ) from e
        self._model = SentenceTransformer(model_name, device=device)
        self.name = f"st:{model_name}"
        self.dimension = int(self._model.get_sentence_embedding_dimension())

    def embed(self, texts: Sequence[str]) -> np.ndarray:  # pragma: no cover - heavy
        vecs = self._model.encode(list(texts), convert_to_numpy=True, normalize_embeddings=True)
        return vecs.astype(np.float32)


def get_embedder(name: str | None = None) -> Embedder:
    from sentinel.config import get_settings

    name = name or get_settings().embedding_model
    if name == "hashing" or name.startswith("hashing-"):
        dim = int(name.split("-", 1)[1]) if "-" in name else 384
        return HashingEmbedder(dimension=dim)
    return SentenceTransformerEmbedder(name)
