# Assumptions register

*Revision 2 applied on 2026-09-07 evening: see section 0 for what was removed or replaced by data. The preamble below, sections 1 to 5 and the appendix document version 1 (the census taken before the revision) and are kept as the record; config line numbers in the appendix refer to the version-1 file.*

Written 2026-09-07 at the project lead's request: "I need a basis for all this information that you've chosen
to use." This is every modelling choice in Finorchestra, with where it lives, what its basis is, what it moves,
and how much. It was produced by five sweeps of the code and config (one per area), a completeness check that
diffed the sweeps against every numeric literal in `src/` and every key in `configs/default.yaml`, and a set of
sensitivity runs on the decision of 2026-08-07 that re-run the real functions with each knob moved. Scripts and
outputs are under `outputs/verify_scratch/assumptions/`.

**Counts (version-1 census).** 162 assumptions found. 59 are config values, 94 are constants or rules in code, 9 are choices about
data. For 77 of them no reason was recorded anywhere; for 74 a code comment or doc states one; 11 are standard
choices from the literature. 23 are rated high severity, meaning the headline numbers would move materially if
they were wrong.

**Three kinds of basis are used below.** *Literature*: a published, standard choice, cited. *Data or mandate*:
forced by data availability or copied from a public source. *Judgement*: I chose it. Where it is judgement I say
what I was trying to achieve, and the sensitivity section says how much it matters on a real week.

The honest summary of version 1: the mathematics (Black-Litterman, the optimiser, the bootstrap, the deflated Sharpe)
was standard and cited. The *numbers fed into the mathematics* (the universe, the market weights, the duration and
risk-weight tables, the constraint limits, the theme definitions, the formula agent's loadings, the temperature,
the windows) were mostly my judgement, recorded only as config lines. Section 0 says which of them revision 2
replaced with estimates or public sources.

---

## 0. Revision 2 (2026-09-07, evening): assumptions removed or replaced by data

After this register was written the project lead asked for the number of assumptions to be reduced and the rest
to be based on real data. The sections below this one describe the *first* version and are kept as the record of
what was assumed and why. This section says what changed. Every run made after this revision carries an
`assumptions` block in its certificate listing the remaining choices with their basis.

| Was (version 1, hand-set) | Now (version 2) | Basis of the replacement |
|---|---|---|
| Market weights table, 10 numbers | Neutral portfolio computed each week: inverse-volatility over the risky funds from the date's covariance | data; no parameters. Cash is excluded because it is where the optimiser retreats, not a neutral position |
| Duration table, 10 numbers, stale | Estimated each week per bond fund: minus the slope of weekly fund return on the weekly change in the 10-year Treasury yield over the covariance window; non-bond funds 0 | data (FRED `DGS10`, one-day lag); on 7 Sep 2026: TLT 14.1, IEF 7.2, LQD 7.1, TIP 4.5, HYG 1.9 years |
| Risk-weight table, 10 numbers | Regulatory weights by declared fund kind: US government, inflation-linked, cash and gold 0%; corporate 100%; listed equity 300%; commodity and currency funds 100% | public rule, 12 CFR 217.32 and 217.52 (US standardised approach) |
| Caps 30% / 35% / 40%, volatility cap 10%, duration 4.5 ± 2.5 y, capital budget 0.60: 8 numbers | Limits relative to the neutral portfolio: active-weight band 0.15; volatility at most 1.25× neutral; duration within 2 years of neutral; regulatory risk-weighted exposure at most 1.25× neutral; turnover cap 0.25: 5 numbers, labelled placeholders | these are the client's policy limits; the placeholders are marked as such in the config and the certificate |
| Formula agent: 50 loadings, 16 regime multipliers, confidence floor/ceiling/saturation (69 numbers) | Past-only ridge regression per asset of 4-week forward excess return on the seven signal features, refit weekly, penalty by leave-one-out cross-validation; confidence = 2Φ(\|prediction\|/residual sd) − 1. Procedure parameters: horizon 4 weeks, 156-week minimum history, penalty grid, view ceiling 6 | estimated from data; the procedure choices are stated |
| Fed surprise = stance × (0.5 + novelty), and the 2.0 loading | Removed. Stance, stance change and novelty enter the fitted agent and the model's prompt as separate features; the incremental test reports each | the regression decides the loading |
| Regime temperature 0.75 | Removed. P(theme up) is the empirical percentile of the theme within its own past-only history (normal-CDF fallback with under 52 weeks) | data |
| Covariance shrinkage 0.20 and the 0.5% variance floor | Ledoit-Wolf (2004) constant-correlation shrinkage with the paper's estimated intensity: each fund keeps its own variance, correlations are pulled toward their average | estimated each week |
| Black-Litterman tau 0.05 | Removed from the config: with the view-uncertainty formula used it cancels out of the posterior exactly | mathematics |
| Deflated-Sharpe trials 3 and dispersion prior 0.5 | Trials = number of strategies run; dispersion measured across them | data |
| Baselines "market" and "inverse vol" | One baseline, "benchmark": the same neutral portfolio the prior and mandate use, plus 60/40 as a familiar reference | consistency |

**Count.** In the sections that changed, hand-set modelling numbers went from 114 (universe table 30, constraint
limits 8, formula agent 69, regime 1, Black-Litterman and covariance 3, deflated-Sharpe prior 2, rounds 1) to 17
(mandate placeholders 5, covariance window 1, risk aversion 1, turnover penalty 1, feedback rounds 1, fitted-agent
procedure 8). The remaining choices elsewhere (z-score window and clip, theme membership, retrieval budget,
bootstrap block, cost grid, attribution proxies, availability lags) are unchanged and listed in the certificate.

**What is still judgement, stated plainly.** The ten-year z-score window and the ±3 clip; theme membership and
signs; the two-year covariance window; risk aversion 3 (literature range); the turnover penalty; two feedback
rounds; the fitted agent's horizon, minimum history, penalty grid and view ceiling; the retrieval budget; the
bootstrap block length; the mandate placeholders. Each appears in the certificate's `assumptions` block with a basis
tag of `judgement`, `literature`, `data` or `PLACEHOLDER`.

**Consequences for the numbers.** Every result in the decks produced before this revision describes version 1. Both
reference runs were relaunched under version 2 the same evening. The ten-year mock run is `mock-full-v3-02621a1e`:
the fitted formula agent scores Sharpe 0.09 where the hand-written version-1 rules scored 0.61, which says the old
loadings encoded relationships the data of 2015 to 2026 does not support, and the honest floor is now much lower; the
two AI paths score 0.57 (clipped) and 0.39 (told) against 0.43 for the neutral portfolio, none of the differences
distinguishable from zero. (A first revision-2 run, `mock-full-v2-e375a7e8`, used a scaled-identity shrinkage
target that inflated the variance of low-risk funds, cash included; it was withdrawn in favour of the
constant-correlation target the same evening.) The feedback loop fires on 97% of weeks under the active-band mandate. The real-model run is
`openai-postcutoff-v3-3baad69b` (gpt-4.1-mini, 114 weeks after its cutoff): fitted formula 1.42, clipped 0.34, told
0.62, neutral portfolio 0.76. The version-1 headline, feedback beating clipping by 0.78 Sharpe at p = 0.03, became
+0.27 at p = 0.41 under the benchmark-relative mandate. That is the most important consequence of this revision: the
project's headline depended on how the bank's rules were specified, which is exactly why those rules are now labelled
placeholders for the client to set.

---

## 1. Version 1: the judgement calls that moved results (historical record)

Ordered roughly by how much they matter.

### 1.1 The ten funds and their "market" weights

| | Value | Where |
|---|---|---|
| Universe | SPY, TLT, IEF, TIP, LQD, HYG, GLD, DBC, UUP, BIL | `configs/default.yaml` market.universe |
| Market weights | stocks 25, long Treasuries 8, mid Treasuries 14, inflation-protected 6, IG credit 12, high yield 5, gold 5, commodities 4, dollar 5, cash 16 (percent) | same, `market_weight` |

**Basis: judgement.** One liquid ETF per major asset class with prices back to 2007. The weights sketch a
conservative institutional multi-asset book, about 25% equity, 45% bonds, 16% cash, 14% real assets and
currency. They are not a real mandate and not estimated from any holdings data.

**Why it matters most.** These weights are the Black-Litterman prior every week, the neutral point every view
tilts from, *and* the "hold market weights" yardstick that scored Sharpe 0.93 on the post-cutoff run. Change them
and both the strategies and the bar they are judged against change. The RL and Fed-reuse scope note already
proposes replacing them with a consensus prior built from public fund filings.

### 1.2 Duration and risk-weight tables

| Fund | Duration used (years) | Fact-sheet duration, checked 2026-09-07 | Risk weight used |
|---|---|---|---|
| TLT | 17.0 | 16 to 17 | 0.20 |
| IEF | 7.5 | 7 to 8 | 0.15 |
| TIP | 7.0 | 6.3 | 0.15 |
| LQD | 8.5 | 7.9 | 0.40 |
| HYG | 4.0 | 2.8 | 0.80 |
| BIL | 0.1 | about 0.1 | 0.00 |
| SPY, GLD, DBC, UUP | 0 | not applicable | 1.00, 0.80, 1.00, 0.50 |

**Basis: durations are approximate fund fact-sheet values, frozen in time; risk weights are a stylised
Basel-like ladder** (government 0.15 to 0.20, investment-grade credit 0.40, high yield and gold 0.80, equities and
commodities 1.00, currency 0.50, cash 0). Both are judgement. The durations for TIP, LQD and HYG are higher than
today's fact sheets, so the duration band binds slightly more often than it should. The risk weights are not any
regulator's actual table.

**What they move.** The duration band and capital budget are two of the five rules. On the post-cutoff run the
capital budget bound on 13 of 114 weeks and the duration floor or ceiling on 6.

### 1.3 The bank's rules

| Rule | Value | Where |
|---|---|---|
| Single-fund cap | 30%, stocks 35%, cash 40% | allocation.constraints |
| Portfolio volatility | at most 10% a year | same |
| Duration | 4.5 years, plus or minus 2.5 | same |
| Capital budget | 0.60 | same |
| Weekly one-way turnover | at most 25% | same |
| Long only, fully invested | yes | same |

**Basis: judgement, imitating a typical institutional mandate.** No real investment policy statement was used.
The 30% cap is the rule that binds most (inflation-protected bonds hit it on 82 of 114 post-cutoff weeks), so
it shapes the whole feedback-loop story. The scope note proposes calibrating these to a published pension
mandate. Sensitivity for the cap is in section 4.

### 1.4 Which economic series, and how they become themes

| Theme | Series and sign | Basis |
|---|---|---|
| Growth | industrial production 12-month change (+), payrolls 3-month change (+), unemployment 3-month change (−) | judgement, textbook |
| Inflation | CPI 12-month (+), CPI 3-month annualised (+), 10-year breakeven (+) | judgement, textbook |
| Policy | fed funds rate (+), 10y−2y curve (−) | judgement |
| Financial | Baa credit spread (+), VIX (+) | judgement |

**Basis: judgement guided by convention.** The four themes are the axes of the growth-and-inflation regime
framework popularised by the Merrill Lynch Investment Clock (2004) plus the two conditioning themes most macro
desks track. Equal weights within a theme, no estimation. Only these nine FRED series are used because four of
them have proper publication-vintage histories (needed for point-in-time discipline) and the five daily market
series are never revised. Nothing was tested for predictive value before inclusion.

### 1.5 Z-score window and clip

**10-year window, 5-year minimum, clipped at plus or minus 3.** Basis: judgement. Ten years covers roughly one
business cycle so "normal" includes both expansion and recession; the clip stops a single extreme print from
dominating a theme. Sensitivity for 5, 10 and 15 years is in section 4. This also fixes the backtest start:
weekly ALFRED vintages begin 2005-01-07, so the first decision with full ten-year windows is 2015-01-02.

