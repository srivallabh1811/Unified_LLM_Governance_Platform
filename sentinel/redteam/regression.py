"""Track safety regressions between two red-team runs (e.g. model v1 → v2)."""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class CategoryDelta:
    category: str
    baseline_asr: float
    candidate_asr: float

    @property
    def delta(self) -> float:
        return self.candidate_asr - self.baseline_asr


@dataclass
class RegressionReport:
    baseline: str
    candidate: str
    tolerance: float
    deltas: list[CategoryDelta]
    newly_failing_cases: list[str]

    @property
    def regressions(self) -> list[CategoryDelta]:
        return [d for d in self.deltas if d.delta > self.tolerance]

    @property
    def improvements(self) -> list[CategoryDelta]:
        return [d for d in self.deltas if d.delta < -self.tolerance]

    @property
    def has_regression(self) -> bool:
        return bool(self.regressions)

    def to_dict(self) -> dict:
        return {
            "baseline": self.baseline,
            "candidate": self.candidate,
            "tolerance": self.tolerance,
            "has_regression": self.has_regression,
            "categories": [
                {
                    "category": d.category,
                    "baseline_asr": round(d.baseline_asr, 4),
                    "candidate_asr": round(d.candidate_asr, 4),
                    "delta": round(d.delta, 4),
                    "status": "regressed"
                    if d.delta > self.tolerance
                    else "improved"
                    if d.delta < -self.tolerance
                    else "stable",
                }
                for d in self.deltas
            ],
            "newly_failing_cases": self.newly_failing_cases,
        }


def compare_summaries(
    baseline: dict,
    candidate: dict,
    tolerance: float = 0.05,
    baseline_failures: set[str] | None = None,
    candidate_failures: set[str] | None = None,
) -> RegressionReport:
    """Compare two ``RedTeamReport.summary()`` dicts.

    ``*_failures`` are optional sets of case keys (e.g. ``template_id|mutator|objective``)
    that succeeded as attacks, used to list cases that newly fail.
    """
    cats = sorted(set(baseline["by_category"]) | set(candidate["by_category"]))
    deltas = [
        CategoryDelta(
            category=c,
            baseline_asr=baseline["by_category"].get(c, {}).get("attack_success_rate", 0.0),
            candidate_asr=candidate["by_category"].get(c, {}).get("attack_success_rate", 0.0),
        )
        for c in cats
    ]
    newly = sorted((candidate_failures or set()) - (baseline_failures or set()))
    return RegressionReport(
        baseline=baseline["model"],
        candidate=candidate["model"],
        tolerance=tolerance,
        deltas=deltas,
        newly_failing_cases=newly,
    )


def case_key(template_id: str, mutator: str, objective: str) -> str:
    return f"{template_id}|{mutator}|{objective}"
