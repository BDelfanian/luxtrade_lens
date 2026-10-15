# Text-to-SQL Hardening and Hierarchical Exploration Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Eliminate failure modes in the NL-to-SQL custom fallback path and implement interactive hierarchical visualization (Treemap with Top N + Other grouping) to answer STATEC Hackathon Question Q4.

**Architecture:** 
1. Fix SQL AST guard regex false positives in `sql_guard.py`.
2. Add few-shot DuckDB exemplars and trilingual explanations to `prompts/custom_sql.md`.
3. Inject resolved entity candidates and session context into the `custom_sql` prompt in `graph.py`.
4. Populate `FactSheet.entities` from custom SQL results so `grounding.py` validates partner names correctly.
5. Add self-correction retry in `supervisor.py` when custom SQL returns `no_data` (0 rows).
6. Implement `treemap` visualization in `viz/charts.py`, `viz/selector.py`, and `agents/analyse.py` for hierarchical product drill-downs up to CN8.

**Tech Stack:** Python 3.12, DuckDB, `sqlglot`, `langgraph`, Plotly, Pydantic, pytest.

**Spec:** `docs/SOLUTION_DESIGN.md` (§5.4 Query builder, §5.7 Insight writer), `Statec Hackathon 2026.pdf` (Q1–Q6).

## Global Constraints

- **Python Floor:** Requires Python >= 3.12.
- **SQL Safety:** All SQL must pass `sql_guard.check_sql` and run on read-only DuckDB with `enable_external_access = False`.
- **Trilingual:** System must handle English, French, and German (`en`, `fr`, `de`).
- **Explainability:** LLMs translate and draft insights; numbers come only from SQL or tested Python calculations.
- **Zero Regressions:** All 116 existing tests must continue to pass.

## Review Focus

1. `_FILE_LITERAL` regex allows valid string literals with `/` (e.g. `'kg/m'` or `'and/or'`) while strictly blocking actual file paths/URIs.
2. Custom SQL prompt receives `CANDIDATES:` matching `prompts/custom_sql.md` Rule 3.
3. Grounding check does not falsely flag partners that are present in the custom SQL query output.
4. Custom SQL returning 0 rows triggers a retry with helpful feedback rather than immediately routing to the optimiser.
5. Treemap chart correctly groups small flows into "Other" without breaking parent-child hierarchy.

---

### Task 1: Relax SQL Guard `_FILE_LITERAL` to Prevent String False Positives

**Files:**
- Modify: `src/luxtrade/agents/sql_guard.py`
- Test: `tests/agents/test_sql_guard.py`

**Interfaces:**
- Consumes: `sqlglot`
- Produces: `check_sql(sql: str) -> str`

- [ ] **Step 1: Write the failing test**

In `tests/agents/test_sql_guard.py`, add:
```python
def test_accepts_slashes_in_benign_string_literals():
    sql = "SELECT 'kg/m' AS unit, 'apples and/or oranges' AS desc FROM v_lu_trade"
    checked = check_sql(sql)
    assert "kg/m" in checked
```

- [ ] **Step 2: Run test to verify it fails**

Run: `.venv/bin/pytest tests/agents/test_sql_guard.py::test_accepts_slashes_in_benign_string_literals`
Expected: FAIL with `SQLRejectedError: file paths and URLs are not allowed`

- [ ] **Step 3: Update `_FILE_LITERAL` regex in `src/luxtrade/agents/sql_guard.py`**

Replace blanket `[\\/]` matching with explicit URI scheme or file path with extension:
```python
_FILE_LITERAL = re.compile(
    r"(://|\b[\w\-./]+\.(parquet|csv|json|duckdb|db|txt|xlsx?)\b)",
    re.IGNORECASE,
)
```

- [ ] **Step 4: Run test to verify it passes**

Run: `.venv/bin/pytest tests/agents/test_sql_guard.py`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add src/luxtrade/agents/sql_guard.py tests/agents/test_sql_guard.py
git commit -m "fix(sql_guard): allow benign slashes in string literals while blocking file paths"
```

---

### Task 2: Few-Shot DuckDB Examples & Localized Explanations in `custom_sql.md`

**Files:**
- Modify: `src/luxtrade/agents/prompts/custom_sql.md`
- Test: `tests/agents/test_graph_flows.py`

**Interfaces:**
- Consumes: DuckDB schema from `luxtrade.semantic.catalog`
- Produces: System prompt string with few-shot DuckDB exemplars and instruction to explain in the target language.

- [ ] **Step 1: Write the test verifying prompt content**

In `tests/agents/test_graph_flows.py`, add:
```python
def test_custom_sql_prompt_contains_examples():
    from luxtrade.agents.interpret import prompt
    p = prompt("custom_sql")
    assert "Examples:" in p
    assert "v_lu_trade" in p
    assert "LIMIT 1000" in p
