"""Overview: Luxembourg's trade in goods at a glance, the app's landing page (SOLUTION_DESIGN §8a).

Five fixed business questions. Each one is a ``QuerySpec`` run through the same deterministic
path as a preset (defaults → compiled SQL → SQL guard → analysis), so a panel's numbers equal
what its "Explore" run returns in the assistant. No LLM is involved: every sentence is a template
filled with numbers from the SQL that is shown as evidence.
"""

from dataclasses import dataclass, field

import pandas as pd

from luxtrade.agents import guard
from luxtrade.agents.analyse import Analysis, analyse
from luxtrade.agents.compile_sql import compile_spec
from luxtrade.agents.defaults import apply_defaults
from luxtrade.agents.findings import Finding, build_findings
from luxtrade.agents.presets import preset
from luxtrade.agents.spec import QuerySpec
from luxtrade.agents.sql_guard import check_sql
from luxtrade.analytics import rankings, timeseries
from luxtrade.config import DATASET_ID, REPORTER
from luxtrade.semantic.layer import SemanticLayer
from luxtrade.viz.format import flow_label, fmt_eur, fmt_number, fmt_pct

BASE_YEARS_BACK = 10  # structural comparisons: latest complete year vs ten years earlier
TOP_K = 5  # dependence: share of total trade with the five largest partners
BENCHMARK_BASE_YEAR = 2015  # same base as the benchmark default (agents/defaults.py)

# Reading aids on the long-run chart: well-known shocks, not data from this dataset.
REFERENCE_EVENTS = {
    2009: {"en": "Financial crisis", "fr": "Crise financière", "de": "Finanzkrise"},
    2020: {"en": "COVID-19", "fr": "COVID-19", "de": "COVID-19"},
    2022: {"en": "Energy crisis", "fr": "Crise énergétique", "de": "Energiekrise"},
}
MONTHS_LONG = {
    "en": "January February March April May June July August September October November December".split(),  # noqa: SIM905
    "fr": "janvier février mars avril mai juin juillet août septembre octobre novembre décembre".split(),  # noqa: SIM905
    "de": "Januar Februar März April Mai Juni Juli August September Oktober November Dezember".split(),  # noqa: SIM905
}

