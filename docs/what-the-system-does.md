# What Finorchestra Does

**Status:** describes the system as built on 2026-09-06 and revised on 2026-09-07 (revision 2: data-derived inputs; see the note at the top of section 3). Companion to `finorchestra-first-principles.md`, which explains the concepts; this document explains the machine.

---

## 1. In one paragraph

Every Friday, the system asks: given everything that was publicly knowable at today's close, how should a rule-bound institutional portfolio of ten ETFs be positioned for next week? It answers three times in parallel with the same information: once with a formula fitted on past data, once with a language model whose proposals are silently clipped to the rules, and once with the same language model that is told which rules its proposal broke and asked to reconsider. It then records what each would have earned, and evaluates the three against passive benchmarks with methods designed to be hard to fool.

## 2. The question we are actually testing

Not "can an AI predict markets." The question is narrower and answerable: **holding the information fixed, does a reasoning layer add value over a deterministic rule, and does telling that reasoning layer about institutional constraints help or hurt?** Every design choice below serves that comparison.

## 3. One decision, step by step

> **Version-1 example.** The walkthrough in this section reproduces the decision of 2026-08-14 from the run `ollama-smoke-35f09d83`, made under the first version (hand-set market weights, fixed 30% caps, hand-written formula agent, stance-times-novelty surprise). The mechanism is the same in revision 2; the numbers and the rule messages are version 1's.

Take Friday 2026-08-14, a date from the real-model run. Here is what happened.

### 3.1 Assemble what was knowable

The point-in-time store returns a snapshot containing only data available at that day's close.

- **Official statistics** (unemployment, payrolls, CPI, industrial production) come back exactly as published on the latest Friday on or before the date, from reconstructed ALFRED vintages. A number revised later is invisible; a number not yet released is absent.
- **Market series** (effective fed funds, yield curve, credit spread, breakeven inflation, VIX) are never revised but are posted the next business day, so they enter with a one-day lag. **ETF prices** are used through that day's close; only returns enter the model, so later dividend adjustments cannot leak.
- **Newspaper indices** (EPU, GPR) are used with a two-business-day lag.
- **FOMC statements** are usable from their release day. On this date the newest was 2026-07-29.

### 3.2 Turn raw data into signals

Each macro series is transformed (year-over-year change, three-month change, level) and converted to a z-score against its own trailing ten-year window, using only observations before the latest one. Signed z-scores are averaged into four themes: growth, inflation, policy, financial stress. The daily newspaper indices are smoothed over 21 days and z-scored the same way.

The 2026-07-29 statement is scored for stance on a dovish-to-hawkish scale (here -0.50, dovish) and for novelty against the prior statement (0.06, nearly identical wording). (Version 1 also combined the two into a "surprise" number; revision 2 passes stance and novelty separately.)

The regime estimate turns the growth and inflation themes into probabilities over four quadrants. On this date: goldilocks 29 percent, recession 27 percent, overheating 23 percent, stagflation 21 percent. An undecided macro picture.

### 3.3 Form views two ways from identical inputs

**The fitted formula agent** (revision 2; the first version used a hand-written loading table) fits, at every decision date and using only weeks whose outcome was already known, a ridge regression of each fund's next-four-week excess return on the four theme composites and the three Fed-text features. It predicts from today's features, sets confidence to the fit's own probability that the sign is right, and emits up to six views. It has no judgment and no hand-set loadings. It is the floor.

**The LLM agent** receives a prompt containing the asset list with tickers replaced by letters and plain descriptions, the same z-scores and regime probabilities as a JSON block, the Fed stance and novelty, and the two most relevant retrieved statements with dates masked to "t minus k weeks." It is instructed to reason as a strategist and return a JSON view set. On this date the real model (qwen2.5:3b via Ollama) returned:

| Asset | Direction | Expected excess return | Confidence | Cited evidence |
|---|---|---|---|---|
| SPY | overweight | +5.0% | 0.80 | growth z-scores |
| TIP | overweight | +3.0% | 0.80 | breakeven inflation |
| TLT | underweight | -2.0% | 0.70 | CPI z-scores |
| GLD | underweight | -2.0% | 0.70 | Fed stance |
| IEF, LQD | neutral | 0 | 0.9, 0.8 | curve, credit spread |

