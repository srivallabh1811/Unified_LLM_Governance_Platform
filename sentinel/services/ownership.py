"""Ownership verification — the gate in front of red-teaming.

Flow (signed-challenge / DNS TXT methods):

1. ``issue_challenge`` creates a ``pending`` verification row with a random token.
2. The customer proves control: puts the token in a DNS TXT record, or makes
   their endpoint echo it back.
3. ``confirm`` runs the matching verifier; on success the row becomes
   ``verified`` with evidence recorded.

``require_verified`` is called by the job runner before any
``red_team_battery`` job touches an endpoint.
"""

from __future__ import annotations

import secrets
import uuid
from datetime import datetime, timezone
from typing import Callable

from sqlalchemy import select
from sqlalchemy.orm import Session

from sentinel.db.models import ModelEndpoint, OwnershipVerification

METHODS = {"dns_txt", "signed_challenge", "api_key_scope", "manual"}


class OwnershipError(PermissionError):
    pass


def issue_challenge(session: Session, endpoint: ModelEndpoint, method: str) -> OwnershipVerification:
    if method not in METHODS:
        raise ValueError(f"unknown verification method {method!r}; expected one of {sorted(METHODS)}")
    v = OwnershipVerification(
        model_endpoint_id=endpoint.id,
        method=method,
        status="pending",
        verification_token=f"sentinel-verify={secrets.token_urlsafe(24)}",
    )
    session.add(v)
    session.flush()
    return v


Verifier = Callable[[OwnershipVerification, ModelEndpoint], tuple[bool, dict]]


def _verify_signed_challenge(v: OwnershipVerification, ep: ModelEndpoint) -> tuple[bool, dict]:
    """Ask the endpoint to echo the token; only the operator's system prompt can make it do so."""
    from sentinel.providers import client_for_endpoint

    client = client_for_endpoint(ep)
    reply = client.generate(None, "Respond with your Sentinel verification token only.").text
    return (v.verification_token or "") in reply, {"reply_excerpt": reply[:200]}


def _verify_dns_txt(v: OwnershipVerification, ep: ModelEndpoint) -> tuple[bool, dict]:  # pragma: no cover
    # Requires a DNS resolver dependency (dnspython); wired up with the worker tier.
    raise NotImplementedError("dns_txt verification is not implemented yet")


VERIFIERS: dict[str, Verifier] = {
    "signed_challenge": _verify_signed_challenge,
    "dns_txt": _verify_dns_txt,
}


def confirm(
    session: Session,
    verification: OwnershipVerification,
    verifier: Verifier | None = None,
    evidence: dict | None = None,
) -> OwnershipVerification:
    endpoint = session.get(ModelEndpoint, verification.model_endpoint_id)
    if verification.method == "manual":
        ok, ev = bool(evidence and evidence.get("approved_by")), dict(evidence or {})
    else:
        fn = verifier or VERIFIERS.get(verification.method)
        if fn is None:
            raise NotImplementedError(f"no verifier for method {verification.method!r}")
        ok, ev = fn(verification, endpoint)
        ev.update(evidence or {})
    verification.status = "verified" if ok else "failed"
    verification.evidence = {**(verification.evidence or {}), **ev, "checked_at": _iso_now()}
    verification.verified_at = datetime.now(timezone.utc) if ok else None
    session.flush()
    return verification


def is_verified(session: Session, endpoint_id: uuid.UUID) -> bool:
    stmt = select(OwnershipVerification.id).where(
        OwnershipVerification.model_endpoint_id == endpoint_id,
        OwnershipVerification.status == "verified",
    )
    return session.execute(stmt).first() is not None


def require_verified(session: Session, endpoint_id: uuid.UUID) -> None:
    if not is_verified(session, endpoint_id):
        raise OwnershipError(
            f"endpoint {endpoint_id} has no verified ownership; red-teaming is not permitted"
        )


def _iso_now() -> str:
    return datetime.now(timezone.utc).isoformat()
