"""Insight writer: 4–5 grounded sentences from the fact sheet (SOLUTION_DESIGN §5.7)."""

from luxtrade.agents import grounding
from luxtrade.agents.facts import FactSheet
from luxtrade.agents.interpret import prompt
from luxtrade.agents.llm import LLMError, StructuredLLM
from luxtrade.agents.spec import InsightOutput
from luxtrade.semantic.layer import SemanticLayer


def write_insight(
    sheet: FactSheet,
    *,
    llm: StructuredLLM | None,
    sem: SemanticLayer,
) -> tuple[list[str], str, list[str]]:
    """Return (sentences, source 'llm' or 'template', notes); template after 2 failed drafts."""
    if llm is None:
        return sheet.template, "template", ["no LLM configured: template insight"]
    payload = sheet.model_dump_json(exclude={"template", "title"}, indent=1)
    notes: list[str] = []
    problems: list[str] = []
    for _ in range(2):
        user = f"language: {sheet.language}\n\nFACT SHEET:\n{payload}"
        if problems:
            user += "\n\nPROBLEMS in the previous draft:\n- " + "\n- ".join(problems)
        try:
            out = llm.parse(
                step="insight",
                system=prompt("insight"),
                user=user,
                schema=InsightOutput,
                effort="low",
            )
        except LLMError as exc:
            notes.append(f"insight LLM failed: {exc}")
            break
        problems = grounding.check(out.sentences, sheet, sem)
        if not problems:
            return out.sentences, "llm", notes
        notes.append("grounding failed: " + "; ".join(problems))
    return sheet.template, "template", notes + ["fell back to the template insight"]
