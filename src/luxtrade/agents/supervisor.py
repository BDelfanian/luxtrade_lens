"""Supervisor: deterministic routing between graph nodes (SOLUTION_DESIGN §5.1).

Pure functions over the run state, so every routing rule has a unit test. No LLM decides the path.
"""

from luxtrade.agents.guard import is_blocked
from luxtrade.config import MAX_RETRIES

END = "__end__"
CORE_DIMENSIONS = {"who", "what", "intent"}


def _retries(state: dict, node: str) -> int:
    return state.get("retries", {}).get(node, 0)


def entry(state: dict) -> str:
    """Route a given spec to the guard, on-demand optimising to the optimiser, else interpret."""
    if state.get("spec") is not None:
        return "guard_pre"
    if state.get("force_optimise"):
        return "optimise"
    return "interpret"


def core_ambiguities(state: dict) -> list[str]:
    """Ambiguities about WHO, WHAT or the intent (minor gaps are filled by defaults)."""
    interp = state.get("interpretation")
    if interp is None:
        return []
    return [a.text for a in interp.ambiguities if a.dimension in CORE_DIMENSIONS]


def after_interpret(state: dict) -> str:
    """Retry once with a wider lookup for unresolved terms; vague questions go to the optimiser."""
    if state.get("status") == "error":
        return END
    interp = state["interpretation"]
    if interp.unresolved and _retries(state, "interpret") < 2:
        return "interpret"
    if interp.unresolved or core_ambiguities(state):
        return "optimise"
    return "guard_pre"


def after_guard_pre(state: dict) -> str:
    """Blocked questions are explained and get answerable alternatives instead of a query."""
    if state.get("status") == "error":
        return END
    return "optimise" if is_blocked(state.get("limitations", [])) else "query"


def after_query(state: dict) -> str:
    """Retry LLM-written SQL on errors; failures and empty results go to the optimiser."""
    if state.get("status") == "error":
        return END
    if state.get("sql_error"):
        if state.get("custom_sql") and _retries(state, "query") <= MAX_RETRIES:
            return "query"
        return "optimise"
    if state.get("status") == "no_data":
        return "optimise"
    return "guard_post"


def optimiser_reason(state: dict) -> str:
    """Why the optimiser was called, in words the optimiser prompt (and the trace) can use."""
    lims = state.get("limitations", [])
    if is_blocked(lims):
        return "blocked by data limits: " + " ".join(
            f"[{lim.id}] {lim.message}" for lim in lims if lim.severity == "block"
        )
    interp = state.get("interpretation")
    if interp is not None and interp.unresolved:
        return "terms not found in the data: " + ", ".join(interp.unresolved)
    if core_ambiguities(state):
        return "the question is unclear: " + "; ".join(core_ambiguities(state))
    if state.get("sql_error"):
        return f"the query could not be run: {state['sql_error']}"
    if state.get("status") == "no_data":
        return "the selection returned no trade"
    if state.get("force_optimise"):
        return "the user asked for more precise versions of the question before running it"
    return "the question could not be answered as written"
