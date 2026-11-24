"""Model client adapters and a factory that builds one from a ``ModelEndpoint`` row."""

from __future__ import annotations

import os

from sentinel.providers.base import Completion, ModelClient
from sentinel.providers.openai_compat import OpenAICompatibleClient
from sentinel.providers.simulated import SimulatedModel

__all__ = [
    "Completion",
    "ModelClient",
    "OpenAICompatibleClient",
    "SimulatedModel",
    "client_for_endpoint",
    "resolve_credential",
]


def resolve_credential(credential_ref: str | None) -> str | None:
    """Resolve a ``credential_ref`` to a secret.

    Only ``env:VAR_NAME`` is supported for now (open question #1 in
    docs/schema.md — Vault / AWS Secrets Manager backends slot in here).
    """
    if not credential_ref:
        return None
    scheme, _, ref = credential_ref.partition(":")
    if scheme == "env":
        return os.environ.get(ref)
    raise ValueError(f"unsupported credential_ref scheme {scheme!r}")


def client_for_endpoint(endpoint) -> ModelClient:
    """Build a client from a :class:`sentinel.db.models.ModelEndpoint`."""
    provider = endpoint.provider.lower()
    if provider == "simulated":
        # model_identifier encodes persona/style, e.g. "vulnerable/verbose"
        persona, _, style = endpoint.model_identifier.partition("/")
        return SimulatedModel(name=endpoint.name, persona=persona, style=style or "concise")
    if provider in {"openai", "openai-compatible", "self-hosted", "grok", "vllm"}:
        return OpenAICompatibleClient(
            model=endpoint.model_identifier,
            base_url=endpoint.endpoint_url or "https://api.openai.com/v1",
            api_key=resolve_credential(endpoint.credential_ref),
        )
    raise ValueError(f"unsupported provider {endpoint.provider!r}")
