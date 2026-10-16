"""The assistant in one slide: what it does and for whom (presentation mode, before the findings).

Also the kicker of the slide that follows, so the results read as the tool's output. Fixed texts
in English, French and German; every feature named here exists in the app.
"""

from dataclasses import dataclass


@dataclass
class ToolPitch:
    """The slide that presents the assistant; the findings that follow are made with it."""

    kicker: str
    headline: str
    audience: str
    features: list[tuple[str, str, str, str]]  # (tint key, icon, title, text)
    flow: list[str]  # the pipeline, step by step
    bridge: str  # the link to the findings


_FEATURES = {
    "en": [
        (
            "Ask in your own words",
            "English, French or German, no codes or SQL. The assistant picks the right view: "
            "map, chart, treemap, pivot or table, and explains it in plain language.",
        ),
        (
            "Never stuck on a vague question",
            "The optimiser offers three precise, checked rewrites; follow-ups keep the "
            "context; Refine changes years, flow or top N without retyping.",
        ),
        (
            "Every number traceable",
            "Guarded SQL on the official data, each sentence checked against the numbers, "
            "the data limits that apply, and a run ID to reopen any answer.",
        ),
        (
            "From answers to reports",
            "Download the data as CSV, build dashboards from examples or your own queries "
            "and save them as files, and present the results as slides saved to PDF.",
        ),
    ],
    "fr": [
        (
            "Demandez avec vos mots",
            "En français, anglais ou allemand, sans codes ni SQL. L'assistant choisit la "
            "bonne vue : carte, graphique, treemap, tableau croisé ou tableau, et l'explique "
            "simplement.",
        ),
        (
            "Jamais bloqué par une question vague",
            "L'optimiseur propose trois reformulations précises et vérifiées ; les questions "
            "de suivi gardent le contexte ; Affiner change les années, le flux ou le top N "
            "sans tout retaper.",
        ),
        (
            "Chaque chiffre traçable",
            "Du SQL contrôlé sur les données officielles, chaque phrase vérifiée par rapport "
            "aux chiffres, les limites des données, et un identifiant pour rouvrir chaque "
            "réponse.",
        ),
        (
            "Des réponses aux rapports",
            "Téléchargez les données en CSV, composez des tableaux de bord à partir "
            "d'exemples ou de vos requêtes et enregistrez-les, et présentez les résultats "
            "en diapositives exportées en PDF.",
        ),
    ],
    "de": [
        (
            "Fragen in eigenen Worten",
            "Auf Deutsch, Englisch oder Französisch, ohne Codes oder SQL. Der Assistent wählt "
            "die passende Ansicht: Karte, Diagramm, Treemap, Pivot oder Tabelle, und erklärt "
            "sie in einfacher Sprache.",
        ),
        (
            "Nie an einer vagen Frage hängen",
            "Der Optimierer schlägt drei präzise, geprüfte Umformulierungen vor; Folgefragen "
            "behalten den Kontext; Verfeinern ändert Jahre, Richtung oder Top N ohne neue "
            "Eingabe.",
        ),
        (
            "Jede Zahl nachvollziehbar",
            "Geprüftes SQL auf den amtlichen Daten, jeder Satz gegen die Zahlen geprüft, die "
            "geltenden Datengrenzen und eine Run-ID, um jede Antwort wieder zu öffnen.",
        ),
        (
            "Von Antworten zu Berichten",
            "Daten als CSV herunterladen, Dashboards aus Beispielen oder eigenen Abfragen "
            "bauen und speichern, und die Ergebnisse als Folien im PDF präsentieren.",
        ),
    ],
}
_LOOK = [  # (tint key, icon) per feature
    ("diversification", ":material/forum:"),
    ("composition", ":material/auto_fix_high:"),
    ("europe", ":material/verified:"),
    ("prices", ":material/dashboard:"),
]
_T = {
    "kicker": {
        "en": "Our tool: the LuxTrade Lens assistant",
        "fr": "Notre outil : l'assistant LuxTrade Lens",
        "de": "Unser Werkzeug: der LuxTrade-Lens-Assistent",
    },
    "headline": {
        "en": "Ask the trade data a question. Get a checked answer in seconds.",
        "fr": "Posez une question aux données du commerce. Obtenez une réponse vérifiée en "
        "quelques secondes.",
        "de": "Stellen Sie den Handelsdaten eine Frage. Erhalten Sie in Sekunden eine "
        "geprüfte Antwort.",
    },
    "audience": {
        "en": "For policy officers, analysts, journalists, businesses and students: anyone can "
        "run their own statistical analysis and build dashboards and reports, without "
        "knowing SQL or product codes.",
        "fr": "Pour les décideurs publics, analystes, journalistes, entreprises et étudiants : "
        "chacun peut mener sa propre analyse statistique et créer tableaux de bord et "
        "rapports, sans connaître le SQL ni les codes produits.",
        "de": "Für Verwaltung, Analysten, Journalisten, Unternehmen und Studierende: Alle können "
        "eigene statistische Analysen durchführen und Dashboards und Berichte erstellen, "
        "ohne SQL oder Produktcodes zu kennen.",
    },
    "flow": {
        "en": ["Your question", "Query plan", "Guarded SQL", "Chart + checked insight"],
        "fr": ["Votre question", "Plan de requête", "SQL contrôlé", "Graphique + analyse vérifiée"],
        "de": ["Ihre Frage", "Abfrageplan", "Geprüftes SQL", "Diagramm + geprüfte Analyse"],
    },
    "bridge": {
        "en": "The language model only translates the question; the numbers are computed by "
        "code. The five findings that follow were built on the same engine, and each one "
        "opens in the assistant.",
        "fr": "Le modèle de langage ne fait que traduire la question ; les chiffres sont "
        "calculés par du code. Les cinq constats qui suivent reposent sur le même moteur, "
        "et chacun s'ouvre dans l'assistant.",
        "de": "Das Sprachmodell übersetzt nur die Frage; die Zahlen berechnet Code. Die fünf "
        "folgenden Erkenntnisse beruhen auf derselben Engine, und jede lässt sich im "
        "Assistenten öffnen.",
    },
}


_NUMBERS_KICKER = {
    "en": "What the assistant found: the key numbers",
    "fr": "Ce que l'assistant a trouvé : les chiffres clés",
    "de": "Was der Assistent gefunden hat: die wichtigsten Zahlen",
}


def numbers_kicker(lang: str) -> str:
    """The kicker of the slide with the findings in numbers (after the tool slide)."""
    return _NUMBERS_KICKER.get(lang, _NUMBERS_KICKER["en"])


def tool_pitch(lang: str) -> ToolPitch:
    """The assistant's slide in ``lang`` (en, fr or de; English otherwise)."""
    lang = lang if lang in _FEATURES else "en"
    return ToolPitch(
        kicker=_T["kicker"][lang],
        headline=_T["headline"][lang],
        audience=_T["audience"][lang],
        features=[
            (tint, icon, title, text)
            for (tint, icon), (title, text) in zip(_LOOK, _FEATURES[lang], strict=True)
        ],
        flow=_T["flow"][lang],
        bridge=_T["bridge"][lang],
    )
