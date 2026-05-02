"""
app.py — FastAPI backend for BIST Conviction Scanner v2.0.
Run locally: uvicorn app:app --reload --port 5050
"""

import json
import logging
import os
import threading
import time
from contextlib import asynccontextmanager
from datetime import datetime
from typing import Optional

import pytz
from fastapi import FastAPI, HTTPException, Request, BackgroundTasks
from fastapi.responses import HTMLResponse, JSONResponse, StreamingResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates

from scorer import run_scan, StockResult
from tickers import get_bist_tickers, get_ticker_info
from db.database import init_db, save_signal_history, get_recent_signals
from db.database import save_backtest_result, get_backtest_result, list_backtest_results
from analysis.tier1 import generate_signal
from indicators.scoring import compute_composite, generate_score_breakdown

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
)
logger = logging.getLogger(__name__)

APP_VERSION  = "2.1.0"  # bump this on each release

TZ_ISTANBUL  = pytz.timezone("Europe/Istanbul")
TZ_KITCHENER = pytz.timezone("America/Toronto")


def _format_time(dt: datetime, tz) -> str:
    return dt.astimezone(tz).strftime("%d.%m.%Y %H:%M")


# ── Scan state ────────────────────────────────────────────────────────────────
_scan_lock  = threading.Lock()
_scan_state = {
    "running": False,
    "progress": 0,
    "total": 0,
    "results": [],
    "last_scan_adana": None,
    "last_scan_kitchener": None,
    "error": None,
}


def _progress_callback(done: int, total: int):
    with _scan_lock:
        _scan_state["progress"] = done
        _scan_state["total"]    = total


def _serialize_results(results: list[StockResult]) -> list[dict]:
    out = []
    for i, r in enumerate(results):
        if r.error:
            continue
        out.append({
            "rank":          i + 1,
            "ticker":        r.ticker.replace(".IS", ""),
            "ticker_full":   r.ticker,
            "company_name":  r.company_name or r.ticker.replace(".IS", ""),
            "price":         r.price,
            "change_pct":    r.change_pct,
            "rvol":          r.rvol,
            "score":         r.score,
            "tier":          r.tier,
            "signals":       r.active_signals,
            "score_breakdown": r.score_breakdown,
            "adr":           r.adr,
            # v2.0 five-set scores
            "regime_score":      r.regime_score,
            "momentum_score":    r.momentum_score,
            "structure_score":   r.structure_score,
            "smart_money_score": r.smart_money_score,
            "catalyst_score":    r.catalyst_score,
            "reasoning":         r.reasoning,
            "vwap":              r.vwap_data.get("vwap") if r.vwap_data else None,
            "above_vwap":        r.vwap_data.get("above_vwap") if r.vwap_data else None,
        })
    for i, item in enumerate(out):
        item["rank"] = i + 1
    return out


def _do_scan():
    with _scan_lock:
        _scan_state.update(running=True, progress=0, total=0, results=[], error=None)

    try:
        tickers = get_bist_tickers()
        with _scan_lock:
            _scan_state["total"] = len(tickers)

        logger.info(f"Starting scan: {len(tickers)} tickers")
        results = run_scan(tickers, progress_callback=_progress_callback)

        now_utc    = datetime.now(pytz.utc)
        serialized = _serialize_results(results)

        # Persist to DB
        try:
            save_signal_history([
                {
                    "ticker":          r.ticker,
                    "score":           r.score,
                    "tier":            r.tier,
                    "regime_score":    r.regime_score,
                    "momentum_score":  r.momentum_score,
                    "structure_score": r.structure_score,
                    "smartmoney_score": r.smart_money_score,
                    "catalyst_score":  r.catalyst_score,
                    "price":           r.price,
                    "change_pct":      r.change_pct,
                    "rvol":            r.rvol,
                    "signals":         r.active_signals,
                    "reasoning":       r.reasoning,
                }
                for r in results if r.error is None
            ])
        except Exception as e:
            logger.warning(f"DB save error: {e}")

        with _scan_lock:
            _scan_state.update(
                results=serialized,
                last_scan_adana=_format_time(now_utc, TZ_ISTANBUL),
                last_scan_kitchener=_format_time(now_utc, TZ_KITCHENER),
                running=False,
                progress=len(tickers),
            )

    except Exception as e:
        logger.error(f"Scan error: {e}", exc_info=True)
        with _scan_lock:
            _scan_state.update(error=f"Tarama hatası: {str(e)}", running=False)


