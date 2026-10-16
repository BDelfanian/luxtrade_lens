"""Key findings: the Overview's story tab, written for decision-makers (SOLUTION_DESIGN §8a).

Five findings and a conclusion on resilience: how diversified trade is, how it absorbed the
crises and where it depends on one route, how European it has become, and what a kilogram of
imports is worth inside and outside the EU. Same rules as the overview panels: every number
comes from guarded SQL on the semantic views (shown as evidence), every sentence is a fixed
template filled with those numbers. No LLM.
"""

from dataclasses import dataclass, field

import pandas as pd

from luxtrade.agents import guard
from luxtrade.agents.presets import preset
from luxtrade.agents.spec import QuerySpec
from luxtrade.agents.sql_guard import check_sql
from luxtrade.semantic.layer import SemanticLayer
from luxtrade.viz.format import flow_label, fmt_eur, fmt_number, fmt_pct

SNAPSHOT_SPAN, SNAPSHOT_STEP = 20, 5  # 2005, 2010, …, 2025: one point every five years
NEIGHBOURS = ("BE", "DE", "FR")
# Non-EU partners whose weight changed most, each in the flow where it matters
WATCH = (("CN", "import"), ("JP", "import"), ("US", "import"), ("GB", "export"))
ENERGY = "27"  # HS chapter: mineral fuels and oils
ENERGY_SHOCK = 2022
MIN_SHARE = 2.0  # % of exports: smaller chapters are left out of the crisis ranking
# Crisis episodes, reading aids rather than data: (key, last year before, year of the fall)
EPISODES = (("gfc", 2008, 2009), ("covid", 2019, 2020), ("energy", 2022, 2023))
HHI_MODERATE, HHI_HIGH = 1_000, 1_800  # US Merger Guidelines (2023) thresholds
# EU partner rule of the query compiler: undisclosed intra-EU partners count as EU
_EU = "partner_is_eu27_2020 OR (partner_is_special AND trade_type = 'intra')"

