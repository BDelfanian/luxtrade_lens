"""Fact sheet: the pre-computed, pre-formatted facts the insight writer may use (SOLUTION_DESIGN §5.7).

Also builds the deterministic template insight used when the LLM is unavailable or its text
fails the grounding check, and the chart's takeaway title.
"""

import pandas as pd
from pydantic import BaseModel, Field

from luxtrade.agents.analyse import Analysis
from luxtrade.agents.spec import Limitation, QuerySpec
from luxtrade.analytics import rankings, timeseries
from luxtrade.semantic.layer import SemanticLayer
from luxtrade.viz.format import flow_label, fmt_eur, fmt_pct, fmt_period, month_name

_T = {
    "rank": {
        "en": "In {period}, the largest {what} for {flow} was {name} with {value} ({share} of {total}).",
        "fr": "En {period}, le premier {what} pour les {flow} était {name} avec {value} ({share} d'un total de {total}).",
        "de": "{period} war {name} {what} für die {flow} mit {value} ({share} von insgesamt {total}).",
    },
    "top3": {
        "en": "The top three ({names}) account for {conc} of {flow}.",
        "fr": "Les trois premiers ({names}) représentent {conc} du total ({flow}).",
        "de": "Die drei größten ({names}) machen {conc} des Gesamtwerts aus ({flow}).",
    },
    "what_partner": {"en": "partner", "fr": "partenaire", "de": "der wichtigste Partner"},
    "what_product": {
        "en": "product group",
        "fr": "groupe de produits",
        "de": "die wichtigste Warengruppe",
    },
    "series": {
        "en": "Between {start} and {end}, {flow}{scope} went from {v0} to {v1} ({chg}).",
        "fr": "Entre {start} et {end}, les {flow}{scope} sont passées de {v0} à {v1} ({chg}).",
        "de": "Zwischen {start} und {end} entwickelten sich die {flow}{scope} von {v0} auf {v1} ({chg}).",
    },
    "peak": {
        "en": "The highest value was reached in {when} ({value}).",
        "fr": "Le niveau le plus élevé a été atteint en {when} ({value}).",
        "de": "Der höchste Wert wurde {when} erreicht ({value}).",
    },
    "single": {
        "en": "In {period}, {flow}{scope} totalled {value} ({chg} compared with {prev}).",
        "fr": "En {period}, les {flow}{scope} ont atteint {value} ({chg} par rapport à {prev}).",
        "de": "{period} beliefen sich die {flow}{scope} auf {value} ({chg} gegenüber {prev}).",
    },
    "season": {
        "en": "For {flow}, the strongest month is usually {mmax} ({fmax} above a typical month) and the weakest {mmin} ({fmin} below).",
        "fr": "Pour les {flow}, le mois le plus fort est généralement {mmax} ({fmax} au-dessus d'un mois type) et le plus faible {mmin} ({fmin} en dessous).",
        "de": "Für die {flow} ist {mmax} meist der stärkste Monat ({fmax} über einem typischen Monat) und {mmin} der schwächste ({fmin} darunter).",
    },
    "adjusted": {
        "en": "Without seasonal effects, {flow} stood at {value} in {when}.",
        "fr": "Hors effets saisonniers, les {flow} s'élevaient à {value} en {when}.",
        "de": "Saisonbereinigt lagen die {flow} im {when} bei {value}.",
    },
    "forecast": {
        "en": "If past patterns continue, {flow} would be about {value} in {when} (80 % range {lo} to {hi}).",
        "fr": "Si les tendances passées se poursuivent, les {flow} atteindraient environ {value} en {when} (fourchette à 80 % : {lo} à {hi}).",
        "de": "Setzen sich die bisherigen Muster fort, lägen die {flow} {when} bei etwa {value} (80-%-Spanne {lo} bis {hi}).",
    },
    "bench": {
        "en": "From {start} to {end}, Luxembourg's trade index reached {lu} (base {start} = 100), against {best} for {best_name} and {worst} for {worst_name}.",
        "fr": "De {start} à {end}, l'indice des échanges du Luxembourg a atteint {lu} (base {start} = 100), contre {best} pour {best_name} et {worst} pour {worst_name}.",
        "de": "Von {start} bis {end} erreichte Luxemburgs Handelsindex {lu} ({start} = 100), gegenüber {best} für {best_name} und {worst} für {worst_name}.",
    },
    "intra": {
        "en": "In {end}, {share} of Luxembourg's trade was with EU countries.",
        "fr": "En {end}, {share} des échanges du Luxembourg se faisaient avec des pays de l'UE.",
        "de": "{end} entfielen {share} des Handels Luxemburgs auf EU-Länder.",
    },
    "pivot": {
        "en": "Over {start}–{end}, the largest value is {name} in {period} with {value}.",
        "fr": "Sur {start}–{end}, la valeur la plus élevée est {name} en {period} avec {value}.",
        "de": "Im Zeitraum {start}–{end} ist der größte Wert {name} im Jahr {period} mit {value}.",
    },
    "limits": {
        "en": "See the notes below for the data limits that apply.",
        "fr": "Voir les remarques ci-dessous sur les limites des données qui s'appliquent.",
        "de": "Hinweise zu den geltenden Datengrenzen finden Sie unten.",
    },
    "nodata": {
        "en": "No trade is recorded for this selection.",
        "fr": "Aucun échange n'est enregistré pour cette sélection.",
        "de": "Für diese Auswahl ist kein Handel verzeichnet.",
    },
}


