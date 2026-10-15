"""Tiny synthetic Comext bulk archives and code lists (same format as the real files)."""

import py7zr
import pytest

HEADER = (
    "REPORTER,PARTNER,TRADE_TYPE,PRODUCT_NC,PRODUCT_SITC,PRODUCT_CPA21,PRODUCT_CPA22,PRODUCT_BEC,"
    "PRODUCT_BEC5,PRODUCT_SECTION,FLOW,STAT_PROCEDURE,SUPPL_UNIT,PERIOD,VALUE_EUR,VALUE_NAC,"
    "QUANTITY_KG,QUANTITY_SUPPL_UNIT"
)


_TOTAL_ATTRS = "TOTAL,TOTAL,TOTAL,TOTAL,TOTAL,TO"
_CN8_ATTRS = "02491,1051,1051,122,.....,01"  # SITC, CPA21, CPA22, BEC, BEC5 (old '.....'), section


def _row(rep, partner, tt, product, flow, sp, period, value, kg):
    attrs = _TOTAL_ATTRS if product == "TOTAL" else _CN8_ATTRS
    tail = f"NO_SU,{period},{value},{value},{kg},0"
    return f"{rep},{partner},{tt},{product},{attrs},{flow},{sp},{tail}"


def month_rows(period: str, intra: bool = True) -> list[str]:
    """LU detail + TOTAL rows for one month; QY trade sits under DE in the TOTAL (as in Comext)."""
    rows = [
        _row("LU", "US", "E", "04061000", "2", "1", period, 100, 10),
        _row("LU", "US", "E", "TOTAL", "2", "1", period, 100, 10),
        _row("BE", "US", "E", "04061000", "2", "1", period, 900, 90),
    ]
    if intra:
        rows += [
            # same key twice (two statistical procedures): summed; one quantity unknown (0)
            _row("LU", "DE", "I", "04061000", "1", "1", period, 1000, 50),
            _row("LU", "DE", "I", "04061000", "1", "2", period, 500, 0),
            _row("LU", "DE", "I", "27XXXXXX", "1", "1", period, 300, 30),
            _row("LU", "QY", "I", "99XXXXXX", "1", "1", period, 200, 20),
            _row("LU", "DE", "I", "TOTAL", "1", "1", period, 2000, 100),
            _row("BE", "DE", "I", "27101943", "1", "1", period, 5000, 500),
        ]
    return rows


def write_archive(path, period: str, intra: bool = True) -> None:
    """Write ``full_v2_YYYYMM.7z`` holding ``full_YYYYMM.dat``."""
    dat = path.parent / f"full_{period}.dat"
    dat.write_text("\n".join([HEADER, *month_rows(period, intra)]) + "\n", encoding="utf-8")
    with py7zr.SevenZipFile(path, "w") as z:
        z.write(dat, arcname=dat.name)
    dat.unlink()


_CN = {
    "en": [
        ("04", "DAIRY PRODUCE"),
        ("0406", "Cheese and curd"),
        ("040610", "Fresh cheese"),
        ("04061000", "Fresh cheese, incl. whey cheese"),
        ("27", "MINERAL FUELS"),
        ("99", "Other products"),
    ],
    "fr": [
        ("04", "LAIT ET PRODUITS DE LA LAITERIE"),
        ("0406", "Fromages et caillebotte"),
        ("040610", "Fromages frais"),
        ("04061000", "Fromages frais, y.c. de lactosérum"),
        ("27", "COMBUSTIBLES MINERAUX"),
        ("99", "Produits divers"),
    ],
    "de": [
        ("04", "MILCH UND MILCHERZEUGNISSE"),
        ("0406", "Käse und Quark"),
        ("040610", "Frischkäse"),
        ("04061000", "Frischkäse, einschl. Molkenkäse"),
        ("27", "MINERALISCHE BRENNSTOFFE"),
        ("99", "Verschiedenes"),
    ],
}
_PARTNERS = {
    "en": [("DE", "Germany"), ("US", "United States"), ("QY", "Secret intra")],
    "fr": [("DE", "Allemagne"), ("US", "Etats-Unis"), ("QY", "Secret intra")],
    "de": [("DE", "Deutschland"), ("US", "Vereinigte Staaten"), ("QY", "Geheim intra")],
}


def write_codelists(raw_dir) -> None:
    """Write CN.txt and PARTNERS_ISO.txt per language (with an old label and a malformed line)."""
    for lang in ("en", "fr", "de"):
        folder = raw_dir / "codelists" / lang
        folder.mkdir(parents=True, exist_ok=True)
        cn = [f"{c}\t01/01/1988\t31/12/2500\t{lab}" for c, lab in _CN[lang]]
        cn.insert(0, "04061000\t01/01/1988\t31/12/1999\tOld wording")
        cn.append('290891\t01/01/2007\t31/12/2500\t"Dinosèbe\t01/01/2007\t31/12/2500"')
        (folder / "CN.txt").write_text("\n".join(cn) + "\n", encoding="utf-8")
        partners = [f"{c}\t01/01/1976\t31/12/2500\t{lab}  " for c, lab in _PARTNERS[lang]]
        (folder / "PARTNERS_ISO.txt").write_text("\r\n".join(partners) + "\r\n", encoding="utf-8")


@pytest.fixture
def bulk_raw(tmp_path):
    """A raw folder with two monthly archives (Jan 2026 extra-EU only) and code lists."""
    raw = tmp_path / "raw"
    (raw / "bulk").mkdir(parents=True)
    write_archive(raw / "bulk" / "full_v2_202512.7z", "202512")
    write_archive(raw / "bulk" / "full_v2_202601.7z", "202601", intra=False)
    write_codelists(raw)
    return raw
