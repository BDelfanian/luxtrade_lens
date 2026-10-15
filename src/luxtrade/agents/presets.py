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


# Examples of well-asked questions: each names its period, flow, size of ranking and product
# code, so nothing is left to the defaults. 2025 = latest complete year of the 2026-10-14 vintage.
PRESET_YEAR = "2025"

PRESETS: list[Preset] = [
    Preset(
        id="Q1",
        label={"en": "Main partners", "fr": "Principaux partenaires", "de": "Wichtigste Partner"},
        question={
            "en": "Who were Luxembourg's top 10 trading partners in 2025, for exports and imports?",
            "fr": "Quels étaient les 10 principaux partenaires commerciaux du Luxembourg "
            "en 2025, à l'exportation et à l'importation ?",
            "de": "Wer waren 2025 Luxemburgs 10 wichtigste Handelspartner, "
            "bei Exporten und Importen?",
        },
        spec=QuerySpec(
            intent="ranking",
            breakdown="partner",
            flow="both",
            period_start=PRESET_YEAR,
            period_end=PRESET_YEAR,
            top_n=10,
        ),
    ),
    Preset(
        id="Q2",
        label={"en": "Main goods", "fr": "Principales marchandises", "de": "Wichtigste Waren"},
        question={
            "en": "What were the top 10 goods chapters (HS2) exported and imported by "
            "Luxembourg in 2025?",
            "fr": "Quels étaient les 10 principaux chapitres de marchandises (SH2) exportés "
            "et importés par le Luxembourg en 2025 ?",
            "de": "Welche 10 Warenkapitel (HS2) hat Luxemburg 2025 am meisten exportiert "
            "und importiert?",
        },
        spec=QuerySpec(
            intent="ranking",
            breakdown="product",
            product_level="HS2",
            flow="both",
            period_start=PRESET_YEAR,
            period_end=PRESET_YEAR,
            top_n=10,
        ),
    ),
    Preset(
        id="Q3",
        label={
            "en": "Partners for vehicles",
            "fr": "Partenaires pour les véhicules",
            "de": "Partner für Fahrzeuge",
        },
        question={
            "en": "Who were the top 10 partners for vehicles and parts (HS 87) in 2025, "
            "for exports and imports?",
            "fr": "Quels étaient les 10 principaux partenaires pour les véhicules et leurs "
            "parties (SH 87) en 2025, à l'exportation et à l'importation ?",
            "de": "Wer waren 2025 die 10 wichtigsten Partner bei Fahrzeugen und Teilen "
            "(HS 87), bei Exporten und Importen?",
        },
        spec=QuerySpec(
            intent="ranking",
            breakdown="partner",
            products=["87"],
            flow="both",
            period_start=PRESET_YEAR,
            period_end=PRESET_YEAR,
            top_n=10,
        ),
    ),
    Preset(
        id="Q4",
        label={
            "en": "What we trade with Germany",
            "fr": "Échanges avec l'Allemagne",
            "de": "Handel mit Deutschland",
        },
        question={
            "en": "What were the main goods traded with Germany in 2025, by HS2 chapter "
            "with detail down to CN8?",
            "fr": "Quelles étaient les principales marchandises échangées avec l'Allemagne "
            "en 2025, par chapitre SH2 avec le détail jusqu'à la NC8 ?",
            "de": "Welche Waren wurden 2025 hauptsächlich mit Deutschland gehandelt, "
            "nach HS2-Kapitel mit Details bis KN8?",
        },
        spec=QuerySpec(
            intent="drilldown",
            partners=["DE"],
            product_level="HS2",
            flow="both",
            period_start=PRESET_YEAR,
            period_end=PRESET_YEAR,
            top_n=10,
        ),
    ),
    Preset(
        id="Q5",
        label={
            "en": "Luxembourg vs EU peers",
            "fr": "Le Luxembourg face à ses voisins",
            "de": "Luxemburg im EU-Vergleich",
        },
        question={
            "en": "How did Luxembourg's trade grow from 2015 to 2025 compared with Belgium, "
            "the Netherlands, Germany, France and Austria (index 2015 = 100)?",
            "fr": "Comment le commerce du Luxembourg a-t-il évolué de 2015 à 2025 par rapport "
            "à la Belgique, aux Pays-Bas, à l'Allemagne, à la France et à l'Autriche "
            "(indice 2015 = 100) ?",
            "de": "Wie hat sich Luxemburgs Handel von 2015 bis 2025 im Vergleich zu Belgien, "
            "den Niederlanden, Deutschland, Frankreich und Österreich entwickelt "
            "(Index 2015 = 100)?",
        },
        spec=QuerySpec(
            intent="benchmark",
            compare_reporters=["BE", "NL", "DE", "FR", "AT"],
            flow="both",
            period_start="2015",
            period_end=PRESET_YEAR,
        ),
    ),
    Preset(
        id="Q6",
        label={
            "en": "Seasonal pattern of exports",
            "fr": "Saisonnalité des exportations",
            "de": "Saisonmuster der Exporte",
        },
        question={
            "en": "Do Luxembourg's monthly exports since January 2002 have a seasonal "
            "pattern, and what is the trend without it?",
            "fr": "Les exportations mensuelles du Luxembourg depuis janvier 2002 ont-elles "
            "un profil saisonnier, et quelle est la tendance sans lui ?",
            "de": "Haben Luxemburgs monatliche Exporte seit Januar 2002 ein saisonales "
            "Muster, und wie verläuft der Trend ohne es?",
        },
        # no end month: the series runs to the latest complete month of the data
        spec=QuerySpec(intent="seasonality", flow="export", period_start="2002-01"),
    ),
]


def preset(preset_id: str) -> Preset:
    """Look up a preset by ID."""
    return next(p for p in PRESETS if p.id == preset_id)
