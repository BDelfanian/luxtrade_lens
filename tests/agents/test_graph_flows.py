"""End-to-end graph flows with a scripted LLM (no network)."""

import pytest
from conftest import insight_from_facts

from luxtrade.agents.llm import LLMError
from luxtrade.agents.presets import preset
from luxtrade.agents.spec import (
    Ambiguity,
    CustomSQL,
    InsightOutput,
    Interpretation,
    OptimiserOutput,
    QuerySpec,
    Suggestion,
)


def interp(**spec_fields):
    extra = {
        k: spec_fields.pop(k)
        for k in list(spec_fields)
        if k
        in (
            "followup_of",
            "inherited",
            "view_only",
            "ambiguities",
            "unresolved",
            "out_of_scope",
            "needs_custom_sql",
        )
    }
    return Interpretation(spec=QuerySpec(**spec_fields), **extra)


def test_question_is_answered_with_a_grounded_llm_insight(make_assistant, fake_llm):
    llm = fake_llm(interpret=interp(intent="ranking", breakdown="partner", flow="export"))
    rec = make_assistant(llm).ask("Who are Luxembourg's main export partners?")
    assert rec.status == "answered"
    assert rec.insight_source == "llm"
    assert rec.view_kind in ("map", "bar")
    assert rec.sql and "v_lu_trade" in rec.sql
    assert rec.frames["main"] and rec.result_hash
    assert [t["node"] for t in rec.trace] == [
        "interpret",
        "guard_pre",
        "query",
        "guard_post",
        "analyse",
        "insight",
    ]
    assert "latest complete year 2025 (no period given)" in rec.assumptions


def test_insight_with_an_invented_number_falls_back_to_the_template(make_assistant, fake_llm):
    bad = InsightOutput(
        sentences=["Exports reached 999.99 bn €.", "Germany leads.", "More.", "End."]
    )
    llm = fake_llm(
        interpret=interp(intent="ranking", breakdown="partner", flow="export"), insight=[bad, bad]
    )
    rec = make_assistant(llm).ask("Main export partners?")
    assert rec.status == "answered" and rec.insight_source == "template"
    insight_step = next(t for t in rec.trace if t["node"] == "insight")
    assert "999.99" in insight_step["detail"] and insight_step["outcome"] == "fallback"


def test_vague_question_gets_three_validated_suggestions(make_assistant, fake_llm):
    good = Suggestion(
        question="How did exports to Germany evolve since 2015?",
        note="exports, DE",
        spec=QuerySpec(intent="time_series", partners=["DE"], flow="export", period_start="2015"),
    )
    unknown = Suggestion(
        question="Exports to Atlantis?", note="x", spec=QuerySpec(intent="ranking", partners=["ZZ"])
    )
    blocked = Suggestion(
        question="Exports as a share of GDP?", note="x", spec=QuerySpec(intent="single_value")
    )
    llm = fake_llm(
        interpret=interp(
            intent="time_series",
            ambiguities=[Ambiguity(dimension="intent", text="unclear what to measure")],
        ),
        optimise=[
            OptimiserOutput(suggestions=[good, unknown, blocked], missing_hint="Which partner?")
        ]
        * 2,
    )
    rec = make_assistant(llm).ask("How is our trade doing?")
    assert rec.status == "suggestions" and rec.sql is None
    questions = [s["question"] for s in rec.suggestions]
    assert len(questions) == 3 and questions[0] == good.question
    assert "Exports to Atlantis?" not in questions and "Exports as a share of GDP?" not in questions
    assert rec.missing_hint == "Which partner?"


def test_unresolved_entity_is_retried_once_then_optimised(make_assistant, fake_llm):
    llm = fake_llm(
        interpret=[
            interp(intent="ranking", unresolved=["widgets"]),
            interp(intent="ranking", unresolved=["widgets"]),
        ],
        optimise=LLMError("offline"),
    )
    rec = make_assistant(llm).ask("Who buys our widgets?")
    assert [t["node"] for t in rec.trace] == ["interpret", "interpret", "optimise"]
    assert rec.status == "suggestions" and len(rec.suggestions) == 3  # presets fill the slots


def test_out_of_scope_question_is_blocked_with_alternatives(make_assistant, fake_llm):
    llm = fake_llm(
        interpret=interp(intent="single_value", out_of_scope=["S02"]), optimise=LLMError("offline")
    )
    rec = make_assistant(llm).ask("What share of Luxembourg's GDP is exports?")
    assert rec.status == "blocked"
    assert "S02" in {lim["id"] for lim in rec.limitations}
    assert rec.suggestions and rec.sql is None


