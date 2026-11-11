from decimal import Decimal as D
import pytest
from app.services.trade_service import build_trade, parse_number

BASE = dict(opened_at="2026-01-01 10:00", closed_at="2026-01-01 12:00")


def test_persian_digits():
    assert parse_number("۱٬۲۳۴٫۵", "x") == D("1234.5")


def test_forex_preset_and_r():
    t = build_trade({**BASE, "market": "forex", "side": "buy", "symbol": "eurusd",
                     "quantity": "1", "entry_price": "1.1000", "exit_price": "1.1050",
                     "stop_loss": "1.0975"})
    assert t["pnl"] == 500.0 and t["risk_amount"] == pytest.approx(250.0)
    assert t["r_multiple"] == pytest.approx(2.0)


def test_open_trade_has_no_pnl():
    t = build_trade({**BASE, "market": "crypto", "side": "long".replace("long", "buy"),
                     "symbol": "BTCUSDT", "quantity": "0.1", "entry_price": "60000"})
    assert t["status"] == "open" and t["pnl"] is None and t["closed_at"] is None


def test_crypto_fees():
    t = build_trade({**BASE, "market": "crypto", "side": "sell", "symbol": "ETH",
                     "quantity": "2", "entry_price": "3000", "exit_price": "2900",
                     "commission": "4", "swap": "1"})
    assert t["pnl"] == 195.0 and t["fees"] == 5.0


def test_iran_toman_stored_as_rial():
    t = build_trade({**BASE, "market": "iran", "side": "buy", "symbol": "فولاد",
                     "quantity": "1000", "entry_price": "1000", "exit_price": "1200",
                     "unit": "toman", "buy_fee_percent": "0.3", "sell_fee_percent": "0.7"})
    assert t["entry_price"] == 10000.0 and t["pnl"] == 1886000.0


def test_validation_errors():
    ok = {**BASE, "market": "forex", "side": "buy", "symbol": "EURUSD",
          "quantity": "1", "entry_price": "1.1"}
    with pytest.raises(ValueError):
        build_trade({**ok, "stop_loss": "1.2"})
    with pytest.raises(ValueError):
        build_trade({**ok, "quantity": "abc"})
    with pytest.raises(ValueError):
        build_trade({**ok, "symbol": "FOO"})  # unknown symbol needs contract size
    with pytest.raises(ValueError):
        build_trade({**ok, "market": "iran"})  # fee rates required
