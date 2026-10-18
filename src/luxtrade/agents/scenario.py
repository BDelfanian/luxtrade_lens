"""Scenario builder: answer a broad question with a chain of checked assistant runs.

One query rarely settles a concern such as "Has Luxembourg spread its risk, across the goods it
sells and the countries it buys from?". The builder (SOLUTION_DESIGN §5.10):

1. **Plans** (LLM): 3–5 self-contained questions, each with its purpose and ``QuerySpec``. Code
   keeps only the questions the optimiser's checks pass (codes exist, no limitation blocks
   them, the SQL compiles and passes the guard). The user can edit, drop or add questions.
2. **Runs** each question through the ``Assistant``, all in one session (origin "scenario"):
   every step is an ordinary run record with its SQL, trace and checked insight.
3. **Follows up** (LLM, optional): reads the facts the steps returned and proposes up to two
   questions about what they revealed; checked and run the same way.
4. **Answers** (LLM): combines the steps' facts into a headline, analytical points and a
   conclusion, each point citing the steps it rests on. Code checks every number against the
   facts of the cited steps (and against the years they cover), every country against their
   results and that observed years are not called projections. A second LLM call then judges
   only the reasoning (directions, comparisons, superlatives). A failing point is removed and
   noted; after two failed drafts a template lists each step's own headline.

The language model only sees the question, the data's codes and the steps' facts: it plans and
words, the assistant's code computes. Data limits come from the runs' limitation checks.

``python -m luxtrade.agents.scenario --demo`` records the example scenarios (needs an LLM key).
"""

import argparse
import hashlib
import json
import re
from collections.abc import Callable
from dataclasses import dataclass, field
from pathlib import Path

from pydantic import BaseModel, Field

from luxtrade.agents import guard
from luxtrade.agents.context import SessionContext
from luxtrade.agents.defaults import apply_defaults, share_of_nothing
from luxtrade.agents.evidence import EvidenceFigure, compose
from luxtrade.agents.grounding import (
    ALWAYS_ALLOWED,
    describes_future,
    numbers_in,
    parse_numbers,
    partners_named,
    plain_numbers,
    supports,
    unknown_partners,
    unsupported_numbers,
)
from luxtrade.agents.interpret import candidates_for, coverage_text, interpret, prompt
from luxtrade.agents.llm import LLMError
from luxtrade.agents.optimise import known_codes, optimise, validate_suggestion
from luxtrade.agents.presets import PRESETS
from luxtrade.agents.service import Assistant
from luxtrade.agents.share import ShareText, review_share, write_share
from luxtrade.agents.spec import SNAPSHOT_INTENTS, Language, QuerySpec, Suggestion
from luxtrade.runs.scenarios import ScenarioRecord, ScenarioStep, ScenarioStore
from luxtrade.runs.sessions import new_session_id
from luxtrade.runs.store import RunRecord, code_version, now_iso

MIN_STEPS, MAX_STEPS = 2, 5  # questions in a plan (the prompt asks for 3–5)
MAX_FOLLOW_UPS = 2
MAX_CHARTS = 3
Progress = Callable[[str], None]


# --- what the language model returns (validated by Pydantic, then checked by code) -------------
class PlanStep(BaseModel):
    """One proposed question of the chain."""

    question: str
    purpose: str
    spec: QuerySpec


class ScenarioPlan(BaseModel):
    """Planner output: the chain of questions and what the data cannot answer."""

    title: str
    approach: str
    steps: list[PlanStep]
    out_of_scope: list[str]


class FollowUp(BaseModel):
    """A question prompted by an earlier answer."""

    question: str
    purpose: str
    builds_on: list[int]
    spec: QuerySpec


class FollowUps(BaseModel):
    """Follow-up output: zero, one or two questions."""

    follow_ups: list[FollowUp]


class AnswerPoint(BaseModel):
    """One analytical point and the steps it rests on."""

    text: str
    steps: list[int]


class StepNote(BaseModel):
    """What one step adds to the answer."""

    step: int
    text: str


class ScenarioAnswer(BaseModel):
    """Answer writer output: checked against the steps' facts before it is shown."""

    headline: str
    points: list[AnswerPoint]
    conclusion: str
    step_notes: list[StepNote]
    charts: list[int]


_STEP_REF = re.compile(
    r"\s*\((?:steps?|étapes?|schritte?)\s+\d+(?:\s*(?:,|–|-|and|et|und)\s*\d+)*\)",
    re.IGNORECASE,
)


_CODE_REF = re.compile(r"\s*\((?:HS|SH|CN|NC|KN)\s?\d{2,8}\)|\b(?:HS|SH|CN|NC|KN)\s?\d{2,8}\s*")


def strip_step_refs(answer: ScenarioAnswer) -> ScenarioAnswer:
    """The answer without "(steps 1, 3)" or "(HS 8471)" in its text, which the prompt forbids.

    The ``steps`` lists already cite the steps, and the labels name the products. Seen on real
    data: "(steps 13, 17)" and "computers (HS 8471)" in points, which the number check then
    removed (13, 17 and 8471 are not in the facts), taking the points about China, the US
    and where computers came from with them.
    """

    def clean(text: str) -> str:
        return _CODE_REF.sub("", _STEP_REF.sub("", text))

    return answer.model_copy(
        update={
            "headline": clean(answer.headline),
            "points": [p.model_copy(update={"text": clean(p.text)}) for p in answer.points],
            "conclusion": clean(answer.conclusion),
            "step_notes": [n.model_copy(update={"text": clean(n.text)}) for n in answer.step_notes],
        }
    )


class Verdict(BaseModel):
    """Whether one claim follows from its facts, and if not, why.

    ``check`` comes first so the model writes out the comparison before it rules on it.
    """

    check: str
    supported: bool
    problem: str


class AnswerVerdicts(BaseModel):
    """Reasoning check output: one verdict per part of the answer."""

    headline: Verdict
    points: list[Verdict]
    conclusion: Verdict


class FitVerdict(BaseModel):
    """Whether an added or edited question fits the chain, and where it reads best."""

    fits: bool
    problem: str
    position: int


class Alternative(BaseModel):
    """An answerable rewrite of a question that failed its check."""

    question: str
    note: str = ""
    spec: QuerySpec
    queried: str = ""


class StepCheck(BaseModel):
    """The check of a question the user added or edited (``ScenarioBuilder.check_step``)."""

    ok: bool = False  # no problems: the assistant can answer it as written
    problems: list[str] = Field(default_factory=list)  # why it cannot be answered as written
    warnings: list[str] = Field(default_factory=list)  # fit, repetition, position
    spec: QuerySpec | None = None  # the checked reading, run as is
    queried: str = ""
    position: int | None = None  # a better step number, if the order reads better
    notes: list[str] = Field(default_factory=list)  # how it was read; informational only
    alternatives: list[Alternative] = Field(default_factory=list)  # answerable rewrites
    hint: str = ""  # what to add or change to make it answerable


