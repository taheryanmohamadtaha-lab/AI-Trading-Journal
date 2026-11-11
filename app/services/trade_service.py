"""Turns raw form input into a validated trade record.
All numbers come from app.core.calculations (never from AI)."""
from __future__ import annotations
import json
from decimal import Decimal, InvalidOperation
from app.core import calculations as C

_DIGITS = str.maketrans("۰۱۲۳۴۵۶۷۸۹٠١٢٣٤٥٦٧٨٩", "01234567890123456789")


def parse_number(text, name: str, required: bool = True):
    s = "" if text is None else str(text).translate(_DIGITS)
    s = s.replace("٬", "").replace(",", "").replace("٫", ".").strip()
    if not s:
        if required:
            raise ValueError(f"فیلد «{name}» را وارد کنید.")
        return None
    try:
        return Decimal(s)
    except InvalidOperation:
        raise ValueError(f"مقدار «{name}» عدد معتبر نیست.")


BEHAVIOR_FLAGS = ("fomo", "revenge", "rushed", "early_exit", "moved_sl")
BEHAVIOR_KEYS = ("followed_plan", "mood") + BEHAVIOR_FLAGS + ("entry_reason", "lesson")


def behavior_from_form(f: dict) -> dict:
    out = {"followed_plan": None if f.get("followed_plan") in (None, "") else int(bool(int(f["followed_plan"]))),
           "mood": None if f.get("mood") in (None, "") else int(f["mood"]),
           "entry_reason": (f.get("entry_reason") or "").strip() or None,
           "lesson": (f.get("lesson") or "").strip() or None}
    if out["mood"] is not None and not 1 <= out["mood"] <= 5:
        raise ValueError("وضعیت روحی باید بین ۱ تا ۵ باشد.")
    for k in BEHAVIOR_FLAGS:
        out[k] = int(bool(int(f.get(k) or 0)))
    return out


def build_trade(f: dict) -> dict:
    market, side = f["market"], f["side"]
    symbol = (f.get("symbol") or "").strip().upper()
    if not symbol:
        raise ValueError("نماد را وارد کنید.")
    qty = parse_number(f.get("quantity"), "حجم")
    entry = parse_number(f.get("entry_price"), "قیمت ورود")
    exit_ = parse_number(f.get("exit_price"), "قیمت خروج", required=False)
    sl = parse_number(f.get("stop_loss"), "حد ضرر", required=False)
    tp = parse_number(f.get("take_profit"), "حد سود", required=False)
    if qty <= 0 or entry <= 0:
        raise ValueError("حجم و قیمت ورود باید بزرگ‌تر از صفر باشند.")
    if exit_ is not None and exit_ <= 0:
        raise ValueError("قیمت خروج باید بزرگ‌تر از صفر باشد.")
    sign = C.direction_sign(side)
    if sl is not None and (entry - sl) * sign <= 0:
        raise ValueError("حد ضرر باید در سمت زیان‌ده قیمت ورود باشد.")
    if tp is not None and (tp - entry) * sign <= 0:
        raise ValueError("حد سود باید در سمت سودده قیمت ورود باشد.")

    pnl = risk = None
    fees = Decimal(0)
    closed = exit_ is not None

    if market == "forex":
        cs = parse_number(f.get("contract_size"), "اندازه قرارداد", required=False)
        ps = parse_number(f.get("pip_size"), "اندازه پیپ", required=False)
        preset = C.PRESET_SPECS.get(symbol)
        if cs is None and preset is None:
            raise ValueError("برای این نماد «اندازه قرارداد» را وارد کنید.")
        spec = C.InstrumentSpec(symbol, cs or preset.contract_size,
                                ps or (preset.pip_size if preset else Decimal("0.0001")), "")
        rate = parse_number(f.get("rate"), "نرخ تبدیل", required=False) or Decimal(1)
        comm = parse_number(f.get("commission"), "کمیسیون", required=False) or Decimal(0)
        swap = parse_number(f.get("swap"), "سواپ", required=False) or Decimal(0)
        fees = comm - swap
        if closed:
            pnl = C.forex_pnl(spec, side, qty, entry, exit_, rate, comm, swap)
        if sl is not None:
            risk = abs(entry - sl) * qty * spec.contract_size * rate
    elif market == "crypto":
        fee = parse_number(f.get("commission"), "کارمزد", required=False) or Decimal(0)
        fund = parse_number(f.get("swap"), "فاندینگ", required=False) or Decimal(0)
        fees = fee + fund
        if closed:
            pnl = C.crypto_pnl(side, qty, entry, exit_, fee, fund)
        if sl is not None:
            risk = abs(entry - sl) * qty
    elif market == "iran":
        if C.direction_sign(side) != 1:
            raise ValueError("در بورس ایران فقط معامله خرید ثبت می‌شود.")
        unit = f.get("unit", "rial")
        bf = parse_number(f.get("buy_fee_percent"), "کارمزد خرید (٪)")
        sf = parse_number(f.get("sell_fee_percent"), "کارمزد فروش (٪)")
        entry, qty_ = C.to_rial(entry, unit), qty
        exit_ = C.to_rial(exit_, unit) if closed else None
        sl = C.to_rial(sl, unit) if sl is not None else None
        tp = C.to_rial(tp, unit) if tp is not None else None
        if closed:
            r = C.iran_stock_pnl(qty_, entry, exit_, bf / 100, sf / 100)
            pnl, fees = r["net_pnl"], r["buy_fee"] + r["sell_fee"]
        else:
            fees = entry * qty_ * bf / 100
        if sl is not None:
            risk = abs(entry - sl) * qty_
    else:
        raise ValueError("بازار نامعتبر است.")

    rm = C.r_multiple(pnl, risk) if pnl is not None else None
    fl = lambda x: None if x is None else float(x)
    return {
        "market": market, "symbol": symbol, "side": side,
        "status": "closed" if closed else "open",
        "quantity": float(qty), "entry_price": float(entry),
        "exit_price": fl(exit_), "stop_loss": fl(sl), "take_profit": fl(tp),
        "opened_at": f["opened_at"], "closed_at": f.get("closed_at") if closed else None,
        "timeframe": f.get("timeframe") or None, "strategy": f.get("strategy") or None,
        "fees": float(fees), "pnl": fl(pnl), "risk_amount": fl(risk),
        "r_multiple": fl(rm), "notes": f.get("notes") or None,
        "data_source": f.get("data_source", "manual"),
        "close_reason": f.get("close_reason") if closed else None,
        **behavior_from_form(f),
        # raw inputs, so an open trade can be closed later with the same settings
        "params": json.dumps({k: str(v) for k, v in f.items() if v not in (None, "")
                              and k not in ("exit_price", "closed_at", "close_reason") + BEHAVIOR_KEYS},
                             ensure_ascii=False),
    }


def close_open_trade(db, trade_id: int, exit_price, closed_at: str, reason: str = "manual") -> dict:
    """Close a previously saved open trade; P/L is recomputed by the core."""
    row = db.get_trade(trade_id)
    if row is None:
        raise ValueError("معامله پیدا نشد.")
    if row["status"] == "closed":
        raise ValueError("این معامله قبلاً بسته شده است.")
    if not row.get("params"):
        raise ValueError("این معامله اطلاعات لازم برای محاسبه‌ی خودکار ندارد "
                         "(احتمالاً از CSV وارد شده). آن را حذف و دوباره ثبت کنید.")
    form = json.loads(row["params"])
    form.update(exit_price=exit_price, closed_at=closed_at, close_reason=reason)
    built = build_trade(form)
    db.close_trade(trade_id, built)
    return db.get_trade(trade_id)
