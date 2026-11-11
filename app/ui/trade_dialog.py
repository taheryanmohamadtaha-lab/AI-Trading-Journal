"""Per-trade window: images at every stage, before/after comparison,
and closing an open trade (TP / SL / manual) with a result screenshot."""
from __future__ import annotations
from PySide6.QtCore import Qt, QDateTime, QSize, QUrl
from PySide6.QtGui import QIcon, QPixmap, QDesktopServices
from PySide6.QtWidgets import (
    QDialog, QVBoxLayout, QHBoxLayout, QLabel, QListWidget, QListWidgetItem,
    QComboBox, QPushButton, QFileDialog, QMessageBox, QLineEdit, QDateTimeEdit,
    QGroupBox, QFormLayout, QTextEdit)
from app.services.image_store import STAGES, STAGE_LABEL
from app.services.trade_service import close_open_trade, behavior_from_form
from app.ai_engine import coach
from app.ui.behavior_widget import BehaviorWidget
from app.ui.ai_helpers import ask_with_consent

FMT = "yyyy-MM-dd HH:mm"
IMG_FILTER = "Images (*.png *.jpg *.jpeg *.webp)"


class CompareDialog(QDialog):
    def __init__(self, before: str, after: str, parent=None):
        super().__init__(parent)
        self.setWindowTitle("مقایسه قبل و بعد از معامله")
        self.resize(1100, 600)
        lay = QHBoxLayout(self)
        for title, path in (("بعد از خروج", after), ("قبل / هنگام ورود", before)):
            col = QVBoxLayout()
            col.addWidget(QLabel(title), alignment=Qt.AlignCenter)
            img = QLabel(); img.setAlignment(Qt.AlignCenter)
            pm = QPixmap(path)
            img.setPixmap(pm.scaled(520, 520, Qt.KeepAspectRatio, Qt.SmoothTransformation))
            col.addWidget(img, 1)
            lay.addLayout(col)


