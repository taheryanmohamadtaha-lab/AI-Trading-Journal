import os
import pytest
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
pytest.importorskip("PySide6")
from PySide6.QtWidgets import QApplication
from app.database.db import Database
from app.ui.main_window import MainWindow


@pytest.fixture(scope="module")
def app():
    return QApplication.instance() or QApplication([])


def test_save_trade_through_ui(app):
    db = Database()
    w = MainWindow(db)
    p = w.new_trade
    p.symbol.setText("EURUSD")
    p.f["quantity"].setText("۱")
    p.f["entry_price"].setText("1.1000")
    p.f["exit_price"].setText("1.1050")
    p.submit()
    assert "ذخیره شد" in p.msg.text()
    assert len(db.list_trades()) == 1
    assert w.dashboard.vals["total_trades"].text() == "1"
    p.f["quantity"].setText("1"); p.f["entry_price"].setText("1.1000")
    p.f["exit_price"].setText("1.1050"); p.submit()
    assert len(db.list_trades()) == 2 or "قبلاً" in p.msg.text()


def test_bad_input_shows_error(app):
    w = MainWindow(Database())
    w.new_trade.submit()
    assert "نماد" in w.new_trade.msg.text()
    assert w.db.list_trades() == []


def test_delete_requires_selection_and_works(app):
    db = Database()
    w = MainWindow(db)
    w.new_trade.symbol.setText("EURUSD")
    w.new_trade.f["quantity"].setText("1"); w.new_trade.f["entry_price"].setText("1.1")
    w.new_trade.f["exit_price"].setText("1.101"); w.new_trade.submit()
    w.archive.table.setCurrentCell(0, 0)
    w.archive.delete_selected(confirm=False)
    assert db.list_trades() == []