Its stated reasoning: "solid growth and stable inflation, but elevated geopolitical risks, suggest a Goldilocks regime." Every view carries citations to specific inputs, so the explanation is not reconstructed afterward.

### 3.4 Turn views into a portfolio that obeys the rules

Black-Litterman blends the views into expected returns, starting from a neutral portfolio computed from data each week (inverse-volatility over the risky funds, with no typed-in weights) and tilting by confidence: a 0.9-confidence view nearly pins its asset's expected return; a 0.2-confidence view barely moves it. A quadratic program then maximizes expected return minus risk minus a turnover penalty, subject to:

| Rule (revision 2: relative to the neutral portfolio) | Setting |
|---|---|
| Long only, fully invested | yes |
| Active weight per fund | within 15 points of the neutral weight (cash included) |
| Portfolio volatility | at most 1.25 times the neutral portfolio's |
| Portfolio duration | within 2 years of the neutral portfolio's; fund durations estimated from data |
| Regulatory risk-weighted exposure (capital) | at most 1.25 times the neutral portfolio's; risk weights from 12 CFR 217 by fund kind |
| One-way turnover per week | at most 25% |

The five numbers are placeholders for the client's own policy limits and are labelled so in the configuration and in every run's certificate. The worked example below was produced under the first version's fixed caps (30% per fund) and is kept for the record; the mechanism is identical.

A deterministic critic re-checks the executed weights against every rule and lists violations in plain English. In every one of the 610 backtest weeks and 14 real-model weeks the final list was empty.

### 3.5 The feedback loop, and what it did here

The critic also reports which institutional rules were **binding**: pinned at their limit because the views asked for more. On this date the first-pass LLM views pinned the equity cap at 35 percent and the inflation-protected bond cap at 30 percent. Those two messages went back to the model:

> "SPY (broad domestic equities) is pinned at its single-asset cap of 35%; the views asked for more. TIP (inflation-protected government bonds) is pinned at its single-asset cap of 30%; the views asked for more."

The model revised twice. It trimmed the equity view from +5 to +4 percent, flipped inflation-protected bonds from a +3 percent overweight to a small underweight, and halved its gold and long-bond underweights. Both caps stopped binding, but the revised book then sat on the duration floor, the capital budget, and the equity cap, so the second round changed nothing further. That is recorded in the decision file. The clipped variant used the first-pass views unchanged. Both variants and the rule agent then have executable weights:

| | SPY | TLT | IEF | TIP | HYG | DBC | UUP | BIL |
|---|---|---|---|---|---|---|---|---|
| llm_feedback final weights | 35.0% | 1.9% | 3.1% | 11.0% | 15.8% | 5.8% | 8.0% | 19.2% |

### 3.6 Write the explanation

A JSON file for the date holds every number above: the snapshot's signal values, regime probabilities, Fed text features, each strategy's views with evidence, the Black-Litterman prior and posterior, which constraints bound, the revision history with views before and after each round, final weights, and the critic's verdict. A Markdown rendering of the latest decision sits beside it.

## 4. The backtest around the decision

The pipeline repeats step 3 for every Friday from 2015-01-02 to the latest price date, 610 times. For each strategy it records the weights, the realized return over the following week, and the one-way turnover. Two passive baselines that form no views run alongside: the neutral portfolio ("benchmark", the same data-derived portfolio the prior and the mandate use) and 60/40.

Then it evaluates:

- **Sharpe ratio** on returns in excess of the cash ETF.
- **Cost curve:** Sharpe after charging 0, 5, 10, 20, 30 basis points on each week's one-way turnover, including the initial trade out of cash.
- **Deflated Sharpe:** the probability that a strategy's Sharpe beats the best of N skill-less strategies, with N set to the number of strategies run and the dispersion of Sharpe measured across them (no assumed prior).
- **Paired circular block bootstrap** of Sharpe differences between strategies, with confidence intervals and p-values.
- **Return attribution:** regression of weekly excess returns on ETF-built factors (market, duration, credit, commodities, dollar) with HAC standard errors, splitting variance into market, style, their covariance, and residual, which equals one minus R².
- **Incremental information test:** do the three Fed-text features (stance, stance change, novelty) predict forward 4- and 13-week returns after controlling for the theme z-scores and the newspaper indices?
- **Contamination certificate:** for every input, how point-in-time it truly is; model identity, temperature, declared knowledge cutoff, share of decision dates after it; prompt masking; number of model failures and fallbacks; declared trial count.

