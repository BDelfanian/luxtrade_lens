"""Scenario builder: plan checks, the run through the assistant, follow-ups and the answer check.

Scripted LLM on placeholder data (2018 onwards); no network.
"""

import json

import pytest
from test_graph_flows import interp

from luxtrade.agents.llm import LLMError
from luxtrade.agents.scenario import (
    AnswerPoint,
    AnswerVerdicts,
    FollowUp,
    FollowUps,
    PlanStep,
    ScenarioAnswer,
    ScenarioBuilder,
    ScenarioPlan,
    StepInput,
    check_answer,
    mismatch,
    review_answer,
    to_markdown,
)
from luxtrade.agents.spec import QuerySpec
from luxtrade.runs.scenarios import ScenarioStore

EXPORTS_BY_PRODUCT = QuerySpec(
    intent="composition",
    breakdown="product",
    flow="export",
    measure="share",
    period_start="2024",
    period_end="2024",
)
IMPORTS_BY_PARTNER = QuerySpec(
    intent="composition",
    breakdown="partner",
    flow="import",
    measure="share",
    period_start="2024",
    period_end="2024",
)
STEEL_SERIES = QuerySpec(
    intent="time_series",
    products=["72"],
    flow="export",
    period_start="2019",
    period_end="2024",
    freq="A",
)
QUESTION = (
    "Has Luxembourg spread its risk across the goods it sells and the countries it buys from?"
)


def step(question: str, spec: QuerySpec, purpose: str = "evidence") -> PlanStep:
    return PlanStep(question=question, purpose=purpose, spec=spec)


def plan_of(*steps: PlanStep) -> ScenarioPlan:
    return ScenarioPlan(
        title="Spread of risk",
        approach="Products, then partners.",
        steps=list(steps),
        out_of_scope=[],
    )


GOOD_PLAN = plan_of(
    step("What share of exports did each chapter have in 2024?", EXPORTS_BY_PRODUCT),
    step("What share of imports came from each partner in 2024?", IMPORTS_BY_PARTNER),
)


def answer_from_steps(user: str) -> ScenarioAnswer:
    """A well-behaved answer writer: each point quotes one answered step's first fact."""
    payload = user.split("STEPS:\n", 1)[1].split("\n\nPROBLEMS", 1)[0]
    steps = [s for s in json.loads(payload) if s["answered"] and s["facts"]]
    return ScenarioAnswer(
        headline="Exports are spread over more products than imports over partners.",
        points=[AnswerPoint(text=s["facts"][0] + ".", steps=[s["step"]]) for s in steps[:5]],
        conclusion="The data covers goods only.",
        step_notes=[{"step": s["step"], "text": "It adds one view of the spread."} for s in steps],
        charts=[s["step"] for s in steps][:2],
    )


def verdicts(user: str, bad_points: tuple[int, ...] = (), bad_headline: bool = False):
    """A reasoning check that finds the given points (1-based) or the headline unsupported."""
    drafted = json.loads(user.split("ANSWER:\n", 1)[1])
    ok = {"check": "follows", "supported": True, "problem": ""}
    bad = {"check": "the direction is wrong", "supported": False, "problem": "wrong direction"}
    return AnswerVerdicts(
        headline=bad if bad_headline else ok,
        points=[bad if p["point"] in bad_points else ok for p in drafted["points"]],
        conclusion=ok,
    )


@pytest.fixture
def builder(make_assistant, fake_llm, tmp_path):
    def _make(**responses):
        responses.setdefault("scenario_answer", answer_from_steps)
        responses.setdefault("scenario_review", verdicts)
        responses.setdefault("scenario_follow_up", FollowUps(follow_ups=[]))
        assistant = make_assistant(fake_llm(**responses))
        return ScenarioBuilder(assistant, ScenarioStore(tmp_path / "scn", tmp_path / "demo_scn"))

    return _make


