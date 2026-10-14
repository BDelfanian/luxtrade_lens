"""View catalogue: the only tables agents may query, with one-line descriptions for the LLM.

View and column names are part of the data contract (GUIDELINES §1.3): prompts, SQL templates
and the SQL guard whitelist all depend on them.
"""

VIEWS: dict[str, tuple[str, list[tuple[str, str, str]]]] = {
    "v_lu_trade": (
        "Luxembourg's monthly trade in goods at full detail: one row per partner × CN8 product × flow × month.",
        [
            ("period", "DATE", "first day of the month"),
            ("year", "INT", "calendar year"),
            ("month", "INT", "month 1–12"),
            ("partner", "VARCHAR", "partner country ISO-2 code; Q* codes are undisclosed partners"),
            ("trade_type", "VARCHAR", "'intra' (EU at the time) or 'extra'"),
            ("flow", "VARCHAR", "'import' or 'export'"),
            (
                "cn8",
                "VARCHAR",
                "CN8 product code as text; masked codes like '27XXXXXX' are confidential",
            ),
            ("hs2", "VARCHAR", "HS2 chapter (first 2 characters)"),
            ("hs4", "VARCHAR", "HS4 heading (first 4 characters)"),
            ("hs6", "VARCHAR", "HS6 subheading (first 6 characters)"),
            ("section", "VARCHAR", "HS section '01'–'21'; 'XX' undisclosed"),
            ("is_confidential", "BOOLEAN", "masked confidential product code"),
            ("partner_is_special", "BOOLEAN", "undisclosed/unspecified partner (Q* codes)"),
            ("partner_is_eu27_2020", "BOOLEAN", "partner in the fixed EU27 (2020) composition"),
            ("value_eur", "DOUBLE", "trade value in euros, current prices"),
            ("qty_kg", "DOUBLE", "net mass in kg; NULL when unknown"),
        ],
    ),
    "v_lu_trade_hs2": (
        "Same as v_lu_trade aggregated to HS2 chapters (faster for long series).",
        [
            ("period", "DATE", ""),
            ("year", "INT", ""),
            ("month", "INT", ""),
            ("partner", "VARCHAR", ""),
            ("trade_type", "VARCHAR", ""),
            ("flow", "VARCHAR", ""),
            ("hs2", "VARCHAR", ""),
            ("section", "VARCHAR", ""),
            ("partner_is_special", "BOOLEAN", ""),
            ("partner_is_eu27_2020", "BOOLEAN", ""),
            ("value_eur", "DOUBLE", ""),
            ("qty_kg", "DOUBLE", ""),
            ("confidential_value_eur", "DOUBLE", "part of value_eur from masked product codes"),
        ],
    ),
    "v_eu_reporters_hs2": (
        "Monthly trade of EU reporters (LU, BE, NL, DE, FR, AT) by HS2, all partners summed.",
        [
            ("reporter", "VARCHAR", "reporting country ISO-2"),
            ("period", "DATE", ""),
            ("year", "INT", ""),
            ("month", "INT", ""),
            ("trade_type", "VARCHAR", ""),
            ("flow", "VARCHAR", ""),
            ("hs2", "VARCHAR", ""),
            ("value_eur", "DOUBLE", ""),
        ],
    ),
    "dim_product": (
        "Product codes at levels 2/4/6/8 with parent and labels in EN/FR/DE.",
        [
            ("product", "VARCHAR", ""),
            ("level", "INT", "2, 4, 6 or 8 digits"),
            ("parent", "VARCHAR", ""),
            ("label_en", "VARCHAR", ""),
            ("label_fr", "VARCHAR", ""),
            ("label_de", "VARCHAR", ""),
            ("section", "VARCHAR", ""),
            ("is_confidential", "BOOLEAN", ""),
        ],
    ),
    "dim_partner": (
        "Partner codes with ISO-3 and labels in EN/FR/DE.",
        [
            ("partner", "VARCHAR", ""),
            ("iso3", "VARCHAR", "NULL for special codes"),
            ("label_en", "VARCHAR", ""),
            ("label_fr", "VARCHAR", ""),
            ("label_de", "VARCHAR", ""),
            ("is_eu27_2020", "BOOLEAN", ""),
            ("is_special", "BOOLEAN", ""),
        ],
    ),
    "dim_section": (
        "HS sections with roman numerals and labels in EN/FR/DE.",
        [
            ("section", "VARCHAR", ""),
            ("roman", "VARCHAR", ""),
            ("label_en", "VARCHAR", ""),
            ("label_fr", "VARCHAR", ""),
            ("label_de", "VARCHAR", ""),
        ],
    ),
    "meta_coverage": (
        "One row: first period, latest complete month (intra + extra), latest month, extraction date.",
        [
            ("first_period", "DATE", ""),
            ("latest_complete_period", "DATE", ""),
            ("latest_period", "DATE", ""),
            ("extraction_date", "VARCHAR", ""),
            ("is_placeholder", "BOOLEAN", ""),
            ("source", "VARCHAR", ""),
        ],
    ),
}

ALLOWED_VIEWS = frozenset(VIEWS)


def catalog_text() -> str:
    """Render the catalogue as compact text for LLM prompts."""
    lines = []
    for view, (description, columns) in VIEWS.items():
        lines.append(f"{view}: {description}")
        for name, dtype, note in columns:
            lines.append(f"  - {name} {dtype}" + (f": {note}" if note else ""))
    return "\n".join(lines)
