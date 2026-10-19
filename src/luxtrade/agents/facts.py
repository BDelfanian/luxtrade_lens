"""Fact sheet: the pre-computed, pre-formatted facts the insight writer may use (SOLUTION_DESIGN §5.7).

Also builds the deterministic template insight used when the LLM is unavailable or its text
fails the grounding check, and the chart's takeaway title.
"""

import pandas as pd
from pydantic import BaseModel, Field

from luxtrade.agents.analyse import HHI_HIGH, HHI_MODERATE, Analysis
from luxtrade.agents.spec import SPLIT_BREAKDOWNS, Limitation, QuerySpec
from luxtrade.analytics import rankings, timeseries
from luxtrade.semantic.layer import SemanticLayer
from luxtrade.viz.format import (
    flow_label,
    fmt_eur,
    fmt_measure,
    fmt_number,
    fmt_pct,
    fmt_period,
    month_name,
)

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
    "split": {
        "en": "In {period}, {name} accounted for {share} of {flow}{scope} ({value} of {total}).",
        "fr": "En {period}, {name} représentaient {share} des {flow}{scope} ({value} sur {total}).",
        "de": "{period} entfielen {share} der {flow}{scope} auf {name} ({value} von {total}).",
    },
    # shares of the whole flow (compile_sql.share_base): the selection and the whole it is of
    "selection": {
        "en": "{flow} {period}, selection: {value}",
        "fr": "{flow} {period}, sélection : {value}",
        "de": "{flow} {period}, Auswahl: {value}",
    },
    "whole": {
        "en": "{flow} {period}, all {of}: {value}",
        "fr": "{flow} {period}, tous {of} : {value}",
        "de": "{flow} {period}, alle {of}: {value}",
    },
    "of_partner": {"en": "partners", "fr": "partenaires", "de": "Partner"},
    "of_product": {"en": "products", "fr": "produits", "de": "Waren"},
    "what_partner": {"en": "partner", "fr": "partenaire", "de": "der wichtigste Partner"},
    "what_product": {
        "en": "product group",
        "fr": "groupe de produits",
        "de": "die wichtigste Warengruppe",
    },
    "title_partner": {
        "en": "Main trading partners",
        "fr": "Principaux partenaires commerciaux",
        "de": "Wichtigste Handelspartner",
    },
    "title_product": {
        "en": "Main product groups",
        "fr": "Principaux groupes de produits",
        "de": "Wichtigste Warengruppen",
    },
    # the shape of a series: what tells a lasting trend from a jump in the last period
    "y_obs": {
        "en": "{flow} total {year} (observed): {value}",
        "fr": "{flow}, total {year} (observé) : {value}",
        "de": "{flow}, Summe {year} (beobachtet): {value}",
    },
    "y_proj": {
        "en": "{flow} projected total {year}: {value} (80 %: {lo} to {hi}), {chg} on {base}",
        "fr": "{flow}, total projeté {year} : {value} (80 % : {lo} à {hi}), {chg} par rapport à {base}",
        "de": "{flow}, projizierte Summe {year}: {value} (80 %: {lo} bis {hi}), {chg} gegenüber {base}",
    },
    "y_part": {
        "en": "{flow} projected for the last {months} months of {year}: {value} (80 %: {lo} to {hi})",
        "fr": "{flow}, projeté pour les {months} derniers mois de {year} : {value} (80 % : {lo} à {hi})",
        "de": "{flow}, projiziert für die letzten {months} Monate {year}: {value} (80 %: {lo} bis {hi})",
    },
    "s_move": {
        "en": "{label}: largest change between consecutive periods {pa}–{pb}: {va} to {vb}",
        "fr": "{label} : plus forte variation entre deux périodes {pa}–{pb} : {va} à {vb}",
        "de": "{label}: größte Veränderung zwischen zwei Perioden {pa}–{pb}: {va} auf {vb}",
    },
    "s_median": {
        "en": "{label}: median over {p0}–{p1}: {v}",
        "fr": "{label} : médiane sur {p0}–{p1} : {v}",
        "de": "{label}: Median über {p0}–{p1}: {v}",
    },
    "s_jump": {
        "en": "{label}: the last change ({pa}–{pb}) is more than twice any earlier one: a jump in the last period, not yet a trend",
        "fr": "{label} : la dernière variation ({pa}–{pb}) dépasse le double de toutes les précédentes : un saut sur la dernière période, pas encore une tendance",
        "de": "{label}: die letzte Veränderung ({pa}–{pb}) ist mehr als doppelt so groß wie jede frühere: ein Sprung in der letzten Periode, noch kein Trend",
    },
    "s_top2": {
        "en": "{label}: the two largest periods ({pa}, {pb}) make {pct} of the total over {p0}–{p1}",
        "fr": "{label} : les deux plus fortes périodes ({pa}, {pb}) font {pct} du total sur {p0}–{p1}",
        "de": "{label}: die zwei stärksten Perioden ({pa}, {pb}) machen {pct} der Summe {p0}–{p1} aus",
    },
    "gap": {
        "en": "Value per kg, non-EU27 ÷ EU27 ({flow})",
        "fr": "Valeur au kg, hors UE27 ÷ UE27 ({flow})",
        "de": "Wert je kg, Nicht-EU27 ÷ EU27 ({flow})",
    },
    "gap_hi": {"en": ", highest", "fr": ", maximum", "de": ", höchster"},
    "gap_lo": {"en": ", lowest", "fr": ", minimum", "de": ", niedrigster"},
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
    "rise": {
        "en": "Between {start} and {end}, the largest rise in {flow} was {name}: +{delta} ({v0} to {v1}).",
        "fr": "Entre {start} et {end}, la plus forte hausse des {flow} concerne {name} : +{delta} (de {v0} à {v1}).",
        "de": "Zwischen {start} und {end} verzeichnete {name} den stärksten Anstieg der {flow}: +{delta} (von {v0} auf {v1}).",
    },
    "fall": {
        "en": "The largest fall in {flow} was {name}: −{delta} ({v0} to {v1}).",
        "fr": "La plus forte baisse des {flow} concerne {name} : −{delta} (de {v0} à {v1}).",
        "de": "Den stärksten Rückgang der {flow} verzeichnete {name}: −{delta} (von {v0} auf {v1}).",
    },
    "title_change": {
        "en": "Largest changes by {what}",
        "fr": "Plus fortes variations par {what}",
        "de": "Größte Veränderungen nach {what}",
    },
    "by_partner": {"en": "partner", "fr": "partenaire", "de": "Partner"},
    "by_product": {"en": "product group", "fr": "groupe de produits", "de": "Warengruppe"},
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


