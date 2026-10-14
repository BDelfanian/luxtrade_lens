"""Question optimiser: three validated, answerable rewrites (SOLUTION_DESIGN §5.8).

The LLM proposes; code decides what is shown: a rewrite survives only if its codes exist, no
limitation blocks it and its SQL compiles and passes the guard. Presets fill empty slots.
"""

import json
import logging

from luxtrade.agents import guard
from luxtrade.agents.compile_sql import SpecError, compile_spec
from luxtrade.agents.context import SessionContext
from luxtrade.agents.defaults import apply_defaults
from luxtrade.agents.interpret import candidates_for, coverage_text, prompt, validate_codes
from luxtrade.agents.llm import LLMError, StructuredLLM
from luxtrade.agents.presets import PRESETS
from luxtrade.agents.spec import OptimiserOutput, Suggestion
from luxtrade.agents.sql_guard import SQLRejectedError, check_sql
from luxtrade.semantic.layer import SemanticLayer
from luxtrade.semantic.lookup import EntityIndex

logger = logging.getLogger(__name__)

_HINT = {
    "en": "Try naming a partner or product, the flow (exports or imports) and a period.",
    "fr": "Précisez un partenaire ou un produit, le flux (exportations ou importations) "
    "et une période.",
    "de": "Nennen Sie einen Partner oder ein Produkt, den Warenstrom (Export oder Import) "
    "und einen Zeitraum.",
}
_PRESET_NOTE = {"en": "sample question", "fr": "question type", "de": "Beispielfrage"}


def validate_suggestion(s: Suggestion, sem: SemanticLayer) -> str | None:
    """Return None if the suggestion is answerable, else why it was dropped."""
    spec, dropped = validate_codes(s.spec, sem, allowed=set())
    if dropped:
        return f"unknown codes {dropped}"
    resolved = apply_defaults(spec, sem.coverage)
    lims = guard.check_question(s.question) + guard.check_spec(resolved, sem.coverage)
    if guard.is_blocked(lims):
        return "blocked by " + ", ".join(lim.id for lim in lims if lim.severity == "block")
    try:
        check_sql(compile_spec(resolved).sql)
    except (SpecError, SQLRejectedError) as exc:
        return f"does not compile: {exc}"
    return None


def _known_codes(sem: SemanticLayer, lang: str) -> str:
    col = {"en": "label_en", "fr": "label_fr", "de": "label_de"}[lang]
    partners = sem.partners[~sem.partners["is_special"]][col].to_dict()
    chapters = sem.products[(sem.products["level"] == 2) & ~sem.products["is_confidential"]][
        col
    ].to_dict()
    return json.dumps({"partners": partners, "hs2_chapters": chapters}, ensure_ascii=False)


def _presets(lang: str, exclude: set[str], k: int) -> list[Suggestion]:
    out = []
    for p in PRESETS:
        question, spec = p.for_language(lang)
        if question not in exclude and len(out) < k:
            out.append(Suggestion(question=question, note=_PRESET_NOTE[lang], spec=spec))
    return out


def optimise(
    question: str,
    reason: str,
    *,
    lang: str,
    llm: StructuredLLM | None,
    sem: SemanticLayer,
    index: EntityIndex,
    context: SessionContext,
) -> tuple[list[Suggestion], str, list[str]]:
    """Return (three validated suggestions, missing-information hint, notes for the trace)."""
    notes: list[str] = []
    valid: list[Suggestion] = []
    hint = _HINT.get(lang, _HINT["en"])
    if llm is not None:
        user = "\n\n".join(
            [
                f"QUESTION: {question}",
                f"REASON: {reason}",
                f"LANGUAGE: {lang}",
                coverage_text(sem),
                "CANDIDATES:\n"
                + json.dumps(
                    [
                        c.model_dump(exclude_none=True)
                        for c in candidates_for(question, index, wide=True)
                    ],
                    ensure_ascii=False,
                ),
                "KNOWN CODES:\n" + _known_codes(sem, lang),
                "SESSION CONTEXT:\n" + context.to_prompt(),
            ]
        )
        for attempt in range(2):
            try:
                out = llm.parse(
                    step="optimise",
                    system=prompt("optimise"),
                    user=user,
                    schema=OptimiserOutput,
                    effort="low",
                )
            except LLMError as exc:
                notes.append(f"optimiser LLM failed: {exc}")
                break
            hint = out.missing_hint or hint
            for s in out.suggestions:
                s = s.model_copy(update={"spec": s.spec.model_copy(update={"language": lang})})
                problem = validate_suggestion(s, sem)
                if problem:
                    notes.append(f"dropped '{s.question}': {problem}")
                elif s.question not in {v.question for v in valid}:
                    valid.append(s)
            if len(valid) >= 3 or attempt == 1:
                break
            user += (
                f"\n\nPREVIOUS ATTEMPT gave only {len(valid)} valid suggestions. "
                f"Notes: {notes[-3:]}"
            )
    if len(valid) < 3:
        filler = _presets(lang, {v.question for v in valid}, 3 - len(valid))
        notes.append(f"{len(filler)} slot(s) filled with presets")
        valid += filler
    return valid[:3], hint, notes
