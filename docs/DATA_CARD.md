# Data Card — Luxembourg External Trade in Goods

The single reference for **where our data comes from, what it covers, and what its limits are**. Every chart in the app should be read against this page.
Figures marked *(measured)* were verified on the bulk files of **Dec 2025** and **Jul 2026**, downloaded on 14 Oct 2026.

---

## 1. Source

| Item | Value |
|---|---|
| Dataset | Eurostat Comext **DS-045409**, "EU trade since 1988 by HS2-4-6 and CN8" |
| Publisher | Eurostat (data produced by national statistical institutes, incl. STATEC for Luxembourg) |
| Access method used | **Comext bulk download**: monthly files `full_v2_YYYYMM.7z` |
| Bulk location | `https://ec.europa.eu/eurostat/api/dissemination/files/?sort=1&dir=comext%2FCOMEXT_DATA%2FPRODUCTS` |
| Download pattern | `…/files/?sort=1&downfile=comext%2FCOMEXT_DATA%2FPRODUCTS%2Ffull_v2_YYYYMM.7z` |
| Cross-check source | Comext API (`/eurostat/api/comext/dissemination/statistics/1.0/data/DS-045409`), used only for validation |
| Licence | Eurostat reuse policy: free reuse with attribution ([policy](https://ec.europa.eu/eurostat/about-us/policies/copyright)) |
| Attribution text | *"Source: Eurostat, Comext DS-045409, extracted YYYY-MM-DD; calculations by The Outliers."* |

### Why bulk rather than the API (team decision, 14 Oct 2026)

- The full CN8 detail plus **extra product classifications** (SITC, CPA, BEC, BEC5, HS section) come in every row. The API only offers the HS/CN hierarchy.
- There are **no row limits**. The API refuses requests above 5 million rows and puts heavy ones in a queue.
- The app runs on **local files**, so there are no network failures during the demo.
- Bulk and API **agree exactly** *(measured, Dec 2025, LU, M€)*:

  | | Intra-EU import | Intra-EU export | Extra-EU import | Extra-EU export |
  |---|---|---|---|---|
  | Bulk | 1,817.4 | 1,062.4 | 350.3 | 277.6 |
  | API | 1,817.4 | 1,062.4 | 350.3 | 277.6 |

## 2. File structure (bulk `full_YYYYMM.dat`, comma-separated, with header)

| Column | Meaning | Notes |
|---|---|---|
| `REPORTER` | Declaring country (ISO-2) | We keep `LU`, plus per-country summaries for benchmarking |
| `PARTNER` | Partner country (ISO-2) | No aggregates such as WORLD or EU27 in the file. Derive them (see §4.6) |
| `TRADE_TYPE` | `I` = intra-EU, `E` = extra-EU | |
| `PRODUCT_NC` | CN8 code, `TOTAL`, or a **masked confidential code** | Read as **text** (leading zeros!) |
| `PRODUCT_SITC`, `PRODUCT_CPA21`, `PRODUCT_CPA22`, `PRODUCT_BEC`, `PRODUCT_BEC5` | Other product classifications linked to the CN8 code | Also masked (`X`) for confidential rows |
| `PRODUCT_SECTION` | HS section `01`–`21`; `TO` = total; `XX` = confidential | |
| `FLOW` | `1` = import, `2` = export | |
| `STAT_PROCEDURE` | Statistical procedure code | Values `1` and `2` observed. **Sum all of them** to match totals |
| `SUPPL_UNIT` | Supplementary unit (`NO_SU`, `PST` = pieces, `L`, `M2`, …) | Differs by product. Not additive across products |
| `PERIOD` | `YYYYMM` (monthly files) or `YYYY52` (annual files) | |
| `VALUE_EUR` | Trade value in euros | **Main indicator** |
| `VALUE_NAC` | Value in national currency | Identical to EUR for Luxembourg |
| `QUANTITY_KG` | Net mass in **kg** | Unlike the API, which uses 100 kg |
| `QUANTITY_SUPPL_UNIT` | Quantity in the supplementary unit | |

Volume *(measured)*: one monthly file holds about 2.9 M rows for all EU reporters (240 MB unzipped, 26–45 MB as 7z). **Luxembourg has about 62,000 rows per month** with intra- and extra-EU combined.

## 3. Coverage

| Dimension | Coverage |
|---|---|
| Time (bulk monthly) | **Jan 2002 → Jul 2026** (295 files, about 11.2 GB compressed in total) |
| Time (bulk annual) | 2002 → 2025 (`full_v2_YYYY52.7z`, 24 files, about 2 GB) |
| Latest complete month (intra + extra) | **Dec 2025** at extraction time. See §4.3 |
| Partners | About 250 countries/territories (ISO-2) |
| Products | All CN8 codes valid in each year, plus masked confidential codes |
| Indicators | Value (EUR), net mass (kg), supplementary quantity |

---

## 4. Limitations and how we handle them

### 4.1 Series start in 2002, not 1988 or 1999

- DS-045409 as a whole starts in 1988. However, **Luxembourg was reported jointly with Belgium (BLEU) until 1998**, so LU-only figures exist **from 1999**.
- The **bulk files start in January 2002**. Luxembourg's 1999–2001 data is only available through the API.
- **Decision:** our time series start in **2002**. That still gives 24 years, including the 2008–09 crisis, COVID-19 and the 2022 energy shock. We don't merge in the API for 1999–2001, to keep a single, simple source. It can be added later if needed.
- **In the app:** the time axis starts in 2002, and the footnote reads *"Data from 2002 (bulk Comext files)."*

### 4.2 Confidential trade (masked product codes)

To protect individual companies, some flows are **not published at full CN8 detail**. Instead of being removed, they are **pooled into masked codes** at a higher level:

| Masked pattern | Meaning | Example *(measured, Dec 2025)* |
|---|---|---|
| `CCXXXXXX` | Confidential within HS chapter `CC` | `27XXXXXX` (mineral fuels): **77.5 M€** in one month |
| `CCCCXXXX` | Confidential within HS4 heading `CCCC` | `3920XXXX` (plastic plates/sheets): 4.4 M€ |
| `99XXXXXX` | Confidential, chapter not disclosed | 7.0 M€ |
| `PRODUCT_SECTION = XX`, `X` in SITC/BEC fields | Same confidentiality reflected in the other classifications | |

Key facts *(measured, Dec 2025, LU)*:
- **Nothing is lost at total level:** CN8 detail + masked codes = `TOTAL`, exactly, for every trade type and flow.
- **The share hidden at CN8 level is small but not trivial:** **4.9 % of imports** and **1.7 % of exports**. It is concentrated in a few chapters, mainly energy (27), chemicals (28, 38) and vehicles (87).
- About 60 distinct masked codes appear in one month.

**How we handle it:**
- During processing, flag masked rows with `is_confidential = True`. Never drop them.
- **At HS2 level and above, use masked rows normally.** `27XXXXXX` belongs to chapter 27, so chapter totals stay correct. `99XXXXXX` goes into an **"Undisclosed"** category.
- **At HS4, HS6 and CN8 level**, show masked value as a separate **"Confidential"** slice inside its parent, so drill-downs still add up.
- **Never sum `TOTAL` rows together with detail rows** (double counting). `TOTAL` is only used for reconciliation tests.
- **In the app:** a tooltip or footnote states *"x % of this value is confidential at this level of detail."*

### 4.3 The latest months have extra-EU trade only

- Intra-EU data (Intrastat) is published **later** than extra-EU data (customs). At extraction time, **Jan–Jul 2026 contain extra-EU only**, so totals for those months look about 75 % too low *(measured: Jul 2026 file has only `TRADE_TYPE = E` for LU)*.
- **How we handle it:** the pipeline finds the **latest complete month** (both `I` and `E` present) automatically. The overview pages stop there. Extra-EU-only views may show later months, with a clear "provisional / extra-EU only" label.

### 4.4 Product codes change over time

- **CN8 codes change every year**, and **HS is revised about every 5 years** (2002, 2007, 2012, 2017, 2022). A CN8 code can split, merge or disappear, which breaks long series.
- **How we handle it:**
  - Long time series (2002 → today) are shown at **HS2 / section** level, which is stable.
  - HS4 and HS6 are used for medium ranges.
  - **CN8 is used for recent cross-sections** (e.g. the last 12 months or the last year), not for 24-year trends.
  - Labels come from the code list of the matching year.

### 4.5 Values are nominal; quantities are incomplete

- Values are in **current euros**, with no price adjustment. Growth includes inflation. We say "nominal" in captions.
- `QUANTITY_KG` is **zero in about 4 % of rows** *(measured)*, and supplementary units differ by product.
- **How we handle it:** unit values (EUR/kg) are only computed where quantity > 0, only within one product, and are labelled as an approximate price indicator.

### 4.6 No partner aggregates in the bulk files

- The bulk files list individual partner countries only. **World / intra-EU / extra-EU totals must be derived**: World = all partners; intra/extra from `TRADE_TYPE`.
- **Brexit:** the United Kingdom is intra-EU before 2021 and extra-EU from 2021. Separate `full_partxixu_v2_*` files exist for Northern Ireland (`XI`) / UK excluding NI (`XU`) after 2021.
- **How we handle it:**
  - For long-term intra/extra comparisons we use a **fixed EU27 (2020) composition**, defined in `config.py`, and state this in captions.
  - Whether we need the `partxixu` files is a check during the download step.

### 4.7 Revisions and vintages

- Recent months are **provisional** and are revised in later releases. Eurostat republishes files.
- **How we handle it:** every download is recorded in `data/raw/manifest.json` (file name, server date, SHA-256, download time). The app displays the extraction date.

### 4.8 Methodological differences and mirror asymmetries

- Intra-EU trade comes from **Intrastat**, where small traders below a threshold are exempt and their trade is estimated. Extra-EU trade comes from **customs declarations**. The quality and detail of the two differ slightly.
- **Asymmetries:** "LU exports to X" ≠ "X imports from LU" in X's own statistics, because of valuation (FOB vs CIF), timing, transit and the "Rotterdam effect", where goods are recorded against the EU entry country.
- **How we handle it:** we always show **Luxembourg as reporter**. When comparing with other countries, we compare *their reported totals*, never mirror flows. This is stated in the methodology.

### 4.9 Small-economy volatility

- Luxembourg's trade is concentrated: a few firms and products can create large monthly spikes. Confidentiality (§4.2) also hits Luxembourg harder than large countries.
- **How we handle it:** spikes are **flagged and explained**, never deleted (see the Outlier Radar). Seasonally adjusted and 12-month rolling views are offered next to raw monthly data.

---

## 5. Processing summary (what we change, and what we don't)

| Step | Action |
|---|---|
| Download | Fetch each monthly 7z file, record it in the manifest, extract it |
| Filter | Keep `REPORTER = LU` (all detail), plus per-reporter summaries for EU comparison |
| Clean | Codes as text; flag `is_confidential`; map flows and trade types; parse periods |
| Never | Delete masked rows, edit values by hand, or mix `TOTAL` rows with detail rows |
| Validate | Detail + masked = `TOTAL` per month, trade type and flow; spot-check against the API |
| Store | Parquet in `data/processed/` (raw files are git-ignored and re-downloadable) |

## 6. Open points

- [ ] Confirm the meaning of the `STAT_PROCEDURE` codes in the Eurostat metadata
- [ ] Decide whether `full_partxixu_v2_*` files are needed for the UK split after 2021
- [ ] Measure the size of LU's processed Parquet → decide what can be committed or published for the hosted app
- [ ] Re-measure the confidential share across all years (the Dec 2025 figures are one month only)