# Split keys as they read inside the "split" sentence (chart labels are in semantic.layer)
_SPLIT_NAMES = {
    "EU27": ("EU27 countries", "les pays de l'UE27", "EU27-Länder"),
    "NON_EU27": ("non-EU27 countries", "les pays hors UE27", "Nicht-EU27-Länder"),
    "CONFIDENTIAL": (
        "confidential trade (not published at CN8 level)",
        "les échanges confidentiels (non publiés au niveau NC8)",
        "vertraulichen Handel (nicht auf KN8-Ebene veröffentlicht)",
    ),
    "DISCLOSED": (
        "trade published at CN8 level",
        "les échanges publiés au niveau NC8",
        "auf KN8-Ebene veröffentlichten Handel",
    ),
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


# what an undisclosed partner is: seen on real data, a growing undisclosed share of fuel imports
# was written up as "diversification beyond the Belgian route"
_HIDDEN = {
    "en": " (partner withheld for confidentiality: it may be any country, the main ones included)",
    "fr": " (partenaire masqué pour confidentialité : ce peut être n'importe quel pays, y compris "
    "les principaux)",
    "de": " (Partner aus Vertraulichkeitsgründen verborgen: es kann jedes Land sein, auch die "
    "wichtigsten)",
}


def _t(template: str, lang: str, **values: object) -> str:
    return _T[template][lang].format(**values)


def _scope(spec: QuerySpec, sem: SemanticLayer) -> str:
    parts = [sem.label(p, "partner", spec.language) for p in spec.partners]
    parts += [sem.label(p, "product", spec.language) for p in spec.products]
    return f" ({', '.join(parts)})" if parts else ""


def _period_text(spec: QuerySpec) -> str:
    start, end = spec.period_start or "", spec.period_end or ""
    return start if start == end else f"{start}–{end}"


def _wholes(a: Analysis) -> dict[str, float]:
    """Each flow's whole when shares are of the whole flow (``compile_sql.share_base``)."""
    totals = a.extra.get("totals")
    if totals is None or "period" in totals.columns:
        return {}
    wholes = {str(r["flow"]): float(r["value"]) for _, r in totals.iterrows()}
    if {"export", "import"} <= set(wholes):
        wholes["total"] = wholes["export"] + wholes["import"]
    return wholes


def _ranking_facts(spec: QuerySpec, a: Analysis, lang: str) -> tuple[list[Fact], list[str], str]:
    facts, sents = [], []
    kind = "partner" if spec.breakdown == "partner" else "product"
    what = _T[f"what_{kind}"][lang]
    period = _period_text(spec)
    flows = [f for f in ("export", "import", "total", "balance") if f in set(a.main["flow"])]
    # the chart shows the whole ranking, so the title names it (not the top item)
    scope = f"{flow_label(flows[0], lang)} {period}" if len(flows) == 1 else period
    title = f"{_t(f'title_{kind}', lang)} — {scope}"
    wholes = _wholes(a)
    for flow in flows:
        part = a.main[a.main["flow"] == flow]
        items = part[part["kind"] == "item"].sort_values("rank")
        if items.empty:
            continue
        total = part["value"].sum()
        fl = flow_label(flow, lang)
        if flow in wholes:  # shares are of the whole flow, not of the selection
            sel = _t("selection", lang, flow=fl, period=period, value=fmt_eur(total, lang))
            total = wholes[flow]
            of = _t(f"of_{kind}", lang)
            facts.append(Fact(key=f"{flow}.selection", text=sel))
            facts.append(
                Fact(
                    key=f"{flow}.total",
                    text=_t(
                        "whole", lang, flow=fl, period=period, of=of, value=fmt_eur(total, lang)
                    ),
                )
            )
        else:
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
            hidden = _HIDDEN[lang] if row["key"] == rankings.UNDISCLOSED else ""
            facts.append(
                Fact(
                    key=f"{flow}.{row['key'].lower()}",
                    text=f"{row['label']}{hidden}: {fmt_eur(row['value'], lang)}, "
                    f"{fmt_pct(row['share'], lang)}",
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
        if flow == "total" or len(set(a.main["flow"])) == 1:
            names = ", ".join(items.head(3)["label"])
            sents.append(_t("top3", lang, names=names, conc=fmt_pct(conc, lang), flow=fl))
    return facts, sents, title


def _change_facts(spec: QuerySpec, a: Analysis, lang: str) -> tuple[list[Fact], list[str], str]:
    facts, sents = [], []
    start, end = spec.period_start, spec.period_end
    flows = [f for f in ("export", "import", "balance") if f in set(a.main["flow"])]
    what = _t("by_partner" if spec.breakdown == "partner" else "by_product", lang)
    scope = f"{flow_label(flows[0], lang)} " if len(flows) == 1 else ""
    title = f"{_t('title_change', lang, what=what)} — {scope}{start}–{end}"
    for flow in flows:
        part = a.main[a.main["flow"] == flow].sort_values("change", ascending=False)
        fl = flow_label(flow, lang)
        for _, row in part.iterrows():
            pct = (
                fmt_pct(row["change_pct"], lang, signed=True)
                if pd.notna(row["change_pct"])
                else "–"
            )
            facts.append(
                Fact(
                    key=f"{flow}.{row['key']}",
                    text=f"{fl} {row['label']}: {fmt_eur(row['base'], lang)} {start} → "
                    f"{fmt_eur(row['value'], lang)} {end} ({fmt_eur(row['change'], lang)}, {pct})",
                )
            )
        for name, rows in (("rise", part[part["change"] > 0]), ("fall", part[part["change"] < 0])):
            if rows.empty or len(sents) >= 4:
                continue
            row = rows.iloc[0] if name == "rise" else rows.iloc[-1]  # sorted by change, desc
            sents.append(
                _t(
                    name,
                    lang,
                    start=start,
                    end=end,
                    flow=fl,
                    name=row["label"],
                    delta=fmt_eur(abs(row["change"]), lang),
                    v0=fmt_eur(row["base"], lang),
                    v1=fmt_eur(row["value"], lang),
                )
            )
    return facts, sents, title


def _split_facts(spec: QuerySpec, a: Analysis, sem: SemanticLayer, lang: str):  # noqa: ANN202
    """Facts for a two-way split: each part's value and share, the subject part first."""
    facts, sents, title = [], [], ""
    period, scope = _period_text(spec), _scope(spec, sem)
    idx = ("en", "fr", "de").index(lang)
    for flow in [f for f in ("export", "import") if f in set(a.main["flow"])]:
        part = a.main[a.main["flow"] == flow].sort_values("rank")
        total, fl = part["value"].sum(), flow_label(flow, lang)
        if spec.measure == "unit_value":  # a price per kg: no total, no shares
            for _, row in part.iterrows():
                value = fmt_measure(row["value"], spec.measure, lang)
                facts.append(
                    Fact(key=f"{flow}.{row['key'].lower()}", text=f"{row['label']}: {value}")
                )
            title = title or f"{fl} {period}: " + " · ".join(
                f"{r['label']} {fmt_measure(r['value'], spec.measure, lang)}"
                for _, r in part.iterrows()
            )
            continue
        facts.append(Fact(key=f"{flow}.total", text=f"{fl} {period}: {fmt_eur(total, lang)}"))
        for _, row in part.iterrows():
            facts.append(
                Fact(
                    key=f"{flow}.{row['key'].lower()}",
                    text=f"{row['label']}: {fmt_eur(row['value'], lang)}, "
                    f"{fmt_pct(row['share'], lang)}",
                )
            )
        subject = part.iloc[0]
        sents.append(
            _t(
                "split",
                lang,
                period=period,
                name=_SPLIT_NAMES[subject["key"]][idx],
                share=fmt_pct(subject["share"], lang),
                flow=fl,
                scope=scope,
                value=fmt_eur(subject["value"], lang),
                total=fmt_eur(total, lang),
            )
        )
        title = title or f"{subject['label']} — {fl} {period}: {fmt_pct(subject['share'], lang)}"
    return facts, sents, title


def _series_facts(spec: QuerySpec, a: Analysis, sem: SemanticLayer, lang: str):  # noqa: ANN202
    facts, sents, title = [], [], ""

    def fmt_v(value: float, lang: str) -> str:  # percentages, €/kg, kg or euros
        return fmt_measure(value, spec.measure, lang)

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
            Fact(key=f"{label}.start", text=f"{label} {p0}: {fmt_v(v0, lang)}"),
            Fact(key=f"{label}.end", text=f"{label} {p1}: {fmt_v(v1, lang)}"),
            Fact(key=f"{label}.change", text=f"{label} change {p0}–{p1}: {chg_text}"),
        ]
        pk_idx, pk_val = timeseries.peak(g.set_index("period")["value"])
        facts.append(
            Fact(
                key=f"{label}.peak",
                text=f"{label} peak {fmt_period(_py(pk_idx), lang)}: {fmt_v(pk_val, lang)}",
            )
        )
        facts += _series_shape(g, label, spec.measure, fmt_v, lang)
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
                    v0=fmt_v(v0, lang),
                    v1=fmt_v(v1, lang),
                    chg=chg_text,
                )
            )
        if not title:
            title = f"{label}: {chg_text} ({p0}–{p1})"
    if groups and len(sents) < 3:
        g = groups[0][1].sort_values("period")
        pk_idx, pk_val = timeseries.peak(g.set_index("period")["value"])
        sents.append(
            _t("peak", lang, when=fmt_period(_py(pk_idx), lang), value=fmt_v(pk_val, lang))
        )
    if spec.measure == "unit_value" and spec.breakdown == "partner_group":
        facts += _gap_facts(a.main, lang)
    return facts, sents, title