# --- what the app hands over and keeps --------------------------------------------------------
class StepInput(BaseModel):
    """A question to run: from the plan (with its checked spec) or written by the user."""

    question: str
    purpose: str = ""
    spec: QuerySpec | None = None  # None: the assistant interprets the question itself
    kind: str = "plan"  # "plan" or "own"


class PlanResult(BaseModel):
    """A checked plan, ready to review: only the questions that passed the checks."""

    question: str
    language: Language = "en"
    title: str = ""
    approach: str = ""
    steps: list[PlanStep] = Field(default_factory=list)
    out_of_scope: list[str] = Field(default_factory=list)
    notes: list[str] = Field(default_factory=list)
    llm_usage: list[dict] = Field(default_factory=list)


_TEMPLATE = {
    "headline": {
        "en": "{n} of the {total} questions were answered from the data; their own headlines "
        "are listed below.",
        "fr": "{n} des {total} questions ont reçu une réponse à partir des données ; leurs "
        "titres sont repris ci-dessous.",
        "de": "{n} der {total} Fragen wurden aus den Daten beantwortet; ihre eigenen "
        "Überschriften stehen unten.",
    },
    "conclusion": {
        "en": "The combined summary did not pass the number check, so only each step's own "
        "checked headline is shown. Open the steps for their full answers.",
        "fr": "La synthèse n'a pas passé la vérification des chiffres : seuls les titres "
        "vérifiés de chaque étape sont affichés. Ouvrez les étapes pour leurs réponses.",
        "de": "Die Zusammenfassung hat die Zahlenprüfung nicht bestanden; daher stehen nur die "
        "geprüften Überschriften der Schritte hier. Öffnen Sie die Schritte für die Antworten.",
    },
}


def spec_fields() -> str:
    """The QuerySpec field reference, shared with the interpreter's prompt."""
    text = prompt("interpret")
    return text.split("## QuerySpec fields", 1)[1].split("## Rules", 1)[0].strip()


_FLOW = {
    "export": "exports",
    "import": "imports",
    "both": "exports and imports",
    "balance": "trade balance",
}
_MEASURE = {
    "value_eur": "value in €",
    "qty_kg": "mass in kg",
    "unit_value": "value per kg",
    "share": "share of the whole flow in %",
    "growth_yoy": "year-on-year growth",
    "change": "change between the two years",
    "hhi": "concentration index (HHI)",
}
_GROUP = {"EU27_2020": "EU27 partners", "EXTRA_EU27_2020": "non-EU27 partners"}


def describe(spec: dict | None) -> str:
    """What a resolved spec queried, in words: 'imports · by partner · 2025 · share …'."""
    if not spec:
        return ""
    parts = [_FLOW.get(spec.get("flow") or "both", "")]
    if spec.get("products"):
        parts.append("products " + ", ".join(spec["products"]))
    if spec.get("partners"):
        parts.append("partners " + ", ".join(spec["partners"]))
    if spec.get("partner_group") in _GROUP:
        parts.append(_GROUP[spec["partner_group"]])
    if spec.get("intent") == "benchmark":
        parts.append("vs " + ", ".join(spec.get("compare_reporters") or []) + " as reporters")
    breakdown = spec.get("breakdown")
    top = f" (top {spec['top_n']})" if spec.get("top_n") else ""
    if spec.get("measure") == "hhi":  # an index across every item, not a ranking
        across = "partners" if breakdown == "partner" else f"{spec.get('product_level')} products"
        parts.append(f"across all {across}")
    elif breakdown == "partner":
        parts.append("by partner" + top)
    elif breakdown == "product":
        parts.append(f"by {spec.get('product_level') or 'HS2'} product" + top)
    elif breakdown == "partner_group":
        parts.append("EU27 vs non-EU27")
    elif breakdown == "confidentiality":
        parts.append("confidential vs published")
    start, end = spec.get("period_start") or "", spec.get("period_end") or ""
    period = start if start == end else f"{start}–{end}"
    if spec.get("intent") in ("time_series", "seasonality", "forecast"):
        period += ", monthly" if spec.get("freq") == "M" else ", yearly"
    if spec.get("year_step"):
        period += f", every {spec['year_step']} years"
    parts += [period, _MEASURE.get(spec.get("measure") or "value_eur", "")]
    return " · ".join(p for p in parts if p)


_YEAR = re.compile(r"\b(?:19|20)\d{2}\b")
_LASTING = re.compile(
    r"\b(?:lasting|structural|steady|steadily|sustained|permanent|long-term|durable|"
    r"structurel\w*|régulier\w*|soutenu\w*|permanent\w*|"
    r"dauerhaft\w*|strukturell\w*|stetig\w*|anhaltend\w*|nachhaltig\w*)\b",
    re.IGNORECASE,
)
_NEGATION = re.compile(
    r"\b(?:rather\s+than|instead\s+of|not|no|never|than|plutôt\s+que|pas|non|nicht|kein\w*|"
    r"statt|anstatt)\b(?:\W+\w+){0,5}\W*$",
    re.IGNORECASE,
)
# a claim ends at a sentence mark or a contrast: "computers fell lastingly, while X jumped"
_CLAUSES = re.compile(
    r"[.;:!?](?=\s|$)|\b(?:while|whereas|but|unlike|although|however|yet|tandis\s+que|alors\s+que|"
    r"mais|contrairement|während|aber|jedoch|wohingegen)\b",
    re.IGNORECASE,
)


def jump_steps(records: dict[int, RunRecord], sem: object, lang: str) -> dict[int, str]:
    """Steps whose series jumped in its last period, with a word that names what jumped.

    A jump: the largest change between consecutive periods is the last one, and at least twice
    any earlier change (lifting machinery, 0.1 % for years, then 3.1 % in 2025).
    """
    found = {}
    for n, rec in records.items():
        spec = rec.spec or {}
        if rec.status != "answered" or spec.get("intent") != "time_series":
            continue
        frame = rec.frame("main")
        if frame.empty or not {"period", "value"} <= set(frame.columns):
            continue
        group = [c for c in ("key", "flow") if c in frame.columns]
        for _, g in frame.groupby(group) if group else [((), frame)]:
            moves = g.sort_values("period")["value"].astype(float).diff().dropna().abs()
            if len(moves) >= 3 and moves.iloc[-1] >= 2 * moves.iloc[:-1].max():
                codes = list(spec.get("products") or []) + list(spec.get("partners") or [])
                kind = "product" if spec.get("products") else "partner"
                if codes:
                    name = sem.label(codes[0], kind, lang)
                else:
                    name = str(g["label"].iloc[0]) if "label" in g.columns else ""
                cue = next((w for w in re.findall(r"\w+", name) if len(w) >= 4), "")
                if cue:
                    found[n] = cue.lower()
                break
    return found


