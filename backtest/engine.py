"""backtest/engine.py — Daily-bar VWAP stop strategy backtest for BIST"""
from __future__ import annotations
import logging
import numpy as np
import pandas as pd
import yfinance as yf
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime, timedelta

from backtest.metrics    import compute_metrics
from backtest.strategies import STRATEGIES, FILTER_VARIANTS

logger = logging.getLogger(__name__)


def _fetch_hist(ticker: str, period: str = "2y") -> pd.DataFrame | None:
    try:
        df = yf.download(ticker, period=period, interval="1d",
                         progress=False, auto_adjust=True)
        if df is not None and not df.empty:
            return df.dropna(how="all")
    except Exception as e:
        logger.warning(f"Fetch error {ticker}: {e}")
    return None


def _rolling_vwap(hist: pd.DataFrame, window: int = 20) -> pd.Series:
    """Return rolling VWAP series aligned to hist.index."""
    tp = (hist["High"] + hist["Low"] + hist["Close"]) / 3
    tp_vol = tp * hist["Volume"]
    cum_tp_vol = tp_vol.rolling(window, min_periods=1).sum()
    cum_vol    = hist["Volume"].rolling(window, min_periods=1).sum()
    return cum_tp_vol / cum_vol.replace(0, np.nan)


def _atr_series(hist: pd.DataFrame, period: int = 14) -> pd.Series:
    high  = hist["High"]
    low   = hist["Low"]
    close = hist["Close"]
    prev_close = close.shift(1)
    tr = pd.concat([high - low, (high - prev_close).abs(), (low - prev_close).abs()], axis=1).max(axis=1)
    return tr.ewm(alpha=1/period, adjust=False).mean()


def _run_single(hist: pd.DataFrame, strategy_cfg: dict) -> list[dict]:
    """Run one strategy on a single stock's history. Returns list of trade dicts."""
    if hist is None or len(hist) < 40:
        return []

    entry_gap_min  = strategy_cfg.get("entry_gap_min", 2.0)
    entry_rvol_min = strategy_cfg.get("entry_rvol_min", 2.0)
    stop_type      = strategy_cfg.get("stop_type", "vwap")
    atr_mult       = strategy_cfg.get("atr_mult", 1.5)
    stop_pct       = strategy_cfg.get("stop_pct", 2.0)
    max_hold       = strategy_cfg.get("max_hold_days", 10)

    vwap_ser = _rolling_vwap(hist, window=20)
    atr_ser  = _atr_series(hist, period=14)
    vol_avg  = hist["Volume"].rolling(20).mean().shift(1)

    trades = []
    in_trade = False
    entry_price = 0.0
    entry_date  = None
    stop_level  = 0.0
    hold_days   = 0
    mae         = 0.0
    mfe         = 0.0

    for i in range(30, len(hist)):
        row       = hist.iloc[i]
        prev_row  = hist.iloc[i - 1]
        date      = hist.index[i]

        if in_trade:
            # Track MAE / MFE
            mae = min(mae, (row["Low"]  - entry_price) / entry_price * 100)
            mfe = max(mfe, (row["High"] - entry_price) / entry_price * 100)
            hold_days += 1
            close = float(row["Close"])

            # Stop condition
            stopped = False
            if stop_type == "vwap" and close < float(vwap_ser.iloc[i]):
                stopped = True
            elif stop_type in ("atr", "fixed_pct") and close < stop_level:
                stopped = True

            if stopped or hold_days >= max_hold:
                ret_pct = (close - entry_price) / entry_price * 100
                trades.append({
                    "entry_date":  str(entry_date.date()),
                    "exit_date":   str(date.date()),
                    "entry_price": round(entry_price, 2),
                    "exit_price":  round(close, 2),
                    "return_pct":  round(ret_pct, 2),
                    "hold_days":   hold_days,
                    "exit_reason": "stop" if stopped else "max_hold",
                    "outcome":     "win" if ret_pct > 0 else ("loss" if ret_pct < 0 else "breakeven"),
                    "mae":         round(mae, 2),
                    "mfe":         round(mfe, 2),
                })
                in_trade = False
            continue

        # Entry: gap-up + RVOL
        prev_close = float(prev_row["Close"])
        open_price = float(row["Open"])
        if prev_close <= 0:
            continue

        gap_pct = (open_price - prev_close) / prev_close * 100
        avg_vol = float(vol_avg.iloc[i])
        rvol = float(row["Volume"]) / avg_vol if avg_vol > 0 else 0

        if gap_pct >= entry_gap_min and rvol >= entry_rvol_min:
            entry_price = open_price
            entry_date  = date
            hold_days   = 0
            mae = 0.0; mfe = 0.0
            in_trade = True

            # Compute stop
            atr_val = float(atr_ser.iloc[i])
            if stop_type == "atr":
                stop_level = entry_price - atr_val * atr_mult
            elif stop_type == "fixed_pct":
                stop_level = entry_price * (1 - stop_pct / 100)
            else:  # vwap: dynamic, checked each day
                stop_level = 0.0

    return trades


def run_full_backtest(ticker: str, strategy_name: str = "vwap_stop") -> dict:
    """Run a full backtest for one ticker with the given strategy."""
    cfg = STRATEGIES.get(strategy_name, STRATEGIES["vwap_stop"])
    hist = _fetch_hist(ticker, period="2y")
    if hist is None or hist.empty:
        return {"error": f"No data for {ticker}"}

    trades = _run_single(hist, cfg)
    metrics = compute_metrics(trades)

    return {
        "ticker": ticker,
        "strategy": strategy_name,
        "strategy_name": cfg["name"],
        "metrics": metrics,
        "trades": trades,
    }


def run_multi_stop_comparison(ticker: str) -> dict:
    """Run all four stop strategies and compare metrics."""
    hist = _fetch_hist(ticker, period="2y")
    if hist is None or hist.empty:
        return {"error": f"No data for {ticker}"}

    comparison = {}
    for key, cfg in STRATEGIES.items():
        trades = _run_single(hist, cfg)
        metrics = compute_metrics(trades)
        comparison[key] = {
            "name": cfg["name"],
            "metrics": metrics,
            "trade_count": len(trades),
        }

    return {"ticker": ticker, "comparison": comparison}


def run_filter_sweep(tickers: list[str], max_workers: int = 8) -> dict:
    """
    Run filter sensitivity sweep across multiple tickers and all FILTER_VARIANTS.
    Returns aggregate metrics per filter variant.
    """
    # Fetch all histories first
    all_hist: dict[str, pd.DataFrame] = {}
    with ThreadPoolExecutor(max_workers=max_workers) as ex:
        futures = {ex.submit(_fetch_hist, t, "2y"): t for t in tickers}
        for f in as_completed(futures):
            t = futures[f]
            try:
                h = f.result()
                if h is not None and not h.empty:
                    all_hist[t] = h
            except Exception:
                pass

    sweep_results = {}
    for variant in FILTER_VARIANTS:
        all_trades = []
        for hist in all_hist.values():
            trades = _run_single(hist, variant)
            all_trades.extend(trades)
        metrics = compute_metrics(all_trades)
        sweep_results[variant["name"]] = {
            "config": variant,
            "metrics": metrics,
            "total_trades": len(all_trades),
        }

    return sweep_results
