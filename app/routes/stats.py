"""Stats routes: summary, person detail."""
from fastapi import APIRouter, Query, Depends, Request
from app.database import get_connection
from app.routes.transactions import get_current_user

router = APIRouter(prefix="/api/stats", tags=["stats"])


@router.get("/summary")
def get_summary(request: Request):
    """获取统计摘要"""
    user = get_current_user(request)
    user_id = user["user_id"]
    conn = get_connection()
    try:
        # Totals
        total = conn.execute(
            "SELECT COALESCE(SUM(CASE WHEN direction='income' THEN amount ELSE 0 END),0) as ti,"
            " COALESCE(SUM(CASE WHEN direction='expense' THEN amount ELSE 0 END),0) as te,"
            " COUNT(CASE WHEN direction='income' THEN 1 END) as ic,"
            " COUNT(CASE WHEN direction='expense' THEN 1 END) as ec "
            f"FROM transactions WHERE user_id={user_id}"
        ).fetchone()

        # Category income
        cat_inc = conn.execute(
            f"SELECT category, SUM(amount) as total FROM transactions "
            f"WHERE user_id={user_id} AND direction='income' GROUP BY category ORDER BY total DESC"
        ).fetchall()

        # Category expense
        cat_exp = conn.execute(
            f"SELECT category, SUM(amount) as total FROM transactions "
            f"WHERE user_id={user_id} AND direction='expense' GROUP BY category ORDER BY total DESC"
        ).fetchall()

        # Monthly
        monthly = conn.execute(
            f"SELECT substr(date,1,7) as month, "
            f"  COALESCE(SUM(CASE WHEN direction='income' THEN amount ELSE 0 END),0) as income, "
            f"  COALESCE(SUM(CASE WHEN direction='expense' THEN amount ELSE 0 END),0) as expense, "
            f"  COALESCE(SUM(CASE WHEN direction='income' THEN amount ELSE 0 END),0) - "
            f"  COALESCE(SUM(CASE WHEN direction='expense' THEN amount ELSE 0 END),0) as net "
            f"FROM transactions WHERE user_id={user_id} GROUP BY substr(date,1,7) ORDER BY month DESC LIMIT 12"
        ).fetchall()

        # Person stats - 按 (name, address) 分组，通过 people 表关联
        person_stats = conn.execute(
            f"""SELECT p.id, p.name, p.address,
                  COALESCE(SUM(CASE WHEN t.direction='income' THEN t.amount ELSE 0 END),0) as total_income,
                  COALESCE(SUM(CASE WHEN t.direction='expense' THEN t.amount ELSE 0 END),0) as total_expense,
                  COALESCE(SUM(CASE WHEN t.direction='income' THEN t.amount ELSE -t.amount END),0) as balance,
                  COUNT(t.id) as cnt
                FROM people p
                LEFT JOIN transactions t ON t.person_id=p.id AND t.user_id={user_id}
                WHERE p.user_id={user_id}
                GROUP BY p.id, p.name, p.address
                HAVING cnt > 0
                ORDER BY balance DESC LIMIT 20"""
        ).fetchall()

        def _d(rows):
            return [dict(r) for r in rows]

        return {
            "total_income": total["ti"],
            "total_expense": total["te"],
            "balance": total["ti"] - total["te"],
            "income_count": total["ic"],
            "expense_count": total["ec"],
            "category_income": _d(cat_inc),
            "category_expense": _d(cat_exp),
            "monthly": _d(monthly),
            "person_stats": _d(person_stats),
        }
    finally:
        conn.close()


@router.get("/person/{person_id}")
def get_person_detail(person_id: int, request: Request):
    """获取人员详情"""
    user = get_current_user(request)
    user_id = user["user_id"]
    conn = get_connection()
    try:
        person = conn.execute(
            "SELECT id, name, phone, address, note FROM people WHERE id = ? AND user_id = ?",
            (person_id, user_id),
        ).fetchone()
        if not person:
            return {"error": "人员不存在"}

        stats = conn.execute(
            "SELECT "
            "  COALESCE(SUM(CASE WHEN direction='income' THEN amount ELSE 0 END),0) as ti, "
            "  COALESCE(SUM(CASE WHEN direction='expense' THEN amount ELSE 0 END),0) as te, "
            "  COALESCE(SUM(CASE WHEN direction='income' THEN amount ELSE -amount END),0) as bal "
            "FROM transactions WHERE person_id=? AND user_id=?",
            (person_id, user_id),
        ).fetchone()

        txns = conn.execute(
            "SELECT id, name, amount, category, date, direction, note "
            "FROM transactions WHERE person_id=? AND user_id=? ORDER BY date DESC",
            (person_id, user_id),
        ).fetchall()

        return {
            **dict(person),
            "total_income": stats["ti"],
            "total_expense": stats["te"],
            "balance": stats["bal"],
            "transactions": [dict(r) for r in txns],
        }
    finally:
        conn.close()