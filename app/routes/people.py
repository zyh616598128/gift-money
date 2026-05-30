"""Person management routes: search, dedup, conflict resolution."""
from fastapi import APIRouter, HTTPException, Query, Depends, Request
from pydantic import BaseModel
from typing import Optional, List
from app.database import get_connection
from app.routes.transactions import get_current_user

router = APIRouter(prefix="/api/people", tags=["people"])


class PersonCreate(BaseModel):
    name: str
    phone: str = ""
    address: str = ""
    note: str = ""


class PersonBulkCreate(BaseModel):
    people: List[PersonCreate]


def _resolve_person(conn, user_id: int, name: str, note: str) -> Optional[int]:
    """Find or create a person by (name, note). Returns person_id or None."""
    if not name:
        return None
    person = conn.execute(
        "SELECT id FROM people WHERE user_id = ? AND name = ? AND note = ?",
        (user_id, name, note),
    ).fetchone()
    if person:
        return person["id"]
    # No note? Try matching by name only
    if not note:
        person = conn.execute(
            "SELECT id FROM people WHERE user_id = ? AND name = ? AND note = ?",
            (user_id, name, ""),
        ).fetchone()
        if person:
            return person["id"]
    return None


@router.get("/search")
def search_people(q: str = Query(..., min_length=1), request: Request = None):
    """Search people by name."""
    user = get_current_user(request)
    conn = get_connection()
    try:
        rows = conn.execute(
            "SELECT id, name, phone, address, note FROM people WHERE user_id = ? AND name LIKE ? LIMIT 20",
            (user["user_id"], f"%{q}%"),
        ).fetchall()
        return [dict(r) for r in rows]
    finally:
        conn.close()


@router.post("", status_code=201)
def create_person(person: PersonCreate, request: Request):
    """创建新人员（name+address为唯一键）"""
    user = get_current_user(request)
    conn = get_connection()
    try:
        # 检查是否已存在 name + address 的人员
        existing = conn.execute(
            "SELECT id FROM people WHERE user_id = ? AND name = ? AND address = ?",
            (user["user_id"], person.name, person.address)
        ).fetchone()

        if existing:
            return {"id": existing["id"], "message": "人员已存在", "exists": True}

        # 创建新人员
        cur = conn.execute(
            "INSERT INTO people (user_id, name, phone, address, note) VALUES (?, ?, ?, ?, ?)",
            (user["user_id"], person.name, person.phone, person.address, person.note)
        )
        conn.commit()
        return {"id": cur.lastrowid, "message": "人员创建成功", "exists": False}
    except Exception as e:
        conn.rollback()
        # 处理唯一约束冲突
        if "UNIQUE constraint failed" in str(e) or "unique" in str(e).lower():
            raise HTTPException(status_code=400, detail=f"人员 '{person.name}' 已存在相同地址的记录")
        raise HTTPException(status_code=400, detail=f"创建失败: {str(e)}")
    finally:
        conn.close()


@router.get("")
def list_people_summary(
    name: Optional[str] = Query(None),
    sort: str = Query("name"),
    request: Request = None,
):
    """获取人员列表"""
    user = get_current_user(request)
    user_id = user["user_id"]
    conn = get_connection()
    try:
        where = "p.user_id = ?"
        params = [user_id]
        if name:
            where += " AND p.name LIKE ?"
            params.append(f"%{name}%")

        sort_map = {"name": "p.name", "income": "total_income DESC", "expense": "total_expense DESC",
                     "balance": "balance DESC", "cnt": "cnt DESC"}
        order = sort_map.get(sort, "p.name")

        # 注意：参数顺序必须与 SQL 中 ? 的顺序一致
        # LEFT JOIN ... t.user_id = ?  -> user_id
        # WHERE p.user_id = ?          -> user_id
        # WHERE p.name LIKE ?          -> like_param (如果有)
        rows = conn.execute(f"""
            SELECT p.id, p.name, p.phone, p.address, p.note,
                   COALESCE(SUM(CASE WHEN t.direction='income' THEN t.amount ELSE 0 END), 0) as total_income,
                   COALESCE(SUM(CASE WHEN t.direction='expense' THEN t.amount ELSE 0 END), 0) as total_expense,
                   COALESCE(SUM(CASE WHEN t.direction='income' THEN t.amount ELSE -t.amount END), 0) as balance,
                   COUNT(t.id) as cnt
            FROM people p
            LEFT JOIN transactions t ON t.person_id = p.id AND t.user_id = ?
            WHERE {where}
            GROUP BY p.id
            ORDER BY {order}
        """, [user_id] + params).fetchall()

        return [dict(r) for r in rows]
    finally:
        conn.close()


