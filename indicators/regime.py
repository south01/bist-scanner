"""indicators/regime.py — Market regime score from XU100 (0-100)"""
import logging
import numpy as np
import pandas as pd

logger = logging.getLogger(__name__)


def _ema(series: pd.Series, span: int) -> pd.Series:
    return series.ewm(span=span, adjust=False).mean()


def score_regime(xu100_hist: pd.DataFrame) -> dict:
    """
    Score market regime from XU100 daily bars.
    Returns dict with 'score' (0-100) and 'details'.
    """
    result = {"score": 50.0, "trend": "neutral", "details": {}}

    if xu100_hist is None or len(xu100_hist) < 50:
        return result

    closes = xu100_hist["Close"].dropna()
    if len(closes) < 50:
        return result

    price = float(closes.iloc[-1])

    ema20 = _ema(closes, 20).iloc[-1]
    ema50 = _ema(closes, 50).iloc[-1]
    ema200 = _ema(closes, 200).iloc[-1] if len(closes) >= 200 else None

    score = 50.0
    trend_signals = []

    # EMA 20 vs 50
    if price > ema20:
        score += 10
        trend_signals.append("EMA20↑")
    else:
        score -= 10

    if price > ema50:
        score += 10
        trend_signals.append("EMA50↑")
    else:
        score -= 10

    if ema200 is not None:
        if price > ema200:
            score += 10
            trend_signals.append("EMA200↑")
        else:
            score -= 10

    # 5-day momentum of index
    if len(closes) >= 6:
        week_chg = (closes.iloc[-1] - closes.iloc[-6]) / closes.iloc[-6] * 100
        if week_chg > 2:
            score += 10
            trend_signals.append("週+2%")
        elif week_chg > 0:
            score += 5
        elif week_chg < -2:
            score -= 10
        else:
            score -= 5

    # 20-day trend slope (is EMA20 rising?)
    ema20_series = _ema(closes, 20)
    if len(ema20_series) >= 5:
        slope = (ema20_series.iloc[-1] - ema20_series.iloc[-5]) / ema20_series.iloc[-5] * 100
        if slope > 0.5:
            score += 10
            trend_signals.append("EMA20slope↑")
        elif slope < -0.5:
            score -= 10

    score = max(0.0, min(100.0, score))

    if score >= 65:
        trend = "bullish"
    elif score >= 45:
        trend = "neutral"
    else:
        trend = "bearish"

    result["score"] = round(score, 1)
    result["trend"] = trend
    result["details"] = {
        "xu100_price": round(price, 2),
        "ema20": round(float(ema20), 2),
        "ema50": round(float(ema50), 2),
        "ema200": round(float(ema200), 2) if ema200 is not None else None,
        "trend_signals": trend_signals,
    }
    return result