_T = {
    "intro": {
        "en": "**When the next shock hits, which goods and which supply routes should Luxembourg watch first?** Five findings from the data and a conclusion. Open each one for its charts, queries and method.",
        "fr": "**Quand le prochain choc surviendra, quels biens et quelles routes d'approvisionnement le Luxembourg doit-il surveiller en priorité ?** Cinq constats tirés des données et une conclusion. Ouvrez chacun pour voir ses graphiques, ses requêtes et sa méthode.",
        "de": "**Welche Waren und welche Versorgungswege sollte Luxemburg beim nächsten Schock zuerst im Blick haben?** Fünf Befunde aus den Daten und ein Fazit. Öffnen Sie jeden für Grafiken, Abfragen und Methode.",
    },
    # the story in one line, and its plain fallback when the data stops supporting it
    "hero": {
        "en": "Luxembourg diversified what it sells, not whom it depends on",
        "fr": "Le Luxembourg a diversifié ce qu'il vend, pas ceux dont il dépend",
        "de": "Luxemburg hat breiter gestreut, was es verkauft – nicht, von wem es abhängt",
    },
    "hero_n": {
        "en": "Luxembourg's trade in goods: four findings for the next shock",
        "fr": "Le commerce de biens du Luxembourg : quatre constats pour le prochain choc",
        "de": "Luxemburgs Warenhandel: vier Befunde für den nächsten Schock",
    },
    # engaging headlines (each only when the data supports it), with neutral fallbacks
    "h_div": {
        "en": "Eggs in more baskets, but bought from the same three neighbours",
        "fr": "Plus de paniers pour nos œufs, mais toujours les trois mêmes voisins",
        "de": "Die Eier in mehr Körben – aber von denselben drei Nachbarn",
    },
    "h_div_n": {
        "en": "How spread out is Luxembourg's trade?",
        "fr": "Le commerce du Luxembourg est-il diversifié ?",
        "de": "Wie breit ist Luxemburgs Handel aufgestellt?",
    },
    "h_shock": {
        "en": "{name}: first to fall, every time",
        "fr": "{name} : le premier à tomber, à chaque fois",
        "de": "{name}: fällt zuerst, jedes Mal",
    },
    "h_shock_n": {
        "en": "Which goods break first in a crisis?",
        "fr": "Quels biens cèdent en premier lors d'une crise ?",
        "de": "Welche Waren brechen in einer Krise zuerst ein?",
    },
    "h_eu": {
        "en": "Less China, more Europe",
        "fr": "Moins de Chine, plus d'Europe",
        "de": "Weniger China, mehr Europa",
    },
    "h_eu_n": {
        "en": "Is Luxembourg's trade becoming more European?",
        "fr": "Le commerce du Luxembourg devient-il plus européen ?",
        "de": "Wird Luxemburgs Handel europäischer?",
    },
    "h_price": {
        "en": "One kilo from outside the EU is worth {ratio} kilos from inside",
        "fr": "Un kilo venu de hors UE vaut {ratio} kilos venus de l'UE",
        "de": "Ein Kilo von außerhalb der EU wiegt {ratio} Kilo aus der EU auf",
    },
    "h_price_n": {
        "en": "What is a kilo of imports worth?",
        "fr": "Que vaut un kilo d'importations ?",
        "de": "Was ist ein Kilo Import wert?",
    },
    "h_end": {
        "en": "Resilient, but exposed: three things to watch",
        "fr": "Résilient, mais exposé : trois points à surveiller",
        "de": "Widerstandsfähig, aber verwundbar: drei Punkte im Blick",
    },
    # the three things to watch (conclusion tiles)
    "w_weak": {
        "en": "Exports fell in all {n} crises since {first}.",
        "fr": "Exportations en baisse lors des {n} crises depuis {first}.",
        "de": "Die Exporte fielen in allen {n} Krisen seit {first}.",
    },
    "w_weak_n": {
        "en": "Largest fall in a crisis: {chg}.",
        "fr": "Plus forte baisse lors d'une crise : {chg}.",
        "de": "Stärkster Rückgang in einer Krise: {chg}.",
    },
    "w_routes": {
        "en": "Neighbour routes",
        "fr": "Routes des pays voisins",
        "de": "Wege über die Nachbarn",
    },
    "w_routes_t": {
        "en": "{nb} of imports come from three neighbours: {names}.",
        "fr": "{nb} des importations viennent de trois voisins : {names}.",
        "de": "{nb} der Importe kommen aus drei Nachbarländern: {names}.",
    },
    "w_fuel": {"en": "Fuel prices", "fr": "Prix des carburants", "de": "Brennstoffpreise"},
    "w_fuel_t": {
        "en": "Largest fuel supplier: {top}, with {share} of imports.",
        "fr": "Premier fournisseur de carburants : {top}, avec {share} des importations.",
        "de": "Größter Brennstofflieferant: {top}, mit {share} der Importe.",
    },
    "w_fuel_p": {
        "en": "In {y}, the price per kg rose by {p}.",
        "fr": "En {y}, le prix par kg a augmenté de {p}.",
        "de": "{y} stieg der Preis je kg um {p}.",
    },
    # "why it matters": the analysis paragraph on each card
    "why": {
        "en": "**Why it matters.**",
        "fr": "**Pourquoi c'est important.**",
        "de": "**Warum das wichtig ist.**",
    },
    "a_div": {
        "en": "Spreading exports over more products cushions a shock in any one sector: the two largest export chapters of {y0} went from {s0} to {s1} of exports. But {nb} of imports now come from three neighbours ({names}), so a disruption at one border would reach most supplies at once.",
        "fr": "Répartir les exportations sur davantage de produits amortit un choc dans un secteur : les deux premiers chapitres à l'exportation de {y0} sont passés de {s0} à {s1} des exportations. Mais {nb} des importations viennent désormais de trois voisins ({names}) : une perturbation à une frontière toucherait la plupart des approvisionnements à la fois.",
        "de": "Mehr Warenvielfalt im Export federt einen Schock in einer Branche ab: Die zwei größten Exportkapitel von {y0} veränderten sich von {s0} auf {s1} der Exporte. Doch {nb} der Importe kommen heute aus drei Nachbarländern ({names}) – eine Störung an einer Grenze träfe den Großteil der Versorgung auf einmal.",
    },
    "a_shock": {
        "en": "Across the {n} crises, {name} fell on average {ratio} times as far as all exports ({w} against {a}).",
        "fr": "Sur les {n} crises, {name} a reculé en moyenne {ratio} fois plus que l'ensemble des exportations ({w} contre {a}).",
        "de": "Über die {n} Krisen fiel {name} im Schnitt {ratio}-mal so stark wie alle Exporte ({w} gegenüber {a}).",
    },
    "a_shock_lag": {
        "en": "Its {ylag} fall came one year after the {yshock} energy price shock, when fuel cost {p} more per kilo.",
        "fr": "Sa baisse de {ylag} est survenue un an après le choc des prix de l'énergie de {yshock}, quand le carburant coûtait {p} de plus par kilo.",
        "de": "Der Rückgang von {ylag} kam ein Jahr nach dem Energiepreisschock von {yshock}, als Brennstoff je Kilo {p} mehr kostete.",
    },
    "a_eu": {
        "en": "With {eu1} of imports from EU countries, the single market (open borders, cross-border transport, common rules) is Luxembourg's main supply line.",
        "fr": "Avec {eu1} des importations venant de l'UE, le marché unique (frontières ouvertes, transport transfrontalier, règles communes) est la principale ligne d'approvisionnement du Luxembourg.",
        "de": "Mit {eu1} der Importe aus EU-Ländern ist der Binnenmarkt (offene Grenzen, grenzüberschreitender Verkehr, gemeinsame Regeln) Luxemburgs wichtigste Versorgungslinie.",
    },
    "a_eu_swap": {
        "en": "Outside the EU, partners changed places: China went from {c0} to {c1} of imports, Japan from {j0} to {j1}.",
        "fr": "Hors UE, les partenaires ont changé de place : la Chine est passée de {c0} à {c1} des importations, le Japon de {j0} à {j1}.",
        "de": "Außerhalb der EU haben die Partner die Plätze getauscht: China ging von {c0} auf {c1} der Importe, Japan von {j0} auf {j1}.",
    },
    "a_price": {
        "en": "Imports from EU partners are heavy and cheap per kilo; imports from further away are light and valuable.",
        "fr": "Les importations de l'UE sont lourdes et bon marché au kilo ; celles venant de plus loin sont légères et de grande valeur.",
        "de": "Importe aus der EU sind schwer und je Kilo günstig, Importe von weiter her leicht und wertvoll.",
    },
    "a_price_fuel": {
        "en": "A price shock shows in value before mass: in {y}, fuel imports rose by {v} in value but only by {q} in mass.",
        "fr": "Un choc de prix se voit dans la valeur avant la masse : en {y}, les importations de carburants ont augmenté de {v} en valeur, mais de {q} seulement en masse.",
        "de": "Ein Preisschock zeigt sich im Wert vor der Menge: {y} stiegen die Brennstoffimporte wertmäßig um {v}, mengenmäßig nur um {q}.",
    },
    # 5. main goods over time
    "n_comp": {
        "en": "Main goods over time",
        "fr": "Principales marchandises dans le temps",
        "de": "Wichtigste Waren im Zeitverlauf",
    },
    "h_comp": {
        "en": "{name}: from {s0} of {flow} in {y0} to {s1} in {y1}",
        "fr": "{name} : de {s0} des {flow} en {y0} à {s1} en {y1}",
        "de": "{name}: von {s0} der {flow} im Jahr {y0} auf {s1} im Jahr {y1}",
    },
    "t_comp": {
        "en": "Top 3 export chapters in {y1}: {exports}. Top 3 import chapters: {imports}.",
        "fr": "Les 3 premiers chapitres à l'exportation en {y1} : {exports}. À l'importation : {imports}.",
        "de": "Die 3 größten Exportkapitel {y1}: {exports}. Die 3 größten Importkapitel: {imports}.",
    },
    "s_comp": {
        "en": "Each bar is one year. A colour is a chapter; its darkest shade is the chapter's largest heading in {y1}, the next two are lighter, and the palest is the rest of the chapter (including confidential trade). Lengths are % of all exports or imports.",
        "fr": "Chaque barre est une année. Une couleur est un chapitre ; sa teinte la plus foncée est la première position du chapitre en {y1}, les deux suivantes sont plus claires, et la plus pâle est le reste du chapitre (commerce confidentiel compris). Les longueurs sont en % du total des exportations ou des importations.",
        "de": "Jeder Balken ist ein Jahr. Eine Farbe ist ein Kapitel; der dunkelste Ton ist die größte Position des Kapitels im Jahr {y1}, die nächsten zwei sind heller, der hellste ist der Rest des Kapitels (einschließlich vertraulichem Handel). Die Längen sind % aller Exporte bzw. Importe.",
    },
    "a_comp": {
        "en": "The top three chapters made up {e0} of exports in {y0} and {e1} in {y1}; for imports, {i0} and {i1}. The fastest riser among their headings: {name}, from {s0} to {s1} of {flow}.",
        "fr": "Les trois premiers chapitres représentaient {e0} des exportations en {y0} et {e1} en {y1} ; pour les importations, {i0} et {i1}. Plus forte progression parmi leurs positions : {name}, de {s0} à {s1} des {flow}.",
        "de": "Die drei größten Kapitel machten {y0} {e0} der Exporte aus und {y1} {e1}; bei den Importen {i0} und {i1}. Am stärksten gewachsen unter ihren Positionen: {name}, von {s0} auf {s1} der {flow}.",
    },
    "m_comp": {
        "en": "{name}: share of {flow} since {y0}",
        "fr": "{name} : part des {flow} depuis {y0}",
        "de": "{name}: Anteil an den {flow} seit {y0}",
    },
    "rest_chapter": {
        "en": "rest of the chapter (incl. confidential)",
        "fr": "reste du chapitre (y c. confidentiel)",
        "de": "Rest des Kapitels (inkl. vertraulich)",
    },
    "c_comp": {
        "en": "Top 3 chapters and their top 3 headings, share of trade, {years}",
        "fr": "3 premiers chapitres et leurs 3 premières positions, part des échanges, {years}",
        "de": "3 größte Kapitel und ihre 3 größten Positionen, Anteil am Handel, {years}",
    },
    "lim_hs4": {
        "en": "HS4 headings can change when the Harmonized System is revised (2007, 2012, 2017, 2022), so a heading's long series may break. Confidential trade stays in the rest of its chapter.",
        "fr": "Les positions SH4 peuvent changer lors des révisions du Système harmonisé (2007, 2012, 2017, 2022) : la série longue d'une position peut être rompue. Le commerce confidentiel reste dans le reste de son chapitre.",
        "de": "HS4-Positionen können sich bei Revisionen des Harmonisierten Systems ändern (2007, 2012, 2017, 2022), lange Reihen einer Position können daher brechen. Vertraulicher Handel bleibt im Rest seines Kapitels.",
    },
    "x_comp": {
        "en": "How have the top 3 export chapters developed since {start}?",
        "fr": "Comment les 3 premiers chapitres à l'exportation ont-ils évolué depuis {start} ?",
        "de": "Wie haben sich die 3 größten Exportkapitel seit {start} entwickelt?",
    },
    # the challenge (first tab and first slide)
    "ch_kicker": {"en": "The challenge", "fr": "Le défi", "de": "Die Herausforderung"},
    "ch_statement": {
        "en": "Luxembourg trades {total} of goods a year with {partners} partner countries. When the next shock hits, which goods and which supply routes should it watch first?",
        "fr": "Le Luxembourg échange {total} de marchandises par an avec {partners} pays partenaires. Quand le prochain choc surviendra, quels biens et quelles routes d'approvisionnement doit-il surveiller en priorité ?",
        "de": "Luxemburg handelt jährlich Waren im Wert von {total} mit {partners} Partnerländern. Welche Waren und welche Versorgungswege sollte es beim nächsten Schock zuerst im Blick haben?",
    },
    "ch_open_t": {"en": "Small and open", "fr": "Petit et ouvert", "de": "Klein und offen"},
    "ch_open": {
        "en": "In {year}, exports reached {exp} and imports {imp}: {gap} more bought than sold. {nb} of it is traded with the three neighbours.",
        "fr": "En {year}, les exportations ont atteint {exp} et les importations {imp} : {gap} de plus achetés que vendus. {nb} sont échangés avec les trois pays voisins.",
        "de": "{year} erreichten die Exporte {exp} und die Importe {imp}: {gap} mehr gekauft als verkauft. {nb} davon entfallen auf die drei Nachbarländer.",
    },
    "ch_shocks_t": {
        "en": "Three shocks in 15 years",
        "fr": "Trois chocs en 15 ans",
        "de": "Drei Schocks in 15 Jahren",
    },
    "ch_shocks": {
        "en": "The financial crisis, COVID-19 and the energy crisis each hit trade differently; exports fell by up to {worst} in a single year.",
        "fr": "La crise financière, la COVID-19 et la crise énergétique ont chacune touché le commerce différemment ; les exportations ont reculé jusqu'à {worst} en une seule année.",
        "de": "Finanzkrise, COVID-19 und Energiekrise trafen den Handel jeweils anders; die Exporte fielen in einem einzigen Jahr um bis zu {worst}.",
    },
    "ch_evidence_t": {
        "en": "Decisions need evidence",
        "fr": "Décider sur des preuves",
        "de": "Entscheiden auf Basis von Belegen",
    },
    "ch_evidence": {
        "en": "The official data exists, but it is vast and technical: {records} records, {products} products and {partners} partners since {first}.",
        "fr": "Les données officielles existent, mais elles sont vastes et techniques : {records} lignes, {products} produits et {partners} partenaires depuis {first}.",
        "de": "Die amtlichen Daten gibt es, aber sie sind umfangreich und technisch: {records} Datensätze, {products} Produkte und {partners} Partner seit {first}.",
    },
    "ch_task": {
        "en": "**Our task:** turn one large public dataset into evidence that shows decision-makers where Luxembourg's trade in goods is exposed, and how to prepare.",
        "fr": "**Notre mission :** transformer un vaste jeu de données public en preuves qui montrent aux décideurs où le commerce de biens du Luxembourg est exposé, et comment s'y préparer.",
        "de": "**Unsere Aufgabe:** einen großen öffentlichen Datensatz in Belege verwandeln, die Entscheidungsträgern zeigen, wo Luxemburgs Warenhandel verwundbar ist und wie man sich vorbereitet.",
    },
    "ch_approach": {"en": "Our approach", "fr": "Notre démarche", "de": "Unser Vorgehen"},
    "ch_a1_t": {
        "en": "One official dataset",
        "fr": "Un seul jeu de données officiel",
        "de": "Ein amtlicher Datensatz",
    },
    "ch_a1": {
        "en": "Eurostat Comext DS-045409: Luxembourg's monthly trade in goods since {first}, by partner and product, used as published.",
        "fr": "Eurostat Comext DS-045409 : le commerce mensuel de biens du Luxembourg depuis {first}, par partenaire et produit, utilisé tel que publié.",
        "de": "Eurostat Comext DS-045409: Luxemburgs monatlicher Warenhandel seit {first}, nach Partner und Produkt, so wie veröffentlicht.",
    },
    "ch_a2_t": {"en": "Five lenses", "fr": "Cinq angles", "de": "Fünf Blickwinkel"},
    "ch_a2": {
        "en": "Diversification, shocks, Europe, price vs volume and the main goods: each measured, charted and checked.",
        "fr": "Diversification, chocs, Europe, prix et volume, principales marchandises : chacun mesuré, illustré et vérifié.",
        "de": "Diversifizierung, Schocks, Europa, Preis und Menge, wichtigste Waren: jeweils gemessen, dargestellt und geprüft.",
    },
    "ch_a3_t": {
        "en": "Evidence you can check",
        "fr": "Des preuves vérifiables",
        "de": "Überprüfbare Belege",
    },
    "ch_a3": {
        "en": "Every number comes from SQL shown on the page; the assistant answers new questions the same way, in English, French and German.",
        "fr": "Chaque chiffre provient d'une requête SQL affichée sur la page ; l'assistant répond aux nouvelles questions de la même façon, en français, anglais et allemand.",
        "de": "Jede Zahl stammt aus einer auf der Seite gezeigten SQL-Abfrage; der Assistent beantwortet neue Fragen genauso, auf Deutsch, Englisch und Französisch.",
    },
    "all_exports": {"en": "All exports", "fr": "Toutes les exportations", "de": "Alle Exporte"},
    "k_vs": {"en": "vs {year}", "fr": "vs {year}", "de": "ggü. {year}"},
    "k_pp": {"en": "pp", "fr": "pts", "de": "Pp."},
    "eu": {"en": "EU", "fr": "UE", "de": "EU"},
    "non_eu": {"en": "non-EU", "fr": "hors UE", "de": "Nicht-EU"},
    # 1. diversification
    "n_div": {"en": "Diversification", "fr": "Diversification", "de": "Diversifizierung"},
    "d_prod_down": {
        "en": "Exports are spread over more products (concentration {h0} → {h1})",
        "fr": "Les exportations se répartissent sur davantage de produits (concentration {h0} → {h1})",
        "de": "Die Exporte verteilen sich auf mehr Waren (Konzentration {h0} → {h1})",
    },
    "d_prod_up": {
        "en": "Exports depend on fewer products (concentration {h0} → {h1})",
        "fr": "Les exportations dépendent de moins de produits (concentration {h0} → {h1})",
        "de": "Die Exporte hängen von weniger Waren ab (Konzentration {h0} → {h1})",
    },
    "d_part_up": {
        "en": "but imports depend more on a few partners ({p0} → {p1})",
        "fr": "mais les importations dépendent davantage de quelques partenaires ({p0} → {p1})",
        "de": "doch die Importe hängen stärker von wenigen Partnern ab ({p0} → {p1})",
    },
    "d_part_down": {
        "en": "and imports depend less on a few partners ({p0} → {p1})",
        "fr": "et les importations dépendent moins de quelques partenaires ({p0} → {p1})",
        "de": "und die Importe hängen weniger von wenigen Partnern ab ({p0} → {p1})",
    },
    "d_sum": {
        "en": "Concentration index (HHI), {y0} to {y1}: 0 means spread evenly, 10,000 means a single product or partner; above {high} counts as highly concentrated.",
        "fr": "Indice de concentration (HHI), {y0} à {y1} : 0 = réparti uniformément, 10 000 = un seul produit ou partenaire ; au-delà de {high}, la concentration est forte.",
        "de": "Konzentrationsindex (HHI), {y0} bis {y1}: 0 = gleichmäßig verteilt, 10.000 = ein einziges Produkt oder ein einziger Partner; über {high} gilt als hoch konzentriert.",
    },
    "d_f_prod": {
        "en": "By product chapter, export concentration went from {h0} in {y0} to {h1} in {y1} ({chg}); import concentration from {i0} to {i1}.",
        "fr": "Par chapitre de produits, la concentration des exportations est passée de {h0} en {y0} à {h1} en {y1} ({chg}) ; celle des importations de {i0} à {i1}.",
        "de": "Nach Warenkapiteln veränderte sich die Exportkonzentration von {h0} ({y0}) auf {h1} ({y1}) ({chg}), die Importkonzentration von {i0} auf {i1}.",
    },
    "d_f_top": {
        "en": "The two largest export chapters of {y0} ({names}) made up {s0} of exports then and {s1} in {y1}.",
        "fr": "Les deux premiers chapitres à l'exportation de {y0} ({names}) représentaient alors {s0} des exportations, et {s1} en {y1}.",
        "de": "Die zwei größten Exportkapitel von {y0} ({names}) machten damals {s0} der Exporte aus und {y1} {s1}.",
    },
    "d_f_part": {
        "en": "By partner country, import concentration went from {p0} to {p1} and export concentration from {x0} to {x1}.",
        "fr": "Par pays partenaire, la concentration des importations est passée de {p0} à {p1}, celle des exportations de {x0} à {x1}.",
        "de": "Nach Partnerländern veränderte sich die Importkonzentration von {p0} auf {p1}, die Exportkonzentration von {x0} auf {x1}.",
    },
    "d_f_nb": {
        "en": "The three neighbours ({names}) supplied {m0} of imports in {y0} and {m1} in {y1}; their share of exports went from {x0} to {x1}.",
        "fr": "Les trois pays voisins ({names}) fournissaient {m0} des importations en {y0} et {m1} en {y1} ; leur part des exportations est passée de {x0} à {x1}.",
        "de": "Die drei Nachbarländer ({names}) lieferten {y0} {m0} der Importe und {y1} {m1}; ihr Anteil an den Exporten veränderte sich von {x0} auf {x1}.",
    },
    "d_f_n": {
        "en": "Luxembourg imported from {n0} countries in {y0} and from {n1} in {y1}.",
        "fr": "Le Luxembourg importait de {n0} pays en {y0} et de {n1} en {y1}.",
        "de": "Luxemburg importierte {y0} aus {n0} Ländern und {y1} aus {n1}.",
    },
    "d_m": {
        "en": "Export concentration since {y0}",
        "fr": "Concentration des exportations depuis {y0}",
        "de": "Exportkonzentration seit {y0}",
    },
    "by_product": {"en": "by product", "fr": "par produit", "de": "nach Waren"},
    "by_partner": {"en": "by partner", "fr": "par partenaire", "de": "nach Partnern"},
    "hhi_high": {
        "en": "highly concentrated",
        "fr": "forte concentration",
        "de": "hoch konzentriert",
    },
    "hhi_moderate": {
        "en": "moderately concentrated",
        "fr": "concentration modérée",
        "de": "mäßig konzentriert",
    },
    "c_hhi": {
        "en": "Concentration (HHI) by product and by partner, {y0}–{y1}",
        "fr": "Concentration (HHI) par produit et par partenaire, {y0}–{y1}",
        "de": "Konzentration (HHI) nach Waren und Partnern, {y0}–{y1}",
    },
    "c_top": {
        "en": "Share of exports by chapter, {y0} and {y1}",
        "fr": "Part des exportations par chapitre, {y0} et {y1}",
        "de": "Anteil an den Exporten nach Kapitel, {y0} und {y1}",
    },
    # 2. shocks and dependencies
    "n_shock": {
        "en": "Shocks and dependencies",
        "fr": "Chocs et dépendances",
        "de": "Schocks und Abhängigkeiten",
    },
    "ep_gfc": {
        "en": "Financial crisis ({y})",
        "fr": "Crise financière ({y})",
        "de": "Finanzkrise ({y})",
    },
    "ep_covid": {"en": "COVID-19 ({y})", "fr": "COVID-19 ({y})", "de": "COVID-19 ({y})"},
    "ep_energy": {
        "en": "Energy crisis, aftershock ({y})",
        "fr": "Crise énergétique, contrecoup ({y})",
        "de": "Energiekrise, Nachwirkung ({y})",
    },
    "s_title_all": {
        "en": "{name} is the weak spot: its exports fell in each of the {n} crises ({changes})",
        "fr": "{name}, le point faible : ses exportations ont baissé lors de chacune des {n} crises ({changes})",
        "de": "{name} ist die Schwachstelle: die Exporte fielen in jeder der {n} Krisen ({changes})",
    },
    "s_title_one": {
        "en": "{name} fell most in a crisis: {chg} in {year}",
        "fr": "{name} a le plus reculé lors d'une crise : {chg} en {year}",
        "de": "{name} fiel in einer Krise am stärksten: {chg} im Jahr {year}",
    },
    "s_sum_a": {
        "en": "Across {n} crises since {first}, total exports fell by up to {worst} in a year.",
        "fr": "Lors des {n} crises depuis {first}, les exportations totales ont reculé jusqu'à {worst} en un an.",
        "de": "In den {n} Krisen seit {first} fielen die Gesamtexporte um bis zu {worst} in einem Jahr.",
    },
    "s_sum_b": {
        "en": "The critical import is fuel: {share} of it came from {top} in {year}.",
        "fr": "L'importation critique est le carburant : {share} venait de {top} en {year}.",
        "de": "Kritischer Import ist Brennstoff: {year} kamen {share} davon aus {top}.",
    },
    "s_ep": {
        "en": "{label}: exports {e}, imports {i}; hardest hit: {hits}.",
        "fr": "{label} : exportations {e}, importations {i} ; les plus touchés : {hits}.",
        "de": "{label}: Exporte {e}, Importe {i}; am stärksten betroffen: {hits}.",
    },
    "s_rec_yes": {
        "en": "Exports first passed their {a} level ({va}) again in {ry}.",
        "fr": "Les exportations ont retrouvé leur niveau de {a} ({va}) pour la première fois en {ry}.",
        "de": "Die Exporte erreichten ihr Niveau von {a} ({va}) erst {ry} wieder.",
    },
    "s_rec_no": {
        "en": "Exports have not regained their {a} level ({va}); in {year} they stood at {vy}.",
        "fr": "Les exportations n'ont pas retrouvé leur niveau de {a} ({va}) ; en {year}, elles s'élevaient à {vy}.",
        "de": "Die Exporte haben ihr Niveau von {a} ({va}) nicht wieder erreicht; {year} lagen sie bei {vy}.",
    },
    "s_bill": {
        "en": "In {y}, the fuel import bill (HS 27) changed by {chg} ({v0} → {v1}): {share} of the rise in all imports.",
        "fr": "En {y}, la facture des importations de carburants (SH 27) a varié de {chg} ({v0} → {v1}) : {share} de la hausse de toutes les importations.",
        "de": "{y} veränderte sich die Rechnung für Brennstoffimporte (HS 27) um {chg} ({v0} → {v1}): {share} des Anstiegs aller Importe.",
    },
    "s_src": {
        "en": "In {year}, {s1} of fuel imports came from {top}, {s2} from {top2} and {su} from undisclosed partners.",
        "fr": "En {year}, {s1} des importations de carburants venaient de {top}, {s2} de {top2} et {su} de partenaires non divulgués.",
        "de": "{year} kamen {s1} der Brennstoffimporte aus {top}, {s2} aus {top2} und {su} von nicht offengelegten Partnern.",
    },
    "s_m": {
        "en": "{name}: crises with falling exports",
        "fr": "{name} : crises avec baisse des exportations",
        "de": "{name}: Krisen mit sinkenden Exporten",
    },
    "s_m_n": {
        "en": "{name}: largest fall in a crisis",
        "fr": "{name} : plus forte baisse lors d'une crise",
        "de": "{name}: stärkster Rückgang in einer Krise",
    },
    "c_trend": {
        "en": "Exports and imports per year, {start}–{end}",
        "fr": "Exportations et importations par an, {start}–{end}",
        "de": "Exporte und Importe pro Jahr, {start}–{end}",
    },
    "c_heat": {
        "en": "Change in exports during each crisis, largest chapters",
        "fr": "Variation des exportations lors de chaque crise, principaux chapitres",
        "de": "Veränderung der Exporte in jeder Krise, größte Kapitel",
    },
    "c_fuel": {
        "en": "Fuel imports (HS 27) by partner, {year}",
        "fr": "Importations de carburants (SH 27) par partenaire, {year}",
        "de": "Brennstoffimporte (HS 27) nach Partner, {year}",
    },
    "x_chapter": {
        "en": "How have exports of {name} developed since {start}?",
        "fr": "Comment les exportations de {name} ont-elles évolué depuis {start} ?",
        "de": "Wie haben sich die Exporte von {name} seit {start} entwickelt?",
    },
    # 3. a more European trade
    "n_eu": {
        "en": "A more European trade",
        "fr": "Un commerce plus européen",
        "de": "Ein europäischerer Handel",
    },
    "e_title_up": {
        "en": "Trade became more European: {eu1} of imports now come from EU countries ({eu0} in {y0})",
        "fr": "Un commerce plus européen : {eu1} des importations viennent désormais de pays de l'UE ({eu0} en {y0})",
        "de": "Der Handel wurde europäischer: {eu1} der Importe stammen heute aus EU-Ländern ({eu0} im Jahr {y0})",
    },
    "e_title_down": {
        "en": "Trade became less European: {eu1} of imports come from EU countries ({eu0} in {y0})",
        "fr": "Un commerce moins européen : {eu1} des importations viennent de pays de l'UE ({eu0} en {y0})",
        "de": "Der Handel wurde weniger europäisch: {eu1} der Importe stammen aus EU-Ländern ({eu0} im Jahr {y0})",
    },
    "e_sum": {
        "en": "For exports, the EU share went from {x0} to {x1}.",
        "fr": "Pour les exportations, la part de l'UE est passée de {x0} à {x1}.",
        "de": "Bei den Exporten veränderte sich der EU-Anteil von {x0} auf {x1}.",
    },
    "e_f_eu": {
        "en": "EU27 countries supplied {m0} of imports in {y0} and {m1} in {y1}; they took {x0} of exports in {y0} and {x1} in {y1}.",
        "fr": "Les pays de l'UE27 fournissaient {m0} des importations en {y0} et {m1} en {y1} ; ils recevaient {x0} des exportations en {y0} et {x1} en {y1}.",
        "de": "EU27-Länder lieferten {y0} {m0} der Importe und {y1} {m1}; sie nahmen {y0} {x0} der Exporte ab und {y1} {x1}.",
    },
    "e_f_partner": {
        "en": "{name}: {s0} of {flow} in {y0}, {s1} in {y1} (peak {smax} in {ymax}).",
        "fr": "{name} : {s0} des {flow} en {y0}, {s1} en {y1} (maximum {smax} en {ymax}).",
        "de": "{name}: {s0} der {flow} im Jahr {y0}, {s1} im Jahr {y1} (Höchstwert {smax} im Jahr {ymax}).",
    },
    "e_f_uk": {
        "en": "The United Kingdom counts as non-EU in every year (fixed EU27 composition), so Brexit in 2021 does not change the EU share by itself.",
        "fr": "Le Royaume-Uni est compté hors UE pour toutes les années (composition fixe UE27) : le Brexit de 2021 ne modifie donc pas à lui seul la part de l'UE.",
        "de": "Das Vereinigte Königreich zählt in allen Jahren als Nicht-EU-Land (feste EU27-Zusammensetzung); der Brexit 2021 verändert den EU-Anteil daher nicht für sich allein.",
    },
    "e_m": {
        "en": "Imports from EU countries, {y1}",
        "fr": "Importations venant de l'UE, {y1}",
        "de": "Importe aus EU-Ländern, {y1}",
    },
    "c_eu": {
        "en": "Share of trade with EU27 countries, {start}–{end}",
        "fr": "Part des échanges avec les pays de l'UE27, {start}–{end}",
        "de": "Anteil des Handels mit EU27-Ländern, {start}–{end}",
    },
    "c_watch": {
        "en": "Share of selected non-EU partners, {start}–{end}",
        "fr": "Part de partenaires hors UE choisis, {start}–{end}",
        "de": "Anteil ausgewählter Nicht-EU-Partner, {start}–{end}",
    },
    "x_eu": {
        "en": "How have imports from EU27 and non-EU countries developed since {start}?",
        "fr": "Comment les importations en provenance des pays de l'UE27 et hors UE ont-elles évolué depuis {start} ?",
        "de": "Wie haben sich die Importe aus EU27- und Nicht-EU-Ländern seit {start} entwickelt?",
    },
    # 4. price vs volume
    "n_price": {"en": "Price vs volume", "fr": "Prix et volume", "de": "Preis und Menge"},
    "v_title": {
        "en": "A kilogram imported from outside the EU is worth {ratio} times one from the EU ({ex} vs {in_} per kg, {year})",
        "fr": "Un kilogramme importé hors UE vaut {ratio} fois un kilogramme importé de l'UE ({ex} contre {in_} par kg, {year})",
        "de": "Ein Kilogramm Import von außerhalb der EU ist {ratio}-mal so viel wert wie eines aus der EU ({ex} gegenüber {in_} je kg, {year})",
    },
    "v_sum": {
        "en": "Value per kilogram separates price from volume: it is the only price signal in this dataset.",
        "fr": "La valeur par kilogramme sépare le prix du volume : c'est le seul signal de prix de ce jeu de données.",
        "de": "Der Wert je Kilogramm trennt Preis und Menge: das einzige Preissignal in diesem Datensatz.",
    },
    "v_f_imp": {
        "en": "Imports, {year}: {ex} per kg from outside the EU, {in_} per kg from EU partners (in {y0}: {ex0} and {in0}).",
        "fr": "Importations, {year} : {ex} par kg hors UE, {in_} par kg depuis l'UE (en {y0} : {ex0} et {in0}).",
        "de": "Importe {year}: {ex} je kg von außerhalb der EU, {in_} je kg aus der EU ({y0}: {ex0} und {in0}).",
    },
    "v_f_exp": {
        "en": "Exports, {year}: {ex} per kg outside the EU, {in_} per kg inside.",
        "fr": "Exportations, {year} : {ex} par kg hors UE, {in_} par kg dans l'UE.",
        "de": "Exporte {year}: {ex} je kg außerhalb der EU, {in_} je kg innerhalb.",
    },
    "v_f_read": {
        "en": "This fits light, high-value goods arriving by air and heavy goods arriving overland from neighbours. The data has no transport mode, so this is a reading, not a measurement.",
        "fr": "Cela correspond à des biens légers et de grande valeur arrivant par avion, et à des biens lourds arrivant par voie terrestre des pays voisins. Les données n'indiquent pas le mode de transport : c'est une lecture, pas une mesure.",
        "de": "Das passt zu leichten, hochwertigen Waren, die per Luftfracht kommen, und zu schweren Waren, die über Land aus den Nachbarländern kommen. Die Daten enthalten keinen Verkehrsträger: das ist eine Lesart, keine Messung.",
    },
    "v_f_fuel": {
        "en": "Fuel imports in {y} compared with {b}: value {v}, mass {q}, value per kg {p}.",
        "fr": "Importations de carburants en {y} par rapport à {b} : valeur {v}, masse {q}, valeur par kg {p}.",
        "de": "Brennstoffimporte {y} gegenüber {b}: Wert {v}, Masse {q}, Wert je kg {p}.",
    },
    "v_f_price": {
        "en": "The energy shock was mainly a price shock, not a supply cut.",
        "fr": "Le choc énergétique a surtout été un choc de prix, pas une rupture d'approvisionnement.",
        "de": "Der Energieschock war vor allem ein Preisschock, kein Lieferausfall.",
    },
    "v_m": {
        "en": "Value of a kilo imported from outside the EU vs inside",
        "fr": "Valeur d'un kilo importé hors UE / UE",
        "de": "Wert eines Kilos Import Nicht-EU / EU",
    },
    "c_uv": {
        "en": "Value per kg, inside and outside the EU, {start}–{end} (log scale)",
        "fr": "Valeur par kg, dans et hors UE, {start}–{end} (échelle log)",
        "de": "Wert je kg, innerhalb und außerhalb der EU, {start}–{end} (log. Skala)",
    },
    "c_fuel_idx": {
        "en": "Fuel imports: value, mass and value per kg, index {b} = 100",
        "fr": "Importations de carburants : valeur, masse et valeur par kg, indice {b} = 100",
        "de": "Brennstoffimporte: Wert, Masse und Wert je kg, Index {b} = 100",
    },
    "idx_value": {"en": "Value", "fr": "Valeur", "de": "Wert"},
    "idx_mass": {"en": "Mass (kg)", "fr": "Masse (kg)", "de": "Masse (kg)"},
    "idx_price": {"en": "Value per kg", "fr": "Valeur par kg", "de": "Wert je kg"},
    "x_fuel": {
        "en": "How has the value per kg of fuel imports developed since {start}?",
        "fr": "Comment la valeur par kg des importations de carburants a-t-elle évolué depuis {start} ?",
        "de": "Wie hat sich der Wert je kg der Brennstoffimporte seit {start} entwickelt?",
    },
    # 5. conclusion
    "n_end": {
        "en": "Conclusion: resilience",
        "fr": "Conclusion : résilience",
        "de": "Fazit: Resilienz",
    },
    "c_title": {
        "en": "Resilient but exposed: diversified in products, concentrated in partners and routes",
        "fr": "Résilient mais exposé : diversifié en produits, concentré en partenaires et en routes",
        "de": "Widerstandsfähig, aber verwundbar: breit bei den Waren, konzentriert bei Partnern und Wegen",
    },
    "c_sum": {
        "en": "Diversification has worked for products, not for partners. Preparedness means watching the few sectors and routes that break first.",
        "fr": "La diversification a fonctionné pour les produits, pas pour les partenaires. Se préparer, c'est surveiller les quelques secteurs et routes qui cèdent en premier.",
        "de": "Die Diversifizierung hat bei den Waren gewirkt, nicht bei den Partnern. Vorsorge heißt, die wenigen Branchen und Wege zu beobachten, die zuerst brechen.",
    },
    "c_f_div": {
        "en": "Diversification: export concentration by product went from {h0} to {h1}, but {nb} of imports came from {names} in {y1}.",
        "fr": "Diversification : la concentration des exportations par produit est passée de {h0} à {h1}, mais {nb} des importations venaient de {names} en {y1}.",
        "de": "Diversifizierung: die Exportkonzentration nach Waren veränderte sich von {h0} auf {h1}, doch {y1} kamen {nb} der Importe aus {names}.",
    },
    "c_f_res": {
        "en": "Resilience: {shock}.",
        "fr": "Résilience : {shock}.",
        "de": "Resilienz: {shock}.",
    },
    "c_f_eu": {
        "en": "Europe: {eu1} of imports come from EU27 countries; the single market is Luxembourg's main supply line.",
        "fr": "Europe : {eu1} des importations viennent des pays de l'UE27 ; le marché unique est la principale ligne d'approvisionnement du Luxembourg.",
        "de": "Europa: {eu1} der Importe stammen aus EU27-Ländern; der Binnenmarkt ist Luxemburgs wichtigste Versorgungslinie.",
    },
    "c_f_prep": {
        "en": "Preparedness: {share} of fuel imports came from {top} in {year}; watch this route and the price per kg.",
        "fr": "Préparation : {share} des importations de carburants venaient de {top} en {year} ; surveiller cette route et le prix par kg.",
        "de": "Vorsorge: {year} kamen {share} der Brennstoffimporte aus {top}; diesen Weg und den Preis je kg beobachten.",
    },
    "c_note": {
        "en": "Options for discussion: our reading of the findings, not computed from the data.",
        "fr": "Options à discuter : notre lecture des constats, non calculée à partir des données.",
        "de": "Optionen zur Diskussion: unsere Lesart der Befunde, nicht aus den Daten berechnet.",
    },
    "col_finding": {"en": "Finding", "fr": "Constat", "de": "Befund"},
    "col_option": {"en": "Option", "fr": "Option", "de": "Option"},
    "col_monitor": {
        "en": "Monitor in LuxTrade Lens with",
        "fr": "À suivre dans LuxTrade Lens avec",
        "de": "Beobachten in LuxTrade Lens mit",
    },
    "o1": {
        "en": (
            "Products diversified, partners concentrated",
            "Keep the diversification policy; track one yearly concentration index",
            "Concentration (HHI) by product and partner",
        ),
        "fr": (
            "Produits diversifiés, partenaires concentrés",
            "Poursuivre la politique de diversification ; suivre un indice annuel de concentration",
            "Concentration (HHI) par produit et par partenaire",
        ),
        "de": (
            "Waren breit gestreut, Partner konzentriert",
            "Diversifizierungspolitik fortführen; einen jährlichen Konzentrationsindex verfolgen",
            "Konzentration (HHI) nach Waren und Partnern",
        ),
    },
    "o2": {
        "en": (
            "{name} falls first and deepest",
            "Prepare sector support triggers in advance, linked to energy prices",
            "Change in exports by chapter, monthly",
        ),
        "fr": (
            "{name} recule en premier et le plus fortement",
            "Préparer à l'avance des seuils de soutien sectoriel, liés aux prix de l'énergie",
            "Variation des exportations par chapitre, mensuelle",
        ),
        "de": (
            "{name} fällt zuerst und am stärksten",
            "Auslöser für Branchenhilfen im Voraus festlegen, gekoppelt an Energiepreise",
            "Veränderung der Exporte nach Kapitel, monatlich",
        ),
    },
    "o3": {
        "en": (
            "Most imports come from the EU",
            "Treat single-market functioning (borders, transport) as critical infrastructure",
            "EU27 share of trade",
        ),
        "fr": (
            "La plupart des importations viennent de l'UE",
            "Traiter le bon fonctionnement du marché unique (frontières, transport) comme une infrastructure critique",
            "Part de l'UE27 dans les échanges",
        ),
        "de": (
            "Die meisten Importe kommen aus der EU",
            "Das Funktionieren des Binnenmarkts (Grenzen, Verkehr) als kritische Infrastruktur behandeln",
            "EU27-Anteil am Handel",
        ),
    },
    "o4": {
        "en": (
            "Fuel arrives through a few neighbours, at volatile prices",
            "Corridor and energy agreements with neighbouring countries",
            "Fuel imports by partner; value per kg",
        ),
        "fr": (
            "Le carburant arrive par quelques pays voisins, à des prix volatils",
            "Accords de corridor et d'énergie avec les pays voisins",
            "Importations de carburants par partenaire ; valeur par kg",
        ),
        "de": (
            "Brennstoff kommt über wenige Nachbarländer, zu schwankenden Preisen",
            "Korridor- und Energieabkommen mit den Nachbarländern",
            "Brennstoffimporte nach Partner; Wert je kg",
        ),
    },
    # caveats
    "lim_consign": {
        "en": "For EU partners, the partner is the country goods were shipped from, not where they were made.",
        "fr": "Pour les partenaires de l'UE, le partenaire est le pays d'expédition, pas le pays de fabrication.",
        "de": "Bei EU-Partnern ist der Partner das Versendungsland, nicht das Herstellungsland.",
    },
    "lim_uv": {
        "en": "Value per kg mixes products: a change can come from a different product mix, not only from prices. Rows without a recorded mass are left out.",
        "fr": "La valeur par kg mélange les produits : une variation peut venir d'un autre assortiment de produits, pas seulement des prix. Les lignes sans masse déclarée sont exclues.",
        "de": "Der Wert je kg mischt Waren: eine Veränderung kann aus einer anderen Warenzusammensetzung stammen, nicht nur aus Preisen. Zeilen ohne erfasste Masse bleiben unberücksichtigt.",
    },
    "lim_lumpy": {
        "en": "In a country this small, a few large shipments can move a whole chapter; one-off swings are not crises.",
        "fr": "Dans un pays aussi petit, quelques grosses expéditions peuvent faire varier tout un chapitre ; les écarts ponctuels ne sont pas des crises.",
        "de": "In einem so kleinen Land können wenige große Sendungen ein ganzes Kapitel bewegen; einmalige Ausschläge sind keine Krisen.",
    },
}