def _gap_facts(main: pd.DataFrame, lang: str) -> list[Fact]:
    """How many times a non-EU27 kilo is worth an EU27 one, year by year (computed by code).

    Seen on real data: both values per kg rose, and the answer called the gap "stable over two
    decades" while it went from 23 times (2005) to 29 (2015), 10 (2024) and 16 (2025).
    """
    out = []
    for flow, g in main.groupby("flow", sort=True):
        wide = g.pivot_table(index="period", columns="key", values="value")
        if not {"EU27", "NON_EU27"} <= set(wide.columns):
            continue
        ratio = (wide["NON_EU27"] / wide["EU27"]).dropna()
        if ratio.empty:
            continue
        label = _t("gap", lang, flow=flow_label(str(flow), lang))
        shown = [("", ratio.index[0]), ("", ratio.index[-1])]
        if len(ratio) >= 3:
            shown += [("", ratio.index[-2]), (_t("gap_hi", lang), ratio.idxmax())]
            shown += [(_t("gap_lo", lang), ratio.idxmin())]
        for word, p in dict.fromkeys(shown):
            out.append(
                Fact(
                    key=f"{flow}.gap.{word or 'year'}.{_py(p)}",
                    text=f"{label}{word} {fmt_period(_py(p), lang)}: "
                    f"{fmt_number(float(ratio[p]), 1, lang)} ×",
                )
            )
    return out