_T = {
    # business questions (panel headers)
    "q_trend": {
        "en": "How big is Luxembourg's trade in goods, and how has it changed?",
        "fr": "Quel est le poids du commerce de biens du Luxembourg, et comment a-t-il évolué ?",
        "de": "Wie groß ist Luxemburgs Warenhandel, und wie hat er sich entwickelt?",
    },
    "q_partners": {
        "en": "Who does Luxembourg trade with, and how dependent is it on a few partners?",
        "fr": "Avec qui le Luxembourg commerce-t-il, et dans quelle mesure dépend-il de quelques partenaires ?",
        "de": "Mit wem handelt Luxemburg, und wie stark hängt es von wenigen Partnern ab?",
    },
    "q_products": {
        "en": "What does Luxembourg sell and buy, and what is changing?",
        "fr": "Que vend et qu'achète le Luxembourg, et qu'est-ce qui change ?",
        "de": "Was verkauft und kauft Luxemburg, und was ändert sich?",
    },
    "q_season": {
        "en": "Is there a seasonal rhythm, and what is the trend without it?",
        "fr": "Existe-t-il un rythme saisonnier, et quelle est la tendance sans lui ?",
        "de": "Gibt es einen saisonalen Rhythmus, und wie verläuft der Trend ohne ihn?",
    },
    "q_peers": {
        "en": "How does Luxembourg compare with other EU countries?",
        "fr": "Comment le Luxembourg se situe-t-il par rapport à d'autres pays de l'UE ?",
        "de": "Wie steht Luxemburg im Vergleich zu anderen EU-Ländern da?",
    },
    # questions sent to the assistant by "Explore" (when no preset matches)
    "x_trend": {
        "en": "How have Luxembourg's exports and imports developed since {start}?",
        "fr": "Comment les exportations et les importations du Luxembourg ont-elles évolué depuis {start} ?",
        "de": "Wie haben sich Luxemburgs Exporte und Importe seit {start} entwickelt?",
    },
    "x_peers": {
        "en": "How has Luxembourg's trade developed since {start} compared with other EU countries?",
        "fr": "Comment le commerce du Luxembourg a-t-il évolué depuis {start} par rapport à d'autres pays de l'UE ?",
        "de": "Wie hat sich Luxemburgs Handel seit {start} im Vergleich zu anderen EU-Ländern entwickelt?",
    },
    # takeaways (one headline per panel, computed from the data)
    "t_deficit": {
        "en": "Imports exceed exports: a trade deficit of {bal} in {end}",
        "fr": "Les importations dépassent les exportations : déficit commercial de {bal} en {end}",
        "de": "Die Importe übersteigen die Exporte: Handelsdefizit von {bal} im Jahr {end}",
    },
    "t_surplus": {
        "en": "Exports exceed imports: a trade surplus of {bal} in {end}",
        "fr": "Les exportations dépassent les importations : excédent commercial de {bal} en {end}",
        "de": "Die Exporte übersteigen die Importe: Handelsüberschuss von {bal} im Jahr {end}",
    },
    "t_partners": {
        "en": "Five partners account for {c5} of Luxembourg's trade in {year}",
        "fr": "Cinq partenaires représentent {c5} du commerce du Luxembourg en {year}",
        "de": "Fünf Partner stehen für {c5} des Handels Luxemburgs im Jahr {year}",
    },
    "t_products": {
        "en": "Largest export: {name}, with {share} of exports in {year}",
        "fr": "Premier poste à l'exportation : {name}, avec {share} des exportations en {year}",
        "de": "Größter Exportposten: {name} mit {share} der Exporte im Jahr {year}",
    },
    "t_season": {
        "en": "Exports are usually strongest in {mmax} and weakest in {mmin}",
        "fr": "Les exportations sont généralement les plus fortes en {mmax} et les plus faibles en {mmin}",
        "de": "Die Exporte sind meist im {mmax} am stärksten und im {mmin} am schwächsten",
    },
    "t_peers": {
        "en": "Luxembourg's trade index reached {lu} in {end} ({start} = 100): rank {r} of the {n} countries compared",
        "fr": "L'indice des échanges du Luxembourg atteint {lu} en {end} (base {start} = 100) : {r} sur les {n} pays comparés",
        "de": "Luxemburgs Handelsindex erreichte {lu} im Jahr {end} ({start} = 100): Rang {r} unter {n} verglichenen Ländern",
    },
    # facts
    "growth": {
        "en": "Between {start} and {end}, exports went from {e0} to {e1} ({ecagr} a year) and imports from {i0} to {i1} ({icagr} a year).",
        "fr": "Entre {start} et {end}, les exportations sont passées de {e0} à {e1} ({ecagr} par an) et les importations de {i0} à {i1} ({icagr} par an).",
        "de": "Zwischen {start} und {end} entwickelten sich die Exporte von {e0} auf {e1} ({ecagr} pro Jahr) und die Importe von {i0} auf {i1} ({icagr} pro Jahr).",
    },
    "bal_deficit_all": {
        "en": "Imports exceeded exports in every year since {start}; the deficit was {bal} in {end}.",
        "fr": "Les importations ont dépassé les exportations chaque année depuis {start} ; le déficit atteignait {bal} en {end}.",
        "de": "Seit {start} lagen die Importe in jedem Jahr über den Exporten; {end} betrug das Defizit {bal}.",
    },
    "bal_surplus_all": {
        "en": "Exports exceeded imports in every year since {start}; the surplus was {bal} in {end}.",
        "fr": "Les exportations ont dépassé les importations chaque année depuis {start} ; l'excédent atteignait {bal} en {end}.",
        "de": "Seit {start} lagen die Exporte in jedem Jahr über den Importen; {end} betrug der Überschuss {bal}.",
    },
    "bal_mixed": {
        "en": "Imports exceeded exports in {n} of {m} years; in {end} the trade balance was {bal}.",
        "fr": "Les importations ont dépassé les exportations pendant {n} des {m} années ; en {end}, le solde commercial était de {bal}.",
        "de": "In {n} von {m} Jahren lagen die Importe über den Exporten; {end} betrug die Handelsbilanz {bal}.",
    },
    "drop": {
        "en": "The sharpest fall in exports came in {year} ({chg} on the year before).",
        "fr": "La plus forte baisse des exportations a eu lieu en {year} ({chg} sur un an).",
        "de": "Der stärkste Rückgang der Exporte erfolgte {year} ({chg} gegenüber dem Vorjahr).",
    },
    "latest": {
        "en": "In {end}, exports changed by {echg} and imports by {ichg} compared with {prev}.",
        "fr": "En {end}, les exportations ont varié de {echg} et les importations de {ichg} par rapport à {prev}.",
        "de": "{end} veränderten sich die Exporte um {echg} und die Importe um {ichg} gegenüber {prev}.",
    },
    "p_top": {
        "en": "Largest partner in {year}: {name}, with {share} of total trade ({value}).",
        "fr": "Premier partenaire du Luxembourg en {year} : {name}, avec {share} du commerce total ({value}).",
        "de": "Größter Partner Luxemburgs im Jahr {year}: {name} mit {share} des Gesamthandels ({value}).",
    },
    "p_flows": {
        "en": "Main export market: {xname} ({xshare} of exports). Main supplier: {mname} ({mshare} of imports).",
        "fr": "Premier client : {xname} ({xshare} des exportations). Premier fournisseur : {mname} ({mshare} des importations).",
        "de": "Wichtigster Absatzmarkt: {xname} ({xshare} der Exporte). Wichtigster Lieferant: {mname} ({mshare} der Importe).",
    },
    "p_conc": {
        "en": "The top five ({names}) took {c5} of total trade, compared with {c5b} in {base}.",
        "fr": "Les cinq premiers ({names}) représentaient {c5} du commerce total, contre {c5b} en {base}.",
        "de": "Die fünf größten ({names}) machten {c5} des Gesamthandels aus, gegenüber {c5b} im Jahr {base}.",
    },
    "g_top": {
        "en": "Largest export chapter: {xname} ({xshare} of exports). Largest import chapter: {mname} ({mshare} of imports).",
        "fr": "Premier chapitre à l'exportation : {xname} ({xshare} des exportations). À l'importation : {mname} ({mshare} des importations).",
        "de": "Größtes Exportkapitel: {xname} ({xshare} der Exporte). Größtes Importkapitel: {mname} ({mshare} der Importe).",
    },
    "g_top3": {
        "en": "The three largest export chapters make up {c3} of exports.",
        "fr": "Les trois premiers chapitres à l'exportation représentent {c3} des exportations.",
        "de": "Die drei größten Exportkapitel machen {c3} der Exporte aus.",
    },
    "g_gain": {
        "en": "Since {base}, exports grew most in {name} ({delta}).",
        "fr": "Depuis {base}, c'est pour {name} que les exportations ont le plus augmenté ({delta}).",
        "de": "Seit {base} sind die Exporte bei {name} am stärksten gestiegen ({delta}).",
    },
    "g_loss": {
        "en": "The largest fall was in {name} ({delta}).",
        "fr": "La plus forte baisse concerne {name} ({delta}).",
        "de": "Den stärksten Rückgang gab es bei {name} ({delta}).",
    },
    "s_months": {
        "en": "In {mmax}, exports are usually {fmax} above a typical month; in {mmin}, {fmin} below.",
        "fr": "En {mmax}, les exportations dépassent généralement un mois type de {fmax} ; en {mmin}, elles sont inférieures de {fmin}.",
        "de": "Im {mmax} liegen die Exporte meist {fmax} über einem typischen Monat, im {mmin} {fmin} darunter.",
    },
    "s_adjusted": {
        "en": "Without seasonal effects, exports stood at {value} in {when} ({chg} on a year earlier).",
        "fr": "Hors effets saisonniers, les exportations s'élevaient à {value} en {when} ({chg} sur un an).",
        "de": "Saisonbereinigt lagen die Exporte im {when} bei {value} ({chg} gegenüber dem Vorjahresmonat).",
    },
    "b_range": {
        "en": "Among the {n} countries compared, the highest index is {best_name} ({best}) and the lowest {worst_name} ({worst}).",
        "fr": "Parmi les {n} pays comparés, indice le plus élevé : {best_name} ({best}) ; le plus bas : {worst_name} ({worst}).",
        "de": "Unter den {n} verglichenen Ländern: höchster Index {best_name} ({best}), niedrigster {worst_name} ({worst}).",
    },
    "b_intra": {
        "en": "In {end}, {share} of Luxembourg's trade was with EU countries, against an average of {avg} for the other countries.",
        "fr": "En {end}, {share} des échanges du Luxembourg se faisaient avec des pays de l'UE, contre {avg} en moyenne pour les autres pays.",
        "de": "{end} entfielen {share} des Handels Luxemburgs auf EU-Länder, gegenüber durchschnittlich {avg} bei den anderen Ländern.",
    },
    # chart titles (short and descriptive; the takeaway sits above the chart)
    "c_trend": {
        "en": "Exports and imports per year, {start}–{end}",
        "fr": "Exportations et importations par an, {start}–{end}",
        "de": "Exporte und Importe pro Jahr, {start}–{end}",
    },
    "c_map": {
        "en": "Total trade by partner, {year}",
        "fr": "Commerce total par partenaire, {year}",
        "de": "Gesamthandel nach Partnerland, {year}",
    },
    "c_bar": {
        "en": "Ten largest partners, {year}",
        "fr": "Dix premiers partenaires, {year}",
        "de": "Zehn größte Partner, {year}",
    },
    "c_treemap": {
        "en": "Goods by HS chapter, {year}",
        "fr": "Marchandises par chapitre SH, {year}",
        "de": "Waren nach HS-Kapitel, {year}",
    },
    "c_change": {
        "en": "Largest changes in exports by chapter, {base}–{year}",
        "fr": "Plus fortes variations des exportations par chapitre, {base}–{year}",
        "de": "Größte Veränderungen der Exporte nach Kapitel, {base}–{year}",
    },
    "c_season": {"en": "Monthly trade", "fr": "Échanges mensuels", "de": "Monatlicher Handel"},
    "c_index": {
        "en": "Total trade, index {start} = 100",
        "fr": "Commerce total, indice base {start} = 100",
        "de": "Gesamthandel, Index {start} = 100",
    },
    # KPI tiles
    "k_balance": {"en": "Trade balance", "fr": "Solde commercial", "de": "Handelsbilanz"},
    "k_top5": {
        "en": "Top-5 partner share",
        "fr": "Part des 5 premiers partenaires",
        "de": "Anteil der 5 größten Partner",
    },
    "k_vs": {"en": "vs {year}", "fr": "vs {year}", "de": "ggü. {year}"},
    "k_pp": {"en": "pp", "fr": "pts", "de": "Pp."},
}