A separate command deletes every row of data published after a chosen date and re-runs the decision. The output must match the full-data decision exactly. It does, on 2020-05-01, 2022-06-17, and 2025-03-14.

## 5. What the reference run found

Mock model, 610 weeks, run `mock-full-v3-02621a1e` under revision 2 (data-derived neutral portfolio, estimated
durations, regulatory risk weights, fitted formula agent, empirical regime percentiles, Ledoit-Wolf
constant-correlation covariance shrinkage). The mock is a deterministic regime playbook that stands in for a language model so the pipeline reproduces
bit for bit without keys. The version-1 run `mock-full-b811156c` (hand-set weights, fixed 30% caps, hand-written
formula) is kept for the record; its table is in the git history of this file and in the assumptions register.

| Strategy | Ann. return | Ann. vol | Sharpe | Max drawdown | Turnover/wk | Sharpe at 30bp |
|---|---|---|---|---|---|---|
| rule (fitted formula) | +2.3% | 5.9% | 0.09 | -14.7% | 9.3% | -0.15 |
| llm_clip | +4.6% | 4.8% | 0.57 | -7.2% | 3.7% | 0.45 |
| llm_feedback | +3.8% | 4.9% | 0.39 | -11.7% | 6.2% | 0.19 |
| benchmark (neutral portfolio) | +4.0% | 5.0% | 0.43 | -11.7% | 0.5% | 0.41 |
| sixty_forty | +8.9% | 10.1% | 0.71 | -20.8% | 0.2% | 0.70 |

None of the differences among the three strategies, or between them and the neutral portfolio, is distinguishable
from zero: bootstrap p-values run from 0.08 to 0.87. Two things are visibly different from version 1. The fitted
formula agent is weak (Sharpe 0.09 with 9.3 percent weekly turnover): a ridge regression of four-week forward returns
on seven weekly features finds little that is stable, and the hand-written loadings it replaced, which scored 0.61,
had encoded textbook relationships that the data of 2015 to 2026 do not confirm. That is the honest floor now, and it
is the point of estimating rather than assuming. Second, the feedback loop fires on 593 of 610 weeks (97 percent):
the mandate is an active band around the neutral portfolio, and the mock's playbook views press against those bands
almost every week, most often the dollar and gold bands, the duration floor and the volatility allowance. Revision
cleared every binding rule on 49 weeks. The critic found zero violations on executed weights and the turnover cap
never had to be relaxed.

The incremental test now reports the three Fed-text features separately. Hawkish stance carries a small negative
relation with forward equity returns (SPY t = -2.1 at 4 weeks, high yield -2.0) and nothing for Treasuries; stance
change and novelty add little. Consistent with the literature, not evidence of a tradable edge.

A note on provenance. The version-1 figures were themselves produced after an adversarial re-verification that
found and fixed a fed-funds leak, a turnover accounting error, an attribution error, an undisclosed deflated-Sharpe
prior and a masking defect. The assumptions sweep that followed found two more defects, fixed before this run: the
mock's revision handler halved the wrong asset on cap messages, and the masker rounded quarter-point rate moves to
half a point. Run directories are never overwritten: every run id is a hash of its configuration.

## 6. What the real-model runs found

Two fourteen-week runs over 2026-06-05 to 2026-09-04, both entirely after the models' declared training cutoffs, so recall of history is not a concern for this slice. In both, every call returned valid JSON, nothing fell back to the mock, and the critic found no violation on any executed weight vector.

- **Local qwen2.5:3b via Ollama** (run `ollama-smoke-35f09d83`): 42 calls at about 51 seconds each, 36 minutes in all. Its first-pass views hit an institutional limit on every one of the 14 dates, and its revisions never cleared them: 0 of 14. Its evidence lists signal names without values.
- **gpt-4.1-mini via the OpenAI API** (run `openai-smoke-c9e172b2`): 40 calls at about 10 seconds each, 7 minutes in all. Its evidence cites the numbers it used ("infl_cpi_3m_ann 1.52, gpr_threat 1.68"), its first-pass views bound on 12 of 14 dates, and its revisions cleared every binding constraint on 5 of those, with rationales that name the rule being satisfied: "to comply with the portfolio duration floor of 2.0 years, the underweight on government bonds is reduced to neutral."

