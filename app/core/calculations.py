"""Deterministic financial calculations. No AI is ever involved here.

All money maths uses Decimal to avoid floating point errors.
"""
from __future__ import annotations
from dataclasses import dataclass
from decimal import Decimal, ROUND_HALF_UP, getcontext

getcontext().prec = 28
D = Decimal


def d(value) -> Decimal:
    """Convert any numeric input to Decimal safely."""
    if isinstance(value, Decimal):
        return value
    return Decimal(str(value))


def direction_sign(side: str) -> int:
    s = side.strip().lower()
    if s in ("buy", "long"):
        return 1
    if s in ("sell", "short"):
        return -1
    raise ValueError(f"Unknown trade side: {side!r}")


# ---------------------------------------------------------------- Forex
@dataclass(frozen=True)
class InstrumentSpec:
    """Contract specification. Brokers differ, so every field is editable
    by the user; the presets below are only common starting points."""
    symbol: str
    contract_size: Decimal      # units per 1.00 lot
    pip_size: Decimal           # price distance that counts as 1 pip
    quote_currency: str


PRESET_SPECS = {
    "EURUSD": InstrumentSpec("EURUSD", D(100000), D("0.0001"), "USD"),
    "GBPUSD": InstrumentSpec("GBPUSD", D(100000), D("0.0001"), "USD"),
    "USDJPY": InstrumentSpec("USDJPY", D(100000), D("0.01"), "JPY"),
    "USDCHF": InstrumentSpec("USDCHF", D(100000), D("0.0001"), "CHF"),
    "XAUUSD": InstrumentSpec("XAUUSD", D(100), D("0.1"), "USD"),
    "US30":   InstrumentSpec("US30", D(1), D("1"), "USD"),
}


def forex_pnl(spec: InstrumentSpec, side: str, lots, entry, exit_price,
              quote_to_account_rate=1, commission=0, swap=0) -> Decimal:
    """Net P/L in ACCOUNT currency.

    gross (quote currency) = (exit - entry) * sign * lots * contract_size
    gross_account = gross * quote_to_account_rate
    The rate (1 unit of quote currency in account currency) must be supplied
    when quote currency != account currency (e.g. USDJPY on a USD account
    needs 1/exit_price).
    """
    sign = direction_sign(side)
    gross_quote = (d(exit_price) - d(entry)) * sign * d(lots) * spec.contract_size
    return gross_quote * d(quote_to_account_rate) - d(commission) + d(swap)


def pip_value_per_lot(spec: InstrumentSpec, quote_to_account_rate=1) -> Decimal:
    """Value of one pip for 1 lot, in account currency."""
    return spec.pip_size * spec.contract_size * d(quote_to_account_rate)


def pips_between(spec: InstrumentSpec, price_a, price_b) -> Decimal:
    return abs(d(price_a) - d(price_b)) / spec.pip_size


def position_size_lots(spec: InstrumentSpec, balance, risk_percent, entry,
                       stop_loss, quote_to_account_rate=1) -> Decimal:
    """Lots such that hitting the stop loses `risk_percent` of balance."""
    risk_amount = d(balance) * d(risk_percent) / D(100)
    distance = abs(d(entry) - d(stop_loss))
    if distance == 0:
        raise ValueError("Entry and stop loss cannot be equal")
    loss_per_lot = distance * spec.contract_size * d(quote_to_account_rate)
    return risk_amount / loss_per_lot


# --------------------------------------------------------------- Crypto
def crypto_pnl(side: str, quantity, entry, exit_price,
               trading_fee=0, funding_fee=0) -> Decimal:
    """Realized P/L for spot or futures (quantity in base asset units).
    Fees and funding are positive numbers meaning cost."""
    sign = direction_sign(side)
    gross = (d(exit_price) - d(entry)) * sign * d(quantity)
    return gross - d(trading_fee) - d(funding_fee)


def crypto_unrealized_pnl(side, quantity, entry, mark_price) -> Decimal:
    return crypto_pnl(side, quantity, entry, mark_price)


def isolated_liquidation_price(side: str, entry, leverage,
                               maintenance_margin_rate="0.005") -> Decimal:
    """APPROXIMATE isolated-margin liquidation price (ignores fees/funding).
    Exchanges use their own tiered formulas; treat this as an estimate."""
    sign = direction_sign(side)
    e, lev, mmr = d(entry), d(leverage), d(maintenance_margin_rate)
    if lev <= 0:
        raise ValueError("Leverage must be positive")
    return e * (D(1) - sign * (D(1) / lev - mmr))


# ---------------------------------------------------------- Iran bourse
RIAL_PER_TOMAN = D(10)


def to_rial(amount, unit: str) -> Decimal:
    u = unit.strip().lower()
    if u in ("rial", "ریال"):
        return d(amount)
    if u in ("toman", "تومان"):
        return d(amount) * RIAL_PER_TOMAN
    raise ValueError(f"Unknown currency unit: {unit!r}")


def from_rial(amount_rial, unit: str) -> Decimal:
    u = unit.strip().lower()
    if u in ("rial", "ریال"):
        return d(amount_rial)
    if u in ("toman", "تومان"):
        return d(amount_rial) / RIAL_PER_TOMAN
    raise ValueError(f"Unknown currency unit: {unit!r}")


def iran_stock_pnl(quantity, buy_price, sell_price, buy_fee_rate,
                   sell_fee_rate, dividends=0) -> dict:
    """Net P/L of a closed bourse trade. Prices share one currency unit;
    fee rates are fractions (0.003712 = 0.3712%) because they change over
    time and per instrument, so they must be supplied, never assumed."""
    q = d(quantity)
    buy_value = d(buy_price) * q
    sell_value = d(sell_price) * q
    buy_fee = buy_value * d(buy_fee_rate)
    sell_fee = sell_value * d(sell_fee_rate)
    net = sell_value - sell_fee - buy_value - buy_fee + d(dividends)
    cost = buy_value + buy_fee
    return {"buy_value": buy_value, "sell_value": sell_value,
            "buy_fee": buy_fee, "sell_fee": sell_fee, "net_pnl": net,
            "return_percent": (net / cost * 100) if cost else D(0)}


def average_buy_price(lots: list[tuple]) -> Decimal:
    """Weighted average over [(quantity, price), ...] (ladder buying)."""
    total_q = sum((d(q) for q, _ in lots), D(0))
    if total_q == 0:
        raise ValueError("No quantity")
    return sum((d(q) * d(p) for q, p in lots), D(0)) / total_q


# --------------------------------------------------------- Common metrics
def risk_reward(side: str, entry, stop_loss, take_profit) -> Decimal:
    sign = direction_sign(side)
    e, sl, tp = d(entry), d(stop_loss), d(take_profit)
    risk = (e - sl) * sign
    reward = (tp - e) * sign
    if risk <= 0:
        raise ValueError("Stop loss is not on the losing side of entry")
    if reward <= 0:
        raise ValueError("Take profit is not on the winning side of entry")
    return reward / risk


def r_multiple(pnl, risk_amount) -> Decimal | None:
    """None when initial risk is unknown/zero (never guess)."""
    if risk_amount is None or d(risk_amount) <= 0:
        return None
    return d(pnl) / d(risk_amount)


def round2(x) -> Decimal:
    return d(x).quantize(D("0.01"), rounding=ROUND_HALF_UP)