# Share of total trade with the five largest partners of each year (the sparkline of the
# dependence tile). Same rule as the ranking: undisclosed partners count in the total only.
_CONCENTRATION_SQL = f"""WITH by_partner AS (
  SELECT year,
         CASE WHEN partner_is_special THEN 'UNDISCLOSED' ELSE partner END AS key,
         sum(value_eur) AS value_eur
  FROM v_lu_trade_hs2
  WHERE year BETWEEN {{first}} AND {{year}}
  GROUP BY year, key
), ranked AS (
  SELECT year, key, value_eur,
         row_number() OVER (PARTITION BY year
                            ORDER BY (key = 'UNDISCLOSED'), value_eur DESC) AS rank,
         sum(value_eur) OVER (PARTITION BY year) AS total
  FROM by_partner
)
SELECT year,
       100 * sum(value_eur) FILTER (WHERE rank <= {TOP_K} AND key <> 'UNDISCLOSED')
         / any_value(total) AS top_share
FROM ranked
GROUP BY year
ORDER BY year"""


@dataclass
class Kpi:
    """One headline tile: value, change and a sparkline."""

    label: str
    value: str
    delta: str | None = None
    delta_color: str = "normal"
    spark: list[float] = field(default_factory=list)
    help: str = ""


@dataclass
class Panel:
    """One business question answered from the data, with its evidence."""

    key: str  # trend, partners, products, season, peers
    question: str
    takeaway: str
    facts: list[str]
    chart_titles: list[str]
    frames: dict[str, pd.DataFrame]
    sql: list[str]
    methods: list[str]
    limits: list[str]
    explore_question: str
    explore_spec: QuerySpec


