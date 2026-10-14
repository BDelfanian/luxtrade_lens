"""Static nomenclature reference: HS sections, chapter/heading labels and partner labels (EN/FR/DE).

HS sections and the chapter → section mapping are part of the HS nomenclature itself.
Chapter, heading and partner labels below are a **placeholder subset** used until the Eurostat
code lists in EN/FR/DE are wired into the real pipeline (DATA_CARD §6, open point).
"""

from luxtrade.config import EU27_2020, SPECIAL_PARTNERS

# section code → (roman, label_en, label_fr, label_de)
SECTIONS: dict[str, tuple[str, str, str, str]] = {
    "01": (
        "I",
        "Live animals; animal products",
        "Animaux vivants et produits du règne animal",
        "Lebende Tiere und Waren tierischen Ursprungs",
    ),
    "02": ("II", "Vegetable products", "Produits du règne végétal", "Waren pflanzlichen Ursprungs"),
    "03": (
        "III",
        "Animal or vegetable fats and oils",
        "Graisses et huiles animales ou végétales",
        "Tierische und pflanzliche Fette und Öle",
    ),
    "04": (
        "IV",
        "Prepared foodstuffs; beverages; tobacco",
        "Produits des industries alimentaires ; boissons ; tabacs",
        "Waren der Lebensmittelindustrie; Getränke; Tabak",
    ),
    "05": ("V", "Mineral products", "Produits minéraux", "Mineralische Stoffe"),
    "06": (
        "VI",
        "Products of the chemical industries",
        "Produits des industries chimiques",
        "Erzeugnisse der chemischen Industrie",
    ),
    "07": (
        "VII",
        "Plastics and rubber",
        "Matières plastiques et caoutchouc",
        "Kunststoffe und Kautschuk",
    ),
    "08": ("VIII", "Hides, skins and leather", "Peaux et cuirs", "Häute, Felle und Leder"),
    "09": ("IX", "Wood and articles of wood", "Bois et ouvrages en bois", "Holz und Holzwaren"),
    "10": (
        "X",
        "Pulp, paper and paperboard",
        "Pâtes de bois, papier et carton",
        "Halbstoffe, Papier und Pappe",
    ),
    "11": ("XI", "Textiles", "Matières textiles", "Spinnstoffe und Waren daraus"),
    "12": ("XII", "Footwear and headgear", "Chaussures et coiffures", "Schuhe und Kopfbedeckungen"),
    "13": (
        "XIII",
        "Stone, ceramic and glass",
        "Ouvrages en pierres, céramique et verre",
        "Waren aus Steinen, Keramik und Glas",
    ),
    "14": (
        "XIV",
        "Pearls and precious metals",
        "Perles et métaux précieux",
        "Perlen und Edelmetalle",
    ),
    "15": ("XV", "Base metals", "Métaux communs", "Unedle Metalle"),
    "16": (
        "XVI",
        "Machinery and electrical equipment",
        "Machines et appareils électriques",
        "Maschinen und elektrotechnische Waren",
    ),
    "17": ("XVII", "Transport equipment", "Matériel de transport", "Beförderungsmittel"),
    "18": (
        "XVIII",
        "Optical and precision instruments",
        "Instruments d'optique et de précision",
        "Optische und Präzisionsinstrumente",
    ),
    "19": ("XIX", "Arms and ammunition", "Armes et munitions", "Waffen und Munition"),
    "20": (
        "XX",
        "Miscellaneous manufactured articles",
        "Marchandises et produits divers",
        "Verschiedene Waren",
    ),
    "21": ("XXI", "Works of art", "Objets d'art", "Kunstgegenstände"),
    "XX": (
        "—",
        "Undisclosed (confidential)",
        "Non divulgué (confidentiel)",
        "Nicht offengelegt (vertraulich)",
    ),
}

# (first chapter, last chapter, section) — HS nomenclature
_SECTION_RANGES = [
    (1, 5, "01"),
    (6, 14, "02"),
    (15, 15, "03"),
    (16, 24, "04"),
    (25, 27, "05"),
    (28, 38, "06"),
    (39, 40, "07"),
    (41, 43, "08"),
    (44, 46, "09"),
    (47, 49, "10"),
    (50, 63, "11"),
    (64, 67, "12"),
    (68, 70, "13"),
    (71, 71, "14"),
    (72, 83, "15"),
    (84, 85, "16"),
    (86, 89, "17"),
    (90, 92, "18"),
    (93, 93, "19"),
    (94, 96, "20"),
    (97, 97, "21"),
]


def section_of(hs2: str) -> str:
    """Return the HS section code ('01'–'21') of an HS2 chapter, or 'XX' if undisclosed."""
    if not hs2.isdigit():
        return "XX"
    chapter = int(hs2)
    for first, last, section in _SECTION_RANGES:
        if first <= chapter <= last:
            return section
    return "XX"


