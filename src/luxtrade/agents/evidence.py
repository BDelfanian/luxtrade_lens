"""Evidence for a scenario's answer: key figures and charts built by code from its steps.

The combined answer of a scenario is words. This module gives it what an Overview card has: a
chart and a few key figures. No LLM is involved:

- Steps that ask the same thing for different periods form a group: the same ranking of changes
  for several pairs of years (three crises), or the same shares in two years (2005 and 2025).
- The item shown is the one the answer talks about (its label in the headline and points), or
  else the one that falls most often; it is compared with the whole flow ("All exports").
- Every value comes from re-running each step's own stored, guarded SQL, so items outside a
  step's top 10 and the whole flow are exact too.
- Steps that compute the concentration index (``measure`` "hhi") form one figure with a panel
  per flow and dimension (exports and imports, by product and by partner), like the Overview's
  diversification card, with each panel's first and last value as key figures.
- Projections (intent "forecast") form one figure: a panel per flow with the last eight years
  observed, the projection and its 80 % band; key figures are each flow's projected total for
  the last full year projected and, from seasonality steps, its strongest and weakest month.
- Yearly series of one line each (a share or a value: "Japan's share of imports each year")
  form small multiples, a panel per step on its own scale, with first and last value as key
  figures; their values are the steps' own analysed frames (computed by code in each run).
"""

import re
from typing import Literal

import pandas as pd
from pydantic import BaseModel, Field

from luxtrade.runs.store import RunRecord
from luxtrade.semantic.layer import QueryError, SemanticLayer
from luxtrade.viz.format import flow_label, fmt_measure, fmt_number, fmt_pct, month_name

MAX_FIGURES = 2
MAX_FOCUS = {"change": 2, "share": 3}

