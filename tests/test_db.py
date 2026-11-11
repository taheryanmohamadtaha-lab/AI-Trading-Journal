import pytest
from app.database.db import Database

TRADE = dict(market="forex", symbol="EURUSD", side="buy", quantity=1,
             entry_price=1.1, exit_price=1.105, opened_at="2026-01-01T10:00",
             closed_at="2026-01-01T12:00", pnl=500.0)


def test_schema_version_and_insert():
    db = Database()
    assert db.version == 3
    assert db.add_trade(TRADE) == 1
    assert len(db.list_trades()) == 1


def test_duplicate_import_blocked():
    db = Database()
    db.add_trade(TRADE)
    assert db.add_trade(TRADE) is None
    assert len(db.list_trades()) == 1


def test_invalid_rejected():
    db = Database()
    with pytest.raises(ValueError):
        db.add_trade({**TRADE, "exit_price": None})
    with pytest.raises(Exception):
        db.add_trade({**TRADE, "quantity": -1, "opened_at": "x"})


def test_delete_needs_confirmation_and_backup(tmp_path):
    db = Database()
    tid = db.add_trade(TRADE)
    with pytest.raises(PermissionError):
        db.delete_trade(tid)
    db.backup(tmp_path / "b.db")
    db.delete_trade(tid, confirmed=True)
    assert db.list_trades() == []
    assert len(Database(tmp_path / "b.db").list_trades()) == 1
