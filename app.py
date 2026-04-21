"""
app.py — Flask backend for BIST Conviction Scanner.
Run with: python app.py
"""

import json
import logging
import threading
import time
from datetime import datetime

import pytz
from flask import Flask, jsonify, render_template, request

from scorer import run_scan, StockResult
from tickers import get_bist_tickers, get_ticker_info

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
)
logger = logging.getLogger(__name__)

app = Flask(__name__)

# ── Scan state ───────────────────────────────────────────────────────────────
_scan_lock = threading.Lock()
_scan_state = {
    "running": False,
    "progress": 0,
    "total": 0,
    "results": [],
    "last_scan_adana": None,   # UTC+3
    "last_scan_kitchener": None,
    "error": None,
}

TZ_ADANA = pytz.timezone("Europe/Istanbul")      # UTC+3
TZ_KITCHENER = pytz.timezone("America/Toronto")  # Eastern (handles DST)


def _format_time(dt: datetime, tz) -> str:
    local = dt.astimezone(tz)
    return local.strftime("%d.%m.%Y %H:%M")


def _progress_callback(done: int, total: int):
    with _scan_lock:
        _scan_state["progress"] = done
        _scan_state["total"] = total


def _do_scan():
    """Background thread: fetch tickers, run scan, update state."""
    with _scan_lock:
        _scan_state["running"] = True
        _scan_state["progress"] = 0
        _scan_state["total"] = 0
        _scan_state["results"] = []
        _scan_state["error"] = None

    try:
        tickers = get_bist_tickers()
        with _scan_lock:
            _scan_state["total"] = len(tickers)

        logger.info(f"Starting scan: {len(tickers)} tickers")
        results = run_scan(tickers, progress_callback=_progress_callback)

        now_utc = datetime.now(pytz.utc)
        serialized = _serialize_results(results)

        with _scan_lock:
            _scan_state["results"] = serialized
            _scan_state["last_scan_adana"] = _format_time(now_utc, TZ_ADANA)
            _scan_state["last_scan_kitchener"] = _format_time(now_utc, TZ_KITCHENER)
            _scan_state["running"] = False
            _scan_state["progress"] = len(tickers)

    except Exception as e:
        logger.error(f"Scan error: {e}", exc_info=True)
        with _scan_lock:
            _scan_state["error"] = f"Tarama hatası: {str(e)}"
            _scan_state["running"] = False


def _serialize_results(results: list[StockResult]) -> list[dict]:
    """Convert StockResult objects to JSON-serializable dicts."""
    out = []
    for i, r in enumerate(results):
        if r.error:
            continue  # Skip errored stocks from display
        out.append({
            "rank": i + 1,
            "ticker": r.ticker.replace(".IS", ""),
            "ticker_full": r.ticker,
            "company_name": r.company_name or r.ticker.replace(".IS", ""),
            "price": r.price,
            "change_pct": r.change_pct,
            "rvol": r.rvol,
            "score": r.score,
            "tier": r.tier,
            "signals": r.active_signals,
        })
    # Re-rank after filtering
    for i, item in enumerate(out):
        item["rank"] = i + 1
    return out


# ── Routes ───────────────────────────────────────────────────────────────────

@app.route("/")
def index():
    return render_template("index.html")


@app.route("/api/scan", methods=["POST"])
def start_scan():
    with _scan_lock:
        if _scan_state["running"]:
            return jsonify({"ok": False, "message": "Tarama zaten devam ediyor."}), 409

    thread = threading.Thread(target=_do_scan, daemon=True)
    thread.start()
    return jsonify({"ok": True, "message": "Tarama başlatıldı."})


@app.route("/api/status")
def scan_status():
    with _scan_lock:
        state = dict(_scan_state)
    return jsonify(state)


@app.route("/api/results")
def get_results():
    with _scan_lock:
        results = _scan_state["results"]
        last_adana = _scan_state["last_scan_adana"]
        last_kitchener = _scan_state["last_scan_kitchener"]
    return jsonify({
        "results": results,
        "last_scan_adana": last_adana,
        "last_scan_kitchener": last_kitchener,
        "count": len(results),
    })


@app.route("/api/ticker-info")
def ticker_info():
    info = get_ticker_info()
    return jsonify(info)


@app.route("/api/refresh-tickers", methods=["POST"])
def refresh_tickers():
    """Force-refresh the ticker cache."""
    try:
        tickers = get_bist_tickers(force_refresh=True)
        return jsonify({"ok": True, "count": len(tickers)})
    except Exception as e:
        return jsonify({"ok": False, "error": str(e)}), 500


if __name__ == "__main__":
    logger.info("BIST Conviction Scanner başlatılıyor...")
    # Pre-warm ticker cache on startup
    try:
        tickers = get_bist_tickers()
        logger.info(f"Ticker listesi hazır: {len(tickers)} hisse")
    except Exception as e:
        logger.warning(f"Ticker ön yükleme hatası: {e}")

    app.run(host="127.0.0.1", port=5050, debug=False)
