# Benchmark Q1 — Luxembourg's main trading partners in 2025

Expected answer and justification for golden entry `Q1_partners_2025` in [tests/golden/questions.yaml](../../tests/golden/questions.yaml).
*Source: Eurostat, Comext DS-045409, extracted 2026-10-14 (dataset updated 2026-09-15); calculations by The Outliers.*

## Answer

**Germany, Belgium and France are Luxembourg's main trading partners in 2025.** Together they account for **64.4 %** of Luxembourg's goods trade (exports + imports = 41.4 bn €). The Netherlands (5.7 %) and Italy (3.6 %) complete the top five, which together cover 73.7 %.

| Rank | Exports (16.3 bn €) | Imports (25.1 bn €) | Total trade (41.4 bn €) |
|---|---|---|---|
| 1 | Germany 3,990.7 M€ (24.6 %) | Belgium 7,805.9 M€ (31.1 %) | Germany 10,801.1 M€ (26.1 %) |
| 2 | France 3,125.0 (19.2 %) | Germany 6,810.4 (27.1 %) | Belgium 9,946.0 (24.1 %) |
| 3 | Belgium 2,140.1 (13.2 %) | France 2,777.8 (11.1 %) | France 5,902.8 (14.3 %) |
| 4 | Netherlands 967.0 (5.9 %) | Netherlands 1,393.0 (5.6 %) | Netherlands 2,360.1 (5.7 %) |
| 5 | Italy 665.5 (4.1 %) | Japan 1,127.1 (4.5 %) | Italy 1,485.9 (3.6 %) |
| 6–10 | ES, US, PL, GB, AT | IT, CN, US, PL, ES | JP, US, CN, PL, ES |

## Justification

1. **Robust across every measure.** Germany, Belgium, France and the Netherlands are the top four for exports, imports and total trade. The top three are the same as in 2024.
2. **Asymmetric roles.** Germany is the first **export** market. Belgium is the first **import** source, led by vehicles (HS 87, 1.6 bn €) and fuels (HS 27, 1.1 bn €). Luxembourg runs its largest deficits with Belgium (−5.7 bn €) and Germany (−2.8 bn €). France is the only top-5 partner with a surplus (+0.3 bn €).
3. **The EU dominates.** 83.1 % of exports and 86.6 % of imports are intra-EU27.
4. **Ranks 5–10 are less stable in 2025, so the tool should flag them.**
   - **Japan** goes from #11 to #5 in imports (+406 %). Almost all of the rise is lifting and handling machinery (HS 8428): 744 M€ in 2025 against 49 M€ in 2024, mostly from two shipments in July and October.
   - **China** goes from #14 to #7 in imports. The driver is telephone sets (HS 8517): 620 M€, against 12 M€ in 2024, all in Sep–Dec 2025.
   - In the same months, telephone exports to **France** reached 776 M€, against 15 M€ in 2024. This looks like goods passing through Luxembourg on their way to France. Without this flow, exports to France would still be 2.35 bn €, so France stays #2 ahead of Belgium (2.14 bn €). **The top-4 ranking does not depend on these one-off flows.**

## Checks performed

| Check | Result |
|---|---|
| Sum of country partners = `WORLD` aggregate (both flows) | Exact |
| Sum of 12 monthly 2025 values = annual value (WORLD + top 10, both flows) | Exact |
| 2025 complete for intra- and extra-EU | Yes: Dec 2025 is the latest complete month ([DATA_CARD §4.3](../DATA_CARD.md)) |
| Undisclosed partners (`QV`, `QY`, `QZ`, …) | 1.6 % of exports and 0.2 % of imports. Kept in the totals, never ranked as a country |

## Caveats to state in the answer

- Values are **nominal** (current euros). Shares and rankings are not affected by this.
- The figures show **Luxembourg as the reporter**. Partner countries' mirror statistics will differ ([DATA_CARD §4.8](../DATA_CARD.md)).
- Figures from 2025 are recent and may still be **revised** by Eurostat.
- **Open:** Kasra should re-compute these figures from `trade.parquet` with `reference_sql` once the pipeline is done. Until then, they come from the Comext API, which matched the bulk files exactly for Dec 2025 ([DATA_CARD §1](../DATA_CARD.md)).