_HHI = {
    "across": {
        "partner": {"en": "partners", "fr": "partenaires", "de": "Partner"},
        "product": {"en": "product groups", "fr": "groupes de produits", "de": "Warengruppen"},
        "HS2": {"en": "product chapters", "fr": "chapitres de produits", "de": "Warenkapitel"},
    },
    "label": {
        "en": "Concentration (HHI) of {flow} across {across}",
        "fr": "Concentration (HHI) des {flow} entre {across}",
        "de": "Konzentration (HHI) der {flow} über {across}",
    },
    "level": {
        "low": {
            "en": "unconcentrated (below {a})",
            "fr": "peu concentré (moins de {a})",
            "de": "gering konzentriert (unter {a})",
        },
        "mid": {
            "en": "moderately concentrated ({a} to {b})",
            "fr": "modérément concentré ({a} à {b})",
            "de": "mäßig konzentriert ({a} bis {b})",
        },
        "high": {
            "en": "highly concentrated (above {b})",
            "fr": "fortement concentré (plus de {b})",
            "de": "hoch konzentriert (über {b})",
        },
    },
    "change": {
        "en": "{label}, change {p0}–{p1}: {chg}, {direction}",
        "fr": "{label}, évolution {p0}–{p1} : {chg}, {direction}",
        "de": "{label}, Veränderung {p0}–{p1}: {chg}, {direction}",
    },
    # what a change of the index means, so the answer never infers it the wrong way round
    "direction": {
        "down": {
            "en": "less concentrated (more diversified)",
            "fr": "moins concentré (plus diversifié)",
            "de": "weniger konzentriert (breiter gestreut)",
        },
        "up": {
            "en": "more concentrated (less diversified)",
            "fr": "plus concentré (moins diversifié)",
            "de": "stärker konzentriert (weniger gestreut)",
        },
        "flat": {
            "en": "about as concentrated as before",
            "fr": "concentration à peu près inchangée",
            "de": "etwa gleich stark konzentriert",
        },
    },
    "move": {
        "en": "{label}: the largest move was between {pa} and {pb} ({va} to {vb})",
        "fr": "{label} : la plus forte variation a eu lieu entre {pa} et {pb} ({va} à {vb})",
        "de": "{label}: die größte Veränderung lag zwischen {pa} und {pb} ({va} auf {vb})",
    },
    "flat": {
        "en": "{label}: from {pa} to {pb} it stayed between {lo} and {hi}",
        "fr": "{label} : de {pa} à {pb}, il est resté entre {lo} et {hi}",
        "de": "{label}: von {pa} bis {pb} blieb er zwischen {lo} und {hi}",
    },
    "equivalent": {
        "en": "{label}, {year}: the same as {k} equally sized {across} ({n} traded)",
        "fr": "{label}, {year} : équivaut à {k} {across} de même taille ({n} au total)",
        "de": "{label}, {year}: entspricht {k} gleich großen {across} ({n} insgesamt)",
    },
    "top": {
        "en": "Largest of the {n} {across} in {flow} {period}: {name}, {share} of the flow",
        "fr": "Premier des {n} {across} pour les {flow} {period} : {name}, {share} du flux",
        "de": "Größte(r) der {n} {across} bei den {flow} {period}: {name}, {share} des Flusses",
    },
    "sentence": {
        "en": "Between {p0} and {p1}, the concentration of {flow} across {across} (HHI) went "
        "from {v0} to {v1} ({chg}): {level}.",
        "fr": "Entre {p0} et {p1}, la concentration des {flow} entre {across} (HHI) est passée "
        "de {v0} à {v1} ({chg}) : {level}.",
        "de": "Zwischen {p0} und {p1} entwickelte sich die Konzentration der {flow} über "
        "{across} (HHI) von {v0} auf {v1} ({chg}): {level}.",
    },
}


