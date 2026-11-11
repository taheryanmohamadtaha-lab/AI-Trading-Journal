"""Persian RTL main window: dashboard, new trade, archive, statistics, data."""
from __future__ import annotations
from PySide6.QtCore import Qt, QDateTime
from PySide6.QtGui import QPainter, QPen, QColor, QFont
from PySide6.QtWidgets import (
    QMainWindow, QWidget, QHBoxLayout, QVBoxLayout, QListWidget, QStackedWidget,
    QLabel, QFormLayout, QLineEdit, QComboBox, QPushButton, QDateTimeEdit,
    QTableWidget, QTableWidgetItem, QMessageBox, QFileDialog, QGridLayout,
    QFrame, QPlainTextEdit, QCheckBox, QHeaderView, QAbstractItemView, QScrollArea)
from app.analytics.stats import compute_stats, group_stats
from app.services.trade_service import build_trade
from app.services import csv_io
from app.services.image_store import ImageStore, STAGES, STAGE_LABEL
from app.ui.trade_dialog import TradeDialog
from app.ui.extract_page import ExtractPage
import tempfile
from app.ui.behavior_widget import BehaviorWidget
from app.ui.coach_pages import CoachPage, AiSettingsPage
from app.ai_engine.service import AiService
from app.ai_engine.settings import SettingsStore, SecretStore

MARKETS = [("فارکس", "forex"), ("ارز دیجیتال", "crypto"), ("بورس ایران", "iran")]
FMT = "yyyy-MM-dd HH:mm"
STYLE = """
QMainWindow, QWidget { background: #14181f; color: #e6e9ef; font-size: 14px; }
QListWidget { background: #0e1117; border: none; font-size: 15px; }
QListWidget::item { padding: 12px; }
QListWidget::item:selected { background: #2f6fed; color: white; }
QLineEdit, QComboBox, QDateTimeEdit, QPlainTextEdit, QTableWidget {
    background: #1d2330; border: 1px solid #2c3445; border-radius: 6px; padding: 5px; }
QPushButton { background: #2f6fed; color: white; border-radius: 6px; padding: 8px 16px; }
QPushButton:hover { background: #4a82f2; }
QLabel { background: transparent; }
QFrame#card { background: #1d2330; border-radius: 10px; }
QHeaderView::section { background: #232b3b; padding: 5px; border: none; }
"""


def fmt(x, digits=2):
    return "—" if x is None else f"{x:,.{digits}f}"


class EquityChart(QWidget):
    def __init__(self):
        super().__init__()
        self.curve: list[float] = []
        self.setMinimumHeight(180)

    def set_curve(self, c):
        self.curve = list(c)
        self.update()

    def paintEvent(self, _):
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing)
        w, h = self.width(), self.height()
        if len(self.curve) < 2:
            p.setPen(QColor("#7d879a"))
            p.drawText(self.rect(), Qt.AlignCenter, "برای رسم نمودار حداقل ۲ معامله بسته لازم است")
            return
        lo, hi = min(self.curve), max(self.curve)
        span = (hi - lo) or 1
        pts = [(10 + i * (w - 20) / (len(self.curve) - 1),
                h - 10 - (v - lo) / span * (h - 20)) for i, v in enumerate(self.curve)]
        p.setPen(QPen(QColor("#4ade80" if self.curve[-1] >= self.curve[0] else "#f87171"), 2))
        for a, b in zip(pts, pts[1:]):
            p.drawLine(int(a[0]), int(a[1]), int(b[0]), int(b[1]))


def card(title: str):
    f = QFrame(); f.setObjectName("card")
    lay = QVBoxLayout(f)
    t = QLabel(title); t.setStyleSheet("color:#8f9bb3;")
    v = QLabel("—"); v.setFont(QFont("Segoe UI", 18, QFont.Bold))
    lay.addWidget(t); lay.addWidget(v)
    return f, v