@dataclass
class Overview:
    """Everything the landing page shows, in one language."""

    language: str
    year: int
    base_year: int
    kpis: list[Kpi]
    panels: list[Panel]
    about: dict[str, object]
    limits: list[str]
    findings_hero: str = ""  # the story in one line (agents/findings.py)
    findings_intro: str = ""
    findings: list[Finding] = field(default_factory=list)  # the story tab (agents/findings.py)


@dataclass
class _Run:
    spec: QuerySpec
    sql: str
    analysis: Analysis
    stats: guard.ScopeStats | None


def _t(key: str, lang: str, **values: object) -> str:
    return _T[key][lang].format(**values)


def _signed_pct(value: float | None, lang: str) -> str:
    return "–" if value is None or pd.isna(value) else fmt_pct(value, lang, signed=True)


def _signed_eur(value: float, lang: str) -> str:
    return ("+" if value >= 0 else "") + fmt_eur(value, lang)


def _delta(text: str) -> str:
    """Streamlit reads the delta direction from a leading ASCII minus sign."""
    return text.replace("−", "-")


def _rank_text(rank: int, lang: str) -> str:
    """'3' in EN/DE templates ('rank 3', 'Rang 3'); French ordinal '1er' / '3e'."""
    if lang == "fr":
        return f"{rank}er" if rank == 1 else f"{rank}e"
    return str(rank)


def _month_year(ts: pd.Timestamp, lang: str) -> str:
    return f"{MONTHS_LONG[lang][ts.month - 1]} {ts.year}"


