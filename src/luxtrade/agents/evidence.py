"""Evidence for a scenario's answer: key figures and charts built by code from its steps.

The combined answer of a scenario is words. This module gives it what an Overview card has: a
chart and a few key figures. No LLM is involved:

- Steps that ask the same thing for different periods form a group: the same ranking of changes
  for several pairs of years (three crises), or the same shares in two years (2005 and 2025).
- The item shown is the one the answer talks about (its label in the headline and points), or
  else the one that falls most often; it is compared with the whole flow ("All exports").
- Every value comes from re-running each step's own stored, guarded SQL, so items outside a
  step's top 10 and the whole flow are exact too.
"""

import re
from typing import Literal

import pandas as pd
from pydantic import BaseModel, Field

from luxtrade.runs.store import RunRecord
from luxtrade.semantic.layer import QueryError, SemanticLayer
from luxtrade.viz.format import flow_label, fmt_pct

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

    kind: Literal["change", "share"]
    title: str
    flow: str
    steps: list[int]
    rows: list[dict] = Field(default_factory=list)  # {"group", "series", "value", "step"}
    tiles: list[dict] = Field(default_factory=list)  # {"value", "label", "detail", "tone"}
    note: str = ""


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
    groups: dict[tuple, list[int]] = {}
    for step in chain:
        rec = records.get(step.n)
        shape = _shape(rec) if rec is not None else None
        if shape is not None:
            groups.setdefault(shape, []).append(step.n)
    figures = []
    ordered = sorted((g for g in groups.items() if len(g[1]) >= 2), key=lambda g: -len(g[1]))
    for shape, steps in ordered[:MAX_FIGURES]:
        steps = sorted(steps, key=lambda n: records[n].spec.get("period_start", ""))
        try:
            fig = _figure(shape, steps, records, headline, text, sem, lang)
        except (QueryError, KeyError, ValueError):
            continue
        if fig is not None:
            figures.append(fig)
    return figures


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
    fl = flow_label(flow, lang)
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
