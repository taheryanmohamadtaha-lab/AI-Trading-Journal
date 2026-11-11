"""Coach page (offline analysis + optional AI interpretation + goals) and AI settings page."""
from __future__ import annotations
import datetime
from PySide6.QtGui import QFont
from PySide6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QLabel, QPushButton, QComboBox, QTextEdit, QLineEdit,
    QTableWidget, QTableWidgetItem, QHeaderView, QCheckBox, QFormLayout, QSpinBox, QMessageBox)
from app.ai_engine import coach
from app.ai_engine.providers import PROVIDERS, PRESET_URLS, AiError
from app.ai_engine.settings import AiConfig
from app.ui.ai_helpers import ask_with_consent

PERIODS = [("۷ روز اخیر", 7), ("۳۰ روز اخیر", 30), ("۹۰ روز اخیر", 90), ("همه‌ی معاملات", None)]


def _title(text):
    l = QLabel(text); l.setFont(QFont("Segoe UI", 20, QFont.Bold)); return l


class CoachPage(QWidget):
    def __init__(self, db, ai, confirm=None):
        super().__init__()
        self.db, self.ai, self.confirm = db, ai, confirm
        self.report = None
        lay = QVBoxLayout(self)
        lay.addWidget(_title("مربی هوشمند"))
        row = QHBoxLayout()
        self.period = QComboBox()
        for label, days in PERIODS: self.period.addItem(label, days)
        self.period.setCurrentIndex(1)
        b1 = QPushButton("تحلیل آفلاین معاملات"); b1.clicked.connect(self.run_offline)
        self.ai_btn = QPushButton("تفسیر با AI (با تأیید)"); self.ai_btn.clicked.connect(self.run_ai)
        for w in (self.period, b1, self.ai_btn): row.addWidget(w)
        lay.addLayout(row)
        self.out = QTextEdit(); self.out.setReadOnly(True); self.out.setMinimumHeight(260); lay.addWidget(self.out)
        self.ai_out = QTextEdit(); self.ai_out.setReadOnly(True); self.ai_out.setMaximumHeight(160)
        self.ai_out.setPlaceholderText("تفسیر AI اینجا نمایش داده می‌شود (تفسیر است، نه محاسبه).")
        lay.addWidget(self.ai_out)
        self.msg = QLabel(""); self.msg.setWordWrap(True); lay.addWidget(self.msg)

        lay.addWidget(QLabel("اهداف قابل اندازه‌گیری (روی معاملات ۳۰ روز اخیر سنجیده می‌شوند)"))
        self.goals = QTableWidget(0, 4)
        self.goals.setHorizontalHeaderLabels(["هدف", "مقدار هدف", "مقدار فعلی", "وضعیت"])
        self.goals.horizontalHeader().setSectionResizeMode(QHeaderView.Stretch)
        self.goals.setMaximumHeight(170); lay.addWidget(self.goals)
        g = QHBoxLayout()
        self.metric = QComboBox()
        for k, v in coach.GOAL_METRICS.items(): self.metric.addItem(v, k)
        self.target = QLineEdit(); self.target.setPlaceholderText("عدد هدف")
        add = QPushButton("افزودن هدف"); add.clicked.connect(self.add_goal)
        sug = QPushButton("افزودن اهداف پیشنهادی"); sug.clicked.connect(self.add_suggested)
        rm = QPushButton("حذف هدف"); rm.clicked.connect(self.delete_goal)
        for w in (self.metric, self.target, add, sug, rm): g.addWidget(w)
        lay.addLayout(g)
        self.refresh()

    # ----------------------------------------------------------- data
    @staticmethod
    def _cut(days):
        return (datetime.datetime.now() - datetime.timedelta(days=days)).strftime("%Y-%m-%d %H:%M")

    def _split(self, days):
        trades = self.db.list_trades()
        if days is None:
            return trades, []
        cut, cut2 = self._cut(days), self._cut(days * 2)
        cur = [t for t in trades if (t["opened_at"] or "") >= cut]
        prev = [t for t in trades if cut2 <= (t["opened_at"] or "") < cut]
        return cur, prev

    # --------------------------------------------------------- actions
    def run_offline(self):
        cur, prev = self._split(self.period.currentData())
        self.report = coach.analyze_period(cur, prev)
        self.out.setPlainText(coach.render_report_text(self.report))
        self.ai_out.clear(); self.msg.setText("")

    def run_ai(self):
        if self.report is None:
            self.run_offline()
        if self.report["n"] == 0:
            self.msg.setStyleSheet("color:#fbbf24;"); self.msg.setText("ابتدا چند معامله‌ی بسته ثبت کنید."); return
        res = ask_with_consent(self, self.ai, "period", coach.facts_for_ai(self.report), self.confirm)
        self._show_ai(res)

    def _show_ai(self, res):
        if res is None:
            self.msg.setStyleSheet("color:#8f9bb3;"); self.msg.setText("ارسال لغو شد؛ هیچ داده‌ای ارسال نشد."); return
        if "error" in res:
            self.msg.setStyleSheet("color:#f87171;"); self.msg.setText(res["error"]); return
        self.ai_out.setPlainText(res["text"])
        self.msg.setStyleSheet("color:#fbbf24;")
        self.msg.setText(" ".join(res["warnings"]) or "")
        self.msg.setText((self.msg.text() + " " + self.ai.usage_text()).strip())

    # ----------------------------------------------------------- goals
    def refresh(self):
        trades = [t for t in self.db.list_trades() if (t["opened_at"] or "") >= self._cut(30)]
        ev = coach.evaluate_goals(self.db.list_goals(), trades)
        self.goals.setRowCount(len(ev))
        for r, g in enumerate(ev):
            cur = "—" if g["current"] is None else f"{g['current']:.2f}"
            st = "نامشخص (داده‌ی کافی نیست)" if g["met"] is None else ("✔ محقق شده" if g["met"] else "✘ هنوز نه")
            op = "حداقل" if g["op"] == ">=" else "حداکثر"
            items = [f"{g['label']}", f"{op} {g['target']:g}", cur, st]
            for c, v in enumerate(items):
                it = QTableWidgetItem(v)
                if c == 0: it.setData(256, g["id"])
                self.goals.setItem(r, c, it)

    def add_goal(self):
        try:
            v = float(self.target.text().replace("٫", ".").translate(str.maketrans("۰۱۲۳۴۵۶۷۸۹", "0123456789")))
        except ValueError:
            self.msg.setStyleSheet("color:#f87171;"); self.msg.setText("مقدار هدف باید عدد باشد."); return
        m = self.metric.currentData()
        self.db.add_goal(m, "<=" if m == "max_consecutive_losses" else ">=", v)
        self.target.clear(); self.refresh()

    def add_suggested(self):
        if not self.report or not self.report["suggestions"]:
            self.msg.setStyleSheet("color:#fbbf24;"); self.msg.setText("ابتدا تحلیل آفلاین را اجرا کنید؛ هدف پیشنهادی وجود ندارد."); return
        have = {(g["metric"], g["op"], g["target"]) for g in self.db.list_goals()}
        n = 0
        for s in self.report["suggestions"]:
            g = s.get("goal")
            if g and (g["metric"], g["op"], float(g["target"])) not in have:
                self.db.add_goal(g["metric"], g["op"], g["target"]); n += 1
        self.msg.setStyleSheet("color:#4ade80;" if n else "color:#fbbf24;")
        self.msg.setText(f"{n} هدف اضافه شد." if n else "برای این تحلیل هدف عددی خودکار وجود ندارد (یا قبلاً اضافه شده است).")
        self.refresh()

    def delete_goal(self):
        r = self.goals.currentRow()
        if r >= 0:
            self.db.delete_goal(self.goals.item(r, 0).data(256)); self.refresh()


