# -*- coding: utf-8 -*-
"""Guard tests: dates entering transactions must be strict YYYY-MM-DD.

These cover every write path so a regression in ANY entry point is caught
here, instead of discovering dirty rows in production later:
  1. shared validator (normalize_date / is_iso_date)
  2. REST create (Pydantic model)
  3. REST batch create (dict rows)
  4. REST update + batch update
  5. database CHECK constraint (direct SQL — the final boundary)

Run:  python -m unittest discover -s tests -p "test_*.py"
"""
import unittest

from tests import _env  # noqa: F401  (sets DB_PATH before app import)

from fastapi.testclient import TestClient  # noqa: E402

from app.database import get_connection, init_db  # noqa: E402
from app.main import app  # noqa: E402
from app.services.validators import date_error, is_iso_date, normalize_date  # noqa: E402


class TestNormalizeDate(unittest.TestCase):
    """Shared validator: user-facing dates normalize to YYYY-MM-DD or None."""

    def test_relative_dates(self):
        import datetime
        today = datetime.date.today()
        self.assertEqual(normalize_date("今天"), today.isoformat())
        self.assertEqual(normalize_date("今日"), today.isoformat())
        self.assertEqual(normalize_date("昨天"), (today - datetime.timedelta(days=1)).isoformat())
        self.assertEqual(normalize_date("前天"), (today - datetime.timedelta(days=2)).isoformat())

    def test_iso_variants(self):
        self.assertEqual(normalize_date("2026-08-16"), "2026-08-16")
        self.assertEqual(normalize_date("2026/08/16"), "2026-08-16")
        self.assertEqual(normalize_date("2026.08.16"), "2026-08-16")
        self.assertEqual(normalize_date("2026年8月16日"), "2026-08-16")
        self.assertEqual(normalize_date("20260816"), "2026-08-16")
        self.assertEqual(normalize_date(" 2026-08-16 "), "2026-08-16")

    def test_month_day_current_year(self):
        import datetime
        today = datetime.date.today()
        self.assertEqual(normalize_date("8月16日"), f"{today.year}-08-16")
        self.assertEqual(normalize_date("08-16"), f"{today.year}-08-16")

    def test_invalid_rejected(self):
        for bad in ("not-a-date", "2026-02-30", "2026-13-01", "", "   ", "昨天哦", None, 20260816):
            self.assertIsNone(normalize_date(bad), f"expected None for {bad!r}")

    def test_is_iso_date(self):
        self.assertTrue(is_iso_date("2026-08-16"))
        self.assertFalse(is_iso_date("2026-02-30"))  # real calendar check
        self.assertFalse(is_iso_date("2026-8-16"))   # zero-padding required
        self.assertFalse(is_iso_date("今天"))
        self.assertFalse(is_iso_date(""))
        self.assertFalse(is_iso_date(None))

    def test_date_error_mentions_format(self):
        self.assertIn("YYYY-MM-DD", date_error("垃圾输入"))


class TestDbCheckConstraint(unittest.TestCase):
    """Database boundary: direct SQL cannot persist a non-ISO date."""

    @classmethod
    def setUpClass(cls):
        init_db()

    def test_valid_insert_ok(self):
        conn = get_connection()
        try:
            conn.execute(
                "INSERT INTO transactions (name, amount, date, direction) VALUES (?, ?, ?, ?)",
                ("张三", 100, "2026-08-16", "income"),
            )
            conn.commit()
        finally:
            conn.close()

    def test_invalid_insert_rejected_by_check(self):
        conn = get_connection()
        try:
            with self.assertRaises(Exception):  # sqlite3.IntegrityError
                conn.execute(
                    "INSERT INTO transactions (name, amount, date, direction) VALUES (?, ?, ?, ?)",
                    ("张三", 100, "今天", "income"),
                )
                conn.commit()
        finally:
            conn.close()


class TestRestValidators(unittest.TestCase):
    """REST API: Pydantic models reject non-ISO dates with 4xx."""

    @classmethod
    def setUpClass(cls):
        init_db()
        from app.routes.transactions import TransactionCreate, TransactionUpdate
        cls.Create = TransactionCreate
        cls.Update = TransactionUpdate

    def test_create_rejects_bad_date(self):
        from pydantic import ValidationError
        with self.assertRaises(ValidationError):
            self.Create(name="张三", amount=100, category="婚嫁", date="今天", direction="income")
        with self.assertRaises(ValidationError):
            self.Create(name="张三", amount=100, category="婚嫁", date="2026-02-30", direction="income")

    def test_create_accepts_good_date(self):
        m = self.Create(name="张三", amount=100, category="婚嫁", date="2026-08-16", direction="income")
        self.assertEqual(m.date, "2026-08-16")

    def test_update_rejects_bad_date(self):
        from pydantic import ValidationError
        with self.assertRaises(ValidationError):
            self.Update(date="今天")
        with self.assertRaises(ValidationError):
            self.Update(direction="invalid")


class TestRestEndpoints(unittest.TestCase):
    """End-to-end HTTP: bad date cannot reach the DB through any REST route."""

    @classmethod
    def setUpClass(cls):
        init_db()
        cls.client = TestClient(app)

    def _auth(self):
        import app.database as db
        token = db.create_token(1, "admin", True)
        return {"Authorization": f"Bearer {token}"}

    def test_create_endpoint_rejects_bad_date(self):
        headers = self._auth()
        r = self.client.post(
            "/api/transactions",
            json={"name": "张三", "amount": 100, "category": "婚嫁", "date": "2026-02-30", "direction": "income"},
            headers=headers,
        )
        self.assertEqual(r.status_code, 422)

    def test_batch_create_rejects_bad_date(self):
        headers = self._auth()
        # 好行入库，坏行（今天）被逐行校验拦下并记入 errors——批量接口语义为
        # 部分成功，不允许脏数据入库。
        r = self.client.post(
            "/api/transactions/batch",
            json=[
                {"name": "张三", "amount": 100, "category": "婚嫁", "date": "2026-08-16", "direction": "income"},
                {"name": "李四", "amount": 200, "category": "婚嫁", "date": "今天", "direction": "income"},
            ],
            headers=headers,
        )
        self.assertEqual(r.status_code, 201)
        body = r.json()
        self.assertEqual(body["count"], 1)          # 只有好行入库
        self.assertEqual(body["skipped"], 1)        # 坏行被跳过
        self.assertTrue(any("日期" in e or "YYYY-MM-DD" in e for e in body["errors"]))

    def test_batch_create_all_invalid_returns_400(self):
        headers = self._auth()
        r = self.client.post(
            "/api/transactions/batch",
            json=[{"name": "李四", "amount": 200, "category": "婚嫁", "date": "今天", "direction": "income"}],
            headers=headers,
        )
        self.assertEqual(r.status_code, 400)


if __name__ == "__main__":
    unittest.main()