@dataclass
class Finding:
    """One evidence-backed finding: a card on the Overview, details in its dialog."""

    key: str  # diversification, shocks, europe, prices, conclusion
    name: str  # short name: card label and dialog title
    title: str  # the finding in one sentence, with its numbers
    summary: str
    facts: list[str]
    chart_titles: list[str]
    frames: dict[str, pd.DataFrame]
    sql: list[str]
    methods: list[str]
    limits: list[str]
    metric_label: str = ""
    metric_value: str = ""
    metric_delta: str | None = None
    delta_color: str = "off"
    delta_arrow: str = "auto"
    explore_question: str | None = None
    explore_spec: QuerySpec | None = None
    note: str = ""
    headline: str = ""  # the engaging line on the card; ``title`` is its evidence
    tiles: list[tuple[str, str]] = field(default_factory=list)  # conclusion: (title, text)
    analysis: str = ""  # "why it matters": what the numbers mean, on the card


def _t(key: str, lang: str, **values: object) -> str:
    return _T[key][lang].format(**values)


def _q(sem: SemanticLayer, sql: str) -> tuple[pd.DataFrame, str]:
    """Run guarded SQL; return the rows and the SQL as shown in the evidence."""
    checked = check_sql(sql)
    return sem.query(checked), checked


def _why(lang: str, text: str) -> str:
    """'**Why it matters.** …' (empty when there is nothing to say)."""
    return f"{_T['why'][lang]} {text}" if text else ""


