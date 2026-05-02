"""indicators/momentum.py — Momentum score (0-100)"""
import numpy as np
import pandas as pd


def _ema(s: pd.Series, span: int) -> pd.Series:
    return s.ewm(span=span, adjust=False).mean()


def _macd(closes: pd.Series, fast=12, slow=26, signal=9):
    ema_fast = _ema(closes, fast)
    ema_slow = _ema(closes, slow)
    macd_line = ema_fast - ema_slow
    signal_line = _ema(macd_line, signal)
    hist = macd_line - signal_line
    return macd_line, signal_line, hist


def _rsi(series: pd.Series, period: int = 14) -> float:
    if len(series) < period + 1:
        return float("nan")
    delta = series.diff(1).dropna()
    gain = delta.clip(lower=0).ewm(alpha=1/period, adjust=False).mean()
    loss = (-delta).clip(lower=0).ewm(alpha=1/period, adjust=False).mean()
    last_loss = loss.iloc[-1]
    if last_loss == 0:
        return 100.0
    return round(100 - 100 / (1 + gain.iloc[-1] / last_loss), 2)


def _adx(hist: pd.DataFrame, period: int = 14) -> float:
    if hist is None or len(hist) < period + 5:
        return float("nan")
    high = hist["High"].values
    low  = hist["Low"].values
    close = hist["Close"].values
    tr_arr, pdm_arr, ndm_arr = [], [], []
    for i in range(1, len(close)):
        tr = max(high[i]-low[i], abs(high[i]-close[i-1]), abs(low[i]-close[i-1]))
        pdm = max(high[i]-high[i-1], 0) if (high[i]-high[i-1]) > (low[i-1]-low[i]) else 0
        ndm = max(low[i-1]-low[i], 0) if (low[i-1]-low[i]) > (high[i]-high[i-1]) else 0
        tr_arr.append(tr); pdm_arr.append(pdm); ndm_arr.append(ndm)
    tr_s  = pd.Series(tr_arr).ewm(alpha=1/period, adjust=False).mean()
    pdm_s = pd.Series(pdm_arr).ewm(alpha=1/period, adjust=False).mean()
    ndm_s = pd.Series(ndm_arr).ewm(alpha=1/period, adjust=False).mean()
    pdi = 100 * pdm_s / tr_s.replace(0, np.nan)
    ndi = 100 * ndm_s / tr_s.replace(0, np.nan)
    dx  = 100 * abs(pdi - ndi) / (pdi + ndi).replace(0, np.nan)
    adx = dx.ewm(alpha=1/period, adjust=False).mean()
    return float(adx.iloc[-1])


def _rvol(hist: pd.DataFrame, lookback: int = 20) -> float:
    if hist is None or len(hist) < 5:
        return 0.0
    vols = hist["Volume"].dropna()
    if len(vols) < 2:
        return 0.0
    today = float(vols.iloc[-1])
    avg   = float(vols.iloc[-(lookback+1):-1].mean())
    return round(today / avg, 2) if avg > 0 else 0.0


def score_momentum(hist: pd.DataFrame) -> dict:
    """Score momentum signals. Returns {'score': 0-100, 'details': {...}}"""
    result = {"score": 0.0, "details": {}}

    if hist is None or len(hist) < 30:
        return result

    closes = hist["Close"].dropna()
    if len(closes) < 20:
        return result

    price = float(closes.iloc[-1])
    score = 0.0
    signals = []

    # ── EMA alignment (8/13/21) ──────────────────────────────────────────
    ema8  = float(_ema(closes, 8).iloc[-1])
    ema13 = float(_ema(closes, 13).iloc[-1])
    ema21 = float(_ema(closes, 21).iloc[-1])

    if price > ema8 > ema13 > ema21:
        score += 25
        signals.append("EMA8>13>21 bullish stack")
    elif price > ema13 and ema13 > ema21:
        score += 15
        signals.append("EMA13>21 aligned")
    elif price > ema21:
        score += 8
        signals.append("Above EMA21")

    # ── MACD ─────────────────────────────────────────────────────────────
    if len(closes) >= 35:
        _, sig, hist_macd = _macd(closes)
        macd_hist_last = float(hist_macd.iloc[-1])
        macd_hist_prev = float(hist_macd.iloc[-2]) if len(hist_macd) >= 2 else 0
        if macd_hist_last > 0 and macd_hist_last > macd_hist_prev:
            score += 20
            signals.append("MACD bullish + expanding")
        elif macd_hist_last > 0:
            score += 10
            signals.append("MACD positive")
        elif macd_hist_last > macd_hist_prev:
            score += 5
            signals.append("MACD recovering")

    # ── RSI ──────────────────────────────────────────────────────────────
    rsi = _rsi(closes)
    if np.isfinite(rsi):
        if 50 < rsi <= 70:
            score += 20
            signals.append("RSI Bullish")
        elif rsi > 70:
            score += 10
            signals.append("RSI Overbought")
        elif 40 <= rsi <= 50:
            score += 8
            signals.append("RSI Neutral")
        elif rsi < 30:
            score += 5
            signals.append("RSI Oversold")

    # ── RVOL ─────────────────────────────────────────────────────────────
    rvol = _rvol(hist)
    if rvol >= 3.0:
        score += 20
        signals.append("RVOL Extreme")
    elif rvol >= 2.0:
        score += 12
        signals.append("RVOL High")
    elif rvol >= 1.5:
        score += 6
        signals.append("RVOL Elevated")

    # ── ADX ──────────────────────────────────────────────────────────────
    adx = _adx(hist)
    if np.isfinite(adx):
        if adx >= 30:
            score += 15
            signals.append("ADX Strong")
        elif adx >= 20:
            score += 8
            signals.append("ADX Moderate")

    score = max(0.0, min(100.0, score))
    result["score"] = round(score, 1)
    result["details"] = {
        "ema8": round(ema8, 2), "ema13": round(ema13, 2), "ema21": round(ema21, 2),
        "rsi": round(rsi, 1) if np.isfinite(rsi) else None,
        "rvol": rvol, "adx": round(adx, 1) if np.isfinite(adx) else None,
        "signals": signals,
    }
    return result
