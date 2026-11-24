"""Provider-agnostic interface for the target models under governance."""

from __future__ import annotations

import time
from abc import ABC, abstractmethod
from dataclasses import dataclass


@dataclass(frozen=True)
class Completion:
    text: str
    latency_ms: int


class ModelClient(ABC):
    """Anything that turns (system prompt, user input) into a text response."""

    name: str = "model"

    @abstractmethod
    def _generate(self, system_prompt: str | None, user_input: str) -> str: ...

    def generate(self, system_prompt: str | None, user_input: str) -> Completion:
        start = time.perf_counter()
        text = self._generate(system_prompt, user_input)
        return Completion(text=text, latency_ms=int((time.perf_counter() - start) * 1000))