_T = {
    "all": {"en": "All {flow}", "fr": "Toutes les {flow}", "de": "Alle {flow}"},
    "t_change": {
        "en": "{focus} vs all {flow}: change in each period",
        "fr": "{focus} et l'ensemble des {flow} : variation sur chaque période",
        "de": "{focus} und alle {flow}: Veränderung je Zeitraum",
    },
    "t_share": {
        "en": "Share of {flow}, {y0} and {y1}",
        "fr": "Part des {flow}, {y0} et {y1}",
        "de": "Anteil an den {flow}n, {y0} und {y1}",  # dative: Exporten
    },
    "k_falls": {
        "en": "{focus}: periods with falling {flow}",
        "fr": "{focus} : périodes de baisse des {flow}",
        "de": "{focus}: Zeiträume mit sinkenden {flow}",
    },
    "k_ratio": {
        "en": "as far as all {flow}, on average",
        "fr": "plus que l'ensemble des {flow}, en moyenne",
        "de": "so stark wie alle {flow}, im Schnitt",
    },
    "k_ratio_d": {"en": "{a} against {b}", "fr": "{a} contre {b}", "de": "{a} gegenüber {b}"},
    "k_worst": {"en": "{focus}, {period}", "fr": "{focus}, {period}", "de": "{focus}, {period}"},
    "k_worst_d": {
        "en": "all {flow}: {total}",
        "fr": "ensemble des {flow} : {total}",
        "de": "alle {flow}: {total}",
    },
    "k_share": {
        "en": "{focus}, share of {flow} {year}",
        "fr": "{focus}, part des {flow} {year}",
        "de": "{focus}, Anteil an den {flow}n {year}",
    },
    "k_share_d": {
        "en": "{value} in {year}",
        "fr": "{value} en {year}",
        "de": "{value} im Jahr {year}",
    },
    "k_pp": {
        "en": "{focus}: change in share",
        "fr": "{focus} : évolution de la part",
        "de": "{focus}: Veränderung des Anteils",
    },
    "t_hhi": {
        "en": "Concentration (HHI), {y0}–{y1}",
        "fr": "Concentration (HHI), {y0}–{y1}",
        "de": "Konzentration (HHI), {y0}–{y1}",
    },
    "panel": {
        "en": {"product": "{flow} by product", "partner": "{flow} by partner"},
        "fr": {"product": "{flow} par produit", "partner": "{flow} par partenaire"},
        "de": {"product": "{flow} nach Waren", "partner": "{flow} nach Partnern"},
    },
    "k_hhi": {"en": "{panel}, {year}", "fr": "{panel}, {year}", "de": "{panel}, {year}"},
    "k_hhi_d": {
        "en": "{value} in {year} ({chg})",
        "fr": "{value} en {year} ({chg})",
        "de": "{value} im Jahr {year} ({chg})",
    },
    "note_hhi": {
        "en": "Computed by code from the steps' own SQL (steps {steps}): the sum of squared "
        "shares × 10,000 across every partner or product chapter; above 1,800 counts as highly "
        "concentrated, below 1,000 as unconcentrated.",
        "fr": "Calculé par le code à partir du SQL des étapes ({steps}) : somme des parts au "
        "carré × 10 000 sur tous les partenaires ou chapitres ; au-delà de 1 800, la "
        "concentration est forte, en dessous de 1 000, faible.",
        "de": "Vom Code aus dem SQL der Schritte berechnet ({steps}): Summe der quadrierten "
        "Anteile × 10.000 über alle Partner oder Warenkapitel; über 1.800 gilt als hoch, unter "
        "1.000 als gering konzentriert.",
    },
    "t_series": {
        "en": "Year by year, {y0}–{y1}",
        "fr": "Année par année, {y0}–{y1}",
        "de": "Jahr für Jahr, {y0}–{y1}",
    },
    "p_share": {
        "en": "{who}, share of {flow}",
        "fr": "{who}, part des {flow}",
        "de": "{who}, Anteil an den {flow}n",
    },
    "p_value": {"en": "{who}, {flow}", "fr": "{who}, {flow}", "de": "{who}, {flow}"},
    "p_unit": {
        "en": "{who}, {flow}: value per kg",
        "fr": "{who}, {flow} : valeur au kg",
        "de": "{who}, {flow}: Wert je kg",
    },
    "p_mass": {
        "en": "{who}, {flow}: mass",
        "fr": "{who}, {flow} : masse",
        "de": "{who}, {flow}: Masse",
    },
    "eu27": {"en": "EU27 countries", "fr": "Pays de l'UE27", "de": "EU27-Länder"},
    "extra": {"en": "Non-EU27 countries", "fr": "Pays hors UE27", "de": "Nicht-EU27-Länder"},
    "t_proj": {
        "en": "Observed and projected, monthly, {y0}–{y1}",
        "fr": "Observé et projeté, par mois, {y0}–{y1}",
        "de": "Beobachtet und projiziert, monatlich, {y0}–{y1}",
    },
    "k_proj": {
        "en": "{flow}, projected total {year}",
        "fr": "{flow}, total projeté {year}",
        "de": "{flow}, projizierte Summe {year}",
    },
    "k_proj_d": {
        "en": "{year} observed: {value}",
        "fr": "{year} observé : {value}",
        "de": "{year} beobachtet: {value}",
    },
    "k_season": {
        "en": "{flow} in {month}, vs a typical month",
        "fr": "{flow} en {month}, par rapport à un mois type",
        "de": "{flow} im {month}, gegenüber einem typischen Monat",
    },
    "k_season_d": {"en": "{month}: {value}", "fr": "{month} : {value}", "de": "{month}: {value}"},
    "note_proj": {
        "en": "Projection computed by code (steps {steps}): ETS on log values with a damped trend "
        "and a monthly season, fitted on the full monthly series, unless the same month of the "
        "previous year did better in the back-test; the band is the 80 % range of 500 simulated "
        "paths. A projection extends past patterns, it does not forecast events.",
        "fr": "Projection calculée par le code (étapes {steps}) : ETS sur les logarithmes, "
        "tendance amortie et saison mensuelle, ajusté sur toute la série mensuelle, sauf si le "
        "même mois de l'année précédente fait mieux au test ; la bande est l'intervalle à 80 % "
        "de 500 trajectoires simulées. Une projection prolonge les tendances passées, elle ne "
        "prévoit pas les événements.",
        "de": "Projektion vom Code berechnet (Schritte {steps}): ETS auf Logarithmen mit "
        "gedämpftem Trend und Monatssaison, auf der ganzen Monatsreihe geschätzt, außer der "
        "gleiche Monat des Vorjahres schneidet im Rücktest besser ab; das Band ist der "
        "80-%-Bereich von 500 simulierten Pfaden. Eine Projektion schreibt Muster fort, sie "
        "sagt keine Ereignisse voraus.",
    },
    "fit_proj": {
        "en": "{flow}: α (level) {a}, β (trend) {b}, γ (season) {g}, damping φ {p}, fitted on "
        "{first} to {last}; back-test error on the last 12 months {mape} % (same month last "
        "year: {naive} %).",
        "fr": "{flow} : α (niveau) {a}, β (tendance) {b}, γ (saison) {g}, amortissement φ {p}, "
        "ajusté sur {first} à {last} ; erreur du test sur les 12 derniers mois {mape} % (même "
        "mois l'an passé : {naive} %).",
        "de": "{flow}: α (Niveau) {a}, β (Trend) {b}, γ (Saison) {g}, Dämpfung φ {p}, geschätzt "
        "auf {first} bis {last}; Fehler im Rücktest der letzten 12 Monate {mape} % (gleicher "
        "Monat im Vorjahr: {naive} %).",
    },
    "fit_naive": {
        "en": "{flow}: the same month of the previous year, because ETS did not beat it in the "
        "back-test ({mape} % vs {naive} %); σ of the yearly log change {sigma}, fitted on "
        "{first} to {last}.",
        "fr": "{flow} : le même mois de l'année précédente, car ETS ne fait pas mieux au test "
        "({mape} % contre {naive} %) ; σ de la variation annuelle des logarithmes {sigma}, "
        "ajusté sur {first} à {last}.",
        "de": "{flow}: der gleiche Monat des Vorjahres, da ETS im Rücktest nicht besser war "
        "({mape} % gegenüber {naive} %); σ der jährlichen Log-Änderung {sigma}, geschätzt auf "
        "{first} bis {last}.",
    },
    "cap_naive": {
        "en": "{flow}: same month last year (beat ETS in the back-test)",
        "fr": "{flow} : même mois l'an passé (meilleur qu'ETS au test)",
        "de": "{flow}: gleicher Monat im Vorjahr (besser als ETS im Rücktest)",
    },
    "cap_proj": {
        "en": "ETS on log values, damped trend, monthly season: {fits} · band: 80 % of 500 "
        "simulated paths",
        "fr": "ETS sur les logarithmes, tendance amortie, saison mensuelle : {fits} · bande : "
        "80 % de 500 trajectoires simulées",
        "de": "ETS auf Logarithmen, gedämpfter Trend, Monatssaison: {fits} · Band: 80 % von 500 "
        "simulierten Pfaden",
    },
    "note_series": {
        "en": "Each panel is one step's yearly series (steps {steps}), computed by code from its "
        "own SQL; panels have their own scales.",
        "fr": "Chaque panneau est la série annuelle d'une étape ({steps}), calculée par le code à "
        "partir de son SQL ; chaque panneau a sa propre échelle.",
        "de": "Jedes Feld ist die Jahresreihe eines Schritts ({steps}), vom Code aus dessen SQL "
        "berechnet; jedes Feld hat eine eigene Skala.",
    },
    "note": {
        "en": "Computed by code from the steps' own SQL (steps {steps}); the whole flow is all "
        "{flow} of each step's scope.",
        "fr": "Calculé par le code à partir du SQL des étapes ({steps}) ; l'ensemble est la "
        "totalité des {flow} du périmètre de chaque étape.",
        "de": "Vom Code aus dem SQL der Schritte berechnet ({steps}); das Ganze sind alle "
        "{flow} im Umfang jedes Schritts.",
    },
}


