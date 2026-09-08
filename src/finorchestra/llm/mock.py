"""A deterministic stand-in for a language model.

The mock never sees the network. It parses the same machine-readable blocks a real model receives in the
prompt (asset table, signals JSON, retrieved passages, violations) and applies a transparent playbook. It is
*not* the rule agent: it reasons over regime probabilities, Fed stance, and the newspaper indices with a
different, nonlinear recipe, so the comparison between "rule" and "llm" strategies is meaningful even in
offline mode. It is clearly labelled as a mock in every certificate and report.

On a revision request (a <<VIOLATIONS>> block is present) the mock starts from its own previous answer, the
last assistant message, and edits it in the direction the violations point, so successive rounds compound.
"""

from __future__ import annotations

import json
import re

HAWKISH = [
    "inflation remains elevated", "remains elevated", "further firming", "additional firming", "raise the target",
    "raising the target", "tighten", "tightening", "upside risks to inflation", "restrictive", "vigilant",
    "increase in the target range", "reduce its holdings", "balance sheet runoff", "well anchored but", "persistent",
    "elevated", "strong", "solid pace", "robust", "above 2 percent",
]
DOVISH = [
    "downside risks", "accommodative", "accommodation", "lower the target", "lowering the target", "cut",
    "ease", "easing", "weak", "weakened", "slow", "slowed", "softening", "softened", "moderated", "patient",
    "below 2 percent", "subdued", "purchase", "purchases", "support the recovery", "strains", "deteriorat",
    "unemployment rate has risen", "decrease in the target range", "highly accommodative", "exceptionally low",
]

_PLAYBOOK = {
    # keyword in asset label -> (goldilocks, overheating, stagflation, recession) annual excess return
    "equities": (0.040, 0.010, -0.030, -0.040),
    "long-term government": (-0.010, -0.040, -0.020, 0.050),
    "intermediate government": (0.000, -0.020, -0.010, 0.030),
    "inflation-protected": (0.000, 0.020, 0.020, 0.005),
    "investment-grade": (0.010, -0.010, -0.010, 0.005),
    "high-yield": (0.020, 0.005, -0.030, -0.040),
    "gold": (-0.010, 0.010, 0.040, 0.010),
    "commodities": (0.000, 0.040, 0.030, -0.030),
    "dollar": (-0.010, 0.010, 0.020, 0.020),
    "cash": (0.000, 0.000, 0.000, 0.000),
}
_ORDER = ("goldilocks", "overheating", "stagflation", "recession")
_RISKY = {"equities", "high-yield", "commodities", "gold"}
_DURATION_BEARERS = {"long-term government", "intermediate government", "inflation-protected", "investment-grade"}


def _block(text: str, tag: str) -> str | None:
    m = re.search(rf"<<{tag}>>\s*(.*?)\s*<<END_{tag}>>", text, re.S)
    return m.group(1) if m else None


def lexicon_stance(text: str) -> tuple[float, list[str]]:
    t = text.lower()
    h = [k for k in HAWKISH if k in t]
    d = [k for k in DOVISH if k in t]
    hs = sum(t.count(k) for k in h)
    ds = sum(t.count(k) for k in d)
    stance = (hs - ds) / (hs + ds + 3.0)
    phrases = (h[:3] + d[:3])[:6]
    return float(max(-1.0, min(1.0, stance))), phrases


def _fix_direction(v: dict) -> dict:
    q = v["expected_excess_return_annual"]
    v["direction"] = "overweight" if q > 0 else ("underweight" if q < 0 else "neutral")
    return v