### 1.6 Regime temperature 0.75

**Basis: judgement.** The four-quadrant regime idea is standard (Investment Clock). The logistic squash and its
temperature are mine. I set 0.75 so that a theme one standard deviation from normal reads as a 79% lean rather
than a near-certainty. Sensitivity for 0.25 to 1.5 is in section 4. It touches the regime odds shown, the
formula agent's multipliers, and the probabilities in the model's prompt. It does not touch the optimiser or
the evaluation.

### 1.7 The formula agent

The formula agent is `expected edge = sum over themes of loading × regime multiplier × theme z`, plus
`2.0 × Fed surprise × text loading`. Loadings (percent per unit z, before multipliers):

| | growth | inflation | policy | financial | text |
|---|---|---|---|---|---|
| SPY | +3.0 | −1.0 | −1.0 | −2.5 | −1.0 |
| TLT | −3.0 | −3.5 | +1.0 | +2.0 | −2.5 |
| IEF | −1.5 | −2.0 | +0.5 | +1.0 | −1.5 |
| TIP | −0.5 | +2.0 | 0 | +0.5 | −1.0 |
| LQD | +0.5 | −1.5 | 0 | −1.0 | −1.0 |
| HYG | +2.0 | −0.5 | −0.5 | −3.0 | −1.0 |
| GLD | −1.0 | +2.0 | −1.0 | +1.5 | −1.5 |
| DBC | +2.0 | +3.0 | 0 | −1.0 | 0 |
| UUP | 0 | +0.5 | +1.5 | +1.5 | +1.5 |

Regime multipliers: goldilocks trusts growth 1.0, inflation 0.6, policy 0.8, financial 1.0; overheating 0.8,
1.3, 1.2, 0.8; stagflation 0.7, 1.4, 0.8, 1.2; recession 1.3, 0.5, 1.0, 1.3. Confidence runs from 0.25 to
0.85, saturating when the edge reaches 5% a year.

**Basis: judgement, encoding textbook relationships.** Strong growth helps stocks and high yield and hurts
Treasuries; hot inflation hurts nominal bonds and helps inflation-protected bonds, gold and commodities; stress
helps Treasuries and hurts credit. None of it is estimated from data. This matters for how the results are
read: the "formula" is a hand-written baseline, not a fitted model. It also sees less than the language model:
only the four themes and the surprise term, not the ten individual z-scores, the news indices or the regime odds. It lost to cash on the post-cutoff period
(Sharpe −0.15) largely because its inflation loadings were wrong for 2024 to 2026. A fitted alternative
(loadings estimated on data before 2015) would be a fairer floor and is a natural addition.

### 1.8 Fed-text numbers

**Stance** comes from the language model reading the masked statement on a −1 to +1 scale (or from a keyword
lexicon in mock runs). **Novelty** is one minus the TF-IDF cosine similarity with the previous statement.
**Surprise = stance × (0.5 + novelty).** The formula agent multiplies surprise by 2.0.

**Basis: judgement throughout.** The 0.5 floor means a hawkish statement counts even when its wording barely
changed; novelty then scales it up when the wording moves. The lexicon's hawkish and dovish word lists are mine.
The stance prompt is not reproduced anywhere outside the code. The surprise term reaches only the formula agent
and the incremental test; the language model sees stance, stance change and novelty directly. The scope note
proposes replacing this surprise with the market-implied one, which has a literature basis (Kuttner 2001).

### 1.9 Black-Litterman constants

**Risk aversion δ = 3, τ = 0.05, view uncertainty Ω = (1/c − 1) τ Σᵢᵢ, confidence clamped to 0.02 to 0.98,
neutral views dropped.**

**Basis: literature for the form and the ranges, judgement for the exact values.** He and Litterman (1999) and
Idzorek (2005) place τ in 0.025 to 0.05 and describe δ as the market's average risk aversion; values from 2.25
to about 3 appear in that literature. The confidence-to-Ω mapping is the common closed form in which a lone view
moves the posterior a fraction c of the way to its target. One consequence worth knowing: with this Ω, τ cancels
out of the posterior for single-asset views, so τ is close to inert here. The clamp exists so a view can never
overwrite the prior completely.

### 1.10 Covariance

**104 weeks of Friday returns, sample covariance shrunk 20% toward its diagonal, 0.5% volatility floor, total
returns rather than excess.** Basis: shrinkage toward a structured target is Ledoit and Wolf (2004); using a
fixed 20% rather than their estimated intensity, and the two-year window, are judgement. Two years makes the
covariance responsive to the recent regime at the cost of noise. Sensitivity for 52, 104 and 156 weeks and 0,
20 and 40% shrinkage is in section 4.

### 1.11 Optimiser details

**Objective: expected return minus (δ/2) × variance minus a turnover penalty of 0.002 per unit traded, solved by
a convex solver; if no solution satisfies the turnover cap the cap is relaxed once and recorded.** The same δ
= 3 is reused from Black-Litterman. **Feedback fires when a rule is "binding"**: a fund within 0.2 points of
its cap, volatility within 1% of its ceiling, duration within 0.05 years of the band edge, or capital within 1%
of budget. **Up to two revision rounds.**

**Basis: judgement.** The turnover penalty and the binding tolerances were tuned once so that the loop fires on
weeks where the views genuinely pressed against a rule, not on numerical noise. The two-round limit is a cost
control. None of these has been varied systematically.

### 1.12 What the model is shown

**Two retrieved statements, each cut to 1,400 characters, chosen by BM25 relevance times a 120-day recency
half-life; all ten z-scores, four themes, regime odds, stance, stance change and novelty; tickers replaced by
letters; dates replaced by relative weeks; percentages rounded to the nearest 0.5.** Sampling temperature 0.

**Basis: mostly practical.** Two documents at 1,400 characters fit a 4k-token local model. The half-life is
judgement. The masking rules are judgement about what a model could use to recognise an episode. All of this is
recorded in the run certificate except the half-life and the query string.

### 1.13 Evaluation choices

| Choice | Value | Basis |
|---|---|---|
| Trade at the same Friday close the decision uses, hold one week | | standard academic simplification; slightly optimistic |
| Sharpe | weekly excess over cash, × √52 | standard |
| Costs | 0 to 30 bp one-way on turnover, first week charged from cash | judgement on the grid |
| Bootstrap | paired circular blocks of 8 weeks, 2,000 draws | method Politis and Romano (1994); block length judgement |
| Deflated Sharpe | 3 declared trials, 0.5 assumed annual dispersion | method Bailey and López de Prado (2014); prior judgement, disclosed |
| 60/40 yardstick | 60% SPY, 40% IEF, ignores the rules | judgement; the usual convention is an aggregate bond index |
| Inverse-volatility yardstick | 104-week volatilities, weekly rebalance | judgement |
| Attribution factors | ETF spreads: SPY−BIL, TLT−BIL, HYG−IEF, DBC−BIL, UUP−BIL; HAC lag 4 | judgement (proxies), HAC standard |
| Incremental test | 4 and 13-week horizons on SPY, TLT, HYG | judgement |
| Model training cutoff | declared in config, never checked | limitation, disclosed in the certificate |

### 1.14 Mock proposer

The deterministic stand-in used in the ten-year run has its own playbook of regime returns scaled by 0.6, a
0.4% emission threshold, and keyword rules for revisions. All judgement. It exists to test the machinery, not to
represent intelligence, and every number from the mock run should be read that way.

---

## 2. Standard choices with citations

- Black-Litterman prior and posterior: Black and Litterman (1992); He and Litterman (1999), "The intuition behind
  Black-Litterman model portfolios"; Idzorek (2005), "A step-by-step guide to the Black-Litterman model".
- Covariance shrinkage: Ledoit and Wolf (2004), "Honey, I shrunk the sample covariance matrix", *J. Portfolio
  Management* 30(4).
- Block bootstrap: Politis and Romano (1994), "The stationary bootstrap", *JASA* 89; we use the circular variant.
- Deflated Sharpe ratio: Bailey and López de Prado (2014), *J. Portfolio Management*.
- HAC standard errors: Newey and West (1987).
- BM25 with k1 = 1.5, b = 0.75: Robertson and Zaragoza (2009) defaults.
- Growth-and-inflation regime quadrants: Merrill Lynch, "The Investment Clock" (Greetham, 2004).
- Sharpe annualisation by √52 and geometric annual return: textbook.

## 3. Proposed corrections and disclosures

Written before revision 2. Items 1, 2 and 3 were applied by revision 2 (durations estimated rather than corrected, the market weights replaced by a data-derived neutral portfolio, an assumptions block in every certificate); items 4 to 7 remain open.

1. **Correct the duration table** to current fact-sheet values (TIP 6.3, LQD 7.9, HYG 2.8) and record the
   source and date in the config comment.
2. **Replace the market weights** with a documented public source (consensus of large balanced funds from
   filings, or a published pension mandate), or at minimum label them "illustrative" everywhere they appear.
3. **Add an assumptions block to every run's certificate and report** listing each config knob with its basis
   tag, so no reader has to find this register.
4. **Show the top judgement calls on the dashboard** in the "For the quants" section.
5. **Add a fitted formula baseline** with loadings estimated before 2015, so the hand-written one is not the only
   floor.
6. **Re-run both reference runs** with the corrected masker and mock (section 5) and refresh every quoted number, dashboard and deck from the new runs.
7. **Run the sensitivity sweep on the full 114-week sample** for the cap, the temperature and the covariance
   window, not just on one decision date, and report the Sharpe range as an uncertainty band.

## 4. Sensitivity on one real week (2026-08-07)

Each knob was moved with everything else held fixed, re-running the project's own functions on the logged first-pass views. Baseline values reproduce the log exactly (max difference 0.0 on themes, regime, posterior and weights). Script: `outputs/verify_scratch/assumptions/sensitivity/sensitivity_2026-08-07.py`.

### 4.1 Regime temperature

| Temperature | goldilocks | overheating | stagflation | recession |
|---|---|---|---|---|
| 0.25 | 20% | 37% | 28% | 15% |
| 0.5 | 23% | 31% | 27% | 20% |
| 0.75 (used) | 24% | 29% | 26% | 21% |
| 1.0 | 24% | 28% | 26% | 22% |
| 1.5 | 24% | 27% | 26% | 23% |

**Reading.** On a week where both themes sit near zero the temperature barely matters: the leading regime stays the same and its odds move between 27% and 37%. It matters more on weeks with a strong theme, where a low temperature turns a lean into near-certainty.

### 4.2 Z-score window

| Window | growth | inflation | policy | financial | Leading regime |
|---|---|---|---|---|---|
| 5 years | -0.18 | -0.57 | -0.33 | -0.78 | recession 38% |
| 10 years (used) | +0.07 | +0.15 | +0.25 | -0.76 | overheating 29% |
| 15 years | +0.02 | +0.37 | +0.75 | -0.85 | overheating 31% |

**Reading.** This is the most consequential judgement at station 1. With a five-year window the 2021 to 2023 inflation surge sits inside "normal", so today's 3.7% CPI reads as *low* inflation, the inflation theme flips sign, and the leading regime flips from overheating to recession. With fifteen years the policy theme triples. The formula agent, the model's prompt and the regime odds all inherit this choice. (A five-year window with the five-year minimum-history rule produces no z-scores at all; the row above relaxes the minimum to four years.)

### 4.3 Black-Litterman constants

