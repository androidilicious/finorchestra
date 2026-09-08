"""Interactive dashboard for a completed run: one self-contained HTML file with the run's data embedded.

`build_dashboard(run_dir)` reads summary.json, panel.csv, returns_*.csv, weights_*.csv and decisions/*.json,
compacts them into a JSON bundle, and writes `dashboard.html` next to `report.md`. No server, no external data,
no library: every chart is hand-drawn SVG so marks, gaps, crosshairs and tables follow one spec. Every number
shown is reachable without hovering (tables under each chart), and both colour themes are designed, not flipped.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pandas as pd

from ..config import Config, load_config
from ..utils import LOG


def _round(x: Any, nd: int = 4) -> Any:
    try:
        if x is None or (isinstance(x, float) and pd.isna(x)):
            return None
        return round(float(x), nd)
    except (TypeError, ValueError):
        return x


def _compact_views(views: list[dict]) -> list[list]:
    out = []
    for v in views:
        ev = [str(e)[:140] for e in (v.get("evidence") or [])[:2]]
        out.append([v["asset"], v["direction"], _round(v["expected_excess_return_annual"], 4), _round(v["confidence"], 3), ev])
    return out


def _compact_decision(alloc: dict) -> dict:
    hist = []
    for h in alloc.get("revision_history") or []:
        hist.append([[v["asset"], _round(v["expected_excess_return_annual"], 4), _round(v["confidence"], 3)] for v in h.get("views_after") or []])
    vs = alloc.get("views") or {}
    return {
        "v": _compact_views(vs.get("views") or []),
        "ra": str(vs.get("regime_assessment") or "")[:200],
        "rat": str(vs.get("rationale") or "")[:400],
        "bf": [b["rule"] for b in alloc.get("binding_constraints_first_pass") or []],
        "bl": [b["rule"] for b in alloc.get("binding_constraints_final") or []],
        "bm": [b["message"] for b in alloc.get("binding_constraints_first_pass") or []][:4],
        "r": int(alloc.get("feedback_rounds") or 0),
        "h": hist,
        "cs": {k: _round(v, 4) if not isinstance(v, list) else [_round(x, 3) for x in v] for k, v in (alloc.get("constraint_summary") or {}).items()},
        "fv": len(alloc.get("final_violations") or []),
        "rt": bool((alloc.get("optimizer") or {}).get("relaxed_turnover")),
    }


def bundle(run_dir: Path, cfg: Config | None = None) -> dict[str, Any]:
    run_dir = Path(run_dir)
    summary = json.loads((run_dir / "summary.json").read_text(encoding="utf-8"))
    panel = pd.read_csv(run_dir / "panel.csv", index_col=0, parse_dates=True)
    gross = pd.read_csv(run_dir / "returns_gross.csv", index_col=0, parse_dates=True)
    excess = pd.read_csv(run_dir / "returns_excess.csv", index_col=0, parse_dates=True)
    weights = {}
    for p in sorted(run_dir.glob("weights_*.csv")):
        weights[p.stem.replace("weights_", "")] = pd.read_csv(p, index_col=0, parse_dates=True)

    strategies = [s for s in ("rule", "llm_clip", "llm_feedback") if s in gross.columns]
    baselines = [c for c in gross.columns if c not in strategies]  # e.g. benchmark, sixty_forty (older runs: market, inverse_vol)
    dates = [d.strftime("%Y-%m-%d") for d in panel.index]
    assets = list(next(iter(weights.values())).columns) if weights else []

    cfg = cfg or load_config(run_dir.parents[2] / "configs" / "default.yaml") if (run_dir.parents[2] / "configs" / "default.yaml").exists() else cfg
    asset_meta = {}
    caps: dict = {}
    limits: dict = {}
    if cfg is not None:
        for a in cfg.market.universe:
            asset_meta[a.ticker] = {"label": a.label, "kind": a.kind}
    # caps and limits are relative to the date's neutral portfolio, so they vary by date: the dashboard shows the
    # last decision's values, read from that decision's constraint summary rather than from the config
    last_dec_path = sorted((run_dir / "decisions").glob("*.json"))[-1] if (run_dir / "decisions").exists() else None
    if last_dec_path is not None:
        ld = json.loads(last_dec_path.read_text(encoding="utf-8"))
        first_strategy = next(iter((ld.get("strategies") or {}).values()), None)
        cs_last = ((first_strategy or {}).get("allocation") or {}).get("constraint_summary") or {}
        caps = cs_last.get("caps") or {}
        band = cs_last.get("duration_band") or [None, None]
        limits = {"vol": cs_last.get("volatility_limit"), "dur_lo": band[0], "dur_hi": band[1], "rw": cs_last.get("risk_weight_budget"), "turnover": cfg.allocation.mandate.max_one_way_turnover if cfg is not None else None, "neutral": cs_last.get("benchmark") or ld.get("neutral_portfolio")}

    # per-decision compact records
    decisions: dict[str, list] = {s: [] for s in strategies}
    cons: dict[str, dict[str, list]] = {s: {"vol": [], "dur": [], "rw": [], "to": []} for s in strategies}
    fed_text: list[dict] = []
    ddir = run_dir / "decisions"
    for d in dates:
        p = ddir / f"{d}.json"
        if not p.exists():
            for s in strategies:
                decisions[s].append(None)
                for k in cons[s]:
                    cons[s][k].append(None)
            fed_text.append({})
            continue
        dec = json.loads(p.read_text(encoding="utf-8"))
        ts = dec.get("text_signal") or {}
        fed_text.append({"sd": ts.get("statement_date"), "kp": (ts.get("key_phrases") or [])[:4]})
        for s in strategies:
            st = (dec.get("strategies") or {}).get(s)
            if not st:
                decisions[s].append(None)
                for k in cons[s]:
                    cons[s][k].append(None)
                continue
            alloc = st["allocation"]
            decisions[s].append(_compact_decision(alloc))
            cs = alloc.get("constraint_summary") or {}
            cons[s]["vol"].append(_round(cs.get("volatility")))
            cons[s]["dur"].append(_round(cs.get("duration"), 3))
            cons[s]["rw"].append(_round(cs.get("risk_weighted_exposure")))
            cons[s]["to"].append(_round(cs.get("one_way_turnover")))

    panel_cols = [c for c in panel.columns if c != "regime"]
    inc = summary.get("incremental_test") or []
    cert = summary.get("certificate") or {}
    return {
        "meta": {
            "run_id": summary["run_id"],
            "model": summary.get("model") or {},
            "dates": summary.get("dates") or {},
            "strategies": strategies,
            "baselines": baselines,
            "assets": assets,
            "cash": cfg.market.risk_free_ticker if cfg is not None else "BIL",
            "asset_meta": asset_meta,
            "caps": caps,
            "limits": limits,
            "elapsed_s": summary.get("elapsed_s"),
        },
        "dates": dates,
        "ret_dates": [d.strftime("%Y-%m-%d") for d in gross.index],
        "gross": {c: [_round(x, 6) for x in gross[c].tolist()] for c in gross.columns},
        "excess": {c: [_round(x, 6) for x in excess[c].tolist()] for c in excess.columns},
        "weights": {k: [[_round(x, 4) for x in row] for row in v.reindex(panel.index).fillna(0.0).values.tolist()] for k, v in weights.items()},
        "panel": {c: [_round(x, 4) for x in panel[c].tolist()] for c in panel_cols},
        "regime": panel["regime"].tolist() if "regime" in panel.columns else [],
        "cons": cons,
        "decisions": decisions,
        "fed_text": fed_text,
        "summary": {
            "performance": summary.get("performance") or {},
            "deflated": summary.get("deflated") or {},
            "comparisons": summary.get("comparisons") or {},
            "attribution": summary.get("attribution") or {},
            "feedback": summary.get("feedback") or {},
            "incremental_test": inc,
            "regime_share": summary.get("regime_share") or {},
            "certificate": {
                "inputs": cert.get("inputs") or [],
                "model": cert.get("model") or {},
                "model_call_stats": cert.get("model_call_stats") or {},
                "prompt_masking": cert.get("prompt_masking") or {},
                "knowledge_cutoff": cert.get("knowledge_cutoff") or {},
                "multiple_testing": cert.get("multiple_testing") or {},
            },
        },
    }


def build_dashboard(run_dir: Path, cfg: Config | None = None, out_name: str = "dashboard.html") -> Path:
    run_dir = Path(run_dir)
    data = bundle(run_dir, cfg)
    payload = json.dumps(data, separators=(",", ":"), ensure_ascii=False).replace("</", "<\\/")
    html = TEMPLATE.replace("__DATA_JSON__", payload)
    out = run_dir / out_name
    out.write_text(html, encoding="utf-8")
    LOG.info("dashboard -> %s (%.1f MB)", out, len(html) / 1e6)
    return out


# ---------------------------------------------------------------------------------------------------------------
# Template. Body content only (no doctype/html/head/body): it renders standalone and inside the Artifact wrapper.
# ---------------------------------------------------------------------------------------------------------------
TEMPLATE = r"""<title>Finorchestra Portfolio Intelligence</title>
<style>
  :root {
    color-scheme: light;
    --page: #f9f9f7; --surface: #fcfcfb; --ink: #0b0b0b; --ink2: #52514e; --muted: #898781; --grid: #e1e0d9; --axis: #c3c2b7;
    --ring: rgba(11,11,11,0.10); --wash: rgba(42,120,214,0.10);
    --s1: #2a78d6; --s2: #eb6834; --s3: #1baf7a; --s4: #eda100; --s5: #e87ba4; --s6: #008300; --s7: #4a3aa7; --s8: #e34948;
    --g1: #6f6d67; --g2: #a09e96; --g3: #c9c7bf;
    --seq-lo: #86b6ef; --seq-hi: #2a78d6;
    --good: #006300; --critical: #d03b3b; --warning: #fab219;
    --accent: #2a78d6; --chip: #eef1f4; --soft: #e8f0fb;
  }
  @media (prefers-color-scheme: dark) {
    :root:not([data-theme="light"]) {
      color-scheme: dark;
      --page: #0d0d0d; --surface: #1a1a19; --ink: #ffffff; --ink2: #c3c2b7; --muted: #898781; --grid: #2c2c2a; --axis: #383835;
      --ring: rgba(255,255,255,0.10); --wash: rgba(57,135,229,0.14);
      --s1: #3987e5; --s2: #d95926; --s3: #199e70; --s4: #c98500; --s5: #d55181; --s6: #008300; --s7: #9085e9; --s8: #e66767;
      --g1: #b5b3ab; --g2: #8a887f; --g3: #5e5c55;
      --seq-lo: #184f95; --seq-hi: #3987e5;
      --good: #0ca30c; --critical: #d03b3b; --warning: #fab219;
      --accent: #3987e5; --chip: #242a30; --soft: #14243a;
    }
  }
  :root[data-theme="dark"] {
    color-scheme: dark;
    --page: #0d0d0d; --surface: #1a1a19; --ink: #ffffff; --ink2: #c3c2b7; --muted: #898781; --grid: #2c2c2a; --axis: #383835;
    --ring: rgba(255,255,255,0.10); --wash: rgba(57,135,229,0.14);
    --s1: #3987e5; --s2: #d95926; --s3: #199e70; --s4: #c98500; --s5: #d55181; --s6: #008300; --s7: #9085e9; --s8: #e66767;
    --g1: #b5b3ab; --g2: #8a887f; --g3: #5e5c55;
    --seq-lo: #184f95; --seq-hi: #3987e5;
    --good: #0ca30c; --critical: #d03b3b; --warning: #fab219;
    --accent: #3987e5; --chip: #242a30; --soft: #14243a;
  }
  * { box-sizing: border-box; }
  body { margin: 0; background: var(--page); color: var(--ink); font: 16px/1.55 system-ui, -apple-system, "Segoe UI", sans-serif; }
  .wrap { max-width: 1080px; margin: 0 auto; padding: 32px 22px 80px; }
  header.top { margin-bottom: 22px; }
  header.top h1 { font-size: 34px; font-weight: 650; margin: 0 0 6px; letter-spacing: -.015em; }
  header.top .sub { font-size: 18px; color: var(--ink2); margin: 0 0 6px; max-width: 62ch; }
  .quiet { color: var(--muted); font-size: 13.5px; }
  .card { background: var(--surface); border: 1px solid var(--ring); border-radius: 10px; padding: 22px 24px 20px; margin-bottom: 22px; position: relative; }
  .card h2 { font-size: 22px; font-weight: 650; margin: 0 0 6px; letter-spacing: -.01em; text-wrap: balance; }
  .card h3 { font-size: 14px; font-weight: 650; margin: 0 0 6px; text-transform: uppercase; letter-spacing: .05em; color: var(--ink2); }
  .card .lead { font-size: 15.5px; color: var(--ink2); margin: 0 0 14px; max-width: 72ch; }
  .takeaway { font-size: 16px; margin: 0 0 14px; padding: 12px 16px; background: var(--soft); border-left: 3px solid var(--accent); border-radius: 0 8px 8px 0; max-width: 78ch; }
  .takeaway b { font-weight: 650; }
  .grid3 { display: grid; grid-template-columns: 1fr 1fr 1fr; gap: 20px; }
  .grid2 { display: grid; grid-template-columns: 1fr 1fr; gap: 20px; }
  .grid5 { display: grid; grid-template-columns: repeat(5, 1fr); gap: 12px; }
  @media (max-width: 900px) { .grid3, .grid2 { grid-template-columns: 1fr; } .grid5 { grid-template-columns: repeat(2, 1fr); } }
  .players { list-style: none; padding: 0; margin: 0; }
  .players li { display: grid; grid-template-columns: 14px 1fr; gap: 10px; align-items: start; margin-bottom: 10px; font-size: 14.5px; }
  .players .sw { width: 14px; height: 14px; border-radius: 3px; margin-top: 4px; }
  .players b { display: block; font-weight: 650; }
  .players .why { color: var(--ink2); font-size: 13.5px; }
  .filters { display: flex; flex-wrap: wrap; gap: 12px 22px; align-items: center; padding: 12px 16px; background: var(--surface); border: 1px solid var(--ring); border-radius: 10px; margin-bottom: 22px; position: sticky; top: 0; z-index: 5; }
  .filters label { font-size: 12px; color: var(--ink2); text-transform: uppercase; letter-spacing: .05em; margin-right: 8px; }
  .seg { display: inline-flex; border: 1px solid var(--axis); border-radius: 8px; overflow: hidden; flex-wrap: wrap; }
  .seg button { font: inherit; font-size: 13.5px; padding: 6px 12px; border: 0; background: transparent; color: var(--ink2); cursor: pointer; }
  .seg button + button { border-left: 1px solid var(--axis); }
  .seg button[aria-pressed="true"] { background: var(--chip); color: var(--ink); font-weight: 650; }
  .seg button:focus-visible { outline: 2px solid var(--accent); outline-offset: -2px; }
  .seg button .dot { display: inline-block; width: 9px; height: 9px; border-radius: 2px; margin-right: 7px; vertical-align: 0; }
  .hero { display: grid; grid-template-columns: 220px 1fr; gap: 24px; align-items: start; }
  @media (max-width: 760px) { .hero { grid-template-columns: 1fr; } }
  .hero .num { font-size: 64px; font-weight: 650; line-height: 1; letter-spacing: -.02em; }
  .hero .numlab { font-size: 13.5px; color: var(--ink2); margin-top: 6px; max-width: 24ch; }
  .verdicts { list-style: none; margin: 0; padding: 0; }
  .verdicts li { padding: 10px 0; border-bottom: 1px solid var(--grid); font-size: 15.5px; }
  .verdicts li:last-child { border-bottom: 0; }
  .verdicts .tag { display: inline-block; font-size: 12px; padding: 2px 8px; border-radius: 999px; margin-right: 8px; vertical-align: 1px; border: 1px solid var(--axis); color: var(--ink2); }
  .verdicts .tag.good { border-color: var(--good); color: var(--good); }
  .verdicts .tag.bad { border-color: var(--critical); color: var(--critical); }
  .stat { display: flex; flex-wrap: wrap; gap: 12px; margin: 6px 0 14px; }
  .stat div { background: var(--chip); border-radius: 8px; padding: 10px 14px; min-width: 160px; }
  .stat .v { font-size: 24px; font-weight: 650; line-height: 1.1; }
  .stat .l { font-size: 12.5px; color: var(--ink2); margin-top: 2px; }
  .chart { position: relative; width: 100%; }
  .chart svg { display: block; width: 100%; height: auto; overflow: visible; }
  .legend { display: flex; flex-wrap: wrap; gap: 6px 16px; font-size: 12.5px; color: var(--ink2); margin-top: 8px; }
  .legend .k { display: inline-block; width: 14px; height: 0; border-top: 2px solid; vertical-align: middle; margin-right: 6px; border-radius: 2px; }
  .legend .k.rect { height: 10px; border: 0; border-radius: 2px; }
  .tools { position: absolute; top: 18px; right: 20px; display: flex; gap: 6px; }
  .tools button { font: inherit; font-size: 12px; padding: 3px 9px; border: 1px solid var(--axis); background: transparent; color: var(--ink2); border-radius: 6px; cursor: pointer; }
  .tools button[aria-pressed="true"] { background: var(--chip); color: var(--ink); }
  .tip { position: absolute; pointer-events: none; background: var(--surface); border: 1px solid var(--ring); box-shadow: 0 4px 14px rgba(0,0,0,.12); border-radius: 6px; padding: 8px 10px; font-size: 12px; min-width: 150px; z-index: 10; display: none; }
  .tip .d { color: var(--ink2); margin-bottom: 4px; font-variant-numeric: tabular-nums; }
  .tip .row { display: flex; align-items: center; gap: 8px; line-height: 1.5; }
  .tip .row .k { width: 12px; border-top: 2px solid; }
  .tip .row .v { font-weight: 600; min-width: 52px; text-align: right; font-variant-numeric: tabular-nums; }
  .tip .row .n { color: var(--ink2); }
  .tbl { display: none; margin-top: 8px; max-height: 260px; overflow: auto; border: 1px solid var(--ring); border-radius: 6px; }
  .tbl.open { display: block; }
  table { border-collapse: collapse; width: 100%; font-size: 13px; font-variant-numeric: tabular-nums; }
  th, td { padding: 6px 8px; text-align: right; border-bottom: 1px solid var(--grid); white-space: nowrap; vertical-align: top; }
  th:first-child, td:first-child { text-align: left; }
  th { position: sticky; top: 0; background: var(--surface); color: var(--ink2); font-weight: 600; font-size: 11.5px; text-transform: uppercase; letter-spacing: .04em; }
  td.txt { text-align: left; white-space: normal; }
  .small h4 { font-size: 13px; font-weight: 600; margin: 0 0 2px; color: var(--ink2); }
  .small .cur { font-size: 12.5px; color: var(--ink); font-weight: 650; float: right; font-variant-numeric: tabular-nums; }
  .explorer { display: grid; grid-template-columns: 1.15fr 1fr; gap: 20px; }
  @media (max-width: 900px) { .explorer { grid-template-columns: 1fr; } }
  .scrub { display: flex; align-items: center; gap: 10px; margin: 6px 0 14px; flex-wrap: wrap; }
  .scrub input[type=range] { flex: 1; min-width: 200px; accent-color: var(--accent); }
  .scrub .date { font-weight: 650; font-variant-numeric: tabular-nums; min-width: 96px; }
  .scrub button { font: inherit; font-size: 12px; padding: 4px 10px; border: 1px solid var(--axis); background: transparent; color: var(--ink); border-radius: 6px; cursor: pointer; }
  .pill { display: inline-block; padding: 1px 9px; border-radius: 999px; font-size: 12px; background: var(--chip); color: var(--ink2); margin-right: 4px; }
  .pill.bad { background: transparent; border: 1px solid var(--critical); color: var(--critical); }
  .pill.ok { background: transparent; border: 1px solid var(--good); color: var(--good); }
  .meter { margin: 8px 0; font-size: 12.5px; }
  .meter .lab { display: flex; justify-content: space-between; color: var(--ink2); }
  .meter .lab b { color: var(--ink); font-variant-numeric: tabular-nums; }
  .meter .track { height: 8px; border-radius: 4px; background: var(--seq-lo); position: relative; overflow: hidden; }
  .meter .fill { height: 100%; background: var(--seq-hi); border-radius: 4px; }
  .meter .band { position: absolute; top: 0; height: 100%; background: rgba(0,0,0,.10); }
  .bars { margin-top: 6px; }
  .bar { display: grid; grid-template-columns: 52px 1fr 52px; align-items: center; gap: 8px; font-size: 12.5px; margin: 3px 0; }
  .bars.wide .bar { grid-template-columns: 96px 1fr 52px; }
  .bar .t { color: var(--ink2); font-family: ui-monospace, Consolas, monospace; }
  .bar .b { height: 12px; background: var(--seq-hi); border-radius: 0 4px 4px 0; }
  .bar .v { text-align: right; font-variant-numeric: tabular-nums; }
  details.quants { background: var(--surface); border: 1px solid var(--ring); border-radius: 10px; padding: 8px 24px 4px; margin-bottom: 22px; }
  details.quants summary { cursor: pointer; font-size: 16px; font-weight: 650; padding: 12px 0; list-style: none; }
  details.quants summary::-webkit-details-marker { display: none; }
  details.quants summary::before { content: "▸ "; color: var(--accent); }
  details.quants[open] summary::before { content: "▾ "; }
  details.quants .card { border: 0; padding: 10px 0 14px; margin: 0; border-top: 1px solid var(--grid); border-radius: 0; }
  details.quants .card .tools { top: 8px; right: 0; }
  pre { font-size: 11.5px; overflow: auto; background: var(--chip); padding: 10px; border-radius: 6px; }
  .foot { color: var(--muted); font-size: 12.5px; margin-top: 18px; }
  dfn.hov { font-style: normal; cursor: help; text-decoration: underline dotted; text-decoration-color: var(--accent); text-underline-offset: 3px; text-decoration-thickness: 1.5px; }
  dfn.hov:hover, dfn.hov:focus-visible, dfn.hov.on { background: var(--soft); outline: none; border-radius: 2px; }
  #termtip { position: fixed; z-index: 50; max-width: 340px; background: var(--surface); color: var(--ink); border: 1px solid var(--ring); border-left: 3px solid var(--accent); border-radius: 6px; box-shadow: 0 4px 14px rgba(0,0,0,.14); padding: 10px 14px; font-size: 13.5px; line-height: 1.45; display: none; pointer-events: none; }
  #termtip b { display: block; font-family: ui-monospace, Consolas, monospace; font-size: 12px; color: var(--accent); margin-bottom: 3px; font-weight: 500; }
  @media (prefers-reduced-motion: no-preference) { .hero .num { transition: color .2s; } }
