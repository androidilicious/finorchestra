# Scope note: reusing the previous team's Fed work, and where reinforcement learning fits

> **Version-1 analysis.** The measurements in this note were made on the version-1 reference runs (`openai-postcutoff-aefba080`, `mock-full-b811156c`) before revision 2 (2026-09-07). The surprise term and the `text_stance` loading described below no longer exist in the code, and the headline the note refers to (feedback beating clipping by 0.78 Sharpe, p = 0.03) became +0.27 at p = 0.41 under the data-based mandate (current run `openai-postcutoff-v3-3baad69b`). The conclusions about what is and is not learnable at this sample size are unchanged by that; the numbers should be re-measured on the v3 runs before being quoted.


Written 2026-09-07 for Team 4. Every number here was produced by a script run against the current repository,
the two reference runs (`outputs/runs/openai-postcutoff-aefba080`, 114 weeks with gpt-4.1-mini after its
training cutoff; `outputs/runs/mock-full-b811156c`, 610 weeks with the deterministic stand-in), and the previous
team's repository (`adlerviton/BNY_Crew_FOMC_Simulator`, "Fedsight AI"). Scripts and their outputs live under
`outputs/verify_scratch/rl_scope/`. Nothing in the pipeline was changed to produce this note.

## Verdict in six lines

1. **Reuse the previous team's Fed *data plumbing*, not their predictor.** The Beige Book scraper, the FOMC
   outcome table, and their variable list are worth porting. The persona simulation is not: its inputs contained
   the answer, and its headline accuracy cannot be recomputed from anything in the repository.
2. **Beige Books go in as a second dated corpus.** 239 issues exist since 1996, eight a year, each released at
   2 pm on a Wednesday about two weeks before the FOMC meeting. That publication date is the availability date.
   About 2.5 engineer-days.
3. **Replace the text-only Fed surprise with a market-implied one.** Add four public FRED series by config, then
   define surprise as realised target change minus the market-implied change the day before. About 3 days.
4. **Reinforcement learning to decide *when* to run the feedback loop is not learnable yet.** With 113 real
   weeks the learned policy picks the better arm 48% of the time and shuffled labels do as well 72% of the time.
   "Always run the loop" stays the policy. Revisit with several hundred real-model weeks and a replay
   harness that prices switching costs.
5. **Reinforcement learning to fine-tune the proposer is feasible only with a shaped constraint reward and a
   GPU, and only as a stretch.** The model's view directions are a coin flip on this sample, so any
   return-based reward would train on noise.
6. **An end-to-end RL allocator stays out.** Too few decisions, non-stationary data, and it discards the
   explainability and constraint certification that make the project defensible.

One finding cuts across both parts. The feedback loop's Sharpe advantage over silent clipping (0.79 against
0.01) did **not** come from the model calling direction correctly. It coincides with the loop pushing the model
toward neutral views: 25.6% of first-pass views were neutral, 44.7% of final views were. Neutral views pull the
book toward market weights, which had Sharpe 0.93 in this period. That is a hypothesis about mechanism, and it
is testable without any reinforcement learning (section 3.5).

---

## Part A. What to take from Fedsight AI

### 1. Inventory verdicts

