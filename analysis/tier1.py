"""analysis/tier1.py — Tier 1 signal generation (LONG/SHORT/BLOCKED)"""
from __future__ import annotations
import numpy as np
import pandas as pd


def _atr(hist: pd.DataFrame, period: int = 14) -> float:
    if hist is None or len(hist) < period + 1:
        return 0.0
    high  = hist["High"].values
    low   = hist["Low"].values
    close = hist["Close"].values
    trs   = [max(high[i]-low[i], abs(high[i]-close[i-1]), abs(low[i]-close[i-1]))
             for i in range(1, len(close))]
    return float(pd.Series(trs).ewm(alpha=1/period, adjust=False).mean().iloc[-1])


def generate_signal(comp: dict, hist: pd.DataFrame) -> dict:
    """
    Generate a Tier-1 trade signal from composite scoring output.
    Returns: {direction, entry, stop_vwap, stop_atr, tp1, tp2, rr, blocked_reason, notes}
    """
    default = {
        "direction": "BLOCKED",
        "entry": None, "stop_vwap": None, "stop_atr": None,
        "tp1": None, "tp2": None, "rr": None,
        "blocked_reason": "Yetersiz puan",
        "notes": [],
    }

    score = comp.get("score", 0)
    tier  = comp.get("tier", "-")

    # Minimum score gate
    if score < 20 or tier == "-":
        default["blocked_reason"] = f"Puan çok düşük ({score:.0f}/100)"
        return default

    # Regime gate: don't go long in bearish regime unless catalyst is very strong
    regime_score  = comp.get("regime_score", 50)
    catalyst_score = comp.get("catalyst_score", 0)
    if regime_score < 35 and catalyst_score < 60:
        default["blocked_reason"] = f"Piyasa rejimi çok zayıf (rejim: {regime_score:.0f})"
        return default

    if hist is None or len(hist) < 10:
        return default

    closes    = hist["Close"].dropna()
    price     = float(closes.iloc[-1])
    prev_close = float(closes.iloc[-2]) if len(closes) >= 2 else price

    vwap_data = comp.get("vwap_data", {})
    vwap = vwap_data.get("vwap")
    atr  = _atr(hist)

    # Direction
    struct = comp.get("structure_details", {})
    gap_pct = struct.get("gap_pct", 0)
    above_vwap = vwap_data.get("above_vwap", True)
    momentum_score = comp.get("momentum_score", 50)

    direction = "LONG" if (momentum_score >= 40 or gap_pct > 1.0 or above_vwap) else "BLOCKED"
    if direction == "BLOCKED":
        default["blocked_reason"] = "Momentum ve yapı uzun pozisyonu desteklemiyor"
        return default

    # Entry
    if gap_pct > 3.0:
        entry = prev_close * 1.01  # Wait for pullback
        entry_note = "Boşluk sonrası ilk geri çekilmede gir"
    else:
        entry = price
        entry_note = "Mevcut fiyatta gir"

    # Stops
    stop_vwap = vwap if vwap and vwap < entry * 0.98 else entry * 0.97
    stop_atr  = entry - atr * 1.5 if atr > 0 else entry * 0.97

    # Use the tighter (higher) stop for primary recommendation
    stop_primary = max(stop_vwap, stop_atr)
    risk = entry - stop_primary
    if risk <= 0:
        risk = entry * 0.02

    # Targets
    tp1 = entry + risk          # 1:1
    tp2 = entry + risk * 2.0   # 1:2

    # R:R
    rr = round((tp2 - entry) / risk, 1) if risk > 0 else 0

    notes = [entry_note]
    if tier == "S":
        notes.append("S Kademe: Tam pozisyon büyüklüğü uygun.")
    elif tier == "A":
        notes.append("A Kademe: 2/3 pozisyon büyüklüğü önerilir.")
    elif tier == "B":
        notes.append("B Kademe: 1/3 pozisyon büyüklüğü, sıkı stop.")
    else:
        notes.append("C Kademe: Küçük deneme pozisyonu.")

    if vwap and price < vwap:
        notes.append(f"⚠️ Fiyat VWAP'ın ({vwap:.2f} ₺) altında — dikkatli olun.")

    if atr > 0:
        notes.append(f"ATR: {atr:.2f} ₺ | Stop VWAP: {stop_vwap:.2f} ₺ | Stop ATR×1.5: {stop_atr:.2f} ₺")

    return {
        "direction": direction,
        "entry": round(entry, 2),
        "stop_vwap": round(stop_vwap, 2),
        "stop_atr":  round(stop_atr, 2),
        "stop_primary": round(stop_primary, 2),
        "tp1": round(tp1, 2),
        "tp2": round(tp2, 2),
        "rr": rr,
        "blocked_reason": None,
        "notes": notes,
    }
