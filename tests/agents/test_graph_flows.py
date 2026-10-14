"""End-to-end graph flows with a scripted LLM (no network)."""

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
    assert second.followup_of == first.run_id and second.inherited == ["intent", "breakdown"]
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


def test_custom_sql_prompt_contains_examples():
    from luxtrade.agents.interpret import prompt

    p = prompt("custom_sql")
    assert "Examples:" in p
    assert "v_lu_trade" in p
    assert "LIMIT 1000" in p


def test_custom_sql_prompt_receives_candidates_and_language(make_assistant, fake_llm):
    llm = fake_llm(
        interpret=interp(
            intent="time_series", partners=["DE", "FR"], needs_custom_sql=True, language="fr"
        ),
        custom_sql=CustomSQL(
            sql="SELECT period, sum(value_eur) AS value_eur FROM v_lu_trade_hs2 GROUP BY period",
            explanation="Évolution mensuelle",
        ),
    )
    rec = make_assistant(llm).ask("Mois inhabituels pour l'Allemagne et la France")
    assert rec.status == "answered"
    sql_call = next(prompt for step, prompt in llm.calls if step == "custom_sql")
    assert "LANGUAGE: fr" in sql_call
    assert "CANDIDATES:" in sql_call
    assert "DE" in sql_call and "FR" in sql_call


def test_custom_sql_insight_with_partner_name_passes_grounding(make_assistant, fake_llm):
    llm = fake_llm(
        interpret=interp(intent="time_series", partners=["DE"], needs_custom_sql=True),
        custom_sql=CustomSQL(
            sql="SELECT 'DE' AS partner, 500.0 AS value_eur FROM v_lu_trade_hs2",
            explanation="Exports to Germany",
        ),
        insight=InsightOutput(
            sentences=[
                "Exports to Germany were 500 EUR.",
                "Trade remained steady across the period.",
                "Germany was the primary destination.",
                "Historical trends indicate stability.",
                "See notes for confidential data limits.",
            ]
        ),
    )
    rec = make_assistant(llm).ask("Custom query for Germany")
    assert rec.status == "answered"
    assert rec.insight_source == "llm"


def test_custom_sql_retries_on_empty_result_before_optimising(make_assistant, fake_llm):
    llm = fake_llm(
        interpret=interp(intent="time_series", needs_custom_sql=True),
        custom_sql=[
            CustomSQL(
                sql=(
                    "SELECT period, sum(value_eur) AS value_eur "
                    "FROM v_lu_trade_hs2 WHERE year = 1990 GROUP BY period"
                ),
                explanation="empty year",
            ),
            CustomSQL(
                sql=(
                    "SELECT period, sum(value_eur) AS value_eur "
                    "FROM v_lu_trade_hs2 WHERE year = 2024 GROUP BY period ORDER BY period"
                ),
                explanation="valid year",
            ),
        ],
    )
    rec = make_assistant(llm).ask("Trade in an unusual period")
    assert rec.status == "answered"
    query_traces = [t for t in rec.trace if t["node"] == "query"]
    assert len(query_traces) == 2