# ── Lifespan ──────────────────────────────────────────────────────────────────
@asynccontextmanager
async def lifespan(app: FastAPI):
    # Startup
    init_db()
    try:
        tickers = get_bist_tickers()
        logger.info(f"Ticker cache ready: {len(tickers)} tickers")
    except Exception as e:
        logger.warning(f"Ticker pre-warm error: {e}")
    yield
    # Shutdown (nothing to clean up)


app = FastAPI(title="BIST Tarayıcı v2.0", lifespan=lifespan)

# Static files + templates
_BASE_DIR = os.path.dirname(__file__)
app.mount("/static", StaticFiles(directory=os.path.join(_BASE_DIR, "static")), name="static")
templates = Jinja2Templates(directory=os.path.join(_BASE_DIR, "templates"))
# Add enumerate filter for Jinja2 (used in backtest_results.html)
templates.env.globals["enumerate"] = enumerate


# ── Routes ────────────────────────────────────────────────────────────────────

@app.get("/", response_class=HTMLResponse)
async def index(request: Request):
    return templates.TemplateResponse(request, "index.html", {"app_version": APP_VERSION})


@app.post("/api/scan")
async def start_scan():
    with _scan_lock:
        if _scan_state["running"]:
            return JSONResponse(
                {"ok": False, "message": "Tarama zaten devam ediyor."},
                status_code=409,
            )
    thread = threading.Thread(target=_do_scan, daemon=True)
    thread.start()
    return {"ok": True, "message": "Tarama başlatıldı."}


@app.get("/api/status")
async def scan_status():
    with _scan_lock:
        return dict(_scan_state)


@app.get("/api/results")
async def get_results():
    with _scan_lock:
        return {
            "results":             _scan_state["results"],
            "last_scan_adana":     _scan_state["last_scan_adana"],
            "last_scan_kitchener": _scan_state["last_scan_kitchener"],
            "count":               len(_scan_state["results"]),
            "version":             APP_VERSION,
        }


@app.get("/api/ticker-info")
async def ticker_info():
    return get_ticker_info()


@app.post("/api/refresh-tickers")
async def refresh_tickers():
    try:
        tickers = get_bist_tickers(force_refresh=True)
        return {"ok": True, "count": len(tickers)}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


# ── Analysis endpoint ─────────────────────────────────────────────────────────

@app.get("/analyze/{ticker}", response_class=HTMLResponse)
async def analyze_page(request: Request, ticker: str):
    return templates.TemplateResponse(request, "analysis.html", {
        "ticker": ticker.upper(),
    })


@app.get("/api/analyze/{ticker}")
async def api_analyze(ticker: str):
    """Full analysis for a single ticker: five-set scores + signal + VWAP chart data."""
    import yfinance as yf
    import pandas as pd
    import numpy as np

    ticker_yf = ticker.upper()
    if not ticker_yf.endswith(".IS"):
        ticker_yf = ticker_yf + ".IS"

    try:
        hist = yf.download(
            ticker_yf, period="1y", interval="1d",
            progress=False, auto_adjust=True,
        )
        if hist is None or hist.empty:
            raise HTTPException(status_code=404, detail="Hisse verisi bulunamadı")

        xu100 = yf.download(
            "XU100.IS", period="1y", interval="1d",
            progress=False, auto_adjust=True,
        )
        index_change = 0.0
        if xu100 is not None and len(xu100) >= 2:
            c = xu100["Close"].dropna()
            if len(c) >= 2:
                index_change = float((c.iloc[-1] - c.iloc[-2]) / c.iloc[-2] * 100)

        comp    = compute_composite(ticker_yf, hist, xu100, index_change)
        signal  = generate_signal(comp, hist)
        breakdown = generate_score_breakdown(comp)

        # Build candlestick series for chart
        candles = []
        closes  = hist["Close"].dropna()
        for idx, row in hist.tail(60).iterrows():
            try:
                candles.append({
                    "time":  str(idx.date()),
                    "open":  round(float(row["Open"]), 2),
                    "high":  round(float(row["High"]), 2),
                    "low":   round(float(row["Low"]), 2),
                    "close": round(float(row["Close"]), 2),
                })
            except Exception:
                pass

        vwap_data = comp.get("vwap_data", {})

        return {
            "ticker":     ticker.upper(),
            "ticker_yf":  ticker_yf,
            "composite":  comp["score"],
            "tier":       comp["tier"],
            "breakdown":  breakdown,
            "signal":     signal,
            "regime":     comp.get("regime_details", {}),
            "momentum":   comp.get("momentum_details", {}),
            "structure":  comp.get("structure_details", {}),
            "vwap":       {
                "vwap":        vwap_data.get("vwap"),
                "upper1":      vwap_data.get("vwap_upper1"),
                "lower1":      vwap_data.get("vwap_lower1"),
                "upper2":      vwap_data.get("vwap_upper2"),
                "lower2":      vwap_data.get("vwap_lower2"),
                "above_vwap":  vwap_data.get("above_vwap"),
                "series":      vwap_data.get("series", []),
            },
            "candles":    candles,
            "reasoning":  comp.get("reasoning", ""),
            "xu100_change": round(index_change, 2),
        }

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Analyze error for {ticker}: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=str(e))


