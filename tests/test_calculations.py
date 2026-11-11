from decimal import Decimal as D
import pytest
from app.core.calculations import *


def test_forex_buy_eurusd():
    spec = PRESET_SPECS["EURUSD"]
    # 1 lot, +50 pips: 0.0050 * 100000 = 500 USD
    assert forex_pnl(spec, "buy", 1, "1.1000", "1.1050") == D("500")


def test_forex_sell_loss_with_costs():
    spec = PRESET_SPECS["EURUSD"]
    # 0.5 lot sell, price rises 20 pips -> -100, commission 3.5, swap -1
    assert forex_pnl(spec, "sell", "0.5", "1.1000", "1.1020",
                     commission="3.5", swap="-1") == D("-104.5")


def test_pip_value_symbol_specific():
    assert pip_value_per_lot(PRESET_SPECS["EURUSD"]) == D("10")
    assert pip_value_per_lot(PRESET_SPECS["XAUUSD"]) == D("10")
    # USDJPY pip = 1000 JPY; at 150 JPY/USD -> 6.666.. USD
    v = pip_value_per_lot(PRESET_SPECS["USDJPY"], D(1) / D(150))
    assert round2(v) == D("6.67")


def test_position_size():
    spec = PRESET_SPECS["EURUSD"]
    # 10000 balance, 1% = 100 USD, 50 pip stop (0.0050) -> 0.2 lot
    assert position_size_lots(spec, 10000, 1, "1.1000", "1.0950") == D("0.2")


def test_crypto_long_with_fees():
    assert crypto_pnl("long", "0.5", 60000, 62000, trading_fee=10,
                      funding_fee=5) == D("985")


def test_crypto_short():
    assert crypto_pnl("short", 2, 3000, 2900) == D("200")


def test_liquidation_estimate():
    assert isolated_liquidation_price("long", 100, 10, "0.005") == D("90.5")
    assert isolated_liquidation_price("short", 100, 10, "0.005") == D("109.5")


def test_toman_rial_conversion():
    assert to_rial(1000, "toman") == D(10000)
    assert from_rial(10000, "تومان") == D(1000)
    assert from_rial(to_rial("123456.7", "toman"), "toman") == D("123456.7")


def test_iran_stock_pnl():
    r = iran_stock_pnl(1000, 10000, 12000, "0.003", "0.007")
    # buy 10,000,000 +30,000 ; sell 12,000,000 -84,000
    assert r["net_pnl"] == D("1886000")


def test_average_buy_ladder():
    assert average_buy_price([(100, 10), (300, 14)]) == D("13")


def test_risk_reward():
    assert risk_reward("buy", 100, 98, 106) == D(3)
    assert risk_reward("sell", 100, 102, 94) == D(3)
    with pytest.raises(ValueError):
        risk_reward("buy", 100, 101, 106)


def test_r_multiple_unknown_risk():
    assert r_multiple(50, 25) == D(2)
    assert r_multiple(50, None) is None
    assert r_multiple(50, 0) is None
