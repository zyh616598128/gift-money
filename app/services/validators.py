"""Shared input validators for gift-money writes.

Every write path (MCP tools, REST API, batch import) MUST normalize/validate
through this single source of truth, so a new entry point cannot silently accept
a format the rest of the system rejects. The database CHECK constraint
(transactions.date GLOB '[0-9][0-9][0-9][0-9]-[0-9][0-9]-[0-9][0-9]') is the final
boundary; these validators give callers a friendly error BEFORE the write.
"""
from __future__ import annotations

import datetime as _dt
import re
from typing import Optional

# Strict ISO date as the storage/query contract across every path.
DATE_PATTERN = re.compile(r"\d{4}-\d{2}-\d{2}")


def normalize_date(value: str) -> Optional[str]:
    """Parse a user-facing date into a strict ``YYYY-MM-DD`` string, or None.

    Accepts Chinese relative dates (今天/今日/昨天/昨日/前天/大前天), ISO-ish
    forms (2026-08-16, 2026/08/16, 2026.08.16, 20260816, 2026年8月16日), and
    bare month-day forms (8月16日, 08-16). Anything unrecognizable returns None
    so the caller can reject it instead of persisting a junk value.
    """
    if not isinstance(value, str):
        return None
    text = value.strip()
    if not text:
        return None

    today = _dt.date.today()

    relative = {
        "今天": 0, "今日": 0,
        "昨天": -1, "昨日": -1,
        "前天": -2, "大前天": -3,
    }
    if text in relative:
        return (_dt.date.today() + _dt.timedelta(days=relative[text])).isoformat()

    # 2026-08-16 / 2026/08/16 / 2026.08.16 / 2026年8月16日
    iso = re.fullmatch(r"(\d{4})[-/.年](\d{1,2})[-/.月](\d{1,2})日?", text)
    if iso:
        year, month, day = (int(g) for g in iso.groups())
        try:
            return _dt.date(year, month, day).isoformat()
        except ValueError:
            return None

    # 20260816 (bare)
    bare = re.fullmatch(r"(\d{4})(\d{2})(\d{2})", text)
    if bare:
        year, month, day = (int(g) for g in bare.groups())
        try:
            return _dt.date(year, month, day).isoformat()
        except ValueError:
            return None

    # 8月16日 / 08-16 (assume the current year)
    month_day = re.fullmatch(r"(\d{1,2})[月/-](\d{1,2})日?", text)
    if month_day:
        month, day = (int(g) for g in month_day.groups())
        try:
            return _dt.date(today.year, month, day).isoformat()
        except ValueError:
            return None

    return None


def is_iso_date(value: str) -> bool:
    """True only for strict YYYY-MM-DD with a real calendar date."""
    if not isinstance(value, str) or not DATE_PATTERN.fullmatch(value.strip()):
        return False
    try:
        _dt.date.fromisoformat(value.strip())
        return True
    except ValueError:
        return False


def date_error(value: str) -> str:
    """Human-friendly validation error for an unrecognized date input."""
    return (
        f"无法识别的日期 {value!r}，请使用 YYYY-MM-DD（例如 2026-08-16），"
        "或 今天/昨天/8月16日。"
    )