def calls_jump_lasting(text: str, steps: set[int], jumps: dict[int, str]) -> list[str]:
    """Clauses that call a series that jumped in its last period lasting, steady or structural.

    Seen on real data: lifting machinery, 0.1 % of imports for years and 3.1 % in 2025 (96.6 %
    from Japan), written up as "lasting shifts rather than temporary spikes"; the reasoning
    check let it through. "Rather than a lasting trend" is not a claim of one.
    """
    found = []
    for clause in _CLAUSES.split(text):
        lasting = [
            m for m in _LASTING.finditer(clause) if not _NEGATION.search(clause[: m.start()])
        ]
        if not lasting:
            continue
        low = clause.lower()
        for n in sorted(steps & set(jumps)):
            if jumps[n] in low:
                found.append(
                    f"calls {jumps[n]} lasting or steady, but its series jumped only in its last "
                    f"period (step {n}): say it is a jump not yet confirmed"
                )
    return found


def mismatch(question: str, spec: dict, proposed: QuerySpec | None = None) -> str | None:
    """Why a question and its resolved spec disagree, or None.

    Seen on real data: "the top chapters in 2002 and in 2025" planned as one snapshot of 2002,
    or of 2002–2025 added up. Every year the question names must be in the queried period, and
    a snapshot (ranking, composition) covers one year unless it ranks the change between two.
    A proposed share must select or split something (``proposed``, before defaults): "the share
    of the top 3 export products over time" planned as a share of all exports is 100 %.
    """
    if proposed is not None and share_of_nothing(proposed):
        return (
            "a share needs a breakdown (by partner, product or EU27) or a partner or product "
            "filter; of the whole flow it is 100 %"
        )
    start, end = int(spec["period_start"][:4]), int(spec["period_end"][:4])
    named = {int(y) for y in _YEAR.findall(question)}
    outside = sorted(named - set(range(start, end + 1)))
    if outside:
        years = ", ".join(map(str, outside))
        return f"the question names {years} but the query covers {start}–{end}"
    if spec["intent"] in SNAPSHOT_INTENTS and spec.get("measure") != "change" and end > start:
        return (
            f"one snapshot would add up {start}–{end}: ask one year per question, rank the "
            "change between two years, or ask for a yearly series"
        )
    return None


# words that ask for detail below chapters (HS2), in EN, FR and DE
_DETAIL = re.compile(
    r"\b(hs ?[468]|cn ?8|headings?|sub-?headings?|detail(ed)?|positions?|postes?|"
    r"détail(lée?s?)?|Positionen|Unterpositionen|detailliert)\b",
    re.IGNORECASE,
)
_FINE = {"HS4", "HS6", "CN8"}


def prepare(
    spec: QuerySpec, lang: str, main_question: str, question: str, notes: list[str]
) -> QuerySpec:
    """A proposed spec in the scenario's language, ranked by chapter unless detail is asked for.

    A ranking of every heading (HS4 or finer) picks one-off swings in a country this small
    (seen on real data: "telephone sets broke first"). Without a product filter, and unless the
    user's question asks for headings, a proposed product ranking is kept at chapter level (HS2).
    """
    spec = spec.model_copy(update={"language": lang})
    fine = spec.breakdown == "product" and spec.product_level in _FINE and not spec.products
    if fine and not _DETAIL.search(main_question):
        notes.append(f"ranked by chapter (HS2), not {spec.product_level}: '{question}'")
        spec = spec.model_copy(update={"product_level": "HS2"})
    return spec


def _same_query(a: dict | None, b: dict | None) -> bool:
    """True if two resolved specs ask the same thing (wording and presentation aside)."""
    skip = {"assumptions", "language", "view"}
    if not a or not b:
        return False
    return {k: v for k, v in a.items() if k not in skip} == {
        k: v for k, v in b.items() if k not in skip
    }


def scenario_id(question: str, session_id: str, run_ids: list[str], vintage: str) -> str:
    """Content-addressed scenario ID (10 hex characters), like run IDs."""
    payload = json.dumps(
        {
            "question": question,
            "session": session_id,
            "runs": run_ids,
            "vintage": vintage,
            "code": code_version(),
        },
        sort_keys=True,
    )
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()[:10]


MIN_POINTS = 2  # an answer with fewer checked points falls back to the template


@dataclass
class AnswerReview:
    """What the checks found, per part of a combined answer.

    ``blocking`` problems (headline, conclusion, too few points) reject the whole draft; a
    failing point or step note is only removed, and the removal is noted.
    """

    blocking: list[str] = field(default_factory=list)
    points: dict[int, list[str]] = field(default_factory=dict)  # 0-based point index → problems
    notes: dict[int, list[str]] = field(default_factory=dict)  # step number → problems

    def problems(self) -> list[str]:
        """Every problem, worded for the next draft's PROBLEMS list."""
        return (
            self.blocking
            + [f"point {i + 1}: {p}" for i, ps in self.points.items() for p in ps]
            + [f"note on step {n}: {p}" for n, ps in self.notes.items() for p in ps]
        )

    def kept(self, answer: ScenarioAnswer) -> ScenarioAnswer:
        """The answer without its failing points and notes."""
        return answer.model_copy(
            update={
                "points": [p for i, p in enumerate(answer.points) if i not in self.points],
                "step_notes": [n for n in answer.step_notes if n.step not in self.notes],
            }
        )