def test_plan_keeps_only_checked_questions_and_retries_once(builder):
    first = plan_of(
        step("What share of exports did each chapter have in 2024?", EXPORTS_BY_PRODUCT),
        step(
            "What did Luxembourg import from Atlantis in 2024?",
            IMPORTS_BY_PARTNER.model_copy(update={"partners": ["ZZ"]}),
        ),
        step(
            "Which chapters led exports in 2019 and in 2024?",  # one snapshot cannot hold both
            EXPORTS_BY_PRODUCT.model_copy(update={"period_start": "2019", "period_end": "2019"}),
        ),
        step("Shares of exports by chapter, 2024?", EXPORTS_BY_PRODUCT),  # the same query again
    )
    third = step("How did iron and steel exports develop from 2019 to 2024?", STEEL_SERIES)
    b = builder(scenario_plan=[first, plan_of(*GOOD_PLAN.steps, third)])
    plan = b.plan(QUESTION, "en")
    assert [s.question for s in plan.steps] == [s.question for s in [*GOOD_PLAN.steps, third]]
    assert any("unknown codes" in n for n in plan.notes)
    assert any("names 2024 but the query covers 2019" in n for n in plan.notes)
    assert any("same as an earlier step" in n for n in plan.notes)
    assert [u["step"] for u in plan.llm_usage] == ["scenario_plan", "scenario_plan"]


def test_plan_lists_what_the_data_cannot_answer(builder):
    plan = builder(scenario_plan=GOOD_PLAN).plan("How do exports compare with GDP?", "en")
    assert plan.out_of_scope  # GDP is blocked by the limitation guard (S02)


def test_run_asks_follows_up_answers_and_saves(builder):
    follow = FollowUp(
        question="How did iron and steel exports develop from 2019 to 2024?",
        purpose="Step 1 shows iron and steel among the main exports.",
        builds_on=[1, 9],
        spec=STEEL_SERIES,
    )
    again = FollowUp(
        question="Shares of exports by chapter in 2024?",
        purpose="repeat",
        builds_on=[1],
        spec=EXPORTS_BY_PRODUCT,
    )
    b = builder(scenario_plan=GOOD_PLAN, scenario_follow_up=FollowUps(follow_ups=[follow, again]))
    plan = b.plan(QUESTION, "en")
    steps = [StepInput(question=s.question, purpose=s.purpose, spec=s.spec) for s in plan.steps]
    rec = b.run(QUESTION, steps, plan=plan)

    assert rec.status == "answered" and rec.answer_source == "llm"
    assert [(s.n, s.kind) for s in rec.steps] == [(1, "plan"), (2, "plan"), (3, "follow-up")]
    assert rec.steps[2].builds_on == [1]  # step 9 does not exist
    assert any("same as an earlier step" in n for n in rec.notes)
    runs = b.records(rec)
    assert all(r.status == "answered" and r.session_id == rec.session_id for r in runs.values())
    assert {r.origin for r in runs.values()} == {"scenario"}
    assert rec.steps[0].queried.startswith("exports · by HS2 product")
    assert rec.steps[0].note == "It adds one view of the spread."
    assert b.store.load(rec.scenario_id) == rec
    assert b.assistant.sessions.get(rec.session_id).title == "Scenario: Spread of risk"
    assert {u["step"] for u in rec.llm_usage} == {
        "scenario_plan",
        "scenario_follow_up",
        "scenario_answer",
        "scenario_review",
    }
    assert rec.charts == [1, 2]


def test_an_invented_number_falls_back_to_the_template(builder):
    invented = ScenarioAnswer(
        headline="Exports grew by 42.42 %.",
        points=[AnswerPoint(text="Imports rose by 77.7 %.", steps=[1])],
        conclusion="",
        step_notes=[],
        charts=[],
    )
    b = builder(scenario_plan=GOOD_PLAN, scenario_answer=[invented, invented])
    plan = b.plan(QUESTION, "en")
    steps = [StepInput(question=s.question, spec=s.spec) for s in plan.steps]
    rec = b.run(QUESTION, steps, plan=plan, follow_ups=False)
    runs = b.records(rec)
    assert rec.answer_source == "template"
    assert [p["text"] for p in rec.points] == [runs[1].title, runs[2].title]
    assert sum("answer check failed" in n for n in rec.notes) == 2


def test_a_failing_point_is_removed_and_the_rest_kept(builder):
    def one_bad_point(user: str) -> ScenarioAnswer:
        good = answer_from_steps(user)
        bad = AnswerPoint(text="Imports rose by about 400 million.", steps=[2])
        return good.model_copy(update={"points": [*good.points, bad]})

    b = builder(scenario_plan=GOOD_PLAN, scenario_answer=one_bad_point)
    plan = b.plan(QUESTION, "en")
    steps = [StepInput(question=s.question, spec=s.spec) for s in plan.steps]
    rec = b.run(QUESTION, steps, plan=plan, follow_ups=False)
    assert rec.answer_source == "llm" and len(rec.points) == 2
    assert not any("400 million" in p["text"] for p in rec.points)
    assert any("removed from the answer: point 3: number 400" in n for n in rec.notes)