def _pct(value: float, lang: str) -> str:
    return fmt_pct(value, lang)


def _chg(v0: float, v1: float, lang: str, decimals: int = 1) -> str:
    """Signed change in percent, '–' when the base is zero."""
    if not v0:
        return "–"
    return fmt_pct(100 * (v1 / v0 - 1), lang, decimals=decimals, signed=True)


def _hhi(value: float, lang: str) -> str:
    return fmt_number(value, 0, lang)


def _eur_kg(value: float, lang: str) -> str:
    return f"{fmt_number(value, 2, lang)} €"


def _pp(v0: float, v1: float, lang: str, year: int) -> str:
    sign = "+" if v1 >= v0 else "-"  # ASCII minus: Streamlit reads the delta's direction from it
    return (
        f"{sign}{fmt_number(abs(v1 - v0), 1, lang)} {_T['k_pp'][lang]} "
        f"{_t('k_vs', lang, year=year)}"
    )


def _cell(df: pd.DataFrame, col: str, **eq: object) -> float:
    """The one value of ``col`` where every column equals its ``eq`` value (NaN if none)."""
    mask = pd.Series(True, index=df.index)
    for k, v in eq.items():
        mask &= df[k] == v
    part = df.loc[mask, col]
    return float(part.iloc[0]) if len(part) else float("nan")