def _t(key: str, lang: str, **values: object) -> str:
    return _T[key].get(lang, _T[key]["en"]).format(**values)


class EvidenceFigure(BaseModel):
    """One chart of a scenario's answer and the key figures read from it."""

    kind: Literal["change", "share", "concentration", "series", "projection"]
    title: str
    flow: str
    steps: list[int]
    rows: list[dict] = Field(default_factory=list)  # {"group", "series", "value", "step"}
    tiles: list[dict] = Field(default_factory=list)  # {"value", "label", "detail", "tone"}
    note: str = ""
    caption: str = ""  # one line under the chart on the share card (projections: the method)


def _shape(rec: RunRecord) -> tuple | None:
    """What a step compares, or None if its result cannot join a group."""
    s = rec.spec or {}
    if rec.status != "answered" or not rec.sql or rec.custom_sql:
        return None
    breakdown = s.get("breakdown")
    if s.get("intent") not in ("ranking", "composition") or breakdown not in ("partner", "product"):
        return None
    if s.get("flow") not in ("export", "import"):
        return None
    # a filter on the ranked dimension makes "all of them" a different whole in each step
    if (breakdown == "partner" and s.get("partners")) or (
        breakdown == "product" and s.get("products")
    ):
        return None
    single_year = (s.get("period_start") or "")[:4] == (s.get("period_end") or "")[:4]
    if s.get("measure") == "change":
        kind = "change"
    elif s.get("measure") in ("share", "value_eur") and single_year:
        kind = "share"
    else:
        return None
    return (
        kind,
        breakdown,
        s.get("product_level"),
        s.get("flow"),
        tuple(sorted(s.get("products") or [])),
        tuple(sorted(s.get("partners") or [])),
        s.get("partner_group"),
    )


def _labels(recs: list[RunRecord]) -> dict[str, str]:
    """Item label → key, from the steps' ranked rows."""
    out: dict[str, str] = {}
    for rec in recs:
        for row in rec.frames.get("main", []):
            if row.get("kind", "item") == "item" and row.get("label") and row.get("key"):
                out.setdefault(str(row["label"]), str(row["key"]))
    return out


def _mentions(labels: list[str], headline: str, text: str) -> dict[str, int]:
    """How often the answer names each label (the headline counts three times)."""
    found = {}
    for label in labels:
        pattern = re.compile(rf"\b{re.escape(label)}\b", re.IGNORECASE)
        n = 3 * len(pattern.findall(headline)) + len(pattern.findall(text))
        if n:
            found[label] = n
    return found


