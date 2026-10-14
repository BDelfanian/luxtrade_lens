# Solution Design — LuxTrade Lens

**Owner:** Behrooz (solution design) · **Status:** implemented as a skeleton on placeholder data, 14 Oct 2026 (`src/luxtrade/`)
Related: [PROJECT_CONTEXT.md](PROJECT_CONTEXT.md) (WHAT/WHY, requirements) · [DATA_CARD.md](DATA_CARD.md) (data and its limits) · [GUIDELINES.md](GUIDELINES.md) (engineering rules) · [ROADMAP.md](ROADMAP.md) (plan)

> **In one sentence:** a public-sector employee asks a trade question in English, French or German. They get back a **data product** (an interactive chart, table or pivot table) with a **4–5 sentence insight**, a **list of the data limits that apply**, and a **full trace** of how the answer was produced. They can then **ask follow-up questions in the same session**. When a question is too vague, they get **three answerable rewrites** of it.

---

## 1. Users and the job to be done

| | |
|---|---|
| **Persona** | An employee of a Luxembourg public institution: STATEC, a ministry (Economy, Finance, Foreign & European Affairs), the central bank (BCL), or a public agency. They know the economy but not Comext codes, SQL or the HS nomenclature. They work in EN, FR or DE. |
| **Job** | *"I need a reliable answer about Luxembourg's trade in goods, now, in a form I can paste into a note or a meeting, and I need to be able to say where it comes from."* |
| **Today** | Eurostat data browser: pick codes, export tables, build charts by hand. That takes 30 minutes to hours and needs expert knowledge. |
| **With LuxTrade Lens** | Type the question in plain language → the answer arrives in seconds → dig deeper with follow-ups ("and imports?", "only Germany") or filters → copy the run or session ID to cite or recall it later. |

Example questions (the official sample questions Q1–Q6 are a subset; see [PROJECT_CONTEXT §2](PROJECT_CONTEXT.md)):
- *"Who are Luxembourg's main export partners and how has that changed since 2010?"*
  - Follow-up: *"And for imports?"* → same question, flow switched to imports
  - Follow-up: *"Zoom in on the second one by product"* → drill-down on the partner ranked second
- *"Quels produits le Luxembourg importe-t-il de Chine ?"*
- *"Wie entwickeln sich die Exporte von Maschinen (HS 84) und wie geht es weiter?"*
- *"Compare Luxembourg's intra-EU trade share with Belgium and the Netherlands."*
- *"How is our trade doing?"* → **too vague**. The tool offers three specific rewrites (§5.8), e.g. *"How did LU's total exports and imports change in 2025 vs 2024?"*
- *"What share of Luxembourg's GDP is exports?"* → **refused clearly**: GDP is not in the dataset (limit S02). The tool suggests answerable alternatives instead.

## 2. Is this the right data for NL-to-SQL? Yes: structured tabular data (confirmed)