def snapshot_years(first: int, year: int) -> list[int]:
    """One year every five, back from the latest complete year: 2005, 2010, …, 2025."""
    years = [y for y in range(year - SNAPSHOT_SPAN, year + 1, SNAPSHOT_STEP) if y >= first]
    return years if len(years) >= 2 else sorted({first, year})


def _in(years: list[int]) -> str:
    return ", ".join(str(y) for y in years)


# --- 1. diversification ---------------------------------------------------------------------


def _diversification(
    sem: SemanticLayer, lang: str, years: list[int], ctx: dict[str, object]
) -> Finding:
    y0, y1 = years[0], years[-1]
    hhi, hhi_sql = _q(
        sem,
        f"""WITH by_product AS (
  SELECT year, flow, hs2 AS key, sum(value_eur) AS v
  FROM v_lu_trade_hs2
  WHERE year IN ({_in(years)})
  GROUP BY year, flow, hs2
), by_partner AS (
  SELECT year, flow, partner AS key, sum(value_eur) AS v
  FROM v_lu_trade_hs2
  WHERE year IN ({_in(years)}) AND NOT partner_is_special
  GROUP BY year, flow, partner
), shares AS (
  SELECT 'product' AS dim, year, flow, v / sum(v) OVER (PARTITION BY year, flow) AS s
  FROM by_product WHERE v > 0
  UNION ALL
  SELECT 'partner' AS dim, year, flow, v / sum(v) OVER (PARTITION BY year, flow) AS s
  FROM by_partner WHERE v > 0
)
SELECT dim, year, flow, 10000 * sum(s * s) AS hhi, count(*) AS n
FROM shares
GROUP BY dim, year, flow
ORDER BY dim, flow, year""",
    )
    nb_codes = ", ".join(f"'{c}'" for c in NEIGHBOURS)
    nb, nb_sql = _q(
        sem,
        f"""SELECT year, flow,
       100 * sum(value_eur) FILTER (WHERE partner IN ({nb_codes})) / sum(value_eur) AS share
FROM v_lu_trade_hs2
WHERE year IN ({_in(years)})
GROUP BY year, flow
ORDER BY flow, year""",
    )
    chapters, ch_sql = _q(
        sem,
        f"""WITH by_chapter AS (
  SELECT year, hs2, sum(value_eur) AS v
  FROM v_lu_trade_hs2
  WHERE flow = 'export' AND year IN ({y0}, {y1})
  GROUP BY year, hs2
)
SELECT year, hs2, 100 * v / sum(v) OVER (PARTITION BY year) AS share
FROM by_chapter
ORDER BY year, share DESC""",
    )

    def h(dim: str, flow: str, y: int) -> float:
        return _cell(hhi, "hhi", dim=dim, flow=flow, year=y)

    hx0, hx1 = h("product", "export", y0), h("product", "export", y1)
    hm0, hm1 = h("product", "import", y0), h("product", "import", y1)
    px0, px1 = h("partner", "export", y0), h("partner", "export", y1)
    pm0, pm1 = h("partner", "import", y0), h("partner", "import", y1)
    a = _t(
        "d_prod_down" if hx1 <= hx0 else "d_prod_up", lang, h0=_hhi(hx0, lang), h1=_hhi(hx1, lang)
    )
    b = _t(
        "d_part_up" if pm1 >= pm0 else "d_part_down", lang, p0=_hhi(pm0, lang), p1=_hhi(pm1, lang)
    )

    label = {c: sem.label(c, "product", lang) for c in chapters["hs2"].unique()}
    first2 = chapters[chapters["year"] == y0].head(2)["hs2"].tolist()
    then_now = chapters[chapters["hs2"].isin(first2)].groupby("year")["share"].sum()
    nb_names = ", ".join(sem.label(c, "partner", lang) for c in NEIGHBOURS)
    n0 = int(_cell(hhi, "n", dim="partner", flow="import", year=y0))
    n1 = int(_cell(hhi, "n", dim="partner", flow="import", year=y1))
    nbm0, nbm1 = (
        _cell(nb, "share", flow="import", year=y0),
        _cell(nb, "share", flow="import", year=y1),
    )
    facts = [
        _t(
            "d_f_prod",
            lang,
            h0=_hhi(hx0, lang),
            h1=_hhi(hx1, lang),
            y0=y0,
            y1=y1,
            chg=_chg(hx0, hx1, lang, 0),
            i0=_hhi(hm0, lang),
            i1=_hhi(hm1, lang),
        ),
        _t(
            "d_f_top",
            lang,
            y0=y0,
            y1=y1,
            names=", ".join(label[c] for c in first2),
            s0=_pct(then_now.get(y0, 0.0), lang),
            s1=_pct(then_now.get(y1, 0.0), lang),
        ),
        _t(
            "d_f_part",
            lang,
            p0=_hhi(pm0, lang),
            p1=_hhi(pm1, lang),
            x0=_hhi(px0, lang),
            x1=_hhi(px1, lang),
        ),
        _t(
            "d_f_nb",
            lang,
            names=nb_names,
            y0=y0,
            y1=y1,
            m0=_pct(nbm0, lang),
            m1=_pct(nbm1, lang),
            x0=_pct(_cell(nb, "share", flow="export", year=y0), lang),
            x1=_pct(_cell(nb, "share", flow="export", year=y1), lang),
        ),
        _t("d_f_n", lang, n0=n0, n1=n1, y0=y0, y1=y1),
    ]
    # chart frames: HHI lines and the chapters that were in the top five in either year
    hhi_lines = hhi.assign(
        label=[
            f"{flow_label(f, lang).capitalize()}, {_T['by_' + d][lang]}"
            for d, f in zip(hhi["dim"], hhi["flow"], strict=True)
        ]
    )
    top = set()
    for y in (y0, y1):
        top |= set(chapters[chapters["year"] == y].head(5)["hs2"])
    bars = chapters[chapters["hs2"].isin(top)].assign(label=lambda d: d["hs2"].map(label))
    refs = pd.DataFrame(
        {
            "level": [HHI_MODERATE, HHI_HIGH],
            "label": [_T["hhi_moderate"][lang], _T["hhi_high"][lang]],
        }
    )
    # the story holds when products spread out while the neighbours' grip tightened
    story = hx1 < hx0 and nbm1 > nbm0
    ctx.update(hx0=hx0, hx1=hx1, nb=nbm1, nb_names=nb_names, y1=y1, story=story and pm1 > pm0)
    question, explore = preset("Q2").for_language(lang)
    return Finding(
        key="diversification",
        name=_T["n_div"][lang],
        title=f"{a}, {b}",
        summary=_t("d_sum", lang, y0=y0, y1=y1, high=_hhi(HHI_HIGH, lang)),
        facts=facts,
        chart_titles=[_t("c_hhi", lang, y0=y0, y1=y1), _t("c_top", lang, y0=y0, y1=y1)],
        frames={"main": hhi_lines, "chapters": bars, "refs": refs, "neighbours": nb},
        sql=[hhi_sql, nb_sql, ch_sql],
        methods=[
            "concentration = Herfindahl-Hirschman index (HHI): the sum of squared shares × 10,000",
            "by product: shares of the HS2 chapters (confidential codes stay in their chapter); "
            "by partner: shares of disclosed partner countries",
            f"reading guide (US Merger Guidelines 2023): below {HHI_MODERATE:,} unconcentrated, "
            f"above {HHI_HIGH:,} highly concentrated",
            f"snapshot years every {SNAPSHOT_STEP} years, back from the latest complete year",
        ],
        limits=[guard.make("L06", "warn").message],
        metric_label=_t("d_m", lang, y0=y0),
        metric_value=_chg(hx0, hx1, lang, 0),
        metric_delta=f"HHI {_hhi(hx0, lang)} → {_hhi(hx1, lang)}",
        delta_arrow="off",
        headline=_T["h_div" if story else "h_div_n"][lang],
        analysis=_why(
            lang,
            _t(
                "a_div",
                lang,
                y0=y0,
                s0=_pct(then_now.get(y0, 0.0), lang),
                s1=_pct(then_now.get(y1, 0.0), lang),
                nb=_pct(nbm1, lang),
                names=nb_names,
            ),
        ),
        explore_question=question,
        explore_spec=explore,
    )


# --- 2. shocks and dependencies -------------------------------------------------------------


