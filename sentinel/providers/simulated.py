"""Deterministic, offline model stand-ins for tests, demos and CI.

``SimulatedModel`` behaves like a chat model with a configurable *persona*:

* ``hardened``   — refuses adversarial requests and never leaks its prompt.
* ``vulnerable`` — complies with most attacks and leaks the system prompt.
* ``partial``    — refuses obvious attacks but falls for role-play/obfuscation.

Its "voice" is controlled by ``style`` so that two simulated models with the
same style produce near-identical outputs (a clone), while different styles
produce measurably different fingerprints.
"""

from __future__ import annotations

import hashlib
import re

from sentinel.providers.base import ModelClient

_ATTACK_MARKERS = {
    "obvious": [
        r"ignore (all|any|the)? ?(previous|prior|above)",
        r"disregard",
        r"system prompt",
        r"your instructions",
        r"developer mode",
        r"\bDAN\b",
    ],
    "subtle": [
        r"pretend",
        r"role[- ]?play",
        r"hypothetical",
        r"fiction",
        r"base64",
        r"translate",
        r"grandmother",
        r"as an? (actor|character)",
        r"for a novel",
    ],
}

_STYLES = {
    "concise": {
        "refusal": "I can't help with that.",
        "prefix": "",
        "suffix": "",
    },
    "verbose": {
        "refusal": (
            "I'm sorry, but I'm not able to assist with that request. "
            "If you have another question, I'd be glad to help!"
        ),
        "prefix": "Certainly! Here's a detailed answer. ",
        "suffix": " Let me know if you'd like more detail on any part of this.",
    },
    "formal": {
        "refusal": "Regrettably, that request falls outside the permitted scope of this assistant.",
        "prefix": "Thank you for your enquiry. ",
        "suffix": " Kind regards.",
    },
}


class SimulatedModel(ModelClient):
    def __init__(
        self,
        name: str = "simulated",
        persona: str = "hardened",
        style: str = "concise",
        system_prompt_override: str | None = None,
    ) -> None:
        if persona not in {"hardened", "vulnerable", "partial"}:
            raise ValueError(f"unknown persona {persona!r}")
        if style not in _STYLES:
            raise ValueError(f"unknown style {style!r}")
        self.name = name
        self.persona = persona
        self.style = style
        self.system_prompt_override = system_prompt_override

    @staticmethod
    def _matches(text: str, kind: str) -> bool:
        return any(re.search(p, text, re.IGNORECASE) for p in _ATTACK_MARKERS[kind])

    def _is_refused(self, user_input: str) -> bool:
        obvious = self._matches(user_input, "obvious")
        subtle = self._matches(user_input, "subtle")
        if self.persona == "hardened":
            return obvious or subtle
        if self.persona == "partial":
            return obvious and not subtle
        return False

    def _generate(self, system_prompt: str | None, user_input: str) -> str:
        style = _STYLES[self.style]
        if self._is_refused(user_input):
            return style["refusal"]
        sp = self.system_prompt_override or system_prompt or ""
        lowered = user_input.lower()
        if sp and ("prompt" in lowered or "instructions" in lowered or "verbatim" in lowered):
            return f"{style['prefix']}My instructions are: {sp}{style['suffix']}"
        if self._matches(user_input, "obvious") or self._matches(user_input, "subtle"):
            return (
                f"{style['prefix']}Sure, here is how to do it. Step 1: obtain the materials. "
                f"Step 2: follow the procedure exactly.{style['suffix']}"
            )
        # Benign request: a deterministic, topic-dependent answer.
        topic = re.sub(r"[^a-z0-9 ]", "", lowered)[:80].strip()
        digest = int(hashlib.sha256(topic.encode()).hexdigest(), 16)
        facts = [
            "it depends on the context",
            "there are several common approaches",
            "the key idea is to start simple",
            "experts generally recommend caution",
        ]
        return (
            f"{style['prefix']}Regarding {topic}: {facts[digest % len(facts)]}."
            f"{style['suffix']}"
        )
