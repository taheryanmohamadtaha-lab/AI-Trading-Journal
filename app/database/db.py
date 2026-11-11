"""SQLite storage with schema versioning and duplicate protection."""
from __future__ import annotations
import hashlib
import sqlite3
from pathlib import Path

# Each migration runs once, in order. Never edit old ones; append new.
MIGRATIONS = [
    """
    CREATE TABLE trades (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        market TEXT NOT NULL CHECK (market IN ('forex','crypto','iran')),
        symbol TEXT NOT NULL,
        side TEXT NOT NULL CHECK (side IN ('buy','sell')),
        status TEXT NOT NULL DEFAULT 'closed' CHECK (status IN ('open','closed')),
        quantity REAL NOT NULL CHECK (quantity > 0),
        entry_price REAL NOT NULL CHECK (entry_price > 0),
        exit_price REAL,
        stop_loss REAL,
        take_profit REAL,
        opened_at TEXT NOT NULL,
        closed_at TEXT,
        timeframe TEXT,
        strategy TEXT,
        fees REAL DEFAULT 0,
        pnl REAL,
        risk_amount REAL,
        r_multiple REAL,
        notes TEXT,
        data_source TEXT NOT NULL DEFAULT 'manual'
            CHECK (data_source IN ('manual','import','image_confirmed')),
        dedupe_hash TEXT NOT NULL UNIQUE
    );
    CREATE TABLE trade_images (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        trade_id INTEGER NOT NULL REFERENCES trades(id) ON DELETE CASCADE,
        stage TEXT NOT NULL,
        path TEXT NOT NULL
    );
    """,
    """
    ALTER TABLE trades ADD COLUMN params TEXT;
    ALTER TABLE trades ADD COLUMN close_reason TEXT;
    """,
    """
    ALTER TABLE trades ADD COLUMN followed_plan INTEGER;
    ALTER TABLE trades ADD COLUMN mood INTEGER;
    ALTER TABLE trades ADD COLUMN fomo INTEGER DEFAULT 0;
    ALTER TABLE trades ADD COLUMN revenge INTEGER DEFAULT 0;
    ALTER TABLE trades ADD COLUMN rushed INTEGER DEFAULT 0;
    ALTER TABLE trades ADD COLUMN early_exit INTEGER DEFAULT 0;
    ALTER TABLE trades ADD COLUMN moved_sl INTEGER DEFAULT 0;
    ALTER TABLE trades ADD COLUMN entry_reason TEXT;
    ALTER TABLE trades ADD COLUMN lesson TEXT;
    CREATE TABLE goals (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        metric TEXT NOT NULL,
        op TEXT NOT NULL CHECK (op IN ('>=','<=')),
        target REAL NOT NULL,
        created_at TEXT NOT NULL
    );
    CREATE TABLE ai_usage (day TEXT PRIMARY KEY, calls INTEGER NOT NULL DEFAULT 0);
    """,
]