| Asset in their repo | Count / coverage | Verdict | What to do |
|---|---|---|---|
| Beige Book PDFs (`*/knowledge/*beige book.pdf`) | 31 distinct issues across 32 meeting months, 2017-07 to 2025-04, with gaps; the June 2022 meeting was fed the March 2022 book | Reuse with work | Do not copy the files. Port their scraper and re-download all 239 issues from the Fed's year index pages. Key each by release date. |
| `helper_prepare_knowledge.py` `download_latest_beige_book` | Working scraper of the Fed archive | Port | Half a day. Resolves release dates from the year index and fetches `BeigeBook_{YYYYMMDD}.pdf`. `pypdf` is already in our venv. |
| `state_of_art_model/fomc_meetings.csv` | 255 meetings 1994-02 to 2025-03, HIKE / CUT / NO CHANGE | Reuse with work | Label table for a policy-surprise test, never an input. Five labels are wrong (1994-09-27, 1995-11-15, 1995-12-19, 1997-03-25, 1998-09-29) and intermeeting moves are incomplete. |
| "Historical macro" CSV outcome columns | 212 change rows 1990-07 to 2025-03 | Reuse with work | All 212 post-meeting target levels match the Fed's own target-change tables. Ends 2025-03-19, so the three 2025 cuts are missing. Extend from FRED `DFEDTARU` / `DFEDTARL`. Our cleaned copy: `outputs/verify_scratch/rl_scope/outcomes/fomc_outcomes.csv`. |
| `base_simulation/knowledge/fedwatch.csv` | 71 meetings 2016-07 to 2025-03, hike and cut odds two days before each meeting | Reuse privately | CME proprietary. Never commit it to a public repo. Use only as an evaluation yardstick for our surprise measure, not as a feature. Public proxy below. |
| Michigan Surveys `.xls` (three tables) | Monthly to 2025-02 | Reuse with work | Candidate expectation features. Re-download, fix a swapped column label, apply an end-of-month availability lag. |
| `etl.ipynb` VARIABLES dict | 27 predictors (Yoon and Fan set) | Reuse the list | Checklist of ALFRED series to add by config: CPILFESL, PPIACO, MANEMP, ICSA, IC4WSA, RRSFS, M2SL, TB6SMFFM, Treasury spreads. |
| "Current macro" one-pagers | 31 files | Discard | Team-generated. Embed CME odds and the meeting month's own data, which was published after the meeting. |
| "Dot plot description" PDFs | 88 files | Discard | Hand-typed from the Summary of Economic Projections. Use the official SEP tables instead, dated by release. |
| "Historical macro" feature columns | 88 truncated copies of one table | Discard | Systematic look-ahead: the stored value is the meeting month's own print for UNRATE in 53 of 66 meetings, CPI in 61 of 66, PCE in 62 of 66. Our ALFRED store supersedes it. |
| `predictor_df.csv`, `pmi_quarterly.csv` | Quarterly, current vintage | Discard | Latest-revision values; the PMI came from a Refinitiv terminal and cannot be redistributed under the public-data rule. |
| CrewAI persona simulation, memory databases, demo app | | Discard as a predictor | See below. |

### 2. Why the persona simulation is not reused as a predictor

These are quotes and counts from their code and logs, not opinions.

- The economist and voter agents were told to "pay particular attention to the implied rate hike probabilities"
  and to "never give options that have a 0 percent implied probability" (`crew.py` lines 111 to 139). CME
  FedWatch odds from two days before each decision sat in every prompt. The option set was bounded by the answer.
- The macro sheets fed to the agents carried the meeting month's own data, published after the decision
  (same-month values for 53 to 62 of 66 meetings depending on the series).
- The headline "93.75% prediction accuracy" is 15 of 16 meetings, but no script aggregates across meetings.
  `Automated_metrics.py` scores one hard-coded meeting at a time, and the per-run result files are excluded by
  `.gitignore`. The number cannot be recomputed from the repository.
- The models were gpt-4o and gpt-4o-mini, whose training data extends past the 2023 to 2024 test meetings.
  There is no cutoff declaration, masking, or contamination check.
- The "62.5%" ordinal-forest baseline they beat merges each meeting to its calendar quarter's end-of-quarter
  features, so it also sees the future.
- The "reasoning similarity" metric is cosine similarity between a generated statement written "in the same
  tone, structure, and formality as official FOMC post-meeting statements" and the real one. Runs with 0%
  correct votes scored 0.62 to 0.66.

What survives as an idea: a pre-meeting view of the policy path is legitimate if it is built point-in-time. In
our system that is not a committee of personas but one more input to the views: the market-implied path (below)
and, optionally, the model's own hike / hold / cut probability produced from the Beige Book and statement text
with the same masking and cutoff discipline as everything else.

### 3. Integration seams in our code

