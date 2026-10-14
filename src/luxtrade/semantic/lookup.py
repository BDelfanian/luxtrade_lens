"""Entity lookup: map words in a question (EN/FR/DE) to partner, product and group codes.

The interpreter may only use codes returned here or present in the session context
(SOLUTION_DESIGN §5.2), so this is where "Allemagne", "Maschinen" or "cars" become codes.
"""

import re
import unicodedata
from difflib import SequenceMatcher

from pydantic import BaseModel

from luxtrade.semantic.layer import SemanticLayer

_STOP = {
    "and",
    "the",
    "of",
    "for",
    "with",
    "other",
    "than",
    "thereof",
    "parts",
    "articles",
    "et",
    "de",
    "des",
    "du",
    "la",
    "le",
    "les",
    "en",
    "ou",
    "autres",
    "leurs",
    "ces",
    "und",
    "der",
    "die",
    "das",
    "von",
    "aus",
    "mit",
    "andere",
    "teile",
    "waren",
    "davon",
    # generic trade words that appear in many labels or questions
    "products",
    "produits",
    "produkte",
    "erzeugnisse",
    "goods",
    "marchandises",
    "trade",
    "commerce",
    "handel",
    "exports",
    "imports",
    "export",
    "import",
    "main",
    "principaux",
}
# Adjectives and short names that fuzzy matching misses
_PARTNER_ALIASES = {
    "german": "DE",
    "allemand": "DE",
    "allemande": "DE",
    "deutsch": "DE",
    "deutschen": "DE",
    "french": "FR",
    "francais": "FR",
    "francaise": "FR",
    "franzosisch": "FR",
    "belgian": "BE",
    "belge": "BE",
    "belgisch": "BE",
    "dutch": "NL",
    "holland": "NL",
    "neerlandais": "NL",
    "niederlandisch": "NL",
    "italian": "IT",
    "italien": "IT",
    "spanish": "ES",
    "espagnol": "ES",
    "chinese": "CN",
    "chinois": "CN",
    "chinesisch": "CN",
    "japanese": "JP",
    "japonais": "JP",
    "american": "US",
    "usa": "US",
    "americain": "US",
    "amerika": "US",
    "uk": "GB",
    "britain": "GB",
    "british": "GB",
    "britannique": "GB",
    "england": "GB",
    "swiss": "CH",
    "suisse": "CH",
}
_GROUPS = {
    "EU27_2020": [
        "eu",
        "ue",
        "european union",
        "union europeenne",
        "europaische union",
        "intra-eu",
        "intra eu",
        "intra-ue",
        "eu27",
        "eu-27",
        "eu member states",
    ],
    "EXTRA_EU27_2020": [
        "extra-eu",
        "extra eu",
        "non-eu",
        "outside the eu",
        "hors ue",
        "extra-ue",
        "ausserhalb der eu",
        "drittlander",
        "third countries",
    ],
}
_UPPER_CODES_RE = re.compile(r"(?<![\w.])(USA|U\.S\.|US|UK)(?![\w])")
_CODE_RE = re.compile(
    r"\b(?:(hs|sh|cn|nc|kapitel|chapitre|chapter)\s*)?(\d{2}|\d{4}|\d{6}|\d{8})\b"
)


class Candidate(BaseModel):
    """A possible meaning of a piece of the question."""

    kind: str  # partner | product | group
    code: str
    label: str
    matched: str
    score: float
    level: int | None = None


def normalise(text: str) -> str:
    """Lowercase, strip accents and punctuation (keeps hyphens)."""
    text = unicodedata.normalize("NFKD", text.lower())
    text = "".join(c for c in text if not unicodedata.combining(c))
    return re.sub(r"[^\w\s-]", " ", text).replace("ß", "ss")


def _ngrams(tokens: list[str], max_n: int = 4) -> list[str]:
    return [
        " ".join(tokens[i : i + n]) for n in range(1, max_n + 1) for i in range(len(tokens) - n + 1)
    ]


