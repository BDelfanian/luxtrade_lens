import pytest

from luxtrade.agents import supervisor
from luxtrade.agents.facts import Fact, FactSheet
from luxtrade.agents.grounding import check, parse_numbers
from luxtrade.agents.spec import Ambiguity, Interpretation, Limitation, QuerySpec


@pytest.mark.parametrize(
    ("text", "lang", "expected"),
    [
        ("16.25 bn € and 1,234.5", "en", [16.25, 1234.5]),
        ("16,25 Md € et 1 234,5", "fr", [16.25, 1234.5]),
        ("16,25 Mrd. € und 1.234,5", "de", [16.25, 1234.5]),
        ("in 2025 16,2 %", "fr", [2025, 16.2]),
    ],
)
def test_parse_numbers_by_locale(text, lang, expected):
    assert [v for v, _ in parse_numbers(text, lang)] == expected


def _sheet(lang="en"):
    return FactSheet(
        language=lang,
        question="Main partners in 2025?",
        entities=["DE"],
        facts=[
            Fact(key="a", text="exports 2025: 16.25 bn €"),
            Fact(key="b", text="#1 Germany: 4.95 bn €, 29.1 %"),
        ],
    )


def test_grounded_text_passes(semantic):
    text = [
        "In 2025 exports were 16.25 bn €.",
        "Germany led with 4.95 bn €.",
        "That is 29.1 %.",
        "About 16.3 bn € in total.",
    ]
    assert check(text, _sheet(), semantic) == []


def test_invented_number_and_partner_are_caught(semantic):
    problems = check(["Exports were 17.4 bn €.", "France led.", "x", "y"], _sheet(), semantic)
    assert any("17.4" in p for p in problems)
    assert any("France" in p for p in problems)


def _state(**kw):
    base = {"retries": {}, "limitations": [], "status": None}
    base.update(kw)
    return base


def test_entry_routes():
    assert supervisor.entry(_state(spec=QuerySpec(intent="ranking"))) == "guard_pre"
    assert supervisor.entry(_state(force_optimise=True)) == "optimise"
    assert supervisor.entry(_state()) == "interpret"


def test_minor_ambiguity_answers_core_ambiguity_optimises():
    minor = Interpretation(
        spec=QuerySpec(intent="ranking"),
        ambiguities=[Ambiguity(dimension="when", text="no period")],
    )
    core = Interpretation(
        spec=QuerySpec(intent="ranking"),
        ambiguities=[Ambiguity(dimension="who", text="'Asia' is not a group")],
    )
    assert (
        supervisor.after_interpret(_state(interpretation=minor, retries={"interpret": 1}))
        == "guard_pre"
    )
    assert (
        supervisor.after_interpret(_state(interpretation=core, retries={"interpret": 1}))
        == "optimise"
    )


def test_unresolved_retries_once():
    i = Interpretation(spec=QuerySpec(intent="ranking"), unresolved=["Gaul"])
    assert (
        supervisor.after_interpret(_state(interpretation=i, retries={"interpret": 1}))
        == "interpret"
    )
    assert (
        supervisor.after_interpret(_state(interpretation=i, retries={"interpret": 2})) == "optimise"
    )


def test_blocked_goes_to_optimiser_and_reason_names_the_limit():
    lim = Limitation(id="S02", key="no_external_data", severity="block", message="GDP is not here")
    state = _state(limitations=[lim])
    assert supervisor.after_guard_pre(state) == "optimise"
    assert "S02" in supervisor.optimiser_reason(state)


def test_query_retry_only_for_llm_sql():
    assert (
        supervisor.after_query(_state(sql_error="x", custom_sql=True, retries={"query": 1}))
        == "query"
    )
    assert (
        supervisor.after_query(_state(sql_error="x", custom_sql=True, retries={"query": 3}))
        == "optimise"
    )
    assert (
        supervisor.after_query(_state(sql_error="x", custom_sql=False, retries={"query": 1}))
        == "optimise"
    )
    assert supervisor.after_query(_state(status="no_data")) == "optimise"
    assert supervisor.after_query(_state()) == "guard_post"


def test_year_spans_and_event_names_are_not_read_as_statistics():
    from luxtrade.agents.grounding import unsupported_numbers

    text = "In the 2022–23 aftershock and during COVID-19, exports fell 3.7 %."
    assert unsupported_numbers(text, [2022.0, 2023.0, 3.7], "en") == []
    assert unsupported_numbers("Exports fell 23 % in 2023.", [2023.0], "en") != []