def _shocks(
    sem: SemanticLayer, lang: str, first: int, year: int, ctx: dict[str, object]
) -> Finding:
    yearly, yearly_sql = _q(
        sem,
        f"""SELECT year, flow, hs2, sum(value_eur) AS value_eur
FROM v_lu_trade_hs2
WHERE year BETWEEN {first} AND {year}
GROUP BY year, flow, hs2
ORDER BY year, flow, hs2""",
    )
    fuel, fuel_sql = _q(
        sem,
        f"""SELECT year, CASE WHEN partner_is_special THEN 'UNDISCLOSED' ELSE partner END AS key,
       sum(value_eur) AS value_eur
FROM v_lu_trade_hs2
WHERE hs2 = '{ENERGY}' AND flow = 'import' AND year BETWEEN {first} AND {year}
GROUP BY year, key
ORDER BY year, value_eur DESC""",
    )
    totals = yearly.groupby(["year", "flow"])["value_eur"].sum()
    exports = yearly[yearly["flow"] == "export"].pivot_table(
        index="hs2", columns="year", values="value_eur", aggfunc="sum", fill_value=0.0
    )
    episodes = [(k, a, b) for k, a, b in EPISODES if a >= first and b <= year]
    label = {c: sem.label(c, "product", lang) for c in exports.index}
    ep_label = {k: _t(f"ep_{k}", lang, y=b) for k, _, b in episodes}

    changes = pd.DataFrame(index=exports.index)
    for k, a, b in episodes:
        share = 100 * exports[a] / exports[a].sum()
        chg = 100 * (exports[b] / exports[a] - 1)
        changes[k] = chg.where((share >= MIN_SHARE) & (exports[a] > 0))
    keys = [k for k, _, _ in episodes]
    full = changes.dropna()
    fell_everywhere = full[(full < 0).all(axis=1)] if keys else full.iloc[0:0]
    all_fell = not fell_everywhere.empty
    if all_fell:
        weak = fell_everywhere.mean(axis=1).idxmin()
        changes_text = " · ".join(
            fmt_pct(changes.loc[weak, k], lang, decimals=0, signed=True) for k in keys
        )
        title = _t("s_title_all", lang, name=label[weak], n=len(keys), changes=changes_text)
        shock_text = title
    else:
        cells = (
            changes.reset_index(names="hs2")
            .melt(id_vars="hs2", var_name="episode", value_name="change")
            .dropna()
        )
        if cells.empty:
            weak, k_worst, changes_text = exports.index[0], None, "–"
        else:
            worst_cell = cells.loc[cells["change"].idxmin()]
            weak, k_worst = worst_cell["hs2"], worst_cell["episode"]
            changes_text = fmt_pct(worst_cell["change"], lang, decimals=0, signed=True)
        y_worst = next((b for k, _, b in episodes if k == k_worst), year)
        title = _t("s_title_one", lang, name=label[weak], chg=changes_text, year=y_worst)
        shock_text = title

    facts = []
    worst = 0.0
    for k, a, b in episodes:
        e = _chg(totals[(a, "export")], totals[(b, "export")], lang)
        i = _chg(totals[(a, "import")], totals[(b, "import")], lang)
        worst = min(worst, 100 * (totals[(b, "export")] / totals[(a, "export")] - 1))
        hits = changes[k].dropna().nsmallest(2)
        hits_text = ", ".join(
            f"{label[c]} ({fmt_pct(v, lang, signed=True)})" for c, v in hits.items()
        )
        facts.append(_t("s_ep", lang, label=ep_label[k], e=e, i=i, hits=hits_text or "–"))
    if episodes:
        _, a, b = episodes[0]
        va = totals[(a, "export")]
        later = [y for y in range(b + 1, year + 1) if totals.get((y, "export"), 0.0) >= va]
        facts.append(
            _t("s_rec_yes", lang, a=a, va=fmt_eur(va, lang), ry=later[0])
            if later
            else _t(
                "s_rec_no",
                lang,
                a=a,
                va=fmt_eur(va, lang),
                year=year,
                vy=fmt_eur(totals[(year, "export")], lang),
            )
        )

    # fuel: the import bill in the energy shock, and where fuel comes from
    fuel_year = fuel.groupby("year")["value_eur"].sum()
    y_a, y_b = ENERGY_SHOCK - 1, ENERGY_SHOCK
    if y_a in fuel_year.index and y_b in fuel_year.index:
        d_fuel = fuel_year[y_b] - fuel_year[y_a]
        d_all = totals[(y_b, "import")] - totals[(y_a, "import")]
        if d_fuel > 0 and d_all > 0:
            facts.append(
                _t(
                    "s_bill",
                    lang,
                    y=y_b,
                    chg=_chg(fuel_year[y_a], fuel_year[y_b], lang),
                    v0=fmt_eur(fuel_year[y_a], lang),
                    v1=fmt_eur(fuel_year[y_b], lang),
                    share=_pct(100 * d_fuel / d_all, lang),
                )
            )
    latest = fuel[fuel["year"] == year].copy()
    fuel_total = latest["value_eur"].sum()
    latest["share"] = 100 * latest["value_eur"] / fuel_total if fuel_total else 0.0
    named = latest[latest["key"] != "UNDISCLOSED"].sort_values("value_eur", ascending=False)
    undisclosed = latest.loc[latest["key"] == "UNDISCLOSED", "share"].sum()
    summary = _t("s_sum_a", lang, n=len(episodes), first=first, worst=fmt_pct(abs(worst), lang))
    if len(named) >= 2:
        top, top2 = named.iloc[0], named.iloc[1]
        top_name = sem.label(top["key"], "partner", lang)
        facts.append(
            _t(
                "s_src",
                lang,
                year=year,
                s1=_pct(top["share"], lang),
                top=top_name,
                s2=_pct(top2["share"], lang),
                top2=sem.label(top2["key"], "partner", lang),
                su=_pct(undisclosed, lang),
            )
        )
        summary += " " + _t(
            "s_sum_b", lang, share=_pct(top["share"], lang), top=top_name, year=year
        )
        ctx.update(fuel_top=top_name, fuel_share=top["share"])

    # chart frames
    trend = (
        totals.rename("value")
        .reset_index()
        .rename(columns={"year": "period"})[["period", "flow", "value"]]
    )
    events = pd.DataFrame(
        [{"year": b, "label": ep_label[k]} for k, _, b in episodes], columns=["year", "label"]
    )
    rows = set(fell_everywhere.index) | {weak}
    for k in keys:
        rows |= set(changes[k].dropna().nsmallest(3).index)
    heat = (
        changes.loc[sorted(rows)]
        .assign(label=lambda d: d.index.map(label))
        .reset_index(names="hs2")
        .melt(id_vars=["hs2", "label"], var_name="episode", value_name="change")
        .assign(episode=lambda d: d["episode"].map(ep_label))
    )
    shown = named.head(5)
    other = named.iloc[5:]["share"].sum()
    fuel_bar = pd.concat(
        [
            pd.DataFrame(
                {
                    "key": shown["key"],
                    "label": [sem.label(c, "partner", lang) for c in shown["key"]],
                    "share": shown["share"],
                }
            ),
            pd.DataFrame(
                {
                    "key": ["OTHER", "UNDISCLOSED"],
                    "label": [
                        sem.label("OTHER", "partner", lang),
                        sem.label("UNDISCLOSED", "partner", lang),
                    ],
                    "share": [other, undisclosed],
                }
            ),
        ],
        ignore_index=True,
    )
    fuel_bar = fuel_bar[fuel_bar["share"] > 0]
    # the weak spot against all exports, crisis by crisis (the card's chart)
    episodes_frame = pd.DataFrame(
        [
            row
            for k, a, b in episodes
            for row in (
                {
                    "episode": ep_label[k],
                    "series": label[weak],
                    "change": 100 * (exports.loc[weak, b] / exports.loc[weak, a] - 1)
                    if exports.loc[weak, a]
                    else float("nan"),
                },
                {
                    "episode": ep_label[k],
                    "series": _T["all_exports"][lang],
                    "change": 100 * (totals[(b, "export")] / totals[(a, "export")] - 1),
                },
            )
        ],
        columns=["episode", "series", "change"],
    )
    # how much further the weak spot fell than all exports, on average over the crises
    by_series = episodes_frame.groupby("series", sort=False)["change"].mean()
    w_avg = by_series.get(label[weak], 0.0)
    a_avg = by_series.get(_T["all_exports"][lang], 0.0)
    shock_analysis = ""
    if episodes and a_avg < 0 and w_avg < a_avg:
        ratio = w_avg / a_avg
        shock_analysis = _t(
            "a_shock",
            lang,
            n=len(episodes),
            name=label[weak],
            ratio=fmt_number(ratio, 0 if ratio >= 10 else 1, lang),
            w=fmt_pct(w_avg, lang, signed=True),
            a=fmt_pct(a_avg, lang, signed=True),
        )
    energy = next((b for k, _, b in episodes if k == "energy"), None)
    if energy is not None:
        fell = episodes_frame[
            (episodes_frame["series"] == label[weak])
            & (episodes_frame["episode"] == _t("ep_energy", lang, y=energy))
        ]["change"]
        if (fell < 0).any():
            ctx.update(energy_lag=energy)  # the fuel sentence is added once prices are known
    ctx.update(
        shock=shock_text,
        weak_name=label[weak],
        weak_tile=_t("w_weak", lang, n=len(keys), first=episodes[0][2] if episodes else first)
        if all_fell
        else _t("w_weak_n", lang, chg=changes_text),
    )
    explore = QuerySpec(
        language=lang,
        intent="time_series",
        freq="A",
        flow="export",
        products=[weak],
        period_start=str(first),
        period_end=str(year),
    )
    return Finding(
        key="shocks",
        name=_T["n_shock"][lang],
        title=title,
        summary=summary,
        facts=facts,
        chart_titles=[
            _t("c_trend", lang, start=first, end=year),
            _t("c_heat", lang),
            _t("c_fuel", lang, year=year),
        ],
        frames={
            "main": trend,
            "events": events,
            "heat": heat,
            "fuel": fuel_bar,
            "episodes": episodes_frame,
        },
        sql=[yearly_sql, fuel_sql],
        methods=[
            "crisis change = exports in the year of the fall ÷ exports in the year before − 1, per HS2 chapter",
            f"only chapters with at least {MIN_SHARE:g} % of exports in the year before are ranked",
            "weak spot = the chapter that fell in every crisis, with the largest average fall",
            "crisis years are reading aids (well-known shocks), not part of the data",
            "fuel = HS chapter 27 (mineral fuels and oils), imports",
        ],
        limits=[guard.make("L06", "warn").message, _T["lim_lumpy"][lang]],
        metric_label=_t("s_m" if all_fell else "s_m_n", lang, name=label[weak]),
        metric_value=f"{len(keys)} / {len(keys)}" if all_fell else changes_text,
        metric_delta=changes_text if all_fell else None,
        delta_arrow="off",
        headline=_t("h_shock", lang, name=label[weak]) if all_fell else _T["h_shock_n"][lang],
        analysis=_why(lang, shock_analysis),
        explore_question=_t("x_chapter", lang, name=label[weak], start=first),
        explore_spec=explore,
    )


# --- 3. a more European trade ---------------------------------------------------------------