class PersonUpdate(BaseModel):
    name: Optional[str] = None
    phone: Optional[str] = None
    address: Optional[str] = None
    note: Optional[str] = None


@router.get("/{person_id}")
def get_person(person_id: int, request: Request):
    """获取单个人员信息"""
    user = get_current_user(request)
    conn = get_connection()
    try:
        row = conn.execute(
            "SELECT id, name, phone, address, note FROM people WHERE id = ? AND user_id = ?",
            (person_id, user["user_id"])
        ).fetchone()
        if not row:
            raise HTTPException(status_code=404, detail="人员不存在")
        return dict(row)
    finally:
        conn.close()


@router.put("/{person_id}")
def update_person(person_id: int, person: PersonUpdate, request: Request):
    """更新人员信息"""
    user = get_current_user(request)
    conn = get_connection()
    try:
        # 检查人员是否存在且属于当前用户
        existing = conn.execute(
            "SELECT * FROM people WHERE id = ? AND user_id = ?",
            (person_id, user["user_id"])
        ).fetchone()
        if not existing:
            raise HTTPException(status_code=404, detail="人员不存在")

        # 构建更新语句
        updates = []
        params = []
        for field in ["name", "phone", "address", "note"]:
            value = getattr(person, field, None)
            if value is not None:
                updates.append(f"{field} = ?")
                params.append(value)

        if not updates:
            return {"message": "没有更新内容", "id": person_id}

        # 检查 name + address 是否与其他人员冲突
        new_name = person.name if person.name is not None else existing["name"]
        new_address = person.address if person.address is not None else existing["address"]
        conflict = conn.execute(
            "SELECT id FROM people WHERE user_id = ? AND name = ? AND address = ? AND id != ?",
            (user["user_id"], new_name, new_address, person_id)
        ).fetchone()
        if conflict:
            raise HTTPException(status_code=400, detail="已存在相同姓名和地址的人员")

        params.append(person_id)
        params.append(user["user_id"])
        conn.execute(
            f"UPDATE people SET {', '.join(updates)} WHERE id = ? AND user_id = ?",
            params
        )
        conn.commit()
        return {"message": "人员更新成功", "id": person_id}
    except HTTPException:
        raise
    except Exception as e:
        conn.rollback()
        raise HTTPException(status_code=400, detail=f"更新失败: {str(e)}")
    finally:
        conn.close()


@router.delete("/{person_id}")
def delete_person(person_id: int, request: Request):
    """删除人员（关联记录的 person_id 会被清除）"""
    user = get_current_user(request)
    conn = get_connection()
    try:
        # 检查人员是否存在且属于当前用户
        existing = conn.execute(
            "SELECT * FROM people WHERE id = ? AND user_id = ?",
            (person_id, user["user_id"])
        ).fetchone()
        if not existing:
            raise HTTPException(status_code=404, detail="人员不存在")

        # 清除关联记录的 person_id
        conn.execute(
            "UPDATE transactions SET person_id = NULL WHERE person_id = ? AND user_id = ?",
            (person_id, user["user_id"])
        )

        # 删除人员
        conn.execute(
            "DELETE FROM people WHERE id = ? AND user_id = ?",
            (person_id, user["user_id"])
        )
        conn.commit()
        return {"message": "人员删除成功"}
    except HTTPException:
        raise
    except Exception as e:
        conn.rollback()
        raise HTTPException(status_code=400, detail=f"删除失败: {str(e)}")
    finally:
        conn.close()
