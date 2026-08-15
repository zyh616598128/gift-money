# -*- coding: utf-8 -*-
"""Seed demo gift-money ledger data for the interop-fabric end-to-end demo.

Idempotent: safe to run repeatedly. Inserts people + transactions for the
default MCP user (user_id=1) so the fabric's MCP hop (answer_gift_question)
returns real business data instead of a canned reply.
"""
import logging
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))

from app.database import init_db, get_connection  # noqa: E402

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

USER_ID = 1


def seed() -> None:
    init_db()
    conn = get_connection()
    try:
        # ── Target user must exist (MCP default user_id=1) ──
        row = conn.execute("SELECT id FROM users WHERE id = ?", (USER_ID,)).fetchone()
        if not row:
            # init_db created 'admin' but with a random PK; align to USER_ID if free.
            conn.execute(
                "INSERT OR IGNORE INTO users (id, username, password_hash, display_name, is_admin) "
                "VALUES (?, 'mcp-user', 'x', '台账用户', 0)",
                (USER_ID,),
            )

        # ── People: 张三 ──
        person = conn.execute(
            "SELECT id FROM people WHERE user_id = ? AND name = ? AND address = ?",
            (USER_ID, "张三", "北京朝阳"),
        ).fetchone()
        if person:
            person_id = int(person["id"])
        else:
            cur = conn.execute(
                "INSERT INTO people (user_id, name, phone, address, note) VALUES (?, '张三', '13800000001', '北京朝阳', '演示台账')",
                (USER_ID,),
            )
            person_id = int(cur.lastrowid)

        # ── Transactions for 张三 (income = 张三送给我) ──
        txns = [
            # (name, amount, category, date, direction, note)
            ("张三", 500.0, "婚嫁", "2024-05-01", "income", "婚礼随礼"),
            ("张三", 800.0, "婚嫁", "2025-10-12", "income", "二胎满月酒"),
            ("张三", 200.0, "生日", "2024-03-08", "income", "生日红包"),
            ("张三", 300.0, "其他", "2025-01-20", "expense", "回礼"),
        ]
        inserted = 0
        for name, amount, category, date, direction, note in txns:
            exists = conn.execute(
                "SELECT id FROM transactions WHERE user_id = ? AND person_id = ? AND amount = ? AND date = ? AND note = ?",
                (USER_ID, person_id, amount, date, note),
            ).fetchone()
            if not exists:
                conn.execute(
                    "INSERT INTO transactions (user_id, name, amount, category, date, direction, note, person_id) "
                    "VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
                    (USER_ID, name, amount, category, date, direction, note, person_id),
                )
                inserted += 1

        conn.commit()
        logger.info("person_id=%s inserted=%s", person_id, inserted)
    finally:
        conn.close()


if __name__ == "__main__":
    seed()