| Knob | Value | Prior for TIP | Posterior for TIP | Unconstrained TIP weight | Executed stocks / mid Treasuries / gold |
|---|---|---|---|---|---|
| tau | 0.025 | 0.27% | 2.89% | 949% | 20.8 / 11.6 / 4.7 |
| tau | 0.05 (used) | 0.27% | 2.89% | 949% | 20.8 / 11.6 / 4.7 |
| tau | 0.1 | 0.27% | 2.89% | 949% | 20.8 / 11.6 / 4.7 |
| delta | 2.0 | 0.18% | 2.87% | 1436% | 18.0 / 14.8 / 5.9 |
| delta | 3.0 (used) | 0.27% | 2.89% | 949% | 20.8 / 11.6 / 4.7 |
| delta | 4.0 | 0.35% | 2.90% | 705% | 21.7 / 11.1 / 3.0 |

**Reading.** Tau has no effect at all with our view-uncertainty formula, because it cancels out of the posterior; it could be deleted from the config without changing a number. Delta scales the prior (higher risk aversion means the market mix must be justified by higher returns) and shifts the executed book by a few points; the capped positions do not move.

### 4.4 Confidence clamp

At the logged confidence of 0.8 the clamp is irrelevant. If the model had said confidence 1.0, the posterior for TIP would be 4.0% instead of 2.9% and the unconstrained wish would be 1292% instead of 949%. The clamp at 0.98 caps that at about 3.9%. It is a guard against the model over-ruling the prior entirely, and it rarely engages.

### 4.5 Covariance window and shrinkage

| Window | Shrinkage | TIP vol | Gold vol | Executed: stocks / mid Tsy / IG credit / gold / commodities | Binding |
|---|---|---|---|---|---|
| 52 wk | 0% | 2.9% | 23.6% | 32 / 14 / 9 / 2 / 11 | cap:TIP |
| 52 wk | 20% | 2.9% | 23.6% | 23 / 20 / 20 / 5 / 1 | cap:TIP |
| 52 wk | 40% | 2.9% | 23.6% | 22 / 11 / 30 / 7 / 0 | cap:TIP, cap:LQD |
| 104 wk | 0% | 4.0% | 20.2% | 22 / 0 / 30 / 0 / 12 | cap:TIP, cap:LQD |
| 104 wk | 20% (used) | 4.0% | 20.2% | 21 / 12 / 30 / 5 / 3 | cap:TIP, cap:LQD |
| 104 wk | 40% | 4.0% | 20.2% | 19 / 12 / 30 / 7 / 0 | cap:TIP, cap:LQD |
| 156 wk | 0% | 4.4% | 18.5% | 15 / 0 / 28 / 0 / 16 | cap:TIP |
| 156 wk | 20% | 4.4% | 18.5% | 17 / 11 / 30 / 6 / 6 | cap:TIP, cap:LQD |
| 156 wk | 40% | 4.4% | 18.5% | 17 / 11 / 30 / 8 / 1 | cap:TIP, cap:LQD |

**Reading.** The covariance choices move the executed book by ten points or more in single funds. A one-year window with no shrinkage would have held 31% stocks, 9% credit and 11% commodities; the two-year window with 20% shrinkage held 21%, 30% and 3%. The volatility of the book itself stays near 5% in every case, so the risk rule is not what changes; the shape of the book is. The 30% caps on inflation-protected bonds and credit bind in most variants.

### 4.6 Single-fund cap

| Cap | Executed: stocks / mid Tsy / inflation-protected / IG credit / gold | Book volatility | Binding |
|---|---|---|---|
| 25% | 22 / 20 / 25 / 25 / 5 | 5.2% | cap:TIP, cap:LQD |
| 30% (used) | 21 / 12 / 30 / 30 / 5 | 5.2% | cap:TIP, cap:LQD |
| 40% | 18 / 7 / 40 / 30 / 4 | 4.9% | cap:TIP |

**Reading.** The cap decides how much of the inflation view survives. At 40% the book holds 40% inflation-protected bonds and the credit cap stops binding; at 25% the excess spills into mid Treasuries. Because the feedback loop fires on binding caps, the cap level also decides how often the new idea is even exercised.

### 4.7 Feedback rounds

Not testable offline: the loop only runs through a model call, so a different round count needs a re-run with the model.


## 5. What the completeness check added

An independent agent diffed the five sweeps against every numeric literal in `src/` (2,137 matches inspected)
and every key in the config. It found nine items the sweeps missed and eighteen duplicates or conflicts between
sweeps. Two of the nine were defects rather than assumptions, and both are now fixed with regression tests.

**Defect 1, fixed: the mock proposer halved the wrong asset.** The mock's revision handler looked for an asset
code as a plain substring of the checker's sentence. The phrase "single-asset cap" contains "asset c", so on
every cap message the mock also halved its view on mid Treasuries (Asset C), whichever asset was actually named.
Whole-word matching now. This affects only mock runs, but it means the ten-year mock reference run
(`mock-full-b811156c`) was produced with a distorted revision rule and should be re-run before its numbers are
quoted again.

**Defect 2, fixed: the percentage masker rounded move sizes and collapsed ranges.** "1/4 percentage point" was
rewritten as "about 0.5 percentage point", and "5-1/4 to 5-1/2 percent" as "about 5.5 to 5.5 percent". Move sizes
are now left alone and ranges are widened outward ("about 5 to 5.5 percent"). This affects the text the language
model read in every run, including the post-cutoff reference run (`openai-postcutoff-aefba080`), whose prompts
described quarter-point moves as half-point moves. The logged results stand as a record of what was run; a re-run
with the corrected masker is the right basis for any number the team quotes going forward.

**Smaller items, now recorded:**

| Item | What it is | Status |
|---|---|---|
| Rule agent sees less than the model | The formula agent uses only the four themes and the surprise term; the model also sees all ten z-scores, the news indices, and regime odds. Docs said "same signals". | Wording corrected here; docs to follow |
| Daily market series are unsmoothed | Fed funds, curve, spreads, breakevens and VIX enter as the single latest daily print; the news indices get a 21-day mean. | Assumption, now listed |
| The 21-day mean is calendar days | The index files include weekends, so 21 rows is three weeks, not a trading month. The code comment said business days. | Comment fixed |
| Relaxed turnover was reported as a violation | When the optimiser had to relax the turnover cap, the final critic check still counted it as a breach. Never triggered in any reference run. | Fixed |
| One model call feeds both AI paths | Clipped and feedback share the same first proposal by construction. | Design choice, stated |
| Non-Friday `decide --date` is not snapped | The help text says a rebalance Friday; a mid-week date is used as given. | Minor, to fix |
| Dashboard truncates explanations | Evidence to two items of 140 characters, rationale to 400. | Display choice, now listed |
| Report hardcodes cost and factor columns | Independent of the config grid. | Minor |
| Retrieval half-life is on config line 161, not 160 | Pointer error in one sweep. | Corrected |

Several helpers were also confirmed unused by the pipeline (an annualisation helper, a view-implied-portfolio
routine kept for tests, a market-prior helper); none affects any number.

## Appendix: every assumption found (162), by area and severity

*Version-1 census. Config line numbers refer to the version-1 `configs/default.yaml`; many of these entries no longer exist (see section 0).*

Severity = how much the headline numbers would move if the choice were wrong. Basis: *stated* = a comment or doc explains it; *literature* = a standard choice; *unstated* = chosen without a recorded reason. Disclosed = where a reader could have learned it before this register.


### Allocation