def _values(rec: RunRecord, sem: SemanticLayer, kind: str) -> tuple[dict[str, float], float]:
    """Per key and for the whole flow: the % change (change) or the % share (share)."""
    df = sem.query(rec.sql)
    if kind == "change":
        y0, y1 = int(rec.spec["period_start"][:4]), int(rec.spec["period_end"][:4])
        wide = df.pivot_table(index="key", columns="year", values="value_eur", aggfunc="sum")
        v0, v1 = wide.get(y0, pd.Series(dtype=float)), wide.get(y1, pd.Series(dtype=float))

        def pct(a: float, b: float) -> float:
            return 100 * (b / a - 1) if a and a > 0 else float("nan")

        per_key = {str(k): pct(v0.get(k, 0.0), v1.get(k, 0.0)) for k in wide.index}
        return per_key, pct(float(v0.sum()), float(v1.sum()))
    whole = float(df["value_eur"].sum())
    if rec.support_sql:  # shares of the whole flow when the result itself is filtered
        whole = float(sem.query(rec.support_sql)["value_eur"].sum())
    per_key = df.groupby("key")["value_eur"].sum()
    return {str(k): 100 * v / whole for k, v in per_key.items() if whole}, 100.0


def compose(
    chain: list,  # ScenarioStep (n, question, …)
    records: dict[int, RunRecord],
    headline: str,
    text: str,
    sem: SemanticLayer,
    lang: str = "en",
) -> list[EvidenceFigure]:
    """Charts and key figures for an answer: one per group of comparable steps (at most two)."""
    figures = []
    answered = [
        s.n for s in chain if (r := records.get(s.n)) is not None and r.status == "answered"
    ]
    ahead = [n for n in answered if (records[n].spec or {}).get("intent") == "forecast"]
    season = [n for n in answered if (records[n].spec or {}).get("intent") == "seasonality"]
    if ahead:
        try:
            fig = _projection(ahead, season, records, lang)
        except (KeyError, ValueError, TypeError):
            fig = None
        if fig is not None:
            figures.append(fig)
    hhi_steps = [
        s.n
        for s in chain
        if (rec := records.get(s.n)) is not None
        and rec.status == "answered"
        and rec.sql
        and (rec.spec or {}).get("measure") == "hhi"
    ]
    if hhi_steps and len(figures) < MAX_FIGURES:
        try:
            fig = _concentration(hhi_steps, records, sem, lang)
        except (QueryError, KeyError, ValueError):
            fig = None
        if fig is not None:
            figures.append(fig)
    series = [s.n for s in chain if (r := records.get(s.n)) is not None and _one_series(r)]
    if len(series) >= 2 and len(figures) < MAX_FIGURES:
        fig = _series(series, records, sem, lang)
        if fig is not None:
            figures.append(fig)
    groups: dict[tuple, list[int]] = {}
    for step in chain:
        rec = records.get(step.n)
        shape = _shape(rec) if rec is not None else None
        if shape is not None:
            groups.setdefault(shape, []).append(step.n)
    ordered = sorted((g for g in groups.items() if len(g[1]) >= 2), key=lambda g: -len(g[1]))
    for shape, steps in ordered[: MAX_FIGURES - len(figures)]:
        steps = sorted(steps, key=lambda n: records[n].spec.get("period_start", ""))
        try:
            fig = _figure(shape, steps, records, headline, text, sem, lang)
        except (QueryError, KeyError, ValueError):
            continue
        if fig is not None:
            figures.append(fig)
    return figures


MAX_PANELS = 4
HISTORY_YEARS = 8  # observed years shown before a projection


def _cap(text: str) -> str:
    return text[:1].upper() + text[1:]


