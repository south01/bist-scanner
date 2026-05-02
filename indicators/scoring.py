"""indicators/scoring.py — Five-set composite scoring engine for BIST v2.0"""
from __future__ import annotations
import numpy as np
import pandas as pd

from indicators.regime    import score_regime
from indicators.momentum  import score_momentum
from indicators.structure import score_structure
from indicators.vwap      import compute_rolling_vwap, score_vwap_position

# ── Weights ───────────────────────────────────────────────────────────────────
WEIGHTS = {
    "regime":     0.20,
    "momentum":   0.20,
    "structure":  0.30,
    "smart_money": 0.15,
    "catalyst":   0.15,
}

# ── Tier thresholds ───────────────────────────────────────────────────────────
TIERS = [("S", 70), ("A", 50), ("B", 35), ("C", 20)]


def _tier(score: float) -> str:
    for t, threshold in TIERS:
        if score >= threshold:
            return t
    return "-"


def _score_smart_money(hist: pd.DataFrame) -> dict:
    """
    Smart money proxy from volume pattern analysis.
    Looks for: accumulation (up days with above-avg vol), distribution (down days high vol),
    unusual volume streaks, volume trend.
    Score: 0-100.
    """
    result = {"score": 50.0, "details": {}, "signals": []}
    if hist is None or len(hist) < 20:
        return result

    closes  = hist["Close"].dropna()
    volumes = hist["Volume"].dropna()
    score = 50.0
    signals = []

    if len(closes) < 10 or len(volumes) < 10:
        return result

    # Average volume
    avg_vol_20 = float(volumes.iloc[-21:-1].mean()) if len(volumes) >= 21 else float(volumes.mean())

    # Count up-volume vs down-volume days (last 10 days)
    up_vol = 0.0; down_vol = 0.0
    for i in range(-10, 0):
        if closes.iloc[i] > closes.iloc[i-1]:
            up_vol += volumes.iloc[i]
        else:
            down_vol += volumes.iloc[i]

    if up_vol + down_vol > 0:
        up_ratio = up_vol / (up_vol + down_vol)
        if up_ratio > 0.7:
            score += 20
            signals.append(f"Accumulation pattern ({up_ratio:.0%} up-vol)")
        elif up_ratio > 0.55:
            score += 10
            signals.append("Mild accumulation")
        elif up_ratio < 0.35:
            score -= 20
            signals.append("Distribution pattern")

    # Volume trend: is volume increasing?
    vol_5d  = float(volumes.iloc[-5:].mean())
    vol_20d = avg_vol_20
    if vol_20d > 0:
        vol_trend = vol_5d / vol_20d
        if vol_trend > 1.5:
            score += 15
            signals.append(f"Volume surge ({vol_trend:.1f}x recent avg)")
        elif vol_trend > 1.2:
            score += 8
            signals.append("Volume rising")
        elif vol_trend < 0.7:
            score -= 10
            signals.append("Volume drying up")

    # VWAP from smart-money perspective (above = institutional support)
    vwap_data = compute_rolling_vwap(hist, window=20)
    if vwap_data.get("above_vwap") is True:
        score += 10
        signals.append("Above 20d VWAP (institutional support)")
    elif vwap_data.get("above_vwap") is False:
        score -= 10

    score = max(0.0, min(100.0, score))
    result["score"] = round(score, 1)
    result["signals"] = signals
    result["details"] = {"up_vol_ratio": round(up_vol/(up_vol+down_vol), 2) if (up_vol+down_vol)>0 else 0.5,
                         "vol_trend": round(vol_5d/vol_20d, 2) if vol_20d>0 else 1.0}
    return result


def _score_catalyst(hist: pd.DataFrame, index_change: float = 0.0) -> dict:
    """
    Catalyst score: unusual activity today vs recent history.
    Gap + volume = strongest catalyst signal.
    Score: 0-100.
    """
    result = {"score": 0.0, "details": {}, "signals": []}
    if hist is None or len(hist) < 5:
        return result

    closes  = hist["Close"].dropna()
    volumes = hist["Volume"].dropna()
    score = 0.0
    signals = []

    if len(closes) < 5:
        return result

    price      = float(closes.iloc[-1])
    prev_close = float(closes.iloc[-2])
    today_vol  = float(volumes.iloc[-1])
    avg_vol    = float(volumes.iloc[-21:-1].mean()) if len(volumes) >= 21 else float(volumes.mean())

    day_chg = (price - prev_close) / prev_close * 100 if prev_close > 0 else 0
    rvol    = today_vol / avg_vol if avg_vol > 0 else 1.0

    # Gap-and-volume combo
    gap_pct = 0.0
    if "Open" in hist.columns and prev_close > 0:
        gap_pct = (float(hist["Open"].iloc[-1]) - prev_close) / prev_close * 100

    if gap_pct > 5 and rvol >= 3.0:
        score = 90
        signals.append(f"Gap+Volume combo ({gap_pct:.1f}% gap, {rvol:.1f}x vol)")
    elif gap_pct > 3 and rvol >= 2.0:
        score = 70
        signals.append(f"Gap up {gap_pct:.1f}% with elevated volume {rvol:.1f}x")
    elif gap_pct > 2:
        score = 45
        signals.append(f"Gap up {gap_pct:.1f}%")
    elif rvol >= 3.0:
        score = 55
        signals.append(f"Volume explosion {rvol:.1f}x (no gap)")
    elif rvol >= 2.0:
        score = 30
        signals.append(f"Volume elevated {rvol:.1f}x")

    # RS outperformance amplifies catalyst
    rs = day_chg - index_change
    if rs >= 3.0:
        score = min(score + 15, 100)
        signals.append(f"RS outperformance +{rs:.1f}%")

    score = max(0.0, min(100.0, score))
    result["score"] = round(score, 1)
    result["signals"] = signals
    result["details"] = {"gap_pct": round(gap_pct, 2), "rvol": round(rvol, 2),
                         "day_change": round(day_chg, 2)}
    return result