def _run(spec: QuerySpec, sem: SemanticLayer, with_stats: bool = False) -> _Run:
    """Same path as a preset run: defaults → compiled SQL → SQL guard → query → analysis."""
    resolved = apply_defaults(spec, sem.coverage)
    compiled = compile_spec(resolved)
    sql = check_sql(compiled.sql)
    df = sem.query(sql)
    stats = None
    if with_stats and compiled.stats_sql:
        row = sem.query(check_sql(compiled.stats_sql)).fillna(0.0).iloc[0]
        stats = guard.ScopeStats(
            float(row["total"]), float(row["confidential"]), float(row["special"])
        )
    return _Run(resolved, sql, analyse(resolved, df, sem), stats)


def _flow_series(main: pd.DataFrame, flow: str, value: str = "value") -> pd.Series:
    part = main[main["flow"] == flow].sort_values("period")
    return pd.Series(part[value].to_numpy(dtype=float), index=part["period"].to_numpy())


def _items(main: pd.DataFrame, flow: str) -> pd.DataFrame:
    """Ranked items of one flow (pooled 'Other' and hidden rows excluded)."""
    part = main[(main["flow"] == flow) & (main["kind"] == "item")]
    return part.sort_values("rank")


def _trend(sem: SemanticLayer, lang: str, start: int, year: int) -> tuple[Panel, _Run]:
    spec = QuerySpec(
        language=lang,
        intent="time_series",
        freq="A",
        flow="both",
        period_start=str(start),
        period_end=str(year),
    )
    run = _run(spec, sem)
    main = run.analysis.main
    exp, imp = _flow_series(main, "export"), _flow_series(main, "import")
    first, end = int(exp.index.min()), int(exp.index.max())
    bal = exp - imp
    facts = [
        _t(
            "growth",
            lang,
            start=first,
            end=end,
            e0=fmt_eur(exp[first], lang),
            e1=fmt_eur(exp[end], lang),
            ecagr=_signed_pct(timeseries.cagr_pct(exp[first], exp[end], end - first), lang),
            i0=fmt_eur(imp[first], lang),
            i1=fmt_eur(imp[end], lang),
            icagr=_signed_pct(timeseries.cagr_pct(imp[first], imp[end], end - first), lang),
        )
    ]
    deficits = int((bal < 0).sum())
    if deficits == len(bal):
        facts.append(
            _t("bal_deficit_all", lang, start=first, end=end, bal=fmt_eur(-bal[end], lang))
        )
    elif deficits == 0:
        facts.append(_t("bal_surplus_all", lang, start=first, end=end, bal=fmt_eur(bal[end], lang)))
    else:
        facts.append(
            _t("bal_mixed", lang, n=deficits, m=len(bal), end=end, bal=fmt_eur(bal[end], lang))
        )
    if end - 1 in exp.index:
        facts.append(
            _t(
                "latest",
                lang,
                end=end,
                prev=end - 1,
                echg=_signed_pct(timeseries.change_pct(exp[end - 1], exp[end]), lang),
                ichg=_signed_pct(timeseries.change_pct(imp[end - 1], imp[end]), lang),
            )
        )
    yoy = timeseries.yoy_pct(exp).dropna()
    if not yoy.empty and yoy.min() < 0:
        facts.append(_t("drop", lang, year=int(yoy.idxmin()), chg=_signed_pct(yoy.min(), lang)))

    takeaway = _t(
        "t_deficit" if bal[end] < 0 else "t_surplus",
        lang,
        bal=fmt_eur(abs(bal[end]), lang),
        end=end,
    )
    events = pd.DataFrame(
        [
            {"year": y, "label": labels[lang]}
            for y, labels in REFERENCE_EVENTS.items()
            if first <= y <= end
        ],
        columns=["year", "label"],
    )
    panel = Panel(
        key="trend",
        question=_t("q_trend", lang),
        takeaway=takeaway,
        facts=facts,
        chart_titles=[_t("c_trend", lang, start=first, end=end)],
        frames={"main": main, "events": events},
        sql=[run.sql],
        methods=[
            *run.analysis.methods,
            "growth a year = compound annual growth rate (CAGR) between the first and last year",
            "dotted lines mark well-known shocks as reading aids; they are not part of the data",
        ],
        limits=[guard.make("L06", "warn").message],
        explore_question=_t("x_trend", lang, start=first),
        explore_spec=spec,
    )
    return panel, run