</style>

<div class="wrap">
  <header class="top">
    <h1>Finorchestra</h1>
    <p class="sub">Three ways of splitting the same money across ten funds, tested week after week on data that was knowable at the time. This page shows what each would have done, what it earned, and whether the difference is more than luck.</p>
    <p class="quiet" id="runline"></p>
  </header>

  <section class="card">
    <h2>Start here</h2>
    <div class="grid3">
      <div>
        <h3>The setup</h3>
        <p style="margin:0;font-size:14.5px">Every Friday, a decision-maker splits one dollar across ten funds that stand for the big asset classes: stocks, several kinds of bonds, gold, commodities, the dollar, and cash. It may use only what had been published by that day, and it must obey a bank's rules on concentration, risk, interest-rate sensitivity, and capital. We hold the split for a week, record what it earned, and repeat.</p>
      </div>
      <div>
        <h3>The three players</h3>
        <ul class="players" id="playersList"></ul>
      </div>
      <div>
        <h3>How to read the numbers</h3>
        <p style="margin:0 0 8px;font-size:14.5px"><b>Reward per unit of risk</b> (the Sharpe ratio) is the main score: return above cash divided by how much the value swung. Around 0.5 is ordinary, 1.0 is very good, below 0 lost to cash.</p>
        <p style="margin:0 0 8px;font-size:14.5px"><b>Luck check</b> (a p-value): the chance a difference this big appears by chance. Below 0.05 means probably real.</p>
        <p style="margin:0;font-size:14.5px"><b>Trading cost</b>: a player that trades a lot pays for it. We show the score after charging 0.3% on every unit traded.</p>
      </div>
    </div>
  </section>

  <div class="filters" role="group" aria-label="Filters">
    <span><label>Period</label><span class="seg" id="rangeSeg"></span></span>
    <span><label>Focus on</label><span class="seg" id="stratSeg"></span></span>
    <span class="quiet" id="rangeNote"></span>
  </div>

  <section class="card">
    <h2 id="vTitle">The verdict</h2>
    <div class="hero">
      <div><div class="num" id="heroNum">–</div><div class="numlab">reward per unit of risk over the selected period</div></div>
      <div>
        <ul class="verdicts" id="verdicts"></ul>
        <p class="quiet" id="verdictNote" style="margin-top:10px"></p>
      </div>
    </div>
  </section>

  <section class="card">
    <h2>Did it grow the money?</h2>
    <p class="lead">One dollar invested at the start of the period, held according to each player's weekly decisions. The player you focus on is drawn thicker; the three yardsticks that form no opinion are grey.</p>
    <div class="takeaway" id="growthTake"></div>
    <div class="tools"><button type="button" data-table="growth">Table</button></div>
    <div class="chart" id="growth"></div>
    <div class="tbl" id="growth-tbl"></div>
  </section>

  <section class="card">
    <h2>How bad were the worst stretches?</h2>
    <p class="lead">How far each player's dollar sat below its own previous high. A bank cares about this as much as about the average.</p>
    <div class="takeaway" id="ddTake"></div>
    <div class="tools"><button type="button" data-table="dd">Table</button></div>
    <div class="chart" id="dd"></div>
    <div class="tbl" id="dd-tbl"></div>
  </section>

  <section class="card" id="ideaCard">
    <h2>The new idea: tell the AI which rule it broke</h2>
    <p class="lead">When the AI's proposal breaks a bank rule, most systems quietly trim it to fit and move on. Here, a rule-checker writes back in plain language ("gold is pinned at its active-band cap of 23%; the views asked for more") and the AI is asked to revise, up to twice. The same first proposal feeds both variants, so the only difference between "silently clipped" and "told which rules it broke" is that conversation.</p>
    <div class="stat" id="ideaStats"></div>
    <div class="takeaway" id="ideaTake"></div>
    <div class="grid2">
      <div>
        <h3>By quarter: how often the first proposal hit a rule, and how often the revision fixed it</h3>
        <div class="tools"><button type="button" data-table="fb">Table</button></div>
        <div class="chart" id="fb"></div>
        <div class="tbl" id="fb-tbl"></div>
      </div>
      <div>
        <h3>What a revision looks like</h3>
        <div id="ideaExample" style="font-size:14px"></div>
      </div>
    </div>
  </section>

  <section class="card">
    <h2 id="allocTitle">What did it hold?</h2>
    <p class="lead">Weight in each fund over time for the player you focus on. The line at the top of each panel is that fund's cap on the last date (neutral weight plus the active band). The number is the weight on the last date of the period.</p>
    <div class="takeaway" id="allocTake"></div>
    <div class="tools"><button type="button" data-table="alloc">Table</button></div>
    <div class="grid5" id="alloc"></div>
    <div class="tbl" id="alloc-tbl"></div>
  </section>

  <section class="card">
    <h2 id="consTitle">Did it stay inside the rules?</h2>
    <p class="lead">Three of the bank's limits, and how close the book sat to each one every week. A separate rule-checker re-tested every executed portfolio; its verdict is below the charts.</p>
    <div class="tools"><button type="button" data-table="cons">Table</button></div>
    <div class="grid3" id="cons"></div>
    <div class="tbl" id="cons-tbl"></div>
    <div class="takeaway" id="consNote" style="margin-top:12px"></div>
  </section>

  <section class="card">
    <h2>Pick a week and read the reasoning</h2>
    <p class="lead">Every number here is what the system recorded that week. Nothing is reconstructed afterwards. Drag the slider or use the arrows.</p>
    <div class="scrub">
      <button type="button" id="prevD" aria-label="Previous week">&#8592;</button>
      <input type="range" id="scrub" min="0" max="0" value="0" aria-label="Decision date">
      <button type="button" id="nextD" aria-label="Next week">&#8594;</button>
      <span class="date" id="scrubDate"></span>
    </div>
    <div class="explorer">
      <div id="exLeft"></div>
      <div id="exRight"></div>
    </div>
  </section>

  <section class="card">
    <h2>Was it luck, or just the market?</h2>
    <p class="lead">Two checks a skeptic would ask for. First, reshuffle the history thousands of times to see how often a Sharpe difference this big appears by chance. Second, split each player's result into the part that comes from simply owning the market, the part from known tilts, and the part that might be skill.</p>
    <div class="grid2">
      <div>
        <h3>Luck check, full run</h3>
        <div id="stats"></div>
      </div>
      <div>
        <h3>Where the result came from</h3>
        <div class="tools"><button type="button" data-table="attr">Table</button></div>
        <div class="chart" id="attr"></div>
        <div class="tbl" id="attr-tbl"></div>
        <p class="quiet" id="attrNote" style="margin-top:8px"></p>
      </div>
    </div>
  </section>

  <details class="quants">
    <summary>For the quants: rolling Sharpe, costs, regimes, macro themes, the text-signal test, the certificate</summary>
    <div class="card">
      <h2>Rolling one-year reward per unit of risk</h2>
      <div class="tools"><button type="button" data-table="rs">Table</button></div>
      <div class="chart" id="rs"></div>
      <div class="tbl" id="rs-tbl"></div>
    </div>
    <div class="card">
      <h2>Score after trading costs</h2>
      <p class="lead">One-way cost charged on each week's turnover. Players that barely trade are flat.</p>
      <div class="tools"><button type="button" data-table="cost">Table</button></div>
      <div class="chart" id="cost"></div>
      <div class="tbl" id="cost-tbl"></div>
    </div>
    <div class="grid2">
      <div class="card">
        <h2>Regime probabilities</h2>
        <p class="lead">Which economic season the signals pointed to: growth up or down, inflation up or down.</p>
        <div class="tools"><button type="button" data-table="regime">Table</button></div>
        <div class="chart" id="regime"></div>
        <div class="tbl" id="regime-tbl"></div>
      </div>
      <div class="card">
        <h2>Macro themes (z-scores)</h2>
        <p class="lead">Above zero means above its own ten-year normal.</p>
        <div class="tools"><button type="button" data-table="themes">Table</button></div>
        <div class="grid2" id="themes" style="gap:8px"></div>
        <div class="tbl" id="themes-tbl"></div>
      </div>
    </div>
    <div class="card">
      <h2>Does the Fed-text signal add information?</h2>
      <p class="lead">Forward returns regressed on the baseline signals with and without the Fed-text features (stance, stance-change terms.</p>
      <div id="inc"></div>
    </div>
    <div class="card">
      <h2>Deflated Sharpe</h2>
      <div id="deflated"></div>
    </div>
    <div class="card">
      <h2>Contamination certificate</h2>
      <p class="lead">What was knowable when, which model was used, and what could have leaked.</p>
      <pre id="cert"></pre>
    </div>
  </details>

  <div class="foot" id="foot"></div>
</div>
<div class="tip" id="tip" role="status" aria-live="polite"></div>

<script>
const D = __DATA_JSON__;
(function () {
  'use strict';
  const $ = (s) => document.querySelector(s);
  const NS = 'http://www.w3.org/2000/svg';
  const STRAT = D.meta.strategies, BASE = D.meta.baselines, ALL = STRAT.concat(BASE);
  const NAMES = { rule: 'Fitted formula', llm_clip: 'AI, silently clipped', llm_feedback: 'AI, told which rules it broke', benchmark: 'Hold the neutral portfolio', market: 'Hold market weights', inverse_vol: 'Lowest-risk mix', sixty_forty: '60 / 40 classic' };
  const WHY = { rule: 'A regression fitted on past data only, refit every week: no hand-written rules. The floor to beat.', llm_clip: 'A language model reads the same numbers plus the Fed\'s words and gives opinions; the optimiser trims them to the rules without telling it.', llm_feedback: 'Same first opinion, but the rule-checker writes back and the model revises. The new idea.', benchmark: 'The risk-balanced neutral portfolio computed from data each week. Every view tilts away from it and every rule is measured against it.', market: 'Never changes its mind. The neutral mix every view tilts away from.', inverse_vol: 'Weights each fund by how calm it is.', sixty_forty: 'The classic simple portfolio. It ignores the bank\'s rules, so it is a familiar yardstick, not a legal book.' };
  const REGIMES = ['overheating', 'goldilocks', 'recession', 'stagflation'];
  const REGIME_SLOT = { overheating: '--s4', goldilocks: '--s6', recession: '--s7', stagflation: '--s8' };
  const STRAT_SLOT = { rule: '--s1', llm_clip: '--s2', llm_feedback: '--s3', benchmark: '--g1', market: '--g1', inverse_vol: '--g2', sixty_forty: '--g3' };
  const state = { strategy: STRAT.includes('llm_feedback') ? 'llm_feedback' : STRAT[0], range: 'all', dec: D.dates.length - 1, tables: {} };
  let CSS = {};
  function readCss() { const cs = getComputedStyle(document.documentElement); CSS = {}; ['--s1','--s2','--s3','--s4','--s5','--s6','--s7','--s8','--g1','--g2','--g3','--surface','--ink','--ink2','--muted','--grid','--axis','--wash','--seq-lo','--seq-hi','--good','--critical','--accent'].forEach(k => CSS[k] = cs.getPropertyValue(k).trim()); }
  const col = (slot) => CSS[slot];
  const scol = (s) => col(STRAT_SLOT[s]);

  const pct = (x, d) => (x == null || isNaN(x)) ? 'n/a' : (x * 100).toFixed(d == null ? 1 : d) + '%';
  const spct = (x, d) => (x == null || isNaN(x)) ? 'n/a' : (x >= 0 ? '+' : '') + (x * 100).toFixed(d == null ? 1 : d) + '%';
  const num = (x, d) => (x == null || isNaN(x)) ? 'n/a' : Number(x).toFixed(d == null ? 2 : d);
  const snum = (x, d) => (x == null || isNaN(x)) ? 'n/a' : (x >= 0 ? '+' : '') + Number(x).toFixed(d == null ? 2 : d);
  const year = (s) => s.slice(0, 4);
  function text(el, t) { el.textContent = t; return el; }
  function h(tag, cls, parent, t) { const e = document.createElement(tag); if (cls) e.className = cls; if (t != null) e.textContent = t; if (parent) parent.appendChild(e); return e; }
  function sv(tag, attrs, parent) { const e = document.createElementNS(NS, tag); for (const k in attrs) e.setAttribute(k, attrs[k]); if (parent) parent.appendChild(e); return e; }

  function mean(a) { let s = 0, n = 0; for (const x of a) if (x != null && !isNaN(x)) { s += x; n++; } return n ? s / n : NaN; }
  function std(a) { const m = mean(a); let s = 0, n = 0; for (const x of a) if (x != null && !isNaN(x)) { s += (x - m) * (x - m); n++; } return n > 1 ? Math.sqrt(s / (n - 1)) : NaN; }
  function sharpe(ex) { const sd = std(ex); return sd > 0 ? mean(ex) / sd * Math.sqrt(52) : NaN; }
  function annRet(r) { let w = 1, n = 0; for (const x of r) { w *= 1 + x; n++; } return n ? Math.pow(w, 52 / n) - 1 : NaN; }
  function wealth(r) { const out = []; let w = 1; for (const x of r) { w *= 1 + x; out.push(w); } return out; }
  function drawdown(r) { const out = []; let w = 1, peak = 1; for (const x of r) { w *= 1 + x; peak = Math.max(peak, w); out.push(w / peak - 1); } return out; }
  function maxDD(r) { return Math.min.apply(null, drawdown(r)); }
  function rollingSharpe(ex, win) { const out = new Array(ex.length).fill(null); for (let i = win - 1; i < ex.length; i++) out[i] = sharpe(ex.slice(i - win + 1, i + 1)); return out; }
  const CASH_IDX = D.meta.assets.indexOf(D.meta.cash || 'BIL');
  function turnover(W) { const out = []; for (let i = 0; i < W.length; i++) { if (i === 0) { out.push(CASH_IDX >= 0 ? 1 - (W[0][CASH_IDX] || 0) : 0.5 * W[0].reduce((a, b) => a + Math.abs(b), 0)); continue; } let s = 0; for (let j = 0; j < W[i].length; j++) s += Math.abs(W[i][j] - W[i - 1][j]); out.push(0.5 * s); } return out; }
  function niceTicks(lo, hi, n) { n = n || 5; if (!(hi > lo)) { hi = lo + 1; } const span = hi - lo; const step0 = span / n; const mag = Math.pow(10, Math.floor(Math.log10(step0))); const norm = step0 / mag; const step = (norm < 1.5 ? 1 : norm < 3 ? 2 : norm < 7 ? 5 : 10) * mag; const t = []; for (let v = Math.ceil(lo / step - 1e-9) * step; v <= hi + 1e-9; v += step) t.push(+v.toFixed(10)); return t; }

  const RANGES = [['all', 'Full run'], ['5y', 'Last 5 years'], ['3y', 'Last 3 years'], ['1y', 'Last year'], ['2020', 'Since 2020'], ['2022', 'Since 2022']];
  function rangeIdx() { const n = D.dates.length; const last = D.dates[n - 1]; let start = 0; if (state.range === '2020' || state.range === '2022') start = D.dates.findIndex(d => d >= state.range + '-01-01'); else if (state.range !== 'all') { const yrs = parseInt(state.range); const y = parseInt(last.slice(0, 4)) - yrs; start = D.dates.findIndex(d => d >= (y + last.slice(4))); } if (start < 0) start = 0; return [start, n - 1]; }
  let R0 = 0, R1 = D.dates.length - 1;
  function retSlice(name, which) { const arr = D[which][name]; return arr.slice(R0, Math.min(R1, arr.length - 1) + 1); }
  function retDates() { return D.ret_dates.slice(R0, Math.min(R1, D.ret_dates.length - 1) + 1); }
  const isFull = () => R0 === 0 && R1 === D.dates.length - 1;

  const tip = $('#tip');
  function showTip(host, x, y, dateLabel, rows) { tip.replaceChildren(); h('div', 'd', tip, dateLabel); rows.forEach(r => { const row = h('div', 'row', tip); const k = h('span', 'k', row); k.style.borderColor = r.color; h('span', 'v', row, r.value); h('span', 'n', row, r.name); }); tip.style.display = 'block'; let left = x + 14, top = y + 10; const tw = tip.offsetWidth, th = tip.offsetHeight; if (left + tw > window.innerWidth - 8) left = x - tw - 14; if (top + th > window.innerHeight - 8) top = y - th - 10; tip.style.left = (left + window.scrollX) + 'px'; tip.style.top = (top + window.scrollY) + 'px'; }
  function hideTip() { tip.style.display = 'none'; }

  function lineChart(o) {
    const host = o.el; host.replaceChildren();
    const W = Math.max(320, host.clientWidth || 640), H = o.h || 260, m = { l: 46, r: o.rightPad || 60, t: 12, b: 26 };
    const svg = sv('svg', { viewBox: `0 0 ${W} ${H}`, width: W, height: H, role: 'img' }, host);
    const n = o.xs.length; const px = (i) => m.l + (n > 1 ? i / (n - 1) : 0.5) * (W - m.l - m.r);
    let lo = Infinity, hi = -Infinity;
    o.series.forEach(s => s.values.forEach(v => { if (v != null && !isNaN(v)) { lo = Math.min(lo, v); hi = Math.max(hi, v); } }));
    if (o.y0) { lo = Math.min(lo, 0); hi = Math.max(hi, 0); }
    if (o.limit) o.limit.forEach(l => { lo = Math.min(lo, l.y); hi = Math.max(hi, l.y); });
    if (o.band) { lo = Math.min(lo, o.band[0]); hi = Math.max(hi, o.band[1]); }
    if (o.ymin != null) lo = o.ymin; if (o.ymax != null) hi = Math.max(hi, o.ymax);
    if (!(hi > lo)) { hi = lo + 1; }
    const ticks = niceTicks(lo, hi, o.nticks || 4); lo = Math.min(lo, ticks[0]); hi = Math.max(hi, ticks[ticks.length - 1]);
    const py = (v) => m.t + (1 - (v - lo) / (hi - lo)) * (H - m.t - m.b);
    if (o.band) sv('rect', { x: m.l, y: py(o.band[1]), width: W - m.l - m.r, height: py(o.band[0]) - py(o.band[1]), fill: CSS['--wash'] }, svg);
    ticks.forEach(t => { sv('line', { x1: m.l, x2: W - m.r, y1: py(t), y2: py(t), stroke: CSS['--grid'], 'stroke-width': 1 }, svg); sv('text', { x: m.l - 6, y: py(t) + 4, 'text-anchor': 'end', 'font-size': 11, fill: CSS['--muted'] }, svg).textContent = (o.yfmt || num)(t); });
    if (lo < 0 && hi > 0) sv('line', { x1: m.l, x2: W - m.r, y1: py(0), y2: py(0), stroke: CSS['--axis'], 'stroke-width': 1 }, svg);
    if (o.categorical) { o.xs.forEach((x, i) => sv('text', { x: px(i), y: H - 8, 'text-anchor': 'middle', 'font-size': 11, fill: CSS['--muted'] }, svg).textContent = x); }
    else { let lastY = ''; const yearsShown = []; o.xs.forEach((x, i) => { const y = year(x); if (y !== lastY) { yearsShown.push([i, y]); lastY = y; } }); const every = Math.ceil(yearsShown.length / Math.max(3, Math.floor((W - m.l - m.r) / 60))); yearsShown.forEach((yy, k) => { if (k % every === 0 && (k > 0 || yy[0] === 0 || n < 80)) { sv('line', { x1: px(yy[0]), x2: px(yy[0]), y1: H - m.b, y2: H - m.b + 4, stroke: CSS['--axis'] }, svg); sv('text', { x: px(yy[0]), y: H - 8, 'text-anchor': 'middle', 'font-size': 11, fill: CSS['--muted'] }, svg).textContent = yy[1]; } }); }
    (o.limit || []).forEach(l => { sv('line', { x1: m.l, x2: W - m.r, y1: py(l.y), y2: py(l.y), stroke: CSS['--ink2'], 'stroke-width': 1 }, svg); sv('text', { x: W - m.r + 4, y: py(l.y) + 4, 'font-size': 11, fill: CSS['--ink2'] }, svg).textContent = l.label; });
    o.series.forEach(s => { if (!s.area) return; let d = ''; let started = false; s.values.forEach((v, i) => { if (v == null || isNaN(v)) return; d += (started ? 'L' : 'M') + px(i).toFixed(1) + ' ' + py(v).toFixed(1) + ' '; started = true; }); if (!started) return; const first = s.values.findIndex(v => v != null && !isNaN(v)); let lastI = s.values.length - 1; while (lastI > 0 && (s.values[lastI] == null || isNaN(s.values[lastI]))) lastI--; const base = py(Math.max(lo, Math.min(0, hi))); d += `L${px(lastI).toFixed(1)} ${base} L${px(first).toFixed(1)} ${base} Z`; sv('path', { d, fill: s.color, 'fill-opacity': 0.10 }, svg); });
    const ordered = o.series.slice().sort((a, b) => (a.emph ? 1 : 0) - (b.emph ? 1 : 0));
    ordered.forEach(s => { let d = '', started = false; s.values.forEach((v, i) => { if (v == null || isNaN(v)) { started = false; return; } d += (started ? 'L' : 'M') + px(i).toFixed(1) + ' ' + py(v).toFixed(1) + ' '; started = true; }); sv('path', { d, fill: 'none', stroke: s.color, 'stroke-width': s.emph ? 2.5 : (s.thin ? 1.5 : 2), 'stroke-linejoin': 'round', 'stroke-linecap': 'round', 'stroke-opacity': s.dim ? 0.85 : 1 }, svg); });
    const labelAll = o.series.length <= 3; const placed = [];
    o.series.forEach(s => { if (!(s.emph || labelAll) || o.noEndLabel) return; let li = s.values.length - 1; while (li >= 0 && (s.values[li] == null || isNaN(s.values[li]))) li--; if (li < 0) return; const x = px(li), y = py(s.values[li]); sv('circle', { cx: x, cy: y, r: 6, fill: CSS['--surface'] }, svg); sv('circle', { cx: x, cy: y, r: 4, fill: s.color }, svg); let ly = y; placed.forEach(p => { if (Math.abs(p - ly) < 13) ly = p + 13; }); placed.push(ly); if (ly !== y) sv('line', { x1: x + 6, y1: y, x2: x + 10, y2: ly, stroke: CSS['--axis'] }, svg); sv('text', { x: x + 12, y: ly + 4, 'font-size': 11, 'font-weight': 600, fill: CSS['--ink'] }, svg).textContent = (o.yfmt || num)(s.values[li]); });
    const hair = sv('line', { x1: 0, x2: 0, y1: m.t, y2: H - m.b, stroke: CSS['--axis'], 'stroke-width': 1, visibility: 'hidden' }, svg);
    const dots = o.series.map(s => sv('circle', { r: 4, fill: s.color, stroke: CSS['--surface'], 'stroke-width': 2, visibility: 'hidden' }, svg));
    const hit = sv('rect', { x: m.l, y: m.t, width: W - m.l - m.r, height: H - m.t - m.b, fill: 'transparent' }, svg);
    hit.setAttribute('tabindex', '0'); hit.setAttribute('aria-label', (o.title || 'chart') + ': hover or use arrow keys to read values');
    let focusI = n - 1;
    function at(i, clientX, clientY) { i = Math.max(0, Math.min(n - 1, i)); const x = px(i); hair.setAttribute('x1', x); hair.setAttribute('x2', x); hair.setAttribute('visibility', 'visible'); const rows = []; o.series.forEach((s, k) => { const v = s.values[i]; if (v == null || isNaN(v)) { dots[k].setAttribute('visibility', 'hidden'); return; } dots[k].setAttribute('cx', x); dots[k].setAttribute('cy', py(v)); dots[k].setAttribute('visibility', 'visible'); rows.push({ color: s.color, value: (o.yfmt || num)(v), name: s.name }); }); showTip(host, clientX, clientY, o.xs[i], rows); }
    hit.addEventListener('pointermove', (ev) => { const r = svg.getBoundingClientRect(); const fx = (ev.clientX - r.left) * (W / r.width); const i = Math.round((fx - m.l) / (W - m.l - m.r) * (n - 1)); focusI = i; at(i, ev.clientX, ev.clientY); });
    hit.addEventListener('pointerleave', () => { hair.setAttribute('visibility', 'hidden'); dots.forEach(d => d.setAttribute('visibility', 'hidden')); hideTip(); });
    hit.addEventListener('keydown', (ev) => { if (ev.key === 'ArrowLeft') focusI--; else if (ev.key === 'ArrowRight') focusI++; else if (ev.key === 'Home') focusI = 0; else if (ev.key === 'End') focusI = n - 1; else return; ev.preventDefault(); const r = svg.getBoundingClientRect(); focusI = Math.max(0, Math.min(n - 1, focusI)); at(focusI, r.left + px(focusI) * r.width / W, r.top + 30); });
    hit.addEventListener('blur', () => { hair.setAttribute('visibility', 'hidden'); dots.forEach(d => d.setAttribute('visibility', 'hidden')); hideTip(); });
    if (o.legend !== false && o.series.length > 1) { const lg = h('div', 'legend', host); o.series.forEach(s => { const it = h('span', null, lg); const k = h('span', 'k' + (s.area ? ' rect' : ''), it); k.style.borderColor = s.color; if (s.area) k.style.background = s.color; it.appendChild(document.createTextNode(s.name)); }); }
    return svg;
  }

  function stackedArea(o) {
    const host = o.el; host.replaceChildren();
    const W = Math.max(320, host.clientWidth || 640), H = o.h || 240, m = { l: 40, r: 16, t: 10, b: 26 };
    const svg = sv('svg', { viewBox: `0 0 ${W} ${H}`, width: W, height: H, role: 'img' }, host);
    const n = o.xs.length; const px = (i) => m.l + (n > 1 ? i / (n - 1) : 0.5) * (W - m.l - m.r); const py = (v) => m.t + (1 - v) * (H - m.t - m.b);
    [0, 0.25, 0.5, 0.75, 1].forEach(t => { sv('line', { x1: m.l, x2: W - m.r, y1: py(t), y2: py(t), stroke: CSS['--grid'] }, svg); sv('text', { x: m.l - 6, y: py(t) + 4, 'text-anchor': 'end', 'font-size': 11, fill: CSS['--muted'] }, svg).textContent = Math.round(t * 100) + '%'; });
    let lastY = ''; o.xs.forEach((x, i) => { const y = year(x); if (y !== lastY && (i === 0 || parseInt(y) % Math.ceil(n / 400) === 0 || n < 120)) { sv('text', { x: px(i), y: H - 8, 'text-anchor': 'middle', 'font-size': 11, fill: CSS['--muted'] }, svg).textContent = y; lastY = y; } else if (y !== lastY) lastY = y; });
    const cum = new Array(n).fill(0);
    o.series.forEach(s => { let top = '', bot = ''; for (let i = 0; i < n; i++) { const b = cum[i], t = cum[i] + (s.values[i] || 0); top += (i ? 'L' : 'M') + px(i).toFixed(1) + ' ' + py(t).toFixed(1) + ' '; bot = 'L' + px(i).toFixed(1) + ' ' + py(b).toFixed(1) + ' ' + bot; cum[i] = t; } sv('path', { d: top + bot + 'Z', fill: s.color, 'fill-opacity': 0.85, stroke: CSS['--surface'], 'stroke-width': 1.5, 'stroke-linejoin': 'round' }, svg); });
    const hair = sv('line', { y1: m.t, y2: H - m.b, stroke: CSS['--ink2'], visibility: 'hidden' }, svg);
    const hit = sv('rect', { x: m.l, y: m.t, width: W - m.l - m.r, height: H - m.t - m.b, fill: 'transparent' }, svg); hit.setAttribute('tabindex', '0');
    function at(i, cx, cy) { i = Math.max(0, Math.min(n - 1, i)); hair.setAttribute('x1', px(i)); hair.setAttribute('x2', px(i)); hair.setAttribute('visibility', 'visible'); showTip(host, cx, cy, o.xs[i] + (o.labels ? '  ' + o.labels[i] : ''), o.series.map(s => ({ color: s.color, value: pct(s.values[i], 0), name: s.name }))); }
    hit.addEventListener('pointermove', (ev) => { const r = svg.getBoundingClientRect(); const fx = (ev.clientX - r.left) * (W / r.width); at(Math.round((fx - m.l) / (W - m.l - m.r) * (n - 1)), ev.clientX, ev.clientY); });
    hit.addEventListener('pointerleave', () => { hair.setAttribute('visibility', 'hidden'); hideTip(); });
    const lg = h('div', 'legend', host); o.series.forEach(s => { const it = h('span', null, lg); const k = h('span', 'k rect', it); k.style.background = s.color; it.appendChild(document.createTextNode(s.name)); });
  }

  function hbars(o) {
    const host = o.el; host.replaceChildren();
    const W = Math.max(320, host.clientWidth || 560); const rowH = 14 * o.series.length + 10; const H = o.cats.length * rowH + 30; const m = { l: 110, r: 40, t: 6, b: 22 };
    const svg = sv('svg', { viewBox: `0 0 ${W} ${H}`, width: W, height: H, role: 'img' }, host);
    let lo = 0, hi = 0; o.series.forEach(s => s.values.forEach(v => { lo = Math.min(lo, v); hi = Math.max(hi, v); })); const ticks = niceTicks(lo, hi, 5); lo = Math.min(lo, ticks[0]); hi = Math.max(hi, ticks[ticks.length - 1]);
    const px = (v) => m.l + (v - lo) / (hi - lo) * (W - m.l - m.r);
    ticks.forEach(t => { sv('line', { x1: px(t), x2: px(t), y1: m.t, y2: H - m.b, stroke: CSS['--grid'] }, svg); sv('text', { x: px(t), y: H - 6, 'text-anchor': 'middle', 'font-size': 11, fill: CSS['--muted'] }, svg).textContent = num(t, 2); });
    sv('line', { x1: px(0), x2: px(0), y1: m.t, y2: H - m.b, stroke: CSS['--axis'] }, svg);
    o.cats.forEach((c, ci) => { const y0 = m.t + ci * rowH + 4; sv('text', { x: m.l - 8, y: y0 + rowH / 2, 'text-anchor': 'end', 'font-size': 12, fill: CSS['--ink2'] }, svg).textContent = c; o.series.forEach((s, si) => { const v = s.values[ci]; const y = y0 + si * 14; const x0 = px(Math.min(0, v)), x1 = px(Math.max(0, v)); const r = sv('rect', { x: x0, y, width: Math.max(0.5, x1 - x0), height: 12, fill: s.color, rx: 3 }, svg); r.addEventListener('pointermove', (ev) => showTip(host, ev.clientX, ev.clientY, c, [{ color: s.color, value: snum(v, 2), name: s.name }])); r.addEventListener('pointerleave', hideTip); }); });
    const lg = h('div', 'legend', host); o.series.forEach(s => { const it = h('span', null, lg); const k = h('span', 'k rect', it); k.style.background = s.color; it.appendChild(document.createTextNode(s.name)); });
  }

  function columns(o) {
    const host = o.el; host.replaceChildren();
    const W = Math.max(320, host.clientWidth || 560), H = o.h || 220, m = { l: 36, r: 12, t: 10, b: 26 };
    const svg = sv('svg', { viewBox: `0 0 ${W} ${H}`, width: W, height: H, role: 'img' }, host);
    const n = o.cats.length; const bw = Math.min(24, (W - m.l - m.r) / n - 4); const px = (i) => m.l + (i + 0.5) * (W - m.l - m.r) / n;
    let hi = 0; o.series.forEach(s => s.values.forEach(v => hi = Math.max(hi, v))); const ticks = niceTicks(0, hi, 4); hi = Math.max(hi, ticks[ticks.length - 1]);
    const py = (v) => m.t + (1 - v / hi) * (H - m.t - m.b);
    ticks.forEach(t => { sv('line', { x1: m.l, x2: W - m.r, y1: py(t), y2: py(t), stroke: CSS['--grid'] }, svg); sv('text', { x: m.l - 6, y: py(t) + 4, 'text-anchor': 'end', 'font-size': 11, fill: CSS['--muted'] }, svg).textContent = t; });
    o.cats.forEach((c, i) => { if (i % Math.ceil(n / 12) === 0) sv('text', { x: px(i), y: H - 8, 'text-anchor': 'middle', 'font-size': 10.5, fill: CSS['--muted'] }, svg).textContent = c; o.series.forEach((s, k) => { const v = s.values[i]; if (!v) return; const w = k === 0 ? bw : bw - 4; const r = sv('rect', { x: px(i) - w / 2, y: py(v), width: w, height: py(0) - py(v), fill: s.color, rx: 3 }, svg); r.addEventListener('pointermove', (ev) => showTip(host, ev.clientX, ev.clientY, c, o.series.map(ss => ({ color: ss.color, value: String(ss.values[i]), name: ss.name })))); r.addEventListener('pointerleave', hideTip); }); });
    const lg = h('div', 'legend', host); o.series.forEach(s => { const it = h('span', null, lg); const k = h('span', 'k rect', it); k.style.background = s.color; it.appendChild(document.createTextNode(s.name)); });
  }

  function table(hostId, xs, cols, xname) { const host = document.getElementById(hostId); host.replaceChildren(); if (!state.tables[hostId]) return; const t = h('table', null, host); const tr = h('tr', null, h('thead', null, t)); h('th', null, tr, xname || 'date'); cols.forEach(c => h('th', null, tr, c.name)); const tb = h('tbody', null, t); xs.forEach((x, i) => { const r = h('tr', null, tb); h('td', null, r, x); cols.forEach(c => h('td', null, r, (c.fmt || num)(c.values[i]))); }); }

  // ------------------------------------------------------------ narrative helpers
  const cmpKey = (a, b) => `${a} - ${b}`;
  function comparison(a, b) { const C = D.summary.comparisons || {}; if (C[cmpKey(a, b)]) return { diff: C[cmpKey(a, b)].diff, p: C[cmpKey(a, b)].p_value, sign: 1 }; if (C[cmpKey(b, a)]) return { diff: -C[cmpKey(b, a)].diff, p: C[cmpKey(b, a)].p_value, sign: -1 }; return null; }
  function luck(p) { if (p == null || isNaN(p)) return 'no luck check on this sample'; if (p < 0.05) return `probably not luck (p = ${num(p, 3)})`; if (p < 0.2) return `suggestive but not conclusive (p = ${num(p, 2)})`; return `within what luck produces (p = ${num(p, 2)})`; }

  function renderHeader() {
    const mm = D.meta.model || {}; const isMock = mm.provider === 'mock';
    text($('#runline'), `Run ${D.meta.run_id} · ${D.meta.dates.first} to ${D.meta.dates.last} · ${D.meta.dates.count} weekly decisions · reasoning model: ${isMock ? 'a deterministic stand-in (no language model; tests the machinery, not intelligence)' : mm.model + ', decisions dated after its training cutoff cannot be memorised'}`);
    const pl = $('#playersList'); pl.replaceChildren();
    STRAT.concat(BASE).forEach(s => { const li = h('li', null, pl); const sw = h('span', 'sw', li); sw.style.background = scol(s); const d = h('div', null, li); h('b', null, d, NAMES[s] + (BASE.includes(s) ? ' (yardstick)' : '')); h('span', 'why', d, WHY[s]); });
    const rs = $('#rangeSeg'); rs.replaceChildren(); RANGES.forEach(r => { const b = h('button', null, rs, r[1]); b.type = 'button'; b.setAttribute('aria-pressed', state.range === r[0]); b.onclick = () => { state.range = r[0]; renderAll(); }; });
    const ss = $('#stratSeg'); ss.replaceChildren(); STRAT.forEach(s => { const b = h('button', null, ss); b.type = 'button'; const dot = h('span', 'dot', b); dot.style.background = scol(s); b.appendChild(document.createTextNode(NAMES[s])); b.setAttribute('aria-pressed', state.strategy === s); b.onclick = () => { state.strategy = s; renderAll(); }; });
    text($('#rangeNote'), `${D.dates[R0]} to ${D.dates[R1]} · ${R1 - R0 + 1} decisions`);
  }

  function perf(name) { const g = retSlice(name, 'gross'), ex = retSlice(name, 'excess'); const W = D.weights[name].slice(R0, R1 + 1); const to = turnover(W); const net30 = ex.map((x, i) => x - (to[i] || 0) * 30 / 1e4); return { ret: annRet(g), vol: std(g) * Math.sqrt(52), sharpe: sharpe(ex), dd: maxDD(g), to: mean(to), s30: sharpe(net30), wealth: wealth(g) }; }

  function renderVerdict() {
    const s = state.strategy; const P = {}; ALL.forEach(n => P[n] = perf(n));
    text($('#vTitle'), `The verdict for "${NAMES[s]}"`);
    const hero = $('#heroNum'); text(hero, num(P[s].sharpe, 2)); hero.style.color = scol(s);
    const ul = $('#verdicts'); ul.replaceChildren();
    function line(other, label) { if (!(other in P) || other === s) return; const d = P[s].sharpe - P[other].sharpe; const c = isFull() ? comparison(s, other) : null; const li = h('li', null, ul); const tag = h('span', 'tag ' + (d > 0.05 ? 'good' : d < -0.05 ? 'bad' : ''), li, d > 0.05 ? 'ahead' : d < -0.05 ? 'behind' : 'level'); void tag; li.appendChild(document.createTextNode(`${label}: ${snum(d, 2)} reward per unit of risk` + (c ? `, ${luck(c.p)}` : isFull() ? '' : ' (luck check available on the full run only)') + '.')); }
    if (s !== 'rule') line('rule', 'Against the formula');
    if (s === 'llm_feedback') line('llm_clip', 'Against the same AI silently clipped');
    if (s === 'llm_clip') line('llm_feedback', 'Against the same AI told which rules it broke');
    if (s === 'rule') { line('llm_clip', 'Against the AI silently clipped'); line('llm_feedback', 'Against the AI told which rules it broke'); }
    line('benchmark', 'Against simply holding the neutral portfolio');
    line('sixty_forty', 'Against the 60 / 40 classic (which ignores the bank\'s rules)');
    const decs = D.decisions[s].slice(R0, R1 + 1).filter(Boolean); const viol = decs.filter(d => d.fv > 0).length;
    const li = h('li', null, ul); h('span', 'tag ' + (viol ? 'bad' : 'good'), li, viol ? 'rules broken' : 'rules kept'); li.appendChild(document.createTextNode(viol ? `${viol} executed portfolios broke a rule.` : `Every one of the ${decs.length} executed portfolios passed the rule-checker.`));
    const li2 = h('li', null, ul); h('span', 'tag', li2, 'costs'); li2.appendChild(document.createTextNode(`Traded ${pct(P[s].to, 1)} of the book per week. After a 0.3% cost on every unit traded the score is ${num(P[s].s30, 2)} (formula ${num(P['rule'].s30, 2)}, neutral portfolio ${num(P['benchmark'] ? P['benchmark'].s30 : NaN, 2)}).`));
    text($('#verdictNote'), isFull() ? 'Luck checks come from a paired block bootstrap over the full run.' : 'Luck checks are computed on the full run only; the numbers above are for the selected period.');
    return P;
  }

  function seriesFor(names, fn, emphasize) { return names.map(nm => ({ name: NAMES[nm] || nm, color: scol(nm), values: fn(nm), emph: emphasize ? nm === state.strategy : false, dim: BASE.includes(nm), thin: BASE.includes(nm) })); }

  function renderGrowth(P) {
    const xs = retDates(); const ser = seriesFor(ALL, (nm) => P[nm].wealth, true);
    const s = state.strategy; const end = (n) => P[n].wealth[P[n].wealth.length - 1];
    const tk = $('#growthTake'); tk.replaceChildren(); tk.appendChild(document.createTextNode('One dollar became ')); h('b', null, tk, `$${num(end(s), 2)}`); tk.appendChild(document.createTextNode(` for "${NAMES[s]}", $${num(end('rule'), 2)} for the formula, and $${num(end('benchmark'), 2)} just holding the neutral portfolio. That is ${spct(P[s].ret, 1)} a year at ${pct(P[s].vol, 1)} volatility.`));
    lineChart({ el: $('#growth'), xs, series: ser, yfmt: (v) => '$' + num(v, 2), h: 300, title: 'growth of one dollar' });
    table('growth-tbl', xs, ser.map(s => ({ name: s.name, values: s.values, fmt: (v) => num(v, 3) })));
  }
  function renderDD(P) {
    const xs = retDates(); const ser = seriesFor(ALL, (nm) => drawdown(retSlice(nm, 'gross')), true);
    const s = state.strategy; const tk = $('#ddTake'); tk.replaceChildren(); tk.appendChild(document.createTextNode('Worst fall from a peak: ')); h('b', null, tk, pct(P[s].dd, 1)); tk.appendChild(document.createTextNode(` for "${NAMES[s]}", ${pct(P['rule'].dd, 1)} for the formula, ${pct(P['benchmark'].dd, 1)} for the neutral portfolio, ${pct(P['sixty_forty'].dd, 1)} for 60 / 40.`));
    lineChart({ el: $('#dd'), xs, series: ser, yfmt: (v) => pct(v, 0), y0: true, h: 230, title: 'drawdown' });
    table('dd-tbl', xs, ser.map(s => ({ name: s.name, values: s.values, fmt: (v) => pct(v, 1) })));
  }
  function renderIdea(P) {
    const decs = D.decisions['llm_feedback'] || []; const q = {}; const order = []; let nb = 0, nr = 0, nd = 0;
    for (let i = R0; i <= R1; i++) { const d = decs[i]; if (!d) continue; nd++; const key = D.dates[i].slice(0, 4) + ' Q' + (Math.floor((parseInt(D.dates[i].slice(5, 7)) - 1) / 3) + 1); if (!q[key]) { q[key] = { n: 0, b: 0, r: 0 }; order.push(key); } q[key].n++; if (d.bf.length) { q[key].b++; nb++; } if (d.h.length && !d.bl.length) { q[key].r++; nr++; } }
    const st = $('#ideaStats'); st.replaceChildren();
    if (!order.length) { $('#ideaCard').hidden = true; return; }
    [[String(nb) + ' of ' + nd, 'weeks the first proposal hit a rule'], [String(nr), 'weeks the revision cleared every rule'], [snum((P['llm_feedback'] && P['llm_clip']) ? P['llm_feedback'].sharpe - P['llm_clip'].sharpe : NaN, 2), 'reward per risk, told vs clipped'], [pct(P['llm_feedback'] ? P['llm_feedback'].to : NaN, 1) + ' vs ' + pct(P['llm_clip'] ? P['llm_clip'].to : NaN, 1), 'book traded per week, told vs clipped']].forEach(x => { const d = h('div', null, st); h('div', 'v', d, x[0]); h('div', 'l', d, x[1]); });
    const c = comparison('llm_feedback', 'llm_clip'); const tk = $('#ideaTake'); tk.replaceChildren();
    if (P['llm_feedback'] && P['llm_clip']) { const d = P['llm_feedback'].sharpe - P['llm_clip'].sharpe; tk.appendChild(document.createTextNode('Being told which rule it broke ')); h('b', null, tk, d > 0.05 ? 'improved' : d < -0.05 ? 'hurt' : 'did not change'); tk.appendChild(document.createTextNode(` the AI's reward per unit of risk by ${snum(d, 2)}${c && isFull() ? ', ' + luck(c.p) : ''}. It also changed how much it trades, which the cost line in the verdict prices in.`)); }
    columns({ el: $('#fb'), cats: order, series: [{ name: 'first proposal hit a rule', color: CSS['--seq-lo'], values: order.map(k => q[k].b) }, { name: 'revision cleared every rule', color: CSS['--seq-hi'], values: order.map(k => q[k].r) }], h: 220 });
    table('fb-tbl', order, [{ name: 'decisions', values: order.map(k => q[k].n), fmt: String }, { name: 'hit a rule', values: order.map(k => q[k].b), fmt: String }, { name: 'cleared by revision', values: order.map(k => q[k].r), fmt: String }], 'quarter');
    // example: most recent week in range with a revision that cleared everything, else with any revision
    let ex = null; for (let i = R1; i >= R0; i--) { const d = decs[i]; if (d && d.h.length && !d.bl.length) { ex = [i, d]; break; } } if (!ex) for (let i = R1; i >= R0; i--) { const d = decs[i]; if (d && d.h.length) { ex = [i, d]; break; } }
    const box = $('#ideaExample'); box.replaceChildren();
    if (!ex) { h('p', 'quiet', box, 'No revision in this period.'); return; }
    const [i, d] = ex; h('p', 'quiet', box, `Week of ${D.dates[i]}`);
    h('div', null, box, 'The rule-checker wrote:'); const ul = h('ul', null, box); ul.style.margin = '4px 0 10px'; (d.bm || []).forEach(m => h('li', null, ul, m));
    const before = (D.decisions['llm_clip'] && D.decisions['llm_clip'][i]) ? D.decisions['llm_clip'][i].v : []; const after = d.v;
    const t = h('table', null, box); const tr = h('tr', null, h('thead', null, t)); ['fund', 'before', 'after'].forEach(x => h('th', null, tr, x)); const tb = h('tbody', null, t);
    const assets = Array.from(new Set(before.map(v => v[0]).concat(after.map(v => v[0]))));
    assets.forEach(a => { const b = before.find(v => v[0] === a), af = after.find(v => v[0] === a); const r = h('tr', null, tb); h('td', null, r, a); h('td', null, r, b ? `${spct(b[2], 1)} @ ${num(b[3], 2)}` : '–'); h('td', null, r, af ? `${spct(af[2], 1)} @ ${num(af[3], 2)}` : 'dropped'); });
    h('p', 'quiet', box, d.bl.length ? `After revision, still binding: ${d.bl.join(', ')}.` : 'After revision, nothing binds: the revised views are implementable as stated.');
  }
  function renderAlloc() {
    text($('#allocTitle'), `What did "${NAMES[state.strategy]}" hold?`);
    const box = $('#alloc'); box.replaceChildren(); const xs = D.dates.slice(R0, R1 + 1); const W = D.weights[state.strategy].slice(R0, R1 + 1);
    const cols = []; const last = W[W.length - 1] || [];
    const top = D.meta.assets.map((a, j) => [a, last[j] || 0]).sort((x, y) => y[1] - x[1]).filter(x => x[1] > 0.02).slice(0, 4);
    const tk = $('#allocTake'); tk.replaceChildren(); tk.appendChild(document.createTextNode(`On ${xs[xs.length - 1]} it held mostly `)); h('b', null, tk, top.map(x => `${(D.meta.asset_meta[x[0]] || {}).label || x[0]} ${pct(x[1], 0)}`).join(', ')); tk.appendChild(document.createTextNode('.'));
    D.meta.assets.forEach((a, j) => { const vals = W.map(r => r[j]); cols.push({ name: a, values: vals, fmt: (v) => pct(v, 1) }); const card = h('div', 'small', box); const hd = h('h4', null, card); text(hd, ((D.meta.asset_meta[a] || {}).label || a)); h('span', 'cur', hd, pct(vals[vals.length - 1], 1)); const ch = h('div', 'chart', card); lineChart({ el: ch, xs, series: [{ name: a, color: CSS['--s1'], values: vals, area: true }], yfmt: (v) => pct(v, 0), y0: true, ymax: D.meta.caps[a] || 0.3, h: 110, nticks: 2, rightPad: 44, legend: false, title: a + ' weight', limit: D.meta.caps[a] ? [{ y: D.meta.caps[a], label: 'cap' }] : [] }); });
    table('alloc-tbl', xs, cols);
  }
  function renderCons() {
    text($('#consTitle'), `Did "${NAMES[state.strategy]}" stay inside the rules?`);
    const box = $('#cons'); box.replaceChildren(); const xs = D.dates.slice(R0, R1 + 1); const c = D.cons[state.strategy]; const L = D.meta.limits || {};
    const panels = [['Risk (volatility) against the ceiling', c.vol.slice(R0, R1 + 1), (v) => pct(v, 1), L.vol != null ? [{ y: L.vol, label: 'ceiling ' + pct(L.vol, 0) }] : [], null], ['Interest-rate sensitivity (duration, years) inside its band', c.dur.slice(R0, R1 + 1), (v) => num(v, 1), [], (L.dur_lo != null) ? [L.dur_lo, L.dur_hi] : null], ['Capital used against the budget', c.rw.slice(R0, R1 + 1), (v) => num(v, 2), L.rw != null ? [{ y: L.rw, label: 'budget ' + num(L.rw, 2) }] : [], null]];
    const cols = [];
    panels.forEach(p => { const card = h('div', 'small', box); const hd = h('h4', null, card, p[0]); h('span', 'cur', hd, p[2](p[1][p[1].length - 1])); const ch = h('div', 'chart', card); lineChart({ el: ch, xs, series: [{ name: p[0], color: CSS['--s1'], values: p[1], area: true }], yfmt: p[2], y0: true, h: 140, nticks: 3, rightPad: 74, legend: false, limit: p[3], band: p[4], title: p[0] }); cols.push({ name: p[0], values: p[1], fmt: p[2] }); });
    table('cons-tbl', xs, cols);
    const decs = D.decisions[state.strategy].slice(R0, R1 + 1).filter(Boolean); const viol = decs.filter(d => d.fv > 0).length; const relaxed = decs.filter(d => d.rt).length;
    const tk = $('#consNote'); tk.replaceChildren(); h('b', null, tk, viol === 0 ? 'Rule-checker: no violations' : `Rule-checker: ${viol} violations`); tk.appendChild(document.createTextNode(` across ${decs.length} executed portfolios.` + (relaxed ? ` The weekly trading cap had to be relaxed ${relaxed} time${relaxed === 1 ? '' : 's'} to satisfy the other rules; that is recorded.` : ' The weekly trading cap never had to be relaxed.')));
  }
  function renderRegime() { const xs = D.dates.slice(R0, R1 + 1); const ser = REGIMES.map(r => ({ name: r, color: col(REGIME_SLOT[r]), values: (D.panel['p_' + r] || []).slice(R0, R1 + 1) })); stackedArea({ el: $('#regime'), xs, series: ser, labels: D.regime.slice(R0, R1 + 1), h: 230 }); table('regime-tbl', xs, ser.map(s => ({ name: s.name, values: s.values, fmt: (v) => pct(v, 0) }))); }
  function renderThemes() { const box = $('#themes'); box.replaceChildren(); const xs = D.dates.slice(R0, R1 + 1); const cols = []; ['growth', 'inflation', 'policy', 'financial'].forEach(t => { const vals = (D.panel['theme_' + t] || []).slice(R0, R1 + 1); cols.push({ name: t, values: vals, fmt: (v) => snum(v, 2) }); const card = h('div', 'small', box); const hd = h('h4', null, card, t); h('span', 'cur', hd, snum(vals[vals.length - 1], 2)); const ch = h('div', 'chart', card); lineChart({ el: ch, xs, series: [{ name: t, color: CSS['--s1'], values: vals, area: true }], yfmt: (v) => snum(v, 1), y0: true, h: 100, nticks: 2, rightPad: 40, legend: false, title: t + ' z-score' }); }); table('themes-tbl', xs, cols); }
  function renderRS() { const xs = retDates(); const ser = seriesFor(ALL, (nm) => { const full = rollingSharpe(D.excess[nm], 52); return full.slice(R0, Math.min(R1, full.length - 1) + 1); }, true); lineChart({ el: $('#rs'), xs, series: ser, yfmt: (v) => num(v, 1), y0: true, h: 230, title: 'rolling Sharpe' }); table('rs-tbl', xs, ser.map(s => ({ name: s.name, values: s.values, fmt: (v) => num(v, 2) }))); }
  function renderCost() { const grid = [0, 5, 10, 20, 30]; const xs = grid.map(b => b + ' bp'); const ser = ALL.map(nm => { const ex = retSlice(nm, 'excess'); const to = turnover(D.weights[nm].slice(R0, R1 + 1)); return { name: NAMES[nm], color: scol(nm), values: grid.map(b => sharpe(ex.map((x, i) => x - (to[i] || 0) * b / 1e4))), emph: nm === state.strategy, dim: BASE.includes(nm), thin: BASE.includes(nm) }; }); lineChart({ el: $('#cost'), xs, series: ser, categorical: true, yfmt: (v) => num(v, 2), y0: true, h: 220, rightPad: 40, title: 'Sharpe vs cost' }); table('cost-tbl', xs, ser.map(s => ({ name: s.name, values: s.values, fmt: (v) => num(v, 2) })), 'one-way cost'); }
  function renderAttr() {
    const A = D.summary.attribution || {}; const names = STRAT.filter(s => A[s]); if (!names.length) return; const factors = Object.keys(A[names[0]].betas || {});
    const FL = { MKT: 'stock market', DUR: 'long bonds', CRD: 'credit', CMD: 'commodities', USD: 'the dollar' };
    hbars({ el: $('#attr'), cats: factors.map(f => 'exposure to ' + (FL[f] || f)), series: names.map(s => ({ name: NAMES[s], color: scol(s), values: factors.map(f => A[s].betas[f]) })) });
    const s = state.strategy; const a = A[s]; if (a) { const vs = a.variance_share || {}; const cv = vs.covariance || 0; text($('#attrNote'), `For "${NAMES[s]}" over the full run: ${pct(vs.market, 0)} of the variation came from owning the market, ${pct(vs.style, 0)} from known tilts, and ${pct(vs.residual, 0)} is unexplained by either, which is where any skill would live${Math.abs(cv) > 0.005 ? ` (an overlap term of ${spct(cv, 0)} makes the parts sum to 100%)` : ''}. Unexplained return: ${spct(a.alpha_annual, 1)} a year, t = ${num(a.alpha_t_hac, 1)} (above 2 in size counts as clear).`); }
    const host = document.getElementById('attr-tbl'); host.replaceChildren(); if (state.tables['attr-tbl']) { const t = h('table', null, host); const tr = h('tr', null, h('thead', null, t)); ['player', 'unexplained / yr', 't', 'R²', 'market', 'tilts', 'covariance', 'unexplained'].forEach(x => h('th', null, tr, x)); const tb = h('tbody', null, t); ALL.filter(x => A[x]).forEach(x => { const r = h('tr', null, tb); h('td', null, r, NAMES[x]); h('td', null, r, spct(A[x].alpha_annual, 1)); h('td', null, r, num(A[x].alpha_t_hac, 2)); h('td', null, r, num(A[x].r2, 2)); const vs = A[x].variance_share || {}; h('td', null, r, pct(vs.market, 0)); h('td', null, r, pct(vs.style, 0)); h('td', null, r, spct(vs.covariance || 0, 0)); h('td', null, r, pct(vs.residual, 0)); }); }
  }
  function renderStats() {
    const box = $('#stats'); box.replaceChildren(); const C = D.summary.comparisons || {};
    const t = h('table', null, box); const tr = h('tr', null, h('thead', null, t)); ['comparison', 'difference', 'reads as'].forEach(x => h('th', null, tr, x)); const tb = h('tbody', null, t);
    Object.keys(C).forEach(k => { const c = C[k]; const r = h('tr', null, tb); const parts = k.split(' - '); h('td', 'txt', r, `${NAMES[parts[0]] || parts[0]} minus ${NAMES[parts[1]] || parts[1]}`); h('td', null, r, snum(c.diff, 2)); h('td', 'txt', r, luck(c.p_value)); });
    const Dd = D.summary.deflated || {}; const box2 = $('#deflated'); box2.replaceChildren(); const t2 = h('table', null, box2); const tr2 = h('tr', null, h('thead', null, t2)); ['player', 'Sharpe', 'variants tried', 'probability it beats the best of that many lucky tries'].forEach(x => h('th', null, tr2, x)); const tb2 = h('tbody', null, t2); ALL.filter(s => Dd[s]).forEach(s => { const d = Dd[s]; const r = h('tr', null, tb2); h('td', null, r, NAMES[s]); h('td', null, r, num(d.sharpe_annual, 2)); h('td', null, r, String(d.n_trials)); h('td', null, r, num(d.deflated_sharpe_prob, 2)); }); const dp = D.summary.deflated_inputs; if (dp) h('p', 'quiet', box2, `Uses the ${dp.n_trials} strategies actually run and the Sharpe spread measured across them (${num(dp.sr_dispersion_annual_measured, 2)} a year): no assumed prior.`);
  }
  function renderInc() { const box = $('#inc'); box.replaceChildren(); const rows = D.summary.incremental_test || []; if (!rows.length) { h('p', 'quiet', box, 'Not enough data for the test.'); return; } const t = h('table', null, box); const tr = h('tr', null, h('thead', null, t)); ['target', 'horizon (weeks)', 'n', 'adj R² baseline', 'adj R² with our signal', 'gain', 't (stance)', 't (stance change)', 't (novelty)'].forEach(x => h('th', null, tr, x)); const tb = h('tbody', null, t); rows.forEach(r => { const tr2 = h('tr', null, tb); h('td', null, tr2, r.target); h('td', null, tr2, String(r.horizon_weeks)); h('td', null, tr2, String(r.n)); h('td', null, tr2, num(r.adj_r2_baseline, 3)); h('td', null, tr2, num(r.adj_r2_augmented, 3)); h('td', null, tr2, snum(r.delta_adj_r2, 3)); h('td', null, tr2, num(r.t_fed_stance, 2)); h('td', null, tr2, num(r.t_fed_stance_change, 2)); h('td', null, tr2, num(r.t_fed_novelty, 2)); }); }

  function renderExplorer() {
    const sl = $('#scrub'); sl.min = R0; sl.max = R1; if (state.dec < R0 || state.dec > R1) state.dec = R1; sl.value = state.dec;
    const i = state.dec; text($('#scrubDate'), D.dates[i]);
    const L = $('#exLeft'), Rt = $('#exRight'); L.replaceChildren(); Rt.replaceChildren();
    const s = state.strategy; const dec = D.decisions[s][i]; const ft = D.fed_text[i] || {};
    const ctx = h('div', null, L);
    const rg = h('div', null, ctx); h('h3', null, rg, 'Which economic season the signals pointed to'); const bars = h('div', 'bars wide', rg);
    REGIMES.forEach(r => { const p = (D.panel['p_' + r] || [])[i] || 0; const row = h('div', 'bar', bars); h('span', 't', row, r); const track = h('div', null, row); const b = h('div', 'b', track); b.style.width = (p * 100).toFixed(0) + '%'; b.style.background = col(REGIME_SLOT[r]); h('span', 'v', row, pct(p, 0)); });
    const fx = h('div', null, ctx); fx.style.marginTop = '12px'; h('h3', null, fx, 'What the Fed had said'); const p1 = h('p', 'quiet', fx); text(p1, `Latest statement ${ft.sd || 'n/a'} · stance ${snum((D.panel.fed_stance || [])[i], 2)} (−1 easing … +1 tightening) · novelty ${num((D.panel.fed_novelty || [])[i], 2)}`);
    if (ft.kp && ft.kp.length) { h('div', 'quiet', fx, 'Phrases the stance scorer keyed on:'); const ul = h('ul', 'quiet', fx); ft.kp.forEach(k => h('li', null, ul, k)); }
    const th = h('div', null, ctx); th.style.marginTop = '12px'; h('h3', null, th, 'How unusual the numbers were (z-scores)'); const tp = h('p', 'quiet', th); text(tp, ['growth', 'inflation', 'policy', 'financial'].map(t => `${t} ${snum((D.panel['theme_' + t] || [])[i], 2)}`).join(' · ') + ` · policy-uncertainty news ${snum((D.panel.tiz_epu || [])[i], 1)} · geopolitical news ${snum((D.panel.tiz_gpr || [])[i], 1)}`);
    if (dec) { const vw = h('div', null, ctx); vw.style.marginTop = '14px'; h('h3', null, vw, `What "${NAMES[s]}" thought`); if (dec.ra) h('p', 'quiet', vw, dec.ra); const t = h('table', null, vw); const tr = h('tr', null, h('thead', null, t)); ['fund', 'lean', 'expected edge / yr', 'confidence', 'evidence'].forEach(x => h('th', null, tr, x)); const tb = h('tbody', null, t); dec.v.forEach(v => { const r = h('tr', null, tb); h('td', null, r, v[0]); h('td', null, r, v[1]); h('td', null, r, spct(v[2], 1)); h('td', null, r, num(v[3], 2)); const e = h('td', 'txt', r, (v[4] || []).join('; ')); e.style.maxWidth = '380px'; }); if (dec.rat) { const p = h('p', 'quiet', vw, dec.rat); p.style.marginTop = '6px'; } }
    if (!dec) { h('p', 'quiet', Rt, 'No decision recorded for this date.'); return; }
    const fb = h('div', null, Rt); h('h3', null, fb, 'The bank\'s rules that week');
    if (dec.bf.length) { const p = h('p', null, fb); h('span', 'pill bad', p, `${dec.bf.length} rule${dec.bf.length > 1 ? 's' : ''} hit on the first proposal`); dec.bm.forEach(m => h('div', 'quiet', fb, m)); } else { const p = h('p', null, fb); h('span', 'pill ok', p, 'first proposal fit inside every rule'); }
    if (dec.r) { const p = h('p', null, fb); p.style.marginTop = '6px'; h('span', 'pill', p, `${dec.r} revision round${dec.r > 1 ? 's' : ''}`); h('span', dec.bl.length ? 'pill bad' : 'pill ok', p, dec.bl.length ? `${dec.bl.length} still binding after revision` : 'all cleared by revision'); if (dec.h.length) { const last = dec.h[dec.h.length - 1]; h('div', 'quiet', fb, 'Views after revision: ' + last.map(v => `${v[0]} ${spct(v[1], 1)} @ ${num(v[2], 2)}`).join(', ')); } }
    const cs = dec.cs || {}; const L2 = D.meta.limits || {};
    const mt = h('div', null, Rt); mt.style.marginTop = '12px'; h('h3', null, mt, 'Risk against limits');
    [['Volatility', cs.volatility, L2.vol, (v) => pct(v, 1)], ['Capital used', cs.risk_weighted_exposure, L2.rw, (v) => num(v, 2)]].forEach(m => { if (m[1] == null || m[2] == null) return; const d = h('div', 'meter', mt); const lab = h('div', 'lab', d); h('span', null, lab, m[0]); h('b', null, lab, `${m[3](m[1])} of ${m[3](m[2])}`); const tr = h('div', 'track', d); const f = h('div', 'fill', tr); f.style.width = Math.min(100, m[1] / m[2] * 100).toFixed(0) + '%'; });
    if (cs.duration != null && L2.dur_hi != null) { const d = h('div', 'meter', mt); const lab = h('div', 'lab', d); h('span', null, lab, 'Interest-rate sensitivity (years)'); h('b', null, lab, `${num(cs.duration, 1)} in band ${num(L2.dur_lo, 1)}–${num(L2.dur_hi, 1)}`); const tr = h('div', 'track', d); tr.style.background = 'transparent'; tr.style.border = '1px solid var(--axis)'; const band = h('div', 'band', tr); const top = Math.max(L2.dur_hi * 1.3, 8); band.style.left = (L2.dur_lo / top * 100) + '%'; band.style.width = ((L2.dur_hi - L2.dur_lo) / top * 100) + '%'; const f = h('div', 'fill', tr); f.style.width = Math.min(100, cs.duration / top * 100).toFixed(0) + '%'; }
    const wt = h('div', null, Rt); wt.style.marginTop = '12px'; h('h3', null, wt, 'What it actually held'); const bars2 = h('div', 'bars', wt); const W = D.weights[s][i] || [];
    D.meta.assets.forEach((a, j) => { const w = W[j] || 0; const row = h('div', 'bar', bars2); h('span', 't', row, a); const track = h('div', null, row); const b = h('div', 'b', track); b.style.width = (w / 0.5 * 100).toFixed(1) + '%'; h('span', 'v', row, pct(w, 1)); });
    h('div', 'quiet', wt, dec.fv ? `Rule-checker: ${dec.fv} violation(s) on executed weights` : 'Rule-checker: every rule satisfied on the executed weights.');
    const cmp = h('div', null, Rt); cmp.style.marginTop = '12px'; h('h3', null, cmp, 'Same week, all three players'); const t = h('table', null, cmp); const tr = h('tr', null, h('thead', null, t)); h('th', null, tr, 'fund'); STRAT.forEach(x => h('th', null, tr, NAMES[x])); const tb = h('tbody', null, t); D.meta.assets.forEach((a, j) => { const r = h('tr', null, tb); h('td', null, r, a); STRAT.forEach(x => h('td', null, r, pct((D.weights[x][i] || [])[j], 1))); });
  }

  function renderFoot() { text($('#cert'), JSON.stringify(D.summary.certificate, null, 1)); text($('#foot'), `Finorchestra · run ${D.meta.run_id} · generated from summary.json, panel.csv, returns and weights CSVs and decisions/*.json · ${D.dates.length} decisions embedded · every chart has a table twin; charts read on hover and with arrow keys.`); }

  // ------------------------------------------------------------ hover glossary
  const G = { 'reward per unit of risk': 'The Sharpe ratio: return above cash divided by how much the value swung. Around 0.5 is ordinary, 1.0 is very good, below 0 lost to cash.', 'Sharpe': 'Return above cash divided by how much the value swung: reward per unit of risk. Around 0.5 is ordinary, 1.0 is very good.', 'luck check': 'A p-value from reshuffling the history thousands of times: the chance a difference this big appears by chance. Below 0.05 means probably real.', 'p-value': 'The chance a difference this big appears by chance. Below 0.05 means probably real.', 'volatility': 'How much the value bounces around: the standard deviation of weekly returns, scaled to a year.', 'drawdown': 'The fall from a previous high. The worst one is what a risk manager remembers.', 'turnover': 'The share of the book traded in a week. Trading costs money, so high turnover eats an edge.', 'neutral portfolio': 'A risk-balanced mix computed from data each week (each risky fund weighted by one over its volatility). The starting point every opinion tilts away from and the anchor of every rule.', 'market weights': 'Version-1 label for the neutral mix, then a hand-typed table; revision 2 computes it from data.', 'duration': 'How sensitive a bond book is to interest rates, in years. Longer means bigger swings when rates move.', 'capital': 'A regulatory budget: each fund uses capital at the US standardised risk weight for its kind (government 0%, corporate 100%, listed equity 300%), and the total may not exceed 1.25 times the neutral portfolio\'s.', 'cap': 'A limit on how much of the book one fund may be: its neutral weight plus the active band.', 'binding': 'Pressed right up against a limit because the views wanted more.', 'rule-checker': 'A plain piece of code, no AI, that re-tests every executed portfolio against every rule and writes any breach in plain English.', 'bootstrap': 'Reshuffling blocks of the history thousands of times to see how often a difference reverses. The source of the luck check.', 'z-score': 'How many standard deviations a reading is from its own ten-year normal. Zero is typical; two is unusual.', 'z-scores': 'How many standard deviations readings are from their own ten-year normal. Zero is typical; two is unusual.', 'training cutoff': 'The date after which a language model has seen no data. Decisions after it cannot be helped by memory.', 'certificate': 'A record every run writes: how point-in-time each input truly is, which model was used, its cutoff, and what could have leaked.', 'Fed': 'The US Federal Reserve, the central bank. It sets the key interest rate eight times a year and publishes a short statement each time.', 'Black-Litterman': 'A formula that starts from the neutral portfolio and tilts toward each opinion in proportion to its confidence.', 'optimiser': 'The arithmetic that finds the best mix of weights under all the rules at once. Fast, exact, no AI.', 'stance': 'Where the Fed leans in its latest statement: toward easing (−1) or tightening (+1).', 'novelty': 'How different the latest Fed statement is from the previous one. Near zero means the wording barely changed.', 'regime': 'Which economic season the signals point to: growth up or down combined with inflation up or down.', 'Sharpe ratio': 'Return above cash divided by how much the value swung: reward per unit of risk.' };
  const gkeys = Object.keys(G).sort((a, b) => b.length - a.length);
  const gre = new RegExp('(^|[^A-Za-z0-9-])(' + gkeys.map(s => s.replace(/[.*+?^${}()|[\]\\\/]/g, '\\$&')).join('|') + ')(?![A-Za-z0-9-])', 'gi');
  function glossaryKey(m) { const k = m.toLowerCase(); for (const x of gkeys) if (x.toLowerCase() === k) return x; return null; }
  let termtip = null;
  function wrapTerms(root) {
    const walker = document.createTreeWalker(root, NodeFilter.SHOW_TEXT, { acceptNode: (n) => { let p = n.parentNode; while (p && p !== root) { if (p.namespaceURI === NS || ['PRE', 'CODE', 'DFN', 'SCRIPT', 'STYLE', 'TH', 'BUTTON', 'TABLE', 'B'].includes(p.nodeName) || (p.classList && (p.classList.contains('tip') || p.classList.contains('num') || p.classList.contains('t') || p.classList.contains('legend')))) return NodeFilter.FILTER_REJECT; p = p.parentNode; } return n.nodeValue.trim() ? NodeFilter.FILTER_ACCEPT : NodeFilter.FILTER_REJECT; } });
    const nodes = []; while (walker.nextNode()) nodes.push(walker.currentNode);
    nodes.forEach(node => { const t = node.nodeValue; gre.lastIndex = 0; if (!gre.test(t)) return; gre.lastIndex = 0; const frag = document.createDocumentFragment(); let last = 0, m; while ((m = gre.exec(t)) !== null) { const start = m.index + m[1].length, word = m[2], key = glossaryKey(word); if (!key) continue; frag.appendChild(document.createTextNode(t.slice(last, start))); const d = document.createElement('dfn'); d.className = 'hov'; d.textContent = word; d.setAttribute('tabindex', '0'); d.setAttribute('data-key', key); frag.appendChild(d); last = start + word.length; } frag.appendChild(document.createTextNode(t.slice(last))); node.parentNode.replaceChild(frag, node); });
  }
  function setupGlossary() {
    termtip = document.createElement('div'); termtip.id = 'termtip'; termtip.setAttribute('role', 'tooltip'); document.body.appendChild(termtip);
    let current = null;
    function place(el) { const r = el.getBoundingClientRect(); termtip.style.display = 'block'; const w = termtip.offsetWidth, hh = termtip.offsetHeight; let left = r.left, top = r.bottom + 8; if (left + w > window.innerWidth - 12) left = Math.max(12, window.innerWidth - w - 12); if (top + hh > window.innerHeight - 12) top = r.top - hh - 8; termtip.style.left = left + 'px'; termtip.style.top = Math.max(8, top) + 'px'; }
    function showT(el) { const key = el.getAttribute('data-key'); if (!key) return; termtip.replaceChildren(); const b = document.createElement('b'); b.textContent = key; termtip.appendChild(b); termtip.appendChild(document.createTextNode(G[key])); if (current) current.classList.remove('on'); current = el; el.classList.add('on'); place(el); }
    function hideT() { termtip.style.display = 'none'; if (current) current.classList.remove('on'); current = null; }
    document.addEventListener('mouseover', (e) => { const t = e.target.closest && e.target.closest('dfn.hov'); if (t) showT(t); });
    document.addEventListener('mouseout', (e) => { const t = e.target.closest && e.target.closest('dfn.hov'); if (t && !(e.relatedTarget && t.contains(e.relatedTarget))) hideT(); });
    document.addEventListener('focusin', (e) => { const t = e.target.closest && e.target.closest('dfn.hov'); if (t) showT(t); });
    document.addEventListener('focusout', (e) => { const t = e.target.closest && e.target.closest('dfn.hov'); if (t) hideT(); });
    document.addEventListener('click', (e) => { const t = e.target.closest && e.target.closest('dfn.hov'); if (t) { if (current === t && termtip.style.display === 'block') hideT(); else showT(t); } else hideT(); });
    document.addEventListener('keydown', (e) => { if (e.key === 'Escape') hideT(); });
    window.addEventListener('scroll', hideT, true); window.addEventListener('resize', hideT);
  }

  document.querySelectorAll('[data-table]').forEach(btn => { btn.addEventListener('click', () => { const id = btn.getAttribute('data-table') + '-tbl'; state.tables[id] = !state.tables[id]; btn.setAttribute('aria-pressed', String(!!state.tables[id])); document.getElementById(id).classList.toggle('open', !!state.tables[id]); renderAll(); }); });
  $('#scrub').addEventListener('input', (e) => { state.dec = parseInt(e.target.value); renderExplorer(); wrapTerms($('#exLeft')); wrapTerms($('#exRight')); });
  $('#prevD').addEventListener('click', () => { state.dec = Math.max(R0, state.dec - 1); renderExplorer(); });
  $('#nextD').addEventListener('click', () => { state.dec = Math.min(R1, state.dec + 1); renderExplorer(); });
  function renderAll() {
    readCss(); const rr = rangeIdx(); R0 = rr[0]; R1 = rr[1];
    renderHeader(); const P = renderVerdict(); renderGrowth(P); renderDD(P); renderIdea(P); renderAlloc(); renderCons(); renderExplorer(); renderStats(); renderAttr(); renderRS(); renderCost(); renderRegime(); renderThemes(); renderInc(); renderFoot();
    wrapTerms(document.querySelector('.wrap'));
    try { localStorage.setItem('finorchestra-dash', JSON.stringify({ strategy: state.strategy, range: state.range })); } catch (e) { /* ignore */ }
  }
  let rt = null; window.addEventListener('resize', () => { clearTimeout(rt); rt = setTimeout(renderAll, 150); });
  if (window.matchMedia) { try { window.matchMedia('(prefers-color-scheme: dark)').addEventListener('change', renderAll); } catch (e) { /* older browsers */ } }
  new MutationObserver(renderAll).observe(document.documentElement, { attributes: true, attributeFilter: ['data-theme'] });
  try { const saved = localStorage.getItem('finorchestra-dash'); if (saved) { const s = JSON.parse(saved); if (STRAT.includes(s.strategy)) state.strategy = s.strategy; if (RANGES.some(r => r[0] === s.range)) state.range = s.range; } } catch (e) { /* no storage */ }
  setupGlossary();
  renderAll();
})();
</script>
"""
