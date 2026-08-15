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
        r"^(?:查|查询|看看|看下)?(?P<name>[\u4e00-\u9fa5A-Za-z0-9_·]{1,20}?)(?:送了我|给了我|随了我|礼金|红包|多少|多少钱|明细|记录|哪几次)",
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


# --------------------------------------------------------------------------- #
# Write operations (gift ledger + people + categories). Identity resolution is
# the CALLER's job (channel/external_id -> user_id); these helpers operate on
# an already-resolved user_id so the MCP tools stay single-responsibility.
# --------------------------------------------------------------------------- #
def resolve_person(conn, user_id: int, name: str, address: str = "") -> Optional[int]:
    """Find a person by (name, address); None when not found.

    Prefer an exact (name, address) match; otherwise fall back to a name-only
    match, preferring the row with an empty address so a plain name reliably
    resolves to the canonical person instead of racing a UNIQUE(user, name, address).
    """
    if not name:
        return None
    if address:
        person = conn.execute(
            "SELECT id FROM people WHERE user_id = ? AND name = ? AND address = ?",
            (user_id, name, address),
        ).fetchone()
        if person:
            return person["id"]
    person = conn.execute(
        "SELECT id FROM people WHERE user_id = ? AND name = ? "
        "ORDER BY CASE WHEN address = '' THEN 0 ELSE 1 END LIMIT 1",
        (user_id, name),
    ).fetchone()
    if person:
        return person["id"]
    return None


def create_transaction(
    user_id: int,
    name: str,
    amount: float,
    direction: str,
    category: str,
    date: str,
    note: str = "",
) -> Dict[str, Any]:
    """Record one gift transaction, auto-linking/creating the person. Returns {id, person_id}."""
    if direction not in ("income", "expense"):
        return {"ok": False, "error": f"direction must be 'income' or 'expense', got {direction!r}"}
    if not name or amount <= 0:
        return {"ok": False, "error": "name and a positive amount are required"}

    conn = get_connection()
    try:
        person_id = resolve_person(conn, user_id, name)
        if person_id is None:
            cur = conn.execute(
                "INSERT INTO people (user_id, name, phone, address, note) VALUES (?, ?, '', '', ?)",
                (user_id, name, note),
            )
            person_id = cur.lastrowid
        cur = conn.execute(
            """INSERT INTO transactions (user_id, name, amount, category, date, direction, note, person_id)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?)""",
            (user_id, name, amount, category, date, direction, note, person_id),
        )
        conn.commit()
        return {"ok": True, "id": cur.lastrowid, "person_id": person_id, "person_name": name}
    except Exception as exc:  # noqa: BLE001 - surface as structured error
        conn.rollback()
        return {"ok": False, "error": str(exc)}
    finally:
        conn.close()


def update_transaction(
    user_id: int, tx_id: int, fields: Dict[str, Any]
) -> Dict[str, Any]:
    """Update selected fields of one transaction owned by user_id."""
    allowed = {"name", "amount", "category", "date", "direction", "note"}
    updates = {k: v for k, v in fields.items() if k in allowed and v is not None}
    if not updates:
        return {"ok": False, "error": "no updatable field provided"}

    conn = get_connection()
    try:
        existing = conn.execute(
            "SELECT id FROM transactions WHERE id = ? AND user_id = ?", (tx_id, user_id)
        ).fetchone()
        if not existing:
            return {"ok": False, "error": "transaction not found or not owned by user"}

        set_clause = ", ".join(f"{k} = ?" for k in updates)
        conn.execute(
            f"UPDATE transactions SET {set_clause} WHERE id = ? AND user_id = ?",
            list(updates.values()) + [tx_id, user_id],
        )
        # Re-link person if the name changed.
        if "name" in updates:
            person_id = resolve_person(conn, user_id, str(updates["name"]))
            conn.execute(
                "UPDATE transactions SET person_id = ? WHERE id = ?",
                (person_id, tx_id),
            )
        conn.commit()
        return {"ok": True, "id": tx_id}
    except Exception as exc:  # noqa: BLE001
        conn.rollback()
        return {"ok": False, "error": str(exc)}
    finally:
        conn.close()


def delete_transaction(user_id: int, tx_id: int) -> Dict[str, Any]:
    """Delete one transaction owned by user_id."""
    conn = get_connection()
    try:
        cur = conn.execute(
            "DELETE FROM transactions WHERE id = ? AND user_id = ?", (tx_id, user_id)
        )
        conn.commit()
        if cur.rowcount == 0:
            return {"ok": False, "error": "transaction not found or not owned by user"}
        return {"ok": True, "id": tx_id}
    finally:
        conn.close()


def create_person(
    user_id: int, name: str, phone: str = "", address: str = "", note: str = ""
) -> Dict[str, Any]:
    """Create a person (name+address unique per user)."""
    if not name:
        return {"ok": False, "error": "name is required"}
    conn = get_connection()
    try:
        existing = conn.execute(
            "SELECT id FROM people WHERE user_id = ? AND name = ? AND address = ?",
            (user_id, name, address or ""),
        ).fetchone()
        if existing:
            return {"ok": False, "exists": True, "id": existing["id"], "error": f"人员 {name} 已存在"}
        cur = conn.execute(
            "INSERT INTO people (user_id, name, phone, address, note) VALUES (?, ?, ?, ?, ?)",
            (user_id, name, phone, address, note),
        )
        conn.commit()
        return {"ok": True, "id": cur.lastrowid}
    except Exception as exc:  # noqa: BLE001
        conn.rollback()
        return {"ok": False, "error": str(exc)}
    finally:
        conn.close()