# ── Backtest endpoints ─────────────────────────────────────────────────────────

@app.get("/backtest", response_class=HTMLResponse)
async def backtest_page(request: Request):
    runs = list_backtest_results(limit=10)
    return templates.TemplateResponse(request, "backtest.html", {
        "recent_runs": runs,
    })


@app.post("/api/backtest/run")
async def run_backtest(request: Request):
    body = await request.json()
    ticker       = body.get("ticker", "").upper().strip()
    strategy     = body.get("strategy", "vwap_stop")
    run_sweep    = body.get("run_sweep", False)
    multi_stop   = body.get("multi_stop", True)

    if not ticker:
        raise HTTPException(status_code=422, detail="Ticker gerekli")

    ticker_yf = ticker if ticker.endswith(".IS") else ticker + ".IS"

    from backtest.engine import run_full_backtest, run_multi_stop_comparison, run_filter_sweep

    result = run_full_backtest(ticker_yf, strategy_name=strategy)
    if "error" in result:
        raise HTTPException(status_code=404, detail=result["error"])

    comparison = None
    if multi_stop:
        comparison = run_multi_stop_comparison(ticker_yf)

    sweep = None
    if run_sweep:
        sweep = run_filter_sweep([ticker_yf], max_workers=4)

    config = {
        "ticker":    ticker_yf,
        "strategy":  strategy,
        "multi_stop": multi_stop,
        "run_sweep": run_sweep,
    }
    result_id = save_backtest_result(
        config=config,
        metrics=result["metrics"],
        trades=result["trades"],
        sweep=sweep,
    )

    return {
        "ok":          True,
        "result_id":   result_id,
        "metrics":     result["metrics"],
        "comparison":  comparison,
        "sweep":       sweep,
        "trades":      result["trades"][:50],  # first 50 for preview
        "trade_count": len(result["trades"]),
    }


@app.get("/backtest/result/{result_id}", response_class=HTMLResponse)
async def backtest_result_page(request: Request, result_id: int):
    data = get_backtest_result(result_id)
    if not data:
        raise HTTPException(status_code=404, detail="Backtest sonucu bulunamadı")
    return templates.TemplateResponse(request, "backtest_results.html", {
        "result_id": result_id,
        "data":      data,
    })


@app.get("/api/backtest/result/{result_id}")
async def api_backtest_result(result_id: int):
    data = get_backtest_result(result_id)
    if not data:
        raise HTTPException(status_code=404, detail="Backtest sonucu bulunamadı")
    return data


@app.get("/api/backtest/list")
async def api_backtest_list():
    return {"runs": list_backtest_results(limit=20)}


@app.get("/health")
async def health():
    return {"status": "ok", "version": APP_VERSION}


# ── Dev entry point ───────────────────────────────────────────────────────────
if __name__ == "__main__":
    import uvicorn
    port = int(os.environ.get("PORT", 5050))
    uvicorn.run("app:app", host="0.0.0.0", port=port, reload=False)
