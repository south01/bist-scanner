"""
scorer.py — Signal computation and conviction scoring for BIST stocks (v2.0).
Five-set composite scoring: Regime, Momentum, Structure, Smart Money, Catalyst.
All price data comes from yfinance (EOD/daily). No fundamentals.
"""

import logging
import numpy as np
import pandas as pd
import yfinance as yf
from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import dataclass, field
from typing import Optional

from indicators.scoring import compute_composite, generate_score_breakdown

logger = logging.getLogger(__name__)

# ── Tier thresholds (0–100 composite scale) ───────────────────────────────────
TIERS = [("S", 70), ("A", 50), ("B", 35), ("C", 20)]


def _compute_tier(score: float) -> str:
    for tier, threshold in TIERS:
        if score >= threshold:
            return tier
    return "-"


def _safe_float(val, default=0.0) -> float:
    try:
        v = float(val)
        return v if np.isfinite(v) else default
    except (TypeError, ValueError):
        return default


def _compute_rvol(hist: pd.DataFrame, lookback: int = 20) -> float:
    if hist is None or len(hist) < 5:
        return 0.0
    volumes = hist["Volume"].dropna()
    if len(volumes) < 2:
        return 0.0
    today_vol = _safe_float(volumes.iloc[-1])
    avg_vol   = _safe_float(volumes.iloc[-(lookback + 1):-1].mean())
    return round(today_vol / avg_vol, 2) if avg_vol > 0 else 0.0


def _compute_adr(hist: pd.DataFrame, days: int = 20) -> float:
    if hist is None or len(hist) < 5:
        return 0.0
    recent = hist.tail(days)
    ranges = []
    for _, row in recent.iterrows():
        c = row["Close"]
        if c > 0:
            ranges.append((row["High"] - row["Low"]) / c * 100)
    return round(float(np.mean(ranges)), 2) if ranges else 0.0


@dataclass
class StockResult:
    ticker: str
    company_name: str = ""
    price: float = 0.0
    change_pct: float = 0.0
    rvol: float = 0.0
    score: float = 0.0            # composite 0-100
    tier: str = "-"
    active_signals: list = field(default_factory=list)
    score_breakdown: dict = field(default_factory=dict)
    adr: float = 0.0
    # v2.0 five-set scores
    regime_score: float = 0.0
    momentum_score: float = 0.0
    structure_score: float = 0.0
    smart_money_score: float = 0.0
    catalyst_score: float = 0.0
    reasoning: str = ""
    vwap_data: dict = field(default_factory=dict)
    structure_details: dict = field(default_factory=dict)
    error: Optional[str] = None


def _score_stock(
    ticker: str,
    hist: pd.DataFrame,
    xu100_hist: pd.DataFrame,
    index_change: float,
) -> StockResult:
    """Compute five-set composite score for a single stock."""
    result = StockResult(ticker=ticker)

    try:
        if hist is None or hist.empty or len(hist) < 10:
            result.error = "Yeterli veri yok"
            return result

        closes = hist["Close"].dropna()
        if len(closes) < 5:
            result.error = "Yeterli kapanış verisi yok"
            return result

        price      = _safe_float(closes.iloc[-1])
        prev_close = _safe_float(closes.iloc[-2])
        result.price = round(price, 2)

        if prev_close > 0:
            result.change_pct = round((price - prev_close) / prev_close * 100, 2)

        result.rvol = _compute_rvol(hist)
        result.adr  = _compute_adr(hist)

        # ── Five-set composite ────────────────────────────────────────────
        comp = compute_composite(
            ticker=ticker,
            hist=hist,
            xu100_hist=xu100_hist,
            index_change=index_change,
        )

        result.score            = comp["score"]
        result.tier             = comp["tier"]
        result.regime_score     = comp["regime_score"]
        result.momentum_score   = comp["momentum_score"]
        result.structure_score  = comp["structure_score"]
        result.smart_money_score = comp["smart_money_score"]
        result.catalyst_score   = comp["catalyst_score"]
        result.active_signals   = comp.get("active_signals", [])
        result.reasoning        = comp.get("reasoning", "")
        result.vwap_data        = comp.get("vwap_data", {})
        result.structure_details = comp.get("structure_details", {})
        result.score_breakdown  = generate_score_breakdown(comp)

    except Exception as e:
        logger.warning(f"Score error for {ticker}: {e}", exc_info=True)
        result.error = str(e)

    return result


def _extract_ticker(raw: pd.DataFrame, ticker: str, single: bool) -> pd.DataFrame | None:
    """
    Extract a single ticker's OHLCV DataFrame from a yf.download result.
    Handles both old (Ticker, Price) and new (Price, Ticker) MultiIndex layouts,
    as well as single-ticker flat DataFrames.
    """
    if raw is None or raw.empty:
        return None
    if single:
        return raw.copy()
    if raw.columns.nlevels == 2:
        lvl0 = raw.columns.get_level_values(0).unique()
        lvl1 = raw.columns.get_level_values(1).unique()
        if ticker in lvl0:
            # Old layout: (Ticker, Price) — group_by="ticker"
            return raw[ticker].copy()
        elif ticker in lvl1:
            # New layout (yfinance 0.2.54+): (Price, Ticker)
            return raw.xs(ticker, level=1, axis=1).copy()
    return None


