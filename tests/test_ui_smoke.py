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


# ---------------------------------------------------------------- stage 3
from PIL import Image
from app.ui.trade_dialog import TradeDialog


def _png(tmp_path, name="a.png"):
    p = tmp_path / name
    Image.new("RGB", (30, 30), "blue").save(p)
    return str(p)


def _fill_open(w):
    p = w.new_trade
    p.symbol.setText("EURUSD"); p.f["quantity"].setText("1")
    p.f["entry_price"].setText("1.1000"); p.f["stop_loss"].setText("1.0950")
    p.f["take_profit"].setText("1.1100")


def test_images_attached_on_save_and_close_flow(app, tmp_path):
    db = Database()
    w = MainWindow(db, tmp_path / "imgs")
    _fill_open(w)
    w.new_trade.add_pending("before_entry", _png(tmp_path, "b.png"))
    w.new_trade.add_pending("entry", _png(tmp_path, "e.png"))
    w.new_trade.submit()
    t = db.list_trades()[0]
    assert t["status"] == "open"
    assert [i["stage"] for i in w.store.list_images(t["id"])] == ["before_entry", "entry"]
    assert w.new_trade.pending == []

    dlg = TradeDialog(db, w.store, t["id"], w.refresh_all)
    dlg.reason.setCurrentIndex(0)            # TP -> exit price prefilled
    assert dlg.exit_price.text() == "1.11"
    dlg.close_trade()
    assert db.get_trade(t["id"])["pnl"] == 1000.0
    assert dlg.stage.currentData() == "tp_hit"
    dlg.add_image_path("tp_hit", _png(tmp_path, "tp.png"))
    before, after = w.store.compare_pair(t["id"])
    assert before and after
    assert dlg.list.count() == 3
    dlg.list.setCurrentRow(0)
    dlg.delete_selected(confirm=False)
    assert dlg.list.count() == 2


def test_bad_exit_price_in_dialog(app, tmp_path):
    db = Database(); w = MainWindow(db, tmp_path / "i")
    _fill_open(w); w.new_trade.submit()
    dlg = TradeDialog(db, w.store, db.list_trades()[0]["id"])
    dlg.exit_price.setText("abc"); dlg.close_trade()
    assert db.list_trades()[0]["status"] == "open" and dlg.msg.text()


def test_extract_page_fills_form_but_does_not_save(app, tmp_path):
    db = Database(); w = MainWindow(db, tmp_path / "i")
    ex = w.extract
    ex.load_image(_png(tmp_path))
    ex.text.setPlainText("EURUSD, sell 0.20\nEntry: 1.2000\nS/L: 1.2050 T/P: 1.1900")
    ex.parse_text()
    ex.table.item(2, 1).setText("0.25")            # user corrects the volume
    ex.transfer()
    assert db.list_trades() == []                   # nothing saved yet
    assert w.new_trade.f["quantity"].text() == "0.25"
    assert w.new_trade.symbol.text() == "EURUSD"
    assert w.new_trade.side.currentData() == "sell"
    assert w.new_trade.pending[0][0] == "entry"
    assert w.nav.currentRow() == 1
    w.new_trade.submit()
    assert len(db.list_trades()) == 1 and len(w.store.list_images(1)) == 1


def test_extract_empty_text_reports_nothing_found(app, tmp_path):
    w = MainWindow(Database(), tmp_path / "i")
    w.extract.text.setPlainText("hello world")
    w.extract.parse_text()
    assert w.extract.values() == {}


# ---------------------------------------------------------------- stage 4
from app.ai_engine.settings import AiConfig
from app.ui.trade_dialog import TradeDialog as _TD


class _Fake:
    def __init__(self, reply="تفسیر نمونه"): self.calls, self.reply = [], reply
    def __call__(self, url, headers, payload, timeout=45):
        self.calls.append(payload)
        return {"choices": [{"message": {"content": self.reply}}]}


def _enable_ai(w, fake):
    w.ai.transport = fake
    w.ai.settings.save(AiConfig(enabled=True, base_url="http://localhost:1/v1", model="m"))


def _closed_trades(w, n=8):
    p = w.new_trade
    for i in range(n):
        entry = 1.1 + i * 0.001
        p.symbol.setText("EURUSD"); p.f["quantity"].setText(str(1 + i % 2))
        p.f["entry_price"].setText(f"{entry:.4f}")
        p.f["exit_price"].setText(f"{entry + (0.003 if i % 2 else -0.002):.4f}")
        p.f["stop_loss"].setText(f"{entry - 0.0025:.4f}")
        p.behavior.plan.setCurrentIndex(1 if i % 2 else 2)
        p.submit()
    assert len(w.db.list_trades()) == n