```

- [ ] **Step 2: Run test to verify it fails**

Run: `.venv/bin/pytest tests/agents/test_graph_flows.py::test_custom_sql_prompt_contains_examples`
Expected: FAIL

- [ ] **Step 3: Update `src/luxtrade/agents/prompts/custom_sql.md`**

Update prompt to include few-shot examples (filtering flow, grouping by period, comparing imports vs exports) and request explanation in the language requested in `LANGUAGE:`:
```markdown
You write one DuckDB `SELECT` statement that answers a question about Luxembourg's trade in goods. It is used only when the tool's standard query templates cannot express the question.

Rules:
1. Use only the views in CATALOG. No other tables, no table functions and no file paths.
2. Write exactly one `SELECT`. CTEs (`WITH`) are allowed. Use no other statement types.
3. Product and partner codes are text: `hs2 = '84'`, `partner = 'DE'`. Use only codes listed in CANDIDATES.
4. `period` is a `DATE` (first day of the month). Stop at the LATEST COMPLETE period unless the question asks for later months.
5. Aggregate with `sum(value_eur) AS value_eur`. If the result is a time series, name the time column `period`.
6. Add `LIMIT 1000`.
7. If ERROR is given, your previous SQL failed with that error. Fix it.
8. If CANDIDATES are provided, restrict your filters to those partner and product codes.

Return the SQL and a one-line explanation of what it computes, in the language indicated by LANGUAGE (English by default).

Examples:
- Question: "Months where chemical imports exceeded 100 million EUR"
  SQL:
  SELECT period, sum(value_eur) AS value_eur
  FROM v_lu_trade_hs2
  WHERE flow = 'import' AND section = '06'
  GROUP BY period
  HAVING sum(value_eur) > 100000000
  ORDER BY period
  LIMIT 1000

- Question: "Compare imports from China with exports to Germany in 2024"
  SQL:
  WITH chn AS (
      SELECT period, sum(value_eur) AS import_cn
      FROM v_lu_trade_hs2
      WHERE partner = 'CN' AND flow = 'import' AND year = 2024
      GROUP BY period
  ),
  deu AS (
      SELECT period, sum(value_eur) AS export_de
      FROM v_lu_trade_hs2
      WHERE partner = 'DE' AND flow = 'export' AND year = 2024
      GROUP BY period
  )
  SELECT coalesce(c.period, d.period) AS period,
         coalesce(c.import_cn, 0) AS import_cn,
         coalesce(d.export_de, 0) AS export_de
  FROM chn c
  FULL OUTER JOIN deu d ON c.period = d.period
  ORDER BY period
  LIMIT 1000
```

- [ ] **Step 4: Run test to verify it passes**

Run: `.venv/bin/pytest tests/agents/test_graph_flows.py::test_custom_sql_prompt_contains_examples`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add src/luxtrade/agents/prompts/custom_sql.md tests/agents/test_graph_flows.py
git commit -m "docs(prompts): add few-shot DuckDB exemplars and trilingual explanations to custom_sql prompt"
```

---

### Task 3: Inject Candidates and Session Context into Custom SQL Prompt

**Files:**
- Modify: `src/luxtrade/agents/graph.py`
- Test: `tests/agents/test_graph_flows.py`

**Interfaces:**
- Consumes: `state["question"]`, `state["context"]`, `state["interpretation"]`, `state["spec"]`
- Produces: Complete prompt in `query_node` with `LANGUAGE:`, `CANDIDATES:`, and `SESSION CONTEXT:` (when present).

- [ ] **Step 1: Write the failing test**

In `tests/agents/test_graph_flows.py`, add:
```python
def test_custom_sql_prompt_receives_candidates_and_language(make_assistant, fake_llm):
    llm = fake_llm(
        interpret=interp(intent="time_series", partners=["DE", "FR"], needs_custom_sql=True, language="fr"),
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
```

- [ ] **Step 2: Run test to verify it fails**

Run: `.venv/bin/pytest tests/agents/test_graph_flows.py::test_custom_sql_prompt_receives_candidates_and_language`
Expected: FAIL

- [ ] **Step 3: Update `query_node` in `src/luxtrade/agents/graph.py`**