def _europe(
    sem: SemanticLayer, lang: str, first: int, years: list[int], ctx: dict[str, object]
) -> Finding:
    y0, y1 = years[0], years[-1]
    eu, eu_sql = _q(
        sem,
        f"""SELECT year, flow,
       100 * sum(value_eur) FILTER (WHERE {_EU}) / sum(value_eur) AS share
FROM v_lu_trade_hs2
WHERE year BETWEEN {first} AND {y1}
GROUP BY year, flow
ORDER BY flow, year""",
    )
    codes = ", ".join(f"'{c}'" for c, _ in WATCH)
    watch, watch_sql = _q(
        sem,
        f"""WITH by_partner AS (
  SELECT year, flow, partner, sum(value_eur) AS v
  FROM v_lu_trade_hs2
  WHERE year BETWEEN {first} AND {y1}
  GROUP BY year, flow, partner
), shares AS (
  SELECT year, flow, partner, 100 * v / sum(v) OVER (PARTITION BY year, flow) AS share
  FROM by_partner
)
SELECT year, flow, partner, share
FROM shares
WHERE partner IN ({codes})
ORDER BY partner, flow, year""",
    )
    m0, m1 = _cell(eu, "share", flow="import", year=y0), _cell(eu, "share", flow="import", year=y1)
    x0, x1 = _cell(eu, "share", flow="export", year=y0), _cell(eu, "share", flow="export", year=y1)
    facts = [
        _t(
            "e_f_eu",
            lang,
            y0=y0,
            y1=y1,
            m0=_pct(m0, lang),
            m1=_pct(m1, lang),
            x0=_pct(x0, lang),
            x1=_pct(x1, lang),
        )
    ]
    series = []
    for code, flow in WATCH:
        part = watch[(watch["partner"] == code) & (watch["flow"] == flow)]
        if part.empty:
            continue
        name = sem.label(code, "partner", lang)
        peak = part.loc[part["share"].idxmax()]
        facts.append(
            _t(
                "e_f_partner",
                lang,
                name=name,
                flow=flow_label(flow, lang),
                y0=y0,
                y1=y1,
                s0=_pct(_cell(part, "share", year=y0), lang) if y0 in set(part["year"]) else "–",
                s1=_pct(_cell(part, "share", year=y1), lang) if y1 in set(part["year"]) else "–",
                smax=_pct(peak["share"], lang),
                ymax=int(peak["year"]),
            )
        )
        series.append(
            part.assign(
                key=f"{code}-{flow}", label=f"{name} ({flow_label(flow, lang)})", flow="total"
            )
        )
    if any(c == "GB" for c, _ in WATCH):
        facts.append(_T["e_f_uk"][lang])
    watch_lines = (
        pd.concat(series, ignore_index=True).rename(columns={"year": "period", "share": "value"})[
            ["key", "label", "flow", "period", "value"]
        ]
        if series
        else pd.DataFrame(columns=["key", "label", "flow", "period", "value"])
    )
    eu_lines = eu.rename(columns={"year": "period", "share": "value"})
    ctx.update(eu1=m1)
    china = watch[(watch["partner"] == "CN") & (watch["flow"] == "import")]
    japan = watch[(watch["partner"] == "JP") & (watch["flow"] == "import")]
    swap = ""
    if all(y in set(d["year"]) for d in (china, japan) for y in (y0, y1)):
        swap = _t(
            "a_eu_swap",
            lang,
            c0=_pct(_cell(china, "share", year=y0), lang),
            c1=_pct(_cell(china, "share", year=y1), lang),
            j0=_pct(_cell(japan, "share", year=y0), lang),
            j1=_pct(_cell(japan, "share", year=y1), lang),
        )
    china_down = (
        y0 in set(china["year"])
        and y1 in set(china["year"])
        and _cell(china, "share", year=y1) < _cell(china, "share", year=y0)
    )
    explore = QuerySpec(
        language=lang,
        intent="time_series",
        freq="A",
        flow="import",
        breakdown="partner_group",
        period_start=str(first),
        period_end=str(y1),
    )
    return Finding(
        key="europe",
        name=_T["n_eu"][lang],
        title=_t(
            "e_title_up" if m1 >= m0 else "e_title_down",
            lang,
            eu1=_pct(m1, lang),
            eu0=_pct(m0, lang),
            y0=y0,
        ),
        summary=_t("e_sum", lang, x0=_pct(x0, lang), x1=_pct(x1, lang)),
        facts=facts,
        chart_titles=[
            _t("c_eu", lang, start=first, end=y1),
            _t("c_watch", lang, start=first, end=y1),
        ],
        frames={"main": eu_lines, "watch": watch_lines},
        sql=[eu_sql, watch_sql],
        methods=[
            "EU27 = fixed composition of 2020 for every year (the United Kingdom is never EU27)",
            "undisclosed partners declared as intra-EU count as EU27, as in the assistant",
            "partner share = the partner's value ÷ all trade of that flow and year",
        ],
        limits=[guard.make("L06", "warn").message, _T["lim_consign"][lang]],
        metric_label=_t("e_m", lang, y1=y1),
        headline=_T["h_eu" if m1 > m0 and china_down else "h_eu_n"][lang],
        analysis=_why(lang, " ".join(t for t in (_t("a_eu", lang, eu1=_pct(m1, lang)), swap) if t)),
        metric_value=_pct(m1, lang),
        metric_delta=_pp(m0, m1, lang, y0),
        explore_question=_t("x_eu", lang, start=first),
        explore_spec=explore,
    )


# --- 4. price vs volume ---------------------------------------------------------------------


def _prices(
    sem: SemanticLayer, lang: str, first: int, years: list[int], ctx: dict[str, object]
) -> Finding:
    y0, y1 = years[0], years[-1]
    uv, uv_sql = _q(
        sem,
        f"""SELECT year, trade_type, flow,
       sum(value_eur) AS value_eur, sum(qty_kg) AS qty_kg,
       sum(value_eur) / sum(qty_kg) AS eur_per_kg
FROM v_lu_trade
WHERE year BETWEEN {first} AND {y1} AND qty_kg > 0
GROUP BY year, trade_type, flow
ORDER BY trade_type, flow, year""",
    )
    start = max(first, ENERGY_SHOCK - 7)
    fuel, fuel_sql = _q(
        sem,
        f"""SELECT year, sum(value_eur) AS value_eur, sum(qty_kg) AS qty_kg,
       sum(value_eur) / sum(qty_kg) AS eur_per_kg
FROM v_lu_trade
WHERE hs2 = '{ENERGY}' AND flow = 'import' AND qty_kg > 0 AND year BETWEEN {start} AND {y1}
GROUP BY year
ORDER BY year""",
    )

    def u(tt: str, flow: str, y: int) -> float:
        return _cell(uv, "eur_per_kg", trade_type=tt, flow=flow, year=y)

    ex, in_ = u("extra", "import", y1), u("intra", "import", y1)
    ratio = ex / in_ if in_ else float("nan")
    facts = [
        _t(
            "v_f_imp",
            lang,
            year=y1,
            ex=_eur_kg(ex, lang),
            in_=_eur_kg(in_, lang),
            y0=y0,
            ex0=_eur_kg(u("extra", "import", y0), lang),
            in0=_eur_kg(u("intra", "import", y0), lang),
        ),
        _t(
            "v_f_exp",
            lang,
            year=y1,
            ex=_eur_kg(u("extra", "export", y1), lang),
            in_=_eur_kg(u("intra", "export", y1), lang),
        ),
        _T["v_f_read"][lang],
    ]
    base = ENERGY_SHOCK - 1
    fuel_text = ""
    f = fuel.set_index("year")
    if base in f.index and ENERGY_SHOCK in f.index:
        r0, r1 = f.loc[base], f.loc[ENERGY_SHOCK]
        dv = 100 * (r1["value_eur"] / r0["value_eur"] - 1)
        dq = 100 * (r1["qty_kg"] / r0["qty_kg"] - 1)
        if dv > dq > 0:
            fuel_text = _t(
                "a_price_fuel", lang, y=ENERGY_SHOCK, v=fmt_pct(dv, lang), q=fmt_pct(dq, lang)
            )
        facts.append(
            _t(
                "v_f_fuel",
                lang,
                y=ENERGY_SHOCK,
                b=base,
                v=_chg(r0["value_eur"], r1["value_eur"], lang),
                q=_chg(r0["qty_kg"], r1["qty_kg"], lang),
                p=_chg(r0["eur_per_kg"], r1["eur_per_kg"], lang),
            )
        )
        if r1["eur_per_kg"] / r0["eur_per_kg"] > r1["qty_kg"] / r0["qty_kg"]:
            facts.append(_T["v_f_price"][lang])
        ctx.update(fuel_price=_chg(r0["eur_per_kg"], r1["eur_per_kg"], lang))
        if r1["eur_per_kg"] > r0["eur_per_kg"]:
            rise = 100 * (r1["eur_per_kg"] / r0["eur_per_kg"] - 1)
            ctx.update(fuel_rise=fmt_pct(rise, lang))
    # chart frames: value per kg lines, and the fuel index (base year = 100)
    tt = {"intra": _T["eu"][lang], "extra": _T["non_eu"][lang]}
    uv_lines = uv.assign(
        key=uv["trade_type"] + "-" + uv["flow"],
        label=[
            f"{flow_label(fl, lang).capitalize()}, {tt[t]}"
            for t, fl in zip(uv["trade_type"], uv["flow"], strict=True)
        ],
        flow="total",
        period=uv["year"],
        value=uv["eur_per_kg"],
    )[["key", "label", "flow", "period", "value"]]
    idx_base = base if base in f.index else (f.index.min() if not f.empty else None)
    index_rows = []
    if idx_base is not None:
        for col, key in (("value_eur", "value"), ("qty_kg", "mass"), ("eur_per_kg", "price")):
            index_rows.append(
                pd.DataFrame(
                    {
                        "key": key,
                        "label": _T[f"idx_{key}"][lang],
                        "flow": "total",
                        "period": f.index,
                        "value": 100 * f[col] / f.loc[idx_base, col],
                    }
                )
            )
    fuel_index = (
        pd.concat(index_rows, ignore_index=True)
        if index_rows
        else pd.DataFrame(columns=["key", "label", "flow", "period", "value"])
    )
    ratio_text = fmt_number(ratio, 0 if ratio >= 10 else 1, lang)
    explore = QuerySpec(
        language=lang,
        intent="time_series",
        freq="A",
        flow="import",
        products=[ENERGY],
        measure="unit_value",
        period_start=str(start),
        period_end=str(y1),
    )
    return Finding(
        key="prices",
        name=_T["n_price"][lang],
        title=_t(
            "v_title", lang, ratio=ratio_text, ex=_eur_kg(ex, lang), in_=_eur_kg(in_, lang), year=y1
        ),
        summary=_T["v_sum"][lang],
        facts=facts,
        chart_titles=[
            _t("c_uv", lang, start=first, end=y1),
            _t("c_fuel_idx", lang, b=idx_base if idx_base is not None else base),
        ],
        frames={"main": uv_lines, "fuel_index": fuel_index},
        sql=[uv_sql, fuel_sql],
        methods=[
            "value per kg = value in euros ÷ net mass in kg, over CN8 rows with a recorded mass",
            "EU / non-EU = trade type declared in the data (intra- or extra-EU at the time)",
            f"fuel index: each measure ÷ its {idx_base} value × 100",
        ],
        limits=[guard.make("L06", "warn").message, _T["lim_uv"][lang]],
        metric_label=_T["v_m"][lang],
        headline=_t("h_price", lang, ratio=ratio_text) if ratio >= 2 else _T["h_price_n"][lang],
        analysis=_why(lang, " ".join(t for t in (_T["a_price"][lang], fuel_text) if t)),
        metric_value=f"{ratio_text} ×",
        metric_delta=f"{_eur_kg(ex, lang)} vs {_eur_kg(in_, lang)} / kg",
        delta_arrow="off",
        explore_question=_t("x_fuel", lang, start=start),
        explore_spec=explore,
    )


# --- 5. main goods over time ------------------------------------------------------------------
TOP_CHAPTERS, TOP_HEADINGS = 3, 3


