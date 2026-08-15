# -*- coding: utf-8 -*-
"""Verify the legacy-table migration: an old transactions table (no date CHECK)
is rebuilt with the constraint, dirty legacy dates are repaired, and rows survive.

This uses its OWN disposable database file (not the shared one) so it can build
the legacy schema from scratch without interfering with the other guard tests.

Run:  python -m unittest discover -s tests -p "test_*.py"
"""
import os
import sqlite3
import sys
import tempfile
import unittest
from pathlib import Path

from tests import _env  # noqa: F401  (ensures app import path is ready)

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))


class TestDateCheckMigration(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        # Point app.database at a private DB for this migration test.
        _tmp = tempfile.mkdtemp(prefix="gift_migrate_")
        cls._db_path = str(Path(_tmp) / "test.db")
        import app.database as dbmod
        dbmod.DB_PATH = cls._db_path

        # Build a LEGACY transactions table (no date CHECK) with dirty dates.
        conn = sqlite3.connect(cls._db_path)
        conn.execute("""
            CREATE TABLE transactions (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                user_id INTEGER NOT NULL DEFAULT 1,
                name TEXT NOT NULL,
                amount REAL NOT NULL,
                category TEXT NOT NULL DEFAULT '其他',
                date TEXT NOT NULL,
                direction TEXT NOT NULL CHECK(direction IN ('income', 'expense')),
                note TEXT DEFAULT '',
                person_id INTEGER,
                created_at TEXT DEFAULT (datetime('now', 'localtime'))
            )
        """)
        conn.execute("INSERT INTO transactions (name, amount, date, direction, created_at) VALUES ('何双燕', 600, '今天', 'expense', '2026-08-16 01:36:13')")
        conn.execute("INSERT INTO transactions (name, amount, date, direction, created_at) VALUES ('张琳', 300, '20260524', 'income', '2026-05-24 10:00:00')")
        conn.execute("INSERT INTO transactions (name, amount, date, direction, created_at) VALUES ('正常', 100, '2026-08-15', 'income', '2026-08-15 10:00:00')")
        conn.execute("CREATE TABLE users (id INTEGER PRIMARY KEY AUTOINCREMENT, username TEXT NOT NULL UNIQUE)")
        conn.execute("INSERT INTO users (username) VALUES ('admin')")
        conn.commit()
        conn.close()

        dbmod.init_db()

    def test_table_gained_date_check(self):
        import app.database as dbmod
        conn = sqlite3.connect(self._db_path)
        try:
            ddl = conn.execute(
                "SELECT sql FROM sqlite_master WHERE name='transactions'"
            ).fetchone()[0]
        finally:
            conn.close()
        self.assertIn("CHECK(date GLOB", ddl)

    def test_legacy_rows_survive_and_dates_are_repaired(self):
        conn = sqlite3.connect(self._db_path)
        try:
            rows = conn.execute(
                "SELECT name, date FROM transactions ORDER BY id"
            ).fetchall()
        finally:
            conn.close()
        by_name = {r[0]: r[1] for r in rows}
        self.assertEqual(len(rows), 3)
        self.assertEqual(by_name["何双燕"], "2026-08-16")   # 今天 → relative date
        self.assertEqual(by_name["张琳"], "2026-05-24")     # YYYYMMDD → ISO
        self.assertEqual(by_name["正常"], "2026-08-15")     # already clean

    def test_check_rejects_non_iso_after_migration(self):
        conn = sqlite3.connect(self._db_path)
        try:
            with self.assertRaises(Exception):
                conn.execute(
                    "INSERT INTO transactions (name, amount, date, direction) VALUES ('X', 1, '昨天', 'income')"
                )
                conn.commit()
        finally:
            conn.close()


if __name__ == "__main__":
    unittest.main()
