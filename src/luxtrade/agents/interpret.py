"""Interpreter: question + session context → validated ``Interpretation`` (SOLUTION_DESIGN §5.2)."""

import json
import re
from functools import cache
from pathlib import Path

from luxtrade.agents.context import SessionContext
from luxtrade.agents.llm import StructuredLLM
from luxtrade.agents.spec import Interpretation, QuerySpec
from luxtrade.semantic.layer import SemanticLayer
from luxtrade.semantic.lookup import Candidate, EntityIndex

PROMPTS = Path(__file__).parent / "prompts"


@cache
def prompt(name: str) -> str:
    """Load a versioned prompt from agents/prompts/."""
    return (PROMPTS / f"{name}.md").read_text(encoding="utf-8")


def coverage_text(sem: SemanticLayer) -> str:
    """The period facts the LLM needs to resolve 'last year' and defaults."""
    cov = sem.coverage
    return (
        f"LATEST COMPLETE PERIOD: {cov.latest_complete_period:%Y-%m} "
        f"(latest complete year {cov.latest_complete_year}); data from {cov.first_period:%Y-%m}; "
        f"months up to {cov.latest_period:%Y-%m} contain extra-EU trade only."
    )


def candidates_for(
    question: str, index: EntityIndex, wide: bool = False, extra_terms: list[str] = ()
) -> list[Candidate]:
    """Entity candidates for the question (wider search on the retry for unresolved terms)."""
    found = index.find(question, threshold=0.75 if wide else 0.84)
    for term in extra_terms:
        found += index.find(term, threshold=0.7, limit=5)
    unique = {(c.kind, c.code): c for c in sorted(found, key=lambda c: c.score)}
    return sorted(unique.values(), key=lambda c: -c.score)


def validate_codes(
    spec: QuerySpec, sem: SemanticLayer, allowed: set[str]
) -> tuple[QuerySpec, list[str]]:
    """Drop codes that don't exist or weren't offered; return the clean spec and dropped codes."""
    dropped = []
    partners = []
    for code in spec.partners:
        code = code.upper()
        (
            partners
            if sem.has_code(code, "partner") and (code in allowed or not allowed)
            else dropped
        ).append(code)
    products = []
    for code in spec.products:
        (products if sem.has_code(code, "product") else dropped).append(code)
    reporters = [r for r in spec.compare_reporters if sem.has_code(r.upper(), "reporter")]
    dropped += [r for r in spec.compare_reporters if r not in reporters]
    clean = spec.model_copy(
        update={
            "partners": partners,
            "products": products,
            "compare_reporters": [r.upper() for r in reporters],
        }
    )
    return clean, dropped


def interpret(
    question: str,
    *,
    llm: StructuredLLM,
    sem: SemanticLayer,
    index: EntityIndex,
    context: SessionContext,
    wide: bool = False,
    extra_terms: list[str] = (),
) -> Interpretation:
    """Ask the LLM for an Interpretation, then enforce the code and follow-up rules in code."""
    cands = candidates_for(question, index, wide=wide, extra_terms=extra_terms)
    user = "\n\n".join(
        [
            f"QUESTION: {question}",
            coverage_text(sem),
            "CANDIDATES (the only codes you may use, besides SESSION CONTEXT):\n"
            + json.dumps([c.model_dump(exclude_none=True) for c in cands], ensure_ascii=False),
            f"BENCHMARK REPORTERS: {', '.join(sem.reporters)}",
            "SESSION CONTEXT:\n" + context.to_prompt(),
        ]
    )
    interp = llm.parse(
        step="interpret", system=prompt("interpret"), user=user, schema=Interpretation, effort="low"
    )

    allowed = {c.code for c in cands if c.kind == "partner"} | context.codes()
    spec, dropped = validate_codes(interp.spec, sem, allowed)
    if spec.partner_group not in ("WORLD", "EU27_2020", "EXTRA_EU27_2020"):
        spec = spec.model_copy(update={"partner_group": "WORLD"})
    followup = interp.followup_of if context.get(interp.followup_of) else None
    detected = followup is None and bool(context.turns) and is_elliptical(question)
    if detected:
        followup = context.turns[-1].run_id  # "only from Belgium": the LLM missed the follow-up
    inherited = interp.inherited if followup else []
    view_only = interp.view_only and followup is not None
    prev = context.get(followup)
    if prev and prev.spec and not view_only:
        spec, inherited = merge_followup(spec, prev.spec, inherited, fill_codes=detected)
    return interp.model_copy(
        update={
            "spec": spec,
            "followup_of": followup,
            "inherited": inherited,
            "view_only": view_only,
            "unresolved": list(dict.fromkeys(interp.unresolved + dropped)),
        }
    )


_ELLIPTICAL_RE = re.compile(
    r"^\s*(and|but|only|just|now|also|same|instead|what about|how about|"
    r"et|mais|seulement|uniquement|juste|maintenant|pareil|qu'en est-il|"
    r"und|aber|nur|jetzt|auch|dasselbe|was ist mit|wie steht es mit)\b",
    re.IGNORECASE,
)
_ELLIPTICAL_MAX_WORDS = 7
# Spec fields a follow-up takes from the previous turn when the new question leaves them open
_OPEN_FIELDS = ("flow", "freq", "product_level", "top_n")
_CODE_FIELDS = ("partners", "products")


def is_elliptical(question: str) -> bool:
    """True for short questions that only make sense after an earlier turn ("only Germany")."""
    return len(question.split()) <= _ELLIPTICAL_MAX_WORDS and bool(_ELLIPTICAL_RE.match(question))


def merge_followup(
    spec: QuerySpec, prev: QuerySpec, inherited: list[str], fill_codes: bool = False
) -> tuple[QuerySpec, list[str]]:
    """Complete a follow-up spec from the previous turn's spec; return it and the inherited fields.

    Inherited code filters are copied from the previous *spec*, never from its result (the LLM
    tends to copy the ranked result codes, which silently restricts the new query). Fields the
    new question leaves open take the previous turn's value; empty code filters too when
    ``fill_codes`` (follow-up detected in code: the LLM produced a stand-alone spec).
    """
    inherited = list(inherited)
    update = {f: list(getattr(prev, f)) for f in _CODE_FIELDS if f in inherited}
    for f in _CODE_FIELDS if fill_codes else ():
        if f not in inherited and not getattr(spec, f) and getattr(prev, f):
            update[f] = list(getattr(prev, f))
            inherited.append(f)
    for f in _OPEN_FIELDS:
        if getattr(spec, f) is None and getattr(prev, f) is not None:
            update[f] = getattr(prev, f)
            inherited.append(f)
    if spec.period_start is None and spec.period_end is None and prev.period_start is not None:
        update |= {"period_start": prev.period_start, "period_end": prev.period_end}
        inherited += ["period_start", "period_end"]
    return spec.model_copy(update=update), list(dict.fromkeys(inherited))