| Addition | Where it plugs in | Availability rule | Effort |
|---|---|---|---|
| Beige Book corpus | New `BeigeBookStore` alongside `FomcStore` in `data/fomc.py`; a `BeigeBookCfg` in `config.py`; `Snapshot` in `data/pit.py` gains a second frame; `DatedIndex` in `signals/retrieval.py` indexes both with a `doc_type` column; the certificate in `evaluation/leakage.py` gains an input line | `available_from` = release date (Wednesday 2 pm ET, so usable at that week's Friday decision). Never key by the meeting month or by the "information collected on or before" sentence. Resolve release dates from the Fed's year index pages and fetch the PDF by date; the HTML issue URLs changed pattern in 2024 and are not month-keyed. | 2.5 days |
| Market-implied path | Config only: add `DGS1MO`, `DGS3MO`, `DFEDTARU`, `DFEDTARL` to `fred.series` with `lag_days: 1`, plus derived entries in `signals.derived`; verified live on FRED 2026-09-07 | Same as `DFF`: H.15 posts the next business day | 1 day |
| Kuttner-style surprise | `signals/text_signal.py` `build_text_signal` currently sets surprise = stance × (0.5 + novelty). Add `policy_surprise_bp` = realised change in the target midpoint on decision day minus the market-implied change on the day before, from the proxy above. Consumers: rule agent loading `text_stance`, the LLM signals block, `signals/incremental.py`, the dashboard. Today the text surprise reaches only the formula agent and the panel, not the model's prompt. Report the new column next to the existing one in the incremental test, whose in-sample t of 3.5 on 4-week equity returns (n = 110, overlapping windows) is the bar to beat | FRED dates post-2015 target changes on the effective day, D + 1, so the realised leg is read at D + 1 and, with the one-day lag, `available_from` = D + 2 business days. Wednesday meetings are still in time for that week's Friday decision. | 2 days |

Two cautions on the Beige Book. First, prompt budget: retrieval is capped at two documents of 1,400 characters
because the local 3B model has a 4k context. A Beige Book national summary is about 8,700 characters, so it goes
in as a third capped document, not at full length. Second, contamination: Beige Book text is dense with dated,
place-specific detail. Our masking covers dates, percentages and tickers, not place names, so the knowledge-cutoff
rule matters more for this corpus than for statements.

One caution on the surprise. The T-bill-minus-funds-rate proxy is crude: it carries term premium and bill-supply
noise, and it is uninformative at the zero lower bound (2009 to 2015). It is still a better expectation than
none, which is what the text-only surprise uses today.

---

## Part B. Reinforcement learning in Finorchestra

### 1. What reinforcement learning needs, and what we have

An RL problem needs a state the agent observes, an action it chooses, a reward it receives, and enough repetitions
to tell a good policy from a lucky one. Our decisions are weekly. The ten-year mock run gives 610 of them with a
proposer that has no intelligence; the real-model run gives 114. That is the binding constraint on everything
below.

We do have one unusual asset. Because the clipped and feedback strategies share the same first proposal every
week, both arms of the "clip or feed back" decision are logged with their realised returns. That makes an offline
test of a gating policy possible from existing files, with no new model calls.

### 2. Option 1: learn when to run the feedback loop

**Framing.** A contextual bandit. State: regime probabilities, theme z-scores, Fed stance and novelty, policy and
geopolitical news indices, and which rules bind on the first proposal (all known before the choice). Action: clip,
or run the feedback loop. Reward: the arm's next-week excess return.

**Measured, post-cutoff run, 113 weeks with realised returns.**

| Policy | Sharpe |
|---|---|
| Always clip | 0.01 |
| Always feedback (what the system does) | 0.79 |
| Random arm each week, mean of 1,000 draws | 0.41 |
| Perfect week-by-week choice (uses the future; upper bound) | 1.90 |

The arms differ on 108 of 113 weeks, by 28 basis points on average. Feedback won 64 weeks, clip 44, a mean
edge of 7.6 basis points a week with t = 2.2.

A logistic policy on the state features, refit every week on an expanding window with a 40-week minimum and
scored on the last 73 weeks:

| Same 73 test weeks | Sharpe |
|---|---|
| Learned policy | 1.17 |
| Always feedback | 1.59 |
| Always clip | 0.62 |
| Perfect choice | 3.10 |
| Shuffled-label placebo, median (95th percentile) | 1.33 (1.81) |

The learned policy chose the better arm on 47.9% of test weeks. 72% of placebo policies trained on shuffled labels
matched or beat it. On the 609-week mock run the same design gives 51% accuracy and 97% of placebos beat it. The placebo band on the 73-week window is wide enough that even "always feedback" sits inside it, so this window supports neither a learned policy nor the feedback loop's superiority; the 0.78 headline rests on the full 113 weeks and its paired bootstrap.

**Verdict.** There is a large prize (0.79 to 1.90) but no signal in these features at this sample size. Keep
"always run the loop." Three things would change the answer: several hundred real-model weeks; richer state, such
as the size of the cap breach and how far the revised views moved; and a replay harness that re-simulates a switching policy on its own holdings path with transaction costs, because a policy that switches arms inherits neither arm's turnover (the feedback arm's own edge falls from 0.79 to 0.57 at 10 basis points of cost). The clip-or-feedback choice is full-information, since both arms are logged every week; only policies with unlogged arms, such as stopping after one round, would need a randomised exploration share and off-policy estimators (Li et al. 2011; Dudík et al. 2011).