def hhi_level(value: float, lang: str) -> str:
    """The reading of an HHI value (US Merger Guidelines 2023), with its thresholds."""
    band = "low" if value < HHI_MODERATE else ("mid" if value <= HHI_HIGH else "high")
    a, b = fmt_number(HHI_MODERATE, 0, lang), fmt_number(HHI_HIGH, 0, lang)
    return _HHI["level"][band][lang].format(a=a, b=b)


def _shape_facts(g: pd.DataFrame, label: str, flow: object, lang: str) -> list[Fact]:
    """When the index moved: its largest step, and the range it kept after it (if narrow).

    Seen on real data: imports by product, 880 → 617 → 621 → 554 → 562, written up as
    "stable" over 2005–2025. The facts now say the fall came in 2005–2010 and the index stayed
    between 554 and 621 after, so the answer can say both.
    """
    if len(g) < 3:
        return []
    values, years = list(g["value"].astype(float)), [int(p) for p in g["period"]]
    i = max(range(len(values) - 1), key=lambda k: abs(values[k + 1] - values[k]))

    def n(value: float) -> str:
        return fmt_number(value, 0, lang)

    out = [
        Fact(
            key=f"{flow}.hhi.move",
            text=_HHI["move"][lang].format(
                label=label, pa=years[i], pb=years[i + 1], va=n(values[i]), vb=n(values[i + 1])
            ),
        )
    ]
    after = values[i + 1 :]
    if len(after) >= 2 and max(after) <= 1.15 * min(after):  # within about ±7 % of the middle
        out.append(
            Fact(
                key=f"{flow}.hhi.flat",
                text=_HHI["flat"][lang].format(
                    label=label, pa=years[i + 1], pb=years[-1], lo=n(min(after)), hi=n(max(after))
                ),
            )
        )
    return out


