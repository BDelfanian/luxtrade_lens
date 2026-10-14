"""Presets: the official sample questions Q1–Q6 as one-click specs (no LLM needed)."""

from pydantic import BaseModel

from luxtrade.agents.spec import QuerySpec


class Preset(BaseModel):
    """A sample question with its spec and labels in EN/FR/DE."""

    id: str
    label: dict[str, str]
    question: dict[str, str]
    spec: QuerySpec

    def for_language(self, lang: str) -> tuple[str, QuerySpec]:
        """Question text and spec in the given language."""
        return self.question.get(lang, self.question["en"]), self.spec.model_copy(
            update={"language": lang}
        )


PRESETS: list[Preset] = [
    Preset(
        id="Q1",
        label={"en": "Main partners", "fr": "Principaux partenaires", "de": "Wichtigste Partner"},
        question={
            "en": "Who are Luxembourg's main trading partners?",
            "fr": "Quels sont les principaux partenaires commerciaux du Luxembourg ?",
            "de": "Wer sind Luxemburgs wichtigste Handelspartner?",
        },
        spec=QuerySpec(intent="ranking", breakdown="partner"),
    ),
    Preset(
        id="Q2",
        label={"en": "Main goods", "fr": "Principales marchandises", "de": "Wichtigste Waren"},
        question={
            "en": "What are the main categories of goods exported and imported?",
            "fr": "Quelles sont les principales catégories de marchandises exportées "
            "et importées ?",
            "de": "Welche Warengruppen werden hauptsächlich exportiert und importiert?",
        },
        spec=QuerySpec(intent="ranking", breakdown="product", product_level="HS2"),
    ),
    Preset(
        id="Q3",
        label={
            "en": "Partners for vehicles",
            "fr": "Partenaires pour les véhicules",
            "de": "Partner für Fahrzeuge",
        },
        question={
            "en": "Who are the main partners for vehicles (HS 87)?",
            "fr": "Quels sont les principaux partenaires pour les véhicules (SH 87) ?",
            "de": "Wer sind die wichtigsten Partner bei Fahrzeugen (HS 87)?",
        },
        spec=QuerySpec(intent="ranking", breakdown="partner", products=["87"]),
    ),
    Preset(
        id="Q4",
        label={
            "en": "What we trade with Germany",
            "fr": "Échanges avec l'Allemagne",
            "de": "Handel mit Deutschland",
        },
        question={
            "en": "What are the main goods traded with Germany, by chapter?",
            "fr": "Quelles sont les principales marchandises échangées avec l'Allemagne ?",
            "de": "Welche Waren werden hauptsächlich mit Deutschland gehandelt?",
        },
        spec=QuerySpec(intent="drilldown", partners=["DE"], product_level="HS2"),
    ),
    Preset(
        id="Q5",
        label={
            "en": "Luxembourg vs EU peers",
            "fr": "Le Luxembourg face à ses voisins",
            "de": "Luxemburg im EU-Vergleich",
        },
        question={
            "en": "How does Luxembourg's trade compare with other EU countries?",
            "fr": "Comment le commerce du Luxembourg se compare-t-il à celui "
            "d'autres pays de l'UE ?",
            "de": "Wie schneidet Luxemburgs Handel im Vergleich zu anderen EU-Ländern ab?",
        },
        spec=QuerySpec(intent="benchmark"),
    ),
    Preset(
        id="Q6",
        label={
            "en": "Seasonal pattern of exports",
            "fr": "Saisonnalité des exportations",
            "de": "Saisonmuster der Exporte",
        },
        question={
            "en": "Do Luxembourg's exports have a seasonal pattern?",
            "fr": "Les exportations du Luxembourg ont-elles un profil saisonnier ?",
            "de": "Haben Luxemburgs Exporte ein saisonales Muster?",
        },
        spec=QuerySpec(intent="seasonality", flow="export"),
    ),
]


def preset(preset_id: str) -> Preset:
    """Look up a preset by ID."""
    return next(p for p in PRESETS if p.id == preset_id)
