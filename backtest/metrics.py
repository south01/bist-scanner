"""backtest/metrics.py — Performance metrics for backtests"""
import math
import numpy as np


def compute_metrics(trades: list[dict]) -> dict:
    """
    Compute performance metrics from a list of trade dicts.
    Each trade must have: 'return_pct', 'outcome' ('win'|'loss'|'breakeven').
    """
    if not trades:
        return {"total_trades": 0, "win_rate": 0, "avg_return": 0,
                "profit_factor": 0, "sharpe": 0, "max_drawdown": 0,
                "expectancy": 0, "total_return": 0}

    returns = [t.get("return_pct", 0) for t in trades]
    wins    = [r for r in returns if r > 0]
    losses  = [r for r in returns if r < 0]

    total_trades = len(returns)
    win_rate     = len(wins) / total_trades if total_trades else 0
    avg_return   = float(np.mean(returns)) if returns else 0

    gross_profit = sum(wins)  if wins   else 0
    gross_loss   = abs(sum(losses)) if losses else 0
    profit_factor = gross_profit / gross_loss if gross_loss > 0 else float("inf")

    # Sharpe (annualized, assume 252 trading days, using daily returns)
    if len(returns) > 1:
        std = float(np.std(returns, ddof=1))
        sharpe = (avg_return / std * math.sqrt(252)) if std > 0 else 0
    else:
        sharpe = 0

    # Max drawdown from equity curve
    equity = [1.0]
    for r in returns:
        equity.append(equity[-1] * (1 + r / 100))
    peak = equity[0]
    max_dd = 0.0
    for e in equity:
        if e > peak:
            peak = e
        dd = (peak - e) / peak
        if dd > max_dd:
            max_dd = dd

    # Expectancy: win_rate × avg_win + (1-win_rate) × avg_loss
    avg_win  = float(np.mean(wins))   if wins   else 0
    avg_loss = float(np.mean(losses)) if losses else 0
    expectancy = win_rate * avg_win + (1 - win_rate) * avg_loss

    total_return = (equity[-1] - 1) * 100

    return {
        "total_trades":  total_trades,
        "win_rate":      round(win_rate * 100, 1),
        "avg_return":    round(avg_return, 2),
        "avg_win":       round(avg_win, 2),
        "avg_loss":      round(avg_loss, 2),
        "profit_factor": round(profit_factor, 2) if math.isfinite(profit_factor) else 99.0,
        "sharpe":        round(sharpe, 2),
        "max_drawdown":  round(max_dd * 100, 2),
        "expectancy":    round(expectancy, 2),
        "total_return":  round(total_return, 2),
        "gross_profit":  round(gross_profit, 2),
        "gross_loss":    round(gross_loss, 2),
        "equity_curve":  [round(e, 4) for e in equity],
    }