In `query_node` (around line 200), construct the user prompt including `LANGUAGE:`, `CANDIDATES:`, and `SESSION CONTEXT:`:
```python
candidates: list[str] = []
if spec.partners:
    candidates.extend(f"partner: {p} ({sem.label(p, 'partner', spec.language)})" for p in spec.partners)
if spec.products:
    candidates.extend(f"product: {p} ({sem.label(p, 'product', spec.language)})" for p in spec.products)
candidates_block = ("\n\nCANDIDATES:\n" + "\n".join(candidates)) if candidates else ""

ctx_block = ""
if state.get("context"):
    ctx_turns = [
        f"Turn {turn.turn} ({turn.run_id}): '{turn.question}' -> {turn.spec.flow or 'both'} "
        f"partners={turn.spec.partners} products={turn.spec.products}"
        for turn in state["context"].values()
    ]
    if ctx_turns:
        ctx_block = "\n\nSESSION CONTEXT:\n" + "\n".join(ctx_turns)

user = (
    f"QUESTION: {state['question']}\nLANGUAGE: {spec.language}"
    f"{ctx_block}{candidates_block}\n\n{coverage_text(sem)}"
    f"\n\nCATALOG:\n{catalog_text()}"
)
```

- [ ] **Step 4: Run test to verify it passes**

Run: `.venv/bin/pytest tests/agents/test_graph_flows.py::test_custom_sql_prompt_receives_candidates_and_language`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add src/luxtrade/agents/graph.py tests/agents/test_graph_flows.py
git commit -m "feat(agents): inject candidates, language, and session context into custom SQL prompt"
```

---

### Task 4: Populate Entities from Custom SQL Results to Fix Grounding Check

**Files:**
- Modify: `src/luxtrade/agents/graph.py`
- Test: `tests/agents/test_graph_flows.py`

**Interfaces:**
- Consumes: Custom SQL dataframe `df`
- Produces: `sheet.entities` populated with partner codes present in the dataframe or spec.

- [ ] **Step 1: Write the failing test**

In `tests/agents/test_graph_flows.py`, add:
```python
def test_custom_sql_insight_with_partner_name_passes_grounding(make_assistant, fake_llm):
    import pandas as pd
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
    assert rec.insight_source == "llm"  # must not fall back to template due to partner grounding
```

- [ ] **Step 2: Run test to verify it fails**

Run: `.venv/bin/pytest tests/agents/test_graph_flows.py::test_custom_sql_insight_with_partner_name_passes_grounding`
Expected: FAIL (falls back to template with "partner Germany is not in the result")

- [ ] **Step 3: Update `insight_node` in `src/luxtrade/agents/graph.py`**

In `insight_node` when `state.get("custom_sql")` is true:
Extract partner entities from `spec.partners` and from any column named `'partner'` or `'key'` in `a.main`:
```python
entities = list(spec.partners) + list(spec.products)
if a is not None and not a.main.empty:
    for col in ("partner", "key", "reporter"):
        if col in a.main.columns:
            entities.extend(str(val) for val in a.main[col].dropna().unique())
entities = sorted(set(entities))
```
Pass `entities=entities` to `FactSheet(...)`.

- [ ] **Step 4: Run test to verify it passes**

Run: `.venv/bin/pytest tests/agents/test_graph_flows.py::test_custom_sql_insight_with_partner_name_passes_grounding`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add src/luxtrade/agents/graph.py tests/agents/test_graph_flows.py
git commit -m "fix(agents): populate sheet entities for custom SQL results to satisfy grounding check"
```

---

### Task 5: Enable Self-Correction on Empty Results (`no_data`) for Custom SQL

**Files:**
- Modify: `src/luxtrade/agents/supervisor.py`
- Modify: `src/luxtrade/agents/graph.py`
- Test: `tests/agents/test_graph_flows.py`

**Interfaces:**
- Consumes: `state["status"] == "no_data"`, `state["custom_sql"]`
- Produces: Route back to `"query"` node with feedback message if retries <= MAX_RETRIES.

- [ ] **Step 1: Write the failing test**

In `tests/agents/test_graph_flows.py`, add:
```python
def test_custom_sql_retries_on_empty_result_before_optimising(make_assistant, fake_llm):
    llm = fake_llm(
        interpret=interp(intent="time_series", needs_custom_sql=True),
        custom_sql=[
            CustomSQL(
                sql="SELECT period, sum(value_eur) AS value_eur FROM v_lu_trade_hs2 WHERE year = 1990 GROUP BY period",
                explanation="empty year",
            ),
            CustomSQL(
                sql="SELECT period, sum(value_eur) AS value_eur FROM v_lu_trade_hs2 WHERE year = 2024 GROUP BY period ORDER BY period",
                explanation="valid year",
            ),
        ],
    )
    rec = make_assistant(llm).ask("Trade in an unusual period")
    assert rec.status == "answered"
    query_traces = [t for t in rec.trace if t["node"] == "query"]
    assert len(query_traces) == 2
```