def _concentration_facts(spec: QuerySpec, a: Analysis, lang: str):  # noqa: ANN202
    """Each year's index and its reading, the change, and the largest item at both ends.

    With up to six years every year is a fact (an "every five years" series); longer series
    give the first and last year, the highest and the lowest.
    """
    facts, sents, title = [], [], ""
    level = spec.product_level if spec.breakdown == "product" else "partner"
    across = _HHI["across"].get(level or "", _HHI["across"]["product"])[lang]
    for flow, g in a.main.groupby("flow", sort=True):
        g = g.sort_values("period").reset_index(drop=True)
        fl = flow_label(str(flow), lang)
        label = _HHI["label"][lang].format(flow=fl, across=across)
        if len(g) <= 6:
            shown = list(g.index)
        else:
            shown = sorted({0, len(g) - 1, int(g["value"].idxmax()), int(g["value"].idxmin())})
        for i in shown:
            row = g.loc[i]
            facts.append(
                Fact(
                    key=f"{flow}.hhi.{int(row['period'])}",
                    text=f"{label}, {int(row['period'])}: {fmt_number(row['value'], 0, lang)}, "
                    f"{hhi_level(float(row['value']), lang)}",
                )
            )
        first, last = g.iloc[0], g.iloc[-1]
        p0, p1 = int(first["period"]), int(last["period"])
        v0, v1 = float(first["value"]), float(last["value"])
        chg = timeseries.change_pct(v0, v1)
        chg_text = fmt_pct(chg, lang, signed=True) if chg is not None else "–"
        if p0 != p1:
            facts.append(
                Fact(
                    key=f"{flow}.hhi.change",
                    text=_HHI["change"][lang].format(
                        label=label,
                        p0=p0,
                        p1=p1,
                        chg=chg_text,
                        direction=_HHI["direction"][
                            "flat" if abs(chg or 0) < 5 else ("up" if v1 > v0 else "down")
                        ][lang],
                    ),
                )
            )
        facts += _shape_facts(g, label, flow, lang)
        for row in (first, last) if p0 != p1 else (last,):  # 10,000 / HHI: the main items
            facts.append(
                Fact(
                    key=f"{flow}.hhi.equivalent.{int(row['period'])}",
                    text=_HHI["equivalent"][lang].format(
                        label=label,
                        year=int(row["period"]),
                        k=fmt_number(10_000 / float(row["value"]), 1, lang),
                        across=across,
                        n=int(row["n"]),
                    ),
                )
            )
        for row in (first, last) if p0 != p1 else (last,):
            facts.append(
                Fact(
                    key=f"{flow}.hhi.top.{int(row['period'])}",
                    text=_HHI["top"][lang].format(
                        n=int(row["n"]),
                        across=across,
                        flow=fl,
                        period=int(row["period"]),
                        name=row["top_label"],
                        share=fmt_pct(float(row["top_share"]), lang),
                    ),
                )
            )
        sents.append(
            _HHI["sentence"][lang].format(
                p0=p0,
                p1=p1,
                flow=fl,
                across=across,
                v0=fmt_number(v0, 0, lang),
                v1=fmt_number(v1, 0, lang),
                chg=chg_text,
                level=hhi_level(v1, lang),
            )
        )
        if not title:
            title = f"{label}: {fmt_number(v0, 0, lang)} → {fmt_number(v1, 0, lang)} ({p0}–{p1})"
    return facts, sents, title