class TradeDialog(QDialog):
    def __init__(self, db, store, trade_id: int, on_changed=None, parent=None, ai=None):
        super().__init__(parent)
        self.db, self.store, self.trade_id, self.on_changed = db, store, trade_id, on_changed
        self.ai, self.confirm = ai, None
        self.setWindowTitle(f"معامله شماره {trade_id}")
        self.resize(950, 900)
        self.setLayoutDirection(Qt.RightToLeft)
        lay = QVBoxLayout(self)
        self.summary = QLabel(); self.summary.setWordWrap(True); lay.addWidget(self.summary)

        self.list = QListWidget(); self.list.setViewMode(QListWidget.IconMode)
        self.list.setIconSize(QSize(150, 110)); self.list.setResizeMode(QListWidget.Adjust)
        self.list.setMinimumHeight(220)
        self.list.itemDoubleClicked.connect(self.open_selected)
        lay.addWidget(self.list)

        row = QHBoxLayout()
        self.stage = QComboBox()
        for k, label in STAGES: self.stage.addItem(label, k)
        add = QPushButton("افزودن عکس"); add.clicked.connect(self.pick_image)
        rm = QPushButton("حذف عکس انتخاب‌شده"); rm.clicked.connect(lambda _=False: self.delete_selected())
        cmp_ = QPushButton("مقایسه قبل و بعد"); cmp_.clicked.connect(self.compare)
        for w in (self.stage, add, rm, cmp_): row.addWidget(w)
        lay.addLayout(row)

        self.behavior = BehaviorWidget(); self.behavior.set(self._trade()); lay.addWidget(self.behavior)
        crow = QHBoxLayout()
        bsave = QPushButton("ذخیره اطلاعات رفتاری"); bsave.clicked.connect(self.save_behavior)
        rev = QPushButton("تحلیل مربی (آفلاین)"); rev.clicked.connect(self.show_review)
        self.ai_btn = QPushButton("تفسیر AI (با تأیید شما)"); self.ai_btn.clicked.connect(self.ask_ai)
        for w in (bsave, rev, self.ai_btn): crow.addWidget(w)
        lay.addLayout(crow)
        self.review = QTextEdit(); self.review.setReadOnly(True); self.review.setMaximumHeight(150); lay.addWidget(self.review)

        self.close_box = QGroupBox("بستن معامله باز")
        form = QFormLayout(self.close_box)
        self.reason = QComboBox()
        self.reason.addItem("رسیدن به تارگت (TP)", "tp")
        self.reason.addItem("خورده شدن حد ضرر (SL)", "sl")
        self.reason.addItem("خروج دستی", "manual")
        self.exit_price = QLineEdit()
        self.closed_at = QDateTimeEdit(QDateTime.currentDateTime()); self.closed_at.setDisplayFormat(FMT)
        btn = QPushButton("بستن معامله و محاسبه سود/زیان"); btn.clicked.connect(self.close_trade)
        form.addRow("دلیل خروج", self.reason); form.addRow("قیمت خروج", self.exit_price)
        form.addRow("زمان خروج", self.closed_at); form.addRow(btn)
        lay.addWidget(self.close_box)
        self.reason.currentIndexChanged.connect(self._prefill_exit)

        self.msg = QLabel(""); self.msg.setWordWrap(True); lay.addWidget(self.msg)
        self.refresh()
        self._prefill_exit()

    # ---------------------------------------------------------- helpers
    def _trade(self):
        return self.db.get_trade(self.trade_id)

    def refresh(self):
        t = self._trade()
        status = "باز" if t["status"] == "open" else "بسته"
        pnl = "—" if t["pnl"] is None else f"{t['pnl']:,.2f}"
        self.summary.setText(
            f"{t['symbol']} | {t['market']} | {t['side']} | وضعیت: {status} | "
            f"ورود: {t['entry_price']} | خروج: {t['exit_price'] or '—'} | "
            f"حد ضرر: {t['stop_loss'] or '—'} | حد سود: {t['take_profit'] or '—'} | سود/زیان: {pnl}")
        self.close_box.setVisible(t["status"] == "open")
        self.list.clear()
        for im in self.store.list_images(self.trade_id):
            it = QListWidgetItem(QIcon(QPixmap(im["path"])), STAGE_LABEL.get(im["stage"], im["stage"]))
            it.setData(Qt.UserRole, im)
            self.list.addItem(it)

    def _prefill_exit(self):
        t = self._trade()
        if t["market"] == "iran":      # prices are stored in rial; user types in their own unit
            return
        key = {"tp": "take_profit", "sl": "stop_loss"}.get(self.reason.currentData())
        if key and t.get(key):
            self.exit_price.setText(str(t[key]))

    # ------------------------------------------------------------ images
    def add_image_path(self, stage: str, path: str):
        self.store.add_image(self.trade_id, stage, path)
        self.refresh()

    def pick_image(self):
        p, _ = QFileDialog.getOpenFileName(self, "انتخاب تصویر", "", IMG_FILTER)
        if not p:
            return
        try:
            self.add_image_path(self.stage.currentData(), p)
            self.msg.setStyleSheet("color:#4ade80;"); self.msg.setText("تصویر اضافه شد.")
        except ValueError as e:
            self.msg.setStyleSheet("color:#f87171;"); self.msg.setText(str(e))

    def _selected_image(self):
        it = self.list.currentItem()
        return it.data(Qt.UserRole) if it else None

    def open_selected(self, *_):
        im = self._selected_image()
        if im:
            QDesktopServices.openUrl(QUrl.fromLocalFile(im["path"]))

    def delete_selected(self, confirm=True):
        im = self._selected_image()
        if not im:
            return
        if confirm and QMessageBox.question(self, "تأیید حذف", "این تصویر حذف شود؟") != QMessageBox.Yes:
            return
        self.store.delete_image(im["id"], confirmed=True)
        self.refresh()

    def compare(self):
        before, after = self.store.compare_pair(self.trade_id)
        if not before or not after:
            self.msg.setStyleSheet("color:#fbbf24;")
            self.msg.setText("برای مقایسه، هم عکس «قبل/هنگام ورود» و هم عکس «بعد از خروج / TP / SL / نتیجه نهایی» لازم است.")
            return
        CompareDialog(before, after, self).exec()

    # ------------------------------------------------------------- coach
    def save_behavior(self):
        try:
            self.db.update_behavior(self.trade_id, behavior_from_form(self.behavior.get()))
        except ValueError as e:
            self.msg.setStyleSheet("color:#f87171;"); self.msg.setText(str(e)); return
        self.msg.setStyleSheet("color:#4ade80;"); self.msg.setText("اطلاعات رفتاری ذخیره شد.")

    def findings(self):
        t = self._trade()
        return t, coach.review_trade(t, [x for x in self.db.list_trades() if x["id"] != t["id"]])

    def show_review(self):
        _, f = self.findings()
        mark = {"good": "✔", "warn": "⚠", "info": "•"}
        self.review.setPlainText("\n".join(f"{mark[x['level']]} {x['text']}" for x in f))

    def ask_ai(self):
        if self.ai is None:
            return
        t, f = self.findings()
        keys = ("symbol", "market", "side", "entry_price", "exit_price", "stop_loss", "take_profit", "pnl",
                "r_multiple", "timeframe", "strategy", "followed_plan", "mood", "fomo", "revenge", "rushed",
                "early_exit", "moved_sl", "entry_reason", "lesson")
        facts = {k: t.get(k) for k in keys if t.get(k) not in (None, "")}
        facts["offline_findings"] = [x["text"] for x in f]
        res = ask_with_consent(self, self.ai, "trade", facts, self.confirm)
        if res is None:
            self.msg.setStyleSheet("color:#8f9bb3;"); self.msg.setText("ارسال لغو شد؛ هیچ داده‌ای ارسال نشد.")
        elif "error" in res:
            self.msg.setStyleSheet("color:#f87171;"); self.msg.setText(res["error"])
        else:
            self.review.append("\n— تفسیر AI (تفسیر است، نه محاسبه) —\n" + res["text"])
            self.msg.setStyleSheet("color:#fbbf24;"); self.msg.setText(" ".join(res["warnings"]))

    # ------------------------------------------------------------- close
    def close_trade(self):
        reason = self.reason.currentData()
        try:
            row = close_open_trade(self.db, self.trade_id, self.exit_price.text(),
                                   self.closed_at.dateTime().toString(FMT), reason)
        except ValueError as e:
            self.msg.setStyleSheet("color:#f87171;"); self.msg.setText(str(e)); return
        # suggest the matching screenshot stage
        idx = self.stage.findData({"tp": "tp_hit", "sl": "sl_hit"}.get(reason, "after_exit"))
        self.stage.setCurrentIndex(idx)
        self.msg.setStyleSheet("color:#4ade80;")
        self.msg.setText(f"معامله بسته شد. سود/زیان: {row['pnl']:,.2f}. "
                         "حالا عکس نتیجه را با «افزودن عکس» ثبت کنید.")
        self.refresh()
        if self.on_changed:
            self.on_changed()