def test_behavior_fields_saved_from_form(app, tmp_path):
    db = Database(); w = MainWindow(db, tmp_path / "i", tmp_path)
    p = w.new_trade
    p.symbol.setText("EURUSD"); p.f["quantity"].setText("1"); p.f["entry_price"].setText("1.1")
    p.behavior.plan.setCurrentIndex(2); p.behavior.flags["fomo"].setChecked(True)
    p.behavior.reason.setText("بریک‌اوت"); p.submit()
    r = db.list_trades()[0]
    assert (r["followed_plan"], r["fomo"], r["entry_reason"]) == (0, 1, "بریک‌اوت")
    assert not p.behavior.flags["fomo"].isChecked()      # cleared after save


def test_coach_offline_works_without_ai(app, tmp_path):
    db = Database(); w = MainWindow(db, tmp_path / "i", tmp_path)
    _closed_trades(w)
    c = w.coach
    c.period.setCurrentIndex(3)                            # all trades
    c.run_offline()
    assert "تعداد معاملات بسته: 8" in c.out.toPlainText()
    assert "کمتر از" in c.out.toPlainText()                # low-sample warning


def test_ai_not_sent_when_declined_or_disabled(app, tmp_path):
    db = Database(); w = MainWindow(db, tmp_path / "i", tmp_path)
    _closed_trades(w); fake = _Fake()
    c = w.coach; c.period.setCurrentIndex(3); c.confirm = lambda s, u: False
    c.run_ai()                                             # AI disabled by default
    assert "غیرفعال" in c.msg.text() and fake.calls == []
    _enable_ai(w, fake)
    c.run_ai()                                             # enabled but user says no
    assert fake.calls == [] and "لغو" in c.msg.text()
    assert db.ai_calls_today() == 0


def test_ai_sent_only_after_confirmation_and_preview_has_no_raw_trades(app, tmp_path):
    db = Database(); w = MainWindow(db, tmp_path / "i", tmp_path)
    _closed_trades(w); fake = _Fake("میانگین R خوب است"); _enable_ai(w, fake)
    seen = {}
    def confirm(system, user):
        seen["user"] = user; return True
    c = w.coach; c.period.setCurrentIndex(3); c.confirm = confirm
    c.run_ai()
    assert len(fake.calls) == 1 and c.ai_out.toPlainText() == "میانگین R خوب است"
    assert "opened_at" not in seen["user"] and "EURUSD" not in seen["user"]
    assert db.ai_calls_today() == 1


def test_goals_add_suggested_and_delete(app, tmp_path):
    db = Database(); w = MainWindow(db, tmp_path / "i", tmp_path)
    c = w.coach
    c.metric.setCurrentIndex(c.metric.findData("win_rate")); c.target.setText("۵۵"); c.add_goal()
    assert db.list_goals()[0]["target"] == 55.0 and c.goals.rowCount() == 1
    c.target.setText("abc"); c.add_goal()
    assert len(db.list_goals()) == 1
    c.goals.setCurrentCell(0, 0); c.delete_goal()
    assert db.list_goals() == []


def test_ai_settings_save_key_and_test_connection(app, tmp_path):
    db = Database(); w = MainWindow(db, tmp_path / "i", tmp_path)
    fake = _Fake("pong"); w.ai.transport = fake
    s = w.ai_settings
    s.enabled.setChecked(True); s.base_url.setText("https://x.example/v1"); s.model.setText("m")
    s.key.setText("sk-secret"); s.save()
    assert w.ai.secrets.get() == "sk-secret" and s.key.text() == ""
    cfg = w.ai.settings.load()
    assert cfg.enabled and cfg.model == "m"
    assert "sk-secret" not in (tmp_path / "ai_settings.json").read_text(encoding="utf-8")
    s.test()
    assert "موفق" in s.msg.text() and "trade" not in str(fake.calls[0]).lower()
    s.delete_key(); assert not w.ai.secrets.has_key()


def test_trade_dialog_review_and_behavior_edit(app, tmp_path):
    db = Database(); w = MainWindow(db, tmp_path / "i", tmp_path)
    p = w.new_trade
    p.symbol.setText("EURUSD"); p.f["quantity"].setText("1"); p.f["entry_price"].setText("1.1000")
    p.f["stop_loss"].setText("1.0950"); p.f["take_profit"].setText("1.1100"); p.submit()
    tid = db.list_trades()[0]["id"]
    d = _TD(db, w.store, tid, w.refresh_all, ai=w.ai)
    d.behavior.flags["moved_sl"].setChecked(True); d.save_behavior()
    assert db.get_trade(tid)["moved_sl"] == 1
    d.show_review()
    assert "2.00" in d.review.toPlainText() and "جابه‌جایی حد ضرر" in d.review.toPlainText()
    fake = _Fake("تحلیل"); _enable_ai(w, fake); d.confirm = lambda s, u: False
    d.ask_ai(); assert fake.calls == []
    d.confirm = lambda s, u: True; d.ask_ai()
    assert len(fake.calls) == 1 and "تحلیل" in d.review.toPlainText()
