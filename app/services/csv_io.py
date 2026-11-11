import csv
from app.database.db import Database

FIELDS = ["market", "symbol", "side", "quantity", "entry_price", "exit_price",
          "stop_loss", "take_profit", "opened_at", "closed_at", "strategy",
          "timeframe", "fees", "pnl", "notes"]
_NUM = {"quantity", "entry_price", "exit_price", "stop_loss", "take_profit", "fees", "pnl"}


def export_csv(db: Database, path: str) -> int:
    rows = db.list_trades()
    with open(path, "w", newline="", encoding="utf-8-sig") as fh:
        w = csv.DictWriter(fh, fieldnames=FIELDS, extrasaction="ignore")
        w.writeheader()
        w.writerows(rows)
    return len(rows)


def import_csv(db: Database, path: str) -> dict:
    """Returns {'added', 'duplicates', 'errors': [(line, message)]}."""
    res = {"added": 0, "duplicates": 0, "errors": []}
    with open(path, newline="", encoding="utf-8-sig") as fh:
        for i, row in enumerate(csv.DictReader(fh), start=2):
            try:
                t = {k: (row.get(k) or None) for k in FIELDS}
                for k in _NUM:
                    if t[k] is not None:
                        t[k] = float(t[k])
                t["status"] = "closed" if t["exit_price"] is not None else "open"
                t["data_source"] = "import"
                if t["exit_price"] is not None and t["pnl"] is None:
                    raise ValueError("ستون pnl برای معامله بسته الزامی است")
                new_id = db.add_trade({k: v for k, v in t.items() if v is not None})
                res["duplicates" if new_id is None else "added"] += 1
            except Exception as e:  # keep importing other rows
                res["errors"].append((i, str(e)))
    return res