# HS2 chapter → (label_en, label_fr, label_de)
CHAPTERS: dict[str, tuple[str, str, str]] = {
    "04": (
        "Dairy produce; eggs; honey",
        "Lait et produits de la laiterie ; œufs ; miel",
        "Milch und Milcherzeugnisse; Eier; Honig",
    ),
    "22": (
        "Beverages, spirits and vinegar",
        "Boissons, liquides alcooliques et vinaigres",
        "Getränke, alkoholische Flüssigkeiten und Essig",
    ),
    "27": (
        "Mineral fuels and oils",
        "Combustibles et huiles minéraux",
        "Mineralische Brennstoffe und Mineralöle",
    ),
    "29": (
        "Organic chemicals",
        "Produits chimiques organiques",
        "Organische chemische Erzeugnisse",
    ),
    "30": ("Pharmaceutical products", "Produits pharmaceutiques", "Pharmazeutische Erzeugnisse"),
    "38": (
        "Miscellaneous chemical products",
        "Produits divers des industries chimiques",
        "Verschiedene Erzeugnisse der chemischen Industrie",
    ),
    "39": (
        "Plastics and articles thereof",
        "Matières plastiques et ouvrages en ces matières",
        "Kunststoffe und Waren daraus",
    ),
    "40": (
        "Rubber and articles thereof",
        "Caoutchouc et ouvrages en caoutchouc",
        "Kautschuk und Waren daraus",
    ),
    "48": ("Paper and paperboard", "Papiers et cartons", "Papier und Pappe"),
    "56": (
        "Wadding, felt and nonwovens",
        "Ouates, feutres et nontissés",
        "Watte, Filze und Vliesstoffe",
    ),
    "64": ("Footwear", "Chaussures", "Schuhe"),
    "70": ("Glass and glassware", "Verre et ouvrages en verre", "Glas und Glaswaren"),
    "72": ("Iron and steel", "Fonte, fer et acier", "Eisen und Stahl"),
    "73": (
        "Articles of iron or steel",
        "Ouvrages en fonte, fer ou acier",
        "Waren aus Eisen oder Stahl",
    ),
    "76": (
        "Aluminium and articles thereof",
        "Aluminium et ouvrages en aluminium",
        "Aluminium und Waren daraus",
    ),
    "84": (
        "Machinery and mechanical appliances",
        "Machines et appareils mécaniques",
        "Maschinen und mechanische Geräte",
    ),
    "85": (
        "Electrical machinery and equipment",
        "Machines et appareils électriques",
        "Elektrische Maschinen und Geräte",
    ),
    "87": (
        "Vehicles and parts",
        "Voitures automobiles et leurs parties",
        "Kraftfahrzeuge und Teile davon",
    ),
    "90": (
        "Optical, measuring and medical instruments",
        "Instruments d'optique, de mesure et médicaux",
        "Optische, Mess- und medizinische Instrumente",
    ),
    "94": (
        "Furniture, bedding and lamps",
        "Meubles, literie et luminaires",
        "Möbel, Bettwaren und Leuchten",
    ),
    "99": (
        "Undisclosed (confidential)",
        "Non divulgué (confidentiel)",
        "Nicht offengelegt (vertraulich)",
    ),
}

# HS4 heading → (label_en, label_fr, label_de)
HEADINGS: dict[str, tuple[str, str, str]] = {
    "0401": ("Milk and cream", "Lait et crème", "Milch und Rahm"),
    "0406": ("Cheese", "Fromages", "Käse"),
    "2203": ("Beer", "Bières", "Bier"),
    "2204": ("Wine", "Vins", "Wein"),
    "2710": ("Petroleum oils", "Huiles de pétrole", "Erdöl und Öle aus bituminösen Mineralien"),
    "2711": ("Petroleum gases", "Gaz de pétrole", "Erdgas"),
    "2933": ("Heterocyclic compounds", "Composés hétérocycliques", "Heterocyclische Verbindungen"),
    "3004": ("Medicaments", "Médicaments", "Arzneiwaren"),
    "3824": ("Chemical preparations", "Préparations chimiques", "Chemische Zubereitungen"),
    "3901": ("Polymers of ethylene", "Polymères de l'éthylène", "Polymere des Ethylens"),
    "3920": (
        "Plates and sheets of plastics",
        "Plaques et feuilles en plastique",
        "Platten und Folien aus Kunststoff",
    ),
    "4011": ("New tyres", "Pneumatiques neufs", "Neue Reifen"),
    "4016": (
        "Other articles of rubber",
        "Autres ouvrages en caoutchouc",
        "Andere Waren aus Kautschuk",
    ),
    "4810": ("Coated paper", "Papiers couchés", "Gestrichenes Papier"),
    "5603": ("Nonwovens", "Nontissés", "Vliesstoffe"),
    "6403": ("Leather footwear", "Chaussures en cuir", "Lederschuhe"),
    "7007": ("Safety glass", "Verre de sécurité", "Sicherheitsglas"),
    "7208": (
        "Hot-rolled flat steel",
        "Produits plats laminés à chaud",
        "Warmgewalzte Flacherzeugnisse",
    ),
    "7216": ("Steel angles and sections", "Profilés en acier", "Profile aus Stahl"),
    "7308": ("Steel structures", "Constructions en acier", "Konstruktionen aus Stahl"),
    "7318": ("Screws and bolts", "Vis et boulons", "Schrauben und Bolzen"),
    "7606": ("Aluminium plates", "Tôles en aluminium", "Bleche aus Aluminium"),
    "8428": (
        "Lifting and handling machinery",
        "Machines de levage et de manutention",
        "Hebe- und Fördermaschinen",
    ),
    "8471": ("Computers", "Ordinateurs", "Datenverarbeitungsmaschinen"),
    "8481": ("Taps and valves", "Robinets et vannes", "Armaturen und Ventile"),
    "8517": ("Telephone sets", "Postes téléphoniques", "Telefonapparate"),
    "8536": ("Electrical switches", "Appareils de coupure électrique", "Elektrische Schalter"),
    "8544": ("Insulated wire and cables", "Fils et câbles isolés", "Isolierte Drähte und Kabel"),
    "8703": ("Motor cars", "Voitures de tourisme", "Personenkraftwagen"),
    "8704": ("Goods vehicles (trucks)", "Véhicules de transport de marchandises", "Lastkraftwagen"),
    "8708": (
        "Parts of motor vehicles",
        "Parties de véhicules automobiles",
        "Teile für Kraftfahrzeuge",
    ),
    "9018": ("Medical instruments", "Instruments médicaux", "Medizinische Instrumente"),
    "9403": ("Other furniture", "Autres meubles", "Andere Möbel"),
}