def update_person(user_id: int, person_id: int, fields: Dict[str, Any]) -> Dict[str, Any]:
    """Update selected fields of one person owned by user_id."""
    allowed = {"name", "phone", "address", "note"}
    updates = {k: v for k, v in fields.items() if k in allowed and v is not None}
    if not updates:
        return {"ok": False, "error": "no updatable field provided"}

    conn = get_connection()
    try:
        existing = conn.execute(
            "SELECT id FROM people WHERE id = ? AND user_id = ?", (person_id, user_id)
        ).fetchone()
        if not existing:
            return {"ok": False, "error": "person not found or not owned by user"}
        set_clause = ", ".join(f"{k} = ?" for k in updates)
        conn.execute(
            f"UPDATE people SET {set_clause} WHERE id = ? AND user_id = ?",
            list(updates.values()) + [person_id, user_id],
        )
        conn.commit()
        return {"ok": True, "id": person_id}
    except Exception as exc:  # noqa: BLE001
        conn.rollback()
        return {"ok": False, "error": str(exc)}
    finally:
        conn.close()


def ledger_summary(user_id: int) -> Dict[str, Any]:
    """Global gift ledger summary: totals, monthly trend, category breakdown."""
    conn = get_connection()
    try:
        total = conn.execute(
            """SELECT COALESCE(SUM(CASE WHEN direction='income' THEN amount ELSE 0 END), 0) AS ti,
                      COALESCE(SUM(CASE WHEN direction='expense' THEN amount ELSE 0 END), 0) AS te,
                      COUNT(CASE WHEN direction='income' THEN 1 END) AS ic,
                      COUNT(CASE WHEN direction='expense' THEN 1 END) AS ec
               FROM transactions WHERE user_id = ?""",
            (user_id,),
        ).fetchone()
        monthly = conn.execute(
            """SELECT substr(date, 1, 7) AS month,
                      COALESCE(SUM(CASE WHEN direction='income' THEN amount ELSE 0 END), 0) AS income,
                      COALESCE(SUM(CASE WHEN direction='expense' THEN amount ELSE 0 END), 0) AS expense
               FROM transactions WHERE user_id = ?
               GROUP BY substr(date, 1, 7) ORDER BY month DESC LIMIT 12""",
            (user_id,),
        ).fetchall()
        categories = conn.execute(
            """SELECT category,
                      COALESCE(SUM(CASE WHEN direction='income' THEN amount ELSE 0 END), 0) AS income,
                      COALESCE(SUM(CASE WHEN direction='expense' THEN amount ELSE 0 END), 0) AS expense
               FROM transactions WHERE user_id = ?
               GROUP BY category ORDER BY category""",
            (user_id,),
        ).fetchall()
        top = conn.execute(
            """SELECT p.id, p.name, p.address,
                      COALESCE(SUM(CASE WHEN t.direction='income' THEN t.amount ELSE 0 END), 0) AS total_income,
                      COALESCE(SUM(CASE WHEN t.direction='expense' THEN t.amount ELSE 0 END), 0) AS total_expense,
                      COALESCE(SUM(CASE WHEN t.direction='income' THEN t.amount ELSE -t.amount END), 0) AS balance,
                      COUNT(t.id) AS cnt
               FROM people p
               LEFT JOIN transactions t ON t.person_id = p.id AND t.user_id = ?
               WHERE p.user_id = ?
               GROUP BY p.id, p.name, p.address
               HAVING cnt > 0
               ORDER BY balance DESC LIMIT 20""",
            (user_id, user_id),
        ).fetchall()
        return {
            "total_income": total["ti"],
            "total_expense": total["te"],
            "balance": total["ti"] - total["te"],
            "income_count": total["ic"],
            "expense_count": total["ec"],
            "monthly": [_row_to_dict(row) for row in monthly],
            "categories": [_row_to_dict(row) for row in categories],
            "top_people": [_row_to_dict(row) for row in top],
        }
    finally:
        conn.close()


def list_categories(user_id: int) -> List[Dict[str, Any]]:
    """List the user's transaction categories."""
    conn = get_connection()
    try:
        rows = conn.execute(
            "SELECT id, name, color FROM categories WHERE user_id = ? ORDER BY name",
            (user_id,),
        ).fetchall()
        return [_row_to_dict(row) for row in rows]
    finally:
        conn.close()


def create_category(user_id: int, name: str, color: str = "#6366f1") -> Dict[str, Any]:
    """Create a category (name unique per user)."""
    if not name:
        return {"ok": False, "error": "name is required"}
    conn = get_connection()
    try:
        existing = conn.execute(
            "SELECT id FROM categories WHERE user_id = ? AND name = ?", (user_id, name)
        ).fetchone()
        if existing:
            return {"ok": False, "exists": True, "id": existing["id"], "error": f"分类 {name} 已存在"}
        cur = conn.execute(
            "INSERT INTO categories (user_id, name, color) VALUES (?, ?, ?)",
            (user_id, name, color),
        )
        conn.commit()
        return {"ok": True, "id": cur.lastrowid}
    except Exception as exc:  # noqa: BLE001
        conn.rollback()
        return {"ok": False, "error": str(exc)}
    finally:
        conn.close()