def run_scan(
    tickers: list[str],
    progress_callback=None,
    max_workers: int = 10,
) -> list[StockResult]:
    """
    Download data for all tickers and compute five-set composite scores.
    Returns results sorted by score descending.
    progress_callback(done, total): called after each batch download.
    """
    results = []
    total = len(tickers)

    # ── Step 1: Fetch XU100 index data ──────────────────────────────────
    logger.info("Fetching XU100 index data...")
    index_change = 0.0
    xu100_hist   = None
    try:
        xu100_hist = yf.download(
            "XU100.IS", period="1y", interval="1d", progress=False, auto_adjust=True
        )
        if xu100_hist is not None and len(xu100_hist) >= 2:
            c = xu100_hist["Close"].dropna()
            if len(c) >= 2:
                index_change = float((c.iloc[-1] - c.iloc[-2]) / c.iloc[-2] * 100)
        logger.info(f"XU100 change: {index_change:.2f}%")
    except Exception as e:
        logger.warning(f"XU100 fetch failed: {e}")

    # ── Step 2: Download all tickers in batches ──────────────────────────
    BATCH_SIZE = 50
    all_hist: dict[str, pd.DataFrame] = {}
    done_count = 0

    ticker_batches = [tickers[i:i + BATCH_SIZE] for i in range(0, total, BATCH_SIZE)]
    logger.info(f"Downloading {total} tickers in {len(ticker_batches)} batches...")

    for batch_idx, batch in enumerate(ticker_batches):
        try:
            batch_str = " ".join(batch)
            raw = yf.download(
                batch_str, period="1y", interval="1d",
                progress=False, auto_adjust=True,
            )
            for ticker in batch:
                try:
                    df = _extract_ticker(raw, ticker, single=(len(batch) == 1))
                    if df is not None and not df.empty:
                        all_hist[ticker] = df.dropna(how="all")
                except Exception as e:
                    logger.debug(f"Extract error {ticker}: {e}")
        except Exception as e:
            logger.warning(f"Batch {batch_idx} download error: {e}")

        done_count += len(batch)
        if progress_callback:
            progress_callback(done_count, total)

    # ── Step 2b: Patch today's close ────────────────────────────────────
    logger.info("Patching today's prices...")
    today_batches = [tickers[i:i + BATCH_SIZE] for i in range(0, total, BATCH_SIZE)]
    for batch in today_batches:
        try:
            batch_str = " ".join(batch)
            today_raw = yf.download(
                batch_str, period="1d", interval="1d",
                progress=False, auto_adjust=True,
            )
            if today_raw is None or today_raw.empty:
                continue
            for ticker in batch:
                if ticker not in all_hist:
                    continue
                try:
                    today_df = _extract_ticker(today_raw, ticker, single=(len(batch) == 1))
                    if today_df is None:
                        continue
                    today_df = today_df.dropna(how="all")
                    if today_df.empty:
                        continue
                    last_today = today_df.index[-1]
                    hist = all_hist[ticker]
                    if last_today not in hist.index:
                        all_hist[ticker] = pd.concat([hist, today_df.tail(1)])
                    else:
                        all_hist[ticker].loc[last_today] = today_df.loc[last_today]
                except Exception as e:
                    logger.debug(f"Today patch error {ticker}: {e}")
        except Exception as e:
            logger.warning(f"Today batch download error: {e}")

    # ── Step 3: Score all tickers ────────────────────────────────────────
    logger.info(f"Scoring {len(all_hist)} tickers...")

    with ThreadPoolExecutor(max_workers=max_workers) as executor:
        futures = {
            executor.submit(_score_stock, ticker, hist, xu100_hist, index_change): ticker
            for ticker, hist in all_hist.items()
        }
        for future in as_completed(futures):
            try:
                results.append(future.result())
            except Exception as e:
                ticker = futures[future]
                logger.warning(f"Score future error {ticker}: {e}")
                results.append(StockResult(ticker=ticker, error=str(e)))

    # Add tickers we couldn't fetch
    fetched = set(all_hist.keys())
    for ticker in tickers:
        if ticker not in fetched:
            results.append(StockResult(ticker=ticker, error="Veri indirilemedi"))

    # Sort: scored first by score desc, then errored
    results.sort(key=lambda r: (r.error is None, r.score), reverse=True)

    scored = sum(1 for r in results if r.error is None)
    logger.info(f"Scan complete: {scored}/{total} stocks scored.")
    return results
