"""Performance statistics computed from real closed trades only."""
from __future__ import annotations
from collections import defaultdict


def compute_stats(trades: list[dict], initial_balance: float = 0.0) -> dict:
    """trades: dicts with 'pnl' (float), optional 'r_multiple', 'closed_at'
    (sortable). Only trades with a numeric pnl are counted."""
    closed = [t for t in trades if t.get("pnl") is not None]
    closed.sort(key=lambda t: t.get("closed_at") or "")
    n = len(closed)
    if n == 0:
        return {"total_trades": 0, "sample_note": "no closed trades"}
    pnls = [float(t["pnl"]) for t in closed]
    wins = [p for p in pnls if p > 0]
    losses = [p for p in pnls if p < 0]
    gross_profit, gross_loss = sum(wins), -sum(losses)

    equity, peak = initial_balance, initial_balance
    max_dd, max_dd_pct, curve = 0.0, 0.0, []
    for p in pnls:
        equity += p
        curve.append(equity)
        peak = max(peak, equity)
        dd = peak - equity
        max_dd = max(max_dd, dd)
        if peak > 0:
            max_dd_pct = max(max_dd_pct, dd / peak * 100)

    best_w = best_l = cur_w = cur_l = 0
    for p in pnls:
        cur_w = cur_w + 1 if p > 0 else 0
        cur_l = cur_l + 1 if p < 0 else 0
        best_w, best_l = max(best_w, cur_w), max(best_l, cur_l)

    rs = [float(t["r_multiple"]) for t in closed if t.get("r_multiple") is not None]
    win_rate = len(wins) / n
    avg_win = gross_profit / len(wins) if wins else 0.0
    avg_loss = gross_loss / len(losses) if losses else 0.0
    return {
        "total_trades": n,
        "winning_trades": len(wins),
        "losing_trades": len(losses),
        "win_rate": win_rate * 100,
        "loss_rate": len(losses) / n * 100,
        "net_profit": sum(pnls),
        "gross_profit": gross_profit,
        "gross_loss": gross_loss,
        "profit_factor": (gross_profit / gross_loss) if gross_loss else None,
        "average_win": avg_win,
        "average_loss": avg_loss,
        "expected_value": win_rate * avg_win - (1 - win_rate) * avg_loss,
        "average_r": (sum(rs) / len(rs)) if rs else None,
        "r_sample_size": len(rs),
        "max_drawdown": max_dd,
        "max_drawdown_percent": max_dd_pct,
        "max_consecutive_wins": best_w,
        "max_consecutive_losses": best_l,
        "equity_curve": curve,
        "low_sample_warning": n < 30,
    }


def group_stats(trades: list[dict], key: str, initial_balance=0.0) -> dict:
    """Stats per category (market, symbol, strategy, weekday...). Each group
    carries its own sample size so the UI/coach can warn about small n."""
    groups = defaultdict(list)
    for t in trades:
        groups[t.get(key) or "unspecified"].append(t)
    return {k: compute_stats(v, initial_balance) for k, v in groups.items()}