| Assumption | Value | Kind | Where | Basis | Disclosed today | Severity |
|---|---|---|---|---|---|---|
| Binding-constraint tolerances (feedback trigger) | caps: w_i >= cap_i - 0.002 (and cap_i < 1.0); volatility: vol >= 0.99*max_vol; capital: rwa >= 0.99*budget; duration: wi | hardcoded | src/finorchestra/allocation/constraints.py:142 (`def binding(self, w, sigma, tol_w: float  | unstated | Nowhere (README/docs describe 'binding' qualitatively; dashboard glossary 'bindi | high |
| Black-Litterman risk aversion delta | 3.0 | config | configs/default.yaml:208 (`risk_aversion: 3.0 # delta in Black-Litterman`); used src/finor | literature | docs/pages/one-week-2026-08-07.html:380 ('risk aversion 3') and :486 tooltip ('r | high |
| Duration liability band | target 4.5y, band +/-2.5y -> [2.0, 7.0] years; critic violation beyond +/-1e-4y; 'binding' within 0.05y of either edge | config | configs/default.yaml:218-219 (`duration_target: 4.5`, `duration_band: 2.5`); constraints.p | unstated | docs/what-the-system-does.md:61 ('2.0 to 7.0 years (liability band around 4.5)') | high |
| Market (prior/anchor) weights table | SPY 0.25, TLT 0.08, IEF 0.14, TIP 0.06, LQD 0.12, HYG 0.05, GLD 0.05, DBC 0.04, UUP 0.05, BIL 0.16 (hand-set, static, su | config | configs/default.yaml:68,73,78,83,88,93,98,103,108,113 (`market_weight:` per asset); consum | unstated | README:238 ('the ETF universe with durations, risk weights and market weights' l | high |
| Per-asset duration table (static) | SPY 0.0, TLT 17.0, IEF 7.5, TIP 7.0, LQD 8.5, HYG 4.0, GLD 0.0, DBC 0.0, UUP 0.0, BIL 0.1 years | config | configs/default.yaml:66,71,76,81,86,91,96,101,106,111 (`duration:` per asset); config.py:4 | unstated | README:238 says durations live in config; dashboard bundle meta.asset_meta.durat | high |
| Per-asset risk-weight table (static) | SPY 1.00, TLT 0.20, IEF 0.15, TIP 0.15, LQD 0.40, HYG 0.80, GLD 0.80, DBC 1.00, UUP 0.50, BIL 0.00 | config | configs/default.yaml:67,72,77,82,87,92,97,102,107,112 (`risk_weight:` per asset); config.p | unstated | README:238 ('risk weights' in config); dashboard glossary 'capital: A regulatory | high |
| Single-asset cap (default) | 0.30 for TLT, IEF, TIP, LQD, HYG, GLD, DBC, UUP (pydantic default would be 0.25; YAML wins) | config | configs/default.yaml:215 (`max_weight: 0.30 # every cap sits above the asset's market weig | stated | docs/what-the-system-does.md:59 ('30% (SPY 35%, cash 40%)'); README:144 example  | high |
| Binding-triggers-feedback loop rule, with no acceptance test on revisions | while binding and used_rounds < rounds: revise; the last revised view set is executed even if its binding set is larger  | hardcoded | src/finorchestra/allocation/engine.py:87-102 (`while binding and used_rounds < rounds: ... | stated | README:141-146 and docs/what-the-system-does.md:69-73 describe the loop; the abs | medium |
| Cap overrides | SPY 0.35, BIL 0.40 | config | configs/default.yaml:216 (`max_weight_overrides: { SPY: 0.35, BIL: 0.40 }`); constraints.p | unstated | docs/what-the-system-does.md:59; docs/pages one-week :401 ('stocks 35%, cash 40% | medium |
| Covariance estimation window | 104 weeks (rolling, weekly returns resampled W-FRI last close as of the decision date, pct_change, missing weeks filled  | config | configs/default.yaml:206 (`cov_window_weeks: 104`, no comment); consumed in src/finorchest | unstated | docs/pages/one-week-2026-08-07.html:380 ('Inputs: 104 weeks of returns, market w | medium |
| Covariance shrinkage toward diagonal | 0.20 (Sigma = 0.8*sample + 0.2*diag(sample); off-diagonals scaled by 0.8, variances unchanged) | config | configs/default.yaml:207 (`cov_shrinkage: 0.20 # shrink sample covariance toward its diago | stated | Nowhere outside configs/default.yaml and the market.py docstring: README:238-240 | medium |
| Feedback rounds | 2 (rule agent and llm_clip: 0) | config | configs/default.yaml:211 (`feedback_rounds: 2 # LLM agent revision rounds when the view-im | stated | README:145 ('the loop repeats up to two rounds'); dashboard lead text (dashboard | medium |
| Feedback trigger is the binding set of the constrained optimum, not the view-implied portfolio | binding = cs.binding(optimizer weights); view_implied_portfolio(), relaxed_cvx_constraints() and market_prior() are neve | hardcoded | src/finorchestra/allocation/engine.py:79 (`return bl_res, opt_res, cs.binding(opt_res.weig | stated | README:141-145 and docs/what-the-system-does.md:69 describe the binding-based me | medium |
| Neutral views (and views on unknown assets) are dropped before BL | direction == 'neutral' -> no P row (not a Q=0 view); asset not in universe -> dropped | hardcoded | src/finorchestra/allocation/black_litterman.py:74-76 (`if v.asset not in assets or v.direc | unstated | docs/rl-and-fed-reuse-scope.md:31 ('Neutral views pull the book toward market we | medium |
| One-way turnover cap and its definition | 0.25 per week, one-way turnover = 0.5*\|\|w - w_prev\|\|_1; w_prev = the same strategy's previous executed weights; cons | config | configs/default.yaml:221 (`max_one_way_turnover: 0.25`); constraints.py:79-80, :134-137; p | unstated | docs/what-the-system-does.md:63 ('at most 25%'); docs/pages one-week :459 ('Trad | medium |
| Optimizer objective | maximize mu'w - (delta/2) w'Sigma w - lambda * 0.5*\|\|w - w_prev\|\|_1 (delta = 3.0, lambda = turnover_penalty = 0.002; | hardcoded | src/finorchestra/allocation/optimizer.py:71-75 (`o = m @ w - (delta / 2) * cp.quad_form(w, | stated | docs/what-the-system-does.md:54 ('A quadratic program then maximizes expected re | medium |
| Portfolio volatility cap | 0.10 annual (SOC constraint w'Sigma w <= 0.01 on the 104w shrunk Sigma; critic violation if vol > 0.10 + 1e-4; 'binding' | config | configs/default.yaml:217 (`max_annual_volatility: 0.10`); constraints.py:75, :123-125, :15 | unstated | docs/what-the-system-does.md:60; dashboard 'Risk (volatility) against the ceilin | medium |
| Risk-weight (capital) budget | 0.60 (sum_i rw_i * w_i <= 0.60; 'binding' if >= 0.594) | config | configs/default.yaml:220 (`risk_weight_budget: 0.60`); constraints.py:78, :131-133, :162-1 | unstated | docs/what-the-system-does.md:62; dashboard 'Capital used against the budget' (da | medium |
| Same delta reused as the optimizer's mean-variance risk aversion | 3.0 (the BL delta is passed unchanged as the optimizer's `delta`, objective term (delta/2) w'Sigma w) | hardcoded | src/finorchestra/allocation/engine.py:78 (`optimize(bl_res.posterior, sigma, cs, a.risk_av | unstated | Nowhere explicitly (README/docs describe 'expected return minus risk' without sa | medium |
| Turnover penalty coefficient | 0.002 per unit of one-way turnover (i.e. 20 bp of annual expected return per 100% one-way turnover) | config | configs/default.yaml:210 (`turnover_penalty: 0.002 # per unit of one-way turnover in the o | unstated | docs/what-the-system-does.md:54 mentions 'a turnover penalty' without the value. | medium |
| Turnover-relaxation rule and market fallback | Pass 1: all constraints incl. turnover cap. Pass 2 (if pass 1 fails): drop only the turnover constraint (penalty kept),  | hardcoded | src/finorchestra/allocation/optimizer.py:77-85 | stated | README:113 ('graceful relaxation'); decision JSON optimizer.relaxed_turnover / f | medium |
| View-uncertainty (Omega) formula | Omega = diag((1/c_i - 1) * tau * (P Sigma P')_ii); for a single one-hot view the posterior moves exactly fraction c from | hardcoded | src/finorchestra/allocation/black_litterman.py:91-93 (`pSp = np.einsum("ij,jk,ik->i", P, t | stated | docs/what-the-system-does.md:54 loosely ('a 0.9-confidence view nearly pins its  | medium |
| Annualisation factor for weekly covariance | x52 (returns.cov() * 52.0) | hardcoded | src/finorchestra/data/market.py:82 (`s = returns.cov() * 52.0`) | literature | Implicit in 'per year' language everywhere; the number 52 appears in no README/d | low |
| Black-Litterman tau | 0.05 (numerically inert under the Omega formula used: posterior identical to ~1e-17 for tau in {0.001, 0.05, 0.5}) | config | configs/default.yaml:209 (`tau: 0.05`, no comment); used black_litterman.py:91-98 (`pSp =  | literature | docs/pages/one-week-2026-08-07.html:380 ('tau 0.05'); README:240 names the key.  | low |
| Cash-as-numeraire implied (unconstrained) weights | w* = w_mkt + Sigma_risky^-1 (mu - pi)_risky / delta on risky assets; cash = 1 - sum(risky); numeraire = cfg.market.risk_ | hardcoded | src/finorchestra/allocation/black_litterman.py:44-60 and :102-105; numeraire passed from e | stated | Decision JSON field name only; docstring is misleading about its role. Not in RE | low |
| Confidence clamp | [0.02, 0.98] | hardcoded | src/finorchestra/allocation/black_litterman.py:81 (`conf.append(min(max(v.confidence, 0.02 | stated | Code docstring only. | low |
| Covariance measured on total returns, not excess-over-cash | total-return weekly pct_change of adjusted closes (cash/BIL kept as an asset row) | data | src/finorchestra/pipeline.py:116-120; excess_returns() in data/market.py:75-77 exists but  | stated | Code comment only; README:133 says 'Prices are total-return adjusted closes, and | low |
| Critic budget tolerance (fully invested) | BUDGET_TOL = 1e-3 on \|sum(w) - 1\| | hardcoded | src/finorchestra/allocation/constraints.py:96 (`BUDGET_TOL = 1e-3`), :115 | stated | Code docstring only; the 'zero critic violations' claims (README:194, docs/what- | low |
| Critic violation tolerance (all other rules) | tol = 1e-4 (absolute: weight, vol, duration in years, risk-weighted exposure, turnover) | hardcoded | src/finorchestra/allocation/constraints.py:103 (`tol: float = 1e-4`), applied :117-137; ca | unstated | Nowhere. | low |
| Eigenvalue guard on Sigma in BL | if min eigenvalue < 1e-8, add (1e-8 - min(eig,0)) * I | hardcoded | src/finorchestra/allocation/black_litterman.py:67-70 | stated | Code comment only. | low |
| Fully invested (cash counts as an asset) | true (sum(w) == 1, BIL is one of the ten weights) | config | configs/default.yaml:214; constraints.py:70-71, :115 | unstated | docs/what-the-system-does.md:58. | low |
| Long-only | true (w >= 0; critic flags weight < -1e-4) | config | configs/default.yaml:213; constraints.py:72-73, :117-119 | unstated | docs/what-the-system-does.md:58 table row 'Long only, fully invested \| yes'. | low |
| Numeraire / cash asset identity | BIL (risk_free_ticker), also used as the excess-return benchmark in evaluation | config | configs/default.yaml:114 (`risk_free_ticker: BIL`); config.py:57; engine.py:74; pipeline.p | unstated | dashboard meta.cash; docs describe 'cash'. Not in the certificate. | low |
| Numerical ridges and floors | 1e-10*I added to Sigma in optimizer (twice) and in implied-weights solve; Omega floored at 1e-10 | hardcoded | src/finorchestra/allocation/optimizer.py:67 and :95 (`S = 0.5*(S+S.T) + 1e-10*np.eye(...)` | unstated | Nowhere. | low |
| Per-asset variance floor | 0.5% annual vol (variance floor 0.005**2 = 2.5e-5, applied by bumping the diagonal after shrinkage) | hardcoded | src/finorchestra/pipeline.py:121-124 (`floor = 0.005**2; d = np.diag(sigma.values).copy(); | stated | Nowhere (code comment only). | low |
| Post-solve clipping of negative weights without renormalisation | np.clip(x, 0, None); sum not re-normalised | hardcoded | src/finorchestra/allocation/optimizer.py:79 and :83 (`pd.Series(np.clip(x, 0, None), index | unstated | Nowhere. | low |
| Solver choice, accepted statuses and tolerances | cvxpy: try CLARABEL then SCS, default solver tolerances (none set), accept status 'optimal' or 'optimal_inaccurate', swa | hardcoded | src/finorchestra/allocation/optimizer.py:43-50 (`for solver in ("CLARABEL", "SCS"): try: p | stated | README:113 ('allocation/optimizer.py cvxpy (CLARABEL/SCS) with graceful relaxati | low |

### Data and point-in-time

| Assumption | Value | Kind | Where | Basis | Disclosed today | Severity |
|---|---|---|---|---|---|---|
| Backtest start 2015-01-02 (and end = last price date) | run.start: "2015-01-02"; run.end: null -> min(end, last ETF price date); 610 Friday decisions to 2026-09-04. Not forced  | config | configs/default.yaml lines 7-8; defaults src/finorchestra/config.py:21-22; src/finorchestr | unstated | README results header ('2015-01-02 to 2026-09-04, 610 weekly rebalances'); certi | high |
| Declared LLM training cutoff (and the absence of any check) | llm.knowledge_cutoff: "2024-10-01" paired with model qwen2.5:3b (released Sept 2024; vendor publishes no cutoff). Used o | config | configs/default.yaml line 178; src/finorchestra/config.py:136; src/finorchestra/evaluation | stated | certificate.json (declared date, count and share after it), README, docs/what-th | high |
| ETF price source and adjustment: Yahoo Finance via yfinance, auto_adjust=True, Close column only | yf.download(tickers, start='2007-01-01', auto_adjust=True); adjusted close (splits and dividends folded into price) trea | data | src/finorchestra/data/market.py:1-4 (docstring), 32-43; consumers pipeline.py:114-116, 183 | literature | README 'Data sources' (Yahoo Finance via yfinance) and 'Design commitments'; cer | high |
| Market (neutral) weights | SPY 0.25, BIL 0.16, IEF 0.14, LQD 0.12, TLT 0.08, TIP 0.06, HYG 0.05, GLD 0.05, UUP 0.05, DBC 0.04 (sum validated to 1.0 | config | configs/default.yaml lines 68,73,78,83,88,93,98,103,108,113; validator src/finorchestra/co | unstated | README 'Configuration' and docs ('A neutral, market-like mix that never changes' | high |
| Ten-ETF universe and the label strings the models see | SPY, TLT, IEF, TIP, LQD, HYG, GLD, DBC, UUP, BIL with labels e.g. 'broad domestic equities', 'long-term government bonds | config | configs/default.yaml lines 63-113; src/finorchestra/views/masking.py:58-68, 91; src/finorc | unstated | README 'Configuration' and docs table list the tickers; dashboard embeds label/d | high |
| Which macro series: the nine FRED series | UNRATE, PAYEMS, CPIAUCSL, INDPRO (revised) + DFF, T10Y2Y, BAA10Y, T10YIE, VIXCLS (unrevised daily). Mapped to four theme | config | configs/default.yaml lines 23-59 (fred.series); consumed via signals.derived lines 134-149 | unstated | Listed (not justified) in README 'Design commitments' and 'What is where', data/ | high |
| ALFRED vintage calendar: weekly Friday snapshots from 2005-01-07, weekday hardcoded to 4 | vintage_start: "2005-01-07"; vintages requested for every Friday to today via fridays_between(vintage_start, end, 4) — t | config | configs/default.yaml line 21; src/finorchestra/data/fred.py:254 (weekday literal 4), 319-3 | stated | data/raw/README.md ('every Friday since 2005-01-07, 12 vintages per call'); cert | medium |
| Availability lag per series (lag_days) and the business-day shift | lag_days: 1 for DFF, T10Y2Y, BAA10Y, T10YIE, VIXCLS; default 0 for the four revised series. Applied as available_from =  | config | configs/default.yaml lines 43,47,51,55,59; default in src/finorchestra/config.py:36; appli | stated | certificate.json inputs[].lag_business_days and point_in_time text; README 'Desi | medium |
| EPU: daily USEPUINDXD via FRED (not the monthly index), latest vintage, 2-business-day lag, refreshed when >7  | text_indices.epu_daily_series: USEPUINDXD; epu_lag_days: 2; 15,221 calendar-daily rows 1985-01-01..2026-09-03 (weekends  | config | configs/default.yaml lines 117-118; src/finorchestra/data/text_indices.py:1-11, 33-37, 58- | stated | certificate.json 'USEPUINDXD ... partial: latest vintage, availability lag 2 bus | medium |
| FOMC boilerplate stripping and content truncation rules | Container div#article else body; drop <p> shorter than 40 chars or starting with any of ('For release at','Share','Feder | hardcoded | src/finorchestra/data/fomc.py:26-33 (_BOILERPLATE), 81-96 (parse_statement), 119-120 | stated | Nowhere (code comment only). | medium |
| FRED cache refresh rule: unrevised series are never re-pulled without --force | if cached and (end - last realtime_start).days < 7 or not s.revised: reuse cache. So DFF/T10Y2Y/BAA10Y/T10YIE/VIXCLS sta | hardcoded | src/finorchestra/data/fred.py:237-244 (_pull_one) | unstated | Nowhere. | medium |
| GPR: author's daily .xls (GPRD, GPRD_THREAT, GPRD_ACT), 2-business-day lag, downloaded once and never refreshe | gpr_daily_file: data/raw/gpr/data_gpr_daily_recent.xls (ends 2026-09-01, fetched 2026-09-06 from matteoiacoviello.com);  | config | configs/default.yaml lines 119-120; src/finorchestra/data/text_indices.py:38-47, 65-76 | stated | certificate.json 'GPR daily ... partial: latest vintage, availability lag 2 busi | medium |
| Information-at-close is traded at the same close (zero execution lag), and as-of is inclusive of date d | Decision at d uses available_from <= d (fred.py:284, fomc.py:147, text_indices.py:83) and prices .loc[:d] (market.py:66) | hardcoded | src/finorchestra/data/pit.py:1-7, 50-57; src/finorchestra/data/market.py:64-66, 87-93; src | literature | Nowhere as an assumption; docs describe 'what those weights would have earned ov | medium |
| Per-ETF risk weights (capital budget) | SPY 1.00, DBC 1.00, HYG 0.80, GLD 0.80, UUP 0.50, LQD 0.40, TLT 0.20, IEF 0.15, TIP 0.15, BIL 0.00; portfolio sum must b | config | configs/default.yaml lines 67,72,77,82,87,92,97,102,107,112; src/finorchestra/allocation/c | unstated | README 'Configuration' phrase; dashboard asset_meta and glossary; nowhere justif | medium |
| Rebalance weekday = Friday, W-FRI resampling with forward fill | run.rebalance_weekday: 4; weekly_prices = prices.ffill().resample('W-FRI').last(); 36 of 1027 weekly bars are holiday Fr | config | configs/default.yaml line 9; src/finorchestra/data/market.py:53-58; src/finorchestra/pipel | unstated | docs/what-the-system-does.md ('Every Friday'), README ('weekly backtest'). Holid | medium |
| Static per-ETF durations | TLT 17.0, LQD 8.5, IEF 7.5, TIP 7.0, HYG 4.0, BIL 0.1, SPY/GLD/DBC/UUP 0.0 — constant over 2007-2026 | config | configs/default.yaml lines 66,71,76,81,86,91,96,101,106,111; consumed in src/finorchestra/ | unstated | README 'Configuration' (mentions durations exist); dashboard asset_meta and dura | medium |
| ALFRED chunk size 12 and missing-vintage guard | vintage_chunk: 12; ALFRED_MAX_PER_CALL = 12 caps any larger config value; RuntimeError if any requested vintage is absen | config | configs/default.yaml line 22; src/finorchestra/data/fred.py:70, 79, 87-90 | stated | data/raw/README.md fred section and note at line 25; README Quickstart call coun | low |
| Business-day shift ignores exchange/federal holidays | add_business_days() and pd.offsets.BusinessDay count Mon-Fri only; a Thursday observation before a Friday holiday is dee | hardcoded | src/finorchestra/utils.py:48-56 (add_business_days); src/finorchestra/data/fred.py:232 (Bu | stated | Nowhere outside the two docstrings; certificate says 'usable 1 business day(s) a | low |
| Cash / risk-free proxy = BIL ETF | risk_free_ticker: BIL; BIL's weekly total return is subtracted for excess returns, Sharpe, attribution short legs, and u | config | configs/default.yaml line 114; src/finorchestra/pipeline.py:245, 258, 277; evaluation attr | literature | docs/what-the-system-does.md ('Sharpe ratio on returns in excess of the cash ETF | low |
| Daily text indices turned into a 'current reading' by a 21-row rolling mean (comment says business days; data  | smooth = s.rolling(21, min_periods=10).mean(); series with < 300 observations skipped; the EPU/GPR files are 7-day calen | hardcoded | src/finorchestra/signals/zscores.py:103-108 (consumer of Snapshot.text_indices) | stated | docs/what-the-system-does.md §3.2 ('smoothed over 21 days'); the business-day/ca | low |
| FOMC corpus scope: years [2007, 2026], only 'a' statement URLs | fomc.years: [2007, 2026]; pages = fomccalendars.htm + fomchistorical{year}.htm; STATEMENT_RE matches /newsevents/(pressr | config | configs/default.yaml line 123; src/finorchestra/data/fomc.py:20-23, 67-78, 105-124 | unstated | README 'What is where' ('one dated file per statement (2007 ->)'); data/raw/READ | low |
| FOMC encoding repair | _fetch forces r.encoding='utf-8'; repair_mojibake applied at load only when 'â' or 'Ã' present, trying cp1252 then latin | hardcoded | src/finorchestra/data/fomc.py:36-48, 56-58, 131 | stated | README re-verification paragraph; tests/test_verification_fixes.py::test_fomc_mo | low |
| FOMC statement availability lag = 0 (same-day) | fomc.lag_days: 0; available_from = add_business_days(release_date, 0) = release date; a Wednesday 14:00 ET statement is  | config | configs/default.yaml line 124; src/finorchestra/data/fomc.py:1-5, 136, 145-147 | stated | certificate.json 'FOMC statements ... yes: dated by release; usable from release | low |
| FRED API path (when FRED_API_KEY is set) substitutes exact real-time periods | fetch_api_intervals with realtime_start='1776-07-04', realtime_end='9999-12-31'; mode 'api_realtime'. Docstring claims b | hardcoded | src/finorchestra/data/fred.py:127-159, 249-252; docstring fred.py:9-10 | stated | certificate.json mode field; data/raw/README.md line 25 ('which the pipeline use | low |
| Market cache staleness threshold | Cached adj_close.csv reused if its last date is <= 4 calendar days old and covers all tickers; otherwise full re-downloa | hardcoded | src/finorchestra/data/market.py:26-31 | unstated | Nowhere. | low |
| Market download start 2007-01-01 and pre-inception handling | market.start: "2007-01-01"; HYG first price 2007-04-11, UUP 2007-03-01, BIL 2007-05-30 (67/39/101 NaNs); weekly_prices f | config | configs/default.yaml line 62; src/finorchestra/data/market.py:36, 56-58; src/finorchestra/ | unstated | Nowhere (README mentions 2007 only for the FOMC corpus). | low |
| Revised vs unrevised handling (vintage reconstruction only for four series) | revised: true -> weekly ALFRED vintages (or FRED API real-time periods) collapsed to intervals; revised: false -> single | data | configs/default.yaml lines 27,30,33,36 (revised: true) and 42,46,50,54,58 (revised: false) | stated | certificate.json inputs[].point_in_time ('n/a: series is never revised; usable 1 | low |
| Vintage-interval collapsing rule | For each observation, consecutive Friday vintages with an unchanged value form one interval; a changed value opens a new | hardcoded | src/finorchestra/data/fred.py:38-39, 98-121 (wide_vintages_to_intervals); as_of at 280-286 | stated | certificate.json vintage_intervals_per_observation; data/raw/README.md fred para | low |

### Evaluation and reporting

| Assumption | Value | Kind | Where | Basis | Disclosed today | Severity |
|---|---|---|---|---|---|---|
| Baseline 'market': static config weights, re-set every week | SPY .25, TLT .08, IEF .14, TIP .06, LQD .12, HYG .05, GLD .05, DBC .04, UUP .05, BIL .16 (sum 1, validated). Returned un | config | configs/default.yaml:64-113 (market_weight per asset), :215 comment 'every cap sits above  | unstated | dashboard glossary 'A neutral, market-like mix that never changes'; README/docs  | high |
| Deflated Sharpe: declared trial count | trials_declared = 3 for the three strategies; baselines are passed n_trials = 1 (so SR0 = 0 and their 'deflated' figure  | config | configs/default.yaml:232 (comment: 'strategy variants evaluated; deflated Sharpe uses this | stated | README:151; docs/what-the-system-does.md:91; report.md footnote; summary.json de | high |
| Attribution factor definitions (long-short ETF spreads from the same universe) | MKT = SPY-BIL, DUR = TLT-BIL, CRD = HYG-IEF, CMD = DBC-BIL, USD = UUP-BIL, built as differences of weekly simple returns | config | configs/default.yaml:234-239; src/finorchestra/pipeline.py:274-275; src/finorchestra/evalu | unstated | README:153-155 and docs/what-the-system-does.md:93 list the five names; exact le | medium |
| Baseline 'inverse_vol': trailing 104-week window, weekly rebalance, unconstrained | w_i = (1/vol_i)/sum(1/vol), vol = std(ddof=1)*sqrt(52) over weekly_ret.loc[:d].tail(allocation.cov_window_weeks=104) (bo | hardcoded | src/finorchestra/evaluation/baselines.py:15-20; window built in src/finorchestra/pipeline. | unstated | docs/finorchestra-first-principles.md:420 ('holds each asset in proportion to on | medium |
| Contamination certificate contents and what it does not check | Records: run_id; first/last/count of decision dates; per-FRED-series PIT mode text + lag + vintage stats; fixed prose fo | hardcoded | src/finorchestra/evaluation/leakage.py:20-75 (cutoff :21-22, inputs :28-52, knowledge_cuto | stated | README:155-157 lists what it contains; docs/what-the-system-does.md:95; dashboar | medium |
| Cost grid and charging rule | cost_bps_grid [0, 5, 10, 20, 30] one-way bp; net_excess = excess - turnover*bps/1e4, a flat linear charge identical for  | config | configs/default.yaml:227; src/finorchestra/evaluation/metrics.py:64-66, :215-216; src/fino | stated | README:152-153; docs/what-the-system-does.md:90; docs/first-principles 8.4; repo | medium |
| Dashboard caps/limits taken from whichever config is passed, not the run's own | bundle() uses cfg if given, else loads <root>/configs/default.yaml; the CLI 'dashboard --run-dir' passes load_config('co | hardcoded | src/finorchestra/explain/dashboard.py:70-82; src/finorchestra/cli.py:141-153; run dir list | unstated | nowhere (README:58-59 says only 'Rebuild it for any finished run') | medium |
| Declared LLM knowledge cutoff (default) | llm.knowledge_cutoff = '2024-10-01' for the default model qwen2.5:3b; overridable via --knowledge-cutoff; copied verbati | config | configs/default.yaml:178 (comment: 'declared training cutoff of the configured model; used | stated | README:83-85 and 202-203 (gpt-4.1-mini 'declared June 2024 cutoff'); report.md ' | medium |
| Deflated Sharpe: assumed Sharpe dispersion across trials | trial_sharpe_dispersion_annual = 0.5 (annual), converted to per-period variance v = (0.5/sqrt(52))^2 = 0.0048; used inst | config | configs/default.yaml:233 (comment: 'assumed spread of Sharpe across trials for SR0 (a prio | stated | README:151-152, docs/what-the-system-does.md:91, report.md footnote, summary.jso | medium |
| Execution timing: decide and trade at the same Friday close, hold one week | weights decided on Friday d (using prices through d) earn weekly_ret.iloc[pos+1] = px[next Friday]/px[d] - 1; zero imple | data | src/finorchestra/pipeline.py:206-209 (comment 'next-week realised returns (None on the fin | unstated | dashboard 'We hold the split for a week, record what it earned, and repeat'; doc | medium |
| Paired circular block bootstrap of Sharpe differences | block = 8 weeks, draws = 2000, seed = run.seed = 7 (shared with every other seeded component); n_blocks = ceil(T/block)  | config | configs/default.yaml:230-231 (bootstrap_blocks_weeks: 8, bootstrap_draws: 2000), :6 (seed: | stated | README:152 ('circular-block-bootstrap p-values'); docs/what-the-system-does.md:9 | medium |
| Sharpe ratio definition | mean(weekly excess over BIL) / std(ddof=1) * sqrt(52); returns NaN if fewer than 10 observations, sd == 0 or non-finite. | hardcoded | src/finorchestra/evaluation/metrics.py:33-38; excess built in src/finorchestra/pipeline.py | stated | README 'Evaluation that resists flattery'; docs/what-the-system-does.md:89 ('Sha | medium |
| Annualisation factor (weeks per year) | WEEKS = 52.0; sqrt(52) for vol/Sharpe, 52/len(r) exponent for geometric return, x52 for alpha, (0.5/sqrt(52))^2 for the  | hardcoded | src/finorchestra/evaluation/metrics.py:19 (WEEKS), :26, :30, :38, :84, :97-98, :194; src/f | literature | report.md header says 'Performance (weekly, ...)'; the factor itself is stated n | low |
| Annualised return and volatility computed on gross (not excess) returns; return is geometric, vol arithmetic | ann_return = prod(1+r)^(52/len) - 1 on gross; ann_vol = std(gross, ddof=1)*sqrt(52); Sharpe uses excess. Table columns a | hardcoded | src/finorchestra/evaluation/metrics.py:22-30, :205-211 (summarize passes gross for ann_ret | unstated | report.md header partially; nowhere explicit that return/vol/drawdown are gross | low |
| Attribution regression mechanics: HAC lag, annualisation, variance split | OLS with Newey-West cov_type='HAC', maxlags = 4 (hardcoded); alpha_annual = intercept*52 (arithmetic); t(alpha) from HAC | hardcoded | src/finorchestra/evaluation/metrics.py:165 ('OLS with Newey-West (HAC, 4 lags) standard er | stated | README:154 ('HAC t-stats and an exact variance split'); docs/what-the-system-doe | low |
| Baseline 'sixty_forty': 60% SPY / 40% IEF, static, ignores constraints | w['SPY']=0.60, w['IEF']=0.40 hardcoded tickers; breaches SPY cap 0.35, IEF cap 0.30, risk-weight 0.66 vs budget 0.60 and | hardcoded | src/finorchestra/evaluation/baselines.py:23-27, :33 | unstated | dashboard WHY: 'It ignores the bank's rules, so it is a familiar yardstick, not  | low |
| Bootstrap comparison pairs hardcoded | pairs = [(llm_feedback, rule), (llm_clip, rule), (llm_feedback, llm_clip), (rule, inverse_vol), (llm_feedback, inverse_v | hardcoded | src/finorchestra/pipeline.py:269-272; dashboard lookup src/finorchestra/explain/dashboard. | unstated | nowhere; report.md simply lists the six rows | low |
| Dashboard Sharpe-difference wording threshold of ±0.05 | d = Sharpe(s) - Sharpe(other) over the selected period: d > 0.05 -> tag 'ahead'/'improved'; d < -0.05 -> 'behind'/'hurt' | hardcoded | src/finorchestra/explain/dashboard.py:652 (verdict tags), :688 (idea takeaway) | unstated | nowhere | low |
| Dashboard cost grid and 30 bp headline hardcoded, independent of config | grid = [0, 5, 10, 20, 30] in JS; verdict and 'How to read the numbers' fix 30 bp ('0.3% on every unit traded'); costs re | hardcoded | src/finorchestra/explain/dashboard.py:725 (renderCost grid), :645 (net30 = ... * 30 / 1e4) | unstated | nowhere (the dashboard states 0.3% but not that it ignores the config grid) | low |
| Dashboard interpretive heuristics and display names | 'Around 0.5 is ordinary, 1.0 is very good, below 0 lost to cash' (Sharpe); 't above 2 in size counts as clear' (alpha t) | hardcoded | src/finorchestra/explain/dashboard.py:335, :770 (glossary), :730 (attrNote), :504-506 (NAM | unstated | stated in the dashboard text itself; not in README/docs | low |
| Dashboard luck-check thresholds | luck(p): p < 0.05 -> 'probably not luck (p = x.xxx)'; p < 0.2 -> 'suggestive but not conclusive (p = x.xx)'; else 'withi | hardcoded | src/finorchestra/explain/dashboard.py:633 (luck), :336, :770 (glossary 'luck check' and 'p | unstated | the 0.05 rule is stated in the dashboard itself; the 0.2 'suggestive' band is st | low |
| Dashboard recomputes metrics client-side from rounded embedded data | gross/excess returns rounded to 6 dp, weights and panel to 4 dp (_round default nd=4); JS turnover rebuilt from rounded  | hardcoded | src/finorchestra/explain/dashboard.py:21-27, :135-138, :516-519, :525-534, :537 (RANGES),  | unstated | dashboard note 'Luck checks are computed on the full run only; the numbers above | low |
| Deflated Sharpe formula pieces | SR0 = sqrt(v)*[(1-γ)Φ^{-1}(1-1/n) + γΦ^{-1}(1-1/(n e))], γ = 0.5772156649 (Euler-Mascheroni); PSR = Φ[(SR - SR0)*sqrt(T- | hardcoded | src/finorchestra/evaluation/metrics.py:77-95 | literature | README/docs name the paper; the T-1, non-excess-kurtosis and floor conventions a | low |
| Incremental information test mechanics (reported in report.md and dashboard) | targets [SPY, TLT, HYG], horizons [4, 13] weeks; y = rolling(h).sum().shift(-h) of weekly excess over BIL, matched to de | hardcoded | configs/default.yaml:163-165; src/finorchestra/signals/incremental.py:20-21, :24-28, :42-5 | stated | README:176-179 and 233-234; docs/what-the-system-does.md; lag rule and 3-day tol | low |
| Max drawdown on gross returns, NaN treated as 0 | wealth = cumprod(1 + r.fillna(0)); max_drawdown = min(wealth/cummax - 1); computed on gross weekly returns from a start  | hardcoded | src/finorchestra/evaluation/metrics.py:41-44; called with gross at :211; dashboard reimple | literature | dashboard lead text ('How far each player's dollar sat below its own previous hi | low |
| Minimum-sample guards | sharpe: NaN if < 10 obs; deflated_sharpe: NaN if T < 20; block bootstrap: NaN if T < 30; attribution: NaN if < 30; incre | hardcoded | src/finorchestra/evaluation/metrics.py:36, :79, :117, :176; src/finorchestra/signals/incre | unstated | README:199-200 and docs ('the bootstrap refuses to compute p-values on them') co | low |
| Regime share reporting | panel['regime'].value_counts(normalize=True).round(3): share of the 610 decision dates (not 609 return weeks) whose argm | hardcoded | src/finorchestra/pipeline.py:282; label from src/finorchestra/pipeline.py:95 (regime.label | unstated | report.md and dashboard show the numbers; argmax-vs-probability-mass choice is n | low |
| Risk-free proxy = BIL ETF weekly total return | rf = weekly_ret['BIL'] reindexed to return dates, missing filled with 0; averaged 1.92%/yr over the reference run (near  | data | configs/default.yaml:109-114 (BIL, 'cash-like short-term treasury bills', risk_free_ticker | unstated | docs/what-the-system-does.md:89 and README ('excess over the cash ETF'); the ETF | low |
| Turnover definition and first-row convention | one-way turnover_t = 0.5*sum\|w_t - w_{t-1}\|; row 0 = 1 - w_0[BIL] (pre-inception book is 100% cash); without a cash co | hardcoded | src/finorchestra/evaluation/metrics.py:47-61; alignment src/finorchestra/pipeline.py:257-2 | stated | README:153 ('charged on every trade including the first') and :185; docs/what-th | low |
| report.md truncates the certificate JSON at 6000 characters | json.dumps(summary['certificate'], indent=1)[:6000]; the reference run's certificate is 4891 chars so it fits, but addin | hardcoded | src/finorchestra/explain/report.py:183 | unstated | nowhere | low |
| run_id hashing | run_id = f'{run.name}-{sha1(json.dumps(cfg.model_dump(mode='json', exclude={'root'}), sort_keys=True))[:8]}'; hashes the | hardcoded | src/finorchestra/config.py:217-219; collision rule src/finorchestra/pipeline.py:173-178 (c | stated | README:42-43 and :190-191 ('the run id hashes the config, not the data') | low |

### Signals, regime and Fed text

| Assumption | Value | Kind | Where | Basis | Disclosed today | Severity |
|---|---|---|---|---|---|---|
| Offline lexicon stance formula and keyword lists | stance = (hawkish_hits - dovish_hits) / (hawkish_hits + dovish_hits + 3.0), clipped to [-1,1]; hits = total substring oc | hardcoded | src/finorchestra/llm/mock.py:18-29 (HAWKISH/DOVISH lists), :54-62 (lexicon_stance; `stance | unstated | README file map ('lexicon'); dashboard explorer lists the matched phrases per we | high |
| Stance scorer provider: LLM vs offline lexicon | text_signal.provider: same_as_llm; lexicon is used when provider == 'lexicon' OR llm.provider == 'mock'. Reference mock  | config | configs/default.yaml:155; src/finorchestra/signals/text_signal.py:63-64 (`use_lexicon = cf | stated | README file map ('Fed stance (LLM or lexicon)'); certificate 'model' block gives | high |
| Theme membership, signs, and equal-weight mean over available members | growth: [indpro_yoy +1, payrolls_3m +1, unrate_chg_3m -1]; inflation: [cpi_yoy +1, cpi_3m_ann +1, breakeven +1]; policy: | config | configs/default.yaml:145-149 (membership/signs); src/finorchestra/signals/zscores.py:93-97 | unstated | docs/what-the-system-does.md:30 ('Signed z-scores are averaged into four themes: | high |
| Z-score trailing window length | 10 years (zscore_window_years: 10) | config | configs/default.yaml:130; consumed at src/finorchestra/signals/zscores.py:50 (start = last | unstated | README 'Configuration' (as 'z-score windows', no value); docs/what-the-system-do | high |
| Date masking rules and relative week labels | Three regexes -> '[date]': 'Month D, YYYY', 'Month YYYY', bare 4-digit years 19xx/20xx; retrieved documents labelled 're | hardcoded | src/finorchestra/views/masking.py:17-21 (_DATE_PATTERNS), :83-84; src/finorchestra/views/l | stated | Certificate prompt_masking.what ('absolute dates -> [date] or t-k weeks'); READM | medium |
| Derived macro series: transform and period per raw series | growth_indpro_yoy = pct_change(INDPRO,12); growth_payrolls_3m = pct_change(PAYEMS,3); labor_unrate_chg_3m = diff(UNRATE, | data | configs/default.yaml:134-144; transforms implemented at src/finorchestra/signals/zscores.p | unstated | docs/what-the-system-does.md:30 in generic terms ('year-over-year change, three- | medium |
| HAC lag choice for the incremental regressions | statsmodels OLS cov_type='HAC', maxlags = max(1, h) (Bartlett kernel, library defaults otherwise) | hardcoded | src/finorchestra/signals/incremental.py:24-28 | literature | README ('HAC regressions'); docs/what-the-system-does.md:93 mentions HAC for att | medium |
| Incremental test regressor sets | BASE_COLS = [theme_growth, theme_inflation, theme_policy, theme_financial, tiz_epu, tiz_gpr] (excludes tiz_gpr_threat, t | hardcoded | src/finorchestra/signals/incremental.py:20-21, :34-37, :47-48, :61-62 | stated | README ('does our text signal add information beyond EPU/GPR/z-scores? (HAC regr | medium |
| LLM stance prompt wording, scale and input masking | System prompt: central-bank watcher, rate stance on [-1,+1] ('+1 = strongly hawkish (leaning toward higher rates / tight | hardcoded | src/finorchestra/signals/text_signal.py:27-32 (_SYSTEM), :80-89 (masked user message `self | unstated | Nowhere: the stance prompt is not reproduced in README/docs/worked example (whic | medium |
| Minimum history span before a z-score is emitted | 5 years (min_history_years: 5), measured from the first in-window observation to the latest observation | config | configs/default.yaml:131; applied at src/finorchestra/signals/zscores.py:52-54 (span_years | unstated | Nowhere (config file only). | medium |
| Novelty: TF-IDF cosine to the previous statement | 1 - cosine(TF-IDF) of the last two statements; TfidfVectorizer(ngram_range=(1,2) from text_signal.novelty_ngram, stop_wo | hardcoded | configs/default.yaml:156 (novelty_ngram: [1, 2]); src/finorchestra/signals/text_signal.py: | stated | README ('novelty (TF-IDF)'); docs/what-the-system-does.md:32 ('novelty against t | medium |
| Percentage rounding to nearest 0.5 (ties up), including fractions and ranges, prefixed 'about' | _half(v) = floor(v*2 + 0.5)/2 -> 5.25->5.5, 5.75->6, 4.75->5, 0.25->0.5; matches 'X percent', 'X%', 'X to Y percent', fr | hardcoded | src/finorchestra/views/masking.py:23-24 (_NUM/_PCT), :39-50 (_half, _mask_pct), :85; appli | stated | Certificate prompt_masking.what ('rounded to the nearest 0.5'); README re-verifi | medium |
| Regime logistic temperature | 0.75 (regime.temperature), p_up = 1/(1+exp(-composite/0.75)); duplicated as a function default | config | configs/default.yaml:152; src/finorchestra/signals/regime.py:39-47 (`_sigmoid`, `estimate_ | stated | README 'Configuration' names 'regime temperature' (no value/formula); the value  | medium |
| Regime quadrant definition (boundary at composite = 0, i.e. at the theme's own trailing 10-year mean) | goldilocks: growth>=0 & inflation<0; overheating: growth>=0 & inflation>=0; stagflation: growth<0 & inflation>=0; recess | hardcoded | src/finorchestra/signals/regime.py:3-7 (docstring) and :48-54; QUADRANTS tuple :20 | stated | docs/what-the-system-does.md:34 (four quadrants, no threshold); docs/finorchestr | medium |
| Retrieval score: (1 + BM25) x recency decay, hard availability filter | score = (1 + BM25(k1=1.5, b=0.75)) * 0.5 ** (age_days / max(1, halflife)); documents with available_from > as_of exclude | hardcoded | src/finorchestra/signals/retrieval.py:44 (filter), :54-63 (_bm25 with `k1: float = 1.5, b: | stated | README file map ('BM25 x recency over statements, hard date filter'); certificat | medium |
| Rule-agent scaling of the text signal | text_stance = 2.0 * surprise, multiplier 1.0 (not regime-weighted), then beta_text_stance * text_stance per asset | hardcoded | src/finorchestra/views/rule_agent.py:18 (`text_stance = 2.0 * text.surprise # scaled to a  | stated | Nowhere (docs/what-the-system-does.md:38 says the rule agent 'adds a Fed-surpris | medium |
| Stance score cache keyed only by (scorer tag, statement date) | data/processed/fomc_stance_<lexicon\|model>.csv, loaded at startup, appended on every new score; key excludes prompt tex | hardcoded | src/finorchestra/signals/text_signal.py:63-70 (cache path/tag), :72-76 (lookup by str(date | stated | Nowhere in outputs (not in certificate, report or docs). | medium |
| Surprise = stance x (0.5 + novelty) | surprise = stance * (0.5 + novelty), range [-1.5, 1.5]; duplicated independently in the mock | hardcoded | src/finorchestra/signals/text_signal.py:123; duplicated at src/finorchestra/llm/mock.py:12 | stated | docs/what-the-system-does.md:32 ('stance times (0.5 plus novelty)'); docs/rl-and | medium |
| Text-index (EPU/GPR) smoothing and minimum history | trailing 21-observation (business-day) rolling mean with min_periods=10 as the 'current' reading; series skipped entirel | hardcoded | src/finorchestra/signals/zscores.py:103-112 (`s.rolling(21, min_periods=10).mean()`, `if l | stated | docs/what-the-system-does.md:30 ('smoothed over 21 days'; code is 21 observation | medium |
| Z-score clip | +/-3.0 (clip: 3.0) | config | configs/default.yaml:132; applied at src/finorchestra/signals/zscores.py:59 (np.clip(z, -c | unstated | Nowhere (README mentions 'z-score windows' but not clipping; not in docs, dashbo | medium |
| Annualisation frequency inference for pct_change_annualized | periods_per_year snapped from the median index spacing to 252/52/12/4/1 with 20% relative tolerance; fallback 12.0 when  | hardcoded | src/finorchestra/signals/zscores.py:18-26 and :37-40 | stated | Nowhere. | low |
| Asset masking to letters and un-masking tolerance | tickers -> 'Asset A'..'Asset J' in universe order (SPY=A, TLT=B, IEF=C, TIP=D, LQD=E, HYG=F, GLD=G, DBC=H, UUP=I, BIL=J) | hardcoded | src/finorchestra/views/masking.py:60-78 (build, code, ticker); configs/default.yaml:179 (m | stated | Certificate prompt_masking.enabled/what; README; docs/what-the-system-does.md:40 | low |
| Fed text corpus: statements only, release-day availability, paragraph filtering | FOMC post-meeting statements 2007-2026 (fomc.years), no minutes/speeches/press conferences; usable same day (fomc.lag_da | data | configs/default.yaml:122-124; src/finorchestra/data/fomc.py:26-33, :81-96, :136 (available | stated | Certificate inputs: 'FOMC statements ... yes: dated by release; usable from rele | low |
| Forward-return construction and sample rules for the incremental test | y = sum (not compounded) of the next h weekly excess returns over BIL (`rolling(h).sum().shift(-h)`), aligned to decisio | hardcoded | src/finorchestra/signals/incremental.py:42-52; excess returns defined at src/finorchestra/ | stated | Report table shows n; README notes the sign flip on the short slice; constructio | low |
| Incremental test horizons | [4, 13] weeks (horizons_weeks) | config | configs/default.yaml:164; used at src/finorchestra/signals/incremental.py:41 | unstated | docs/what-the-system-does.md:94 ('forward 4- and 13-week returns'); report/dashb | low |
| Incremental test targets | [SPY, TLT, HYG] | config | configs/default.yaml:165; used at src/finorchestra/signals/incremental.py:38 | stated | Report/dashboard table rows; README results paragraph. | low |
| Independence of the growth and inflation axes; missing-theme default; rounding | P(quadrant) = product of two independent sigmoids; a missing theme is treated as composite 0.0 (p_up = 0.5); probabiliti | hardcoded | src/finorchestra/signals/regime.py:44-55 (`themes.get("growth", 0.0)`, `p_g_up * (1 - p_i_ | unstated | Nowhere. | low |
| Minimum observation counts and degenerate-variance guards for a z-score | len(series) >= 3; len(hist) >= 12; std(hist) > 1e-12 (else None) | hardcoded | src/finorchestra/signals/zscores.py:47-48 (`if len(s) < 3: return None`), :53 (`if len(his | unstated | Nowhere. | low |
| Per-document character cap (head truncation) | 1400 chars (max_chars_per_doc: 1400), keeping the FIRST 1400 characters of each statement; code default is 1800 | config | configs/default.yaml:160 (no comment; shares the token-budget rationale of :159); default  | unstated | docs/rl-and-fed-reuse-scope.md:89 ('two documents of 1,400 characters'). Head-vs | low |
| Recency half-life | 120 days (recency_halflife_days: 120) | config | configs/default.yaml:160; used at src/finorchestra/signals/retrieval.py:72 | unstated | Nowhere (config only). | low |
| Reference window excludes the latest observation ('ends before it') | hist = observations with start <= obs_date < last_obs_date; z = (last - mean(hist)) / std(hist, ddof=1); window defined  | hardcoded | src/finorchestra/signals/zscores.py:49-58 (esp. :51 `hist = s.loc[(s.index >= start) & (s. | stated | docs/what-the-system-does.md:30 ('using only observations before the latest one' | low |
| Retrieval query construction and tokenizer | query = 'inflation growth employment policy rate outlook risks ' + first 3 key_phrases of the LATEST statement; tokens = | hardcoded | src/finorchestra/views/llm_agent.py:76 (query string); src/finorchestra/signals/retrieval. | unstated | Nowhere. | low |
| Retrieval top_k | 2 (top_k: 2); note the code default in config.py is 3 | config | configs/default.yaml:159; default at src/finorchestra/config.py:118 (`top_k: int = 3`); us | stated | docs/what-the-system-does.md:40 ('the two most relevant retrieved statements');  | low |
| Stance change definition | stance_change = stance(latest) - stance(previous statement), with 0.0 substituted when no previous statement exists; pre | hardcoded | src/finorchestra/signals/text_signal.py:117-122 | unstated | Report/dashboard column 't(stance Δ)'; definition nowhere. | low |
| Unicode dash handling in fraction ranges | _DASH = '-‐‑‒–—―' (ASCII hyphen plus six Unicode hyphens/dashes) normalised to '-' before parsing '5-1/4'; upstream repa | hardcoded | src/finorchestra/views/masking.py:22-23, :28; src/finorchestra/data/fomc.py:36-48 | stated | README re-verification paragraph ('the prompt masker garbled fractional rate ran | low |

### View generators

| Assumption | Value | Kind | Where | Basis | Disclosed today | Severity |
|---|---|---|---|---|---|---|
| Mock fallback on any exception in an 'llm' strategy, and how it is labelled | LLMAgent._call catches Exception, logs a warning, increments trace.fallbacks and returns MockLLM().respond(...) on the s | hardcoded | src/finorchestra/views/llm_agent.py:112-118; src/finorchestra/llm/client.py:151-158; label | stated | certificate.model_call_stats.fallbacks_to_mock (summary.json, report.md, dashboa | high |
| Mock playbook: annual excess return by asset kind and regime | src/finorchestra/llm/mock.py:31-43, verbatim (goldilocks, overheating, stagflation, recession): "equities": (0.040, 0.01 | hardcoded | src/finorchestra/llm/mock.py:31-46 (_PLAYBOOK, _ORDER, _RISKY, unused _DURATION_BEARERS),  | unstated | README:86-88 ('a transparent regime playbook ... The mock is not a language mode | high |
| Mock revision rules: keyword matching on critic messages and fixed edit sizes | On a <<VIOLATIONS>> block the mock edits the last assistant answer: (1) lines containing 'single-asset' and an asset cod | hardcoded | src/finorchestra/llm/mock.py:166-233; the keywords are produced by src/finorchestra/alloca | stated | The notes ('halved: single-asset cap', 'duration relief via cash') appear in rev | high |
| Rule-agent theme loadings per asset | configs/default.yaml lines 184-193, verbatim: SPY: { growth: 0.030, inflation: -0.010, policy: -0.010, financial: -0.025 | config | configs/default.yaml:182-193 (key rule_agent.loadings); consumed at src/finorchestra/views | unstated | Values only in configs/default.yaml. README:93 and README:239-240 say the loadin | high |
| Confidence bounds: schema [0,1], Black-Litterman clamp [0.02,0.98] | Schema: confidence ge=0.0, le=1.0 (out-of-range -> ValidationError -> retry). Downstream: conf clamped to [0.02, 0.98] a | hardcoded | src/finorchestra/views/schema.py:16 `confidence: float = Field(ge=0.0, le=1.0)`; src/finor | literature | System prompt tells the model 'confidence in [0,1]' (llm_agent.py:28). The 0.02/ | medium |
| Constraint-feedback revision prompt and transcript structure | Appended to the original conversation: an assistant turn containing the previous ViewSet as masked JSON, then a user tur | hardcoded | src/finorchestra/views/llm_agent.py:97-110; configs/default.yaml:211 `feedback_rounds: 2`; | stated | Reproduced verbatim in docs/worked-example-2026-08-07.md:304-315; README:141-147 | medium |
| Declared knowledge cutoff 2024-10-01 (recorded, never validated or enforced) | llm.knowledge_cutoff: "2024-10-01" (config default for model qwen2.5:3b); overridable with `--knowledge-cutoff`. Certifi | config | configs/default.yaml:178; src/finorchestra/config.py:136; src/finorchestra/llm/client.py:9 | stated | certificate.knowledge_cutoff and certificate.model.declared_knowledge_cutoff in  | medium |
| Evidence list capped at 6 items (schema-enforced, retry on breach) | View.evidence: list[str] max_length=6. A 7th item is a ValidationError, which triggers a retry with the error text appen | hardcoded | src/finorchestra/views/schema.py:17 `evidence: list[str] = Field(default_factory=list, max | unstated | Only as sample_errors inside certificate.model_call_stats (summary.json / report | medium |
| LLM system prompt: role, no-memory instruction, output contract | Verbatim (llm_agent.py:23-35): "You are a macro strategist at an institutional asset manager. You form forward-looking v | hardcoded | src/finorchestra/views/llm_agent.py:23-35 (`_SYSTEM`) | stated | Reproduced verbatim in docs/worked-example-2026-08-07.md:16-31. Summarised in do | medium |
| Mock adjustment coefficients for Fed surprise and newspaper indices | surprise = fed_stance * (0.5 + fed_statement_novelty) (recomputed inside the mock). long/intermediate govt and IG: if \| | hardcoded | src/finorchestra/llm/mock.py:112-156 | unstated | Per-view evidence strings in decisions/*.json, latest_decision.md and the dashbo | medium |
| Mock asset-kind detection by keyword in the config label | _kind(label): first _PLAYBOOK key that is a substring of label.lower() ('equities', 'long-term government', 'intermediat | hardcoded | src/finorchestra/llm/mock.py:244-258; labels at configs/default.yaml:65,70,75,80,85,90,95, | unstated | Nowhere. | medium |
| Mock emission threshold, confidence formula, evidence and view caps | Fresh views: skip if \|q\| < 0.004; conf = clamp(0.30 + 0.35*top_p + min(0.25, \|q\|/0.06), 0.2, 0.9) where top_p = max  | hardcoded | src/finorchestra/llm/mock.py:158-163, :105-109 | unstated | Nowhere outside mock.py; the confidence numbers appear in every mock view table  | medium |
| Mock lexicon stance scorer (used as fed_stance in every mock run and as the stance fallback) | HAWKISH (21 phrases incl. 'elevated', 'strong', 'robust', 'persistent', 'above 2 percent') and DOVISH (28 phrases incl.  | hardcoded | src/finorchestra/llm/mock.py:18-29, :54-62; selected at src/finorchestra/signals/text_sign | unstated | README:102 ('Fed stance (LLM or lexicon)'), docs/what-the-system-does.md:32 give | medium |
| Mock playbook scale factor 0.6 | base = 0.6 * probability-weighted playbook return. | hardcoded | src/finorchestra/llm/mock.py:128-129 | stated | Only the code comment; the first evidence string of each mock view ('regime-weig | medium |
| Prompt masking scheme (llm.masking: true) | Tickers -> 'Asset A'..'Asset Z' in universe order (26-asset limit via string.ascii_uppercase); 'Month D, YYYY', 'Month Y | config | configs/default.yaml:179 `masking: true`; src/finorchestra/views/masking.py:17-24 (pattern | stated | Certificate prompt_masking {enabled, what, limitation} in summary.json, report.m | medium |
| Regime multipliers (trust in each theme by quadrant) | configs/default.yaml lines 195-198, verbatim: goldilocks: { growth: 1.0, inflation: 0.6, policy: 0.8, financial: 1.0 } o | config | configs/default.yaml:194-198 (key rule_agent.regime_multipliers); applied at src/finorches | unstated | Values only in configs/default.yaml. README:148-149 ("Theme loadings are reweigh | medium |
| Rule-agent confidence mapping and its saturation point 0.05 | conf = confidence_floor + (confidence_ceiling - confidence_floor) * min(1, \|q\| / 0.05); floor 0.25, ceiling 0.85 (conf | hardcoded | src/finorchestra/views/rule_agent.py:38 `conf = rc.confidence_floor + (rc.confidence_ceili | unstated | The 0.25/0.85 floor and ceiling are in configs/default.yaml with no comment; the | medium |
| ViewSet.normalized(): direction overrides sign, neutral zeroed | For every view: overweight -> q = \|q\|; underweight -> q = -\|q\|; neutral -> q = 0.0. Applied to rule views, every LLM | hardcoded | src/finorchestra/views/schema.py:30-42; called at rule_agent.py:58, llm_agent.py:114 and : | stated | Nowhere outside the code docstring; the worked example (docs/worked-example-2026 | medium |
| Which documents the LLM agent is shown: retrieval query, top_k=2, 1400-char truncation, week-floored age | Query = "inflation growth employment policy rate outlook risks " + first 3 key_phrases; score = (1+BM25) * 0.5^(age/120  | data | src/finorchestra/views/llm_agent.py:66-77; configs/default.yaml:158-161 (retrieval.top_k 2 | stated | docs/what-the-system-does.md:40: 'the two most relevant retrieved statements wit | medium |
| Which signals the LLM agent is shown (and which are withheld) | Shown (rounded to 3 dp): themes, macro_z (all 10 derived z-scores), text_index_z (epu, gpr, gpr_threat, gpr_act), regime | data | src/finorchestra/views/llm_agent.py:54-64 (`_signals_block`), :76 (key_phrases[:3] into qu | unstated | The JSON block is reproduced verbatim in docs/worked-example-2026-08-07.md:57-85 | medium |
| response_format = {type: json_object} on every call | payload['response_format'] = {'type': 'json_object'} whenever json_mode is True (always, for both views and stance tasks | hardcoded | src/finorchestra/llm/client.py:108-109 | stated | README:105 ('OpenAI-compatible client with JSON schema validation, retries, fall | medium |
| text_stance input = 2.0 x Fed surprise, no regime multiplier | text_stance = 2.0 * text.surprise, where surprise = stance * (0.5 + novelty) (stance in [-1,1], novelty in [0,1], so tex | hardcoded | src/finorchestra/views/rule_agent.py:18 `text_stance = 2.0 * text.surprise # scaled to a z | stated | The evidence strings in report.md/latest_decision.md/dashboard show the scaled v | medium |
| Expected excess return clamp +/-0.15 per year | expected_excess_return_annual is clamped to [-0.15, 0.15] by a pydantic field validator before any other processing. | hardcoded | src/finorchestra/views/schema.py:19-22 `return max(-0.15, min(0.15, float(v)))` | unstated | Nowhere: not in README, docs, the system prompt (which gives only the example 0. | low |
| Model identity string for the mock and what the certificate calls it | describe(): provider 'mock' -> model 'deterministic-mock', base_url null, temperature as configured (0.0, though the moc | hardcoded | src/finorchestra/llm/client.py:88-96 | stated | summary.json.model and certificate.model; dashboard runline; report.md. | low |
| Number of views: prompt says 2-6, schema accepts 1-10, mock emits up to 6 (8 after revision), rule emits up to | System prompt: "Provide between 2 and 6 views." Schema: views min_length=1, max_length=10. Mock fresh views [:6], after  | hardcoded | src/finorchestra/views/llm_agent.py:35; src/finorchestra/views/schema.py:27 `views: list[V | unstated | The '2 and 6' instruction is reproduced verbatim in docs/worked-example-2026-08- | low |
| Retry policy: max_retries 2 (3 attempts), 1+attempt second backoff, timeout 120 s, error text appended to the  | for attempt in range(max_retries + 1): on ValidationError/ValueError/JSONDecodeError/KeyError append the bad reply plus  | config | configs/default.yaml:176-177 (timeout_s 120, max_retries 2); src/finorchestra/llm/client.p | stated | README:105; certificate.model_call_stats {calls, failures, fallbacks_to_mock, sa | low |
| Rule-agent evidence construction, view cap of 8, and the 1e-4 display threshold | Evidence = top 3 contributions by \|c\| with \|c\| > 1e-4 formatted 'theme: z=%+.2f contributes %+.3f', plus 'regime <la | hardcoded | src/finorchestra/views/rule_agent.py:34-35 (1e-4), :39-41 (top 3 + regime line), :51-53 (f | unstated | docs/what-the-system-does.md:38 discloses 'up to eight views'. The 3-item eviden | low |
| Rule-agent expected excess return formula and emission threshold | q = sum over themes of beta_theme * mult_theme * z_theme, rounded to 4 dp; a view is emitted only if \|q\| >= 0.003 (0.3 | hardcoded | src/finorchestra/views/rule_agent.py:32-37 (`c = beta * mult * x; q += c ... if abs(q) < 0 | unstated | docs/what-the-system-does.md:38: "emits up to eight views, for the assets whose  | low |
| Sampling temperature 0.0, omitted for model names matching ^(gpt-5\|o[1-9]) | llm.temperature: 0.0 sent as payload['temperature'] unless re.match(r'^(gpt-5\|o[1-9])', model); recorded in certificate | config | configs/default.yaml:175; src/finorchestra/llm/client.py:105-107; reported client.py:94 | stated | Certificate model.temperature; README:85; dashboard/report show the certificate  | low |
| Unmasking: views on unrecognised asset codes are dropped silently; empty result becomes a neutral cash view | Each view's asset is mapped code -> ticker (exact, or by stripping a parenthetical label and title-casing); views not ma | hardcoded | src/finorchestra/views/llm_agent.py:121-130; src/finorchestra/views/masking.py:73-78 | unstated | Nowhere. | low |
| User-prompt boilerplate: hardcoded '10-year window' and the signal guide | "Decision date: t (the current week). All z-scores are standardized against a trailing 10-year window." ... "Signal guid | hardcoded | src/finorchestra/views/llm_agent.py:79-85; the real window is configs/default.yaml:130 `zs | unstated | Reproduced verbatim in docs/worked-example-2026-08-07.md:33-35 and :88-89. The c | low |

