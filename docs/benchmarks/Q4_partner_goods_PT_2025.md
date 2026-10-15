# Benchmark Q4 — Main goods traded with a given partner (Portugal), 2025

Expected answer and justification for golden entry `Q4_partner_goods_PT_2025` in [tests/golden/questions.yaml](../../tests/golden/questions.yaml).
Portugal is the test case. The same drill-down must work for any partner.
*Source: Eurostat, Comext DS-045409, extracted 2026-10-14 (dataset updated 2026-09-15); calculations by The Outliers.*

## Answer

**Luxembourg sells Portugal industrial goods and buys mainly food and drink.** In 2025, Luxembourg traded 177.7 M€ of goods with Portugal: 80.7 M€ of exports and 96.9 M€ of imports, a deficit of 16.2 M€. Portugal is a small partner: rank 21 by total trade, 0.4 % of Luxembourg's goods trade.

| Rank | Exports to Portugal (80.7 M€) | Imports from Portugal (96.9 M€) |
|---|---|---|
| 1 | 84 Machinery: 11.85 M€ (14.7 %) | 22 Beverages: 16.76 M€ (17.3 %) |
| 2 | 24 Tobacco: 7.67 (9.5 %) | 03 Fish: 6.06 (6.3 %) |
| 3 | 30 Pharmaceuticals: 7.54 (9.3 %) | 09 Coffee, tea, spices: 5.97 (6.2 %) |
| 4 | 87 Vehicles: 7.28 (9.0 %) | 16 Meat and fish preparations: 5.60 (5.8 %) |
| 5 | 73 Articles of iron or steel: 6.81 (8.4 %) | 02 Meat: 5.50 (5.7 %) |
| 6–10 | 39 Plastics, 72 Iron and steel, 85 Electrical, 33 Cosmetics, 40 Rubber | 94 Furniture, 19 Pastry/cereals, 61 Knitted apparel, 20 Fruit/veg preparations, 04 Dairy |

**What sits behind the chapters (HS4):**

- **Exports:**
  - Tobacco is all **cigarettes** (2402, 7.67 M€).
  - Pharmaceuticals are all **medicaments** (3004, 7.54 M€).
  - Vehicles are mostly **motor cars** (8703, 4.47 M€).
  - Machinery is led by **lifting machinery** (8428, 2.74 M€).
- **Imports:**
  - Beverages are mostly **wine** (2204, 10.56 M€) and beer (2203, 3.35 M€).
  - Chapter 09 is almost all **coffee** (0901, 5.80 M€).
  - Meat is led by **poultry** (0207).

**Example drill-down, imports of wine (HS4 → HS6 → CN8):**

```text
2204 Wine                                 10.56 M€
└─ 220421 Wine in containers ≤ 2 l          8.86 M€  (84 %)
   ├─ 22042180 PGI wine, ≤ 15 % vol         2.21 M€
   ├─ 22042169 Dão, Bairrada, Douro wine    1.59 M€
   ├─ 22042189 Port, PDO/PGI                0.97 M€
   └─ Other (45 CN8 codes)                  …
```

Wine is the largest single product flow between the two countries, in either direction.

## Justification

1. **Two different trade profiles.** All top 10 export chapters are manufactured goods. Seven are industrial (machinery, vehicles, steel, plastics, rubber, electrical equipment); the other three are medicines, cosmetics and cigarettes. 8 of the top 10 import chapters are food, drink or agricultural products (chapters 02–22). The rest are furniture and clothing.
2. **The exports match Luxembourg's overall profile** (see the Q2 benchmark): machinery, steel articles, plastics and vehicles. **The imports do not.** Portugal's own mix shows instead: wine, fish, meat products and coffee.
3. **Imports are more spread out than exports.** It takes **18 chapters** to reach 80 % of imports, against **11** for exports. The "top-N + Other" view therefore needs a larger N for imports. This is a good test of the Pareto rule.
4. **Small partner, so the figures move a lot from year to year.** Between 2024 and 2025, exports fell 13 %: machinery fell 4.4 M€ and steel articles 4.2 M€. Imports rose 8 %. The balance went from a surplus of +2.9 M€ to a deficit of −16.2 M€. A change of a few M€ in one chapter can change the ranking, so YoY changes should be treated as indicative.

## Checks performed

| Check | Result |
|---|---|
| Sum of HS2 = partner `TOTAL` | Imports exact. Exports differ by 0.01 M€ (rounding/special codes) |
| Sum of CN8 under 2204 = HS4 2204 | Exact (10.56 M€, 48 codes) |
| Visible HS4 vs chapter 22 | 0.29 M€ is not visible at HS4 level. The app must show it as a **"Confidential"** slice ([DATA_CARD §4.2](../DATA_CARD.md)) |
| Partner rank and share | Consistent with the Q1 ranking data (same extraction) |

## Caveats to state in the answer

- Values are **nominal** euros, and Luxembourg is the **reporter**. Portugal's own statistics will show different figures (mirror asymmetries).
- CN8 labels change from year to year. The drill-down uses 2025 codes only.
- Figures from 2025 are recent and may still be **revised**.
- **Open:** Kasra should re-compute these figures from `trade.parquet` with `reference_sql` once the pipeline is done.
