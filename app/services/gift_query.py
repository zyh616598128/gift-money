"""Gift-money query helpers used by WeChat and MCP integrations."""
from __future__ import annotations

import re
from typing import Any, Dict, List, Optional

from app.database import get_connection


QUERY_WORDS = (
    "多少", "多少钱", "总共", "合计", "明细", "记录", "哪几次", "几次",
    "送了我", "给了我", "随了我", "我收", "收了", "礼金", "红包",
)

DETAIL_WORDS = ("明细", "记录", "哪几次", "列表", "详情", "都送过", "都随过")


def _row_to_dict(row: Any) -> Dict[str, Any]:
    return dict(row) if row is not None else {}


def _money(value: Any) -> str:
    amount = float(value or 0)
    if amount.is_integer():
        return str(int(amount))
    return f"{amount:.2f}".rstrip("0").rstrip(".")


def _clean_text(text: str) -> str:
    return re.sub(r"[\s，。！？?！,.、：:；;]+", "", text or "")


def search_people(user_id: int, name: str, limit: int = 10) -> List[Dict[str, Any]]:
    """Search people and include aggregate gift stats for disambiguation."""
    keyword = (name or "").strip()
    if not keyword:
        return []

    conn = get_connection()
    try:
        rows = conn.execute(
            """
            SELECT p.id, p.name, p.phone, p.address, p.note,
                   COALESCE(SUM(CASE WHEN t.direction='income' THEN t.amount ELSE 0 END), 0) AS total_income,
                   COALESCE(SUM(CASE WHEN t.direction='expense' THEN t.amount ELSE 0 END), 0) AS total_expense,
                   COALESCE(SUM(CASE WHEN t.direction='income' THEN t.amount ELSE -t.amount END), 0) AS balance,
                   COUNT(t.id) AS cnt
            FROM people p
            LEFT JOIN transactions t ON t.person_id = p.id AND t.user_id = p.user_id
            WHERE p.user_id = ? AND p.name LIKE ?
            GROUP BY p.id
            ORDER BY CASE WHEN p.name = ? THEN 0 ELSE 1 END, cnt DESC, p.name
            LIMIT ?
            """,
            (user_id, f"%{keyword}%", keyword, limit),
        ).fetchall()
        return [_row_to_dict(row) for row in rows]
    finally:
        conn.close()


def list_person_transactions(user_id: int, person_id: int, limit: int = 20) -> List[Dict[str, Any]]:
    conn = get_connection()
    try:
        rows = conn.execute(
            """
            SELECT id, name, amount, category, date, direction, note, created_at
            FROM transactions
            WHERE user_id = ? AND person_id = ?
            ORDER BY date DESC, id DESC
            LIMIT ?
            """,
            (user_id, person_id, limit),
        ).fetchall()
        return [_row_to_dict(row) for row in rows]
    finally:
        conn.close()


def get_person_gift_summary(user_id: int, person_id: int, detail_limit: int = 10) -> Optional[Dict[str, Any]]:
    conn = get_connection()
    try:
        person = conn.execute(
            "SELECT id, name, phone, address, note FROM people WHERE id = ? AND user_id = ?",
            (person_id, user_id),
        ).fetchone()
        if not person:
            return None

        stats = conn.execute(
            """
            SELECT COALESCE(SUM(CASE WHEN direction='income' THEN amount ELSE 0 END), 0) AS total_income,
                   COALESCE(SUM(CASE WHEN direction='expense' THEN amount ELSE 0 END), 0) AS total_expense,
                   COALESCE(SUM(CASE WHEN direction='income' THEN amount ELSE -amount END), 0) AS balance,
                   COUNT(CASE WHEN direction='income' THEN 1 END) AS income_count,
                   COUNT(CASE WHEN direction='expense' THEN 1 END) AS expense_count,
                   COUNT(*) AS total_count
            FROM transactions
            WHERE user_id = ? AND person_id = ?
            """,
            (user_id, person_id),
        ).fetchone()

        txns = conn.execute(
            """
            SELECT id, name, amount, category, date, direction, note, created_at
            FROM transactions
            WHERE user_id = ? AND person_id = ?
            ORDER BY date DESC, id DESC
            LIMIT ?
            """,
            (user_id, person_id, detail_limit),
        ).fetchall()

        return {
            "person": _row_to_dict(person),
            "summary": _row_to_dict(stats),
            "transactions": [_row_to_dict(row) for row in txns],
        }
    finally:
        conn.close()