def review_answer(
    answer: ScenarioAnswer, records: dict[int, RunRecord], question: str, sem: object, lang: str
) -> AnswerReview:
    """Check a combined answer against the steps' run records.

    Each point and step note may only quote numbers from the facts (and data-limit messages)
    of the steps it is about, and name only countries from their results; the headline and
    conclusion may draw on every answered step. Observed years are never projections.
    """
    answered = {n for n, r in records.items() if r.status == "answered"}

    def texts(steps: set[int]) -> list[str]:
        return [
            t
            for n in sorted(steps)
            for t in [f["text"] for f in records[n].facts]
            + [lim["message"] for lim in records[n].limitations]
        ]

    def partners(steps: set[int]) -> set[str]:
        # the run's entities hold at most ten codes; a change ranking of both flows names up to
        # twenty partners in its facts (seen on real data), so every country the facts name counts
        named = set(partners_named(" ".join(texts(steps)), sem, lang))
        return named | {
            code
            for n in steps
            for code in records[n].entities.get("partners", [])
            + list((records[n].spec or {}).get("partners", []))
        }

    forecast = any((records[n].spec or {}).get("intent") == "forecast" for n in answered)

    def period(n: int) -> range:
        spec = records[n].spec or {}
        start, end = (spec.get("period_start") or "0")[:4], (spec.get("period_end") or "0")[:4]
        return range(int(start), int(end) + 1)

    # a year is not a statistic: any year of the question or of a step's period may be named
    years = numbers_in([question], lang) + [float(y) for n in answered for y in period(n)]

    def misattributed(text: str, steps: set[int]) -> list[str]:
        """Numbers quoted next to years that the steps they come from do not cover.

        Seen on real data: a fall of 2019–2020 written as "during the 2008–09 crisis", in a
        point citing both steps. The number is in the cited facts, the context is not.
        """
        text = plain_numbers(text)
        named = {int(y) for y in _YEAR.findall(text)}
        if not named:
            return []
        found = []
        for value, decimals in parse_numbers(text, lang):
            if value in named or value in years or supports(value, decimals, ALWAYS_ALLOWED):
                continue
            sources = [
                n for n in sorted(steps) if supports(value, decimals, numbers_in(texts({n}), lang))
            ]
            if sources and not any(named & set(period(n)) for n in sources):
                spans = ", ".join(
                    f"step {n} ({period(n).start}–{period(n).stop - 1})" for n in sources
                )
                found.append(
                    f"number {value:g} comes from {spans}, not from "
                    f"{', '.join(map(str, sorted(named)))}"
                )
        return found

    def problems(text: str, steps: set[int]) -> list[str]:
        found = unsupported_numbers(text, years + numbers_in(texts(steps), lang), lang)
        found += misattributed(text, steps)
        found += unknown_partners(text, partners(steps), sem, lang)
        if describes_future(text) and not forecast:
            found.append("observed data described as projected or expected")
        return found

    jumps = jump_steps({n: records[n] for n in answered}, sem, lang)
    review = AnswerReview()
    if not answer.headline.strip():
        review.blocking.append("the headline is empty")
    for label, text in (("headline", answer.headline), ("conclusion", answer.conclusion)):
        review.blocking += [f"{label}: {p}" for p in problems(text, answered)]
    for i, point in enumerate(answer.points):
        cited = set(point.steps) & answered
        found = problems(point.text, cited) if cited else ["cites no answered step"]
        found += calls_jump_lasting(point.text, cited, jumps)  # a point is about its steps
        if found:
            review.points[i] = found
    for note in answer.step_notes:
        if note.step not in records:
            review.notes[note.step] = [f"step {note.step} does not exist"]
        elif found := problems(note.text, {note.step}):
            review.notes[note.step] = found
    if len(answer.points) - len(review.points) < MIN_POINTS:
        review.blocking.append(
            f"only {len(answer.points) - len(review.points)} of {len(answer.points)} points "
            f"passed the checks; at least {MIN_POINTS} are needed"
        )
    return review


def check_answer(
    answer: ScenarioAnswer, records: dict[int, RunRecord], question: str, sem: object, lang: str
) -> list[str]:
    """Every problem in a combined answer (empty list = fully grounded); see ``review_answer``."""
    return review_answer(answer, records, question, sem, lang).problems()


def to_markdown(record: ScenarioRecord, runs: dict[int, RunRecord]) -> str:
    """The scenario as a shareable Markdown report: answer, evidence, SQL and IDs."""
    lines = [f"# {record.label}", "", f"**Question:** {record.question}", ""]
    lines += ["## Answer", "", f"**{record.headline}**", ""]
    for p in record.points:
        refs = ", ".join(f"step {n}" for n in p.get("steps", []))
        lines.append(f"- {p['text']} *({refs})*")
    lines += ["", record.conclusion, ""]
    if record.out_of_scope:
        lines += ["**Not answerable with this data:** " + "; ".join(record.out_of_scope), ""]
    if record.caveats:
        lines += ["**Data limits that apply:**", ""]
        lines += [f"- {c['id']}: {c['message']}" for c in record.caveats]
        lines.append("")
    lines += ["## The chain of questions", ""]
    for s in record.steps:
        rec = runs.get(s.n)
        lines += [f"### Step {s.n} · {s.kind}", "", f"**{s.question}**", ""]
        if s.purpose:
            lines += [f"*Why:* {s.purpose}", ""]
        if s.queried:
            lines += [f"*Queried:* {s.queried}", ""]
        if rec is not None and rec.status == "answered":
            lines += [" ".join(rec.insight), ""]
            lines += [f"- {f['text']}" for f in rec.facts[:8]]
            lines += ["", "```sql", rec.sql or "", "```", ""]
        else:
            lines += [f"Not answered ({s.status}).", ""]
        if s.note:
            lines += [f"*What it adds:* {s.note}", ""]
        lines += [f"Run `{s.run_id}`", ""]
    lines += [
        "---",
        f"Scenario `{record.scenario_id}` · assistant session `{record.session_id}` · "
        f"data vintage {record.vintage} · code `{record.code_version}` · created "
        f"{record.created_at} · answer: {record.answer_source}",
        "",
        "Source: Eurostat Comext DS-045409. Every number comes from the SQL of the steps above.",
    ]
    return "\n".join(lines)


