"""Offline (rule-based) trading coach. Everything here is deterministic and
works without internet or any AI model. Findings always carry sample sizes,
and wording distinguishes correlation from cause."""
from __future__ import annotations
import datetime
from app.analytics.stats import compute_stats

MIN_GROUP = 5          # minimum trades before a group is reported
LOW_SAMPLE = 30        # below this, conclusions are tentative
DISCLAIMER = "این گزارش گذشته‌نگر است و تضمین‌کننده‌ی نتیجه‌ی آینده نیست؛ ارتباط‌های آماری لزوماً رابطه‌ی علت و معلولی نیستند."

FLAG_LABELS = {"fomo": "ترس از دست دادن فرصت (FOMO)", "revenge": "انتقام از بازار",
               "rushed": "ورود عجولانه", "early_exit": "خروج زودهنگام", "moved_sl": "جابه‌جایی حد ضرر"}
WEEKDAYS = ["دوشنبه", "سه‌شنبه", "چهارشنبه", "پنجشنبه", "جمعه", "شنبه", "یکشنبه"]


# ------------------------------------------------------------------ helpers
def closed_trades(trades):
    ts = [t for t in trades if t.get("pnl") is not None]
    return sorted(ts, key=lambda t: (t.get("closed_at") or t.get("opened_at") or "", t.get("id") or 0))


def _wr(ts):
    return sum(1 for t in ts if t["pnl"] > 0) / len(ts) * 100 if ts else 0.0


def _avg(ts, k="pnl"):
    v = [t[k] for t in ts if t.get(k) is not None]
    return sum(v) / len(v) if v else None


def _sign(side):
    return 1 if side == "buy" else -1


def _weekday(t):
    try:
        return WEEKDAYS[datetime.datetime.strptime((t.get("opened_at") or "")[:10], "%Y-%m-%d").weekday()]
    except ValueError:
        return None


def _hour(t):
    s = (t.get("opened_at") or "")
    return f"{s[11:13]}:00" if len(s) >= 13 and s[11:13].isdigit() else None


def _f(level, text):
    return {"level": level, "text": text}


# ------------------------------------------------------- single trade review
def review_trade(t: dict, previous: list[dict] | None = None) -> list[dict]:
    """Findings for one trade. `previous` = earlier trades (any order)."""
    out = []
    sg = _sign(t["side"])
    entry, sl, tp, ex = t["entry_price"], t.get("stop_loss"), t.get("take_profit"), t.get("exit_price")

    if sl is None:
        out.append(_f("warn", "حد ضرر ثبت نشده؛ ریسک این معامله قابل اندازه‌گیری نیست."))
    elif tp is not None:
        risk, reward = (entry - sl) * sg, (tp - entry) * sg
        if risk > 0 and reward > 0:
            rr = round(reward / risk, 6)   # avoid float edge cases at exactly 2.0
            lvl = "good" if rr >= 2 else ("warn" if rr < 1 else "info")
            out.append(_f(lvl, f"نسبت ریسک به بازده برنامه‌ریزی‌شده: {rr:.2f}."))
    if t.get("risk_amount") is None and sl is not None:
        out.append(_f("info", "مبلغ ریسک نامشخص است، پس R محاسبه نشد."))

    if t.get("pnl") is not None and ex is not None:
        r = t.get("r_multiple")
        if r is not None:
            out.append(_f("info", f"نتیجه‌ی معامله: {r:.2f}R."))
            if sl is not None and r < -1.05:
                out.append(_f("warn", "ضرر از ریسک برنامه‌ریزی‌شده بیشتر شده (اسلیپیج یا جابه‌جایی/حذف حد ضرر محتمل است)."))
        if tp is not None and t["pnl"] > 0:
            if (ex - tp) * sg >= 0:
                out.append(_f("good", "معامله به تارگت رسید."))
            elif (tp - entry) * sg > 0:
                frac = (ex - entry) * sg / ((tp - entry) * sg)
                out.append(_f("info", f"خروج پیش از تارگت؛ حدود {frac*100:.0f}٪ مسیر تارگت طی شد."))
        if sl is not None and t["pnl"] < 0:
            if (ex - sl) * sg <= 0:
                out.append(_f("info", "خروج در حد ضرر یا بدتر از آن انجام شد."))
            else:
                out.append(_f("info", "پیش از رسیدن به حد ضرر خارج شدید؛ ضرر کمتر از ریسک برنامه‌ریزی‌شده بود."))

    fp = t.get("followed_plan")
    if fp == 1:
        out.append(_f("good", "طبق خودتان به برنامه‌ی معاملاتی پایبند بوده‌اید."))
    elif fp == 0:
        out.append(_f("warn", "طبق خودتان به برنامه‌ی معاملاتی پایبند نبوده‌اید."))
    for k, label in FLAG_LABELS.items():
        if t.get(k):
            out.append(_f("warn", f"ثبت‌شده توسط شما: {label}."))
    if t.get("mood") is not None and t["mood"] <= 2:
        out.append(_f("info", f"وضعیت روحی ثبت‌شده پایین بوده ({t['mood']} از ۵)."))

    prev = [p for p in closed_trades(previous or []) if p.get("market") == t.get("market")
            and (p.get("closed_at") or p.get("opened_at") or "") <= (t.get("opened_at") or "")]
    if prev and prev[-1]["pnl"] < 0 and t["quantity"] > prev[-1]["quantity"] * 1.25:
        out.append(_f("warn", "حجم این معامله پس از یک ضرر، بیش از ۲۵٪ بزرگ‌تر از معامله‌ی قبل بوده است."))
    if not out:
        out.append(_f("info", "اطلاعات کافی برای ارزیابی ثبت نشده است."))
    return out


