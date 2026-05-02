"""db/database.py — SQLite persistence for BIST Scanner v2.0"""
import json, logging, os, sqlite3
from contextlib import contextmanager
from datetime import datetime

logger = logging.getLogger(__name__)

# Railway persistent volume: /app/data; local fallback: ./data
_DATA_DIR = os.environ.get("DATA_DIR", os.path.join(os.path.dirname(os.path.dirname(__file__)), "data"))
DB_PATH = os.path.join(_DATA_DIR, "bist_scanner.db")

CREATE_TABLES = """
CREATE TABLE IF NOT EXISTS signal_history (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    ticker      TEXT NOT NULL,
    scanned_at  TEXT NOT NULL,
    score       REAL,
    tier        TEXT,
    regime_score    REAL,
    momentum_score  REAL,
    structure_score REAL,
    smartmoney_score REAL,
    catalyst_score  REAL,
    price       REAL,
    change_pct  REAL,
    rvol        REAL,
    signals     TEXT,
    reasoning   TEXT
);

CREATE TABLE IF NOT EXISTS rvol_baseline (
    ticker      TEXT NOT NULL,
    date        TEXT NOT NULL,
    avg_vol_20  REAL,
    updated_at  TEXT NOT NULL,
    PRIMARY KEY (ticker, date)
);

CREATE TABLE IF NOT EXISTS scan_metadata (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    started_at  TEXT NOT NULL,
    finished_at TEXT,
    ticker_count INTEGER,
    scored_count INTEGER,
    xu100_change REAL
);

CREATE TABLE IF NOT EXISTS backtest_results (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    run_at      TEXT NOT NULL,
    config      TEXT NOT NULL,
    metrics     TEXT NOT NULL,
    trades      TEXT NOT NULL,
    sweep       TEXT
);
"""

def init_db():
    os.makedirs(_DATA_DIR, exist_ok=True)
    with sqlite3.connect(DB_PATH) as con:
        con.executescript(CREATE_TABLES)
    logger.info(f"DB initialized at {DB_PATH}")

@contextmanager
def get_con():
    con = sqlite3.connect(DB_PATH)
    con.row_factory = sqlite3.Row
    try:
        yield con
        con.commit()
    except Exception:
        con.rollback()
        raise
    finally:
        con.close()

def save_signal_history(records: list[dict]):
    """Bulk-insert scored stocks from a scan run."""
    with get_con() as con:
        now = datetime.utcnow().isoformat()
        con.executemany("""
            INSERT INTO signal_history
            (ticker, scanned_at, score, tier, regime_score, momentum_score, structure_score,
             smartmoney_score, catalyst_score, price, change_pct, rvol, signals, reasoning)
            VALUES (:ticker, :scanned_at, :score, :tier, :regime_score, :momentum_score,
             :structure_score, :smartmoney_score, :catalyst_score, :price, :change_pct,
             :rvol, :signals, :reasoning)
        """, [
            {**r, "scanned_at": now,
             "signals": json.dumps(r.get("signals", []), ensure_ascii=False),
             "reasoning": r.get("reasoning", "")}
            for r in records
        ])

def get_recent_signals(limit: int = 50) -> list[dict]:
    with get_con() as con:
        rows = con.execute("""
            SELECT * FROM signal_history ORDER BY scanned_at DESC LIMIT ?
        """, (limit,)).fetchall()
    return [dict(r) for r in rows]

def save_backtest_result(config: dict, metrics: dict, trades: list, sweep: dict | None = None) -> int:
    with get_con() as con:
        cur = con.execute("""
            INSERT INTO backtest_results (run_at, config, metrics, trades, sweep)
            VALUES (?, ?, ?, ?, ?)
        """, (
            datetime.utcnow().isoformat(),
            json.dumps(config),
            json.dumps(metrics),
            json.dumps(trades),
            json.dumps(sweep) if sweep else None,
        ))
        return cur.lastrowid

def get_backtest_result(result_id: int) -> dict | None:
    with get_con() as con:
        row = con.execute("SELECT * FROM backtest_results WHERE id=?", (result_id,)).fetchone()
    if not row:
        return None
    d = dict(row)
    d["config"]  = json.loads(d["config"])
    d["metrics"] = json.loads(d["metrics"])
    d["trades"]  = json.loads(d["trades"])
    d["sweep"]   = json.loads(d["sweep"]) if d.get("sweep") else None
    return d

def list_backtest_results(limit: int = 20) -> list[dict]:
    with get_con() as con:
        rows = con.execute("""
            SELECT id, run_at, config, metrics FROM backtest_results
            ORDER BY run_at DESC LIMIT ?
        """, (limit,)).fetchall()
    out = []
    for r in rows:
        d = dict(r)
        d["config"]  = json.loads(d["config"])
        d["metrics"] = json.loads(d["metrics"])
        out.append(d)
    return out