def _projection(
    steps: list[int], season: list[int], records: dict[int, RunRecord], lang: str
) -> EvidenceFigure | None:
    """Observed and projected months, a panel per flow; projected totals and seasons as tiles."""
    rows, tiles, seasons = [], [], []
    for n in steps:
        main = records[n].frame("main")
        annual = records[n].frame("annual")
        if main.empty or "kind" not in main.columns:
            continue
        for flow, g in main.groupby("flow", sort=False):
            g = g.assign(period=pd.to_datetime(g["period"])).sort_values("period")
            seen = g[g["kind"] == "actual"]
            if seen.empty or g[g["kind"] == "projection"].empty:
                continue
            first = seen["period"].max().year - HISTORY_YEARS + 1
            fl = _cap(flow_label(str(flow), lang))
            for r in g[g["period"].dt.year >= first].itertuples():
                ahead = r.kind == "projection"
                rows.append(
                    {
                        "group": round(r.period.year + (r.period.month - 1) / 12, 4),
                        "series": fl,
                        "value": float(r.value),
                        "lo80": float(r.lo80) if ahead else None,
                        "hi80": float(r.hi80) if ahead else None,
                        "kind": r.kind,
                        "flow": str(flow),
                        "step": n,
                        "unit": "value_eur",
                    }
                )
            years = seen["period"].dt.year
            full = sorted(y for y, k in years.value_counts().items() if k == 12)
            mine = annual[annual["flow"] == flow] if not annual.empty else annual
            mine = mine[mine["months"] == 12] if not mine.empty else mine
            if full and not mine.empty:
                base = float(seen.loc[years == full[-1], "value"].sum())
                last = mine.sort_values("year").iloc[-1]
                tiles.append(
                    {
                        "value": fmt_measure(float(last["value"]), "value_eur", lang),
                        "label": _t("k_proj", lang, flow=fl, year=int(last["year"])),
                        "detail": _t(
                            "k_proj_d",
                            lang,
                            year=full[-1],
                            value=fmt_measure(base, "value_eur", lang),
                        ),
                        "tone": "up" if float(last["value"]) >= base else "down",
                    }
                )
    for n in season:
        prof = records[n].frame("profile")
        if prof.empty:
            continue
        for flow, g in prof.groupby("flow", sort=False):
            hi, lo = g.loc[g["factor"].idxmax()], g.loc[g["factor"].idxmin()]
            fl = _cap(flow_label(str(flow), lang))
            seasons.append(
                {
                    "value": fmt_pct(100 * (float(hi["factor"]) - 1), lang, signed=True),
                    "label": _t(
                        "k_season",
                        lang,
                        flow=fl,
                        month=month_name(int(hi["month"]), lang, full=True),
                    ),
                    "detail": _t(
                        "k_season_d",
                        lang,
                        month=month_name(int(lo["month"]), lang, full=True),
                        value=fmt_pct(100 * (float(lo["factor"]) - 1), lang, signed=True),
                    ),
                    "tone": "",
                }
            )
    if not rows:
        return None
    years = sorted({int(r["group"]) for r in rows})
    used = sorted({r["step"] for r in rows})
    fitted = _fitted(used, records, lang)  # the parameters, read from each step's method note
    return EvidenceFigure(
        kind="projection",
        title=_t("t_proj", lang, y0=years[0], y1=years[-1]),
        flow="both" if len({r["flow"] for r in rows}) > 1 else rows[0]["flow"],
        steps=used,
        rows=rows,
        tiles=(tiles + seasons)[:4],
        note=_t("note_proj", lang, steps=", ".join(map(str, used)))
        + "".join(f" {line['long']}" for line in fitted),
        caption=_t("cap_proj", lang, fits=" · ".join(line["short"] for line in fitted)),
    )


_FIT = re.compile(
    r"^(?P<flow>\w+): ETS.*?α \(level\) (?P<a>[\d.]+), β \(trend\) (?P<b>[\d.]+), "
    r"γ \(season\) (?P<g>[\d.]+), damping φ (?P<p>[\d.]+); fitted on \d+ months "
    r"\((?P<first>[^)]*?) to (?P<last>[^)]*?)\).*?MAPE (?P<m>[\d.]+) % \(seasonal-naive "
    r"(?P<n>[\d.]+) %\)"
)
_NAIVE = re.compile(
    r"^(?P<flow>\w+): Seasonal-naive.*?σ of the yearly log change (?P<s>[\d.]+); fitted on "
    r"\d+ months \((?P<first>[^)]*?) to (?P<last>[^)]*?)\).*?MAPE (?P<m>[\d.]+) % "
    r"\(seasonal-naive (?P<n>[\d.]+) %\)"
)


def _fitted(steps: list[int], records: dict[int, RunRecord], lang: str) -> list[dict]:
    """Each projected flow's fitted parameters and back-test, as written by the code."""
    out = []
    for n in steps:
        for method in records[n].methods:
            m = _FIT.match(method)
            if m is None and (m := _NAIVE.match(method)) is not None:  # the fallback, said so
                fl = _cap(flow_label(m["flow"], lang))
                out.append(
                    {
                        "short": _t("cap_naive", lang, flow=fl),
                        "long": _t(
                            "fit_naive",
                            lang,
                            flow=fl,
                            sigma=m["s"],
                            first=m["first"],
                            last=m["last"],
                            mape=m["m"],
                            naive=m["n"],
                        ),
                    }
                )
                continue
            if m is None:
                continue
            fl = _cap(flow_label(m["flow"], lang))
            out.append(
                {
                    "short": f"{fl} α {m['a']}, φ {m['p']}",
                    "long": _t(
                        "fit_proj",
                        lang,
                        flow=fl,
                        a=m["a"],
                        b=m["b"],
                        g=m["g"],
                        p=m["p"],
                        first=m["first"],
                        last=m["last"],
                        mape=m["m"],
                        naive=m["n"],
                    ),
                }
            )
    return out


