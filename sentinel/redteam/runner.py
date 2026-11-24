"""Run an attack battery against a model and summarise the results."""

from __future__ import annotations

from collections import defaultdict
from dataclasses import asdict, dataclass, field
from typing import Iterable

from sentinel.providers.base import ModelClient
from sentinel.redteam.attacks import AttackCase
from sentinel.redteam.detectors import detect


@dataclass
class AttackResult:
    case: AttackCase
    response: str
    latency_ms: int
    attack_succeeded: bool
    notes: str


@dataclass
class CategoryStats:
    total: int = 0
    succeeded: int = 0

    @property
    def attack_success_rate(self) -> float:
        return self.succeeded / self.total if self.total else 0.0


@dataclass
class RedTeamReport:
    model_name: str
    results: list[AttackResult] = field(default_factory=list)

    @property
    def by_category(self) -> dict[str, CategoryStats]:
        stats: dict[str, CategoryStats] = defaultdict(CategoryStats)
        for r in self.results:
            s = stats[r.case.category.value]
            s.total += 1
            s.succeeded += int(r.attack_succeeded)
        return dict(stats)

    @property
    def attack_success_rate(self) -> float:
        if not self.results:
            return 0.0
        return sum(r.attack_succeeded for r in self.results) / len(self.results)

    def summary(self) -> dict:
        return {
            "model": self.model_name,
            "total_cases": len(self.results),
            "attack_success_rate": round(self.attack_success_rate, 4),
            "by_category": {
                k: {
                    "total": v.total,
                    "succeeded": v.succeeded,
                    "attack_success_rate": round(v.attack_success_rate, 4),
                }
                for k, v in sorted(self.by_category.items())
            },
        }

    def failures(self) -> list[dict]:
        return [
            {**asdict(r.case), "category": r.case.category.value, "response": r.response, "notes": r.notes}
            for r in self.results
            if r.attack_succeeded
        ]


def run_battery(
    client: ModelClient,
    cases: Iterable[AttackCase],
    system_prompt: str | None = None,
) -> RedTeamReport:
    report = RedTeamReport(model_name=client.name)
    for case in cases:
        completion = client.generate(system_prompt, case.text)
        det = detect(case, completion.text, system_prompt)
        report.results.append(
            AttackResult(
                case=case,
                response=completion.text,
                latency_ms=completion.latency_ms,
                attack_succeeded=det.attack_succeeded,
                notes=det.notes,
            )
        )
    return report
