from app.ai_engine.coach import (review_trade, analyze_period, evaluate_goals,
                                 render_report_text, facts_for_ai, metric_value)
from app.database.db import Database
from app.services.trade_service import build_trade


def T(i, pnl, qty=1.0, **kw):
    base = dict(id=i, market="forex", symbol="EURUSD", side="buy", status="closed", quantity=qty,
                entry_price=1.1, exit_price=1.101, stop_loss=1.095, take_profit=1.11,
                opened_at=f"2026-03-{i:02d} 10:00", closed_at=f"2026-03-{i:02d} 12:00",
                pnl=pnl, r_multiple=pnl / 100 if pnl is not None else None, risk_amount=100.0,
                strategy="A", followed_plan=None, mood=None, fomo=0, revenge=0, rushed=0,
                early_exit=0, moved_sl=0)
    base.update(kw)
    return base


def texts(findings, level=None):
    return [f["text"] for f in findings if level in (None, f["level"])]


def test_review_flags_planned_rr_and_missing_sl():
    f = review_trade(T(1, 200, take_profit=1.11))
    assert any("2.00" in x for x in texts(f, "good"))
    assert any("حد ضرر ثبت نشده" in x for x in texts(review_trade(T(1, 50, stop_loss=None)), "warn"))


def test_review_detects_larger_than_planned_loss_and_early_exit():
    assert any("بیشتر" in x for x in texts(review_trade(T(1, -150)), "warn"))
    f = review_trade(T(2, 40, exit_price=1.104))      # 40% of the way to TP
    assert any("40" in x and "تارگت" in x for x in texts(f))


def test_review_behavior_and_size_after_loss():
    prev = [T(1, -80, qty=1.0)]
    f = review_trade(T(2, 50, qty=2.0, followed_plan=0, revenge=1), prev)
    w = texts(f, "warn")
    assert any("برنامه" in x for x in w) and any("انتقام" in x for x in w)
    assert any("حجم" in x for x in w)


def test_small_sample_reports_no_groups_and_warns():
    rep = analyze_period([T(i, 50 if i % 2 else -40) for i in range(1, 7)])
    assert rep["low_sample"] and rep["groups"].get("strategy") is None
    assert "کمتر از 30" in render_report_text(rep).replace("۳۰", "30")


def test_detects_size_increase_after_loss_pattern():
    ts, q = [], 1.0
    for i in range(1, 15):
        pnl = -50 if i % 2 else 80
        ts.append(T(i, pnl, qty=q))
        q = 2.0 if pnl < 0 else 1.0       # doubles after every loss
    rep = analyze_period(ts)
    assert any("افزایش یافته" in p["text"] for p in rep["patterns"])
    assert any("افزایش حجم" in w["text"] for w in rep["weaknesses"])


def test_plan_adherence_and_strategy_groups():
    ts = [T(i, 100 if i <= 6 else -60, followed_plan=1 if i <= 6 else 0,
            strategy="Good" if i <= 6 else "Bad") for i in range(1, 13)]
    rep = analyze_period(ts)
    assert rep["plan_adherence"] == 50.0
    assert any("طبق‌برنامه" in p["text"] for p in rep["patterns"])
    assert rep["groups"]["strategy"][0]["key"] == "Good"
    assert any("Bad" in w["text"] for w in rep["weaknesses"])
    assert all(len(rep[k]) <= 3 for k in ("strengths", "weaknesses"))


def test_missing_sl_creates_measurable_goal_suggestion():
    rep = analyze_period([T(i, 10, stop_loss=None) for i in range(1, 9)])
    assert any(s["goal"] and s["goal"]["metric"] == "sl_usage_rate" for s in rep["suggestions"])


def test_comparison_and_facts_have_no_raw_trades():
    cur = [T(i, 50) for i in range(10, 16)]
    prev = [T(i, -20) for i in range(1, 7)]
    rep = analyze_period(cur, prev)
    assert rep["comparison"]["previous_n"] == 6
    facts = str(facts_for_ai(rep))
    assert "EURUSD" not in facts and "opened_at" not in facts


def test_goals_evaluation():
    db = Database()
    db.add_goal("win_rate", ">=", 50); db.add_goal("max_consecutive_losses", "<=", 1)
    ts = [T(1, 10), T(2, -5), T(3, -5), T(4, 10)]
    res = {g["metric"]: g for g in evaluate_goals(db.list_goals(), ts)}
    assert res["win_rate"]["met"] is True and res["max_consecutive_losses"]["met"] is False
    assert metric_value("plan_adherence", ts) is None


def test_behavior_saved_through_build_trade_and_db():
    db = Database()
    t = build_trade(dict(market="forex", side="buy", symbol="EURUSD", quantity="1", entry_price="1.1",
                         exit_price="1.101", opened_at="2026-01-01 10:00", closed_at="2026-01-01 11:00",
                         followed_plan=0, mood=2, fomo=1, entry_reason="خبر", lesson="صبر"))
    tid = db.add_trade(t)
    row = db.get_trade(tid)
    assert (row["followed_plan"], row["mood"], row["fomo"], row["entry_reason"]) == (0, 2, 1, "خبر")
    db.update_behavior(tid, {"moved_sl": 1, "lesson": "x"})
    assert db.get_trade(tid)["moved_sl"] == 1
