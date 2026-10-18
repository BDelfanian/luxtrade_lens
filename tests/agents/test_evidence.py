"""Evidence figures: comparable steps become one chart and key figures, computed by code."""

from types import SimpleNamespace

from luxtrade.agents.evidence import compose
from luxtrade.agents.spec import QuerySpec


def change(y0: str, y1: str) -> QuerySpec:
    return QuerySpec(
        intent="ranking",
        breakdown="product",
        flow="export",
        measure="change",
        period_start=y0,
        period_end=y1,
    )


def share(year: str) -> QuerySpec:
    return QuerySpec(
        intent="composition",
        breakdown="product",
        flow="export",
        measure="share",
        period_start=year,
        period_end=year,
    )


def runs(assistant, specs):
    records = {
        n: assistant.run_spec(s, question=f"q{n}", origin="preset")
        for n, s in enumerate(specs, start=1)
    }
    return [SimpleNamespace(n=n) for n in records], records


def test_change_steps_compare_the_named_item_with_the_whole_flow(make_assistant, semantic):
    assistant = make_assistant()
    chain, records = runs(assistant, [change("2019", "2020"), change("2023", "2024")])
    label = next(r["label"] for r in records[1].frames["main"] if r["kind"] == "item")
    [fig] = compose(chain, records, f"{label} fell most.", "", semantic)
    assert fig.kind == "change" and fig.steps == [1, 2]
    assert {r["series"] for r in fig.rows} == {label, "All exports"}
    assert [r["group"] for r in fig.rows if r["series"] == label] == ["2019 → 2020", "2023 → 2024"]
    # the whole flow is the step's own SQL summed: the total change of all exports
    df = semantic.query(records[1].sql)
    by_year = df.groupby("year")["value_eur"].sum()
    whole = next(r["value"] for r in fig.rows if r["series"] == "All exports" and r["step"] == 1)
    assert abs(whole - 100 * (by_year[2020] / by_year[2019] - 1)) < 1e-9
    assert fig.tiles[0]["label"].startswith(label)


def test_share_steps_compare_two_years_and_unrelated_steps_make_no_chart(make_assistant, semantic):
    assistant = make_assistant()
    chain, records = runs(assistant, [share("2019"), share("2024"), change("2023", "2024")])
    figs = compose(chain, records, "Exports spread out.", "", semantic)
    assert [f.kind for f in figs] == ["share"]  # one change step alone is not a comparison
    assert {r["series"] for r in figs[0].rows} == {"2019", "2024"}
    assert len({r["group"] for r in figs[0].rows}) == 3  # the three largest items of 2024
    assert compose(chain[2:], records, "", "", semantic) == []