_PANEL = {"share": "p_share", "unit_value": "p_unit", "qty_kg": "p_mass"}


# a subject asked as a share and as a value is one panel; a value per kg or a mass is another
_MEASURE_GROUP = {"share": "level", "value_eur": "level", "unit_value": "price", "qty_kg": "mass"}


def _one_series(rec: RunRecord) -> bool:
    """A yearly series with one line of one flow: a share, a value, a value per kg or a mass.

    A split of the total by EU27 vs non-EU27 counts as one line (the EU27 one).
    """
    s = rec.spec or {}
    if rec.status != "answered" or rec.custom_sql or s.get("measure") not in _MEASURE_GROUP:
        return False
    if s.get("intent") != "time_series" or s.get("freq") != "A" or s.get("year_step"):
        return False
    if s.get("flow") not in ("export", "import"):
        return False
    rows = rec.frames.get("main", [])
    keys = {r.get("key") for r in rows if r.get("flow") == s.get("flow")}
    if s.get("breakdown") == "partner_group":
        return "EU27" in keys
    return len(rows) >= 3 and len(keys) <= 1


def _who(spec: dict, sem: SemanticLayer, lang: str) -> str:
    """Whom a one-line series is about: partners, the EU27, a product, or every partner."""
    if spec.get("breakdown") == "partner_group" or spec.get("partner_group") == "EU27_2020":
        return _t("eu27", lang)
    if spec.get("partner_group") == "EXTRA_EU27_2020":
        return _t("extra", lang)
    partners = [sem.label(p, "partner", lang) for p in spec.get("partners") or []]
    if partners:  # a product filter on top is named with the flow (see _scope)
        return _and(partners, lang)
    products = [sem.label(p, "product", lang)[:32] for p in spec.get("products") or []]
    return _and(products, lang) or _t("all", lang, flow="").strip()


def _and(names: list[str], lang: str) -> str:
    """'Belgium, Germany & France'; more than three: the first two and 'others'."""
    if len(names) > 3:
        names = [*names[:2], {"en": "others", "fr": "autres", "de": "weitere"}.get(lang, "others")]
    return ", ".join(names[:-1]) + " & " + names[-1] if len(names) > 1 else "".join(names)


def _scope(spec: dict, flow: str, sem: SemanticLayer, lang: str) -> str:
    """The flow a panel is about: 'imports', or 'mineral fuels and oils imports'.

    A series of partners filtered on products is a share of that product's flow.
    """
    fl = flow_label(flow, lang)
    if spec.get("products") and (spec.get("partners") or spec.get("breakdown") == "partner"):
        product = sem.label(spec["products"][0], "product", lang)[:32]
        if lang == "de":  # "Anteil an den {flow}n": a compound keeps the dative ending
            return f"{product}-{fl}"
        if lang == "fr":
            return f"{fl} de {product[:1].lower()}{product[1:]}"
        return f"{product[:1].lower()}{product[1:]} {fl}"
    return fl


def _series(
    steps: list[int], records: dict[int, RunRecord], sem: SemanticLayer, lang: str
) -> EvidenceFigure | None:
    """Small multiples of one-line yearly series, first and last values as tiles.

    One panel per subject and flow, at most four: "EU27, imports" asked as a share and as a value
    is one panel (the first step asked, and a share before a value), so the panels tell four
    different things.
    """
    rows, tiles, seen = [], [], set()
    lines = []  # (step, key of the line or None, who): a split in €/kg or kg gives both sides
    for n in sorted(steps, key=lambda n: records[n].spec["measure"] != "share"):  # stable sort
        spec = records[n].spec
        if spec.get("breakdown") != "partner_group":
            lines.append((n, None, _who(spec, sem, lang)))
        elif spec["measure"] in ("share", "value_eur"):  # the non-EU27 side is the rest
            lines.append((n, "EU27", _t("eu27", lang)))
        else:  # a value per kg or a mass does not add up: both sides tell something
            lines += [(n, "EU27", _t("eu27", lang)), (n, "NON_EU27", _t("extra", lang))]
    for n, key, who in lines:
        spec = records[n].spec
        flow, measure = spec["flow"], spec["measure"]
        subject = (who, flow, _MEASURE_GROUP[measure])
        if subject in seen or len(seen) == MAX_PANELS:
            continue
        mine = sorted(
            (
                r
                for r in records[n].frames.get("main", [])
                if r.get("flow") == flow
                and r.get("value") is not None
                and (key is None or r.get("key") == key)
            ),
            key=lambda r: r["period"],
        )
        if len(mine) < 2:
            continue
        seen.add(subject)
        fl = _scope(spec, flow, sem, lang)
        panel = _t(_PANEL.get(measure, "p_value"), lang, who=who, flow=fl)
        for r in mine:
            rows.append(
                {
                    "group": int(r["period"]),
                    "series": panel,
                    "value": float(r["value"]),
                    "step": n,
                    "flow": flow,
                    "unit": measure,
                }
            )
        first, last = float(mine[0]["value"]), float(mine[-1]["value"])

        def show(v: float, m: str = measure) -> str:
            return fmt_measure(v, m, lang)  # %, €, €/kg or kg

        tiles.append(
            {
                "value": show(last),
                "label": f"{panel}, {int(mine[-1]['period'])}",
                "detail": _t("k_share_d", lang, value=show(first), year=int(mine[0]["period"])),
                "tone": "up" if last > first else "down",
            }
        )
    if len({r["series"] for r in rows}) < 2:
        return None
    years = sorted({r["group"] for r in rows})
    used = sorted({r["step"] for r in rows})
    return EvidenceFigure(
        kind="series",
        title=_t("t_series", lang, y0=years[0], y1=years[-1]),
        flow="both" if len({r["flow"] for r in rows}) > 1 else rows[0]["flow"],
        steps=used,
        rows=rows,
        tiles=tiles[:4],
        note=_t("note_series", lang, steps=", ".join(map(str, used))),
    )