class ScenarioBuilder:
    """Plans, runs, follows up and answers a scenario with the assistant (see module docs)."""

    def __init__(self, assistant: Assistant, store: ScenarioStore | None = None) -> None:
        self.assistant = assistant
        self.store = store or ScenarioStore()

    @property
    def online(self) -> bool:
        """True when new scenarios can be planned (an LLM is configured)."""
        return self.assistant.llm is not None

    # --- 1. plan ------------------------------------------------------------------------------
    def plan(self, question: str, lang: str = "en") -> PlanResult:
        """Propose a chain of questions; keep the ones the optimiser's checks pass."""
        llm, sem = self.assistant.llm, self.assistant.sem
        if llm is None:
            raise LLMError("planning a scenario needs the LLM (set OPENAI_API_KEY)")
        question = question.strip()
        blocked = [lim.message for lim in guard.check_question(question) if lim.severity == "block"]
        cands = candidates_for(question, self.assistant.index, wide=True)
        user = "\n\n".join(
            [
                f"QUESTION: {question}",
                f"LANGUAGE: {lang}",
                coverage_text(sem),
                f"STEPS: {MIN_STEPS + 1} to {MAX_STEPS}",
                "SCOPE NOTES:\n" + ("\n".join(blocked) or "none"),
                "CANDIDATES:\n"
                + json.dumps([c.model_dump(exclude_none=True) for c in cands], ensure_ascii=False),
                "KNOWN CODES:\n" + known_codes(sem, lang),
                "SPEC FIELDS:\n" + spec_fields(),
            ]
        )
        start = len(llm.usage)
        notes: list[str] = []
        kept: list[PlanStep] = []
        best: ScenarioPlan | None = None
        # a second draft when questions were dropped and too few are left; the better one wins
        for attempt in range(2):
            out = llm.parse(
                step="scenario_plan",
                system=prompt("scenario_plan"),
                user=user,
                schema=ScenarioPlan,
                effort="medium",
            )
            before = len(notes)
            checked = self._checked(out.steps, lang, notes, question)
            if best is None or len(checked) > len(kept):
                kept, best = checked, out
            dropped = [n for n in notes[before:] if n.startswith("dropped")]
            if not dropped or len(kept) > MIN_STEPS or attempt == 1:
                break
            user += (
                f"\n\nPREVIOUS ATTEMPT: {len(checked)} questions passed the checks. These did "
                "not; fix or replace them:\n- " + "\n- ".join(dropped)
            )
        return PlanResult(
            question=question,
            language=lang,
            title=best.title,
            approach=best.approach,
            steps=kept[:MAX_STEPS],
            out_of_scope=list(dict.fromkeys(best.out_of_scope + blocked)),
            notes=notes,
            llm_usage=[u.__dict__ for u in llm.usage[start:]],
        )

    def _checked(
        self, steps: list[PlanStep], lang: str, notes: list[str], question: str = ""
    ) -> list[PlanStep]:
        """The steps whose spec is answerable and new, prepared (see ``prepare``)."""
        sem, kept, resolved = self.assistant.sem, [], []
        for s in steps:
            s = s.model_copy(update={"spec": prepare(s.spec, lang, question, s.question, notes)})
            problem = validate_suggestion(
                Suggestion(question=s.question, note=s.purpose, spec=s.spec), sem
            )
            spec = apply_defaults(s.spec, sem.coverage).model_dump(mode="json")
            if problem is None:
                problem = mismatch(s.question, spec, s.spec)
            if problem is None and any(_same_query(spec, r) for r in resolved):
                problem = "asks the same as an earlier step"
            if problem:
                notes.append(f"dropped '{s.question}': {problem}")
                continue
            kept.append(s)
            resolved.append(spec)
        return kept

    # --- 2–4. run, follow up, answer ----------------------------------------------------------
    def run(
        self,
        question: str,
        steps: list[StepInput],
        *,
        lang: str = "en",
        plan: PlanResult | None = None,
        follow_ups: bool = True,
        on_progress: Progress | None = None,
        based_on: str = "",
    ) -> ScenarioRecord:
        """Run the steps in one assistant session, follow up, answer, save and return the record."""
        say = on_progress or (lambda _label: None)
        llm, sem = self.assistant.llm, self.assistant.sem
        usage_start = len(llm.usage) if llm is not None else 0
        session_id = new_session_id()
        notes = list(plan.notes) if plan else []
        chain: list[ScenarioStep] = []
        records: dict[int, RunRecord] = {}
        for n, s in enumerate(steps, start=1):
            say(f"Step {n} of {len(steps)}: {s.question}")
            rec = self._ask(s.question, s.spec, session_id)
            records[n] = rec
            chain.append(
                ScenarioStep(
                    n=n,
                    kind=s.kind,
                    question=s.question,
                    purpose=s.purpose,
                    run_id=rec.run_id,
                    status=rec.status,
                    queried=describe(rec.spec),
                )
            )
        if follow_ups and llm is not None and any(r.status == "answered" for r in records.values()):
            say("Reading the answers for follow-up questions")
            for f in self._follow_ups(question, lang, plan, chain, records, notes):
                n = len(chain) + 1
                say(f"Follow-up {n}: {f.question}")
                rec = self._ask(f.question, f.spec, session_id)
                records[n] = rec
                chain.append(
                    ScenarioStep(
                        n=n,
                        kind="follow-up",
                        question=f.question,
                        purpose=f.purpose,
                        builds_on=f.builds_on,
                        run_id=rec.run_id,
                        status=rec.status,
                        queried=describe(rec.spec),
                    )
                )
        say("Combining the answers")
        answer, source = self._answer(question, lang, plan, chain, records, notes)
        for note in answer.step_notes:
            step = next((s for s in chain if s.n == note.step), None)
            if step is not None:
                step.note = note.text
        answered = [n for n, r in records.items() if r.status == "answered"]
        record = ScenarioRecord(
            scenario_id=scenario_id(
                question, session_id, [s.run_id for s in chain], sem.coverage.vintage
            ),
            session_id=session_id,
            created_at=now_iso(),
            question=question,
            language=lang,
            based_on=based_on,
            title=(plan.title if plan else "") or question[:60],
            approach=plan.approach if plan else "",
            out_of_scope=plan.out_of_scope if plan else [],
            steps=chain,
            headline=answer.headline,
            points=[p.model_dump() for p in answer.points],
            conclusion=answer.conclusion,
            charts=self._charts(answer.charts, records),
            figures=[f.model_dump() for f in self._evidence_figures(chain, records, answer, lang)],
            answer_source=source,
            caveats=self._caveats(records),
            notes=notes,
            llm_usage=(plan.llm_usage if plan else [])
            + [
                u.__dict__
                for u in (llm.usage[usage_start:] if llm is not None else [])
                if u.step.startswith("scenario_")
            ],
            vintage=sem.coverage.vintage,
            code_version=code_version(),
            status="failed"
            if not answered
            else ("answered" if len(answered) == len(chain) else "partial"),
        )
        self.store.save(record)
        self.assistant.sessions.retitle(session_id, f"Scenario: {record.title}")
        return record

    def _ask(self, question: str, spec: QuerySpec | None, session_id: str) -> RunRecord:
        """One step through the assistant: the checked spec, or the assistant's own reading."""
        if spec is not None:
            return self.assistant.run_spec(
                spec, question=question, origin="scenario", session_id=session_id
            )
        return self.assistant.ask(question, session_id=session_id, fresh=True)

    def _evidence(self, chain: list[ScenarioStep], records: dict[int, RunRecord]) -> str:
        """The steps as the LLM sees them: question, purpose and the facts code computed."""
        rows = []
        for s in chain:
            rec = records[s.n]
            rows.append(
                {
                    "step": s.n,
                    "question": s.question,
                    "purpose": s.purpose,
                    "queried": s.queried,
                    "answered": rec.status == "answered",
                    "facts": [f["text"] for f in rec.facts],
                    "entities": rec.entities,
                    "data_limits": [
                        lim["message"] for lim in rec.limitations if lim["severity"] == "warn"
                    ],
                }
            )
        return json.dumps(rows, ensure_ascii=False, indent=1)

    def _follow_ups(
        self,
        question: str,
        lang: str,
        plan: PlanResult | None,
        chain: list[ScenarioStep],
        records: dict[int, RunRecord],
        notes: list[str],
    ) -> list[FollowUp]:
        """Up to two checked, new questions prompted by the answers (none if not needed)."""
        llm, sem = self.assistant.llm, self.assistant.sem
        user = "\n\n".join(
            [
                f"QUESTION: {question}",
                f"LANGUAGE: {lang}",
                f"APPROACH: {plan.approach if plan else ''}",
                coverage_text(sem),
                "STEPS:\n" + self._evidence(chain, records),
                "CANDIDATES:\n"
                + json.dumps(
                    [
                        c.model_dump(exclude_none=True)
                        for c in candidates_for(question, self.assistant.index, wide=True)
                    ],
                    ensure_ascii=False,
                ),
                "KNOWN CODES:\n" + known_codes(sem, lang),
                "SPEC FIELDS:\n" + spec_fields(),
            ]
        )
        try:
            out = llm.parse(
                step="scenario_follow_up",
                system=prompt("scenario_follow_up"),
                user=user,
                schema=FollowUps,
                effort="medium",
            )
        except LLMError as exc:
            notes.append(f"follow-up LLM failed: {exc}")
            return []
        done = [r.spec for r in records.values()]
        kept: list[FollowUp] = []
        for f in out.follow_ups:
            f = f.model_copy(update={"spec": prepare(f.spec, lang, question, f.question, notes)})
            builds_on = [n for n in f.builds_on if n in records]
            problem = validate_suggestion(
                Suggestion(question=f.question, note=f.purpose, spec=f.spec), sem
            )
            spec = apply_defaults(f.spec, sem.coverage).model_dump(mode="json")
            if problem is None:
                problem = mismatch(f.question, spec, f.spec)
            if problem is None and not builds_on:
                problem = "builds on no step"
            if problem is None and any(_same_query(spec, d) for d in done):
                problem = "asks the same as an earlier step"
            if problem:
                notes.append(f"dropped follow-up '{f.question}': {problem}")
                continue
            kept.append(f.model_copy(update={"builds_on": builds_on}))
            done.append(spec)
            if len(kept) == MAX_FOLLOW_UPS:
                break
        if not kept:
            notes.append("no follow-up question was needed or answerable")
        return kept

    def _answer(
        self,
        question: str,
        lang: str,
        plan: PlanResult | None,
        chain: list[ScenarioStep],
        records: dict[int, RunRecord],
        notes: list[str],
    ) -> tuple[ScenarioAnswer, str]:
        """The combined answer, checked; the template after two failed drafts."""
        llm, sem = self.assistant.llm, self.assistant.sem
        if llm is not None and any(r.status == "answered" for r in records.values()):
            user = "\n\n".join(
                [
                    f"QUESTION: {question}",
                    f"LANGUAGE: {lang}",
                    f"APPROACH: {plan.approach if plan else ''}",
                    "OUT OF SCOPE: " + ("; ".join(plan.out_of_scope) if plan else "none"),
                    "STEPS:\n" + self._evidence(chain, records),
                ]
            )
            problems: list[str] = []
            previous: dict = {}
            for _ in range(2):
                prompt_user = user
                if problems:  # the draft itself too: at temperature 0 it would come back unchanged
                    prompt_user += "\n\nPREVIOUS DRAFT:\n" + json.dumps(
                        previous, ensure_ascii=False, indent=1
                    )
                    prompt_user += "\n\nPROBLEMS in the previous draft:\n- " + "\n- ".join(problems)
                try:
                    out = llm.parse(
                        step="scenario_answer",
                        system=prompt("scenario_answer"),
                        user=prompt_user,
                        schema=ScenarioAnswer,
                        effort="medium",
                    )
                except LLMError as exc:
                    notes.append(f"answer LLM failed: {exc}")
                    break
                out = strip_step_refs(out)
                previous = {
                    "headline": out.headline,
                    "points": [p.text for p in out.points],
                    "conclusion": out.conclusion,
                }
                review = review_answer(out, records, question, sem, lang)
                problems = review.problems()
                if review.blocking:
                    notes.append("answer check failed: " + "; ".join(problems))
                    continue
                if problems:  # a failing point or note is removed, never shown
                    notes.append("removed from the answer: " + "; ".join(problems))
                kept = review.kept(out)
                judged = self._reasoning(question, lang, chain, records, kept, notes)
                problems = judged.problems()
                if judged.blocking:
                    notes.append("reasoning check failed: " + "; ".join(problems))
                    continue
                if problems:
                    notes.append("removed by the reasoning check: " + "; ".join(problems))
                notes.append(
                    "combined answer passed the number, country, wording and reasoning checks"
                )
                return judged.kept(kept), "llm"
        notes.append("fell back to the template answer")
        return self._template(lang, chain, records), "template"

    def _reasoning(
        self,
        question: str,
        lang: str,
        chain: list[ScenarioStep],
        records: dict[int, RunRecord],
        answer: ScenarioAnswer,
        notes: list[str],
    ) -> AnswerReview:
        """A second, separate LLM call judging whether each claim follows from its facts.

        The numbers are already checked by code; this catches what code cannot read: a wrong
        direction ("more concentrated" where the top share fell), a comparison the wrong way
        round (33.6 % called less than 31.8 %), a superlative that fails in one cited step.
        The judge writes no text into the answer: an unsupported point is removed; an
        unsupported headline or conclusion asks for a new draft.
        """
        drafted = {
            "headline": answer.headline,
            "points": [
                {"point": i, "text": p.text, "steps": p.steps}
                for i, p in enumerate(answer.points, start=1)
            ],
            "conclusion": answer.conclusion,
        }
        user = "\n\n".join(
            [
                f"QUESTION: {question}",
                f"LANGUAGE: {lang}",
                "STEPS:\n" + self._evidence(chain, records),
                "ANSWER:\n" + json.dumps(drafted, ensure_ascii=False, indent=1),
            ]
        )
        try:
            out = self.assistant.llm.parse(
                step="scenario_review",
                system=prompt("scenario_review"),
                user=user,
                schema=AnswerVerdicts,
                effort="medium",
            )
        except LLMError as exc:
            notes.append(f"reasoning check unavailable: {exc}")
            return AnswerReview()
        review = AnswerReview()
        for label, verdict in (("headline", out.headline), ("conclusion", out.conclusion)):
            if not verdict.supported:
                review.blocking.append(f"{label}: {verdict.problem or 'does not follow'}")
        for i, verdict in enumerate(out.points[: len(answer.points)]):
            if not verdict.supported:
                review.points[i] = [verdict.problem or "does not follow from the cited facts"]
        if len(answer.points) - len(review.points) < MIN_POINTS:
            review.blocking.append(
                f"only {len(answer.points) - len(review.points)} points follow from their facts"
            )
        return review

    @staticmethod
    def _template(
        lang: str, chain: list[ScenarioStep], records: dict[int, RunRecord]
    ) -> ScenarioAnswer:
        """Each answered step's own checked headline, as the points of the answer."""
        lang = lang if lang in _TEMPLATE["headline"] else "en"
        answered = [s for s in chain if records[s.n].status == "answered"]
        return ScenarioAnswer(
            headline=_TEMPLATE["headline"][lang].format(n=len(answered), total=len(chain)),
            points=[
                AnswerPoint(text=records[s.n].title or s.question, steps=[s.n]) for s in answered
            ],
            conclusion=_TEMPLATE["conclusion"][lang],
            step_notes=[],
            charts=[],
        )

    @staticmethod
    def _charts(chosen: list[int], records: dict[int, RunRecord]) -> list[int]:
        """Up to three answered steps with a chart: the writer's choice, else the first ones."""
        drawable = [
            n
            for n, r in sorted(records.items())
            if r.status == "answered" and r.view_kind not in ("table", "kpi")
        ]
        picked = [n for n in dict.fromkeys(chosen) if n in drawable]
        return (picked or drawable)[:MAX_CHARTS]

    @staticmethod
    def _caveats(records: dict[int, RunRecord]) -> list[dict]:
        """The data limits the steps' runs flagged, once each, in registry order."""
        found: dict[str, str] = {}
        for rec in records.values():
            for lim in rec.limitations:
                if lim["severity"] == "warn":
                    found.setdefault(lim["id"], lim["message"])
        return [{"id": k, "message": found[k]} for k in sorted(found)]

    def _evidence_figures(
        self,
        chain: list[ScenarioStep],
        records: dict[int, RunRecord],
        answer: ScenarioAnswer,
        lang: str,
    ) -> list[EvidenceFigure]:
        """The answer's charts and key figures, computed by code from the steps' SQL."""
        text = " ".join([p.text for p in answer.points] + [answer.conclusion])
        try:
            return compose(chain, records, answer.headline, text, self.assistant.sem, lang)
        except Exception:  # noqa: BLE001 - a chart must never cost the answer
            return []

    def figures(self, record: ScenarioRecord) -> list[EvidenceFigure]:
        """The record's evidence figures; for older records, computed now from their runs."""
        if record.figures:
            return [EvidenceFigure.model_validate(f) for f in record.figures]
        answer = ScenarioAnswer(
            headline=record.headline,
            points=[AnswerPoint(**p) for p in record.points],
            conclusion=record.conclusion,
            step_notes=[],
            charts=[],
        )
        return self._evidence_figures(record.steps, self.records(record), answer, record.language)

    def share(self, record: ScenarioRecord, renew: bool = False) -> dict:
        """The share card's title and subtitle: written once from the checked answer, then kept.

        Kept in the record with the check notes and the LLM call, so a weekly post is stable
        and traceable. Without a language model the checked headline is used and nothing kept.
        ``renew`` writes a new title, different from the ones written before.
        """
        if record.share and not renew:
            return record.share
        llm = self.assistant.llm
        start = len(llm.usage) if llm is not None else 0
        earlier = list(record.share.get("earlier", []))
        if record.share.get("source") == "llm":
            earlier.append(record.share["title"])
        text, source, notes = write_share(
            llm, record, self.figures(record), self.assistant.sem, avoid=earlier if renew else None
        )
        share = {
            "title": text.title,
            "subtitle": text.subtitle,
            "source": source,
            "notes": notes,
            "earlier": earlier,
        }
        if llm is not None:
            record.share = share
            record.notes = [*record.notes, *notes]
            record.llm_usage += [u.__dict__ for u in llm.usage[start:]]
            self.store.save(record)
        return share

    def set_share(self, record: ScenarioRecord, title: str, subtitle: str) -> list[str]:
        """The user's own title and subtitle for the card, if they pass the checks.

        Same checks as a drafted one (every number, year and country in the checked answer or
        its key figures; lengths; a few figures): the problems are returned and nothing is kept,
        or the text is kept with the earlier titles.
        """
        text = ShareText(
            basis="user", title=" ".join(title.split()), subtitle=" ".join(subtitle.split())
        )
        problems = review_share(text, record, self.figures(record), self.assistant.sem, user=True)
        if problems:
            return problems
        earlier = list(record.share.get("earlier", []))
        if record.share.get("title") and record.share["title"] != text.title:
            earlier.append(record.share["title"])
        record.share = {
            "title": text.title,
            "subtitle": text.subtitle,
            "source": "user",
            "notes": ["written by the user; passed the number, country and wording checks"],
            "earlier": earlier,
        }
        self.store.save(record)
        return []

    def rename(self, scenario_id: str, name: str) -> ScenarioRecord | None:
        """Give a scenario the user's own name; its assistant session takes the name too."""
        rec = self.store.rename(scenario_id, name)
        if rec is not None:
            self.assistant.sessions.retitle(rec.session_id, f"Scenario: {rec.label}")
        return rec

    def records(self, record: ScenarioRecord) -> dict[int, RunRecord]:
        """The run records of a scenario's steps, by step number (missing ones left out)."""
        out = {}
        for s in record.steps:
            rec = self.assistant.runs.load(s.run_id) if s.run_id else None
            if rec is not None:
                out[s.n] = rec
        return out

    # --- a question the user added or edited in the proposed chain -----------------------------
    def check_step(
        self,
        main_question: str,
        chain: list[tuple[str, str]],
        n: int,
        lang: str = "en",
        others: list[QuerySpec | None] = (),
    ) -> StepCheck:
        """Check step ``n`` (1-based) of an edited chain of (question, why) pairs.

        Code reads the question with the assistant's interpreter and applies the plan's checks
        (codes, data limits, SQL guard, years, a share that selects something, repeats of the
        ``others`` steps' specs); a short LLM call judges whether it fits the main question and
        its neighbours, and where in the chain it reads best. Problems mean the assistant cannot
        answer it as written; warnings mean it may not belong, or not there.
        """
        llm, sem = self.assistant.llm, self.assistant.sem
        if llm is None:
            raise LLMError("checking a question needs the LLM (set OPENAI_API_KEY)")
        question = chain[n - 1][0].strip()
        check = StepCheck()
        interp = interpret(
            question,
            llm=llm,
            sem=sem,
            index=self.assistant.index,
            context=SessionContext(session_id="check"),
        )
        if interp.unresolved:
            check.problems.append("not found in the data: " + ", ".join(interp.unresolved))
        # the interpreter's notes on what it read ("energy crisis read as 2022–2023") block only
        # when that reading fails the checks below (seen on real data: a question naming its
        # years was rejected as "unclear")
        unclear = [a.text for a in interp.ambiguities if a.dimension in ("who", "what", "intent")]
        blocked = guard.check_question(question, interp.out_of_scope)
        check.problems += [lim.message for lim in blocked if lim.severity == "block"]
        if interp.needs_custom_sql:
            check.warnings.append(
                "needs SQL written by the language model; the assistant will try it as asked"
            )
        elif not check.problems:
            notes: list[str] = []
            # the user's own question: headings it asks for are kept (prepare reads its words)
            spec = prepare(interp.spec, lang, f"{main_question} {question}", question, notes)
            problem = validate_suggestion(Suggestion(question=question, note="", spec=spec), sem)
            resolved = apply_defaults(spec, sem.coverage).model_dump(mode="json")
            problem = problem or mismatch(question, resolved, spec)
            if problem:
                check.problems.append(problem)
                check.problems += [f"unclear: {u}" for u in unclear]
            else:
                check.notes += [f"read as: {u}" for u in unclear]
                check.spec, check.queried = spec, describe(resolved)
                for k, other in enumerate(others, start=1):
                    done = (
                        apply_defaults(other, sem.coverage).model_dump(mode="json")
                        if other
                        else None
                    )
                    if k != n and _same_query(resolved, done):
                        check.warnings.append(f"asks the same as step {k}")
            check.notes += notes
        listed = "\n".join(
            f"{k}. {q}" + (f" (why: {w})" if w else "") + ("   <- CANDIDATE" if k == n else "")
            for k, (q, w) in enumerate(chain, start=1)
        )
        try:
            fit = llm.parse(
                step="scenario_fit",
                system=prompt("scenario_fit"),
                user=f"MAIN QUESTION: {main_question}\nLANGUAGE: {lang}\nCANDIDATE: {n}\n\n"
                f"CHAIN:\n{listed}",
                schema=FitVerdict,
                effort="low",
            )
        except LLMError as exc:
            check.warnings.append(f"the fit with the chain could not be checked: {exc}")
        else:
            if not fit.fits:
                check.warnings.append(fit.problem or "it may not help answer the main question")
            if 1 <= fit.position <= len(chain) and fit.position != n:
                check.position = fit.position
                check.warnings.append(f"it would read better as step {fit.position}")
        check.ok = not check.problems
        if not check.ok:
            self._alternatives(main_question, question, n, lang, check)
        return check

    def _alternatives(
        self, main_question: str, question: str, n: int, lang: str, check: StepCheck
    ) -> None:
        """Up to three answerable rewrites of a failing question, and a hint to fix it by hand.

        The assistant's optimiser proposes the rewrites, told why the question failed and which
        broad question it serves; the same code checks as the plan keep only answerable ones.
        Its fallback presets (the hackathon's sample questions) are left out: off topic here.
        """
        sem = self.assistant.sem
        reason = (
            "; ".join(check.problems)
            + f". It is step {n} of an investigation answering: {main_question}"
        )
        presets = {p.for_language(lang)[0] for p in PRESETS}
        try:
            found, hint, _ = optimise(
                question,
                reason,
                lang=lang,
                llm=self.assistant.llm,
                sem=sem,
                index=self.assistant.index,
                context=SessionContext(session_id="check"),
            )
        except LLMError:
            return
        check.hint = hint
        for s in found:
            if s.question in presets:
                continue
            spec = prepare(s.spec, lang, main_question, s.question, [])
            resolved = apply_defaults(spec, sem.coverage).model_dump(mode="json")
            if mismatch(s.question, resolved, spec) is None:
                check.alternatives.append(
                    Alternative(
                        question=s.question, note=s.note, spec=spec, queried=describe(resolved)
                    )
                )

    def verify(self, record: ScenarioRecord) -> dict[int, str]:
        """Re-run every step's stored SQL and compare result hashes."""
        return {n: self.assistant.verify(rec) for n, rec in self.records(record).items()}


