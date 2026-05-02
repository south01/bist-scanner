"""indicators/structure.py — Structure score (0-100)"""
import numpy as np
import pandas as pd


def _ema(s: pd.Series, span: int) -> pd.Series:
    return s.ewm(span=span, adjust=False).mean()


def _atr(hist: pd.DataFrame, period: int = 14) -> float:
    if hist is None or len(hist) < period + 1:
        return 0.0
    high  = hist["High"].values
    low   = hist["Low"].values
    close = hist["Close"].values
    trs = [max(high[i]-low[i], abs(high[i]-close[i-1]), abs(low[i]-close[i-1]))
           for i in range(1, len(close))]
    atr_s = pd.Series(trs).ewm(alpha=1/period, adjust=False).mean()
    return float(atr_s.iloc[-1])


def _adr(hist: pd.DataFrame, days: int = 20) -> float:
    if hist is None or len(hist) < 5:
        return 0.0
    rec = hist.tail(days)
    ranges = []
    for _, row in rec.iterrows():
        c = row["Close"]
        if c > 0:
            ranges.append((row["High"] - row["Low"]) / c * 100)
    return round(float(np.mean(ranges)), 2) if ranges else 0.0


def score_structure(hist: pd.DataFrame, index_change: float = 0.0) -> dict:
    """Score price structure signals. Returns {'score': 0-100, 'details': {...}}"""
    result = {"score": 0.0, "details": {}, "gap_pct": 0.0, "gap_type": "none"}

    if hist is None or len(hist) < 10:
        return result

    closes = hist["Close"].dropna()
    if len(closes) < 5:
        return result

    price     = float(closes.iloc[-1])
    prev_close = float(closes.iloc[-2]) if len(closes) >= 2 else price
    score = 0.0
    signals = []

    # ── Gap detection ─────────────────────────────────────────────────────
    gap_pct = 0.0
    if "Open" in hist.columns and prev_close > 0:
        today_open = float(hist["Open"].iloc[-1])
        gap_pct = (today_open - prev_close) / prev_close * 100

    result["gap_pct"] = round(gap_pct, 2)

    # Gap type classification
    day_change = (price - prev_close) / prev_close * 100 if prev_close > 0 else 0
    if gap_pct > 5.0:
        result["gap_type"] = "gap_and_go" if day_change > 0 else "gap_fade"
        score += 25
        signals.append("Gap Up (Large)")
    elif gap_pct > 2.0:
        result["gap_type"] = "gap_up"
        score += 15
        signals.append("Gap Up")
    elif gap_pct < -2.0:
        result["gap_type"] = "gap_down"
        score -= 10
    else:
        result["gap_type"] = "flat"

    # ── PDH (Previous Day High) breakout ─────────────────────────────────
    if len(hist) >= 3:
        pdh = float(hist["High"].iloc[-2])
        if price > pdh:
            score += 15
            signals.append("PDH breakout")
        pdl = float(hist["Low"].iloc[-2])

    # ── EMA 50 / 200 ─────────────────────────────────────────────────────
    ema50 = float(_ema(closes, 50).iloc[-1]) if len(closes) >= 50 else None
    ema200 = float(_ema(closes, 200).iloc[-1]) if len(closes) >= 200 else None

    if ema50 is not None:
        if price > ema50:
            score += 15
            signals.append("Above EMA50")
        else:
            score -= 5

    if ema200 is not None:
        if price > ema200:
            score += 10
            signals.append("Above EMA200")
        else:
            score -= 5

    # ── 52-week high proximity ────────────────────────────────────────────
    high_52w = float(closes.tail(252).max()) if len(closes) >= 20 else float(closes.max())
    pct_from_high = (high_52w - price) / high_52w * 100 if high_52w > 0 else 100

    if pct_from_high <= 2:
        score += 20
        signals.append("At 52w high")
    elif pct_from_high <= 5:
        score += 15
        signals.append("Near 52w high (<5%)")
    elif pct_from_high <= 15:
        score += 5
        signals.append("Within 15% of 52w high")

    # ── Relative strength vs XU100 ────────────────────────────────────────
    rs = day_change - index_change
    if rs >= 3.0:
        score += 15
        signals.append("RS Strong")
    elif rs >= 1.0:
        score += 8
        signals.append("RS Positive")

    # ── ADR (volatility) ─────────────────────────────────────────────────
    adr = _adr(hist)
    if adr >= 4.0:
        score += 5
        signals.append("High ADR")

    atr_val = _atr(hist)

    score = max(0.0, min(100.0, score))
    result["score"] = round(score, 1)
    result["details"] = {
        "price": round(price, 2),
        "prev_close": round(prev_close, 2),
        "gap_pct": round(gap_pct, 2),
        "gap_type": result["gap_type"],
        "ema50": round(ema50, 2) if ema50 else None,
        "ema200": round(ema200, 2) if ema200 else None,
        "high_52w": round(high_52w, 2),
        "pct_from_52w_high": round(pct_from_high, 2),
        "adr": adr,
        "atr": round(atr_val, 2),
        "rs_vs_xu100": round(rs, 2),
        "signals": signals,
    }
    return result
