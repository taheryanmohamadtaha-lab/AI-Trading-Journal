"""Stores trade screenshots (copied into the app's own folder) per stage."""
from __future__ import annotations
import shutil
import time
from pathlib import Path

ALLOWED = {".png", ".jpg", ".jpeg", ".webp"}
STAGES = [("before_entry", "قبل از ورود"), ("entry", "هنگام ورود"),
          ("during", "حین معامله"), ("after_exit", "بعد از خروج"),
          ("tp_hit", "پس از رسیدن به تارگت (TP)"),
          ("sl_hit", "پس از خورده شدن حد ضرر (SL)"), ("final", "نتیجه نهایی")]
STAGE_LABEL = dict(STAGES)
BEFORE_STAGES = ("before_entry", "entry")
AFTER_STAGES = ("after_exit", "tp_hit", "sl_hit", "final")


class ImageStore:
    def __init__(self, db, base_dir):
        self.db = db
        self.base = Path(base_dir)
        self.base.mkdir(parents=True, exist_ok=True)

    def add_image(self, trade_id: int, stage: str, src) -> int:
        src = Path(src)
        if stage not in STAGE_LABEL:
            raise ValueError("مرحله‌ی تصویر نامعتبر است.")
        if src.suffix.lower() not in ALLOWED:
            raise ValueError("فقط فرمت‌های PNG، JPG، JPEG و WEBP پذیرفته می‌شوند.")
        if not src.is_file():
            raise ValueError("فایل تصویر پیدا نشد.")
        if self.db.get_trade(trade_id) is None:
            raise ValueError("معامله پیدا نشد.")
        folder = self.base / f"trade_{trade_id}"
        folder.mkdir(exist_ok=True)
        dest = folder / f"{stage}_{int(time.time() * 1000)}{src.suffix.lower()}"
        shutil.copy2(src, dest)
        with self.db.conn:
            cur = self.db.conn.execute(
                "INSERT INTO trade_images (trade_id, stage, path) VALUES (?,?,?)",
                (trade_id, stage, str(dest)))
        return cur.lastrowid

    def list_images(self, trade_id: int) -> list[dict]:
        order = {k: i for i, (k, _) in enumerate(STAGES)}
        rows = [dict(r) for r in self.db.conn.execute(
            "SELECT * FROM trade_images WHERE trade_id = ? ORDER BY id", (trade_id,))]
        return sorted(rows, key=lambda r: (order.get(r["stage"], 99), r["id"]))

    def delete_image(self, image_id: int, confirmed: bool = False):
        if not confirmed:
            raise PermissionError("حذف تصویر نیاز به تأیید دارد.")
        r = self.db.conn.execute("SELECT path FROM trade_images WHERE id = ?", (image_id,)).fetchone()
        if r:
            Path(r["path"]).unlink(missing_ok=True)
            with self.db.conn:
                self.db.conn.execute("DELETE FROM trade_images WHERE id = ?", (image_id,))

    def compare_pair(self, trade_id: int):
        """(before_path, after_path) or None parts when missing."""
        imgs = self.list_images(trade_id)
        before = next((i["path"] for i in imgs if i["stage"] in BEFORE_STAGES), None)
        after = next((i["path"] for i in reversed(imgs) if i["stage"] in AFTER_STAGES), None)
        return before, after