class MockLLM:
    def respond(self, messages: list[dict[str, str]], task: str | None = None) -> str:
        prompt = "\n".join(m["content"] for m in messages if m["role"] != "system")
        if task == "stance" or (_block(prompt, "STATEMENT") is not None and task != "views"):
            stmt = _block(prompt, "STATEMENT") or prompt
            s, phrases = lexicon_stance(stmt)
            return json.dumps({"stance": round(s, 3), "key_phrases": phrases})
        prev = next((m["content"] for m in reversed(messages) if m["role"] == "assistant"), None)
        return self._views(prompt, prev)

    # ------------------------------------------------------------------ views
    def _views(self, prompt: str, previous_answer: str | None) -> str:
        assets = self._parse_assets(prompt)
        sig = json.loads(_block(prompt, "SIGNALS") or "{}")
        probs = sig.get("regime_probabilities", {}) or {q: 0.25 for q in _ORDER}
        regime = max(probs, key=probs.get) if probs else "unknown"
        vio = _block(prompt, "VIOLATIONS")

        base_views: list[dict] | None = None
        if vio and previous_answer:
            try:
                base_views = json.loads(previous_answer).get("views") or None
            except (json.JSONDecodeError, AttributeError):
                base_views = None

        if base_views is not None:
            views = self._apply_violations(vio, [dict(v) for v in base_views], assets)
            rationale = "Deterministic mock: previous views revised toward feasibility in response to the critic's violations."
        else:
            views = self._fresh_views(sig, assets, probs, regime)
            if vio:
                views = self._apply_violations(vio, views, assets)
            rationale = "Deterministic mock: regime-probability-weighted playbook adjusted for Fed stance x novelty and newspaper-based uncertainty indices."

        views = [v for v in views if abs(v["expected_excess_return_annual"]) >= 0.002] or [
            {"asset": next(iter(assets), "Asset A"), "direction": "neutral", "expected_excess_return_annual": 0.0, "confidence": 0.3, "evidence": ["no signal above threshold"]}
        ]
        views.sort(key=lambda v: -abs(v["expected_excess_return_annual"]))
        return json.dumps({"regime_assessment": f"Most likely regime: {regime}.", "views": views[:8], "rationale": rationale})

    def _fresh_views(self, sig: dict, assets: dict[str, str], probs: dict, regime: str) -> list[dict]:
        stance = float(sig.get("fed_stance", 0.0) or 0.0)
        novelty = float(sig.get("fed_statement_novelty", 0.0) or 0.0)
        tz = sig.get("text_index_z", {}) or {}
        epu_z = float(tz.get("epu", 0.0) or 0.0)
        gpr_z = float(tz.get("gpr", 0.0) or 0.0)
        gpr_threat_z = float(tz.get("gpr_threat", 0.0) or 0.0)
        themes = sig.get("themes", {}) or {}
        fin = float(themes.get("financial", 0.0) or 0.0)
        surprise = stance * (0.5 + novelty)
        top_p = max(probs.values()) if probs else 0.25

        views = []
        for code, label in assets.items():
            kind = self._kind(label)
            if kind is None:
                continue
            # 0.6 scales the playbook to typical strategist magnitudes (1-3%/yr); the raw table is easier to read
            base = 0.6 * sum(probs.get(q, 0.0) * _PLAYBOOK[kind][i] for i, q in enumerate(_ORDER))
            adj = 0.0
            ev = [f"{kind}: regime-weighted playbook {base:+.3f} (top regime {regime} {top_p:.0%})"]
            if kind in ("long-term government", "intermediate government", "investment-grade") and abs(surprise) > 0.05:
                adj -= 0.020 * surprise
                ev.append(f"Fed surprise {surprise:+.2f} ({'hawkish' if stance > 0 else 'dovish'} stance {stance:+.2f} x novelty {novelty:.2f}) -> {-0.020 * surprise:+.3f}")
            if kind == "equities":
                a = -0.010 * surprise - 0.006 * max(epu_z, 0.0) - 0.008 * max(gpr_z, 0.0)
                adj += a
                if abs(a) > 0.002:
                    ev.append(f"Fed surprise / policy uncertainty z={epu_z:+.1f} / geopolitical z={gpr_z:+.1f} -> {a:+.3f}")
            if kind == "high-yield":
                a = -0.008 * max(epu_z, 0.0) - 0.010 * max(fin, 0.0)
                adj += a
                if abs(a) > 0.002:
                    ev.append(f"credit penalised by uncertainty z={epu_z:+.1f} and financial-stress theme {fin:+.2f} -> {a:+.3f}")
            if kind == "gold":
                a = 0.010 * max(gpr_threat_z, 0.0) + 0.006 * max(epu_z, 0.0)
                adj += a
                if abs(a) > 0.002:
                    ev.append(f"safe-haven demand: geopolitical threats z={gpr_threat_z:+.1f}, uncertainty z={epu_z:+.1f} -> {a:+.3f}")
            if kind == "dollar":
                a = 0.012 * surprise + 0.006 * max(gpr_z, 0.0)
                adj += a
                if abs(a) > 0.002:
                    ev.append(f"dollar supported by Fed surprise {surprise:+.2f} and geopolitical z={gpr_z:+.1f} -> {a:+.3f}")
            if kind == "cash":
                adj += 0.004 * max(fin, 0.0)
            q = base + adj
            if abs(q) < 0.004:
                continue
            conf = float(max(0.2, min(0.9, 0.30 + 0.35 * top_p + min(0.25, abs(q) / 0.06))))
            views.append(_fix_direction({"asset": code, "direction": "", "expected_excess_return_annual": round(q, 4), "confidence": round(conf, 3), "evidence": ev[:4]}))
        views.sort(key=lambda v: -abs(v["expected_excess_return_annual"]))
        return views[:6]

    # ------------------------------------------------------------------ revision
    def _apply_violations(self, vio_text: str, views: list[dict], assets: dict[str, str]) -> list[dict]:
        text = vio_text.lower()
        kinds = {code: self._kind(label) for code, label in assets.items()}
        by_code = {v["asset"]: v for v in views}

        def touch(code: str, delta_q: float | None = None, scale: float | None = None, note: str = "", conf_delta: float = -0.15):
            v = by_code.get(code)
            if v is None:
                if delta_q is None:
                    return
                v = {"asset": code, "direction": "", "expected_excess_return_annual": 0.0, "confidence": 0.5, "evidence": []}
                by_code[code] = v
                views.append(v)
            q = v["expected_excess_return_annual"]
            if scale is not None:
                q *= scale
            if delta_q is not None:
                q += delta_q
            v["expected_excess_return_annual"] = round(q, 4)
            v["confidence"] = round(max(0.2, min(0.9, v["confidence"] + conf_delta)), 3)
            ev = list(v.get("evidence") or [])
            note = note or "revised after constraint feedback"
            if note not in ev:
                ev = ev[:4] + [note]
            v["evidence"] = ev[:6]
            _fix_direction(v)

        # 1. named single-asset caps: halve the offending view (only lines that name the asset and a cap).
        # Whole-word match: a bare substring test would find "asset c" inside "single-asset cap" and halve
        # Asset C on every cap message regardless of which asset was named.
        for line in text.splitlines():
            if "single-asset" not in line:
                continue
            for code in assets:
                if re.search(rf"\b{re.escape(code.lower())}\b", line):
                    touch(code, scale=0.5, note="halved: single-asset cap")

        # 2. duration band
        if "too long" in text:
            for code, k in kinds.items():
                if k in ("long-term government", "intermediate government") and by_code.get(code, {}).get("expected_excess_return_annual", 0) > 0:
                    touch(code, scale=0.5, note="halved: portfolio duration too long")
            cash = next((c for c, k in kinds.items() if k == "cash"), None)
            if cash:
                touch(cash, delta_q=0.010, note="duration relief via cash", conf_delta=0.0)
        if "too short" in text:
            for code, k in kinds.items():
                if k in ("cash", "dollar") and by_code.get(code, {}).get("expected_excess_return_annual", 0) > 0:
                    touch(code, scale=0.5, note="halved: zero-duration exposure while duration too short")
            mid = next((c for c, k in kinds.items() if k == "intermediate government"), None)
            tips = next((c for c, k in kinds.items() if k == "inflation-protected"), None)
            if mid:
                touch(mid, delta_q=0.015, note="added duration via intermediate maturities", conf_delta=0.0)
            if tips:
                touch(tips, delta_q=0.008, note="added duration via inflation-protected bonds", conf_delta=0.0)

        # 3. volatility cap: shrink everything
        if "volatility" in text:
            for code in list(by_code):
                touch(code, scale=0.7, note="scaled down: volatility limit")

        # 4. capital budget: shrink risky longs, favour cash
        if "capital budget" in text or "risk-weighted" in text:
            for code, k in kinds.items():
                if k in _RISKY and by_code.get(code, {}).get("expected_excess_return_annual", 0) > 0:
                    touch(code, scale=0.6, note="scaled down: capital budget")
            cash = next((c for c, k in kinds.items() if k == "cash"), None)
            if cash:
                touch(cash, delta_q=0.005, note="capital relief via cash", conf_delta=0.0)
        return [v for v in views if v["asset"] in assets][:8]

    # ------------------------------------------------------------------ helpers
    @staticmethod
    def _parse_assets(prompt: str) -> dict[str, str]:
        out: dict[str, str] = {}
        block = _block(prompt, "ASSETS") or prompt
        for m in re.finditer(r"^-\s*([^:\n]+):\s*(.+)$", block, re.M):
            out[m.group(1).strip()] = m.group(2).strip()
        return out

    @staticmethod
    def _kind(label: str) -> str | None:
        lab = label.lower()
        for k in _PLAYBOOK:
            if k in lab:
                return k
        if "government" in lab and ("20" in lab or "long" in lab):
            return "long-term government"
        if "government" in lab:
            return "intermediate government"
        if "equit" in lab or "stock" in lab:
            return "equities"
        if "bill" in lab or "treasury bills" in lab:
            return "cash"
        return None