We checked the bulk files on 14 Oct ([DATA_CARD §2](DATA_CARD.md#2-file-structure-bulk-full_yyyymmdat-comma-separated-with-header)):
- Each file is **comma-separated text with a header and a fixed set of 17 columns**. There is no free text, no documents and no images.
- The content is a **fact table**: one row per partner × product × flow × month, holding value and quantities.
- It is described by **code lists**: partners, CN8 products with their hierarchy and other classifications, flows and trade types.
- After processing it becomes a classic **star schema** in Parquet, which DuckDB queries directly.

What this means for the design:
- **NL → structured query → SQL** is the right pattern.
- **RAG over documents is not needed.** The only "knowledge" the assistant needs is the schema, the code-list labels and the limitations registry, and all three are small and structured.
- The hard part isn't the SQL. It is **entity resolution**: turning *"Allemagne"*, *"cars"* or *"Maschinen"* into `DE`, `8703` or `84`. It is solved with label lookups, not with LLM guessing (§5.2).
- The second hard part is **vague or over-broad questions**. They are handled by the question optimiser (§5.8), not by guessing.

## 3. Architecture overview

```
 ┌───────────────────────────── Streamlit UI ──────────────────────────────┐
 │  Sessions & history     │  Conversation thread (EN/FR/DE):              │
 │  (search, run/session   │  question → answer card → follow-up → …      │
 │  ID) · Presets (Q1–Q6)  │  [Optimise question]  suggestion chips        │
 └──────────────┬───────────────────────────────────────────▲──────────────┘
                │ question + session context                │ run record
 ┌──────────────▼──────────────── LangGraph ────────────────┴──────────────┐
 │                         ┌──────────────┐                                │
 │          ┌─────────────▶│  SUPERVISOR  │◀──────────────────┐            │
 │          │              └──┬────────┬──┘                   │            │
 │          │   routes, checks results, retries, resolves conflicts        │
 │   ┌──────┴──────┐  ┌───────▼─────┐  │  ┌─────────────┐  ┌──┴──────────┐ │
 │   │1 Interpret  │─▶│2 Limitation │──┼─▶│3 Query      │─▶│4 Analytics &│ │
 │   │ (LLM) spec +│  │  guard      │  │  │  builder +  │  │  forecast   │ │
 │   │ session ctx │  │  (rules)    │  │  │  SQL guard  │  │  (Python)   │ │
 │   └─────────────┘  └─────────────┘  │  └──────┬──────┘  └──────┬──────┘ │
 │                                     │         │ SQL            │        │
 │   ┌─────────────┐  vague / blocked /│         ▼                │        │
 │   │8 Optimise   │◀─ unresolved /    │   result table ◀─────────┘        │
 │   │ (LLM) 3     │   empty result    │         │                         │
 │   │ validated   │                   │  ┌──────▼──────┐  ┌─────────────┐ │
 │   │ rewrites    │                   └─▶│5 Visualise  │─▶│6 Insight    │ │
 │   └─────────────┘                      │  (rules)    │  │ (LLM) +     │ │
 │                                        └─────────────┘  │ grounding   │ │
 │                                                         └─────────────┘ │
 └──────────────────────────────┬──────────────────────────────────────────┘
                                │ read-only SQL
 ┌──────────────────────────────▼──── Semantic layer (DuckDB views) ────────┐
 │  v_lu_trade · v_lu_trade_hs2 · v_eu_reporters_hs2 · dim_product ·        │
 │  dim_partner · meta_coverage           over data/processed/*.parquet     │
 └──────────────────────────────────────────────────────────────────────────┘
```

**Design principle: LLMs translate, code computes.** LLMs are used at **four points, two of them only when needed**:

| Step | When it runs |
|---|---|
| Interpret: understand the question in its session context (→ a structured `QuerySpec`) | Always |
| Insight: write the paragraph from pre-computed facts | Always |
| Optimise: suggest three answerable rewrites | Only for vague, blocked or failed questions |
| SQL fallback: write SQL for questions the spec can't express | Only then |

Every number is produced by SQL or by tested Python. Routing, chart choice, limitation checks, rewrite validation and forecasting are deterministic rules. This keeps the tool **explainable in one sentence per step** (coach tip 4) and makes hallucinated numbers detectable (§7).

**LLM:** Claude **Sonnet 4.6** (`claude-sonnet-4-6`) for every LLM step, called through the official `anthropic` SDK with structured outputs (Pydantic models) and adaptive thinking. The effort level is set per step (low / medium). The model is configurable through `LUXTRADE_LLM_MODEL`.

### Why LangGraph, and why not more "agents"

| Need | LangGraph gives us |
|---|---|
| Conditional paths: blocked, vague, forecast or not, SQL fallback | Explicit graph edges we can draw on a slide |
| Self-correction: SQL error → retry; failed grounding → rewrite | Bounded loops (max 2 retries per step) |
| Session state for follow-ups | Typed state per run; the session context is rebuilt from stored run records before each run, so no checkpointer is needed (§5.9) |
| Traceability | Typed shared state; every node's input and output is logged into the run record |
| Streaming progress in the UI | Node-by-node events ("Understanding… Querying… Writing insight…") |

**The supervisor is code, not an LLM.** Its routing rules are explicit and unit-tested (§5.1). An LLM supervisor would add latency and non-determinism and make the trace harder to explain to the jury. We use **LangGraph only**, not LangChain chains or agents, so there is one fewer abstraction to debug.

## 4. The `QuerySpec`: one contract between language and data

The interpreter turns any question into this object. The manual filters, the presets, the follow-ups, the optimiser's rewrites and the "Refine" controls all produce **the same object**, so there is one engine (coach tip 1: *who × what × when × flow*).

Implemented in [`agents/spec.py`](../src/luxtrade/agents/spec.py). `None` means "use the default" (§ below):

```python
class QuerySpec(BaseModel):
    language: Literal["en", "fr", "de"] = "en"
    intent: Literal["ranking", "time_series", "composition", "drilldown",
                    "benchmark", "seasonality", "forecast", "single_value", "pivot"]
    breakdown: Literal["partner", "product", "none"] = "none"   # what to rank or split by
    # WHO
    partners: list[str] = []            # ISO-2 codes, resolved via dim_partner
    partner_group: Literal["WORLD", "EU27_2020", "EXTRA_EU27_2020"] = "WORLD"
    compare_reporters: list[str] = []   # benchmark only: other EU reporters
    # WHAT
    products: list[str] = []            # codes at any level, resolved via dim_product
    product_level: Literal["TOTAL", "SECTION", "HS2", "HS4", "HS6", "CN8"] | None = None
    # WHEN
    freq: Literal["M", "A"] | None = None
    period_start: str | None = None     # "YYYY" or "YYYY-MM"
    period_end: str | None = None
    # FLOW, MEASURE, PRESENTATION
    flow: Literal["import", "export", "both", "balance"] | None = None
    measure: Literal["value_eur", "qty_kg", "unit_value", "share", "growth_yoy"] = "value_eur"
    top_n: int | None = None
    seasonal_adjust: bool = False
    forecast_horizon: int | None = None   # months; only when the user asks about the future
    view: Literal["auto", "table", "bar", "line", "area", "map", "treemap", "pivot", "kpi"] = "auto"
    assumptions: list[str] = []         # every default applied, shown to the user


class Interpretation(BaseModel):
    spec: QuerySpec
    followup_of: str | None = None      # run_id of the turn this question builds on (§5.9)
    inherited: list[str] = []           # spec fields carried over from that turn
    view_only: bool = False             # "show it as a table" → re-render, no new insight
    ambiguities: list[Ambiguity] = []   # {dimension: who|what|intent|when|flow|other, text}
    unresolved: list[str] = []          # text that matched no partner or product code
    out_of_scope: list[str] = []        # S01, S02, S03, S04, L10 flagged by the interpreter
    needs_custom_sql: bool = False      # the spec can't express the question → LLM SQL (§5.4)
```

Defaults are applied by [`agents/defaults.py`](../src/luxtrade/agents/defaults.py) after interpretation, for every way of asking.

**Defaults are stated, not hidden.** If the user doesn't say which period or flow they mean, the interpreter fills in a default from a fixed table, for example:
- *ranking or composition* → the last complete year, both flows, HS2, top 10
- *trend* → 2002 → latest complete month, annual

Each default is added to `assumptions`, and the answer card shows them: *"Assumed: exports and imports, year 2025, HS2 chapters."*

**Defaults vs the optimiser:** if only *minor* details are missing (period, flow, level), the tool answers with stated defaults. If the *core* of the question is unclear, it goes to the optimiser (§5.8). The core is WHO, WHAT or the intent itself: an ambiguity there, an unresolved entity, or a question that can't be answered as asked.

## 5. Components

### 5.1 Supervisor (graph router, deterministic)

Runs after every node and decides the next step.

| Situation | Supervisor decision |
|---|---|
| Follow-up with `view_only = true` ("as a table", "as a map") | Skip querying; re-render the previous result with the requested view |
| `ambiguities` touch WHO, WHAT or the intent | **Optimiser** → three rewrites + "ask more specifically" (§5.8); nothing is queried until the user picks |
| `unresolved` entity ("Gaul", "widgets") | Re-run the interpreter once with the top-5 label matches as candidates. Still unresolved → **Optimiser** |
| Guard returns a **blocking** limitation (e.g. GDP, services, pre-2002) | Skip querying. Explain the limitation **and** offer the optimiser's answerable alternatives |
| Guard returns **warning** limitations | Continue; attach them to the state for the answer card |
| SQL fails validation or execution | Send the error back to the query builder (max 2 retries). Still failing → **Optimiser** |
| Result is empty | Check whether the filter is valid but trade is truly zero (→ say so) or whether the filter was wrong (→ **Optimiser**) |
| **Conflict:** result total ≠ reconciled `TOTAL` for that slice | Add an "Undisclosed / confidential" row so the parts sum to the whole; record a note in the trace |
| **Conflict:** forecast requested but series too short or too sparse | Drop the forecast; add limitation L05/S05 with the reason |
| **Conflict:** chart chooser picked a map but most value is in special partners (`QY`, …) | Fall back to a ranked bar chart with an "Undisclosed" bar |
| **Conflict:** a follow-up inherits a field that contradicts the new question (e.g. new partner, old partner group) | The new question wins; the inherited field is dropped and listed in the trace |
| Insight fails the grounding check | Rewrite once with the failing sentence flagged; second failure → deterministic template insight |
| LLM unavailable (no network or API key, timeout, error) | Presets and the Refine controls still work (spec → SQL needs no LLM); the insight falls back to the template; the optimiser is hidden |

### 5.2 Interpreter (LLM, structured output)

- **Input:**
  - the question
  - the **session context** (§5.9)
  - a compact schema description and the defaults table
- **Entity candidates (computed before the call, no tool loop):** [`semantic/lookup.py`](../src/luxtrade/semantic/lookup.py) runs a fuzzy search over `dim_partner` and `dim_product` labels in **EN/FR/DE** (plus codes like *HS 84*, groups like *EU*, and common adjectives like *French*). The top matches with codes go into the prompt. If terms stay unresolved, the supervisor retries once with a wider search.
- **Output:** a validated `Interpretation` object (the spec plus follow-up links, ambiguities and unresolved terms).
- **Rule:** the LLM may only use codes returned by the lookup tool or present in the session context, so it can't invent a code. Language is detected by the same call, and the answer is written in that language.
- Model: `claude-sonnet-4-6` at `effort: low`.

### 5.3 Limitation guard (rules, no LLM)

A machine-readable **limitations registry** (`src/luxtrade/semantic/limitations.yaml`, owned by Kasra) turns [DATA_CARD §4](DATA_CARD.md#4-limitations-and-how-we-handle-them) into rules. Each entry has an ID, a trigger on the `QuerySpec` or the result, a severity (`block` or `warn`) and a message.

| ID | Trigger | Severity |
|---|---|---|
| L01 | Period before 2002 | block (offer 2002 onwards) |
| L02 | Product level HS4 or finer, and confidential share > 1 % in the result | warn, with the % |
| L03 | Special partners (`Q*`) hold > 1 % of the result value | warn, with the % |
| L04 | Period after the latest complete month | warn (extra-EU only) or block (intra-EU or totals) |
| L05 | CN8 or HS6 over a range of more than 3 years | warn (code changes); suggest HS4 or HS2 |
| L06 | Growth or trend over time | warn ("nominal euros, not adjusted for prices") |
| L07 | `measure = unit_value` or `qty_kg` | warn (quantity coverage %) |
| L08 | Intra/extra-EU split across 2020/2021 | warn (fixed EU27 2020 composition; Brexit) |
| L10 | Question about a partner's view of the flow ("what does Germany report…") | block (mirror flows not supported) |
| L11 | A single month or product dominates a change | warn (volatility; spike flagged, not removed) |
| S01 | Services trade | block (goods only) |
| S02 | External variables: GDP, population, prices, employment | block (not in DS-045409) |
| S03 | Other reporters below HS2, or other reporters' partner detail | block (we keep only HS2 summaries for EU reporters) |
| S04 | "Why" questions asking for causes, or firm-level questions | warn: describe the data, don't explain causes; firm data is confidential |
| S05 | Forecast requested | warn (statistical projection, no external drivers) |

The guard runs **twice**: before the query, on the spec (fast blocks), and after it, on the result (shares of confidential or special trade). It also validates every optimiser rewrite (§5.8).

### 5.4 Query builder: spec-first, SQL fallback (NL2SQL)

1. **Spec → SQL compiler (deterministic).** Each `intent` has a parameterised SQL template over the semantic views. This covers all sample questions Q1–Q6 and most variants, and is unit-tested against hand-written SQL.
2. **LLM SQL (fallback)** for questions the spec can't express, e.g. *"months in which imports from China exceeded exports to France"*.
   - **Input:** the question, the view catalogue (columns, types and one-line descriptions) and 5 example question/SQL pairs.
   - Model: `claude-sonnet-4-6` at `effort: medium`.
3. **SQL guard** on *every* query, compiled or generated:

   | Check | Rule |
   |---|---|
   | Parsing | Parsed with `sqlglot`; exactly one `SELECT` statement |
   | Allowed tables | Only the whitelisted semantic views |
   | Forbidden | `COPY`, `ATTACH`, `INSTALL`, `read_*`, `PRAGMA` and file paths |
   | Size and time | Forced `LIMIT` of 10,000 rows; 10-second timeout |
   | Connection | DuckDB opened `read_only`, with `enable_external_access = false` |

The executed SQL is **always shown** in the trace, so a STATEC analyst can copy and re-run it.

**Semantic layer** (DuckDB views over `data/processed/`, owned by Kasra; the final names belong in the data contract, [GUIDELINES §1.3](GUIDELINES.md)):

| View | Grain | Purpose |
|---|---|---|
| `v_lu_trade` | LU × partner × CN8 × flow × month | Full detail, incl. `is_confidential`, `partner_is_special`, `trade_type` |
| `v_lu_trade_hs2` | LU × partner × HS2 × flow × month | Fast path for most questions; long series |
| `v_eu_reporters_hs2` | reporter × trade type × flow × HS2 × month | Benchmarking (Q5) |
| `dim_product` | code × level × year | Parent, labels EN/FR/DE, section, SITC/BEC |
| `dim_partner` | partner | Labels EN/FR/DE, ISO-3, `is_eu27_2020`, `is_special` |
| `meta_coverage` | single row | First period, latest complete month, extraction date, code version |

### 5.5 Analytics and forecast tools (Python, deterministic)

These are pure functions in `analytics/` (Mina), called by the graph on the result table:
- shares, YoY and CAGR
- trade balance
- rank changes
- HHI concentration
- Pareto / Top-N + "Other" + "Confidential"
- STL seasonal adjustment
- simple outlier flags

**Forecasting**, offered *where applicable*. It runs when the user asks about the future, or when they press **"Show projection"** on a time-series answer. It is never added unasked.

| Aspect | Rule |
|---|---|
| Eligible series | Monthly or annual aggregates at TOTAL, section, HS2, or a top partner. **Not CN8** (code changes, sparse data) |
| Minimum history | 60 complete months (5 years); the series stops at the latest complete month (L04) |
| Model | Exponential smoothing (ETS, additive damped trend + monthly seasonality, on log values) via `statsmodels`. Annual series: damped Holt, no seasonality |
| Baseline check | Back-test on the last 12 months against a **seasonal-naive** forecast ("same month last year"). If ETS doesn't beat it, we show seasonal-naive and say so |
| Output | Horizon 12 months by default (max 24), with 80 % and 95 % intervals; back-test error (MAPE) shown in the trace |
| Wording | "Projection if past patterns continue. Not an official forecast. It doesn't include prices, policy or company decisions" (S05) |

In one sentence for the jury: *"We extend the seasonal pattern and the damped trend, check that this beats 'same as last year', and show how uncertain it is."*

### 5.6 Visualisation selector (rules, no LLM)

The result's shape and the intent decide the data product. Every answer also has a **Table** tab with a CSV download.

| Result shape / intent | Default data product | Alternatives offered |
|---|---|---|
| One number | KPI tile with YoY change | Table |
| Time × 1 series | Line chart with range slider | Annual bars |
| Time × ≤ 8 series | Multi-line chart; stacked area if they are parts of a whole | Small multiples |
| Time × > 8 series | Top 7 + "Other", line chart | Table |
| Ranking (category × value) | Sorted horizontal bar chart | Treemap |
| Partner ranking with ≥ 5 countries | **Choropleth map** + ranked bar chart (geospatial requirement) | Table |
| Product hierarchy / drill-down | Treemap or sunburst with Top-N + "Other" + "Confidential", click to drill | Indented table |
| Two categories × value (e.g. partner × year) | **Pivot table** with heat colouring; the user picks rows, columns and measure | Grouped bar chart |
| Seasonality | Month × year heatmap + raw vs seasonally adjusted line | STL panel |
| Forecast | History as a solid line, projection dashed, interval band | Table with intervals |
| Benchmark | Indexed lines (2015 = 100) or bars; EU map | Table |

**Interactivity:**
- **Plotly** charts support zoom, pan, hover values, legend toggles and a range slider.
- A **Refine** bar is generated from the `QuerySpec`: a period slider, a flow toggle, partner/product pickers, a level and a top-N. Changing any of them re-runs the **spec → SQL path without the LLM**. That takes under a second, is deterministic, and is saved as a new turn in the session (`origin: refine`).

Every chart has a **title stating the takeaway** and a source caption (*"Source: Eurostat, Comext DS-045409, extracted YYYY-MM-DD; calculations by The Outliers."*).

### 5.7 Insight writer (LLM) and grounding check

- **Input:**
  - a **fact sheet** computed by code, never the raw table. It holds the key numbers with units and periods, rankings, changes, the forecast summary, and the triggered limitations.
  - for follow-ups, the previous turn's headline facts, so the insight can say *"compared with exports (previous answer)…"*
- **Output:** **4–5 sentences** in the user's language:
  1. A direct answer to the question
  2. The key size or trend
  3. The most notable change or comparison
  4. The seasonal or forecast note, if relevant
  5. The main limitation that applies
- **Rules in the prompt:**
  - Use only facts from the fact sheet.
  - No causal claims. Well-known events from a short curated list (2008–09 crisis, Brexit 2021, COVID-19 2020, energy shock 2022) may be named only as timing context ("coincides with").
  - If something can't be answered, say so plainly.
- **Grounding check (code):**
  - Every number in the paragraph must match a fact-sheet value after locale-aware parsing (`1,2 Mrd €` = `1.2 bn €`), within rounding.
  - Every country and product named must be in the result.
  - On failure: rewrite once, then fall back to a deterministic template.
- Model: `claude-sonnet-4-6` at `effort: low`.

### 5.8 Question optimiser (LLM + validation)

Some questions can't be turned into a good query as written:
- too vague (*"how is trade doing?"*)
- ambiguous (*"trade with Asia"*: which countries? exports or imports?)
- referring to something unknown (*"widgets"*)
- asking for something the data can't give (*"share of GDP"*)

Instead of guessing, the tool **offers three optimised versions of the question** plus a way to ask more specifically.

**When it runs:**

| Trigger | Mode |
|---|---|
| **Automatically**, on supervisor routes to the optimiser (§5.1): core ambiguity, unresolved entity, blocking limitation, SQL failure, wrong-filter empty result | Rewrites shown *instead of* an answer (or next to the limitation message) |
| **On demand:** an **"Optimise question"** button next to the ask box, before submitting | Rewrites shown; the user picks one or submits their own text |
| **On demand:** "Not what you meant?" link on any answer card | Rewrites of the question just answered, keeping the session context |

**How it works:**
1. **Generate (LLM, one call):** input is the question, the session context, the reason it was routed here (ambiguity, unresolved term, blocking limitation ID, or SQL error), the schema summary and the label matches. Output is **three rewrites, each with its `QuerySpec`**, in the user's language.
   - Each rewrite resolves the problem in a different direction, e.g. *exports by partner* / *imports by partner* / *trade balance over time*.
   - Rewrites are concrete and short: they name the partner, product, flow and period.
   - Model: `claude-sonnet-4-6` at `effort: low`.
2. **Validate (code), so that only answerable suggestions are shown.** For each rewrite:
   - the spec parses
   - every code exists in `dim_*`
   - the limitation guard gives no block
   - the spec compiles to SQL that passes `sql_guard` (no execution)

   Invalid rewrites are dropped. If fewer than three survive, the optimiser regenerates once, then shows what it has. **Presets that match the topic fill any remaining slots**, since they are always answerable.
3. **Show** the three rewrites as clickable chips, each with a one-line note on how it differs (*"exports only, 2025"*). Next to them is an **"Ask more specifically"** box, pre-filled with the original question plus a hint naming what's missing (*"Which partner or region? Which period?"*).
4. **Run:** clicking a chip runs **its validated `QuerySpec` directly** (no second interpretation), so the answer matches the suggestion exactly. The run record keeps the original question, all three suggestions and the chosen one (`origin: optimiser`).

In one sentence for the jury: *"When a question can't be answered well as written, we suggest three precise versions that we've checked are answerable, and never guess."*

### 5.9 Sessions and follow-up questions

A **session** is one conversation thread. It holds an ordered list of **turns**, and each turn is a run record. Follow-up questions are interpreted in the context of that thread.

**What context is carried:** structured state, **not the chat transcript**. The interpreter receives, for the last 5 turns:
- the question
- the `QuerySpec`
- the **entities in the result** (e.g. the top-10 partner codes in rank order, the products shown)
- a one-line headline fact

This keeps prompts small and deterministic, and every carried field shows up in the trace.

**How follow-ups are resolved:** the interpreter decides whether the new question builds on a previous turn (`followup_of`) or starts a new topic. For follow-ups it outputs the new spec and lists the `inherited` fields.

| Follow-up | Resolution |
|---|---|
| *"And for imports?"* / *"Et pour les importations ?"* | Previous spec, `flow = import`; inherited: partners, products, period |
| *"Only Germany"* / *"Nur Deutschland"* | Previous spec, `partners = [DE]` |
| *"Zoom in on the second one by product"* | Partner = 2nd entity of the previous result; intent `drilldown` |
| *"Since 2010 instead"* | Previous spec, `period_start = 2010` |
| *"What will it look like next year?"* | Previous spec, intent `forecast`, horizon 12 |
| *"Show it as a table"* / *"as a map"* | `view_only = true`: re-render the previous result, no new query |
| *"Why did it drop in 2020?"* | Previous spec narrowed to 2019–2021 + drill-down by product; limitation S04 (describes, doesn't explain causes) |
| A clearly unrelated question | New topic: `followup_of = null`, nothing inherited |

**Making inheritance visible:** the answer card shows *"Kept from your previous question: partner DE, period 2015–2025"* with a **"Start fresh"** link. That link re-runs the question without context. Wrong context is the main risk of follow-ups, so it is never hidden.

**Storage:**
- Before each run, the session context is rebuilt from the session's stored run records (last 5 turns). The run records are the single source of truth, so a resumed session behaves exactly like a live one.
- On disk, each turn's run record carries `session_id`, `turn`, `followup_of` and `origin` (`ask` · `followup` · `optimiser` · `refine` · `preset`).
- A session file `data/runs/sessions/<session_id>.json` lists its run IDs in order. A session can be **resumed** later from the history panel or with `?session=<id>`, and the context is rebuilt from the stored run records.
- **Scope:** context lives within one session only. There is no memory across sessions and no user profile.

## 6. Traceability: "where does this answer come from?"

Every answer has a **"How we got this"** tab and a **run ID** such as `run 3f9a1c07e2`. The tab shows the full chain:

```
Question (as typed, detected language) + session ID and turn number
 → Context: follow-up of which turn, fields inherited (or "new topic")
 → Interpretation: QuerySpec + stated assumptions + resolved entities ("Allemagne" → DE)
 → Optimiser (if used): reason, the three validated suggestions, the one chosen
 → Limitations checked: which rules fired, with values (e.g. "confidential share 3.8 %")
 → SQL executed (copyable) + view names + rows returned + result hash
 → Methods applied (e.g. STL period 12; ETS parameters + back-test MAPE vs seasonal-naive)
 → Data provenance: source files from data/raw/manifest.json, extraction date, latest complete month
 → Agent trace: node sequence, retries, durations, model and token use per LLM call
 → Code version: git commit
```

### Run records, history and IDs (the "hash")

- Each run is saved as one JSON file, `data/runs/<run_id>.json`, holding all the fields above.
- **`run_id`** = the first 10 hex characters of the SHA-256 of `{session ID, turn, normalised question, QuerySpec, SQL, data vintage, git commit}`. Session and turn are included, so two sessions asking the same thing never overwrite each other's records. `result_hash` is what proves the same query on the same data gives the same result.
- **`result_hash`** = the SHA-256 of the result table (sorted, canonical CSV).
- **`session_id`** = a random short ID created when a session starts. It groups the turns.
- **History panel** (sidebar):
  - Sessions, newest first, each expandable to its turns. Searchable by text, run ID or session ID.
  - Opening a run shows the stored answer instantly. No LLM call is needed, so this also works offline.
  - **Resume session** reloads the thread so the user can keep asking follow-ups.
  - **Re-verify** re-executes the stored SQL and compares the `result_hash` → ✅ *"reproduces exactly"* or ⚠️ *"data has changed since"* (e.g. a new vintage).
  - **Deep links:** `?run=3f9a1c07e2` opens one answer; `?session=k7p2qx` opens the whole thread. Either can be cited in a note or an email.
- **Demo safety:** the pitch sessions are pre-recorded run files committed in `demo/runs/`, so the demo replays even without network access.

## 7. How we avoid hallucination (summary for the jury)

| Risk | Control |
|---|---|
| Invented numbers | Numbers come only from SQL or Python; the insight is grounding-checked against the fact sheet |
| Invented codes or entities | The interpreter can only use codes returned by the label lookup or present in the session context |
| Guessing what a vague question meant | The optimiser offers three validated rewrites instead of guessing |
| Unanswerable suggestions | Every rewrite is checked (codes, limitation guard, SQL compile) before it is shown |
| Wrong follow-up context | Inherited fields shown on the card ("Kept from your previous question…") + "Start fresh"; the new question wins on conflict |
| Wrong SQL | Templates for known intents; a guarded, validated fallback; SQL shown to the user |
| Silent assumptions | All defaults are listed under "Assumed:" on the answer card |
| Questions outside the data | The limitation registry blocks them with an explicit message and answerable alternatives |
| Causal storytelling | Prompt rule + curated event list; S04 warning on "why" questions |
| Over-trusting forecasts | Only eligible series; baseline check; intervals; explicit wording |

## 8. User interface (Streamlit)

```
┌──────────────┬───────────────────────────────────────────────────────────┐
│ LuxTrade Lens│  Session k7p2qx · [New session]                           │
│              │ ┌───────────────────────────────────────────────────────┐ │
│ ▸ Presets    │ │ You: Quels sont nos principaux partenaires à l'export ?│ │
│   Q1 … Q6    │ │ ┌ answer card · run 3f9a1c07e2 ⧉ ──────────────────┐  │ │
│              │ │ │ Assumed: exports, 2025, HS2                       │  │ │
│ ▸ Sessions   │ │ │ Insight (4–5 sentences, in French)                │  │ │
│   🔍 text/ID │ │ │ ⚠ Limits: 3.8 % confidential at HS4 …             │  │ │
│   k7p2qx ▾   │ │ │ [ Chart | Table | Pivot | How we got this ]       │  │ │
│    1 3f9a1c… │ │ │ interactive Plotly chart / map                    │  │ │
│    2 a81d00… │ │ │ Refine: period ▭▭▭ flow ◉exp ○imp level HS2 ▾     │  │ │
│   m3c9ve ▸   │ │ │ [Show projection] [CSV] [Re-verify] Not what you  │  │ │
│              │ │ │                                    meant?         │  │ │
│ ▸ Data status│ │ └───────────────────────────────────────────────────┘  │ │
│   vintage    │ │ You: Et pour les importations ?                        │ │
│   2026-10-14 │ │ ┌ answer card · run a81d00b4c9 ────────────────────┐   │ │
│              │ │ │ Kept from your previous question: 2025, HS2 ·    │   │ │
│              │ │ │ Start fresh                                      │   │ │
│              │ │ └──────────────────────────────────────────────────┘   │ │
│              │ └───────────────────────────────────────────────────────┘ │
│              │  [ Ask a follow-up or a new question…   ] [Optimise] [⏎]  │
│              │  Suggestions: ▸ Exports by partner, 2025  ▸ Imports …  ▸ …│
└──────────────┴───────────────────────────────────────────────────────────┘
```

UX principles applied:
- **One clear entry point**, the ask box at the bottom of the thread (familiar chat pattern), with example chips for users who don't know what to ask.
- **Answer first:** the insight, then the evidence.
- **Continuity:** follow-ups stay in the thread; context carried over is always shown.
- **Help instead of failure:** vague or blocked questions get three validated rewrites, never a dead end.
- **Visible system status:** live step progress while the graph runs, plus data vintage and coverage in the sidebar.
- **Recognition over recall:** presets, suggestion chips and session history.
- **Error prevention:** stated assumptions, clear limitation messages and no stack traces.
- **User control:** Refine controls, "Start fresh", alternative views and a CSV download.
- **Accessibility:** colour-blind-safe palette, takeaway titles, and a data table behind every chart.

The UI chrome is in English. Answers, suggestions and labels follow the question's language (EN/FR/DE, using Eurostat labels).

## 9. Quality and evaluation

- **Golden question set** (`tests/golden/questions.yaml`, written by Kasra with expected answers from hand-written SQL):
  - about 24 single questions, one third each in EN, FR and DE, covering Q1–Q6, variants, and **4 that must be refused**
  - **4 follow-up chains** of 3 turns each, with the expected spec after every turn
  - **6 vague questions** that must go to the optimiser
- **`python -m luxtrade.agents.evaluate`** reports:
  - spec accuracy (single questions and follow-up turns)
  - SQL execution success
  - numeric correctness
  - correct limitation behaviour
  - optimiser routing (vague → optimiser, clear → answer) and the share of suggestions that pass validation

  These results go into the README for the jury: *"we measured it"*.
- **Unit tests** use a fake LLM with recorded responses, so they make no network calls (see [GUIDELINES §5](GUIDELINES.md)).

## 10. Technology choices

| Concern | Choice | Why |
|---|---|---|
| UI | Streamlit (`st.chat_input`, `st.chat_message`, `st.status`) | Already planned; native chat-thread layout; easy to deploy |
| Charts and maps | Plotly | Interactive by default (zoom, hover, legend filtering); choropleth maps |
| Pivot | pandas `pivot_table` + `st.dataframe` with user-selected axes | No extra component; sortable; CSV export |
| Orchestration | LangGraph (MIT) `StateGraph` with conditional edges | Explicit state graph, bounded retries, streaming per node, trace (§3) |
| LLM | **Claude Sonnet 4.6** (`claude-sonnet-4-6`) via the `anthropic` SDK (MIT), adaptive thinking, effort per step; overridable with `LUXTRADE_LLM_MODEL` | Structured outputs map directly to `Interpretation`, rewrites and the fact sheet. Timeouts and errors are handled (§5.1). The key is in `.env` (git-ignored) |
| Query engine | DuckDB over Parquet, read-only | Fast, file-based, no server |
| SQL validation | `sqlglot` (MIT) | Parse, whitelist and rewrite (`LIMIT`) |
| Statistics | `statsmodels` | STL and ETS; widely known and citable |

**Data sent to the LLM:** the question, the session's structured context, the schema, label matches and the computed fact sheet, all of it public Eurostat information. Raw data never leaves the machine. For production use in a public institution, the same design can run on an EU-hosted or on-premises model endpoint (see the next-steps slide).

## 11. Scope guard

| In scope (demo) | Out of scope (stated in the app) |
|---|---|
| Luxembourg as reporter; EU reporters at HS2 for benchmarking | Mirror flows; other reporters at finer detail (S03) |
| Goods, 2002 → latest complete month, monthly and annual | Services (S01); pre-2002 (L01) |
| Questions in EN/FR/DE; follow-ups within a session (last 5 turns of context); question optimiser | Luxembourgish (best effort only); memory across sessions; open-ended chat about topics beyond the data |
| Statistical projections for aggregated series | Causal analysis, scenario modelling, external drivers (S02, S04, S05) |