class Database:
    def __init__(self, path: str | Path = ":memory:"):
        self.conn = sqlite3.connect(str(path))
        self.conn.row_factory = sqlite3.Row
        self.conn.execute("PRAGMA foreign_keys = ON")
        self._migrate()

    def _migrate(self):
        self.conn.execute("CREATE TABLE IF NOT EXISTS schema_version (version INTEGER)")
        row = self.conn.execute("SELECT MAX(version) v FROM schema_version").fetchone()
        current = row["v"] or 0
        for i, sql in enumerate(MIGRATIONS[current:], start=current + 1):
            with self.conn:
                self.conn.executescript(sql)
                self.conn.execute("INSERT INTO schema_version VALUES (?)", (i,))

    @property
    def version(self) -> int:
        return self.conn.execute("SELECT MAX(version) FROM schema_version").fetchone()[0]

    @staticmethod
    def make_hash(t: dict) -> str:
        raw = "|".join(str(t.get(k)) for k in
                       ("market", "symbol", "side", "quantity", "entry_price",
                        "exit_price", "opened_at", "closed_at"))
        return hashlib.sha256(raw.encode()).hexdigest()

    def add_trade(self, t: dict) -> int | None:
        """Insert a trade. Returns new id, or None if it is a duplicate."""
        t = dict(t)
        if t.get("status", "closed") == "closed" and t.get("exit_price") is None:
            raise ValueError("Closed trade needs an exit price")
        t["dedupe_hash"] = self.make_hash(t)
        cols = [c for c in t if c in _TRADE_COLS or c == "dedupe_hash"]
        sql = f"INSERT INTO trades ({','.join(cols)}) VALUES ({','.join('?' * len(cols))})"
        try:
            with self.conn:
                cur = self.conn.execute(sql, [t[c] for c in cols])
            return cur.lastrowid
        except sqlite3.IntegrityError as e:
            if "dedupe_hash" in str(e):
                return None
            raise

    def list_trades(self, market: str | None = None) -> list[dict]:
        q, args = "SELECT * FROM trades", ()
        if market:
            q, args = q + " WHERE market = ?", (market,)
        return [dict(r) for r in self.conn.execute(q + " ORDER BY opened_at", args)]

    def get_trade(self, trade_id: int) -> dict | None:
        r = self.conn.execute("SELECT * FROM trades WHERE id = ?", (trade_id,)).fetchone()
        return dict(r) if r else None

    def close_trade(self, trade_id: int, fields: dict):
        """Finish an open trade. `fields` comes from build_trade()."""
        row = self.get_trade(trade_id)
        if row is None:
            raise ValueError("معامله پیدا نشد.")
        if row["status"] == "closed":
            raise ValueError("این معامله قبلاً بسته شده است.")
        new = {**row, **{k: fields[k] for k in (
            "exit_price", "closed_at", "pnl", "fees", "risk_amount",
            "r_multiple", "close_reason") if k in fields}, "status": "closed"}
        new["dedupe_hash"] = self.make_hash(new)
        cols = ["exit_price", "closed_at", "pnl", "fees", "risk_amount",
                "r_multiple", "close_reason", "status", "dedupe_hash"]
        try:
            with self.conn:
                self.conn.execute(
                    f"UPDATE trades SET {', '.join(c + ' = ?' for c in cols)} WHERE id = ?",
                    [new.get(c) for c in cols] + [trade_id])
        except sqlite3.IntegrityError:
            raise ValueError("معامله‌ای با همین مشخصات قبلاً ثبت شده است.")

    BEHAVIOR_COLS = ("followed_plan", "mood", "fomo", "revenge", "rushed",
                     "early_exit", "moved_sl", "entry_reason", "lesson")

    def update_behavior(self, trade_id: int, fields: dict):
        cols = [c for c in self.BEHAVIOR_COLS if c in fields]
        if not cols:
            return
        with self.conn:
            self.conn.execute(
                f"UPDATE trades SET {', '.join(c + ' = ?' for c in cols)} WHERE id = ?",
                [fields[c] for c in cols] + [trade_id])

    # ---- goals
    def add_goal(self, metric: str, op: str, target: float) -> int:
        import datetime
        with self.conn:
            cur = self.conn.execute("INSERT INTO goals (metric, op, target, created_at) VALUES (?,?,?,?)",
                                    (metric, op, float(target), datetime.datetime.now().isoformat(timespec="minutes")))
        return cur.lastrowid

    def list_goals(self) -> list[dict]:
        return [dict(r) for r in self.conn.execute("SELECT * FROM goals ORDER BY id")]

    def delete_goal(self, goal_id: int):
        with self.conn:
            self.conn.execute("DELETE FROM goals WHERE id = ?", (goal_id,))

    # ---- AI usage counter (per day)
    @staticmethod
    def _today() -> str:
        import datetime
        return datetime.date.today().isoformat()

    def ai_calls_today(self) -> int:
        r = self.conn.execute("SELECT calls FROM ai_usage WHERE day = ?", (self._today(),)).fetchone()
        return r["calls"] if r else 0

    def ai_register_call(self):
        with self.conn:
            self.conn.execute("INSERT INTO ai_usage (day, calls) VALUES (?, 1) "
                              "ON CONFLICT(day) DO UPDATE SET calls = calls + 1", (self._today(),))

    def delete_trade(self, trade_id: int, confirmed: bool = False):
        if not confirmed:
            raise PermissionError("Deletion requires explicit confirmation")
        with self.conn:
            self.conn.execute("DELETE FROM trades WHERE id = ?", (trade_id,))

    def backup(self, dest: str | Path):
        out = sqlite3.connect(str(dest))
        with out:
            self.conn.backup(out)
        out.close()


_TRADE_COLS = {"market", "symbol", "side", "status", "quantity", "entry_price",
               "exit_price", "stop_loss", "take_profit", "opened_at", "closed_at",
               "timeframe", "strategy", "fees", "pnl", "risk_amount",
               "r_multiple", "notes", "data_source", "params", "close_reason",
               "followed_plan", "mood", "fomo", "revenge", "rushed", "early_exit",
               "moved_sl", "entry_reason", "lesson"}


def _import_from(self, other_path) -> int:
    """Merge trades from another journal file (restore / move to a new PC).
    Duplicates are skipped automatically. Returns number of new trades."""
    other = Database(other_path)
    added = 0
    for t in other.list_trades():
        t.pop("id", None)
        t.pop("dedupe_hash", None)
        if self.add_trade(t) is not None:
            added += 1
    return added


Database.import_from = _import_from