def test_follow_up_inherits_context_and_is_traced(make_assistant, fake_llm):
    first_spec = dict(intent="ranking", breakdown="partner", flow="export")
    llm = fake_llm(interpret=[interp(**first_spec)])
    assistant = make_assistant(llm)
    first = assistant.ask("Main export partners?")

    llm.responses["interpret"] = [
        interp(
            **{**first_spec, "flow": "import"},
            followup_of=first.run_id,
            inherited=["intent", "breakdown"],
        )
    ]
    second = assistant.ask("And for imports?", session_id=first.session_id)
    assert second.origin == "followup" and second.turn == 2
    assert second.followup_of == first.run_id and second.inherited[:2] == ["intent", "breakdown"]
    # fields the follow-up left open come from the first turn's resolved spec
    assert {"freq", "product_level", "top_n", "period_start", "period_end"} <= set(second.inherited)
    assert second.spec["period_start"] == first.spec["period_start"]
    assert second.spec["flow"] == "import"
    assert first.run_id in llm.calls[-2][1]  # the interpreter saw the previous turn in its context


def test_follow_up_to_an_unknown_turn_is_treated_as_new(make_assistant, fake_llm):
    llm = fake_llm(
        interpret=interp(
            intent="ranking", breakdown="partner", followup_of="deadbeef00", inherited=["flow"]
        )
    )
    rec = make_assistant(llm).ask("And for imports?")
    assert rec.followup_of is None and rec.inherited == [] and rec.origin == "ask"


def test_view_only_follow_up_rerenders_without_new_insight_call(make_assistant, fake_llm):
    llm = fake_llm(interpret=[interp(intent="ranking", breakdown="product", flow="export")])
    assistant = make_assistant(llm)
    first = assistant.ask("Main exported goods?")
    llm.responses["interpret"] = [
        interp(intent="ranking", view="table", followup_of=first.run_id, view_only=True)
    ]
    insight_calls = sum(1 for step, _ in llm.calls if step == "insight")
    second = assistant.ask("Show it as a table", session_id=first.session_id)
    assert second.view_kind == "table" and second.spec["breakdown"] == "product"
    assert sum(1 for step, _ in llm.calls if step == "insight") == insight_calls


def test_custom_sql_is_guarded_and_retried(make_assistant, fake_llm):
    llm = fake_llm(
        interpret=interp(intent="time_series", needs_custom_sql=True),
        custom_sql=[
            CustomSQL(sql="SELECT * FROM trade", explanation="bad"),
            CustomSQL(
                sql="SELECT period, sum(value_eur) AS value_eur FROM v_lu_trade_hs2 "
                "WHERE flow = 'export' GROUP BY period ORDER BY period",
                explanation="Monthly exports",
            ),
        ],
    )
    rec = make_assistant(llm).ask("Months where exports were unusual")
    assert rec.status == "answered" and rec.custom_sql
    assert [t["outcome"] for t in rec.trace if t["node"] == "query"] == ["retry", "ok"]


def test_offline_mode_presets_work_and_questions_explain(make_assistant):
    assistant = make_assistant(llm=None)
    question, spec = preset("Q1").for_language("de")
    rec = assistant.run_spec(spec, question=question, origin="preset")
    assert rec.status == "answered" and rec.language == "de"
    assert rec.insight_source == "template" and "Exporte" in " ".join(rec.insight)
    asked = assistant.ask("Who are our main partners?", session_id=rec.session_id)
    assert asked.status == "error" and "ANTHROPIC_API_KEY" in asked.error


def test_every_preset_answers_offline(make_assistant):
    assistant = make_assistant(llm=None)
    for pid in ("Q1", "Q2", "Q3", "Q4", "Q5", "Q6"):
        question, spec = preset(pid).for_language("en")
        rec = assistant.run_spec(spec, question=question, origin="preset")
        assert rec.status == "answered", (pid, rec.error)
        assert rec.insight and rec.title


def test_re_verify_reproduces_the_result(make_assistant):
    assistant = make_assistant(llm=None)
    question, spec = preset("Q2").for_language("en")
    rec = assistant.run_spec(spec, question=question, origin="preset")
    assert assistant.verify(rec).startswith("✅")
    tampered = rec.model_copy(update={"result_hash": "0" * 64})
    assert assistant.verify(tampered).startswith("⚠️")


def test_session_history_is_stored_and_searchable(make_assistant):
    assistant = make_assistant(llm=None)
    q1, s1 = preset("Q1").for_language("en")
    q6, s6 = preset("Q6").for_language("en")
    first = assistant.run_spec(s1, question=q1, origin="preset")
    second = assistant.run_spec(s6, question=q6, origin="preset", session_id=first.session_id)
    sessions = assistant.sessions
    assert [r.run_id for r in sessions.records(first.session_id)] == [first.run_id, second.run_id]
    assert sessions.search(second.run_id)[0].session_id == first.session_id
    assert sessions.search("seasonal")[0].session_id == first.session_id
    assert assistant.runs.load(second.run_id).turn == 2