def compute_composite(
    ticker: str,
    hist: pd.DataFrame,
    xu100_hist: pd.DataFrame,
    index_change: float = 0.0,
) -> dict:
    """
    Compute five-set composite score.
    Returns full result dict compatible with StockResult expectations.
    """
    empty = {
        "ticker": ticker, "score": 0.0, "tier": "-",
        "regime_score": 0.0, "momentum_score": 0.0, "structure_score": 0.0,
        "smart_money_score": 0.0, "catalyst_score": 0.0,
        "active_signals": [], "reasoning": "",
        "vwap_data": {}, "structure_details": {}, "momentum_details": {},
    }
    if hist is None or hist.empty or len(hist) < 10:
        return empty

    regime_r    = score_regime(xu100_hist)
    momentum_r  = score_momentum(hist)
    structure_r = score_structure(hist, index_change=index_change)
    smart_r     = _score_smart_money(hist)
    catalyst_r  = _score_catalyst(hist, index_change=index_change)
    vwap_data   = compute_rolling_vwap(hist, window=20)

    r = regime_r["score"]
    m = momentum_r["score"]
    s = structure_r["score"]
    sm = smart_r["score"]
    c  = catalyst_r["score"]

    composite = (
        r  * WEIGHTS["regime"]     +
        m  * WEIGHTS["momentum"]   +
        s  * WEIGHTS["structure"]  +
        sm * WEIGHTS["smart_money"] +
        c  * WEIGHTS["catalyst"]
    )
    composite = round(min(100.0, max(0.0, composite)), 1)

    # Aggregate active signals for display
    all_signals = (
        structure_r["details"].get("signals", []) +
        momentum_r["details"].get("signals", []) +
        catalyst_r["signals"] +
        smart_r["signals"]
    )

    # Reasoning text
    trend = regime_r.get("trend", "neutral")
    reasoning = (
        f"Piyasa rejimi {trend}. "
        f"Yapı puanı {s:.0f}/100, momentum {m:.0f}/100, katalizör {c:.0f}/100. "
    )
    if structure_r.get("gap_type") not in ("none", "flat", "gap_down"):
        reasoning += f"Boşluk: {structure_r.get('gap_type')} ({structure_r.get('gap_pct', 0):.1f}%). "
    if catalyst_r["signals"]:
        reasoning += " | ".join(catalyst_r["signals"])

    return {
        "ticker": ticker,
        "score": composite,
        "tier": _tier(composite),
        "regime_score": r,
        "momentum_score": m,
        "structure_score": s,
        "smart_money_score": sm,
        "catalyst_score": c,
        "active_signals": all_signals[:8],  # cap for display
        "reasoning": reasoning,
        "vwap_data": vwap_data,
        "structure_details": structure_r["details"],
        "momentum_details": momentum_r["details"],
        "regime_details": regime_r["details"],
    }


def generate_score_breakdown(comp: dict) -> dict:
    """Format breakdown for the frontend (compatible with old score_breakdown format)."""
    sets = [
        {"label": "Piyasa Rejimi",  "key": "regime_score",     "weight": WEIGHTS["regime"],     "max": 100},
        {"label": "Momentum",       "key": "momentum_score",    "weight": WEIGHTS["momentum"],   "max": 100},
        {"label": "Yapı",           "key": "structure_score",   "weight": WEIGHTS["structure"],  "max": 100},
        {"label": "Akıllı Para",    "key": "smart_money_score", "weight": WEIGHTS["smart_money"],"max": 100},
        {"label": "Katalizör",      "key": "catalyst_score",    "weight": WEIGHTS["catalyst"],   "max": 100},
    ]
    breakdown_sets = []
    for s in sets:
        raw = comp.get(s["key"], 0.0)
        contribution = round(raw * s["weight"], 1)
        breakdown_sets.append({
            "label": s["label"],
            "raw_score": round(raw, 1),
            "weight_pct": int(s["weight"] * 100),
            "contribution": contribution,
        })
    return {
        "sets": breakdown_sets,
        "composite": comp["score"],
        "tier": comp["tier"],
        "signals": comp.get("active_signals", []),
    }