# partner → (iso3, label_en, label_fr, label_de); iso3 is None for special codes (never mapped)
PARTNERS: dict[str, tuple[str | None, str, str, str]] = {
    "DE": ("DEU", "Germany", "Allemagne", "Deutschland"),
    "FR": ("FRA", "France", "France", "Frankreich"),
    "BE": ("BEL", "Belgium", "Belgique", "Belgien"),
    "NL": ("NLD", "Netherlands", "Pays-Bas", "Niederlande"),
    "IT": ("ITA", "Italy", "Italie", "Italien"),
    "ES": ("ESP", "Spain", "Espagne", "Spanien"),
    "AT": ("AUT", "Austria", "Autriche", "Österreich"),
    "PL": ("POL", "Poland", "Pologne", "Polen"),
    "PT": ("PRT", "Portugal", "Portugal", "Portugal"),
    "SE": ("SWE", "Sweden", "Suède", "Schweden"),
    "CZ": ("CZE", "Czechia", "Tchéquie", "Tschechien"),
    "DK": ("DNK", "Denmark", "Danemark", "Dänemark"),
    "IE": ("IRL", "Ireland", "Irlande", "Irland"),
    "GR": ("GRC", "Greece", "Grèce", "Griechenland"),
    "GB": ("GBR", "United Kingdom", "Royaume-Uni", "Vereinigtes Königreich"),
    "CH": ("CHE", "Switzerland", "Suisse", "Schweiz"),
    "US": ("USA", "United States", "États-Unis", "Vereinigte Staaten"),
    "CN": ("CHN", "China", "Chine", "China"),
    "JP": ("JPN", "Japan", "Japon", "Japan"),
    "IN": ("IND", "India", "Inde", "Indien"),
    "KR": ("KOR", "South Korea", "Corée du Sud", "Südkorea"),
    "TR": ("TUR", "Türkiye", "Turquie", "Türkei"),
    "BR": ("BRA", "Brazil", "Brésil", "Brasilien"),
    "CA": ("CAN", "Canada", "Canada", "Kanada"),
    "QV": (
        None,
        "Not specified (intra-EU)",
        "Non spécifié (intra-UE)",
        "Nicht ermittelt (Intra-EU)",
    ),
    "QY": (
        None,
        "Not specified, commercial or military reasons (intra-EU)",
        "Non spécifié, raisons commerciales ou militaires (intra-UE)",
        "Nicht ermittelt, aus kommerziellen oder militärischen Gründen (Intra-EU)",
    ),
    "QZ": (
        None,
        "Not specified, commercial or military reasons (extra-EU)",
        "Non spécifié, raisons commerciales ou militaires (extra-UE)",
        "Nicht ermittelt, aus kommerziellen oder militärischen Gründen (Extra-EU)",
    ),
}

# Accession dates for the actual TRADE_TYPE (intra/extra) at the time of trade
EU_JOINED: dict[str, str] = {"PL": "2004-05", "CZ": "2004-05"}
EU_LEFT: dict[str, str] = {"GB": "2021-01"}
INTRA_SPECIAL = frozenset({"QV", "QY"})


def is_special(partner: str) -> bool:
    """Return True for Eurostat special partner codes (explicit list, DATA_CARD §4.2b)."""
    return partner in SPECIAL_PARTNERS


def is_eu27_2020(partner: str) -> bool:
    """Return True if the partner belongs to the fixed EU27 (2020) composition."""
    return partner in EU27_2020