def test_check_answer_needs_citations_facts_and_known_countries(builder):
    b = builder(scenario_plan=GOOD_PLAN)
    plan = b.plan(QUESTION, "en")
    rec = b.run(
        QUESTION, [StepInput(question=s.question, spec=s.spec) for s in plan.steps], plan=plan
    )
    runs = b.records(rec)
    fact = runs[2].facts[1]["text"]  # e.g. "#1 Germany: … bn €, … %": a fact of step 2 only
    sem = b.assistant.sem
    ok = ScenarioAnswer(
        headline="Imports come from a few partners.",
        points=[AnswerPoint(text=fact, steps=[2]), AnswerPoint(text=fact, steps=[2])],
        conclusion="Goods only.",
        step_notes=[],
        charts=[],
    )
    assert check_answer(ok, runs, QUESTION, sem, "en") == []
    wrong_step = ok.model_copy(update={"points": [AnswerPoint(text=fact, steps=[1])] * 2})
    assert any("point 1: number" in p for p in check_answer(wrong_step, runs, QUESTION, sem, "en"))
    uncited = ok.model_copy(update={"points": [AnswerPoint(text="Spread out.", steps=[])] * 2})
    assert any(
        "cites no answered step" in p for p in check_answer(uncited, runs, QUESTION, sem, "en")
    )
    # a country no answered step returned: step 1 ranks products, so Japan is not in its result
    products_only = {1: runs[1]}
    elsewhere = ok.model_copy(
        update={
            "points": [AnswerPoint(text="Products are spread out.", steps=[1])] * 2,
            "conclusion": "Japan matters too.",
        }
    )
    problems = check_answer(elsewhere, products_only, QUESTION, sem, "en")
    assert any("Japan" in p for p in problems)
    future = ok.model_copy(update={"headline": "Imports are projected to rise."})
    assert any("projected" in p for p in check_answer(future, runs, QUESTION, sem, "en"))


def test_an_edited_question_is_read_by_the_assistant_itself(builder):
    b = builder(
        scenario_plan=GOOD_PLAN,
        interpret=interp(intent="ranking", breakdown="partner", flow="export", period_start="2024"),
    )
    plan = b.plan(QUESTION, "en")
    steps = [
        StepInput(question=plan.steps[0].question, spec=plan.steps[0].spec),
        StepInput(question="Who bought most of our exports in 2024?", kind="own"),
    ]
    rec = b.run(QUESTION, steps, plan=plan, follow_ups=False)
    runs = b.records(rec)
    assert [s.kind for s in rec.steps] == ["plan", "own"]
    assert runs[2].origin == "ask" and runs[2].spec["breakdown"] == "partner"


def test_report_and_re_verify(builder):
    b = builder(scenario_plan=GOOD_PLAN)
    plan = b.plan(QUESTION, "en")
    rec = b.run(QUESTION, [StepInput(question=s.question, spec=s.spec) for s in plan.steps])
    runs = b.records(rec)
    report = to_markdown(rec, runs)
    assert rec.scenario_id in report and all(r.run_id in report for r in runs.values())
    assert "```sql" in report
    assert set(b.verify(rec)) == {1, 2}
    assert all("reproduces exactly" in v for v in b.verify(rec).values())


def test_offline_builder_cannot_plan(make_assistant, tmp_path):
    b = ScenarioBuilder(make_assistant(None), ScenarioStore(tmp_path / "s", tmp_path / "d"))
    assert not b.online
    with pytest.raises(LLMError):
        b.plan(QUESTION, "en")


@pytest.mark.parametrize(
    ("question", "spec", "problem"),
    [
        ("Top chapters in 2024?", EXPORTS_BY_PRODUCT, None),
        ("Top chapters in 2019 and in 2024?", EXPORTS_BY_PRODUCT, "names 2019"),
        (
            "Top chapters from 2019 to 2024?",
            EXPORTS_BY_PRODUCT.model_copy(update={"period_start": "2019"}),
            "add up 2019–2024",
        ),
        (
            "Largest changes from 2019 to 2024?",
            EXPORTS_BY_PRODUCT.model_copy(update={"period_start": "2019", "measure": "change"}),
            None,
        ),
        ("Iron and steel from 2019 to 2024?", STEEL_SERIES, None),
    ],
)
def test_mismatch_between_question_and_query(question, spec, problem):
    found = mismatch(question, spec.model_dump(mode="json"))
    assert (found is None) if problem is None else (problem in found)