- [ ] **Step 2: Run test to verify it fails**

Run: `.venv/bin/pytest tests/agents/test_graph_flows.py::test_custom_sql_retries_on_empty_result_before_optimising`
Expected: FAIL

- [ ] **Step 3: Update `supervisor.py` and `graph.py`**

In `graph.py` `query_node`:
When `custom` and `df.empty`:
Set `sql_error="Query returned 0 rows. Verify filter conditions (e.g. check date bounds, flow casing 'import'/'export', and partner/product codes)."` and `_outcome="retry"`.

In `supervisor.py` `after_query`:
```python
def after_query(state: dict) -> str:
    if state.get("status") == "error":
        return END
    if state.get("sql_error"):
        if state.get("custom_sql") and _retries(state, "query") <= MAX_RETRIES:
            return "query"
        return "optimise"
    if state.get("status") == "no_data":
        if state.get("custom_sql") and _retries(state, "query") <= MAX_RETRIES:
            return "query"
        return "optimise"
    return "guard_post"
```

- [ ] **Step 4: Run test to verify it passes**

Run: `.venv/bin/pytest tests/agents/test_graph_flows.py::test_custom_sql_retries_on_empty_result_before_optimising`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add src/luxtrade/agents/supervisor.py src/luxtrade/agents/graph.py tests/agents/test_graph_flows.py
git commit -m "feat(supervisor): allow custom SQL self-correction retry on empty result sets"
```

---

### Task 6: Interactive Hierarchical Treemap Visualization for Q4

**Files:**
- Modify: `src/luxtrade/viz/charts.py`
- Modify: `src/luxtrade/viz/selector.py`
- Modify: `src/luxtrade/agents/analyse.py`
- Test: `tests/viz/test_viz.py`

**Interfaces:**
- Consumes: `df` containing hierarchical columns (`chapter`/`hs2`, `product`/`cn8`, `label`, `value`)
- Produces: `render_chart(kind="treemap", ...)` returning a Plotly Figure, and `choose_view` selecting `"treemap"` when drilldown is hierarchical.

- [ ] **Step 1: Write the failing test**

In `tests/viz/test_viz.py`, add:
```python
def test_render_treemap_chart(sample_drilldown_df):
    from luxtrade.viz.charts import render_chart
    fig = render_chart("treemap", sample_drilldown_df, title="Product Hierarchy")
    assert fig is not None
    assert fig.data[0].type == "treemap"
```

- [ ] **Step 2: Run test to verify it fails**

Run: `.venv/bin/pytest tests/viz/test_viz.py::test_render_treemap_chart`
Expected: FAIL

- [ ] **Step 3: Implement `treemap` in `src/luxtrade/viz/charts.py`, `viz/selector.py`, and `agents/analyse.py`**

In `src/luxtrade/viz/charts.py`:
Implement `_treemap(df, title)`:
- Use `px.treemap` or `go.Treemap`.
- Hierarchy paths: if `['section_label', 'hs2_label', 'name']` exist, use them as path; otherwise `['parent', 'name']`.
- Value: `value`.
- Apply brand template and format numbers in euros.

In `src/luxtrade/viz/selector.py`:
Add `"treemap"` to valid view kinds; return `"treemap"` when `spec.intent == "drilldown"` and product level is finer than HS2.

In `src/luxtrade/agents/analyse.py`:
Ensure hierarchical labels (parent labels and child labels) are attached to `Analysis.main` for drilldowns.

- [ ] **Step 4: Run test to verify it passes**

Run: `.venv/bin/pytest tests/viz/test_viz.py`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add src/luxtrade/viz/charts.py src/luxtrade/viz/selector.py src/luxtrade/agents/analyse.py tests/viz/test_viz.py
git commit -m "feat(viz): add interactive Plotly treemap for hierarchical product drill-down (Q4)"
```

---

### Task 7: Full Regression & Integration Verification

**Files:**
- Test: All tests in `tests/`

- [ ] **Step 1: Run full test suite**

Run: `.venv/bin/pytest`
Expected: All tests pass (>= 122 tests).

- [ ] **Step 2: Run Ruff linter and formatter check**

Run: `.venv/bin/ruff check .`
Expected: 0 errors.

- [ ] **Step 3: Final verification commit if needed**
