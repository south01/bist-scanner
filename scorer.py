"""
scorer.py — Signal computation and conviction scoring for BIST stocks.
All price data comes from yfinance (EOD/delayed). No fundamentals.
"""

import logging
import numpy as np
import pandas as pd
import yfinance as yf
from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import dataclass, field
from typing import Optional

logger = logging.getLogger(__name__)

# ── Signal weights ──────────────────────────────────────────────────────────
SIGNALS = {
    "gap_up_combo":     {"weight": 3.0, "domain": "Momentum",       "label": "Güçlü Momentum"},
    "gap_up":           {"weight": 1.5, "domain": "Momentum",       "label": "Boşluk Yukarı"},
    "rvol_3x":          {"weight": 2.0, "domain": "Volume",         "label": "Yüksek Hacim"},
    "rvol_2x":          {"weight": 1.0, "domain": "Volume",         "label": "Artan Hacim"},
    "rs_strong":        {"weight": 2.0, "domain": "Rel. Strength",  "label": "Güçlü RS"},
    "rs_moderate":      {"weight": 1.0, "domain": "Rel. Strength",  "label": "Pozitif RS"},
    "above_ema20":      {"weight": 1.0, "domain": "Structure",      "label": "EMA20 Üstü"},
    "above_ema50":      {"weight": 1.5, "domain": "Structure",      "label": "EMA50 Üstü"},
    "near_52w_high":    {"weight": 1.5, "domain": "Structure",      "label": "52H Yakını"},
    "adr_high":         {"weight": 1.0, "domain": "Volatility",     "label": "Yüksek ADR"},
}

DOMAIN_DIVERSITY_MULTIPLIER = 1.2
DOMAIN_DIVERSITY_MIN = 3

# Tier thresholds
TIERS = [
    ("S", 8.0),
    ("A", 5.0),
    ("B", 3.0),
    ("C", 1.0),
]


@dataclass
class StockResult:
    ticker: str
    company_name: str = ""
    price: float = 0.0
    change_pct: float = 0.0
    rvol: float = 0.0
    score: float = 0.0
    tier: str = "-"
    active_signals: list = field(default_factory=list)
    score_breakdown: dict = field(default_factory=dict)
    error: Optional[str] = None


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
    """
    Relative volume: today's volume vs average of previous N days.
    Uses the last row as 'today'.
    """
    if hist is None or len(hist) < 5:
        return 0.0
    volumes = hist["Volume"].dropna()
    if len(volumes) < 2:
        return 0.0
    today_vol = _safe_float(volumes.iloc[-1])
    avg_vol = _safe_float(volumes.iloc[-(lookback + 1):-1].mean())
    if avg_vol <= 0:
        return 0.0
    return round(today_vol / avg_vol, 2)


def _compute_adr(hist: pd.DataFrame, days: int = 20) -> float:
    """Average Daily Range % over last N days."""
    if hist is None or len(hist) < 5:
        return 0.0
    recent = hist.tail(days)
    highs = recent["High"].values
    lows = recent["Low"].values
    closes = recent["Close"].values
    ranges = []
    for h, l, c in zip(highs, lows, closes):
        if c > 0:
            ranges.append((h - l) / c * 100)
    if not ranges:
        return 0.0
    return round(float(np.mean(ranges)), 2)


def _compute_rs(stock_change: float, index_change: float) -> float:
    """Relative strength vs index."""
    return round(stock_change - index_change, 2)


def _compute_ema(series: pd.Series, span: int) -> pd.Series:
    return series.ewm(span=span, adjust=False).mean()


