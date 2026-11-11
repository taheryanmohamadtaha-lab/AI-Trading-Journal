"""Reads a trade screenshot: local OCR + a rule-based text parser.

Principles: only values actually present in the text are returned; every
value has a confidence; nothing is guessed. The user must confirm the result.
"""
from __future__ import annotations
import os
import re

_DIGITS = str.maketrans("۰۱۲۳۴۵۶۷۸۹٠١٢٣٤٥٦٧٨٩", "01234567890123456789")
CCY = {"USD", "EUR", "GBP", "JPY", "CHF", "CAD", "AUD", "NZD"}
INDEX_METALS = ("XAUUSD", "XAGUSD", "US30", "NAS100", "US100", "SPX500", "US500", "GER40", "UK100")
NUM = r"(-?\d+(?:\.\d+)?)"
SEP = r"\s*[:=]?\s*"


class OcrUnavailable(Exception):
    pass


def _norm(text: str) -> str:
    t = text.translate(_DIGITS).replace("٬", ",").replace("٫", ".")
    return re.sub(r"(?<=\d),(?=\d{3}\b)", "", t)


def _first(pattern, text, flags=re.I):
    m = re.search(pattern, text, flags)
    return m


def parse_trade_text(raw: str) -> dict:
    """Return {field: {'value': str, 'confidence': float}} for what was found."""
    text = _norm(raw)
    up = text.upper()
    out: dict = {}

    def put(field, value, conf):
        out[field] = {"value": str(value), "confidence": conf, "source": "ocr"}

    # symbol
    sym = None
    for s in INDEX_METALS:
        if re.search(rf"\b{s}\b", up):
            sym = s; break
    if sym is None:
        for m in re.finditer(r"\b([A-Z]{3})\s*/?\s*([A-Z]{3})\b", up):
            if m.group(1) in CCY and m.group(2) in CCY and m.group(1) != m.group(2):
                sym = m.group(1) + m.group(2); break
    if sym is None:
        m = re.search(r"\b([A-Z]{2,6})\s*/?\s*(USDT|BUSD|USDC)\b", up)
        if m:
            sym = m.group(1) + m.group(2)
    if sym:
        put("symbol", sym, 0.85)

    # side + volume ("buy 0.10")
    m = re.search(rf"\b(buy|sell|long|short)\b\s*(?:limit|stop)?\s*{NUM}?", text, re.I)
    if m:
        side = {"long": "buy", "short": "sell"}.get(m.group(1).lower(), m.group(1).lower())
        put("side", side, 0.9 if m.group(2) else 0.8)
        if m.group(2) and float(m.group(2)) > 0:
            put("quantity", m.group(2), 0.85)
    m = _first(rf"\b(?:volume|size|lots?|qty|quantity){SEP}{NUM}", text)
    if m and float(m.group(1)) > 0:
        put("quantity", m.group(1), 0.9)

    def labeled(field, pattern, conf=0.85, zero_means_unset=False):
        m = _first(pattern + SEP + NUM, text)
        if m:
            if zero_means_unset and float(m.group(1)) == 0:
                return
            put(field, m.group(1), conf)

    labeled("entry_price", r"\b(?:entry(?:\s*price)?|open(?:\s*price)?|price\s*open|avg\.?\s*price)")
    if "entry_price" not in out:
        m = _first(rf"\b(?:buy|sell)\b[^\n]*?\bat\b\s*{NUM}", text)
        if m:
            put("entry_price", m.group(1), 0.7)
    labeled("exit_price", r"\b(?:exit(?:\s*price)?|close\s*price|closed\s*at|price\s*close)")
    labeled("stop_loss", r"\b(?:s/l|sl|stop\s*loss)", zero_means_unset=True)
    labeled("take_profit", r"\b(?:t/p|tp|take\s*profit)", zero_means_unset=True)
    m = _first(r"\b(M1|M5|M15|M30|H1|H4|D1|W1|MN)\b", up, 0)
    if m:
        put("timeframe", m.group(1), 0.8)
    labeled("reported_pnl", r"\b(?:profit|p/?l|pnl)", 0.8)
    return out


def ocr_image(path: str) -> str:
    try:
        import pytesseract
        from PIL import Image, ImageOps
    except ImportError:
        raise OcrUnavailable("کتابخانه‌ی OCR نصب نیست.")
    cmd = os.environ.get("TESSERACT_CMD")
    win = r"C:\Program Files\Tesseract-OCR\tesseract.exe"
    if cmd:
        pytesseract.pytesseract.tesseract_cmd = cmd
    elif os.path.exists(win):
        pytesseract.pytesseract.tesseract_cmd = win
    try:
        img = Image.open(path).convert("L")
        if img.width < 1600:
            img = img.resize((img.width * 2, img.height * 2))
        img = ImageOps.autocontrast(img)
        return pytesseract.image_to_string(img, config="--psm 6")
    except pytesseract.TesseractNotFoundError:
        raise OcrUnavailable(
            "برنامه‌ی Tesseract روی این کامپیوتر نصب نیست. آن را نصب کنید "
            "(نسخه‌ی UB Mannheim) یا متن تصویر را دستی در کادر زیر بچسبانید.")
