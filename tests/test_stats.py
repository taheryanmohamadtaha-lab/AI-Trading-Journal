from app.analytics.stats import compute_stats, group_stats

T = [{"pnl": p, "closed_at": f"2026-01-{i+1:02d}", "r_multiple": r, "market": m}
     for i, (p, r, m) in enumerate([(100, 2, "forex"), (-50, -1, "forex"),
                                    (-50, -1, "crypto"), (200, 2, "crypto"),
                                    (-100, None, "forex")])]


def test_core_stats():
    s = compute_stats(T, initial_balance=1000)
    assert s["total_trades"] == 5 and s["winning_trades"] == 2
    assert s["win_rate"] == 40.0
    assert s["net_profit"] == 100
    assert s["gross_profit"] == 300 and s["gross_loss"] == 200
    assert s["profit_factor"] == 1.5
    assert s["average_r"] == 0.5 and s["r_sample_size"] == 4
    assert s["max_consecutive_losses"] == 2
    # equity 1100,1050,1000,1200,1100 -> peak1200, trough/last 1100 => dd 100
    assert s["max_drawdown"] == 100
    assert s["low_sample_warning"] is True


def test_empty_and_open_trades_ignored():
    assert compute_stats([])["total_trades"] == 0
    assert compute_stats([{"pnl": None}])["total_trades"] == 0


def test_groups_have_own_sample_size():
    g = group_stats(T, "market")
    assert g["forex"]["total_trades"] == 3 and g["crypto"]["total_trades"] == 2
