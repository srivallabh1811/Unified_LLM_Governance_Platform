"""Eval harness: measure judge accuracy against labeled ``eval_examples``."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Iterable

from sentinel.integrity.judges import ConstraintRef, Judge


@dataclass(frozen=True)
class LabeledExample:
    input_text: str
    response_text: str
    constraint: ConstraintRef
    expected_violation: bool
    system_prompt: str | None = None


@dataclass
class JudgeMetrics:
    tp: int = 0
    fp: int = 0
    tn: int = 0
    fn: int = 0

    @property
    def total(self) -> int:
        return self.tp + self.fp + self.tn + self.fn

    @property
    def accuracy(self) -> float:
        return (self.tp + self.tn) / self.total if self.total else 0.0

    @property
    def precision(self) -> float:
        return self.tp / (self.tp + self.fp) if (self.tp + self.fp) else 0.0

    @property
    def recall(self) -> float:
        return self.tp / (self.tp + self.fn) if (self.tp + self.fn) else 0.0

    @property
    def f1(self) -> float:
        p, r = self.precision, self.recall
        return 2 * p * r / (p + r) if (p + r) else 0.0

    def to_dict(self) -> dict:
        return {
            "n": self.total,
            "accuracy": round(self.accuracy, 4),
            "precision": round(self.precision, 4),
            "recall": round(self.recall, 4),
            "f1": round(self.f1, 4),
            "confusion": {"tp": self.tp, "fp": self.fp, "tn": self.tn, "fn": self.fn},
        }


def evaluate_judge(judge: Judge, examples: Iterable[LabeledExample]) -> JudgeMetrics:
    m = JudgeMetrics()
    for ex in examples:
        (verdict,) = judge.judge(ex.input_text, ex.response_text, [ex.constraint], ex.system_prompt)
        if verdict.violated and ex.expected_violation:
            m.tp += 1
        elif verdict.violated:
            m.fp += 1
        elif ex.expected_violation:
            m.fn += 1
        else:
            m.tn += 1
    return m
