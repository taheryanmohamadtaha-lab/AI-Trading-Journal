"""AI settings (non-secret, JSON) and API-key storage (OS keyring when
available, otherwise a local file that is git-ignored)."""
from __future__ import annotations
import json
import os
from dataclasses import dataclass, asdict, fields
from pathlib import Path


@dataclass
class AiConfig:
    enabled: bool = False                 # OFF by default
    provider: str = "openai_compatible"
    base_url: str = ""
    model: str = ""
    daily_limit: int = 10
    max_tokens: int = 800


class SettingsStore:
    def __init__(self, data_dir):
        self.path = Path(data_dir) / "ai_settings.json"

    def load(self) -> AiConfig:
        try:
            raw = json.loads(self.path.read_text(encoding="utf-8"))
            keys = {f.name for f in fields(AiConfig)}
            return AiConfig(**{k: v for k, v in raw.items() if k in keys})
        except (OSError, ValueError, TypeError):
            return AiConfig()

    def save(self, cfg: AiConfig):
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.path.write_text(json.dumps(asdict(cfg), ensure_ascii=False, indent=2), encoding="utf-8")


class SecretStore:
    SERVICE, USER = "AITradingJournal", "api_key"

    def __init__(self, data_dir, backend: str = "auto"):
        self.file = Path(data_dir) / "api_key.secret"
        self.backend = "file"
        if backend == "auto":
            try:
                import keyring
                name = type(keyring.get_keyring()).__name__.lower()
                if "fail" not in name and "null" not in name:
                    self.backend = "keyring"
            except Exception:
                pass

    def _kr(self):
        import keyring
        return keyring

    def get(self) -> str:
        if self.backend == "keyring":
            try:
                return self._kr().get_password(self.SERVICE, self.USER) or ""
            except Exception:
                self.backend = "file"
        try:
            return self.file.read_text(encoding="utf-8").strip()
        except OSError:
            return ""

    def set(self, key: str):
        key = key.strip()
        if self.backend == "keyring":
            try:
                self._kr().set_password(self.SERVICE, self.USER, key)
                return
            except Exception:
                self.backend = "file"
        self.file.parent.mkdir(parents=True, exist_ok=True)
        self.file.write_text(key, encoding="utf-8")
        try:
            os.chmod(self.file, 0o600)
        except OSError:
            pass

    def delete(self):
        if self.backend == "keyring":
            try:
                self._kr().delete_password(self.SERVICE, self.USER)
            except Exception:
                pass
        self.file.unlink(missing_ok=True)

    def has_key(self) -> bool:
        return bool(self.get())
