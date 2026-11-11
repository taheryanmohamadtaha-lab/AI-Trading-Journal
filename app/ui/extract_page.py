"""Register a trade from a screenshot: OCR -> editable table -> user confirms
by sending it to the normal trade form (nothing is saved from here)."""
from __future__ import annotations
from PySide6.QtCore import Qt
from PySide6.QtGui import QFont, QPixmap
from PySide6.QtWidgets import (
    QWidget, QVBoxLayout, QLabel, QPushButton, QFileDialog, QPlainTextEdit,
    QTableWidget, QTableWidgetItem, QHeaderView, QApplication)
from app.image_processing.extractor import parse_trade_text, ocr_image, OcrUnavailable

LABELS = {"symbol": "نماد", "side": "جهت", "quantity": "حجم", "entry_price": "قیمت ورود",
          "exit_price": "قیمت خروج", "stop_loss": "حد ضرر", "take_profit": "حد سود",
          "timeframe": "تایم‌فریم", "reported_pnl": "سود/زیان در عکس (فقط مرجع)"}
TRANSFER = ["symbol", "side", "quantity", "entry_price", "exit_price", "stop_loss",
            "take_profit", "timeframe"]


class ExtractPage(QWidget):
    def __init__(self, on_transfer):
        super().__init__()
        self.on_transfer = on_transfer
        self.image_path: str | None = None
        lay = QVBoxLayout(self)
        h = QLabel("ثبت معامله از روی عکس"); h.setFont(QFont("Segoe UI", 20, QFont.Bold)); lay.addWidget(h)
        warn = QLabel("مقادیر زیر فقط خوانش خودکار از تصویر هستند و ممکن است اشتباه باشند. "
                      "هر مقدار را بررسی و اصلاح کنید؛ معامله تا زمان تأیید شما ذخیره نمی‌شود. "
                      "مقداری که در تصویر دیده نشود خالی می‌ماند و حدس زده نمی‌شود.")
        warn.setWordWrap(True); warn.setStyleSheet("color:#fbbf24;"); lay.addWidget(warn)
        self.preview = QLabel("تصویری انتخاب نشده"); self.preview.setAlignment(Qt.AlignCenter)
        self.preview.setMinimumHeight(180); lay.addWidget(self.preview)
        pick = QPushButton("انتخاب تصویر و خواندن خودکار (OCR)"); pick.clicked.connect(self.pick_and_read)
        lay.addWidget(pick)
        lay.addWidget(QLabel("متن خوانده‌شده (می‌توانید دستی اصلاح کنید یا متن موردنظر را بچسبانید):"))
        self.text = QPlainTextEdit(); self.text.setFixedHeight(100); lay.addWidget(self.text)
        parse = QPushButton("تحلیل متن"); parse.clicked.connect(self.parse_text); lay.addWidget(parse)
        self.table = QTableWidget(0, 3)
        self.table.setHorizontalHeaderLabels(["فیلد", "مقدار (قابل ویرایش)", "اطمینان"])
        self.table.horizontalHeader().setSectionResizeMode(QHeaderView.Stretch)
        lay.addWidget(self.table)
        go = QPushButton("انتقال به فرم ثبت معامله برای بررسی و تأیید"); go.clicked.connect(self.transfer)
        lay.addWidget(go)
        self.msg = QLabel(""); self.msg.setWordWrap(True); lay.addWidget(self.msg)

    # ------------------------------------------------------------ actions
    def load_image(self, path: str):
        self.image_path = path
        pm = QPixmap(path)
        if not pm.isNull():
            self.preview.setPixmap(pm.scaled(560, 180, Qt.KeepAspectRatio, Qt.SmoothTransformation))

    def pick_and_read(self):
        p, _ = QFileDialog.getOpenFileName(self, "انتخاب تصویر", "", "Images (*.png *.jpg *.jpeg *.webp)")
        if not p:
            return
        self.load_image(p)
        self.read_image()

    def read_image(self):
        self.msg.setStyleSheet("color:#8f9bb3;"); self.msg.setText("در حال خواندن تصویر…")
        QApplication.setOverrideCursor(Qt.WaitCursor)
        try:
            self.text.setPlainText(ocr_image(self.image_path))
        except OcrUnavailable as e:
            self.msg.setStyleSheet("color:#fbbf24;"); self.msg.setText(str(e))
            QApplication.restoreOverrideCursor(); return
        except Exception as e:                      # unreadable / corrupt image
            self.msg.setStyleSheet("color:#f87171;"); self.msg.setText(f"خواندن تصویر ناموفق بود: {e}")
            QApplication.restoreOverrideCursor(); return
        QApplication.restoreOverrideCursor()
        self.parse_text()

    def parse_text(self):
        res = parse_trade_text(self.text.toPlainText())
        self.table.setRowCount(len(LABELS))
        for r, (k, label) in enumerate(LABELS.items()):
            lab = QTableWidgetItem(label); lab.setData(Qt.UserRole, k)
            lab.setFlags(lab.flags() & ~Qt.ItemIsEditable)
            f = res.get(k)
            val = QTableWidgetItem(f["value"] if f else "")
            conf = QTableWidgetItem(f"{f['confidence']*100:.0f}٪" if f else "پیدا نشد")
            conf.setFlags(conf.flags() & ~Qt.ItemIsEditable)
            for c, it in enumerate((lab, val, conf)): self.table.setItem(r, c, it)
        found = len(res)
        self.msg.setStyleSheet("color:#8f9bb3;")
        self.msg.setText(f"{found} مورد پیدا شد. موارد خالی را در فرم ثبت خودتان وارد کنید."
                         if found else "چیزی قابل استخراج پیدا نشد؛ اطلاعات را دستی در فرم ثبت وارد کنید.")

    def values(self) -> dict:
        out = {}
        for r in range(self.table.rowCount()):
            k = self.table.item(r, 0).data(Qt.UserRole)
            v = self.table.item(r, 1).text().strip()
            if k in TRANSFER and v:
                out[k] = v
        return out

    def transfer(self):
        vals = self.values()
        if not vals and not self.image_path:
            self.msg.setStyleSheet("color:#fbbf24;"); self.msg.setText("ابتدا یک تصویر بخوانید."); return
        self.on_transfer(vals, self.image_path)