def _partners(
    sem: SemanticLayer, lang: str, year: int, base: int
) -> tuple[Panel, float, float, _Run]:
    spec = QuerySpec(
        language=lang,
        intent="ranking",
        breakdown="partner",
        flow="both",
        period_start=str(year),
        period_end=str(year),
        top_n=10,
    )
    run = _run(spec, sem, with_stats=True)
    then = _run(spec.model_copy(update={"period_start": str(base), "period_end": str(base)}), sem)
    main = run.analysis.main
    total, total_then = _items(main, "total"), _items(then.analysis.main, "total")
    c5 = rankings.concentration(total["share"], TOP_K)
    c5b = rankings.concentration(total_then["share"], TOP_K)
    top, xtop, mtop = total.iloc[0], _items(main, "export").iloc[0], _items(main, "import").iloc[0]
    facts = [
        _t(
            "p_top",
            lang,
            year=year,
            name=top["label"],
            share=fmt_pct(top["share"], lang),
            value=fmt_eur(top["value"], lang),
        ),
        _t(
            "p_flows",
            lang,
            xname=xtop["label"],
            xshare=fmt_pct(xtop["share"], lang),
            mname=mtop["label"],
            mshare=fmt_pct(mtop["share"], lang),
        ),
        _t(
            "p_conc",
            lang,
            names=", ".join(total.head(TOP_K)["label"]),
            c5=fmt_pct(c5, lang),
            c5b=fmt_pct(c5b, lang),
            base=base,
        ),
    ]
    conc_sql = check_sql(_CONCENTRATION_SQL.format(first=sem.coverage.first_period.year, year=year))
    conc = sem.query(conc_sql)
    question, explore = preset("Q1").for_language(lang)
    panel = Panel(
        key="partners",
        question=_t("q_partners", lang),
        takeaway=_t("t_partners", lang, c5=fmt_pct(c5, lang), year=year),
        facts=facts,
        chart_titles=[_t("c_map", lang, year=year), _t("c_bar", lang, year=year)],
        frames={"main": main, "concentration": conc},
        sql=[run.sql, then.sql, conc_sql],
        methods=[
            *run.analysis.methods,
            f"dependence = share of total trade (exports + imports) with the {TOP_K} largest partners",
            f"yearly dependence: the {TOP_K} largest partners of each year; undisclosed partners "
            "stay in the total but are never ranked",
        ],
        limits=[lim.message for lim in guard.check_result(run.spec, run.stats)],
        explore_question=question,
        explore_spec=explore,
    )
    return panel, c5, c5b, run


def _products(sem: SemanticLayer, lang: str, year: int, base: int) -> Panel:
    spec = QuerySpec(
        language=lang,
        intent="ranking",
        breakdown="product",
        product_level="HS2",
        flow="both",
        period_start=str(year),
        period_end=str(year),
        top_n=10,
    )
    run = _run(spec, sem, with_stats=True)
    # all chapters (top 99 = every visible HS2 chapter), exports only, now and in the base year
    every = spec.model_copy(update={"flow": "export", "top_n": 99})
    now = _run(every, sem)
    then = _run(every.model_copy(update={"period_start": str(base), "period_end": str(base)}), sem)
    a, b = _items(now.analysis.main, "export"), _items(then.analysis.main, "export")
    change = (
        pd.DataFrame({"value": a.set_index("key")["value"]})
        .join(b.set_index("key")["value"].rename("value_base"), how="outer")
        .fillna(0.0)
    )
    change["change"] = change["value"] - change["value_base"]
    labels = {
        **dict(zip(b["key"], b["label"], strict=True)),
        **dict(zip(a["key"], a["label"], strict=True)),
    }
    change = change.assign(label=change.index.map(labels)).reset_index(names="key")
    gains = change[change["change"] > 0].nlargest(5, "change")
    losses = change[change["change"] < 0].nsmallest(5, "change")
    shift = pd.concat([gains, losses]).sort_values("change", ascending=False)

    main = run.analysis.main
    xtop, mtop = _items(main, "export"), _items(main, "import")
    facts = [
        _t(
            "g_top",
            lang,
            xname=xtop.iloc[0]["label"],
            xshare=fmt_pct(xtop.iloc[0]["share"], lang),
            mname=mtop.iloc[0]["label"],
            mshare=fmt_pct(mtop.iloc[0]["share"], lang),
        ),
        _t("g_top3", lang, c3=fmt_pct(rankings.concentration(xtop["share"], 3), lang)),
    ]
    if not gains.empty:
        g = gains.iloc[0]
        facts.append(
            _t("g_gain", lang, base=base, name=g["label"], delta=_signed_eur(g["change"], lang))
        )
    if not losses.empty:
        lo = losses.iloc[0]
        facts.append(_t("g_loss", lang, name=lo["label"], delta=_signed_eur(lo["change"], lang)))
    question, explore = preset("Q2").for_language(lang)
    return Panel(
        key="products",
        question=_t("q_products", lang),
        takeaway=_t(
            "t_products",
            lang,
            name=xtop.iloc[0]["label"],
            share=fmt_pct(xtop.iloc[0]["share"], lang),
            year=year,
        ),
        facts=facts,
        chart_titles=[
            _t("c_treemap", lang, year=year),
            _t("c_change", lang, base=base, year=year),
        ],
        frames={"main": main, "change": shift},
        sql=[run.sql, now.sql, then.sql],
        methods=[
            *run.analysis.methods,
            f"change = exports {year} − exports {base} per HS2 chapter; five largest rises and falls",
        ],
        limits=[lim.message for lim in guard.check_result(run.spec, run.stats)],
        explore_question=question,
        explore_spec=explore,
    )


