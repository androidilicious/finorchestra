"""Typed configuration loaded from YAML.

The pydantic models here are the single source of truth for what a run is. A run id is a hash of the
resolved configuration, so two runs with the same id used the same universe, constraints, and model.
"""

from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Any, Literal

import yaml
from pydantic import BaseModel, Field, model_validator


class RunCfg(BaseModel):
    name: str = "default"
    seed: int = 7
    start: str = "2015-01-02"
    end: str | None = None
    rebalance_weekday: int = 4
    outputs_dir: str = "outputs"


class PathsCfg(BaseModel):
    raw: str = "data/raw"
    processed: str = "data/processed"


class FredSeriesCfg(BaseModel):
    id: str
    name: str
    revised: bool = True
    lag_days: int = 0  # business days after the observation date before an unrevised series is usable


class FredCfg(BaseModel):
    api_key_env: str = "FRED_API_KEY"
    vintage_start: str = "2005-01-07"
    vintage_chunk: int = 12
    series: list[FredSeriesCfg]


AssetKind = Literal["equity", "government_bond", "inflation_linked_bond", "corporate_bond", "gold", "commodity", "currency", "cash"]


class AssetCfg(BaseModel):
    """A fund and its regulatory / structural kind. Durations, risk weights and neutral weights are no longer
    typed in: durations are estimated from the fund's own returns, risk weights come from the US standardised
    capital rule by kind, and the neutral portfolio is computed from the covariance at each decision date."""

    ticker: str
    label: str
    kind: AssetKind


class MarketCfg(BaseModel):
    start: str = "2007-01-01"
    universe: list[AssetCfg]
    risk_free_ticker: str = "BIL"
    yield_series: str = "yield_10y"  # derived-series name of the Treasury yield used to estimate durations

    @property
    def tickers(self) -> list[str]:
        return [a.ticker for a in self.universe]

    @property
    def kinds(self) -> dict[str, str]:
        return {a.ticker: a.kind for a in self.universe}


class TextIndicesCfg(BaseModel):
    epu_daily_series: str = "USEPUINDXD"
    epu_lag_days: int = 2
    gpr_daily_file: str = "data/raw/gpr/data_gpr_daily_recent.xls"
    gpr_lag_days: int = 2


class FomcCfg(BaseModel):
    years: tuple[int, int] = (2007, 2026)
    lag_days: int = 0


class DerivedCfg(BaseModel):
    source: str
    transform: Literal["level", "diff", "pct_change", "pct_change_annualized"] = "level"
    periods: int = 1


class ThemeCfg(BaseModel):
    series: list[str]
    signs: list[int]

    @model_validator(mode="after")
    def _same_length(self) -> ThemeCfg:
        if len(self.series) != len(self.signs):
            raise ValueError("theme series and signs must have the same length")
        return self


class SignalsCfg(BaseModel):
    zscore_window_years: int = 10
    min_history_years: int = 5
    clip: float = 3.0
    derived: dict[str, DerivedCfg]
    themes: dict[str, ThemeCfg]


class TextSignalCfg(BaseModel):
    provider: Literal["same_as_llm", "lexicon"] = "same_as_llm"
    novelty_ngram: tuple[int, int] = (1, 2)


class RetrievalCfg(BaseModel):
    top_k: int = 3
    max_chars_per_doc: int = 1800
    recency_halflife_days: int = 120


class IncrementalTestCfg(BaseModel):
    horizons_weeks: list[int] = Field(default_factory=lambda: [4, 13])
    targets: list[str] = Field(default_factory=lambda: ["SPY", "TLT", "HYG"])


class LLMCfg(BaseModel):
    provider: Literal["mock", "openai_compatible"] = "mock"
    base_url: str = "http://localhost:11434/v1"
    api_key_env: str = "FINORCHESTRA_LLM_API_KEY"
    model: str = "qwen2.5:3b"
    temperature: float = 0.0
    timeout_s: int = 120
    max_retries: int = 2
    knowledge_cutoff: str = "2024-10-01"
    masking: bool = True


class FittedAgentCfg(BaseModel):
    """The formula strategy is a fitted, past-only ridge regression of forward excess returns on the signal
    features, refit at every decision date. Nothing in it is hand-set except the horizon, the feature list and the
    regularisation grid the cross-validation searches over."""

    horizon_weeks: int = 4
    features: list[str] = Field(default_factory=lambda: ["theme_growth", "theme_inflation", "theme_policy", "theme_financial", "fed_stance", "fed_stance_change", "fed_novelty"])
    ridge_alphas: list[float] = Field(default_factory=lambda: [0.1, 1.0, 10.0, 100.0, 1000.0])
    min_train_weeks: int = 156
    max_views: int = 6


