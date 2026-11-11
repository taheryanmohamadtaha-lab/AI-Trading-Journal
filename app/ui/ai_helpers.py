"""One place for the 'ask the online AI' flow so every screen asks the
user's explicit permission the same way and shows exactly what is sent."""
from __future__ import annotations
from PySide6.QtWidgets import QMessageBox, QApplication
from PySide6.QtCore import Qt
from app.ai_engine.providers import AiError


def confirm_dialog(parent, system: str, user: str) -> bool:
    box = QMessageBox(parent)
    box.setIcon(QMessageBox.Question)
    box.setWindowTitle("تأیید ارسال داده به سرویس AI")
    box.setText("داده‌های زیر به سرویس هوش مصنوعی آنلاینی که تنظیم کرده‌اید ارسال می‌شود. ادامه می‌دهید؟")
    box.setInformativeText("تصاویر هرگز ارسال نمی‌شوند. فقط متن زیر ارسال می‌شود (برای دیدن کامل «Show Details» را بزنید).")
    box.setDetailedText(user)
    box.setStandardButtons(QMessageBox.Yes | QMessageBox.No)
    box.setDefaultButton(QMessageBox.No)
    return box.exec() == QMessageBox.Yes


def ask_with_consent(parent, service, kind: str, facts: dict, confirm=None):
    """Returns {'text','warnings'} | None (declined) | {'error': msg}."""
    try:
        service._prepare_check()
    except AiError as e:
        return {"error": str(e)}
    system, user = service.build_request(kind, facts)
    if not (confirm or (lambda s, u: confirm_dialog(parent, s, u)))(system, user):
        return None
    QApplication.setOverrideCursor(Qt.WaitCursor)
    try:
        return service.ask(system, user)
    except AiError as e:
        return {"error": str(e)}
    finally:
        QApplication.restoreOverrideCursor()