def _score_stock(ticker: str, hist: pd.DataFrame, index_change: float) -> StockResult:
    """Compute all signals and conviction score for a single stock."""
    result = StockResult(ticker=ticker)

    try:
        if hist is None or hist.empty or len(hist) < 10:
            result.error = "Yeterli veri yok"
            return result

        closes = hist["Close"].dropna()
        if len(closes) < 2:
            result.error = "Yeterli kapanış verisi yok"
            return result

        price = _safe_float(closes.iloc[-1])
        prev_close = _safe_float(closes.iloc[-2])
        result.price = round(price, 2)

        if prev_close > 0:
            result.change_pct = round((price - prev_close) / prev_close * 100, 2)

        # RVOL
        result.rvol = _compute_rvol(hist)

        # Gap up detection (change_pct as proxy for gap, using daily open if available)
        gap_pct = result.change_pct  # fallback: use day change
        if "Open" in hist.columns:
            today_open = _safe_float(hist["Open"].iloc[-1])
            if prev_close > 0 and today_open > 0:
                gap_pct = (today_open - prev_close) / prev_close * 100

        # RS vs XU100
        rs = _compute_rs(result.change_pct, index_change)

        # EMAs
        ema20 = _compute_ema(closes, 20)
        ema50 = _compute_ema(closes, 50) if len(closes) >= 50 else None

        # 52-week high
        high_52w = _safe_float(closes.tail(252).max())
        near_52w = high_52w > 0 and price >= high_52w * 0.95

        # ADR
        adr = _compute_adr(hist)

        # ── Active signals ───────────────────────────────────────────────
        active = []
        score = 0.0

        # Gap+RVOL combo (highest weight — must satisfy both)
        if gap_pct > 5.0 and result.rvol >= 3.0:
            active.append("gap_up_combo")
        else:
            # Individual gap signal
            if gap_pct > 3.0:
                active.append("gap_up")
            # Individual RVOL signals
            if result.rvol >= 3.0:
                active.append("rvol_3x")
            elif result.rvol >= 2.0:
                active.append("rvol_2x")

        # RS
        if rs >= 3.0:
            active.append("rs_strong")
        elif rs >= 1.0:
            active.append("rs_moderate")

        # Structure
        if ema20 is not None and price > _safe_float(ema20.iloc[-1]):
            active.append("above_ema20")
        if ema50 is not None and price > _safe_float(ema50.iloc[-1]):
            active.append("above_ema50")
        if near_52w:
            active.append("near_52w_high")

        # ADR
        if adr >= 3.0:
            active.append("adr_high")

        # ── Score calculation ────────────────────────────────────────────
        domains_hit = set()
        for sig in active:
            w = SIGNALS[sig]["weight"]
            score += w
            domains_hit.add(SIGNALS[sig]["domain"])

        base_score = score
        diversity_bonus = len(domains_hit) >= DOMAIN_DIVERSITY_MIN
        if diversity_bonus:
            score *= DOMAIN_DIVERSITY_MULTIPLIER

        result.score = round(score, 2)
        result.tier = _compute_tier(result.score)
        result.active_signals = [SIGNALS[s]["label"] for s in active]
        result.score_breakdown = {
            "signals": [
                {"label": SIGNALS[s]["label"], "weight": SIGNALS[s]["weight"]}
                for s in active
            ],
            "base_score": round(base_score, 2),
            "diversity_bonus": diversity_bonus,
            "final_score": result.score,
        }

    except Exception as e:
        logger.warning(f"Score error for {ticker}: {e}")
        result.error = str(e)

    return result


def run_scan(
    tickers: list[str],
    progress_callback=None,
    max_workers: int = 10,
) -> list[StockResult]:
    """
    Download data for all tickers and compute scores.
    Returns results sorted by score descending.
    
    progress_callback(done, total): called after each batch completes.
    """
    results = []
    total = len(tickers)

    # ── Step 1: Fetch XU100 index data ──────────────────────────────────
    logger.info("Fetching XU100 index data...")
    index_change = 0.0
    try:
        xu100 = yf.download("XU100.IS", period="5d", interval="1d", progress=False, auto_adjust=True)
        if xu100 is not None and len(xu100) >= 2:
            c = xu100["Close"].dropna()
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
    logger.info(f"Downloading data for {total} tickers in {len(ticker_batches)} batches...")

    for batch_idx, batch in enumerate(ticker_batches):
        try:
            batch_str = " ".join(batch)
            raw = yf.download(
                batch_str,
                period="1y",
                interval="1d",
                progress=False,
                auto_adjust=True,
                group_by="ticker",
                threads=True,
            )

            for ticker in batch:
                try:
                    if len(batch) == 1:
                        # Single ticker returns flat DataFrame
                        df = raw.copy() if not raw.empty else None
                    else:
                        # Multi-ticker returns MultiIndex
                        if ticker in raw.columns.get_level_values(0):
                            df = raw[ticker].copy()
                        else:
                            df = None
                    if df is not None and not df.empty:
                        df = df.dropna(how="all")
                        all_hist[ticker] = df
                except Exception as e:
                    logger.debug(f"Extract error {ticker}: {e}")

        except Exception as e:
            logger.warning(f"Batch {batch_idx} download error: {e}")

        done_count += len(batch)
        if progress_callback:
            progress_callback(done_count, total)

    # ── Step 3: Score all tickers ────────────────────────────────────────
    logger.info(f"Scoring {len(all_hist)} tickers with data...")

    with ThreadPoolExecutor(max_workers=max_workers) as executor:
        futures = {
            executor.submit(_score_stock, ticker, hist, index_change): ticker
            for ticker, hist in all_hist.items()
        }
        for future in as_completed(futures):
            try:
                result = future.result()
                results.append(result)
            except Exception as e:
                ticker = futures[future]
                logger.warning(f"Score future error {ticker}: {e}")
                results.append(StockResult(ticker=ticker, error=str(e)))

    # Add tickers we couldn't fetch at all
    fetched = set(all_hist.keys())
    for ticker in tickers:
        if ticker not in fetched:
            results.append(StockResult(ticker=ticker, error="Veri indirilemedi"))

    # Sort: scored stocks first (by score desc), then errored ones
    results.sort(key=lambda r: (r.error is None, r.score), reverse=True)

    scored = sum(1 for r in results if r.error is None)
    logger.info(f"Scan complete: {scored}/{total} stocks scored.")
    return results
