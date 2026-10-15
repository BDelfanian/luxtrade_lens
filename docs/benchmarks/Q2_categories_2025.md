# Benchmark Q2 — Main categories of goods exported and imported, 2025

Expected answer and justification for golden entry `Q2_categories_2025` in [tests/golden/questions.yaml](../../tests/golden/questions.yaml).
*Source: Eurostat, Comext DS-045409, extracted 2026-10-14 (dataset updated 2026-09-15); calculations by The Outliers.*

## Answer

**Luxembourg mostly exports and imports industrial goods.** Five HS2 chapters lead in both directions:

- machinery (84)
- vehicles (87)
- plastics (39)
- electrical equipment (85)
- iron and steel (72)

On the **import** side, **mineral fuels (27)** is the third-largest chapter and the largest net import.

| Rank | Exports 2025 (16.3 bn €) | Imports 2025 (25.1 bn €) |
|---|---|---|
| 1 | 84 Machinery: 2,038.5 M€ (12.5 %) | 87 Vehicles and parts: 3,318.0 M€ (13.2 %) |
| 2 | 39 Plastics: 1,575.5 (9.7 %) | 84 Machinery: 2,885.7 (11.5 %) |
| 3 | 87 Vehicles and parts: 1,556.3 (9.6 %) | 27 Mineral fuels: 2,231.6 (8.9 %) |
| 4 | 85 Electrical equipment: 1,506.8 (9.3 %) ¹ | 85 Electrical equipment: 1,972.1 (7.9 %) ¹ |
| 5 | 72 Iron and steel: 1,120.3 (6.9 %) | 39 Plastics: 1,292.9 (5.2 %) |
| 6–10 | 40 Rubber, 73 Articles of iron/steel, 04 Dairy, 76 Aluminium, 56 Nonwovens | 72 Iron and steel, 30 Pharmaceuticals, 40 Rubber, 22 Beverages, 04 Dairy |

¹ Inflated in 2025 by a one-off flow. See point 4 below.

**By HS section** (the friendlier top level):

- **Exports:** machinery and electrical equipment (XVI) 21.8 %, base metals (XV) 16.8 %, plastics and rubber (VII) 14.9 %, transport equipment (XVII) 10.5 %.
- **Imports:** machinery and electrical equipment (XVI) 19.4 %, transport equipment (XVII) 15.9 %, mineral products incl. fuels (V) 9.5 %, base metals (XV) 9.5 %.

## Justification

1. **A clear two-way industrial profile.** Machinery, vehicles, plastics, electrical equipment and iron and steel all appear in the top 6 of **both** flows. Luxembourg buys and sells within the same industries.
2. **Net position by chapter** (exports − imports):
   - **Largest net imports:** fuels (27, −2.2 bn €), vehicles (87, −1.8 bn €), machinery (84, −0.8 bn €) and pharmaceuticals (30, −0.6 bn €).
   - **Largest net exports:** articles of iron or steel (73, +336 M€), plastics (39, +283 M€), nonwovens (56, +177 M€), footwear (64, +177 M€) and iron and steel (72, +167 M€).
3. **Moderately concentrated.** The top 5 chapters make up 48 % of exports and 47 % of imports. The top 10 make up 68 % and 62 %.
4. **Stable apart from two one-off flows.** The top-5 import chapters are the same in 2024 and 2025. The 2025 changes come from the flows already found in Q1:
   - **Exports of 85** grew +128 %. Telephones (HS 8517) went from 90 M€ to 935 M€, mostly to France in Sep–Dec. Without that increase, chapter 85 exports would be about 663 M€, flat on 2024 and around rank 8. The **underlying export top 5 is 84, 39, 87, 72, 40**.
   - **Imports of 84** grew +53%, mostly lifting machinery (8428) from Japan: +688 M€.
   - **Imports of 85** grew +50%, mostly telephones (8517) from China: +597 M€.
   - **Fuel imports (27)** fell 15 %, so fuels dropped from rank 2 to rank 3.

## Checks performed

| Check | Result |
|---|---|
| Sum of HS2 chapters = `TOTAL` (both flows, 2024 and 2025) | Exact. Confidential codes such as `27XXXXXX` are counted in their chapter |
| Undisclosed chapter 99 | 99.9 M€ of exports (0.6 %) and 15.2 M€ of imports (0.1 %). Shown as "Undisclosed", not ranked |
| World totals match Q1 | Yes (16,253.9 / 25,097.9 M€) |
| 2025 complete for intra- and extra-EU | Yes: Dec 2025 is the latest complete month |

## Caveats to state in the answer

- Values are **nominal**. The fall in fuel imports partly reflects prices, not only volumes. Volumes would need `qty_kg`.
- The ranking is at **HS2**. Labels come from the Eurostat CN code list, shortened for display.
- Figures from 2025 are recent and may still be **revised**.
- **Open:** Kasra should re-compute these figures from `trade.parquet` with `reference_sql` once the pipeline is done.
- **Out of scope:** the question's second half, how the patterns changed over time. It fits a separate golden entry (2002 → 2025, HS2 or section, stacked area).