def _composition(sem: SemanticLayer, lang: str, years: list[int]) -> Finding:
    """Top chapters per flow and their top headings, each as % of the flow, at the snapshots.

    The chapters and headings are those of the latest year, tracked back, so every bar compares
    the same goods; confidential (masked) headings stay in the rest of their chapter.
    """
    y0, y1 = years[0], years[-1]
    chapters, chapters_sql = _q(
        sem,
        f"""SELECT year, flow, hs2, sum(value_eur) AS value_eur
FROM v_lu_trade_hs2
WHERE year IN ({_in(years)})
GROUP BY year, flow, hs2""",
    )
    totals = chapters.groupby(["year", "flow"])["value_eur"].sum()
    chapters["share"] = (
        100
        * chapters["value_eur"]
        / [totals[(y, fl)] for y, fl in zip(chapters["year"], chapters["flow"], strict=True)]
    )
    top = {
        flow: chapters[(chapters["flow"] == flow) & (chapters["year"] == y1)]
        .nlargest(TOP_CHAPTERS, "share")["hs2"]
        .tolist()
        for flow in ("export", "import")
    }
    where = " OR ".join(
        f"(flow = '{flow}' AND hs2 IN ({', '.join(repr(c) for c in codes)}))"
        for flow, codes in top.items()
    )
    headings, headings_sql = _q(
        sem,
        f"""SELECT year, flow, hs2, hs4, sum(value_eur) AS value_eur
FROM v_lu_trade
WHERE year IN ({_in(years)}) AND ({where})
GROUP BY year, flow, hs2, hs4""",
    )
    headings["share"] = (
        100
        * headings["value_eur"]
        / [totals[(y, fl)] for y, fl in zip(headings["year"], headings["flow"], strict=True)]
    )

    def share(frame: pd.DataFrame, col: str, code: str, flow: str, year: int) -> float:
        part = frame[(frame[col] == code) & (frame["flow"] == flow) & (frame["year"] == year)]
        return float(part["share"].sum())

    rows = []  # one row per flow × year × chapter × slot (3 headings + the rest)
    picked = []  # (flow, hs4) of the headings shown
    for flow, codes in top.items():
        for hs2 in codes:
            latest = headings[
                (headings["flow"] == flow)
                & (headings["hs2"] == hs2)
                & (headings["year"] == y1)
                & ~headings["hs4"].str.contains("X")
            ].nlargest(TOP_HEADINGS, "value_eur")["hs4"]
            picked += [(flow, h) for h in latest]
            for year in years:
                total = share(chapters, "hs2", hs2, flow, year)
                shown = 0.0
                for slot, hs4 in enumerate(latest, start=1):
                    value = share(headings, "hs4", hs4, flow, year)
                    shown += value
                    rows.append((flow, year, hs2, slot, hs4, value))
                rows.append((flow, year, hs2, 0, "", max(total - shown, 0.0)))
    main = pd.DataFrame(rows, columns=["flow", "year", "hs2", "slot", "hs4", "share"])
    main["chapter"] = main["hs2"].map(lambda c: sem.label(c, "product", lang))
    main["label"] = [
        sem.label(h, "product", lang) if h else _T["rest_chapter"][lang] for h in main["hs4"]
    ]

    # headline: the heading that moved most; analysis: the fastest riser among them
    moves = pd.DataFrame(
        [
            (flow, h, share(headings, "hs4", h, flow, y0), share(headings, "hs4", h, flow, y1))
            for flow, h in picked
        ],
        columns=["flow", "hs4", "s0", "s1"],
    ).assign(change=lambda d: d["s1"] - d["s0"])
    mover = moves.loc[moves["change"].abs().idxmax()]
    riser = moves.loc[moves["change"].idxmax()]

    def flow_text(flow: str) -> str:
        return flow_label(flow, lang)

    def chapter_list(flow: str) -> str:
        return ", ".join(
            f"{sem.label(c, 'product', lang)} ({_pct(share(chapters, 'hs2', c, flow, y1), lang)})"
            for c in top[flow]
        )

    def top_sum(flow: str, year: int) -> str:
        return _pct(sum(share(chapters, "hs2", c, flow, year) for c in top[flow]), lang)

    explore = QuerySpec(
        language=lang,
        intent="time_series",
        freq="A",
        flow="export",
        breakdown="product",
        products=top["export"],
        period_start=str(y0),
        period_end=str(y1),
    )
    return Finding(
        key="composition",
        name=_T["n_comp"][lang],
        title=_t(
            "t_comp", lang, y1=y1, exports=chapter_list("export"), imports=chapter_list("import")
        ),
        summary=_t("s_comp", lang, y1=y1),
        facts=[
            _t(
                "h_comp",
                lang,
                name=sem.label(r.hs4, "product", lang),
                s0=_pct(r.s0, lang),
                s1=_pct(r.s1, lang),
                flow=flow_text(r.flow),
                y0=y0,
                y1=y1,
            )
            + "."
            for r in moves.sort_values("change").itertuples()
        ],
        chart_titles=[_t("c_comp", lang, years=", ".join(str(y) for y in years))],
        frames={"main": main},
        sql=[chapters_sql, headings_sql],
        methods=[
            f"chapters and headings = the {TOP_CHAPTERS} largest HS2 chapters of each flow in "
            f"{y1}, and the {TOP_HEADINGS} largest disclosed HS4 headings of each, tracked back",
            "share = value ÷ all exports (or imports) of that year",
            "rest of the chapter = chapter share − its three headings (confidential codes included)",
        ],
        limits=[guard.make("L06", "warn").message, _T["lim_hs4"][lang]],
        headline=_t(
            "h_comp",
            lang,
            name=sem.label(mover["hs4"], "product", lang),
            s0=_pct(mover["s0"], lang),
            s1=_pct(mover["s1"], lang),
            flow=flow_text(mover["flow"]),
            y0=y0,
            y1=y1,
        ),
        analysis=_why(
            lang,
            _t(
                "a_comp",
                lang,
                e0=top_sum("export", y0),
                e1=top_sum("export", y1),
                i0=top_sum("import", y0),
                i1=top_sum("import", y1),
                y0=y0,
                y1=y1,
                name=sem.label(riser["hs4"], "product", lang),
                s0=_pct(riser["s0"], lang),
                s1=_pct(riser["s1"], lang),
                flow=flow_text(riser["flow"]),
            ),
        ),
        metric_label=_t(
            "m_comp",
            lang,
            name=sem.label(mover["hs4"], "product", lang),
            flow=flow_text(mover["flow"]),
            y0=y0,
        ),
        metric_value=(
            ("+" if mover["change"] >= 0 else "−")
            + f"{fmt_number(abs(mover['change']), 1, lang)} {_T['k_pp'][lang]}"
        ),
        metric_delta=f"{_pct(mover['s0'], lang)} → {_pct(mover['s1'], lang)}",
        delta_arrow="off",
        explore_question=_t("x_comp", lang, start=y0),
        explore_spec=explore,
    )


# --- 6. conclusion ----------------------------------------------------------------------------


def _conclusion(lang: str, ctx: dict[str, object]) -> Finding:
    v = ctx
    facts = [
        _t(
            "c_f_div",
            lang,
            h0=_hhi(v["hx0"], lang),
            h1=_hhi(v["hx1"], lang),
            nb=_pct(v["nb"], lang),
            names=v["nb_names"],
            y1=v["y1"],
        ),
        _t("c_f_res", lang, shock=v["shock"]),
        _t("c_f_eu", lang, eu1=_pct(v["eu1"], lang)),
    ]
    if "fuel_top" in v:
        facts.append(
            _t("c_f_prep", lang, share=_pct(v["fuel_share"], lang), top=v["fuel_top"], year=v["y1"])
        )
    fuel = (
        _t("w_fuel_t", lang, share=_pct(v["fuel_share"], lang), top=v["fuel_top"])
        if "fuel_top" in v
        else ""
    )
    if "fuel_rise" in v:
        fuel += " " + _t("w_fuel_p", lang, y=ENERGY_SHOCK, p=v["fuel_rise"])
    tiles = [
        (str(v["weak_name"]), str(v["weak_tile"])),
        (_T["w_routes"][lang], _t("w_routes_t", lang, nb=_pct(v["nb"], lang), names=v["nb_names"])),
    ]
    if fuel:
        tiles.append((_T["w_fuel"][lang], fuel.strip()))
    rows = [list(_T[k][lang]) for k in ("o1", "o2", "o3", "o4")]
    rows[1][0] = rows[1][0].format(name=v["weak_name"])
    options = pd.DataFrame(
        rows, columns=[_T[c][lang] for c in ("col_finding", "col_option", "col_monitor")]
    )
    return Finding(
        key="conclusion",
        name=_T["n_end"][lang],
        title=_T["c_title"][lang],
        summary=_T["c_sum"][lang],
        headline=_T["h_end"][lang],
        tiles=tiles,
        facts=facts,
        chart_titles=[],
        frames={"main": options},
        sql=[],
        methods=["the conclusion reuses the numbers of the four findings above"],
        limits=[],
        note=_T["c_note"][lang],
    )


def build_findings(sem: SemanticLayer, lang: str = "en") -> tuple[str, str, list[Finding]]:
    """The story tab: a hero line, an intro, four findings and a conclusion, in one language."""
    cov = sem.coverage
    year = cov.latest_complete_year
    first = cov.first_period.year
    years = snapshot_years(first, year)
    ctx: dict[str, object] = {}  # numbers the conclusion reuses
    findings = [
        _diversification(sem, lang, years, ctx),
        _shocks(sem, lang, first, year, ctx),
        _europe(sem, lang, first, years, ctx),
        _prices(sem, lang, first, years, ctx),
        _composition(sem, lang, years),
    ]
    if "energy_lag" in ctx and "fuel_rise" in ctx:
        lag = _t(
            "a_shock_lag", lang, ylag=ctx["energy_lag"], yshock=ENERGY_SHOCK, p=ctx["fuel_rise"]
        )
        shocks = findings[1]
        shocks.analysis = f"{shocks.analysis} {lag}" if shocks.analysis else _why(lang, lag)
    findings.append(_conclusion(lang, ctx))
    hero = _T["hero" if ctx.get("story") else "hero_n"][lang]
    return hero, _T["intro"][lang], findings


@dataclass
class Challenge:
    """The problem the Overview answers: first tab and first slide (texts filled from the data)."""

    kicker: str
    statement: str
    context: list[tuple[str, str, str]]  # (tint key, title, text)
    task: str
    approach_title: str
    approach: list[tuple[str, str, str]]  # (icon, title, text)


def build_challenge(
    sem: SemanticLayer, lang: str, findings: list[Finding], about: dict[str, object]
) -> Challenge:
    """Frame the decision question with the latest numbers: trade size, shocks, data scale."""
    year = sem.coverage.latest_complete_year
    nb_codes = ", ".join(f"'{c}'" for c in NEIGHBOURS)
    row = _q(
        sem,
        f"""SELECT sum(value_eur) FILTER (WHERE flow = 'export') AS exports,
       sum(value_eur) FILTER (WHERE flow = 'import') AS imports,
       sum(value_eur) FILTER (WHERE partner IN ({nb_codes})) AS neighbours,
       count(DISTINCT partner) FILTER (WHERE NOT partner_is_special AND value_eur > 0)
         AS partners
FROM v_lu_trade_hs2
WHERE year = {year}""",
    )[0].iloc[0]
    exp, imp = float(row["exports"] or 0.0), float(row["imports"] or 0.0)
    nb_share = 100 * float(row["neighbours"] or 0.0) / (exp + imp) if exp + imp else 0.0
    partners = int(row["partners"])
    episodes = next((f.frames.get("episodes") for f in findings if f.key == "shocks"), None)
    worst = (
        float(episodes.loc[episodes["series"] == _T["all_exports"][lang], "change"].min())
        if episodes is not None and not episodes.empty
        else 0.0
    )
    first = about["first_period"].year
    return Challenge(
        kicker=_T["ch_kicker"][lang],
        statement=_t("ch_statement", lang, total=fmt_eur(exp + imp, lang), partners=partners),
        context=[
            (
                "diversification",
                _T["ch_open_t"][lang],
                _t(
                    "ch_open",
                    lang,
                    year=year,
                    exp=fmt_eur(exp, lang),
                    imp=fmt_eur(imp, lang),
                    gap=fmt_eur(abs(imp - exp), lang),
                    nb=_pct(nb_share, lang),
                ),
            ),
            (
                "shocks",
                _T["ch_shocks_t"][lang],
                _t("ch_shocks", lang, worst=fmt_pct(abs(worst), lang)),
            ),
            (
                "europe",
                _T["ch_evidence_t"][lang],
                _t(
                    "ch_evidence",
                    lang,
                    records=fmt_number(about["records"], 0, lang),
                    products=fmt_number(about["products"], 0, lang),
                    partners=about["partners"],
                    first=first,
                ),
            ),
        ],
        task=_T["ch_task"][lang],
        approach_title=_T["ch_approach"][lang],
        approach=[
            (":material/database:", _T["ch_a1_t"][lang], _t("ch_a1", lang, first=first)),
            (":material/insights:", _T["ch_a2_t"][lang], _T["ch_a2"][lang]),
            (":material/verified:", _T["ch_a3_t"][lang], _T["ch_a3"][lang]),
        ],
    )
