"""Interpreter: question + session context → validated ``Interpretation`` (SOLUTION_DESIGN §5.2)."""

import json
import re
from functools import cache
from pathlib import Path

from luxtrade.agents.context import SessionContext, TurnContext
from luxtrade.agents.llm import StructuredLLM
from luxtrade.agents.spec import RANKED_INTENTS, Interpretation, QuerySpec
from luxtrade.config import REPORTER
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
    spec = unasked_split(question, yearly_series(question, spec))
    followup = interp.followup_of if context.get(interp.followup_of) else None
    detected = followup is None and bool(context.turns) and is_elliptical(question)
    if detected:
        followup = context.turns[-1].run_id  # "only from Belgium": the LLM missed the follow-up
    inherited = interp.inherited if followup else []
    last = context.turns[-1] if context.turns else None
    chosen = context.get(followup)
    if (
        chosen is not None
        and last is not None
        and chosen.run_id != last.run_id
        and is_elliptical(question)
        and chosen.spec is not None
        and last.spec is not None
    ):
        # "and in 2025?" builds on the latest turn, but the LLM picked an older one (seen on
        # real data): apply the change it made to that turn to the latest turn instead
        spec, inherited = rebase_followup(spec, chosen.spec, last.spec)
        followup = last.run_id
    view_only = interp.view_only and followup is not None
    prev = context.get(followup)
    asked = {c.code for c in cands}
    for turn in context.turns:  # follow-up or not: a ranking never filters on earlier results
        spec = drop_result_codes(spec, turn, asked)
    if prev and prev.spec and not view_only:
        spec, inherited = merge_followup(spec, prev.spec, inherited, fill_codes=detected)
    return interp.model_copy(
        update={
            "spec": spec,
            "followup_of": followup,
            "inherited": inherited,
            "view_only": view_only,
            # a partner group ("non-EU") is a spec field, not a code to look up; Luxembourg is
            # the reporter of every question, not a partner (seen on real data: "LU" put in
            # partners, dropped as a code, then reported as "not found in the data")
            "unresolved": [
                u
                for u in dict.fromkeys(interp.unresolved + dropped)
                if u not in _GROUP_CODES and u.strip().lower() not in _REPORTER_NAMES
            ],
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
_GROUP_CODES = {"WORLD", "EU27_2020", "EXTRA_EU27_2020"}
_REPORTER_NAMES = {REPORTER.lower(), "luxembourg", "luxemburg", "lëtzebuerg", "grand duchy"}
_OPEN_FIELDS = ("flow", "freq", "product_level", "top_n")
_CODE_FIELDS = ("partners", "products")


_YEARLY_RE = re.compile(
    r"\b(?:each|every|per)\s+year\b|\byearly\b|\bannually\b|\byear\s+by\s+year\b|"
    r"\bchaque\s+année\b|\bpar\s+an\b|\bannée\s+par\s+année\b|"
    r"\bjedes\s+jahr\b|\bpro\s+jahr\b|\bjährlich\b|\bjahr\s+für\s+jahr\b",
    re.IGNORECASE,
)


def yearly_series(question: str, spec: QuerySpec) -> QuerySpec:
    """A snapshot over several years, asked "each year", read as a yearly series.

    Seen on real data: "What share of imports came from EU27 countries each year from 2005 to
    2025?" read as one composition of 2005–2025 added up (which the scenario check blocks).
    """
    if spec.intent not in ("ranking", "composition", "single_value") or spec.measure == "change":
        return spec
    start, end = (spec.period_start or "")[:4], (spec.period_end or "")[:4]
    if not start or not end or start == end or not _YEARLY_RE.search(question):
        return spec
    return spec.model_copy(
        update={
            "intent": "time_series",
            "freq": "A",
            "assumptions": [*spec.assumptions, "a yearly series: the question asks for each year"],
        }
    )


_EU_RE = re.compile(
    r"\b(?:eu|eu27|ue|ue27|e\.u\.|europ\w*|intra\W?\w*|extra\W?\w*|union\w*|binnen\w*)\b",
    re.IGNORECASE,
)


def unasked_split(question: str, spec: QuerySpec) -> QuerySpec:
    """An EU27 vs non-EU27 split the question never asked for, taken out.

    Seen on real data: "What share of imports were computers (HS 8471) each year?" read as
    computers split by EU27 and non-EU27 partners (after a prompt example about the EU27 share).
    """
    if spec.breakdown != "partner_group" or _EU_RE.search(question):
        return spec
    return spec.model_copy(
        update={
            "breakdown": "product" if spec.products else "none",
            "assumptions": [*spec.assumptions, "no EU27 split: the question does not ask for one"],
        }
    )


def is_elliptical(question: str) -> bool:
    """True for short questions that only make sense after an earlier turn ("only Germany")."""
    return len(question.split()) <= _ELLIPTICAL_MAX_WORDS and bool(_ELLIPTICAL_RE.match(question))


_REBASE_SKIP = {"language", "assumptions", "view"}


def rebase_followup(
    spec: QuerySpec, chosen: QuerySpec, last: QuerySpec
) -> tuple[QuerySpec, list[str]]:
    """The latest turn's spec with what the follow-up changed relative to the turn it picked."""
    fields = [f for f in QuerySpec.model_fields if f not in _REBASE_SKIP]
    changed = {f: getattr(spec, f) for f in fields if getattr(spec, f) != getattr(chosen, f)}
    rebased = last.model_copy(update={**changed, "language": spec.language, "view": spec.view})
    return rebased, [f for f in fields if f not in changed]


def drop_result_codes(spec: QuerySpec, prev: TurnContext, asked: set[str]) -> QuerySpec:
    """Remove codes a ranking follow-up copied from the previous turn's *result*.

    "And in 2025?" after a top-10 ranking must rank everything again: filtering on the ten
    earlier items makes the shares relative to them (seen on real data). Codes named in the
    question or already in the previous spec's filter stay; series ("how did these develop?")
    keep them.
    """
    if spec.intent not in RANKED_INTENTS or prev.spec is None:
        return spec
    update = {}
    for field in ("partners", "products"):
        codes, kept = getattr(spec, field), set(getattr(prev.spec, field))
        copied = [c for c in codes if c in set(prev.entities.get(field, [])) - kept - asked]
        if copied:
            update[field] = [c for c in codes if c not in copied]
    return spec.model_copy(update=update) if update else spec


def merge_followup(
    spec: QuerySpec, prev: QuerySpec, inherited: list[str], fill_codes: bool = False
) -> tuple[QuerySpec, list[str]]:
    """Complete a follow-up spec from the previous turn's spec; return it and the inherited fields.

    Inherited code filters are copied from the previous *spec*, never from its result (the LLM
    tends to copy the ranked result codes, which silently restricts the new query). Fields the
    new question leaves open take the previous turn's value; empty code filters too when
    ``fill_codes`` (follow-up detected in code: the LLM produced a stand-alone spec). An open
    field the LLM declares inherited takes the previous value even if the LLM wrote another one
    ("and between 2019 and 2020?" after an HS2 ranking came back with ``TOTAL``, seen on real data).
    """
    inherited = list(inherited)
    update = {f: list(getattr(prev, f)) for f in _CODE_FIELDS if f in inherited}
    for f in _CODE_FIELDS if fill_codes else ():
        if f not in inherited and not getattr(spec, f) and getattr(prev, f):
            update[f] = list(getattr(prev, f))
            inherited.append(f)
    for f in _OPEN_FIELDS:
        declared = f in inherited and getattr(prev, f) is not None
        if declared or (getattr(spec, f) is None and getattr(prev, f) is not None):
            update[f] = getattr(prev, f)
            inherited.append(f)
    if spec.period_start is None and spec.period_end is None and prev.period_start is not None:
        update |= {"period_start": prev.period_start, "period_end": prev.period_end}
        inherited += ["period_start", "period_end"]
    return spec.model_copy(update=update), list(dict.fromkeys(inherited))
