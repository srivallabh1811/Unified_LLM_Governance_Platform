import numpy as np
import pytest

from sentinel.fingerprint import (
    HashingEmbedder,
    Signature,
    build_signature,
    compare_signatures,
    get_probe_set,
    rank_candidates,
)
from sentinel.providers import SimulatedModel


@pytest.fixture(scope="module")
def emb():
    return HashingEmbedder()


def test_hashing_embedder_normalised_and_deterministic(emb):
    a = emb.embed(["hello world", "hello world", "something else entirely"])
    assert a.shape == (3, 384)
    np.testing.assert_allclose(np.linalg.norm(a, axis=1), 1.0, rtol=1e-5)
    assert float(a[0] @ a[1]) == pytest.approx(1.0)
    assert float(a[0] @ a[2]) < 0.5


def test_clone_detected_and_independent_models_distinct(emb):
    ref = build_signature(SimulatedModel("orig", style="verbose"), emb)
    clone = build_signature(SimulatedModel("clone", persona="vulnerable", style="verbose"), emb)
    other = build_signature(SimulatedModel("other", style="formal"), emb)
    assert compare_signatures(ref, clone, 0.9).likely_clone
    assert not compare_signatures(ref, other, 0.9).likely_clone
    ranked = rank_candidates(ref, [other, clone], 0.9)
    assert ranked[0].candidate == "clone"


def test_signature_roundtrip_through_storage(emb):
    sig = build_signature(SimulatedModel("m"), emb)
    restored = Signature.from_stored("m", sig.embedder_name, sig.probe_set_version, sig.probe_embeddings_dict())
    assert compare_signatures(sig, restored).mean_probe_similarity == pytest.approx(1.0, abs=1e-5)
    assert len(sig.probe_ids) == len(get_probe_set())
    assert set(sig.stylometrics) == {"mean_words", "refusal_rate", "markdown_rate", "exclamation_rate"}


def test_incompatible_signatures_rejected(emb):
    a = build_signature(SimulatedModel("a"), emb)
    b = build_signature(SimulatedModel("b"), HashingEmbedder(dimension=128))
    with pytest.raises(ValueError):
        compare_signatures(a, b)