# --- recorded examples ------------------------------------------------------------------------
EXAMPLES = {
    "en": [
        "Has Luxembourg spread its risk, across the goods it sells and the countries it buys from?",
        "Which goods break first when a crisis hits Luxembourg's exports, and which import is "
        "critical?",
        "Is Luxembourg's trade becoming more European, and who changed places outside the EU?",
        "How did the 2022 energy price shock show in Luxembourg's fuel imports: price or volume?",
    ],
    "fr": [
        "Le Luxembourg a-t-il réparti ses risques, entre les biens qu'il vend et les pays "
        "auprès desquels il achète ?",
        "Le commerce du Luxembourg devient-il plus européen ?",
    ],
    "de": [
        "Hat Luxemburg sein Risiko gestreut, bei den Waren, die es verkauft, und den Ländern, "
        "bei denen es einkauft?",
        "Wird Luxemburgs Handel europäischer?",
    ],
}


# a short title per example, in the same order as EXAMPLES (shown as the example card's header)
EXAMPLE_TITLES = {
    "en": [
        "Spreading the risk",
        "Crises and critical imports",
        "A more European trade",
        "The 2022 energy shock",
    ],
    "fr": ["Répartition des risques", "Un commerce plus européen"],
    "de": ["Risikostreuung", "Ein europäischerer Handel"],
}


