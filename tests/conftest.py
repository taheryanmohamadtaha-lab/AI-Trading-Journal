import gc
import os
import pytest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")


@pytest.fixture(scope="session", autouse=True)
def _qt_cleanup():
    """Destroy Qt widgets in a controlled order before interpreter exit
    (otherwise Python may tear down QApplication first and crash)."""
    yield
    try:
        from PySide6.QtWidgets import QApplication
    except ImportError:
        return
    app = QApplication.instance()
    if app:
        for w in app.topLevelWidgets():
            w.close(); w.deleteLater()
        app.processEvents()
        gc.collect()
