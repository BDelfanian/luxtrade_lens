"""Contracts between language and data: QuerySpec, interpreter/optimiser/insight outputs, trace.

Every way of asking (question, follow-up, optimiser rewrite, preset, Refine) produces a
``QuerySpec`` (SOLUTION_DESIGN §4). LLM outputs are validated against these models.
"""

from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

Language = Literal["en", "fr", "de"]
Intent = Literal[
    "ranking",
    "time_series",
    "composition",
    "drilldown",
    "benchmark",
    "seasonality",
    "forecast",
    "single_value",
    "pivot",
]
Breakdown = Literal["partner", "product", "partner_group", "confidentiality", "none"]
Level = Literal["TOTAL", "SECTION", "HS2", "HS4", "HS6", "CN8"]
Flow = Literal["import", "export", "both", "balance"]
# change: end of period minus start of period, per key (rankings of rises and falls)
# hhi: concentration of a flow across the breakdown's items (Herfindahl-Hirschman, 0-10,000)
# two_way: how much of trade goes both ways in the same product code (Grubel-Lloyd, 0-100)
Measure = Literal[
    "value_eur", "qty_kg", "unit_value", "share", "growth_yoy", "change", "hhi", "two_way"
]
View = Literal[
    "auto", "table", "bar", "line", "area", "stacked", "heatmap", "map", "treemap", "pivot", "kpi"
]
PartnerGroup = Literal["WORLD", "EU27_2020", "EXTRA_EU27_2020"]
ScopeId = Literal["S01", "S02", "S03", "S04", "L10"]
Origin = Literal["ask", "followup", "optimiser", "refine", "preset", "projection"]

LEVEL_DIGITS = {"TOTAL": 0, "HS2": 2, "HS4": 4, "HS6": 6, "CN8": 8}
SNAPSHOT_INTENTS = {"ranking", "composition", "drilldown", "single_value"}
SERIES_INTENTS = {"time_series", "seasonality", "forecast"}
RANKED_INTENTS = {"ranking", "composition", "drilldown"}
# Two-way splits of a total: EU27 vs non-EU27 partners, confidential vs published CN8 detail
SPLIT_BREAKDOWNS = {"partner_group", "confidentiality"}
MAX_SERIES = 8  # categorical palette size; more series fold into "Other"


class QuerySpec(BaseModel):
    """WHO × WHAT × WHEN × FLOW, plus how to present it. ``None`` means "use the default"."""

    model_config = ConfigDict(extra="forbid")

    language: Language = "en"
    intent: Intent
    breakdown: Breakdown = Field("none", description="what to rank or split by")
    partners: list[str] = Field(default_factory=list, description="ISO-2 partner codes")
    partner_group: PartnerGroup = "WORLD"
    compare_reporters: list[str] = Field(default_factory=list, description="benchmark only")
    products: list[str] = Field(default_factory=list, description="product codes, any level")
    product_level: Level | None = None
    freq: Literal["M", "A"] | None = None
    year_step: int | None = Field(
        None, description="yearly series only: every n-th year from period_start (5: 2005, 2010…)"
    )
    period_start: str | None = Field(None, description="'YYYY' or 'YYYY-MM'")
    period_end: str | None = Field(None, description="'YYYY' or 'YYYY-MM'")
    flow: Flow | None = None
    measure: Measure = "value_eur"
    top_n: int | None = None
    seasonal_adjust: bool = False
    forecast_horizon: int | None = Field(
        None, description="months; only when asked about the future"
    )
    view: View = "auto"
    assumptions: list[str] = Field(default_factory=list)


class Ambiguity(BaseModel):
    """Something the question leaves open."""

    dimension: Literal["who", "what", "intent", "when", "flow", "other"]
    text: str


class Interpretation(BaseModel):
    """Interpreter output: the spec plus follow-up links and what is unclear."""

    spec: QuerySpec
    followup_of: str | None = Field(None, description="run_id of the turn this builds on")
    inherited: list[str] = Field(default_factory=list, description="spec fields carried over")
    view_only: bool = Field(False, description="only re-render the previous result")
    ambiguities: list[Ambiguity] = Field(default_factory=list)
    unresolved: list[str] = Field(default_factory=list, description="terms matching no code")
    out_of_scope: list[ScopeId] = Field(default_factory=list)
    needs_custom_sql: bool = False


class Suggestion(BaseModel):
    """One optimised, answerable version of the question."""

    question: str
    note: str = Field(description="one line on how it differs from the original")
    spec: QuerySpec


class OptimiserOutput(BaseModel):
    """Optimiser output: three rewrites plus a hint for asking more specifically."""

    suggestions: list[Suggestion]
    missing_hint: str


class InsightOutput(BaseModel):
    """Insight writer output: 4–5 sentences."""

    sentences: list[str]


class CustomSQL(BaseModel):
    """Fallback SQL written by the LLM for questions the spec can't express."""

    sql: str
    explanation: str


class Limitation(BaseModel):
    """A limitation that applies to this answer (from the registry)."""

    id: str
    key: str
    severity: Literal["block", "warn"]
    message: str
    value: float | None = None


class TraceEvent(BaseModel):
    """One step of the agent trace."""

    node: str
    ms: int
    outcome: Literal["ok", "retry", "fallback", "blocked", "routed", "error", "skipped"] = "ok"
    detail: str = ""