class MandateCfg(BaseModel):
    """The bank's rules, expressed relative to the data-derived neutral portfolio. These four numbers are the
    only mandate parameters; they are placeholders until the client supplies its own policy limits."""

    long_only: bool = True
    fully_invested: bool = True
    active_weight_band: float = 0.15  # |w_i - benchmark_i| <= band, every fund including cash
    volatility_allowance: float = 0.25  # portfolio vol <= benchmark vol x (1 + allowance)
    duration_band_years: float = 2.0  # |duration - benchmark duration| <= band
    capital_allowance: float = 0.25  # regulatory RWA <= benchmark RWA x (1 + allowance)
    max_one_way_turnover: float = 0.25


class AllocationCfg(BaseModel):
    cov_window_weeks: int = 104
    risk_aversion: float = 3.0
    turnover_penalty: float = 0.002
    feedback_rounds: int = 2
    benchmark: Literal["inverse_vol", "equal_weight"] = "inverse_vol"
    mandate: MandateCfg


class FactorCfg(BaseModel):
    long: str
    short: str


class EvaluationCfg(BaseModel):
    cost_bps_grid: list[int] = Field(default_factory=lambda: [0, 5, 10, 20, 30])
    strategies: list[str] = Field(default_factory=lambda: ["rule", "llm_clip", "llm_feedback"])
    baselines: list[str] = Field(default_factory=lambda: ["benchmark", "sixty_forty"])
    bootstrap_blocks_weeks: int = 8
    bootstrap_draws: int = 2000
    attribution_factors: dict[str, FactorCfg]


class Config(BaseModel):
    run: RunCfg
    paths: PathsCfg
    fred: FredCfg
    market: MarketCfg
    text_indices: TextIndicesCfg
    fomc: FomcCfg
    signals: SignalsCfg
    text_signal: TextSignalCfg
    retrieval: RetrievalCfg
    incremental_test: IncrementalTestCfg
    llm: LLMCfg
    fitted_agent: FittedAgentCfg = Field(default_factory=FittedAgentCfg)
    allocation: AllocationCfg
    evaluation: EvaluationCfg

    # populated at load time
    root: Path = Field(default=Path("."), exclude=True)

    @property
    def raw_dir(self) -> Path:
        return self.root / self.paths.raw

    @property
    def processed_dir(self) -> Path:
        return self.root / self.paths.processed

    @property
    def outputs_dir(self) -> Path:
        return self.root / self.run.outputs_dir

    def run_id(self) -> str:
        payload = json.dumps(self.model_dump(mode="json", exclude={"root"}), sort_keys=True)
        return f"{self.run.name}-{hashlib.sha1(payload.encode()).hexdigest()[:8]}"


def _deep_update(base: dict[str, Any], override: dict[str, Any]) -> dict[str, Any]:
    out = dict(base)
    for k, v in override.items():
        if isinstance(v, dict) and isinstance(out.get(k), dict):
            out[k] = _deep_update(out[k], v)
        else:
            out[k] = v
    return out


def load_dotenv(path: str | Path = ".env") -> int:
    """Load KEY=VALUE lines from a .env file into os.environ (existing variables win). Returns the count loaded."""
    import os

    p = Path(path)
    if not p.exists():
        return 0
    n = 0
    for raw in p.read_text(encoding="utf-8").splitlines():
        line = raw.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        k, v = line.split("=", 1)
        k, v = k.strip(), v.strip().strip('"').strip("'")
        if k and v and k not in os.environ:
            os.environ[k] = v
            n += 1
    return n


def load_config(path: str | Path = "configs/default.yaml", overrides: dict[str, Any] | None = None) -> Config:
    """Load YAML config, apply dotted-key overrides (e.g. {"llm.provider": "openai_compatible"})."""
    load_dotenv()
    path = Path(path)
    with open(path, encoding="utf-8") as fh:
        data = yaml.safe_load(fh)
    if overrides:
        nested: dict[str, Any] = {}
        for dotted, value in overrides.items():
            cur = nested
            parts = dotted.split(".")
            for p in parts[:-1]:
                cur = cur.setdefault(p, {})
            cur[parts[-1]] = value
        data = _deep_update(data, nested)
    cfg = Config.model_validate(data)
    cfg.root = path.resolve().parent.parent if path.parent.name == "configs" else Path.cwd()
    return cfg