def test_a_number_quoted_next_to_the_wrong_years_is_caught(builder):
    crisis = QuerySpec(
        intent="ranking",
        breakdown="product",
        flow="export",
        measure="change",
        period_start="2019",
        period_end="2020",
    )
    later = crisis.model_copy(update={"period_start": "2023", "period_end": "2024"})
    plan = plan_of(
        step("Which chapters' exports fell most from 2019 to 2020?", crisis),
        step("Which chapters' exports fell most from 2023 to 2024?", later),
    )
    b = builder(scenario_plan=plan)
    checked = b.plan(QUESTION, "en")
    rec = b.run(QUESTION, [StepInput(question=s.question, spec=s.spec) for s in checked.steps])
    runs = b.records(rec)
    fact = next(f["text"] for f in runs[1].facts if "%" in f["text"])
    pct = fact.rsplit("(", 1)[1].split(",")[-1].strip(" )")  # e.g. "−12.3 %", a 2019–2020 change
    good = AnswerPoint(text=f"Between 2019 and 2020 one chapter changed by {pct}.", steps=[1, 2])
    wrong = AnswerPoint(text=f"Between 2023 and 2024 one chapter changed by {pct}.", steps=[1, 2])
    answer = ScenarioAnswer(
        headline="Chapters fell.",
        points=[good, good, wrong],
        conclusion="",
        step_notes=[],
        charts=[],
    )
    review = review_answer(answer, runs, QUESTION, b.assistant.sem, "en")
    assert list(review.points) == [2]
    assert "comes from step 1 (2019–2020), not from 2023, 2024" in review.points[2][0]


@pytest.mark.parametrize(
    ("main_question", "level"),
    [
        ("Which goods break first in a crisis?", "HS2"),
        ("Which HS4 headings break first in a crisis?", "HS4"),
    ],
)
def test_proposed_rankings_stay_at_chapter_level_unless_detail_is_asked(
    builder, main_question, level
):
    headings = EXPORTS_BY_PRODUCT.model_copy(update={"product_level": "HS4"})
    plan = plan_of(
        step("What share of exports did each product have in 2024?", headings),
        step("What share of imports came from each partner in 2024?", IMPORTS_BY_PARTNER),
    )
    checked = builder(scenario_plan=plan).plan(main_question, "en")
    assert checked.steps[0].spec.product_level == level
    assert any("ranked by chapter" in n for n in checked.notes) == (level == "HS2")


def test_the_reasoning_check_removes_a_point_that_does_not_follow(builder):
    def three_points(user: str) -> ScenarioAnswer:
        good = answer_from_steps(user)
        return good.model_copy(update={"points": [*good.points, good.points[0]]})

    b = builder(
        scenario_plan=GOOD_PLAN,
        scenario_answer=three_points,
        scenario_review=lambda user: verdicts(user, bad_points=(3,)),
    )
    plan = b.plan(QUESTION, "en")
    steps = [StepInput(question=s.question, spec=s.spec) for s in plan.steps]
    rec = b.run(QUESTION, steps, plan=plan, follow_ups=False)
    assert rec.answer_source == "llm" and len(rec.points) == 2
    assert any("removed by the reasoning check: point 3: wrong direction" in n for n in rec.notes)


def test_a_headline_that_does_not_follow_is_redrafted(builder):
    b = builder(
        scenario_plan=GOOD_PLAN,
        scenario_review=[
            lambda user: verdicts(user, bad_headline=True),
            lambda user: verdicts(user),
        ],
    )
    plan = b.plan(QUESTION, "en")
    steps = [StepInput(question=s.question, spec=s.spec) for s in plan.steps]
    rec = b.run(QUESTION, steps, plan=plan, follow_ups=False)
    assert rec.answer_source == "llm"
    assert any("reasoning check failed: headline: wrong direction" in n for n in rec.notes)
    calls = [step for step, _ in b.assistant.llm.calls]
    assert calls.count("scenario_answer") == 2 and calls.count("scenario_review") == 2
    redraft = [user for step, user in b.assistant.llm.calls if step == "scenario_answer"][1]
    assert "PROBLEMS in the previous draft" in redraft and "wrong direction" in redraft