def _season(sem: SemanticLayer, lang: str) -> Panel:
    question, spec = preset("Q6").for_language(lang)
    run = _run(spec, sem)
    main = run.analysis.main
    prof = run.analysis.extra["profile"]
    prof = prof[prof["flow"] == "export"]
    hi, lo = prof.loc[prof["factor"].idxmax()], prof.loc[prof["factor"].idxmin()]
    mmax, mmin = MONTHS_LONG[lang][int(hi["month"]) - 1], MONTHS_LONG[lang][int(lo["month"]) - 1]
    sa = _flow_series(main, "export", "adjusted")
    facts = [
        _t(
            "s_months",
            lang,
            mmax=mmax,
            fmax=fmt_pct(100 * (hi["factor"] - 1), lang),
            mmin=mmin,
            fmin=fmt_pct(100 * (1 - lo["factor"]), lang),
        )
    ]
    if len(sa) > 12:
        facts.append(
            _t(
                "s_adjusted",
                lang,
                value=fmt_eur(sa.iloc[-1], lang),
                when=_month_year(pd.Timestamp(sa.index[-1]), lang),
                chg=_signed_pct(timeseries.change_pct(sa.iloc[-13], sa.iloc[-1]), lang),
            )
        )
    return Panel(
        key="season",
        question=_t("q_season", lang),
        takeaway=_t("t_season", lang, mmax=mmax, mmin=mmin),
        facts=facts,
        chart_titles=[_t("c_season", lang)],
        frames={"main": main, "profile": prof},
        sql=[run.sql],
        methods=[
            *run.analysis.methods,
            "typical-month effect = average seasonal factor of the last five years",
        ],
        limits=[lim.message for lim in run.analysis.flags],
        explore_question=question,
        explore_spec=spec,
    )


def _peers(sem: SemanticLayer, lang: str, first: int, year: int) -> Panel:
    start = max(BENCHMARK_BASE_YEAR, first)
    spec = QuerySpec(
        language=lang, intent="benchmark", period_start=str(start), period_end=str(year)
    )
    run = _run(spec, sem)
    main = run.analysis.main
    end = int(main["period"].max())
    latest = main[main["period"] == end]
    lu = latest[latest["reporter"] == REPORTER].iloc[0]
    others = latest[latest["reporter"] != REPORTER]
    best, worst = latest.loc[latest["index"].idxmax()], latest.loc[latest["index"].idxmin()]
    facts = [
        _t(
            "b_range",
            lang,
            n=len(latest),
            best_name=best["label"],
            best=fmt_number(best["index"], 0, lang),
            worst_name=worst["label"],
            worst=fmt_number(worst["index"], 0, lang),
        ),
        _t(
            "b_intra",
            lang,
            end=end,
            share=fmt_pct(lu["intra_share"], lang),
            avg=fmt_pct(others["intra_share"].mean(), lang),
        ),
    ]
    return Panel(
        key="peers",
        question=_t("q_peers", lang),
        takeaway=_t(
            "t_peers",
            lang,
            lu=fmt_number(lu["index"], 0, lang),
            end=end,
            start=start,
            r=_rank_text(int((others["index"] > lu["index"]).sum()) + 1, lang),
            n=len(latest),
        ),
        facts=facts,
        chart_titles=[_t("c_index", lang, start=start)],
        frames={"main": main},
        sql=[run.sql],
        methods=run.analysis.methods,
        limits=[guard.make("S03", "warn").message],
        explore_question=_t("x_peers", lang, start=start),
        explore_spec=spec,
    )