def _concentration(
    steps: list[int], records: dict[int, RunRecord], sem: SemanticLayer, lang: str
) -> EvidenceFigure | None:
    """One panel per flow and dimension, each step's index re-computed from its own SQL.

    Panels are ordered exports before imports, by product before by partner, so four steps
    make a 2 × 2 grid. A panel's tile shows its last value; it is red when concentration rose
    (more dependence) and green when it fell (more spread), as on the Overview card.
    """
    rows = []
    for n in steps:
        spec = records[n].spec
        dim = "partner" if spec.get("breakdown") == "partner" else "product"
        df = sem.query(records[n].sql)
        for r in df.itertuples():
            panel = (
                _T["panel"]
                .get(lang, _T["panel"]["en"])[dim]
                .format(flow=flow_label(str(r.flow), lang).capitalize())
            )
            rows.append(
                {
                    "group": int(r.period),
                    "series": panel,
                    "value": float(r.hhi),
                    "step": n,
                    "flow": str(r.flow),
                    "dim": dim,
                }
            )
    if not rows:
        return None
    order = {("export", "product"): 0, ("export", "partner"): 1}
    order |= {("import", "product"): 2, ("import", "partner"): 3}
    rows.sort(key=lambda r: (order.get((r["flow"], r["dim"]), 9), r["group"]))
    tiles = []
    for panel in dict.fromkeys(r["series"] for r in rows):
        mine = [r for r in rows if r["series"] == panel]
        first, last = mine[0], mine[-1]
        chg = 100 * (last["value"] / first["value"] - 1) if first["value"] else 0.0
        tiles.append(
            {
                "value": fmt_number(last["value"], 0, lang),
                "label": _t("k_hhi", lang, panel=panel, year=last["group"]),
                "detail": _t(
                    "k_hhi_d",
                    lang,
                    value=fmt_number(first["value"], 0, lang),
                    year=first["group"],
                    chg=fmt_pct(chg, lang, decimals=0, signed=True),
                )
                if len(mine) > 1
                else "",
                # red: more concentrated (more dependence); green: more spread
                "tone": "down" if last["value"] > first["value"] else "up",
            }
        )
    years = sorted({r["group"] for r in rows})
    flows = {r["flow"] for r in rows}
    return EvidenceFigure(
        kind="concentration",
        title=_t("t_hhi", lang, y0=years[0], y1=years[-1]),
        flow=flows.pop() if len(flows) == 1 else "both",
        steps=sorted(steps),
        rows=rows,
        tiles=tiles[:4],
        note=_t("note_hhi", lang, steps=", ".join(map(str, sorted(steps)))),
    )


