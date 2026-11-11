from __future__ import annotations
from PySide6.QtWidgets import (QGroupBox, QFormLayout, QComboBox, QCheckBox, QLineEdit)
from app.services.trade_service import BEHAVIOR_FLAGS
from app.ai_engine.coach import FLAG_LABELS


class BehaviorWidget(QGroupBox):
    """Psychology / discipline fields used by the coach. All optional."""

    def __init__(self):
        super().__init__("اطلاعات رفتاری و روان‌شناسی (اختیاری)")
        form = QFormLayout(self)
        self.plan = QComboBox()
        self.plan.addItem("نامشخص", None); self.plan.addItem("بله، طبق برنامه بود", 1); self.plan.addItem("خیر، خارج از برنامه", 0)
        self.mood = QComboBox(); self.mood.addItem("—", None)
        for i in range(1, 6): self.mood.addItem(f"{i} از ۵", i)
        self.flags = {k: QCheckBox(FLAG_LABELS[k]) for k in BEHAVIOR_FLAGS}
        self.reason = QLineEdit(); self.lesson = QLineEdit()
        form.addRow("رعایت برنامه معاملاتی", self.plan)
        form.addRow("وضعیت روحی قبل از ورود", self.mood)
        for cb in self.flags.values(): form.addRow(cb)
        form.addRow("دلیل ورود", self.reason); form.addRow("درسی که گرفتم", self.lesson)

    def get(self) -> dict:
        d = {"followed_plan": self.plan.currentData(), "mood": self.mood.currentData(),
             "entry_reason": self.reason.text(), "lesson": self.lesson.text()}
        d.update({k: int(cb.isChecked()) for k, cb in self.flags.items()})
        return d

    def set(self, row: dict):
        self.plan.setCurrentIndex(max(0, self.plan.findData(row.get("followed_plan"))))
        self.mood.setCurrentIndex(max(0, self.mood.findData(row.get("mood"))))
        for k, cb in self.flags.items(): cb.setChecked(bool(row.get(k)))
        self.reason.setText(row.get("entry_reason") or ""); self.lesson.setText(row.get("lesson") or "")

    def clear(self):
        self.set({})
