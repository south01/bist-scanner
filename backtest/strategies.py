"""backtest/strategies.py — Named backtest strategies and filter variants"""

STRATEGIES = {
    "vwap_stop": {
        "name": "VWAP Stop (Zarattini/Aziz)",
        "description": "Enter on gap-up with RVOL≥2. Stop when price closes below 20-day VWAP.",
        "entry_gap_min": 2.0,
        "entry_rvol_min": 2.0,
        "stop_type": "vwap",
        "max_hold_days": 10,
        "tp_atr_mult": None,  # hold until stop or max_hold
    },
    "atr_1x": {
        "name": "ATR×1 Stop",
        "description": "Enter on gap-up with RVOL≥2. Stop = entry − ATR×1.",
        "entry_gap_min": 2.0,
        "entry_rvol_min": 2.0,
        "stop_type": "atr",
        "atr_mult": 1.0,
        "max_hold_days": 10,
    },
    "atr_1_5x": {
        "name": "ATR×1.5 Stop",
        "description": "Enter on gap-up with RVOL≥2. Stop = entry − ATR×1.5.",
        "entry_gap_min": 2.0,
        "entry_rvol_min": 2.0,
        "stop_type": "atr",
        "atr_mult": 1.5,
        "max_hold_days": 10,
    },
    "fixed_2pct": {
        "name": "Fixed 2% Stop",
        "description": "Enter on gap-up with RVOL≥2. Stop = entry × 0.98.",
        "entry_gap_min": 2.0,
        "entry_rvol_min": 2.0,
        "stop_type": "fixed_pct",
        "stop_pct": 2.0,
        "max_hold_days": 10,
    },
}

# Filter sensitivity sweep: each filter toggled off independently
FILTER_VARIANTS = [
    {"name": "Baseline",             "entry_gap_min": 2.0, "entry_rvol_min": 2.0, "stop_type": "vwap"},
    {"name": "Gap ≥ 3%",             "entry_gap_min": 3.0, "entry_rvol_min": 2.0, "stop_type": "vwap"},
    {"name": "Gap ≥ 5% (strong)",    "entry_gap_min": 5.0, "entry_rvol_min": 2.0, "stop_type": "vwap"},
    {"name": "RVOL ≥ 1.5x",          "entry_gap_min": 2.0, "entry_rvol_min": 1.5, "stop_type": "vwap"},
    {"name": "RVOL ≥ 3x",            "entry_gap_min": 2.0, "entry_rvol_min": 3.0, "stop_type": "vwap"},
    {"name": "Gap ≥ 3% + RVOL ≥ 3x", "entry_gap_min": 3.0, "entry_rvol_min": 3.0, "stop_type": "vwap"},
]