def test_a_proposed_share_of_nothing_is_dropped():
    whole = QuerySpec(
        intent="time_series",
        flow="export",
        measure="share",
        period_start="2005",
        period_end="2025",
        freq="A",
    )
    resolved = whole.model_copy(update={"measure": "value_eur"}).model_dump(mode="json")
    found = mismatch("Share of the top 3 exports from 2005 to 2025?", resolved, whole)
    assert "a share needs a breakdown" in found


def test_check_step_reads_scores_and_places_an_added_question(builder):
    from luxtrade.agents.scenario import FitVerdict

    b = builder(
        scenario_plan=GOOD_PLAN,
        interpret=interp(
            intent="time_series",
            products=["72"],
            flow="export",
            period_start="2019",
            period_end="2024",
            freq="A",
        ),
        scenario_fit=FitVerdict(fits=True, problem="", position=1),
    )
    chain = [
        ("What share of exports did each chapter have in 2024?", "baseline"),
        ("How did iron and steel exports develop from 2019 to 2024?", ""),
    ]
    check = b.check_step(QUESTION, chain, 2, "en", [EXPORTS_BY_PRODUCT, None])
    assert check.ok and check.spec.products == ["72"]
    assert check.queried.startswith("exports · products 72")
    assert check.position == 1 and any("step 1" in w for w in check.warnings)


def test_check_step_flags_a_question_the_data_cannot_answer(builder):
    from luxtrade.agents.scenario import FitVerdict

    b = builder(
        scenario_plan=GOOD_PLAN,
        interpret=interp(intent="ranking", breakdown="product", unresolved=["tourists"]),
        scenario_fit=FitVerdict(fits=False, problem="about tourism", position=2),
    )
    chain = [("Shares of exports by chapter in 2024?", ""), ("How many tourists came?", "")]
    check = b.check_step(QUESTION, chain, 2, "en", [EXPORTS_BY_PRODUCT, None])
    assert not check.ok and check.spec is None
    assert any("tourists" in p for p in check.problems) and "about tourism" in check.warnings


def test_a_reading_note_does_not_block_a_question_that_passes_the_checks(builder):
    from luxtrade.agents.scenario import FitVerdict
    from luxtrade.agents.spec import Ambiguity

    crisis = dict(
        intent="ranking",
        breakdown="product",
        flow="export",
        measure="change",
        period_start="2022",
        period_end="2023",
    )
    note = Ambiguity(dimension="what", text="energy crisis read as the period 2022-2023")
    b = builder(
        scenario_plan=GOOD_PLAN,
        interpret=interp(**crisis, ambiguities=[note]),  # seen on real data
        scenario_fit=FitVerdict(fits=True, problem="", position=2),
    )
    chain = [
        ("Shares of exports in 2024?", ""),
        ("Largest falls 2022 to 2023 (energy crisis)?", ""),
    ]
    check = b.check_step(QUESTION, chain, 2, "en", [EXPORTS_BY_PRODUCT, None])
    assert check.ok and not check.warnings
    assert check.notes == ["read as: energy crisis read as the period 2022-2023"]


def test_a_failing_question_gets_checked_rewrites_and_a_hint(builder):
    from luxtrade.agents.scenario import FitVerdict
    from luxtrade.agents.spec import OptimiserOutput, Suggestion

    good = Suggestion(
        question="Main import chapters in 2024?", note="imports", spec=IMPORTS_BY_PARTNER
    )
    bad = Suggestion(
        question="Main export chapters in 2019 and 2024?",  # one snapshot cannot hold both years
        note="two years",
        spec=EXPORTS_BY_PRODUCT,
    )
    b = builder(
        scenario_plan=GOOD_PLAN,
        interpret=interp(intent="ranking", breakdown="product", unresolved=["banks"]),
        scenario_fit=FitVerdict(fits=False, problem="about banks", position=2),
        optimise=OptimiserOutput(suggestions=[good, bad], missing_hint="Name the flow and year."),
    )
    chain = [("Shares of exports in 2024?", ""), ("What did banks finance?", "")]
    check = b.check_step(QUESTION, chain, 2, "en", [EXPORTS_BY_PRODUCT, None])
    assert not check.ok and check.hint == "Name the flow and year."
    assert [a.question for a in check.alternatives] == ["Main import chapters in 2024?"]
    assert check.alternatives[0].queried.startswith("imports · by partner")