**One lead to watch, not to act on.** Weeks where the revision fully cleared the rules earned about 23 basis
points the next week against roughly zero when it did not (t = 1.6, 35 against 69 weeks). The mock run does not
reproduce the pattern consistently, so treat it as noise until the real-model sample is much larger.

**Prerequisite either way (1 day).** The engine records only the messages and rule names per round. Add per-round
weights, binding values, posterior and constraint summary, and write the masked prompt transcript and raw model
JSON to a sidecar file. Without this, "stop after one round" cannot be priced, and no preference or policy data
exists to train on.

### 3. Option 2: fine-tune the proposer with a verifiable reward

**Framing.** Reinforcement learning with verifiable rewards (Lambert et al. 2024), GRPO-style (Shao et al. 2024):
sample several view sets per weekly prompt, score each with a deterministic grader, and update a small local model
toward higher-scoring samples. Our critic is already a deterministic grader. The seam is a config change for
inference plus a stand-alone `grade_views(views, sigma, w_prev)` function extracted from the engine's `solve`
closure (about 1.5 days).

**Reward candidates, measured on existing logs.**

| Reward | What we measured | Verdict |
|---|---|---|
| Valid JSON on first attempt | 5 failures in 330 calls (1.5%), all "evidence list over 6 items" | Hard gate only. No variance to learn from. |
| No rule binds on the first proposal | 9 of 114 weeks (1 of 114 under the clipped strategy's turnover state); rounds needed 0 / 1 / 2 = 9 / 15 / 90; 70 weeks still binding after two rounds | Best dense shaping term as minus the number of binding rules. Hackable: an all-neutral view set reproduces market weights and binds nothing. The loop already drifted that way (25.6% to 44.7% neutral), and the few implementable weeks had the worst direction hit rate (30%, n = 27). |
| Rounds needed | Censored at the cap for 79% of weeks; triples generation cost | Skip. |
| View direction correct at 4 weeks | First-pass 47.7% (n = 415), final 45.9% (n = 362); the no-intelligence mock scores 49 to 50%; confidence terciles not monotone; underweight views 44%, overweight 50% | Aligned with the objective but there is no measured skill to amplify, and a naive version teaches "always overweight risk assets" from this sample. |
| Realised portfolio return | Weekly excess mean 0.08%, standard deviation 0.71% (signal-to-noise about 0.1) | Too noisy at this sample size. |

**Budget.** For scale: the whole 114-week real-model run used 618,700 prompt and 206,530 completion tokens
over 330 calls, about 58 US cents at gpt-4.1-mini list prices ($0.40 and $1.60 per million tokens, checked
2026-09-07). Sampling one training epoch, 114 prompts × 8 samples = 912 graded generations, would cost about
$1.60 at those prices if a hosted model of that class generated them, but a hosted model cannot be updated by us. At the measured local latency
(51 seconds a call for the 3B model) that is about 13 hours of generation per epoch, 39 hours if each sample also
runs the two-round critic loop, before any training pass. Training needs a GPU. Hosted reinforcement fine-tuning
with a custom grader exists but is limited to one closed reasoning model family, which would break the local,
swappable-model design.

**Verdict.** Feasible only as a stretch experiment: "teach a small model to propose implementable views." Reward
= minus binding rules, minus a penalty on the neutral share relative to the first proposal, with schema validity
as a gate. Split by date, walk-forward, and register the fine-tuned model as a declared trial in the deflated
Sharpe. Do not use returns in the reward.

### 4. Option 3: end-to-end RL allocator

No. The canonical results (Moody and Saffell 2001; Jiang, Xu and Liang 2017) train on thousands to millions of
steps; the FinRL group's own later paper warns that reported gains "may suffer from the false positive issue due
to overfitting" (Gort et al. 2022); Bailey et al. (2014) show the backtest length needed grows with the number of
variants tried. Six hundred weekly decisions across one macro history cannot support a policy that outputs weights,
and it would discard the view, evidence and constraint audit trail the client asked for.

### 5. The test to run before any of this

The feedback arm beat silent clipping by 0.78 Sharpe (bootstrap p = 0.03) while its views were no better than a
coin flip on direction. The most economical explanation is regularisation: being told a cap binds, the model
retreats to neutral, the book moves toward market weights, and market weights happened to be the best thing to
own in this period. Test it with two control arms that need no model call: a neutral-only view set, which is the market portfolio (Sharpe 0.93, deflated 0.91, against 0.79 and 0.69 for the feedback arm), and a baseline that takes the first-pass views and shrinks them toward neutral to match the feedback arm's neutral share. If that baseline reproduces most of the
0.78, the new idea is a good regulariser rather than a source of better views, and the write-up should say so.
If it does not, the revision is doing something the shrinkage does not, and that is worth understanding before
adding learning on top. About one day.

### 6. Rules that apply to every learning variant

- Rewards may use only information available at the decision date, or realised returns from weeks strictly
  before it. Train walk-forward, evaluate on later weeks that never re-enter training.
- Every trained variant is a trial. Raise `evaluation.trials_declared` and say so in the certificate. Going from three declared variants to six lifts the deflated-Sharpe hurdle from 0.43 to 0.65 annualised.
- Nothing here changes the constraint enforcement. The optimiser and critic remain deterministic and final.

---

## Recommended order

| # | Item | Effort | Why first |
|---|---|---|---|
| 1 | Per-round logging and prompt sidecar | 1.5 d | Prerequisite for any learning; any config change forces a re-run anyway |
| 2 | Control arms: a neutral-only view set (equals market weights) and the neutral-shrinkage baseline | 1 d | Settles what the current headline result means and sets the bar any learned arm must clear net of costs |
| 3 | Adopt the verified outcome table; test whether stance × novelty predicts the policy surprise on the 75 statements in the FedWatch span (FedWatch kept private) | 1 d | Answers whether the Fed-text theme carries policy information before more Fed text is added |
| 4 | Market-implied path from four daily FRED series; validate its sign against the 71 FedWatch snapshots | 1 d | The only public replacement for FedWatch; prerequisite for item 6 |
| 5 | Beige Book corpus | 2.5 d | Highest-value reuse; changes the run id and prompt budget, so it follows the logging re-run |
| 6 | Kuttner-style surprise as an added column next to the existing text surprise in the incremental test | 2 d | Meaningless without the comparison bar from items 3 and 4 |
| 7 | Deflated-Sharpe hygiene: declared trials at least the number of strategies, empirical dispersion path | 0.5 d | Every bandit prior, rounds grid and fine-tune checkpoint is a trial |
| 8 | Fine-tuning pilot with the shaped constraint reward, local model | 1 to 2 wk, GPU | Stretch; only after items 1 to 7 |
| 9 | Gating-policy bandit over clip / one round / two rounds | revisit | Pre-register as a likely negative until the real-model sample is several times larger |
| 10 | Lower-priority comparators: FOMC minutes as a third corpus, official SEP tables, Michigan indices, a leak-free ordinal-forest yardstick | as time allows | Context; none of them blocks the answer on reinforcement learning |

## Provenance and caveats

- Bandit and reward measurements: `outputs/verify_scratch/rl_scope/offline-bandit/offline_bandit.py` and
  `reward-signals/reward_signals.py`, each with a `results.json`. Return alignment was verified by recomputing
  the logged weekly returns from weights and prices to 1e-16.
- Inventory and look-ahead tests: `outputs/verify_scratch/rl_scope/fedsight_inventory/`.
- Outcome table and Beige Book inventory: `outputs/verify_scratch/rl_scope/outcomes/`. FRED was unreachable from
  this machine during the cross-check, so the 212 target levels were verified against the Fed's own target-change
  tables (`federalreserve.gov/monetarypolicy/openmarket.htm`), which are FRED's source. Re-run against
  `DFEDTARU` / `DFEDTARL` before adopting the table.
- Hit rates use an exact binomial test that is anti-conservative because views within a week share one macro
  state; a four-week block bootstrap gives a standard error of about 3 points on the 4-week hit rate. No hit rate
  in either run is distinguishable from 50% after that correction.
- Effort figures are engineering estimates, not measurements. The fine-tuning hours rest on 42 local calls from a smoke run on unrecorded hardware and exclude training passes.
- BNY declined to share iFlow custody-flow data (2026-09-07), so no BNY-internal source appears in this plan.

## References (all verified against the publisher or arXiv record)

- Moody, J., Saffell, M. (2001). Learning to trade via direct reinforcement. *IEEE Trans. Neural Networks* 12(4).
- Jiang, Z., Xu, D., Liang, J. (2017). A deep reinforcement learning framework for the financial portfolio management problem. arXiv:1706.10059.
- Liu, X.-Y. et al. (2020). FinRL. arXiv:2011.09607. Gort, B. et al. (2022). Deep RL for cryptocurrency trading: practical approach to address backtest overfitting. arXiv:2209.05559.
- Bailey, D., Borwein, J., López de Prado, M., Zhu, Q. (2014). Pseudo-mathematics and financial charlatanism. *Notices of the AMS*. Bailey, D., López de Prado, M. (2014). The deflated Sharpe ratio. *J. Portfolio Management*.
- Li, L., Chu, W., Langford, J., Schapire, R. (2010). A contextual-bandit approach to personalized news article recommendation. *WWW*. Li, L. et al. (2011). Unbiased offline evaluation of contextual-bandit-based news article recommendation algorithms. *WSDM*.
- Dudík, M., Langford, J., Li, L. (2011). Doubly robust policy evaluation and learning. *ICML*. Swaminathan, A., Joachims, T. (2015). Counterfactual risk minimization. *ICML*.
- Shao, Z. et al. (2024). DeepSeekMath. arXiv:2402.03300. DeepSeek-AI (2025). DeepSeek-R1. arXiv:2501.12948. Lambert, N. et al. (2024). Tülu 3. arXiv:2411.15124. OpenAI (2025). Reinforcement fine-tuning, API guide.
- Lee, Y. et al. (2025). LLM-enhanced Black-Litterman portfolio optimization. arXiv:2504.14345. Yu, Y. et al. (2024). FinCon. arXiv:2407.06567.
- Kuttner, K. (2001). Monetary policy surprises and interest rates. *J. Monetary Economics* 47(3). Gürkaynak, R., Sack, B., Swanson, E. (2005). Do actions speak louder than words? *Int. J. Central Banking*.
- Armesto, M. et al. (2009). Measuring the information content of the Beige Book. *J. Money, Credit and Banking*. Hansen, S., McMahon, M., Prat, A. (2018). Transparency and deliberation within the FOMC. *QJE*.