class AiSettingsPage(QWidget):
    def __init__(self, ai):
        super().__init__()
        self.ai = ai
        lay = QVBoxLayout(self)
        lay.addWidget(_title("تنظیمات هوش مصنوعی"))
        info = QLabel("هسته‌ی برنامه بدون هوش مصنوعی کار می‌کند. AI آنلاین پیش‌فرض خاموش است، فقط با کلید خودتان کار می‌کند، "
                      "و پیش از هر ارسال، متن دقیق ارسالی را به شما نشان می‌دهد. عکس‌ها هرگز ارسال نمی‌شوند. "
                      "برای مدل محلی (مثل Ollama) آدرس http://localhost:11434/v1 را بدهید؛ کلید لازم نیست.")
        info.setWordWrap(True); info.setStyleSheet("color:#8f9bb3;"); lay.addWidget(info)
        form = QFormLayout(); lay.addLayout(form)
        self.enabled = QCheckBox("فعال کردن هوش مصنوعی آنلاین")
        self.provider = QComboBox()
        for k, v in PROVIDERS.items(): self.provider.addItem(v, k)
        self.base_url = QLineEdit(); self.model = QLineEdit()
        self.model.setPlaceholderText("نام مدل را از پنل سرویس‌دهنده کپی کنید")
        self.key = QLineEdit(); self.key.setEchoMode(QLineEdit.Password)
        self.key_status = QLabel("")
        self.limit = QSpinBox(); self.limit.setRange(1, 500)
        self.tokens = QSpinBox(); self.tokens.setRange(100, 4000); self.tokens.setSingleStep(100)
        for lab, w in (("", self.enabled), ("ارائه‌دهنده", self.provider), ("آدرس سرویس", self.base_url),
                       ("نام مدل", self.model), ("کلید API", self.key), ("", self.key_status),
                       ("سقف درخواست در روز", self.limit), ("حداکثر طول پاسخ (توکن)", self.tokens)):
            form.addRow(lab, w)
        row = QHBoxLayout()
        save = QPushButton("ذخیره تنظیمات"); save.clicked.connect(self.save)
        test = QPushButton("تست اتصال (بدون ارسال معامله)"); test.clicked.connect(self.test)
        dele = QPushButton("حذف کلید ذخیره‌شده"); dele.clicked.connect(self.delete_key)
        for w in (save, test, dele): row.addWidget(w)
        lay.addLayout(row)
        self.msg = QLabel(""); self.msg.setWordWrap(True); lay.addWidget(self.msg)
        lay.addStretch()
        self.provider.currentIndexChanged.connect(self._preset)
        self.load()

    def _preset(self):
        if not self.base_url.text().strip() or self.base_url.text() in PRESET_URLS.values():
            self.base_url.setText(PRESET_URLS[self.provider.currentData()])

    def load(self):
        c = self.ai.settings.load()
        self.enabled.setChecked(c.enabled)
        self.provider.setCurrentIndex(max(0, self.provider.findData(c.provider)))
        self.base_url.setText(c.base_url or PRESET_URLS[self.provider.currentData()])
        self.model.setText(c.model); self.limit.setValue(c.daily_limit); self.tokens.setValue(c.max_tokens)
        self._key_status()

    def _key_status(self):
        s = self.ai.secrets
        where = "حافظه‌ی امن ویندوز" if s.backend == "keyring" else "فایل محلی (امنیت کمتر)"
        self.key_status.setText(f"کلید ذخیره شده است ({where})" if s.has_key() else "کلیدی ذخیره نشده است")

    def save(self):
        self.ai.settings.save(AiConfig(
            enabled=self.enabled.isChecked(), provider=self.provider.currentData(),
            base_url=self.base_url.text().strip(), model=self.model.text().strip(),
            daily_limit=self.limit.value(), max_tokens=self.tokens.value()))
        if self.key.text().strip():
            self.ai.secrets.set(self.key.text()); self.key.clear()
        self._key_status()
        self.msg.setStyleSheet("color:#4ade80;"); self.msg.setText("تنظیمات ذخیره شد. " + self.ai.usage_text())

    def test(self):
        self.save()
        try:
            out = self.ai.test_connection()
            self.msg.setStyleSheet("color:#4ade80;"); self.msg.setText(f"اتصال موفق بود. پاسخ: {out[:80]}")
        except AiError as e:
            self.msg.setStyleSheet("color:#f87171;"); self.msg.setText(str(e))

    def delete_key(self):
        self.ai.secrets.delete(); self._key_status()
        self.msg.setStyleSheet("color:#8f9bb3;"); self.msg.setText("کلید حذف شد.")
