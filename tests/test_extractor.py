import shutil
import pytest
from app.image_processing.extractor import parse_trade_text, ocr_image

MT5 = """EURUSD, buy 0.10
Entry: 1.10250
S/L: 1.09900  T/P: 1.11000
Profit: -12.50   H1"""


def val(r, k):
    return r[k]["value"] if k in r else None


def test_parses_labeled_fields():
    r = parse_trade_text(MT5)
    assert val(r, "symbol") == "EURUSD" and val(r, "side") == "buy"
    assert val(r, "quantity") == "0.10" and val(r, "entry_price") == "1.10250"
    assert val(r, "stop_loss") == "1.09900" and val(r, "take_profit") == "1.11000"
    assert val(r, "timeframe") == "H1" and val(r, "reported_pnl") == "-12.50"
    assert all(0 < f["confidence"] <= 1 for f in r.values())


def test_missing_fields_stay_missing():
    r = parse_trade_text("XAUUSD H4 chart screenshot")
    assert set(r) == {"symbol", "timeframe"}   # no entry/volume guessed


def test_zero_sl_tp_means_not_set():
    r = parse_trade_text("GBPUSD sell 0.5\nS/L: 0.00000\nT/P: 0.00000")
    assert "stop_loss" not in r and "take_profit" not in r
    assert val(r, "side") == "sell"


def test_persian_digits_and_crypto():
    r = parse_trade_text("BTC/USDT long\nEntry: ۶۰٬۰۰۰\nSL: ۵۹۰۰۰")
    assert val(r, "symbol") == "BTCUSDT" and val(r, "side") == "buy"
    assert val(r, "entry_price") == "60000" and val(r, "stop_loss") == "59000"


@pytest.mark.skipif(not shutil.which("tesseract"), reason="tesseract not installed")
def test_real_ocr_roundtrip(tmp_path):
    from PIL import Image, ImageDraw, ImageFont
    img = Image.new("RGB", (900, 260), "white")
    d = ImageDraw.Draw(img)
    try:
        f = ImageFont.truetype("/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf", 34)
    except OSError:
        pytest.skip("no font")
    d.text((20, 20), "EURUSD, buy 0.10", fill="black", font=f)
    d.text((20, 80), "Entry: 1.10250", fill="black", font=f)
    d.text((20, 140), "S/L: 1.09900  T/P: 1.11000", fill="black", font=f)
    p = tmp_path / "t.png"; img.save(p)
    r = parse_trade_text(ocr_image(str(p)))
    assert val(r, "symbol") == "EURUSD" and val(r, "entry_price") == "1.10250"
    assert val(r, "stop_loss") == "1.09900"