# --------------------------------------------------------- period analysis
def _group_table(ts, keyfn, min_n=MIN_GROUP):
    g = {}
    for t in ts:
        k = keyfn(t)
        if k:
            g.setdefault(k, []).append(t)
    rows = [{"key": k, "n": len(v), "win_rate": _wr(v), "avg_pnl": _avg(v), "net": sum(x["pnl"] for x in v)}
            for k, v in g.items() if len(v) >= min_n]
    return sorted(rows, key=lambda r: r["avg_pnl"], reverse=True)


def analyze_period(trades: list[dict], previous_trades: list[dict] | None = None,
                   initial_balance: float = 0.0) -> dict:
    ts = closed_trades(trades)
    n = len(ts)
    rep = {"n": n, "stats": compute_stats(ts, initial_balance), "strengths": [], "weaknesses": [],
           "patterns": [], "groups": {}, "comparison": None, "suggestions": [],
           "low_sample": n < LOW_SAMPLE, "disclaimer": DISCLAIMER}
    if n == 0:
        return rep
    s = rep["stats"]
    strengths, weaknesses, patterns, sugg = [], [], [], []   # (priority, dict)

    # --- stop-loss usage
    sl_rate = sum(1 for t in ts if t.get("stop_loss") is not None) / n * 100
    rep["sl_usage_rate"] = sl_rate
    if n >= 5 and sl_rate < 80:
        weaknesses.append((90, {"text": f"فقط {sl_rate:.0f}٪ معاملات حد ضرر ثبت‌شده دارند (n={n}).", "n": n}))
        sugg.append({"text": "هیچ معامله‌ای را بدون حد ضرر ثبت و باز نکنید؛ هدف: ۱۰۰٪ معاملات دارای SL.",
                     "goal": {"metric": "sl_usage_rate", "op": ">=", "target": 100}})
    elif n >= 5 and sl_rate >= 95:
        strengths.append((60, {"text": f"تقریباً همه‌ی معاملات حد ضرر دارند ({sl_rate:.0f}٪، n={n}).", "n": n}))

    # --- profitability
    if n >= 10 and s["profit_factor"] is not None:
        if s["profit_factor"] >= 1.3:
            strengths.append((80, {"text": f"Profit Factor برابر {s['profit_factor']:.2f} است (n={n}).", "n": n}))
        elif s["profit_factor"] < 1:
            weaknesses.append((85, {"text": f"Profit Factor کمتر از ۱ است ({s['profit_factor']:.2f}، n={n}).", "n": n}))
            sugg.append({"text": "تا رسیدن Profit Factor به بالای ۱، فقط روی یک استراتژی با حداقل ۳۰ معامله تمرکز کنید.",
                         "goal": {"metric": "profit_factor", "op": ">=", "target": 1}})
    if s["average_r"] is not None and s["r_sample_size"] >= 10:
        if s["average_r"] >= 0.3:
            strengths.append((70, {"text": f"میانگین R برابر {s['average_r']:.2f} است (n={s['r_sample_size']}).", "n": s["r_sample_size"]}))
        elif s["average_r"] < 0:
            weaknesses.append((75, {"text": f"میانگین R منفی است ({s['average_r']:.2f}، n={s['r_sample_size']}).", "n": s["r_sample_size"]}))
    if s["max_consecutive_losses"] >= 5:
        weaknesses.append((70, {"text": f"بیشترین ضرر متوالی {s['max_consecutive_losses']} معامله بوده است.", "n": n}))
        sugg.append({"text": "پس از ۳ ضرر متوالی، همان روز معامله نکنید و معاملات را مرور کنید.",
                     "goal": {"metric": "max_consecutive_losses", "op": "<=", "target": 3}})

    # --- plan adherence
    plan = [t for t in ts if t.get("followed_plan") is not None]
    if plan:
        rate = sum(t["followed_plan"] for t in plan) / len(plan) * 100
        rep["plan_adherence"] = rate
        if len(plan) >= 5:
            if rate >= 80:
                strengths.append((75, {"text": f"رعایت برنامه‌ی معاملاتی {rate:.0f}٪ است (n={len(plan)}).", "n": len(plan)}))
            elif rate < 60:
                weaknesses.append((88, {"text": f"فقط {rate:.0f}٪ معاملات طبق برنامه بوده‌اند (n={len(plan)}).", "n": len(plan)}))
                sugg.append({"text": "پیش از هر ورود، دلیل ورود را بنویسید و چک‌لیست استراتژی را بررسی کنید؛ هدف: رعایت برنامه حداقل ۸۰٪.",
                             "goal": {"metric": "plan_adherence", "op": ">=", "target": 80}})
        yes = [t for t in plan if t["followed_plan"] == 1]
        no = [t for t in plan if t["followed_plan"] == 0]
        if len(yes) >= 3 and len(no) >= 3:
            patterns.append({"text": f"میانگین سود/زیان معاملات طبق‌برنامه {_avg(yes):,.2f} (n={len(yes)}) در برابر {_avg(no):,.2f} (n={len(no)}) برای معاملات خارج از برنامه؛ احتمالاً مرتبط است ولی به‌تنهایی علت را ثابت نمی‌کند.", "n": len(plan)})

    # --- behaviour flags
    for k, label in FLAG_LABELS.items():
        fl = [t for t in ts if t.get(k)]
        rest = [t for t in ts if not t.get(k)]
        if len(fl) >= 3:
            patterns.append({"text": f"«{label}» در {len(fl)} از {n} معامله ثبت شده؛ میانگین سود/زیان آن‌ها {_avg(fl):,.2f} در برابر {_avg(rest) if rest else 0:,.2f} برای بقیه (درصد موفقیت {_wr(fl):.0f}٪ در برابر {_wr(rest):.0f}٪).", "n": len(fl)})
            if _avg(rest) is not None and _avg(fl) < _avg(rest) and len(fl) / n >= 0.15:
                weaknesses.append((65, {"text": f"معاملات دارای «{label}» ضعیف‌تر از بقیه بوده‌اند (n={len(fl)}).", "n": len(fl)}))
                sugg.append({"text": f"هر بار که «{label}» را حس کردید، ۱۵ دقیقه صبر کنید و فقط در صورت تأیید چک‌لیست وارد شوید.", "goal": None})

    # --- size increase after loss / behaviour after losing streak
    opp = inc = 0
    for prev, cur in zip(ts, ts[1:]):
        if prev["pnl"] < 0 and prev.get("market") == cur.get("market"):
            opp += 1
            if cur["quantity"] > prev["quantity"] * 1.25:
                inc += 1
    if inc >= 3:
        patterns.append({"text": f"در {inc} از {opp} معامله‌ی بعد از ضرر، حجم بیش از ۲۵٪ افزایش یافته است؛ این الگو معمولاً نشانه‌ی تصمیم احساسی است.", "n": opp})
        weaknesses.append((80, {"text": f"افزایش حجم پس از ضرر ({inc} از {opp} مورد).", "n": opp}))
        sugg.append({"text": "پس از ضرر، حجم معامله‌ی بعد را از سقف ریسک تعیین‌شده بزرگ‌تر نکنید؛ هدف: صفر مورد افزایش حجم پس از ضرر.", "goal": None})
    after2 = [cur for a, b, cur in zip(ts, ts[1:], ts[2:]) if a["pnl"] < 0 and b["pnl"] < 0]
    if len(after2) >= MIN_GROUP:
        patterns.append({"text": f"درصد موفقیت معامله‌ی بعد از دو ضرر متوالی {_wr(after2):.0f}٪ است (n={len(after2)}) در برابر {_wr(ts):.0f}٪ کل.", "n": len(after2)})

    # --- groups
    dims = {"strategy": lambda t: t.get("strategy"), "symbol": lambda t: t.get("symbol"),
            "market": lambda t: t.get("market"), "weekday": _weekday, "hour": _hour}
    for dim, fn in dims.items():
        rows = _group_table(ts, fn)
        if len(rows) >= 2:
            rep["groups"][dim] = rows
    strat = rep["groups"].get("strategy")
    if strat:
        b, w = strat[0], strat[-1]
        if b["avg_pnl"] > 0:
            strengths.append((72, {"text": f"بهترین استراتژی: «{b['key']}» با میانگین {b['avg_pnl']:,.2f} (n={b['n']}).", "n": b["n"]}))
        if w["avg_pnl"] < 0:
            weaknesses.append((72, {"text": f"ضعیف‌ترین استراتژی: «{w['key']}» با میانگین {w['avg_pnl']:,.2f} (n={w['n']}).", "n": w["n"]}))
    for dim, label in (("hour", "ساعت"), ("weekday", "روز هفته"), ("symbol", "نماد")):
        rows = rep["groups"].get(dim)
        if rows:
            b, w = rows[0], rows[-1]
            patterns.append({"text": f"بهترین {label}: {b['key']} (میانگین {b['avg_pnl']:,.2f}، n={b['n']})؛ ضعیف‌ترین: {w['key']} (میانگین {w['avg_pnl']:,.2f}، n={w['n']}).", "n": b["n"] + w["n"]})

    # --- comparison with previous period
    if previous_trades:
        pt = closed_trades(previous_trades)
        if pt:
            ps = compute_stats(pt)
            rep["comparison"] = {"previous_n": len(pt), "net_profit": (s["net_profit"], ps["net_profit"]),
                                 "win_rate": (s["win_rate"], ps["win_rate"]),
                                 "average_r": (s["average_r"], ps["average_r"])}

    key = lambda x: -x[0]
    rep["strengths"] = [d for _, d in sorted(strengths, key=key)[:3]]
    rep["weaknesses"] = [d for _, d in sorted(weaknesses, key=key)[:3]]
    rep["patterns"] = patterns
    rep["suggestions"] = sugg
    return rep


