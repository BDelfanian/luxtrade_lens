"""Session context for follow-up questions (SOLUTION_DESIGN §5.9).

Structured state only: for the last turns, the question, the resolved spec, the entities in the
result and a headline. Never the chat transcript.
"""

import json

from pydantic import BaseModel, Field

from luxtrade.agents.spec import QuerySpec
from luxtrade.config import SESSION_CONTEXT_TURNS


class TurnContext(BaseModel):
    """What a follow-up may refer to from one earlier turn."""

    run_id: str
    turn: int
    question: str
    spec: QuerySpec | None = None
    entities: dict[str, list[str]] = Field(default_factory=dict)
    headline: str = ""


class SessionContext(BaseModel):
    """The recent turns of one session, oldest first."""

    session_id: str
    turns: list[TurnContext] = Field(default_factory=list)

    def get(self, run_id: str | None) -> TurnContext | None:
        """The turn with this run_id, if it is in context."""
        return next((t for t in self.turns if t.run_id == run_id), None)

    def codes(self) -> set[str]:
        """Every partner and product code mentioned in the context (allowed for the interpreter)."""
        found: set[str] = set()
        for t in self.turns:
            for codes in t.entities.values():
                found.update(codes)
            if t.spec:
                found.update(t.spec.partners + t.spec.products + t.spec.compare_reporters)
        return found

    def to_prompt(self) -> str:
        """Compact JSON for the interpreter and optimiser prompts."""
        if not self.turns:
            return "[] (no earlier turns: this is a new topic)"
        rows = [
            {
                "run_id": t.run_id,
                "turn": t.turn,
                "question": t.question,
                "spec": t.spec.model_dump(exclude={"assumptions"}, exclude_defaults=True)
                if t.spec
                else None,
                "entities": t.entities,
                "headline": t.headline,
            }
            for t in self.turns
        ]
        return json.dumps(rows, ensure_ascii=False, indent=1, default=str)


def build_context(session_id: str, records: list) -> SessionContext:
    """Context from a session's run records (``runs.store.RunRecord``), newest turns kept."""
    turns = []
    for rec in records[-SESSION_CONTEXT_TURNS:]:
        spec = QuerySpec.model_validate(rec.spec) if rec.spec else None
        turns.append(
            TurnContext(
                run_id=rec.run_id,
                turn=rec.turn,
                question=rec.question,
                spec=spec,
                entities=rec.entities,
                headline=rec.title,
            )
        )
    return SessionContext(session_id=session_id, turns=turns)
