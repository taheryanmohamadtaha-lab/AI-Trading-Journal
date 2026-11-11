"""Glue between the coach and an online AI. Rules enforced here:
 - disabled by default; user key required (except local servers)
 - daily usage cap; every request is built (and can be previewed) before sending
 - AI only interprets numbers computed by the app; numbers it adds are flagged
"""
from __future__ import annotations
import json
import re
from urllib.parse import urlparse
from app.ai_engine import providers
from app.ai_engine.providers import AiError

SYSTEM_PROMPT = (
    "تو یک مربی معاملاتی هستی. فقط بر اساس «داده‌های محاسبه‌شده» در پیام کاربر تحلیل کن. "
    "هیچ عدد جدیدی نساز و هیچ عددی را تغییر نده. قیمت آینده را پیش‌بینی نکن و سود تضمین نده. "
    "اندازه نمونه را ذکر کن، بین همبستگی و علت فرق بگذار و در نمونه‌ی کم نتیجه‌ی قطعی نگیر. "
    "توصیه‌ها باید قابل اجرا و قابل اندازه‌گیری باشند. پاسخ را به فارسی، کوتاه و ساختاریافته بده.")

_DIGITS = str.maketrans("۰۱۲۳۴۵۶۷۸۹٠١٢٣٤٥٦٧٨٩", "01234567890123456789")
_NUM = re.compile(r"\d+(?:[.,]\d+)?")


def _norm_nums(text: str) -> set[str]:
    out = set()
    for m in _NUM.findall(text.translate(_DIGITS).replace("٬", ",")):
        m = m.replace(",", "")
        out.add(m); out.add(m.rstrip("0").rstrip(".") if "." in m else m)
    return out


def unverified_numbers(response: str, facts_text: str) -> list[str]:
    """Numbers in the AI answer that were not in the data sent to it
    (small whole numbers up to 10 are ignored)."""
    known = _norm_nums(facts_text)
    bad = []
    for n in sorted(_norm_nums(response)):
        if n in known:
            continue
        if re.fullmatch(r"\d{1,2}", n) and int(n) <= 10:
            continue
        if n not in bad and (n.rstrip("0").rstrip(".") if "." in n else n) not in known:
            bad.append(n)
    return bad


class AiService:
    def __init__(self, settings, secrets, db, transport=providers.http_post_json):
        self.settings, self.secrets, self.db, self.transport = settings, secrets, db, transport

    # -- request building (shown to the user for consent before sending)
    def build_request(self, kind: str, facts: dict) -> tuple[str, str]:
        header = {"period": "گزارش آماری دوره‌ای معامله‌گر را تفسیر کن و برنامه‌ی بهبود بده.",
                  "trade": "این معامله را بررسی کن: ۱) منطقی بودن ورود و حد ضرر ۲) خروج ۳) اشتباهات و نکات درست "
                           "۴) برای معامله‌ی بعد چه چیزی اصلاح شود."}[kind]
        return SYSTEM_PROMPT, f"{header}\n\nداده‌های محاسبه‌شده (JSON):\n{json.dumps(facts, ensure_ascii=False, indent=1)}"

    def _prepare(self):
        cfg = self.settings.load()
        if not cfg.model.strip() or not cfg.base_url.strip():
            raise AiError("آدرس سرویس و نام مدل را در «تنظیمات AI» وارد کنید.")
        key = self.secrets.get()
        host = (urlparse(cfg.base_url).hostname or "").lower()
        if not key and host not in ("localhost", "127.0.0.1", "::1"):
            raise AiError("کلید API ثبت نشده است.")
        return cfg, key

    def _prepare_check(self):
        """Raise AiError early (before asking the user for consent) if sending is impossible."""
        cfg = self.settings.load()
        if not cfg.enabled:
            raise AiError("هوش مصنوعی آنلاین غیرفعال است. آن را از «تنظیمات AI» روشن کنید.")
        cfg, _ = self._prepare()
        if self.db.ai_calls_today() >= cfg.daily_limit:
            raise AiError(f"سقف مصرف روزانه ({cfg.daily_limit} درخواست) پر شده است.")

    def ask(self, system: str, user: str) -> dict:
        cfg = self.settings.load()
        if not cfg.enabled:
            raise AiError("هوش مصنوعی آنلاین غیرفعال است. آن را از «تنظیمات AI» روشن کنید.")
        cfg, key = self._prepare()
        if self.db.ai_calls_today() >= cfg.daily_limit:
            raise AiError(f"سقف مصرف روزانه ({cfg.daily_limit} درخواست) پر شده است.")
        self.db.ai_register_call()            # counted even if it fails (prevents runaway retries)
        text = providers.complete(cfg.provider, cfg.base_url, cfg.model, key, system, user,
                                  cfg.max_tokens, self.transport)
        if not text:
            raise AiError("سرویس‌دهنده پاسخ خالی برگرداند.")
        bad = unverified_numbers(text, user)
        warnings = []
        if bad:
            warnings.append("این اعداد در داده‌های ارسالی نبودند و محاسبه‌ی برنامه نیستند "
                            "(شاید هدف پیشنهادی باشند): " + "، ".join(bad[:8]))
        return {"text": text, "warnings": warnings}

    def test_connection(self) -> str:
        """Sends a tiny message with NO trading data. Does not need 'enabled'."""
        cfg, key = self._prepare()
        out = providers.complete(cfg.provider, cfg.base_url, cfg.model, key, "Reply with one word.",
                                 "ping", 20, self.transport)
        return out or "(پاسخ خالی)"

    def usage_text(self) -> str:
        return f"امروز {self.db.ai_calls_today()} از {self.settings.load().daily_limit} درخواست مصرف شده است."
