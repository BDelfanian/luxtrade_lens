from datetime import date

import pytest

from luxtrade.semantic.layer import QueryError


def test_coverage_finds_latest_complete_month(semantic):
    cov = semantic.coverage
    assert cov.latest_complete_period == date(2025, 12, 1)
    assert cov.latest_period == date(2026, 7, 1)
    assert cov.latest_complete_year == 2025
    assert cov.is_placeholder


def test_connection_is_read_only(semantic):
    with pytest.raises(QueryError):
        semantic.query("CREATE TABLE hack AS SELECT 1")


def test_external_file_access_is_disabled(semantic):
    # even without the SQL guard, the database itself refuses to read files
    with pytest.raises(QueryError):
        semantic.query("SELECT * FROM read_csv('pyproject.toml')")


def test_configuration_is_locked(semantic):
    with pytest.raises(QueryError):
        semantic.query("SET enable_external_access = true")


def test_labels_in_three_languages(semantic):
    assert semantic.label("DE", "partner", "fr") == "Allemagne"
    assert semantic.label("DE", "partner", "de") == "Deutschland"
    assert semantic.label("84", "product", "de").startswith("Maschinen")
    assert semantic.label("UNDISCLOSED", "partner", "en").startswith("Undisclosed")


@pytest.mark.parametrize(
    ("question", "kind", "code"),
    [
        ("Quels produits importons-nous d'Allemagne ?", "partner", "DE"),
        ("Exporte nach Frankreich", "partner", "FR"),
        ("exports of cars", "product", "8703"),
        ("Wie entwickeln sich die Exporte von Maschinen (HS 84)?", "product", "84"),
        ("trade with the US", "partner", "US"),
        ("French imports", "partner", "FR"),
        ("trade with the EU", "group", "EU27_2020"),
    ],
)
def test_lookup_resolves_multilingual_entities(index, question, kind, code):
    found = {(c.kind, c.code) for c in index.find(question)}
    assert (kind, code) in found


def test_lookup_ignores_years_and_generic_words(index):
    found = index.find("main products in 2024")
    assert all(c.code != "2024" for c in found)
    assert not [c for c in found if c.kind == "product"]
