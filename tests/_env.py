# -*- coding: utf-8 -*-
"""Shared test environment bootstrap.

Sets a disposable DB path BEFORE any ``app`` module is imported, so all test
modules in this package share one consistent database file regardless of load
order under ``unittest discover`` (which is single-process).
"""
import os
import sys
import tempfile
from pathlib import Path

# Idempotent: keep the first temp dir across test modules in the same process.
if "GIFT_TEST_DB" not in os.environ:
    _tmp = tempfile.mkdtemp(prefix="gift_test_")
    os.environ["GIFT_TEST_DB"] = _tmp
    os.environ["DB_PATH"] = str(Path(_tmp) / "test.db")
    os.environ["GIFT_MONEY_JWT_SECRET"] = "test-secret"
    os.environ["GIFT_MONEY_WECHAT_REQUIRE_BINDING"] = "false"

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