class Fact(BaseModel):
    """One formatted fact: the insight may only use numbers that appear here."""

    key: str
    text: str


class FactSheet(BaseModel):
    """Everything the insight writer is allowed to say."""

    language: str
    question: str = ""
    title: str = ""
    facts: list[Fact] = Field(default_factory=list)
    entities: list[str] = Field(default_factory=list)  # partner codes the text may name
    limitations: list[str] = Field(default_factory=list)
    previous: str = ""  # previous turn's headline (follow-ups)
    template: list[str] = Field(default_factory=list)  # deterministic fallback sentences


def _t(template: str, lang: str, **values: object) -> str:
    return _T[template][lang].format(**values)


def _scope(spec: QuerySpec, sem: SemanticLayer) -> str:
    parts = [sem.label(p, "partner", spec.language) for p in spec.partners]
    parts += [sem.label(p, "product", spec.language) for p in spec.products]
    return f" ({', '.join(parts)})" if parts else ""


def _period_text(spec: QuerySpec) -> str:
    start, end = spec.period_start or "", spec.period_end or ""
    return start if start == end else f"{start}–{end}"


def _ranking_facts(spec: QuerySpec, a: Analysis, lang: str) -> tuple[list[Fact], list[str], str]:
    facts, sents, title = [], [], ""
    what = _T["what_partner" if spec.breakdown == "partner" else "what_product"][lang]
    period = _period_text(spec)
    for flow in [f for f in ("export", "import", "total", "balance") if f in set(a.main["flow"])]:
        part = a.main[a.main["flow"] == flow]
        items = part[part["kind"] == "item"].sort_values("rank")
        if items.empty:
            continue
        total = part["value"].sum()
        fl = flow_label(flow, lang)
        facts.append(Fact(key=f"{flow}.total", text=f"{fl} {period}: {fmt_eur(total, lang)}"))
        for _, row in items.head(5).iterrows():
            share = f", {fmt_pct(row['share'], lang)}" if pd.notna(row["share"]) else ""
            facts.append(
                Fact(
                    key=f"{flow}.rank{int(row['rank'])}",
                    text=f"#{int(row['rank'])} {row['label']}: {fmt_eur(row['value'], lang)}{share}",
                )
            )
        for _, row in part[part["kind"] != "item"].iterrows():
            facts.append(
                Fact(
                    key=f"{flow}.{row['key'].lower()}",
                    text=f"{row['label']}: {fmt_eur(row['value'], lang)}, {fmt_pct(row['share'], lang)}",
                )
            )
        if flow == "balance":
            continue
        top = items.iloc[0]
        conc = rankings.concentration(items["share"], 3)
        facts.append(Fact(key=f"{flow}.top3_share", text=f"top 3 {fl}: {fmt_pct(conc, lang)}"))
        if flow in ("export", "import") or len(sents) < 2:
            sents.append(
                _t(
                    "rank",
                    lang,
                    period=period,
                    what=what,
                    flow=fl,
                    name=top["label"],
                    value=fmt_eur(top["value"], lang),
                    share=fmt_pct(top["share"], lang),
                    total=fmt_eur(total, lang),
                )
            )
        if not title:
            title = f"{top['label']} — {fl} {period} ({fmt_pct(top['share'], lang)})"
        if flow == "total" or len(set(a.main["flow"])) == 1:
            names = ", ".join(items.head(3)["label"])
            sents.append(_t("top3", lang, names=names, conc=fmt_pct(conc, lang), flow=fl))
    return facts, sents, title