def _figure(
    shape: tuple,
    steps: list[int],
    records: dict[int, RunRecord],
    headline: str,
    text: str,
    sem: SemanticLayer,
    lang: str,
) -> EvidenceFigure | None:
    kind, flow = shape[0], shape[3]
    recs = [records[n] for n in steps]
    labels = _labels(recs)
    values = {n: _values(records[n], sem, kind) for n in steps}
    named = _mentions(list(labels), headline, text)
    focus = sorted(named, key=lambda lab: -named[lab])[: MAX_FOCUS[kind]]
    if not focus:  # the answer names no item of these steps: show the most telling one
        if kind == "change":
            falls = {
                lab: [values[n][0].get(key) for n in steps if values[n][0].get(key, 0) < 0]
                for lab, key in labels.items()
            }
            focus = sorted(falls, key=lambda lab: (-len(falls[lab]), sum(falls[lab] or [0])))[:1]
        else:
            last = values[steps[-1]][0]
            focus = sorted(labels, key=lambda lab: -last.get(labels[lab], 0.0))[:3]
    if not focus:
        return None
    fl = _scope(records[steps[0]].spec, flow, sem, lang)  # a product filter is named
    whole_name = _t("all", lang, flow=fl)
    rows = []
    if kind == "change":
        for n in steps:
            spec = records[n].spec
            group = f"{spec['period_start'][:4]} → {spec['period_end'][:4]}"
            per_key, whole = values[n]
            for lab in focus:
                rows.append(
                    {"group": group, "series": lab, "value": per_key.get(labels[lab]), "step": n}
                )
            rows.append({"group": group, "series": whole_name, "value": whole, "step": n})
        title = _t("t_change", lang, focus=" & ".join(focus), flow=fl)
        tiles = _change_tiles(rows, focus[0], whole_name, fl, lang)
    else:
        years = [records[n].spec["period_start"][:4] for n in steps]
        for n, year in zip(steps, years, strict=True):
            per_key, _ = values[n]
            for lab in focus:
                rows.append(
                    {"group": lab, "series": year, "value": per_key.get(labels[lab]), "step": n}
                )
        title = _t("t_share", lang, flow=fl, y0=years[0], y1=years[-1])
        tiles = _share_tiles(rows, focus, years, fl, lang)
    rows = [r for r in rows if r["value"] is not None and r["value"] == r["value"]]  # drop NaN
    if not rows:
        return None
    steps_text = ", ".join(map(str, steps))
    return EvidenceFigure(
        kind=kind,
        title=title,
        flow=flow,
        steps=steps,
        rows=rows,
        tiles=tiles,
        note=_t("note", lang, steps=steps_text, flow=fl),
    )


def _change_tiles(rows: list[dict], focus: str, whole: str, fl: str, lang: str) -> list[dict]:
    mine = [r for r in rows if r["series"] == focus and r["value"] is not None]
    totals = {r["group"]: r["value"] for r in rows if r["series"] == whole}
    if not mine:
        return []
    falls = [r for r in mine if r["value"] < 0]
    tiles = [
        {
            "value": f"{len(falls)} / {len(mine)}",
            "label": _t("k_falls", lang, focus=focus, flow=fl),
            "detail": " · ".join(fmt_pct(r["value"], lang, decimals=0, signed=True) for r in mine),
            "tone": "down" if falls else "",
        }
    ]
    mean_mine = sum(r["value"] for r in mine) / len(mine)
    whole_vals = [totals[r["group"]] for r in mine if totals.get(r["group"]) is not None]
    mean_whole = sum(whole_vals) / len(whole_vals) if whole_vals else 0.0
    if mean_mine < 0 and mean_whole < 0:
        tiles.append(
            {
                "value": f"{mean_mine / mean_whole:.1f} ×",
                "label": _t("k_ratio", lang, flow=fl),
                "detail": _t(
                    "k_ratio_d",
                    lang,
                    a=fmt_pct(mean_mine, lang, signed=True),
                    b=fmt_pct(mean_whole, lang, signed=True),
                ),
                "tone": "down",
            }
        )
    worst = min(mine, key=lambda r: r["value"])
    tiles.append(
        {
            "value": fmt_pct(worst["value"], lang, signed=True),
            "label": _t("k_worst", lang, focus=focus, period=worst["group"]),
            "detail": _t(
                "k_worst_d",
                lang,
                flow=fl,
                total=fmt_pct(totals.get(worst["group"]), lang, signed=True),
            ),
            "tone": "down" if worst["value"] < 0 else "up",
        }
    )
    return tiles


def _share_tiles(
    rows: list[dict], focus: list[str], years: list[str], fl: str, lang: str
) -> list[dict]:
    tiles = []
    for lab in focus[:2]:
        vals = {
            r["series"]: r["value"] for r in rows if r["group"] == lab and r["value"] is not None
        }
        first, last = vals.get(years[0]), vals.get(years[-1])
        if last is None:
            continue
        detail = _t("k_share_d", lang, value=fmt_pct(first, lang), year=years[0]) if first else ""
        tiles.append(
            {
                "value": fmt_pct(last, lang),
                "label": _t("k_share", lang, focus=lab, flow=fl, year=years[-1]),
                "detail": detail,
                "tone": "",
            }
        )
        if first is not None and len(tiles) < 3:
            pp = last - first
            tiles.append(
                {
                    "value": fmt_pct(pp, lang, signed=True).replace("%", "pp"),
                    "label": _t("k_pp", lang, focus=lab),
                    "detail": f"{years[0]} → {years[-1]}",
                    "tone": "up" if pp > 0 else "down",
                }
            )
    return tiles[:4]