def _series_shape(
    g: pd.DataFrame, label: str, measure: str, fmt_v: object, lang: str
) -> list[Fact]:
    """What tells a lasting trend from a jump in the last period.

    The period before the last, the largest step, the median level and, for values, how much
    the two largest periods weigh. Seen on real data: Japan's share of imports, 0.7 % (2005) → 4.5 % (2025), written up as "a
    lasting trend" while 2024 was 0.9 % and two months made two thirds of 2025.
    """
    values = g["value"].astype(float).reset_index(drop=True)
    periods = [fmt_period(_py(p), lang) for p in g["period"]]
    if len(values) < 3 or values.isna().any():
        return []
    out = [Fact(key=f"{label}.prev", text=f"{label} {periods[-2]}: {fmt_v(values.iloc[-2], lang)}")]
    low = int(values.idxmin())  # tests "each year", "throughout", "always above …"
    out.append(
        Fact(
            key=f"{label}.low", text=f"{label} low {periods[low]}: {fmt_v(values.iloc[low], lang)}"
        )
    )
    steps = values.diff().abs()
    i = int(steps.iloc[1:].idxmax())
    out.append(
        Fact(
            key=f"{label}.move",
            text=_t(
                "s_move",
                lang,
                label=label,
                pa=periods[i - 1],
                pb=periods[i],
                va=fmt_v(values.iloc[i - 1], lang),
                vb=fmt_v(values.iloc[i], lang),
            ),
        )
    )
    out.append(
        Fact(
            key=f"{label}.median",
            text=_t(
                "s_median",
                lang,
                label=label,
                p0=periods[0],
                p1=periods[-1],
                v=fmt_v(float(values.median()), lang),
            ),
        )
    )
    moves = steps.iloc[1:]
    if len(moves) >= 3 and moves.iloc[-1] >= 2 * moves.iloc[:-1].max():  # as jump_steps
        out.append(
            Fact(
                key=f"{label}.jump",
                text=_t("s_jump", lang, label=label, pa=periods[-2], pb=periods[-1]),
            )
        )
    total = float(values.sum())
    if measure in ("value_eur", "qty_kg") and len(values) >= 6 and total > 0:
        a, b = sorted(values.nlargest(2).index)
        out.append(
            Fact(
                key=f"{label}.top2",
                text=_t(
                    "s_top2",
                    lang,
                    label=label,
                    pa=periods[a],
                    pb=periods[b],
                    pct=fmt_pct(100 * (values[a] + values[b]) / total, lang),
                    p0=periods[0],
                    p1=periods[-1],
                ),
            )
        )
    return out


