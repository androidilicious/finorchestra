from __future__ import annotations

import json

import pandas as pd

from finorchestra.llm.client import LLMClient
from finorchestra.llm.mock import MockLLM
from finorchestra.signals.regime import estimate_regime
from finorchestra.signals.retrieval import DatedIndex
from finorchestra.signals.text_signal import TextSignal
from finorchestra.signals.zscores import SignalSet
from finorchestra.views.fitted_agent import fitted_views
from finorchestra.views.llm_agent import LLMAgent
from finorchestra.views.masking import Masker
from finorchestra.views.schema import ViewSet


def _signals():
    return SignalSet(
        as_of="2024-03-15",
        raw_latest={},
        z={"growth_indpro_yoy": -1.1, "infl_cpi_yoy": -0.6},
        themes={"growth": -1.1, "inflation": -0.6, "policy": 1.4, "financial": 0.3},
        text_index_z={"epu": 0.4, "gpr": 1.3, "gpr_threat": 1.5, "gpr_act": 0.2},
        text_index_latest={},
    )


def _text():
    return TextSignal(pd.Timestamp("2024-03-13").date(), 2, -0.35, -0.10, -0.25, 0.42, ["inflation has eased"])


def _docs():
    return pd.DataFrame(
        {
            "date": pd.to_datetime(["2024-01-31", "2024-03-13"]),
            "text": ["Inflation has eased over the past year but remains elevated. Job gains remain strong.", "Inflation has eased over the past year but remains elevated. The Committee does not expect it will be appropriate to reduce the target range until it has gained greater confidence."],
            "available_from": pd.to_datetime(["2024-01-31", "2024-03-13"]),
        }
    )


def test_masker_roundtrip(cfg):
    m = Masker.build(cfg.market.universe, enabled=True)
    assert m.code("SPY") == "Asset A" and m.ticker("Asset A") == "SPY"
    assert m.ticker("asset b (long-term government bonds)") == "TLT"
    masked = m.mask_text("On March 20, 2024 the target range was 5-1/4 to 5-1/2 percent; SPY rose in 2023.")
    assert "2024" not in masked and "SPY" not in masked and "[date]" in masked


def test_fitted_agent_learns_a_planted_relationship_from_past_data_only(cfg):
    """Synthetic history where SPY's forward excess return rises with the growth theme: the fitted agent must
    recover a positive SPY view when growth is high, use only rows whose forward window closed, and emit nothing
    when the history is too short."""
    import numpy as np

    rng = np.random.default_rng(1)
    fc = cfg.fitted_agent
    n = fc.min_train_weeks + fc.horizon_weeks + 60
    dates = pd.date_range("2010-01-08", periods=n + 1, freq="W-FRI")
    feats = pd.DataFrame({f: rng.normal(0, 1, n + 1) for f in fc.features}, index=dates)
    ret = pd.DataFrame(rng.normal(0, 0.01, (n + 1, len(cfg.market.tickers))), index=dates, columns=cfg.market.tickers)
    ret["BIL"] = 0.0005
    # plant: each week's SPY return carries 1% x the growth theme observed at each of the previous four decision dates
    for lag in (1, 2, 3, 4):
        ret["SPY"] = ret["SPY"] + 0.01 * feats["theme_growth"].shift(lag).fillna(0.0)
    d = dates[-1]
    history = feats.loc[feats.index < d]
    current = feats.loc[d].to_dict()
    current["theme_growth"] = 2.0
    sig = _signals()
    reg = estimate_regime(sig.themes)
    vs = fitted_views(cfg, history, ret.loc[:d], d, current, reg)
    by = {v.asset: v for v in vs.views}
    assert "SPY" in by and by["SPY"].direction == "overweight" and by["SPY"].expected_excess_return_annual > 0
    assert 0.0 <= by["SPY"].confidence <= 1.0 and any("ridge fit" in e for e in by["SPY"].evidence)
    assert all(v.asset != cfg.market.risk_free_ticker for v in vs.views)
    short = fitted_views(cfg, history.tail(20), ret.loc[:d], d, current, reg)
    assert len(short.views) == 1 and short.views[0].direction == "neutral"


def test_mock_llm_returns_schema_valid_json_and_is_deterministic(cfg):
    client = LLMClient(cfg.llm)  # provider=mock in default config
    agent = LLMAgent(cfg, client, Masker.build(cfg.market.universe, True))
    sig = _signals()
    reg = estimate_regime(sig.themes)
    idx = DatedIndex(_docs(), pd.Timestamp("2024-03-15").date(), cfg.retrieval)
    vs1, msgs, tr = agent.propose(sig, reg, _text(), idx)
    vs2, _, _ = agent.propose(sig, reg, _text(), idx)
    assert vs1.model_dump() == vs2.model_dump()
    assert all(v.asset in cfg.market.tickers for v in vs1.views)
    assert "<<SIGNALS>>" in msgs[1]["content"] and "Asset A" in msgs[1]["content"] and "SPY" not in msgs[1]["content"]
    assert tr.documents_used == ["2024-03-13"] or set(tr.documents_used) <= {"2024-01-31", "2024-03-13"}


def test_mock_revision_reduces_offending_view(cfg):
    client = LLMClient(cfg.llm)
    agent = LLMAgent(cfg, client, Masker.build(cfg.market.universe, True))
    sig = _signals()
    reg = estimate_regime(sig.themes)
    idx = DatedIndex(_docs(), pd.Timestamp("2024-03-15").date(), cfg.retrieval)
    vs, msgs, tr = agent.propose(sig, reg, _text(), idx)
    tlt = next((v for v in vs.views if v.asset == "TLT"), None)
    assert tlt is not None and tlt.expected_excess_return_annual > 0
    revised, _ = agent.revise(msgs, vs, ["TLT (long-term government bonds (20y+)) weight 41.0% exceeds single-asset limit 25%", "portfolio duration 8.9y is above the liability band ceiling 7.0y (too long)"], tr)
    tlt2 = next(v for v in revised.views if v.asset == "TLT")
    assert tlt2.expected_excess_return_annual < tlt.expected_excess_return_annual
    assert tr.rounds == 2


def test_mock_stance_task_uses_statement_block():
    m = MockLLM()
    out = json.loads(m.respond([{"role": "user", "content": "<<STATEMENT>>\nInflation remains elevated. Additional policy firming may be appropriate.\n<<END_STATEMENT>>"}], task="stance"))
    assert out["stance"] > 0


def test_viewset_normalization_fixes_signs():
    vs = ViewSet(views=[{"asset": "SPY", "direction": "underweight", "expected_excess_return_annual": 0.03, "confidence": 0.5}]).normalized()
    assert vs.views[0].expected_excess_return_annual == -0.03
