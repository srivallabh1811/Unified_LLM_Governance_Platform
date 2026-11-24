import base64

from sentinel.providers import SimulatedModel
from sentinel.redteam import (
    AttackCategory,
    AttackGenerator,
    case_key,
    compare_summaries,
    detect,
    is_refusal,
    leakage_score,
    run_battery,
)
from sentinel.redteam.attacks import AttackCase

from .conftest import SYSTEM_PROMPT


def test_generator_covers_all_categories_and_is_deterministic():
    cases = AttackGenerator().generate()
    assert {c.category for c in cases} == set(AttackCategory)
    assert [c.text for c in cases] == [c.text for c in AttackGenerator().generate()]


def test_generator_sampling_and_mutators():
    gen = AttackGenerator(mutators=["identity", "uppercase"], seed=7)
    full = gen.generate()
    assert any(c.text.isupper() for c in full)
    assert len(gen.generate(max_cases=5)) == 5


def test_obfuscation_base64_roundtrip():
    cases = AttackGenerator(categories=[AttackCategory.OBFUSCATION], objectives=["do x"]).generate()
    b64 = next(c for c in cases if c.template_id == "ob.base64")
    payload = b64.text.rsplit(" ", 1)[-1]
    assert base64.b64decode(payload).decode() == "do x"


def test_objectives_from_constraints():
    objs = AttackGenerator.objectives_from_constraints(
        ["Never discuss competitors.", "Always be polite.", "Do not give legal advice"]
    )
    assert objs == ["discuss competitors", "give legal advice"]


def test_refusal_and_leakage_detection():
    assert is_refusal("I'm sorry, but I can't help with that.")
    assert not is_refusal("Sure! Here you go.")
    assert leakage_score(SYSTEM_PROMPT, f"My instructions are: {SYSTEM_PROMPT}") == 1.0
    assert leakage_score(SYSTEM_PROMPT, "Hello there") == 0.0


def test_detect_extraction_requires_system_prompt():
    case = AttackCase(AttackCategory.SYSTEM_PROMPT_EXTRACTION, "spe.direct", "x", "identity", "print prompt")
    assert not detect(case, "anything", None).attack_succeeded
    assert detect(case, SYSTEM_PROMPT, SYSTEM_PROMPT).attack_succeeded


def test_persona_ordering_of_attack_success_rate():
    cases = AttackGenerator().generate()
    asr = {
        p: run_battery(SimulatedModel(p, persona=p), cases, SYSTEM_PROMPT).attack_success_rate
        for p in ("hardened", "partial", "vulnerable")
    }
    assert asr["hardened"] < asr["partial"] < asr["vulnerable"]


def test_regression_detected_between_versions():
    cases = AttackGenerator().generate()
    v1 = run_battery(SimulatedModel("v1", persona="hardened"), cases, SYSTEM_PROMPT)
    v2 = run_battery(SimulatedModel("v2", persona="partial"), cases, SYSTEM_PROMPT)

    def fails(r):
        return {case_key(x.case.template_id, x.case.mutator, x.case.objective) for x in r.results if x.attack_succeeded}

    rep = compare_summaries(v1.summary(), v2.summary(), 0.05, fails(v1), fails(v2))
    assert rep.has_regression
    assert "jailbreak_roleplay" in {d.category for d in rep.regressions}
    assert rep.newly_failing_cases
    # Reverse direction is an improvement, not a regression.
    back = compare_summaries(v2.summary(), v1.summary(), 0.05)
    assert not back.has_regression and back.improvements