Fourteen weekly returns say nothing about performance, and the bootstrap declines to compute p-values on so short a sample. What the runs establish is that the plumbing works with two very different models, and that the value of the feedback loop depends on the model's ability to act on constraint feedback, which the small model lacked and the hosted model has.

**The post-cutoff run** (`openai-postcutoff-v3-3baad69b`, revision 2) is the only slice on which a real model's
performance can be read without a memorisation worry. gpt-4.1-mini decided all 114 weeks from 2024-07-05 to
2026-09-04, every one after its declared cutoff, in 31 minutes and 261 calls, with no schema failures, no fallbacks
and no critic violations. Earlier runs are kept for the record: version 1 (`openai-postcutoff-aefba080`, hand-set
weights and fixed 30% caps) and a withdrawn first revision-2 run whose covariance shrinkage inflated low-risk funds'
variance (`openai-postcutoff-v2-c2d35cef`).

| Strategy | Ann. return | Ann. vol | Sharpe | Max drawdown | Turnover/wk | Sharpe at 30bp |
|---|---|---|---|---|---|---|
| rule (fitted formula) | +12.4% | 5.4% | 1.42 | -3.5% | 10.2% | 1.13 |
| llm_clip | +5.7% | 4.7% | 0.34 | -3.8% | 16.2% | -0.20 |
| llm_feedback | +7.0% | 4.5% | 0.62 | -3.0% | 16.4% | 0.05 |
| benchmark (neutral portfolio) | +7.1% | 3.7% | 0.76 | -2.9% | 1.2% | 0.71 |
| sixty_forty | +11.9% | 9.3% | 0.82 | -9.0% | 0.9% | 0.80 |

Three findings, in decreasing order of confidence. First, the version-1 headline did not survive the change to a
data-based mandate: the model told which rules it broke now beats the same model silently clipped by 0.27 Sharpe with
a bootstrap p-value of 0.41, where version 1 had 0.78 and 0.03. The direction held; the size and the significance did
not. An active band around a risk-balanced neutral portfolio binds differently from fixed caps (the loop fired on 77
of 114 weeks and cleared every rule on 18), and the gap is now well inside what luck produces. Second, neither AI path
beats the neutral portfolio (feedback -0.14, p = 0.67). Third, the fitted formula agent scores 1.42 on this two-year
slice, having scored 0.09 over the ten-year mock run: a weekly-refit regression can look excellent over one regime and
poor over five, and 114 weeks cannot separate skill from a good stretch. The incremental test's sign flips relative
to the ten-year run, which is what a short-sample estimate does.

The honest one-sentence summary, revision 2: the fitted formula did best on the two years that cannot be memorised,
neither AI path beat the neutral portfolio, and telling the model which rules it broke helped in direction but not
by an amount distinguishable from luck.

## 7. What the system is not

- It is not a forecaster of interest rates or recessions. It forms structured weekly views under uncertainty and shows its evidence.
- It is not novel in its parts. Z-scores, Black-Litterman, quadratic programming, FinBERT-style sentiment, and the two newspaper indices are all established. The contribution is the joints: identical inputs to both agents, regime conditioning, constraint feedback to the reasoner, and evaluation strict enough to be believed.
- Its mock results are about architecture, not intelligence. Claims about a language model require a real endpoint, ideally evaluated on dates after that model's training cutoff.

## 8. Where things live

| What | Where |
|---|---|
| Every modelling choice | `configs/default.yaml` |
| Point-in-time store and vintage logic | `src/finorchestra/data/` |
| Signals, regime, retrieval, text scoring | `src/finorchestra/signals/` |
| Both agents, view schema, masking | `src/finorchestra/views/` |
| Black-Litterman, constraints, critic, optimizer, feedback engine | `src/finorchestra/allocation/` |
| Metrics, baselines, certificate | `src/finorchestra/evaluation/` |
| Decision and run reports | `src/finorchestra/explain/`, `outputs/runs/<run_id>/` |
| Orchestration and CLI | `src/finorchestra/pipeline.py`, `src/finorchestra/cli.py` |
| Tests (30 unit, 4 integration) | `tests/` |

Run it: `finorchestra pull`, then `finorchestra run`. Explain a date: `finorchestra decide --date 2024-03-15`. Prove no look-ahead: `finorchestra leakage-check --date 2022-06-17`. Swap the model: `--llm openai_compatible --model ... --base-url ...`.
