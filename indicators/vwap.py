"""indicators/vwap.py — Daily-bar VWAP and deviation bands"""
import numpy as np
import pandas as pd


def compute_rolling_vwap(hist: pd.DataFrame, window: int = 20) -> dict:
    """
    Compute rolling VWAP over last `window` days using daily bars.
    VWAP = sum(typical_price * volume) / sum(volume)
    Returns dict with vwap, upper bands, lower bands, current price position.
    """
    result = {
        "vwap": None, "vwap_upper1": None, "vwap_lower1": None,
        "vwap_upper2": None, "vwap_lower2": None,
        "price_vs_vwap_pct": None, "above_vwap": None,
        "series": [],
    }

    if hist is None or len(hist) < 5:
        return result

    recent = hist.tail(window).copy()
    if "High" not in recent.columns or "Low" not in recent.columns:
        return result

    # Typical price
    recent["tp"] = (recent["High"] + recent["Low"] + recent["Close"]) / 3
    recent["tp_vol"] = recent["tp"] * recent["Volume"]

    cum_tp_vol = recent["tp_vol"].sum()
    cum_vol    = recent["Volume"].sum()

    if cum_vol <= 0:
        return result

    vwap = cum_tp_vol / cum_vol
    price = float(recent["Close"].iloc[-1])

    # Standard deviation of typical prices (volume-weighted)
    recent["sq_dev"] = (recent["tp"] - vwap) ** 2 * recent["Volume"]
    vwap_std = np.sqrt(recent["sq_dev"].sum() / cum_vol)

    result["vwap"]         = round(float(vwap), 2)
    result["vwap_upper1"]  = round(float(vwap + vwap_std), 2)
    result["vwap_lower1"]  = round(float(vwap - vwap_std), 2)
    result["vwap_upper2"]  = round(float(vwap + 2 * vwap_std), 2)
    result["vwap_lower2"]  = round(float(vwap - 2 * vwap_std), 2)
    result["above_vwap"]   = price > vwap
    result["price_vs_vwap_pct"] = round((price - vwap) / vwap * 100, 2) if vwap > 0 else 0

    # Build VWAP series for chart (rolling window VWAP per bar)
    series_out = []
    hist_arr = hist.copy()
    hist_arr["tp"] = (hist_arr["High"] + hist_arr["Low"] + hist_arr["Close"]) / 3
    for i in range(window - 1, len(hist_arr)):
        window_slice = hist_arr.iloc[i - window + 1: i + 1]
        wv = (window_slice["tp"] * window_slice["Volume"]).sum()
        wvol = window_slice["Volume"].sum()
        v = wv / wvol if wvol > 0 else float("nan")
        series_out.append({
            "time": str(hist_arr.index[i].date()),
            "value": round(float(v), 2),
        })
    result["series"] = series_out

    return result


def score_vwap_position(vwap_data: dict) -> dict:
    """Return a score contribution (0-100) based on VWAP position."""
    score = 50.0
    signals = []

    if vwap_data.get("vwap") is None:
        return {"score": score, "signals": signals}

    pct = vwap_data.get("price_vs_vwap_pct", 0)
    above = vwap_data.get("above_vwap", None)

    if above is True:
        if pct > 5:
            score = 85
            signals.append(f"Far above VWAP (+{pct:.1f}%)")
        elif pct > 2:
            score = 70
            signals.append(f"Above VWAP (+{pct:.1f}%)")
        else:
            score = 60
            signals.append("Slightly above VWAP")
    elif above is False:
        if pct < -5:
            score = 15
            signals.append(f"Far below VWAP ({pct:.1f}%)")
        elif pct < -2:
            score = 30
            signals.append(f"Below VWAP ({pct:.1f}%)")
        else:
            score = 42
            signals.append("Slightly below VWAP")

    return {"score": round(score, 1), "signals": signals}
