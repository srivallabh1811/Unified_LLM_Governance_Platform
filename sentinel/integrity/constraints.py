"""Extract individual, checkable rules from a system prompt.

This is the rule-based extractor. It finds imperative sentences containing
normative language ("never", "must", "only", "do not", ...) and tags each with
a category. An LLM-backed extractor can replace it behind the same function
signature for prompts written in free prose.
"""

from __future__ import annotations

import re
from dataclasses import dataclass

_NORMATIVE = re.compile(
    r"\b(never|always|must|must not|should not|shouldn't|do not|don't|only|avoid|refuse|"
    r"under no circumstances|not allowed|prohibited|required to)\b",
    re.IGNORECASE,
)

_CATEGORY_KEYWORDS: list[tuple[str, tuple[str, ...]]] = [
    ("disclosure", ("system prompt", "instructions", "reveal", "disclose", "confidential", "internal")),
    ("safety", ("harm", "weapon", "illegal", "medical", "dosage", "violence", "self-harm", "dangerous")),
    ("privacy", ("personal", "pii", "email address", "phone", "ssn", "password", "credit card")),
    ("tone", ("polite", "professional", "tone", "rude", "insult", "friendly", "profanity")),
    ("scope", ("only", "topic", "related to", "outside", "off-topic", "competitor")),
    ("format", ("json", "markdown", "bullet", "words", "sentences", "format", "language")),
]


@dataclass(frozen=True)
class ExtractedConstraint:
    description: str
    category: str
    polarity: str  # "prohibit" | "require"


def categorize(sentence: str) -> str:
    lowered = sentence.lower()
    for category, keywords in _CATEGORY_KEYWORDS:
        if any(k in lowered for k in keywords):
            return category
    return "general"


def _polarity(sentence: str) -> str:
    return (
        "prohibit"
        if re.search(
            r"\b(never|must not|should not|shouldn't|do not|don't|avoid|refuse|under no circumstances|"
            r"not allowed|prohibited)\b",
            sentence,
            re.IGNORECASE,
        )
        else "require"
    )


def _split_sentences(text: str) -> list[str]:
    parts: list[str] = []
    for line in text.splitlines():
        line = re.sub(r"^\s*(?:[-*•]|\d+[.)])\s*", "", line).strip()
        if not line:
            continue
        parts.extend(s.strip() for s in re.split(r"(?<=[.!?])\s+", line) if s.strip())
    return parts


def extract_constraints(prompt_text: str) -> list[ExtractedConstraint]:
    seen: set[str] = set()
    out: list[ExtractedConstraint] = []
    for sentence in _split_sentences(prompt_text):
        if not _NORMATIVE.search(sentence):
            continue
        key = sentence.lower()
        if key in seen:
            continue
        seen.add(key)
        out.append(
            ExtractedConstraint(
                description=sentence, category=categorize(sentence), polarity=_polarity(sentence)
            )
        )
    return out
