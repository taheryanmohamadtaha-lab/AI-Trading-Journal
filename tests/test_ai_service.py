import json
import threading
from http.server import BaseHTTPRequestHandler, HTTPServer
import pytest
from app.ai_engine.providers import AiError, complete
from app.ai_engine.service import AiService, unverified_numbers
from app.ai_engine.settings import AiConfig, SettingsStore, SecretStore
from app.database.db import Database


class Fake:
    def __init__(self, reply="تحلیل نمونه"): self.calls, self.reply = [], reply
    def __call__(self, url, headers, payload, timeout=45):
        self.calls.append((url, headers, payload))
        if "anthropic" in url or url.endswith("/v1/messages"):
            return {"content": [{"type": "text", "text": self.reply}]}
        return {"choices": [{"message": {"content": self.reply}}]}


def make(tmp_path, **cfg):
    db = Database(); st = SettingsStore(tmp_path); sec = SecretStore(tmp_path, backend="file")
    st.save(AiConfig(**{"enabled": True, "base_url": "https://x.example/v1", "model": "m", **cfg}))
    return db, st, sec


def test_disabled_by_default_and_never_calls(tmp_path):
    fake = Fake(); svc = AiService(SettingsStore(tmp_path), SecretStore(tmp_path, "file"), Database(), fake)
    assert AiConfig().enabled is False
    with pytest.raises(AiError):
        svc.ask("s", "u")
    assert fake.calls == []


def test_requires_key_unless_local(tmp_path):
    db, st, sec = make(tmp_path); fake = Fake()
    svc = AiService(st, sec, db, fake)
    with pytest.raises(AiError, match="کلید"):
        svc.ask("s", "u")
    st.save(AiConfig(enabled=True, base_url="http://localhost:11434/v1", model="llama"))
    assert svc.ask("s", "u")["text"] == "تحلیل نمونه"
    assert "Authorization" not in fake.calls[0][1]


def test_daily_limit_enforced(tmp_path):
    db, st, sec = make(tmp_path, daily_limit=2); sec.set("k"); fake = Fake()
    svc = AiService(st, sec, db, fake)
    svc.ask("s", "u"); svc.ask("s", "u")
    with pytest.raises(AiError, match="سقف"):
        svc.ask("s", "u")
    assert len(fake.calls) == 2


def test_wire_formats(tmp_path):
    f = Fake()
    complete("openai_compatible", "https://a/v1/", "m", "KEY", "sys", "usr", 50, f)
    url, h, p = f.calls[0]
    assert url == "https://a/v1/chat/completions" and h["Authorization"] == "Bearer KEY"
    assert p["messages"][0]["role"] == "system"
    complete("anthropic", "https://api.anthropic.com", "m", "KEY", "sys", "usr", 50, f)
    url, h, p = f.calls[1]
    assert url.endswith("/v1/messages") and h["x-api-key"] == "KEY" and p["system"] == "sys"


def test_unverified_numbers_flagged():
    facts = '{"win_rate": 42.5, "n": 31}'
    assert unverified_numbers("درصد موفقیت ۴۲.۵ است و n=31", facts) == []
    assert unverified_numbers("سود 1250 دلار شد", facts) == ["1250"]


def test_secret_roundtrip_and_delete(tmp_path):
    s = SecretStore(tmp_path, "file")
    assert not s.has_key()
    s.set("  abc  "); assert s.get() == "abc"
    s.delete(); assert s.get() == ""


def test_real_http_errors_and_success(tmp_path):
    class H(BaseHTTPRequestHandler):
        def do_POST(self):
            if self.headers.get("Authorization") != "Bearer good":
                self.send_response(401); self.end_headers(); self.wfile.write(b'{"error":"bad key"}'); return
            self.rfile.read(int(self.headers["Content-Length"]))
            self.send_response(200); self.end_headers()
            self.wfile.write(json.dumps({"choices": [{"message": {"content": "OK"}}]}).encode())
        def log_message(self, *a): pass
    srv = HTTPServer(("127.0.0.1", 0), H); threading.Thread(target=srv.serve_forever, daemon=True).start()
    base = f"http://127.0.0.1:{srv.server_port}/v1"
    try:
        assert complete("openai_compatible", base, "m", "good", "s", "u") == "OK"
        with pytest.raises(AiError, match="نامعتبر"):
            complete("openai_compatible", base, "m", "bad", "s", "u")
    finally:
        srv.shutdown()
    with pytest.raises(AiError, match="اتصال"):
        complete("openai_compatible", "http://127.0.0.1:9/v1", "m", "k", "s", "u")