def test_one_paragraph_insight_is_split_into_sentences(make_assistant, fake_llm):
    def one_paragraph(user):
        sentences = insight_from_facts(user).sentences
        return InsightOutput(sentences=[" ".join(f"Fact {s}" for s in sentences)])

    llm = fake_llm(
        interpret=interp(intent="ranking", breakdown="partner", flow="export"),
        insight=one_paragraph,
    )
    rec = make_assistant(llm).ask("Main export partners?")
    assert rec.insight_source == "llm" and len(rec.insight) >= 3


def test_blocked_topic_wins_over_an_unclear_interpretation(make_assistant, fake_llm):
    llm = fake_llm(
        interpret=interp(
            intent="single_value",
            ambiguities=[Ambiguity(dimension="what", text="GDP is not in the data")],
        ),
        optimise=LLMError("offline"),
    )
    rec = make_assistant(llm).ask("What share of Luxembourg's GDP is exports?")
    assert rec.status == "blocked"
    assert "S02" in {lim["id"] for lim in rec.limitations}
    assert [t["node"] for t in rec.trace] == ["interpret", "guard_pre", "optimise"]


def test_follow_up_never_filters_on_the_previous_result_codes(make_assistant, fake_llm):
    first_spec = dict(intent="ranking", breakdown="product", flow="export", period_start="2024")
    llm = fake_llm(interpret=[interp(**first_spec)])
    assistant = make_assistant(llm)
    first = assistant.ask("Main export products in 2024?")
    result_codes = [r["key"] for r in first.frames["main"] if r.get("kind") == "item"]
    llm.responses["interpret"] = [
        interp(  # the LLM copies the ranked result into the filter (seen on real data)
            **{**first_spec, "flow": "import", "products": result_codes},
            followup_of=first.run_id,
            inherited=["intent", "breakdown", "period_start", "products"],
        )
    ]
    second = assistant.ask("and for imports?", session_id=first.session_id)
    assert second.spec["products"] == [] and second.spec["flow"] == "import"


def test_elliptical_question_is_a_follow_up_even_if_the_llm_misses_it(make_assistant, fake_llm):
    first_spec = dict(
        intent="ranking", breakdown="product", flow="import", period_start="2024", period_end="2024"
    )
    llm = fake_llm(interpret=[interp(**first_spec)])
    assistant = make_assistant(llm)
    first = assistant.ask("Main import products in 2024?")
    llm.responses["interpret"] = [interp(intent="ranking", breakdown="product", partners=["BE"])]
    second = assistant.ask("only from Belgium", session_id=first.session_id)
    assert second.followup_of == first.run_id and second.origin == "followup"
    assert second.spec["partners"] == ["BE"] and second.spec["flow"] == "import"
    assert second.spec["period_start"] == second.spec["period_end"] == "2024"


def test_unrelated_question_is_not_forced_into_a_follow_up(make_assistant, fake_llm):
    llm = fake_llm(interpret=[interp(intent="ranking", breakdown="partner", flow="export")])
    assistant = make_assistant(llm)
    first = assistant.ask("Main export partners?")
    llm.responses["interpret"] = [interp(intent="time_series", products=["27"])]
    second = assistant.ask(
        "How did imports of mineral fuels evolve since 2010?", session_id=first.session_id
    )
    assert second.followup_of is None and second.spec["flow"] != "export"


def test_confidential_share_question_is_answered_with_the_confidential_part_first(
    make_assistant, fake_llm
):
    llm = fake_llm(
        interpret=interp(
            intent="composition", breakdown="confidentiality", products=["27"], flow="import"
        )
    )
    rec = make_assistant(llm).ask("How much of the mineral fuel imports is confidential?")
    assert rec.status == "answered" and rec.view_kind == "bar"
    main = rec.frame("main")
    assert main.iloc[0]["key"] == "CONFIDENTIAL" and main["share"].sum() == pytest.approx(100)
    assert rec.title.startswith("Confidential — imports")
    assert rec.entities == {}  # split keys are not codes a follow-up could refer to


def test_eu_share_question_is_answered_in_french(make_assistant, fake_llm):
    llm = fake_llm(
        interpret=interp(
            language="fr", intent="composition", breakdown="partner_group", flow="import"
        )
    )
    rec = make_assistant(llm).ask("Quelle est la part de l'UE dans les importations ?")
    assert rec.status == "answered"
    assert rec.frame("main").iloc[0]["key"] == "EU27"
    assert rec.title.startswith("Pays de l'UE27 — importations")