def examples(lang: str) -> list[tuple[str, str]]:
    """The example scenarios in ``lang`` (English otherwise), as (title, question)."""
    lang = lang if lang in EXAMPLES else "en"
    return list(zip(EXAMPLE_TITLES[lang], EXAMPLES[lang], strict=True))


def _forget(record: ScenarioRecord, root: Path) -> None:
    """Delete an earlier recording of an example: its scenario, run and session files."""
    for s in record.steps:
        (root / f"{s.run_id}.json").unlink(missing_ok=True)
    (root / "sessions" / f"{record.session_id}.json").unlink(missing_ok=True)
    (root / "scenarios" / f"{record.scenario_id}.json").unlink(missing_ok=True)


def record_examples(root: Path, languages: list[str], matching: str = "") -> None:
    """Plan and run the example scenarios live, stored as demo runs under ``root``.

    ``matching`` re-records only the examples whose question contains it (case-insensitive).
    """
    from luxtrade.runs.sessions import SessionStore
    from luxtrade.runs.store import RunStore

    runs = RunStore(root=root, demo_root=root)
    assistant = Assistant(runs=runs, sessions=SessionStore(runs, demo_root=root / "sessions"))
    store = ScenarioStore(root=root / "scenarios", demo_root=root / "scenarios")
    builder = ScenarioBuilder(assistant, store)
    if not builder.online:
        raise SystemExit("No LLM configured: set OPENAI_API_KEY (or the Anthropic key).")
    old = {r.question: r for r in store.recent(limit=500)}
    for lang in languages:
        for question in EXAMPLES[lang]:
            if matching.lower() not in question.lower():
                continue
            if question in old:
                _forget(old[question], root)
            plan = builder.plan(question, lang)
            steps = [
                StepInput(question=s.question, purpose=s.purpose, spec=s.spec) for s in plan.steps
            ]
            rec = builder.run(question, steps, lang=lang, plan=plan, on_progress=print)
            print(f"-> {rec.scenario_id} · {rec.status} · answer: {rec.answer_source}\n")


if __name__ == "__main__":
    from luxtrade.config import DEMO_RUNS_DIR

    parser = argparse.ArgumentParser(description="Record the example scenarios (live LLM).")
    parser.add_argument("--demo", action="store_true", help="record the examples as demo runs")
    parser.add_argument("--lang", nargs="*", default=["en"], help="languages to record")
    parser.add_argument("--matching", default="", help="only examples whose question has this")
    args = parser.parse_args()
    if args.demo:
        record_examples(DEMO_RUNS_DIR, args.lang, args.matching)