def _series_facts(spec: QuerySpec, a: Analysis, sem: SemanticLayer, lang: str):  # noqa: ANN202
    facts, sents, title = [], [], ""
    by = "key" if "key" in a.main.columns else "flow"
    groups = list(a.main.groupby([by, "flow"] if by == "key" else ["flow"]))[:4]
    for gkey, g in groups:
        g = g.sort_values("period")
        if g.empty:
            continue
        flow = gkey[-1] if isinstance(gkey, tuple) else gkey
        flow = flow if isinstance(flow, str) else g["flow"].iloc[0]
        name = g["label"].iloc[0] if "label" in g.columns else ""
        fl = flow_label(flow, lang)
        first, last = g.iloc[0], g.iloc[-1]
        v0, v1 = float(first["value"]), float(last["value"])
        chg = timeseries.change_pct(v0, v1)
        chg_text = fmt_pct(chg, lang, signed=True) if chg is not None else "–"
        p0, p1 = fmt_period(_py(first["period"]), lang), fmt_period(_py(last["period"]), lang)
        label = f"{name} · {fl}" if name else fl
        facts += [
            Fact(key=f"{label}.start", text=f"{label} {p0}: {fmt_eur(v0, lang)}"),
            Fact(key=f"{label}.end", text=f"{label} {p1}: {fmt_eur(v1, lang)}"),
            Fact(key=f"{label}.change", text=f"{label} change {p0}–{p1}: {chg_text}"),
        ]
        pk_idx, pk_val = timeseries.peak(g.set_index("period")["value"])
        facts.append(
            Fact(
                key=f"{label}.peak",
                text=f"{label} peak {fmt_period(_py(pk_idx), lang)}: {fmt_eur(pk_val, lang)}",
            )
        )
        if len(sents) < 2:
            scope = f" ({name})" if name else _scope(spec, sem)
            sents.append(
                _t(
                    "series",
                    lang,
                    start=p0,
                    end=p1,
                    flow=fl,
                    scope=scope,
                    v0=fmt_eur(v0, lang),
                    v1=fmt_eur(v1, lang),
                    chg=chg_text,
                )
            )
        if not title:
            title = f"{label}: {chg_text} ({p0}–{p1})"
    if groups and len(sents) < 3:
        g = groups[0][1].sort_values("period")
        pk_idx, pk_val = timeseries.peak(g.set_index("period")["value"])
        sents.append(
            _t("peak", lang, when=fmt_period(_py(pk_idx), lang), value=fmt_eur(pk_val, lang))
        )
    return facts, sents, title


def _py(value: object) -> object:
    if isinstance(value, pd.Timestamp):
        return value.date()
    if hasattr(value, "item"):
        return value.item()
    return value


