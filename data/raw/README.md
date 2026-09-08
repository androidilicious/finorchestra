# Raw data inventory

Downloaded 2026-09-06. Everything here is public and free. Machine-generated file-by-file manifests with sheet names, shapes, and columns are in `epu/_inventory_epu.csv` and `gpr/_inventory_gpr.csv`.

## fred/  (Federal Reserve Economic Data, St. Louis Fed)

**What the pipeline reads: `fred/vintages/*.parquet`** (one table per configured series, plus a `.mode` sidecar), built by `finorchestra pull`. Each row is an interval `observation_date, value, realtime_start, realtime_end`: the value that was published for that observation between those two dates. Revised statistics are reconstructed from weekly ALFRED vintages (every Friday since 2005-01-07, 12 vintages per call, the endpoint's silent cap); unrevised daily market series are stored once with `realtime_start = observation_date` and given a one-business-day availability lag at load time.

| Series | Name in pipeline | Kind | Frequency | Availability |
|---|---|---|---|---|
| UNRATE | unemployment_rate | revised statistic | monthly since 1948 | Friday vintage in which it first appeared |
| PAYEMS | nonfarm_payrolls | revised statistic | monthly since 1939 | same (about 6 vintage intervals per observation) |
| CPIAUCSL | cpi | revised statistic | monthly since 1947 | same |
| INDPRO | industrial_production | revised statistic | monthly since 1919 | same (about 19 vintage intervals per observation) |
| DFF | fed_funds | daily market series | daily since 1954 | next business day |
| T10Y2Y | curve_10y2y | daily market series | daily since 1976 | next business day |
| BAA10Y | credit_spread_baa | daily market series | daily since 1986 | next business day |
| T10YIE | breakeven_10y | daily market series | daily since 2003 | next business day |
| VIXCLS | vix | daily market series | daily since 1990 | next business day |

The monthly-average FEDFUNDS series was replaced by daily DFF on 2026-09-07: a monthly average dated the 1st is only knowable after the month ends, and treating it as same-day leaked mid-month rate decisions into the policy signal.

**Exploration files, not consumed by the pipeline:** the flat two-column CSVs (`UNRATE.csv` etc., header `observation_date,<SERIES_ID>`, latest-revision values from `https://fred.stlouisfed.org/graph/fredgraph.csv?id=SERIES`) and `GDP_vintage_*.csv` (real GDP growth, A191RL1Q225SBEA, as published on four dates, from the ALFRED graph endpoint).

Note: the plain FRED graph endpoint ignores `vintage_date`. Use `https://alfred.stlouisfed.org/graph/alfredgraph.csv?id=SERIES&vintage_date=YYYY-MM-DD` (at most 12 vintages per request) or the FRED API with `realtime_start`/`realtime_end`, which the pipeline uses automatically when `FRED_API_KEY` is set.

## gpr/  (Geopolitical Risk index, Caldara and Iacoviello)

Source: https://www.matteoiacoviello.com/gpr.htm and the GitHub folder `iacoviel/iacoviel.github.io/gpr_files`. Index scaled so 1985 to 2019 averages 100 (recent) or 1900 to 2019 averages 100 (historical).

**Core files for the project**

| File | What it is |
|---|---|
| data_gpr_export.xls / .dta | Monthly, 1900-01 to 2026-08. 115 columns in the .xls (113 in the .dta, which lacks the dictionary): headline GPR, threats (GPRT), acts (GPRA), historical versions, article shares, 8 topic-category shares, and country-level GPR for about 45 countries. Data dictionary in the last two columns of the .xls. |
| gpr_core_monthly.csv | Tidy extract made by us: month, GPR, GPRT, GPRA, SHARE_GPR, N10. |
| data_gpr_daily_recent.xls / .dta | Daily, 1985-01-01 to 2026-09-01. GPRD, GPRD_ACT, GPRD_THREAT, plus 7- and 30-day moving averages. This is the series for weekly rebalancing. |
| gpr_daily_latest.xlsx | Alternative daily file with raw counts and shares, 11-newspaper version. |

**Vintages** (`vintages/`): 22 monthly snapshots of the published index from 2019-01 to 2020-10. Useful for checking how much the index itself gets revised when newspaper archives are backfilled (the 2024-02-07 log entry notes one such fix).

**Superseded**: gpr_web_latest.xlsx (2021 layout, has a GPR_WORDS sheet splitting threats into nuclear, war, terrorist), gpr_beta.dta, data_gpr_recent_daily.dta, gpr_recent_daily_data.dta. Older builds kept for reference.

**Documentation** (`docs/`): the AER paper, its appendix, two slide decks, the narrative coding guide and audit guidelines used to validate the index against human readers, methodology page, change log. Not tracked in git: these are the publisher's PDFs and the authors' internal guides (copyrighted), and GPR_SLIDES_2019.pdf turned out to be a mis-saved HTML page. Fetch from https://www.matteoiacoviello.com/gpr_files/<filename> if needed; nothing in the pipeline reads them.

## epu/  (Economic Policy Uncertainty and related indices, policyuncertainty.com)

Source: https://www.policyuncertainty.com, all 50 data files linked from the site, plus 3 replication archives. Baker, Bloom and Davis built the US, global, and several country indices; many country files are contributed by other researchers and carry their own citation in the first row.

**Core files for the project**

| File | What it is |
|---|---|
| USEPUINDXM.csv, USEPUINDXD.csv | US EPU monthly (1985 to 2026-08) and daily (1985 to 2026-09), via FRED. Cleanest format. |
| US_Policy_Uncertainty_Data.xlsx | Same US index from the source. Sheet 1: news-based index back to 1900. Sheet 2: the legacy three-component index (news, tax code expirations, forecaster disagreement). |
| All_Daily_Policy_Data.csv | Daily US EPU from the source, 15,223 rows. |
| Categorical_EPU_Data.xlsx | US EPU split into 12 policy categories: monetary, fiscal, taxes, spending, health care, national security, entitlements, regulation, financial regulation, trade, sovereign debt and currency crises. Monthly since 1985. Directly useful as separate macro signals. |
| All_Daily_TPU_Data.csv | Daily Trade Policy Uncertainty. Spikes on tariff news. |
| EMV_Data.xlsx | Equity Market Volatility trackers, 47 columns. Newspaper-based measures of what is driving stock market volatility: macro news, inflation, interest rates, trade, infectious disease, and so on. Monthly since 1985. |
| All_Infectious_EMV_Data.csv | Daily infectious-disease EMV tracker. |
| All_Country_Data.xlsx | Global EPU (GDP-weighted, current and PPP) plus 20-odd national indices in one sheet. |
| Financial_Stress.xlsx | Monthly and quarterly financial stress indicator, 1889 onward. |

**Country and regional EPU** (mostly contributed): Europe (with Germany, Italy, UK, France, Spain), UK (monthly, daily, historical, interwar), India (plus an India Geopolitical Uncertainty index), Russia, Australia, New Zealand, Singapore, Sweden, Denmark, Netherlands, Belgium, Croatia, Greece, Portugal, Morocco, Pakistan, Brazil (FGV indicator, non-standard CSV layout), US state-level (155 columns).

**Thematic indices** (contributed): climate policy uncertainty (three versions), energy-related uncertainty, oil price uncertainty, energy transportation uncertainty, tourism uncertainty, ESG sustainability uncertainty, migration fear, AI economic uncertainty (daily), debt ceiling and government shutdown frequencies, inter-Korea geopolitical risk (GPRNK).

**Replication** (`replication/`): Replication_Files.zip (144 MB, Stata code and data behind the 2016 QJE paper), AUDIT_ANALYSIS.zip (the human audit of 12,000 articles used to validate the index), BBCDR.zip (a figure and slides from a follow-up). Not tracked in git: the 144 MB archive exceeds GitHub's 100 MB file limit. Nothing in the pipeline reads these; re-download from https://www.policyuncertainty.com/ (US monthly EPU page, replication files) if needed.

## What the pipeline actually consumes

`fred/vintages/*.parquet` (nine series above), `epu/USEPUINDXD.csv` (daily US EPU via FRED), `gpr/data_gpr_daily_recent.xls` (GPRD, GPRD_THREAT, GPRD_ACT), `market/adj_close.csv` (ten ETF adjusted closes from Yahoo), and `fomc/statements/*.txt` (166 dated statements). Everything else in this folder is optional breadth for future signals: Categorical_EPU_Data (monetary, fiscal, trade, national security), All_Daily_TPU_Data, EMV_Data (macro and inflation trackers), the country indices, and the replication archives.

## Caveats

- Text indices are published a few days into the following period. Treat the daily series as available with a lag of about two business days.
- Contributed country files have inconsistent layouts: citation text in row one, blank trailing sheets, dates split across year and month columns. Each needs its own small loader.
- The Brazilian FGV CSV has a malformed line 30 and fails a naive parse.
- The 2020-09 GPR vintage file is named `gpr_web_20200931.xlsx`, a date that does not exist. It is the September 2020 snapshot.