def _about(sem: SemanticLayer, stats: guard.ScopeStats | None, year: int) -> dict[str, object]:
    cov = sem.coverage
    sql = check_sql(
        "SELECT count(DISTINCT partner) FILTER (WHERE NOT partner_is_special) AS partners,\n"
        "       count(DISTINCT cn8) FILTER (WHERE NOT is_confidential) AS products,\n"
        "       count(DISTINCT period) AS months,\n"
        "       count(*) AS records\n"
        "FROM v_lu_trade"
    )
    row = sem.query(sql).iloc[0]
    return {
        "dataset": DATASET_ID,
        "source": cov.source,
        "first_period": cov.first_period,
        "latest_complete_period": cov.latest_complete_period,
        "latest_period": cov.latest_period,
        "extraction_date": cov.extraction_date,
        "is_placeholder": cov.is_placeholder,
        "partners": int(row["partners"]),
        "products": int(row["products"]),
        "months": int(row["months"]),
        "records": int(row["records"]),
        "year": year,
        "confidential_pct": stats.pct(stats.confidential) if stats else 0.0,
        "undisclosed_pct": stats.pct(stats.special) if stats else 0.0,
        "sql": sql,
    }


def _kpis(
    trend: pd.DataFrame, conc: pd.DataFrame, c5: float, c5b: float, base: int, lang: str
) -> list[Kpi]:
    exp, imp = _flow_series(trend, "export"), _flow_series(trend, "import")
    bal = exp - imp
    end = int(exp.index.max())
    vs = _t("k_vs", lang, year=end - 1)

    def tile(name: str, s: pd.Series, color: str, help_text: str) -> Kpi:
        delta = None
        if end - 1 in s.index:
            delta = _delta(f"{_signed_pct(timeseries.change_pct(s[end - 1], s[end]), lang)} {vs}")
        return Kpi(
            label=f"{name} {end}",
            value=fmt_eur(s[end], lang),
            delta=delta,
            delta_color=color,
            spark=[round(v / 1e9, 3) for v in s],
            help=help_text,
        )

    tiles = [
        tile(
            flow_label("export", lang).capitalize(),
            exp,
            "normal",
            "Goods sold abroad, current euros.",
        ),
        tile(
            flow_label("import", lang).capitalize(),
            imp,
            "off",
            "Goods bought abroad, current euros.",
        ),
    ]
    tiles.append(
        Kpi(
            label=f"{_t('k_balance', lang)} {end}",
            value=fmt_eur(bal[end], lang),
            delta=_delta(f"{_signed_eur(bal[end] - bal[end - 1], lang)} {vs}")
            if end - 1 in bal.index
            else None,
            spark=[round(v / 1e9, 3) for v in bal],
            help="Exports minus imports.",
        )
    )
    sign = "+" if c5 >= c5b else ""
    tiles.append(
        Kpi(
            label=_t("k_top5", lang),
            value=fmt_pct(c5, lang),
            delta=f"{sign}{fmt_number(c5 - c5b, 1, lang)} {_t('k_pp', lang)} "
            + _t("k_vs", lang, year=base),
            delta_color="off",
            spark=[round(v, 2) for v in conc["top_share"]],
            help="Share of total trade with the five largest partners: a simple measure of dependence.",
        )
    )
    return tiles


def general_limits(sem: SemanticLayer) -> list[str]:
    """What the data can't tell you: the scope limits every reader should know first."""
    cov = sem.coverage
    lims = [guard.make(i, "warn").message for i in ("S01", "S02", "L06", "L10")]
    if cov.latest_period > cov.latest_complete_period:
        lims.append(guard.make("L04", "warn", latest=f"{cov.latest_complete_period:%b %Y}").message)
    return lims


def build_overview(sem: SemanticLayer, lang: str = "en") -> Overview:
    """Run the five overview questions and assemble facts, frames and evidence."""
    cov = sem.coverage
    year = cov.latest_complete_year
    first = cov.first_period.year
    base = max(first, year - BASE_YEARS_BACK)
    trend, _ = _trend(sem, lang, first, year)
    partners, c5, c5b, partner_run = _partners(sem, lang, year, base)
    panels = [
        trend,
        partners,
        _products(sem, lang, year, base),
        _season(sem, lang),
        _peers(sem, lang, first, year),
    ]
    hero, intro, findings = build_findings(sem, lang)
    return Overview(
        language=lang,
        year=year,
        base_year=base,
        kpis=_kpis(trend.frames["main"], partners.frames["concentration"], c5, c5b, base, lang),
        panels=panels,
        about=_about(sem, partner_run.stats, year),
        limits=general_limits(sem),
        findings_hero=hero,
        findings_intro=intro,
        findings=findings,
    )