class EntityIndex:
    """Fuzzy index over partner and product labels in all three languages."""

    def __init__(self, semantic: SemanticLayer) -> None:
        self.semantic = semantic
        self._entries: list[
            tuple[str, str, int | None, str, str]
        ] = []  # kind, code, level, norm, label
        for code, row in semantic.partners.iterrows():
            for col in ("label_en", "label_fr", "label_de"):
                self._entries.append(("partner", str(code), None, normalise(row[col]), row[col]))
        for code, row in semantic.products.iterrows():
            if row["level"] > 4 or "X" in str(code):
                continue  # HS6/CN8 placeholder labels and masked codes are not searched by name
            for col in ("label_en", "label_fr", "label_de"):
                self._entries.append(
                    ("product", str(code), int(row["level"]), normalise(row[col]), row[col])
                )

    def find(self, question: str, threshold: float = 0.84, limit: int = 12) -> list[Candidate]:
        """Return the best candidates for entities mentioned in the question."""
        norm = normalise(question)
        tokens = norm.split()
        grams = _ngrams(tokens)
        best: dict[tuple[str, str], Candidate] = {}

        def add(c: Candidate) -> None:
            key = (c.kind, c.code)
            if key not in best or c.score > best[key].score:
                best[key] = c

        for group, phrases in _GROUPS.items():
            for phrase in phrases:
                if re.search(rf"(?<![\w-]){re.escape(phrase)}(?![\w-])", norm):
                    add(Candidate(kind="group", code=group, label=group, matched=phrase, score=1.0))
        for m in _UPPER_CODES_RE.finditer(question):  # case-sensitive: "US" yes, "us" no
            code = {"USA": "US", "U.S.": "US", "UK": "GB"}.get(m.group(1), m.group(1))
            if self.semantic.has_code(code, "partner"):
                add(
                    Candidate(
                        kind="partner",
                        code=code,
                        label=self.semantic.label(code, "partner"),
                        matched=m.group(1),
                        score=0.95,
                    )
                )
        for token in tokens:
            if token in _PARTNER_ALIASES and self.semantic.has_code(
                _PARTNER_ALIASES[token], "partner"
            ):
                code = _PARTNER_ALIASES[token]
                add(
                    Candidate(
                        kind="partner",
                        code=code,
                        label=self.semantic.label(code, "partner"),
                        matched=token,
                        score=0.95,
                    )
                )
        for m in _CODE_RE.finditer(norm):
            prefix, digits = m.group(1), m.group(2)
            if len(digits) == 4 and not prefix and 1990 <= int(digits) <= 2035:
                continue  # a year, not a heading
            if self.semantic.has_code(digits, "product"):
                level = int(self.semantic.products.at[digits, "level"])
                add(
                    Candidate(
                        kind="product",
                        code=digits,
                        level=level,
                        matched=m.group(0),
                        label=self.semantic.label(digits, "product"),
                        score=1.0,
                    )
                )

        for kind, code, level, label_norm, label in self._entries:
            words = [w for w in label_norm.split() if len(w) >= 4 and w not in _STOP]
            if label_norm and re.search(rf"\b{re.escape(label_norm)}\b", norm):
                add(
                    Candidate(
                        kind=kind,
                        code=code,
                        level=level,
                        label=label,
                        matched=label_norm,
                        score=1.0,
                    )
                )
                continue
            for gram in grams:
                if len(gram) < 4 or gram in _STOP:
                    continue
                ratio = SequenceMatcher(None, gram, label_norm).ratio()
                if ratio >= threshold:
                    add(
                        Candidate(
                            kind=kind,
                            code=code,
                            level=level,
                            label=label,
                            matched=gram,
                            score=round(ratio, 3),
                        )
                    )
            for word in words:
                for token in tokens:
                    if len(token) < 4 or token in _STOP:
                        continue
                    ratio = SequenceMatcher(None, token, word).ratio()
                    if ratio >= max(threshold, 0.86):
                        add(
                            Candidate(
                                kind=kind,
                                code=code,
                                level=level,
                                label=label,
                                matched=token,
                                score=round(0.8 * ratio, 3),
                            )
                        )
        ranked = sorted(best.values(), key=lambda c: (-c.score, c.kind, c.code))
        return ranked[:limit]