class DashboardPage(QWidget):
    def __init__(self, db):
        super().__init__()
        self.db = db
        lay = QVBoxLayout(self)
        lay.addWidget(self._h("داشبورد"))
        grid = QGridLayout()
        self.vals = {}
        for i, (k, title) in enumerate([
                ("total_trades", "تعداد معاملات"), ("win_rate", "درصد موفقیت"),
                ("net_profit", "سود/زیان خالص"), ("profit_factor", "Profit Factor"),
                ("average_r", "میانگین R"), ("max_drawdown", "حداکثر Drawdown")]):
            c, v = card(title); self.vals[k] = v
            grid.addWidget(c, i // 3, i % 3)
        lay.addLayout(grid)
        self.note = QLabel(""); self.note.setStyleSheet("color:#fbbf24;")
        lay.addWidget(self.note)
        lay.addWidget(QLabel("نمودار Equity"))
        self.chart = EquityChart(); lay.addWidget(self.chart)
        lay.addWidget(QLabel("آخرین معاملات"))
        self.table = QTableWidget(0, 5)
        self.table.setHorizontalHeaderLabels(["تاریخ", "بازار", "نماد", "جهت", "سود/زیان"])
        self.table.horizontalHeader().setSectionResizeMode(QHeaderView.Stretch)
        lay.addWidget(self.table)

    @staticmethod
    def _h(t):
        l = QLabel(t); l.setFont(QFont("Segoe UI", 20, QFont.Bold)); return l

    def refresh(self):
        trades = self.db.list_trades()
        s = compute_stats(trades)
        n = s["total_trades"]
        self.vals["total_trades"].setText(str(len(trades)))
        if n == 0:
            for k in ("win_rate", "net_profit", "profit_factor", "average_r", "max_drawdown"):
                self.vals[k].setText("—")
            self.note.setText("هنوز معامله بسته‌ای ثبت نشده است.")
        else:
            self.vals["win_rate"].setText(f"{s['win_rate']:.1f}٪ (از {n})")
            self.vals["net_profit"].setText(fmt(s["net_profit"]))
            self.vals["profit_factor"].setText(fmt(s["profit_factor"]))
            self.vals["average_r"].setText(
                "—" if s["average_r"] is None else f"{s['average_r']:.2f} (n={s['r_sample_size']})")
            self.vals["max_drawdown"].setText(fmt(s["max_drawdown"]))
            self.note.setText("⚠ تعداد نمونه کم است؛ آمار هنوز قابل اتکا نیست." if s["low_sample_warning"] else "")
        self.chart.set_curve(s.get("equity_curve", []))
        last = trades[-8:][::-1]
        self.table.setRowCount(len(last))
        for r, t in enumerate(last):
            for c, v in enumerate([t["opened_at"], t["market"], t["symbol"], t["side"], fmt(t["pnl"])]):
                self.table.setItem(r, c, QTableWidgetItem(str(v)))


class NewTradePage(QWidget):
    def __init__(self, db, store, on_saved):
        super().__init__()
        self.db, self.store, self.on_saved = db, store, on_saved
        self.pending: list[tuple[str, str]] = []
        lay = QVBoxLayout(self)
        h = QLabel("ثبت معامله جدید"); h.setFont(QFont("Segoe UI", 20, QFont.Bold)); lay.addWidget(h)
        form = QFormLayout(); lay.addLayout(form)
        self.market = QComboBox()
        for label, key in MARKETS: self.market.addItem(label, key)
        self.side = QComboBox(); self.side.addItem("خرید (Buy)", "buy"); self.side.addItem("فروش (Sell)", "sell")
        self.symbol = QLineEdit(); self.symbol.setPlaceholderText("مثلاً EURUSD")
        self.opened = QDateTimeEdit(QDateTime.currentDateTime()); self.opened.setDisplayFormat(FMT)
        self.closed = QDateTimeEdit(QDateTime.currentDateTime()); self.closed.setDisplayFormat(FMT)
        self.f = {k: QLineEdit() for k in (
            "quantity", "entry_price", "exit_price", "stop_loss", "take_profit",
            "commission", "swap", "contract_size", "pip_size", "rate",
            "buy_fee_percent", "sell_fee_percent", "strategy", "timeframe")}
        self.f["exit_price"].setPlaceholderText("خالی = معامله باز")
        self.unit = QComboBox(); self.unit.addItem("ریال", "rial"); self.unit.addItem("تومان", "toman")
        self.notes = QPlainTextEdit(); self.notes.setFixedHeight(70)
        self.rows = {}

        def add(key, label, w):
            form.addRow(label, w); self.rows[key] = (form, w)
        add("market", "بازار", self.market); add("symbol", "نماد", self.symbol)
        add("side", "جهت", self.side)
        add("quantity", "حجم (لات / تعداد)", self.f["quantity"])
        add("entry_price", "قیمت ورود", self.f["entry_price"])
        add("exit_price", "قیمت خروج", self.f["exit_price"])
        add("stop_loss", "حد ضرر", self.f["stop_loss"]); add("take_profit", "حد سود", self.f["take_profit"])
        add("opened", "زمان ورود", self.opened); add("closed", "زمان خروج", self.closed)
        add("commission", "کمیسیون / کارمزد", self.f["commission"])
        add("swap", "سواپ / فاندینگ", self.f["swap"])
        add("contract_size", "اندازه قرارداد (فارکس)", self.f["contract_size"])
        add("pip_size", "اندازه پیپ (فارکس)", self.f["pip_size"])
        add("rate", "نرخ تبدیل ارز قیمت به ارز حساب", self.f["rate"])
        add("unit", "واحد پول (بورس)", self.unit)
        add("buy_fee_percent", "کارمزد خرید ٪ (بورس)", self.f["buy_fee_percent"])
        add("sell_fee_percent", "کارمزد فروش ٪ (بورس)", self.f["sell_fee_percent"])
        add("strategy", "استراتژی", self.f["strategy"]); add("timeframe", "تایم‌فریم", self.f["timeframe"])
        add("notes", "یادداشت", self.notes)
        self.behavior = BehaviorWidget(); lay.addWidget(self.behavior)
        img_row = QHBoxLayout()
        self.img_stage = QComboBox()
        for k, label in STAGES[:3]: self.img_stage.addItem(label, k)
        add_img = QPushButton("افزودن عکس معامله"); add_img.clicked.connect(self.pick_image)
        self.img_label = QLabel("بدون عکس")
        img_row.addWidget(self.img_stage); img_row.addWidget(add_img); img_row.addWidget(self.img_label, 1)
        lay.addLayout(img_row)
        self.hint = QLabel(""); self.hint.setWordWrap(True); self.hint.setStyleSheet("color:#8f9bb3;")
        lay.addWidget(self.hint)
        self.msg = QLabel(""); lay.addWidget(self.msg)
        btn = QPushButton("ذخیره معامله"); btn.clicked.connect(self.submit); lay.addWidget(btn)
        lay.addStretch()
        self.market.currentIndexChanged.connect(self._market_changed)
        self._market_changed()

    def add_pending(self, stage: str, path: str):
        self.pending.append((stage, path))
        self.img_label.setText("، ".join(f"{STAGE_LABEL[s]}" for s, _ in self.pending))

    def pick_image(self):
        p, _ = QFileDialog.getOpenFileName(self, "انتخاب تصویر", "", "Images (*.png *.jpg *.jpeg *.webp)")
        if p: self.add_pending(self.img_stage.currentData(), p)

    def apply_extracted(self, vals: dict, image_path: str | None):
        """Fill the form from OCR values; the user still reviews and presses Save."""
        if "symbol" in vals: self.symbol.setText(vals["symbol"])
        if "side" in vals: self.side.setCurrentIndex(max(0, self.side.findData(vals["side"])))
        for k in ("quantity", "entry_price", "exit_price", "stop_loss", "take_profit", "timeframe"):
            if k in vals: self.f[k].setText(vals[k])
        if image_path: self.add_pending("entry", image_path)
        self.msg.setStyleSheet("color:#fbbf24;")
        self.msg.setText("مقادیر از تصویر خوانده شده‌اند؛ آن‌ها را بررسی کنید، بازار را انتخاب کنید و سپس ذخیره کنید.")

    def _market_changed(self):
        m = self.market.currentData()
        show = {"forex": {"commission", "swap", "contract_size", "pip_size", "rate"},
                "crypto": {"commission", "swap"},
                "iran": {"unit", "buy_fee_percent", "sell_fee_percent"}}[m]
        for key in ("commission", "swap", "contract_size", "pip_size", "rate",
                    "unit", "buy_fee_percent", "sell_fee_percent"):
            form, w = self.rows[key]
            w.setVisible(key in show); form.labelForField(w).setVisible(key in show)
        self.hint.setText({
            "forex": "برای نمادهای رایج (EURUSD, USDJPY, XAUUSD, US30…) اندازه قرارداد و پیپ خودکار پر می‌شود؛ "
                     "برای بقیه وارد کنید. اگر ارز قیمت با ارز حساب فرق دارد، نرخ تبدیل را بدهید.",
            "crypto": "حجم = مقدار دارایی پایه. کمیسیون و فاندینگ را به‌صورت هزینه (عدد مثبت) وارد کنید.",
            "iran": "کارمزد خرید و فروش را حتماً وارد کنید (در صورت نبود، ۰). فقط معامله خرید پشتیبانی می‌شود.",
        }[m])

    def submit(self):
        data = {k: w.text() for k, w in self.f.items()}
        data.update(market=self.market.currentData(), side=self.side.currentData(),
                    symbol=self.symbol.text(), unit=self.unit.currentData(),
                    opened_at=self.opened.dateTime().toString(FMT),
                    closed_at=self.closed.dateTime().toString(FMT),
                    notes=self.notes.toPlainText(), **self.behavior.get())
        try:
            trade = build_trade(data)
            new_id = self.db.add_trade(trade)
        except ValueError as e:
            self.msg.setStyleSheet("color:#f87171;"); self.msg.setText(str(e)); return
        if new_id is None:
            self.msg.setStyleSheet("color:#fbbf24;"); self.msg.setText("این معامله قبلاً ثبت شده است."); return
        warn = ""
        for stage, path in self.pending:
            try:
                self.store.add_image(new_id, stage, path)
            except ValueError as e:
                warn += f" (تصویر ذخیره نشد: {e})"
        self.pending.clear(); self.img_label.setText("بدون عکس")
        self.msg.setStyleSheet("color:#4ade80;")
        self.msg.setText(("معامله ذخیره شد." if trade["pnl"] is None
                         else f"معامله ذخیره شد. سود/زیان محاسبه‌شده: {trade['pnl']:,.2f}") + warn)
        for w in self.f.values(): w.clear()
        self.behavior.clear()
        self.on_saved()


class ArchivePage(QWidget):
    COLS = ["id", "opened_at", "market", "symbol", "side", "quantity", "entry_price",
            "exit_price", "pnl", "strategy"]
    HEAD = ["شناسه", "تاریخ", "بازار", "نماد", "جهت", "حجم", "ورود", "خروج", "سود/زیان", "استراتژی"]

    def __init__(self, db, store, ai, on_changed):
        super().__init__()
        self.db, self.store, self.ai, self.on_changed = db, store, ai, on_changed
        lay = QVBoxLayout(self)
        h = QLabel("آرشیو معاملات"); h.setFont(QFont("Segoe UI", 20, QFont.Bold)); lay.addWidget(h)
        self.table = QTableWidget(0, len(self.COLS))
        self.table.setHorizontalHeaderLabels(self.HEAD)
        self.table.setSelectionBehavior(QAbstractItemView.SelectRows)
        self.table.setEditTriggers(QAbstractItemView.NoEditTriggers)
        self.table.horizontalHeader().setSectionResizeMode(QHeaderView.Stretch)
        lay.addWidget(self.table)
        self.table.doubleClicked.connect(lambda *_: self.open_selected())
        o = QPushButton("تصاویر / بستن معامله (دوبار کلیک روی ردیف)")
        o.clicked.connect(lambda _=False: self.open_selected()); lay.addWidget(o)
        b = QPushButton("حذف معامله انتخاب‌شده"); b.clicked.connect(lambda _=False: self.delete_selected())
        lay.addWidget(b)

    def refresh(self):
        rows = self.db.list_trades()[::-1]
        self.table.setRowCount(len(rows))
        for r, t in enumerate(rows):
            for c, k in enumerate(self.COLS):
                v = t[k]
                self.table.setItem(r, c, QTableWidgetItem("" if v is None else
                                   (f"{v:,.2f}" if k == "pnl" else str(v))))

    def _selected_id(self):
        sel = self.table.selectionModel().selectedRows()
        row = sel[0].row() if sel else self.table.currentRow()
        return None if row < 0 else int(self.table.item(row, 0).text())

    def open_selected(self):
        tid = self._selected_id()
        if tid is None:
            return
        TradeDialog(self.db, self.store, tid, self.on_changed, self, ai=self.ai).exec()
        self.on_changed()

    def delete_selected(self, confirm=True):
        tid = self._selected_id()
        if tid is None:
            return
        if confirm and QMessageBox.question(
                self, "تأیید حذف", f"معامله شماره {tid} حذف شود؟ این کار قابل بازگشت نیست."
        ) != QMessageBox.Yes:
            return
        self.db.delete_trade(tid, confirmed=True)
        self.on_changed()


class StatsPage(QWidget):
    def __init__(self, db):
        super().__init__()
        self.db = db
        lay = QVBoxLayout(self)
        h = QLabel("گزارش‌های آماری"); h.setFont(QFont("Segoe UI", 20, QFont.Bold)); lay.addWidget(h)
        self.main = QTableWidget(0, 2); self.main.setHorizontalHeaderLabels(["شاخص", "مقدار"])
        self.main.horizontalHeader().setSectionResizeMode(QHeaderView.Stretch)
        lay.addWidget(self.main)
        lay.addWidget(QLabel("به تفکیک بازار"))
        self.grp = QTableWidget(0, 5)
        self.grp.setHorizontalHeaderLabels(["بازار", "تعداد نمونه", "درصد موفقیت", "سود خالص", "Profit Factor"])
        self.grp.horizontalHeader().setSectionResizeMode(QHeaderView.Stretch)
        lay.addWidget(self.grp)
        self.note = QLabel(""); self.note.setStyleSheet("color:#fbbf24;"); lay.addWidget(self.note)
        lay.addWidget(QLabel("عملکرد گذشته تضمین‌کننده نتیجه آینده نیست."))

    def refresh(self):
        trades = self.db.list_trades()
        s = compute_stats(trades)
        keys = [("total_trades", "تعداد معاملات بسته"), ("winning_trades", "معاملات سودده"),
                ("losing_trades", "معاملات زیان‌ده"), ("win_rate", "درصد موفقیت"),
                ("net_profit", "سود خالص"), ("gross_profit", "سود ناخالص"),
                ("gross_loss", "زیان ناخالص"), ("profit_factor", "Profit Factor"),
                ("average_win", "میانگین سود"), ("average_loss", "میانگین زیان"),
                ("expected_value", "Expected Value"), ("average_r", "میانگین R"),
                ("max_drawdown", "حداکثر Drawdown"), ("max_consecutive_wins", "بیشترین برد متوالی"),
                ("max_consecutive_losses", "بیشترین باخت متوالی")]
        rows = [(l, s[k]) for k, l in keys if k in s]
        self.main.setRowCount(len(rows))
        for r, (l, v) in enumerate(rows):
            self.main.setItem(r, 0, QTableWidgetItem(l))
            self.main.setItem(r, 1, QTableWidgetItem(
                "—" if v is None else (f"{v:,.2f}" if isinstance(v, float) else str(v))))
        g = group_stats(trades, "market")
        g = {k: v for k, v in g.items() if v["total_trades"]}
        self.grp.setRowCount(len(g))
        for r, (k, v) in enumerate(g.items()):
            for c, val in enumerate([k, str(v["total_trades"]), f"{v['win_rate']:.1f}",
                                     fmt(v["net_profit"]), fmt(v["profit_factor"])]):
                self.grp.setItem(r, c, QTableWidgetItem(val))
        self.note.setText("⚠ کمتر از ۳۰ معامله: نتیجه‌گیری قطعی ممکن نیست." if s.get("low_sample_warning") else "")


class DataPage(QWidget):
    def __init__(self, db, on_changed):
        super().__init__()
        self.db, self.on_changed = db, on_changed
        lay = QVBoxLayout(self)
        h = QLabel("ورود، خروج و پشتیبان‌گیری"); h.setFont(QFont("Segoe UI", 20, QFont.Bold)); lay.addWidget(h)
        for text, fn in [("خروجی CSV", self.export_csv), ("ورود از CSV", self.import_csv),
                         ("پشتیبان‌گیری (ذخیره فایل بکاپ)", self.backup),
                         ("بازیابی از فایل بکاپ (افزودن معاملات جدید)", self.restore)]:
            b = QPushButton(text); b.clicked.connect(fn); lay.addWidget(b)
        self.msg = QLabel(""); self.msg.setWordWrap(True); lay.addWidget(self.msg)
        lay.addStretch()

    def export_csv(self):
        p, _ = QFileDialog.getSaveFileName(self, "خروجی CSV", "trades.csv", "CSV (*.csv)")
        if p: self.msg.setText(f"{csv_io.export_csv(self.db, p)} معامله خروجی گرفته شد.")

    def import_csv(self):
        p, _ = QFileDialog.getOpenFileName(self, "ورود CSV", "", "CSV (*.csv)")
        if not p: return
        r = csv_io.import_csv(self.db, p)
        self.msg.setText(f"اضافه شد: {r['added']} | تکراری: {r['duplicates']} | خطا: {len(r['errors'])}"
                         + "".join(f"\nخط {i}: {m}" for i, m in r["errors"][:5]))
        self.on_changed()

    def backup(self):
        p, _ = QFileDialog.getSaveFileName(self, "پشتیبان‌گیری", "journal-backup.db", "Database (*.db)")
        if p: self.db.backup(p); self.msg.setText("پشتیبان ذخیره شد.")

    def restore(self):
        p, _ = QFileDialog.getOpenFileName(self, "بازیابی", "", "Database (*.db)")
        if p:
            self.msg.setText(f"{self.db.import_from(p)} معامله جدید بازیابی شد (تکراری‌ها رد شدند).")
            self.on_changed()


class MainWindow(QMainWindow):
    def __init__(self, db, image_dir=None, data_dir=None):
        super().__init__()
        self.db = db
        self.store = ImageStore(db, image_dir or tempfile.mkdtemp(prefix="atj_images_"))
        data_dir = data_dir or tempfile.mkdtemp(prefix="atj_data_")
        self.ai = AiService(SettingsStore(data_dir), SecretStore(data_dir), db)
        self.setWindowTitle("ژورنال معاملاتی هوشمند – AI Trading Journal")
        self.resize(1150, 760)
        self.setLayoutDirection(Qt.RightToLeft)
        self.setStyleSheet(STYLE)
        self.dashboard = DashboardPage(db)
        self.new_trade = NewTradePage(db, self.store, self.refresh_all)
        self.extract = ExtractPage(self.send_to_form)
        self.archive = ArchivePage(db, self.store, self.ai, self.refresh_all)
        self.stats = StatsPage(db)
        self.coach = CoachPage(db, self.ai)
        self.ai_settings = AiSettingsPage(self.ai)
        self.data = DataPage(db, self.refresh_all)
        self.pages = [("داشبورد", self.dashboard), ("ثبت معامله", self.new_trade), ("ثبت از روی عکس", self.extract),
                      ("آرشیو معاملات", self.archive), ("گزارش‌های آماری", self.stats),
                      ("مربی هوشمند", self.coach), ("تنظیمات AI", self.ai_settings),
                      ("ورود / خروج / بکاپ", self.data)]
        central = QWidget(); lay = QHBoxLayout(central)
        self.nav = QListWidget(); self.nav.setFixedWidth(210)
        self.stack = QStackedWidget()
        for name, page in self.pages:
            self.nav.addItem(name)
            if page in (self.new_trade, self.coach, self.ai_settings):
                sc = QScrollArea(); sc.setWidgetResizable(True); sc.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff); sc.setWidget(page); self.stack.addWidget(sc)
            else:
                self.stack.addWidget(page)
        self.nav.currentRowChanged.connect(self._go)
        lay.addWidget(self.nav); lay.addWidget(self.stack, 1)
        self.setCentralWidget(central)
        self.nav.setCurrentRow(0)
        self.refresh_all()

    def send_to_form(self, vals, image_path):
        self.new_trade.apply_extracted(vals, image_path)
        self.nav.setCurrentRow(1)

    def _go(self, i):
        self.stack.setCurrentIndex(i)
        self.refresh_all()

    def refresh_all(self):
        for _, p in self.pages:
            if hasattr(p, "refresh"):
                p.refresh()
