import pytest
from PIL import Image
from app.database.db import Database
from app.services.image_store import ImageStore
from app.services.trade_service import build_trade, close_open_trade

OPEN = dict(market="forex", side="buy", symbol="EURUSD", quantity="1",
            entry_price="1.1000", stop_loss="1.0950", take_profit="1.1100",
            opened_at="2026-01-01 10:00")


def png(tmp_path, name="a.png"):
    p = tmp_path / name
    Image.new("RGB", (20, 20), "red").save(p)
    return p


def test_open_then_close_at_tp(tmp_path):
    db = Database()
    tid = db.add_trade(build_trade(OPEN))
    assert db.get_trade(tid)["status"] == "open"
    row = close_open_trade(db, tid, "1.1100", "2026-01-01 15:00", "tp")
    assert row["status"] == "closed" and row["pnl"] == 1000.0
    assert row["r_multiple"] == pytest.approx(2.0) and row["close_reason"] == "tp"
    with pytest.raises(ValueError):
        close_open_trade(db, tid, "1.1", "x", "manual")  # already closed


def test_close_at_sl_is_loss():
    db = Database()
    tid = db.add_trade(build_trade(OPEN))
    row = close_open_trade(db, tid, "1.0950", "2026-01-01 12:00", "sl")
    assert row["pnl"] == -500.0 and row["r_multiple"] == pytest.approx(-1.0)


def test_iran_close_uses_saved_unit_and_fees():
    db = Database()
    tid = db.add_trade(build_trade(dict(
        market="iran", side="buy", symbol="X", quantity="1000", entry_price="1000",
        unit="toman", buy_fee_percent="0.3", sell_fee_percent="0.7",
        opened_at="2026-01-01 10:00")))
    row = close_open_trade(db, tid, "1200", "2026-01-02 10:00")
    assert row["pnl"] == 1886000.0


def test_images_per_stage(tmp_path):
    db = Database()
    tid = db.add_trade(build_trade(OPEN))
    st = ImageStore(db, tmp_path / "imgs")
    st.add_image(tid, "before_entry", png(tmp_path, "b.png"))
    st.add_image(tid, "during", png(tmp_path, "d.png"))
    assert [i["stage"] for i in st.list_images(tid)] == ["before_entry", "during"]
    b, a = st.compare_pair(tid)
    assert b and a is None
    st.add_image(tid, "tp_hit", png(tmp_path, "t.png"))
    assert st.compare_pair(tid)[1].endswith(".png")


def test_image_validation_and_delete(tmp_path):
    db = Database()
    tid = db.add_trade(build_trade(OPEN))
    st = ImageStore(db, tmp_path / "imgs")
    bad = tmp_path / "x.gif"; bad.write_bytes(b"GIF89a")
    with pytest.raises(ValueError):
        st.add_image(tid, "entry", bad)
    with pytest.raises(ValueError):
        st.add_image(tid, "nope", png(tmp_path))
    iid = st.add_image(tid, "entry", png(tmp_path))
    with pytest.raises(PermissionError):
        st.delete_image(iid)
    st.delete_image(iid, confirmed=True)
    assert st.list_images(tid) == []