def _known_name_from_text(user_id: int, text: str) -> Optional[str]:
    cleaned = _clean_text(text)
    conn = get_connection()
    try:
        rows = conn.execute(
            "SELECT DISTINCT name FROM people WHERE user_id = ? ORDER BY length(name) DESC",
            (user_id,),
        ).fetchall()
    finally:
        conn.close()

    for row in rows:
        name = row["name"]
        if name and name in cleaned:
            return name
    return None


def infer_query_name(user_id: int, text: str) -> Optional[str]:
    """Infer a person name from a natural-language query."""
    known_name = _known_name_from_text(user_id, text)
    if known_name:
        return known_name

    cleaned = _clean_text(text)
    patterns = [
        r"^(?:查|查询|看看|看下)?(?P<name>[\u4e00-\u9fa5A-Za-z0-9_·]{1,20})(?:送了我|给了我|随了我|礼金|红包|多少|多少钱|明细|记录|哪几次)",
        r"^(?:查|查询|看看|看下)(?P<name>[\u4e00-\u9fa5A-Za-z0-9_·]{1,20})",
        r"(?P<name>[\u4e00-\u9fa5A-Za-z0-9_·]{1,20})(?:总共|合计)",
    ]
    for pattern in patterns:
        match = re.search(pattern, cleaned)
        if match:
            name = match.group("name")
            for verb in ("送了我", "给了我", "随了我", "礼金", "红包"):
                name = name.replace(verb, "")
            return name.strip() or None
    return None


def answer_gift_question(user_id: int, text: str) -> Dict[str, Any]:
    """Answer common WeChat gift-money questions with structured data and text."""
    normalized = _clean_text(text)
    wants_detail = any(word in normalized for word in DETAIL_WORDS)
    name = infer_query_name(user_id, text)

    if not name:
        return {
            "intent": "help",
            "reply": "你可以这样问：\n张三送了我多少礼金？\n张三都送过哪几次？\n查张三明细",
        }

    people = search_people(user_id, name, limit=10)
    if not people:
        return {
            "intent": "person_not_found",
            "name": name,
            "reply": f"没有找到“{name}”的人员记录。可以先在系统里添加人员，或换个名字再查。",
        }

    exact = [person for person in people if person["name"] == name]
    candidates = exact or people
    if len(candidates) > 1:
        lines = [f"找到 {len(candidates)} 个“{name}”，请补充地址或备注："]
        for idx, person in enumerate(candidates[:5], start=1):
            label = person.get("address") or person.get("note") or "无地址"
            lines.append(
                f"{idx}. {person['name']}（{label}）：收{_money(person['total_income'])}，送{_money(person['total_expense'])}，{person['cnt']}笔"
            )
        return {
            "intent": "ambiguous_person",
            "name": name,
            "candidates": candidates,
            "reply": "\n".join(lines),
        }

    person = candidates[0]
    summary = get_person_gift_summary(user_id, person["id"], detail_limit=10)
    if not summary:
        return {"intent": "person_not_found", "name": name, "reply": f"没有找到“{name}”的人员记录。"}

    person_info = summary["person"]
    stats = summary["summary"]
    address = f"（{person_info['address']}）" if person_info.get("address") else ""
    lines = [
        f"{person_info['name']}{address}",
        f"收礼：{_money(stats['total_income'])} 元，{stats['income_count']} 笔",
        f"送礼：{_money(stats['total_expense'])} 元，{stats['expense_count']} 笔",
        f"净额：{_money(stats['balance'])} 元",
    ]

    if wants_detail or stats["total_count"] <= 3:
        transactions = summary["transactions"]
        if transactions:
            lines.append("明细：")
            for tx in transactions:
                direction = "收" if tx["direction"] == "income" else "送"
                note = f"（{tx['note']}）" if tx.get("note") else ""
                lines.append(f"{tx['date']} {direction}{_money(tx['amount'])} {tx['category']}{note}")
        else:
            lines.append("暂无礼金明细。")
    else:
        lines.append("要看明细可以继续问：查%s明细" % person_info["name"])

    return {
        "intent": "person_summary",
        "name": name,
        "person_id": person["id"],
        "data": summary,
        "reply": "\n".join(lines),
    }
