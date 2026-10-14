"""Locale-aware number, period and flow formatting (EN/FR/DE) for charts, facts, grounding."""

from datetime import date

_UNITS = {
    "bn": {"en": "bn €", "fr": "Md €", "de": "Mrd. €"},
    "m": {"en": "M€", "fr": "M€", "de": "Mio. €"},
    "k": {"en": "k €", "fr": "k €", "de": "Tsd. €"},
}
FLOW_LABELS = {
    "export": {"en": "exports", "fr": "exportations", "de": "Exporte"},
    "import": {"en": "imports", "fr": "importations", "de": "Importe"},
    "total": {"en": "total trade", "fr": "commerce total", "de": "Gesamthandel"},
    "balance": {"en": "trade balance", "fr": "solde commercial", "de": "Handelsbilanz"},
    "both": {
        "en": "exports and imports",
        "fr": "exportations et importations",
        "de": "Exporte und Importe",
    },
}
MONTHS = {
    "en": "Jan Feb Mar Apr May Jun Jul Aug Sep Oct Nov Dec".split(),  # noqa: SIM905
    "fr": "janv. févr. mars avr. mai juin juil. août sept. oct. nov. déc.".split(),  # noqa: SIM905
    "de": "Jan. Feb. März Apr. Mai Juni Juli Aug. Sept. Okt. Nov. Dez.".split(),  # noqa: SIM905
}


def fmt_number(value: float, decimals: int, lang: str) -> str:
    """Format with the locale's thousands and decimal separators."""
    text = f"{value:,.{decimals}f}"
    if lang == "fr":
        return text.replace(",", " ").replace(".", ",")
    if lang == "de":
        return text.replace(",", "§").replace(".", ",").replace("§", ".")
    return text


def fmt_eur(value: float, lang: str = "en") -> str:
    """Format euros with a readable unit: '16.25 bn €', '16,25 Mrd. €', '967.0 M€'."""
    a = abs(value)
    if a >= 1e9:
        return f"{fmt_number(value / 1e9, 2, lang)} {_UNITS['bn'][lang]}"
    if a >= 1e6:
        return f"{fmt_number(value / 1e6, 1, lang)} {_UNITS['m'][lang]}"
    return f"{fmt_number(value / 1e3, 0, lang)} {_UNITS['k'][lang]}"


def fmt_pct(value: float, lang: str = "en", decimals: int = 1, signed: bool = False) -> str:
    """Format a percentage: '24.6 %' / '24,6 %', optionally with a sign."""
    text = fmt_number(abs(value) if signed else value, decimals, lang)
    if signed:
        text = ("+" if value >= 0 else "−") + text
    return f"{text} %"


def fmt_period(period: object, lang: str = "en") -> str:
    """Format a year (int) or month (date/Timestamp) for display."""
    if isinstance(period, int | float):
        return str(int(period))
    if isinstance(period, date):
        return f"{MONTHS[lang][period.month - 1]} {period.year}"
    return str(period)


def flow_label(flow: str, lang: str = "en") -> str:
    """Localised flow name."""
    return FLOW_LABELS.get(flow, {}).get(lang, flow)


def month_name(month: int, lang: str = "en") -> str:
    """Localised short month name."""
    return MONTHS[lang][month - 1]