def _yearly_projection_facts(
    hist: pd.DataFrame, annual: pd.DataFrame | None, flow: str, fl: str, lang: str
) -> list[Fact]:
    """The last full observed year, each projected year (80 % range) and the change between."""
    out = []
    years = pd.to_datetime(hist["period"]).dt.year
    full = [y for y, n in years.value_counts().items() if n == 12]
    if not full:
        return out
    base_year = max(full)
    base = float(hist.loc[years == base_year, "value"].sum())
    out.append(
        Fact(
            key=f"{flow}.total_{base_year}",
            text=_t("y_obs", lang, flow=fl, year=base_year, value=fmt_eur(base, lang)),
        )
    )
    if annual is None or annual.empty:
        return out
    for _, r in annual[annual["flow"] == flow].iterrows():
        year, months = int(r["year"]), int(r["months"])
        if months == 12:
            chg = fmt_pct(100 * (r["value"] / base - 1), lang, signed=True) if base else "–"
            text = _t(
                "y_proj",
                lang,
                flow=fl,
                year=year,
                value=fmt_eur(r["value"], lang),
                lo=fmt_eur(r["lo80"], lang),
                hi=fmt_eur(r["hi80"], lang),
                chg=chg,
                base=base_year,
            )
        else:
            text = _t(
                "y_part",
                lang,
                flow=fl,
                year=year,
                months=months,
                value=fmt_eur(r["value"], lang),
                lo=fmt_eur(r["lo80"], lang),
                hi=fmt_eur(r["hi80"], lang),
            )
        out.append(Fact(key=f"{flow}.projected_{year}", text=text))
    return out


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
    elif spec.measure == "hhi":
        facts, sents, title = _concentration_facts(spec, a, lang)
    elif spec.intent in ("ranking", "composition") and spec.breakdown in SPLIT_BREAKDOWNS:
        facts, sents, title = _split_facts(spec, a, sem, lang)
    elif spec.intent in ("ranking", "composition", "drilldown") and spec.measure == "change":
        facts, sents, title = _change_facts(spec, a, lang)
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
        facts += [Fact(key=f"method{i}", text=m) for i, m in enumerate(a.methods)]  # STL
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
            facts += _yearly_projection_facts(hist, a.extra.get("annual"), str(flow), fl, lang)
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
    # benchmark: the countries compared are reporters, so naming them is grounded
    entities += spec.compare_reporters
    if a is not None and "reporter" in a.main.columns:
        entities += list(a.main["reporter"].astype(str))
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
