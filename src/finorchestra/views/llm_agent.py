"""The LLM macro agent: same signals as the rule agent, plus retrieved Fed text, reasoning in language.

Both the first pass and the constraint-feedback revision live here. Prompts carry machine-readable blocks
(<<ASSETS>>, <<SIGNALS>>, <<DOCUMENTS>>, <<VIOLATIONS>>) so that the offline mock and a real model receive
byte-identical inputs.
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field

from ..config import Config
from ..llm.client import LLMClient
from ..signals.regime import RegimeEstimate
from ..signals.retrieval import DatedIndex
from ..signals.text_signal import TextSignal
from ..signals.zscores import SignalSet
from ..utils import LOG
from .masking import Masker
from .schema import ViewSet

_SYSTEM = """You are a macro strategist at an institutional asset manager. You form forward-looking views on broad
asset classes from macroeconomic signals and central-bank communication, at a weekly decision cadence.

Rules:
- Use ONLY the information provided. Do not rely on memory of specific historical episodes.
- Express each view as an expected excess return over cash per year (e.g. 0.03 = +3%/yr) with a confidence in [0,1].
- Cite evidence from the signals table or the documents for every view.
- Reply with ONLY a JSON object of the form:
{"regime_assessment": "<one sentence>",
 "views": [{"asset": "<asset code>", "direction": "overweight|underweight|neutral",
            "expected_excess_return_annual": <float>, "confidence": <float 0-1>, "evidence": ["<short>", ...]}],
 "rationale": "<two or three sentences>"}
Provide between 2 and 6 views."""


@dataclass
class AgentTrace:
    prompt_chars: int = 0
    rounds: int = 0
    fallbacks: int = 0
    documents_used: list[str] = field(default_factory=list)
    raw_views: list[dict] = field(default_factory=list)


class LLMAgent:
    def __init__(self, cfg: Config, client: LLMClient, masker: Masker):
        self.cfg = cfg
        self.client = client
        self.masker = masker

    # ------------------------------------------------------------------ prompt pieces
    def _signals_block(self, signals: SignalSet, regime: RegimeEstimate, text: TextSignal) -> dict:
        return {
            "themes": {k: round(v, 3) for k, v in signals.themes.items()},
            "macro_z": {k: round(v, 3) for k, v in signals.z.items()},
            "text_index_z": {k: round(v, 3) for k, v in signals.text_index_z.items()},
            "regime_probabilities": regime.probabilities,
            "fed_stance": round(text.stance, 3),
            "fed_stance_change": round(text.stance_change, 3),
            "fed_statement_novelty": round(text.novelty, 3),
            "weeks_since_fed_statement": None if text.days_since is None else round(text.days_since / 7, 1),
        }

    def _documents_block(self, index: DatedIndex, query: str) -> tuple[str, list[str]]:
        hits = index.search(query)
        parts, used = [], []
        for i, h in enumerate(hits, 1):
            parts.append(f"Document {i} (released t-{max(0, h.age_days // 7)} weeks):\n{self.masker.mask_text(h.text)}")
            used.append(str(h.date))
        return "\n\n".join(parts), used

    def build_messages(self, signals: SignalSet, regime: RegimeEstimate, text: TextSignal, index: DatedIndex) -> tuple[list[dict], list[str]]:
        sig = self._signals_block(signals, regime, text)
        query = "inflation growth employment policy rate outlook risks " + " ".join(text.key_phrases[:3])
        docs, used = self._documents_block(index, query)
        user = (
            "Decision date: t (the current week). All z-scores are standardized against a trailing 10-year window.\n\n"
            "<<ASSETS>>\n" + self.masker.asset_table() + "\n<<END_ASSETS>>\n\n"
            "<<SIGNALS>>\n" + json.dumps(sig, indent=1) + "\n<<END_SIGNALS>>\n\n"
            "Signal guide: themes >0 mean above-normal (growth strong, inflation high, policy tight, financial stress high). "
            "fed_stance >0 is hawkish. text_index_z are newspaper-based policy-uncertainty (epu) and geopolitical-risk (gpr) indices.\n\n"
            "<<DOCUMENTS>>\n" + docs + "\n<<END_DOCUMENTS>>\n\n"
            "Form your views now."
        )
        return [{"role": "system", "content": _SYSTEM}, {"role": "user", "content": user}], used

    # ------------------------------------------------------------------ calls
    def propose(self, signals: SignalSet, regime: RegimeEstimate, text: TextSignal, index: DatedIndex) -> tuple[ViewSet, list[dict], AgentTrace]:
        msgs, used = self.build_messages(signals, regime, text, index)
        trace = AgentTrace(prompt_chars=sum(len(m["content"]) for m in msgs), rounds=1, documents_used=used)
        vs = self._call(msgs, trace)
        trace.raw_views.append(vs.model_dump())
        return self._unmask(vs), msgs, trace

    def revise(self, msgs: list[dict], previous: ViewSet, violations: list[str], trace: AgentTrace) -> tuple[ViewSet, list[dict]]:
        prev_json = json.dumps(self._mask_viewset(previous).model_dump())
        masked_violations = [self.masker.mask_text(v) for v in violations]
        feedback = (
            "<<VIOLATIONS>>\n" + "\n".join(f"- {v}" for v in masked_violations) + "\n<<END_VIOLATIONS>>\n\n"
            "The portfolio implied by your views breaks the institutional constraints listed above. Revise your views so "
            "that a portfolio consistent with them is feasible: reduce or reallocate the offending exposures (for example, "
            "spread a duration view across maturities, or lower confidence). Keep the same JSON schema."
        )
        new_msgs = msgs + [{"role": "assistant", "content": prev_json}, {"role": "user", "content": feedback}]
        trace.rounds += 1
        vs = self._call(new_msgs, trace)
        trace.raw_views.append(vs.model_dump())
        return self._unmask(vs), new_msgs

    def _call(self, msgs: list[dict], trace: AgentTrace) -> ViewSet:
        try:
            return self.client.chat_json(msgs, ViewSet, task="views").normalized()
        except Exception as e:  # noqa: BLE001
            LOG.warning("LLM view generation failed (%s); using deterministic fallback", str(e)[:120])
            trace.fallbacks += 1
            return self.client.mock_fallback(msgs, ViewSet, task="views").normalized()

    # ------------------------------------------------------------------ masking helpers
    def _unmask(self, vs: ViewSet) -> ViewSet:
        tickers = set(self.cfg.market.tickers)
        views = []
        for v in vs.views:
            t = self.masker.ticker(v.asset)
            if t in tickers:
                views.append(v.model_copy(update={"asset": t}))
        if not views:
            views = [vs.views[0].model_copy(update={"asset": self.cfg.market.risk_free_ticker, "direction": "neutral", "expected_excess_return_annual": 0.0})]
        return vs.model_copy(update={"views": views})

    def _mask_viewset(self, vs: ViewSet) -> ViewSet:
        return vs.model_copy(update={"views": [v.model_copy(update={"asset": self.masker.code(v.asset)}) for v in vs.views]})