# ------------------------------------------------------------------- goals
GOAL_METRICS = {
    "win_rate": "درصد موفقیت", "average_r": "میانگین R", "profit_factor": "Profit Factor",
    "plan_adherence": "درصد رعایت برنامه", "sl_usage_rate": "درصد معاملات دارای SL",
    "max_consecutive_losses": "بیشترین ضرر متوالی"}


def metric_value(metric: str, trades: list[dict]):
    ts = closed_trades(trades)
    if not ts:
        return None
    if metric == "sl_usage_rate":
        return sum(1 for t in ts if t.get("stop_loss") is not None) / len(ts) * 100
    if metric == "plan_adherence":
        p = [t for t in ts if t.get("followed_plan") is not None]
        return sum(t["followed_plan"] for t in p) / len(p) * 100 if p else None
    return compute_stats(ts).get(metric)


def evaluate_goals(goals: list[dict], trades: list[dict]) -> list[dict]:
    out = []
    for g in goals:
        cur = metric_value(g["metric"], trades)
        met = None if cur is None else (cur >= g["target"] if g["op"] == ">=" else cur <= g["target"])
        out.append({**g, "label": GOAL_METRICS.get(g["metric"], g["metric"]), "current": cur, "met": met})
    return out


# ------------------------------------------------------------------ report
def render_report_text(rep: dict) -> str:
    if rep["n"] == 0:
        return "هنوز معامله‌ی بسته‌ای در این بازه ثبت نشده است."
    s = rep["stats"]
    L = [f"تعداد معاملات بسته: {rep['n']} | درصد موفقیت: {s['win_rate']:.1f}٪ | سود خالص: {s['net_profit']:,.2f} | "
         f"Profit Factor: {'—' if s['profit_factor'] is None else format(s['profit_factor'], '.2f')} | "
         f"حداکثر Drawdown: {s['max_drawdown']:,.2f}"]
    if rep["low_sample"]:
        L.append(f"⚠ تعداد نمونه ({rep['n']}) کمتر از {LOW_SAMPLE} است؛ همه‌ی نتیجه‌گیری‌ها موقتی‌اند.")
    for title, key in (("نقاط قوت", "strengths"), ("نقاط ضعف", "weaknesses")):
        L.append(f"\n{title}:")
        L += [f"  • {d['text']}" for d in rep[key]] or ["  (با داده‌ی فعلی مورد قابل اتکایی پیدا نشد)"]
    if rep["patterns"]:
        L.append("\nالگوهای مشاهده‌شده:")
        L += [f"  • {p['text']}" for p in rep["patterns"]]
    c = rep["comparison"]
    if c:
        fmt = lambda a, b, d=2: f"{'—' if a is None else format(a, f',.{d}f')} (قبل: {'—' if b is None else format(b, f',.{d}f')})"
        L.append(f"\nمقایسه با دوره‌ی قبل (n قبلی={c['previous_n']}): سود خالص {fmt(*c['net_profit'])} | "
                 f"درصد موفقیت {fmt(*c['win_rate'], 1)} | میانگین R {fmt(*c['average_r'])}")
    if rep["suggestions"]:
        L.append("\nبرنامه‌ی پیشنهادی (قابل اندازه‌گیری):")
        L += [f"  {i}. {x['text']}" for i, x in enumerate(rep["suggestions"], 1)]
    L.append("\n" + rep["disclaimer"])
    return "\n".join(L)


def facts_for_ai(rep: dict) -> dict:
    """Aggregate, already-computed facts only (no raw trades, no notes)."""
    s = rep["stats"]
    r = lambda v: None if v is None else round(v, 2)
    return {"sample_size": rep["n"], "low_sample": rep["low_sample"],
            "stats": {k: r(s.get(k)) for k in ("win_rate", "net_profit", "profit_factor", "average_r",
                                               "max_drawdown", "max_consecutive_losses", "expected_value")},
            "strengths": [d["text"] for d in rep["strengths"]], "weaknesses": [d["text"] for d in rep["weaknesses"]],
            "patterns": [p["text"] for p in rep["patterns"]],
            "suggestions": [x["text"] for x in rep["suggestions"]]}