def build_fact_sheet(
    spec: QuerySpec,
    a: Analysis | None,
    lims: list[Limitation],
    sem: SemanticLayer,
    question: str = "",
    previous: str = "",
) -> FactSheet:
    """Compute the formatted facts, the takeaway title and the template insight."""
    lang = spec.language
    facts: list[Fact] = []
    sents: list[str] = []
    title = ""
    if a is None or a.main.empty:
        sents.append(_t("nodata", lang))
    elif spec.intent in ("ranking", "composition", "drilldown"):
        facts, sents, title = _ranking_facts(spec, a, lang)
    elif spec.intent == "time_series":
        facts, sents, title = _series_facts(spec, a, sem, lang)
    elif spec.intent == "single_value":
        for flow, g in a.main.groupby("flow"):
            g = g.sort_values("period")
            fl = flow_label(flow, lang)
            cur = g.iloc[-1]
            facts.append(
                Fact(
                    key=f"{flow}.value",
                    text=f"{fl} {int(cur['period'])}: {fmt_eur(cur['value'], lang)}",
                )
            )
            if len(g) > 1:
                prev = g.iloc[-2]
                chg = timeseries.change_pct(prev["value"], cur["value"])
                chg_text = fmt_pct(chg, lang, signed=True) if chg is not None else "–"
                facts += [
                    Fact(
                        key=f"{flow}.previous",
                        text=f"{fl} {int(prev['period'])}: {fmt_eur(prev['value'], lang)}",
                    ),
                    Fact(key=f"{flow}.change", text=f"{fl} change: {chg_text}"),
                ]
                sents.append(
                    _t(
                        "single",
                        lang,
                        period=int(cur["period"]),
                        flow=fl,
                        scope=_scope(spec, sem),
                        value=fmt_eur(cur["value"], lang),
                        chg=chg_text,
                        prev=int(prev["period"]),
                    )
                )
                title = (
                    title
                    or f"{fl} {int(cur['period'])}: {fmt_eur(cur['value'], lang)} ({chg_text})"
                )
    elif spec.intent == "seasonality":
        prof = a.extra.get("profile", pd.DataFrame())
        for flow, g in prof.groupby("flow"):
            fl = flow_label(flow, lang)
            hi, lo = g.loc[g["factor"].idxmax()], g.loc[g["factor"].idxmin()]
            fmax, fmin = (
                fmt_pct(100 * (hi["factor"] - 1), lang),
                fmt_pct(100 * (1 - lo["factor"]), lang),
            )
            mmax, mmin = month_name(int(hi["month"]), lang), month_name(int(lo["month"]), lang)
            facts += [
                Fact(key=f"{flow}.strongest", text=f"{fl} strongest month {mmax}: +{fmax}"),
                Fact(key=f"{flow}.weakest", text=f"{fl} weakest month {mmin}: −{fmin}"),
            ]
            sents.append(_t("season", lang, flow=fl, mmax=mmax, fmax=fmax, mmin=mmin, fmin=fmin))
            last = a.main[a.main["flow"] == flow].sort_values("period").iloc[-1]
            when = fmt_period(_py(last["period"]), lang)
            facts.append(
                Fact(
                    key=f"{flow}.adjusted_last",
                    text=f"{fl} adjusted {when}: {fmt_eur(last['adjusted'], lang)}",
                )
            )
            sents.append(
                _t("adjusted", lang, flow=fl, value=fmt_eur(last["adjusted"], lang), when=when)
            )
            title = title or f"{fl}: {mmax} +{fmax}, {mmin} −{fmin}"
    elif spec.intent == "forecast":
        for flow, g in a.main.groupby("flow"):
            fl = flow_label(flow, lang)
            hist, proj = g[g["kind"] == "actual"], g[g["kind"] == "projection"]
            last = hist.sort_values("period").iloc[-1]
            facts.append(
                Fact(
                    key=f"{flow}.last_actual",
                    text=f"{fl} {fmt_period(_py(last['period']), lang)}: {fmt_eur(last['value'], lang)}",
                )
            )
            if proj.empty:
                continue
            end = proj.sort_values("period").iloc[-1]
            when = fmt_period(_py(end["period"]), lang)
            facts.append(
                Fact(
                    key=f"{flow}.projection_end",
                    text=f"{fl} projection {when}: {fmt_eur(end['value'], lang)} "
                    f"(80 %: {fmt_eur(end['lo80'], lang)}–{fmt_eur(end['hi80'], lang)})",
                )
            )
            sents.append(
                _t(
                    "forecast",
                    lang,
                    flow=fl,
                    value=fmt_eur(end["value"], lang),
                    when=when,
                    lo=fmt_eur(end["lo80"], lang),
                    hi=fmt_eur(end["hi80"], lang),
                )
            )
            title = title or f"{fl}: {fmt_eur(end['value'], lang)} {when}"
        facts += [Fact(key=f"method{i}", text=m) for i, m in enumerate(a.methods)]
    elif spec.intent == "benchmark":
        last_p, first_p = int(a.main["period"].max()), int(a.main["period"].min())
        latest = a.main[a.main["period"] == last_p].set_index("reporter")
        for r, row in latest.iterrows():
            facts.append(
                Fact(key=f"{r}.index", text=f"{row['label']} index {last_p}: {row['index']:.0f}")
            )
            facts.append(
                Fact(
                    key=f"{r}.intra",
                    text=f"{row['label']} intra-EU share {last_p}: {fmt_pct(row['intra_share'], lang)}",
                )
            )
        others = latest.drop(index="LU", errors="ignore").sort_values("index")
        if "LU" in latest.index and len(others):
            best, worst = others.iloc[-1], others.iloc[0]
            sents.append(
                _t(
                    "bench",
                    lang,
                    start=first_p,
                    end=last_p,
                    lu=f"{latest.loc['LU', 'index']:.0f}",
                    best=f"{best['index']:.0f}",
                    best_name=best["label"],
                    worst=f"{worst['index']:.0f}",
                    worst_name=worst["label"],
                )
            )
            sents.append(
                _t("intra", lang, end=last_p, share=fmt_pct(latest.loc["LU", "intra_share"], lang))
            )
            lu_index = latest.loc["LU", "index"]
            title = f"Luxembourg {first_p}–{last_p}: {lu_index:.0f} (index {first_p} = 100)"
    elif spec.intent == "pivot":
        top = a.main.sort_values("value", ascending=False).iloc[0]
        facts.append(
            Fact(
                key="pivot.max",
                text=f"{top['label']} {int(top['period'])}: {fmt_eur(top['value'], lang)}",
            )
        )
        sents.append(
            _t(
                "pivot",
                lang,
                start=spec.period_start,
                end=spec.period_end,
                name=top["label"],
                period=int(top["period"]),
                value=fmt_eur(top["value"], lang),
            )
        )
        title = f"{top['label']}: {fmt_eur(top['value'], lang)} ({int(top['period'])})"

    warn = [lim for lim in lims if lim.severity == "warn" and lim.id != "L06"]
    if warn or any(lim.id == "L06" for lim in lims):
        sents.append(_t("limits", lang))
    entities = []
    if a is not None:
        entities = list(a.entities.get("partners", []))
        if "key" in a.main.columns and spec.breakdown == "partner":
            entities = list(dict.fromkeys(entities + list(a.main["key"].astype(str))))
    entities += spec.partners
    return FactSheet(
        language=lang,
        question=question,
        title=title or question[:80],
        facts=facts,
        entities=list(dict.fromkeys(entities)),
        limitations=[lim.message for lim in lims],
        previous=previous,
        template=sents[:5],
    )
