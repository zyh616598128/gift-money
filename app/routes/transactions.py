"""Transaction routes: CRUD and batch operations."""
from fastapi import APIRouter, HTTPException, Query, Depends, Request
from pydantic import BaseModel, Field
from typing import Optional, List
from app.database import get_connection

router = APIRouter(prefix="/api/transactions", tags=["transactions"])


class TransactionCreate(BaseModel):
    name: str = Field(..., min_length=1, max_length=100)
    amount: float = Field(..., gt=0)
    category: str
    date: str
    direction: str
    note: str = ""
    person_id: Optional[int] = None


class TransactionUpdate(BaseModel):
    name: Optional[str] = None
    amount: Optional[float] = None
    category: Optional[str] = None
    date: Optional[str] = None
    direction: Optional[str] = None
    note: Optional[str] = None
    person_id: Optional[int] = None


class BatchDeleteRequest(BaseModel):
    ids: List[int]


def get_current_user(request: Request) -> dict:
    """获取当前登录用户信息，如果未登录则抛出异常"""
    auth_header = request.headers.get("Authorization")
    if not auth_header or not auth_header.startswith("Bearer "):
        raise HTTPException(status_code=401, detail="未登录")
    token = auth_header[7:]
    from app.database import verify_token
    user = verify_token(token)
    if not user:
        raise HTTPException(status_code=401, detail="登录已过期")
    return user


def _resolve_person(conn, user_id: int, name: str, address: str = "") -> Optional[int]:
    """Find a person by (name, address). Returns None if not found."""
    if not name:
        return None
    # 按姓名 + 地址查找
    person = conn.execute(
        "SELECT id FROM people WHERE user_id = ? AND name = ? AND address = ?",
        (user_id, name, address or ""),
    ).fetchone()
    if person:
        return person["id"]
    # 如果没有地址，尝试只按姓名查找（兼容旧数据）
    if not address:
        person = conn.execute(
            "SELECT id FROM people WHERE user_id = ? AND name = ? LIMIT 1",
            (user_id, name),
        ).fetchone()
        if person:
            return person["id"]
    return None


@router.post("", status_code=201)
def create_transaction(tx: TransactionCreate, request: Request):
    """创建交易记录"""
    user = get_current_user(request)
    conn = get_connection()
    try:
        # 如果前端传了 person_id，直接使用
        if tx.person_id:
            person_id = tx.person_id
        else:
            # 否则根据 name + note 查找
            person_id = _resolve_person(conn, user["user_id"], tx.name, tx.note)

        cur = conn.execute(
            """INSERT INTO transactions (user_id, name, amount, category, date, direction, note, person_id)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?)""",
            (user["user_id"], tx.name, tx.amount, tx.category, tx.date, tx.direction, tx.note, person_id),
        )
        conn.commit()
        return {"id": cur.lastrowid, "message": "记录创建成功", "person_id": person_id}
    finally:
        conn.close()


@router.post("/batch", status_code=201)
def create_transactions_batch(tx_list: List[dict], request: Request):
    """批量创建记录，自动处理人员关联"""
    user = get_current_user(request)
    if not tx_list:
        return {"count": 0, "message": "空列表，无记录需要创建"}

    conn = get_connection()
    inserted = 0
    errors = []
    try:
        for i, tx in enumerate(tx_list):
            try:
                person_id = _resolve_person(conn, user["user_id"], tx.get("name", ""), tx.get("note", ""))
                conn.execute(
                    """INSERT INTO transactions (user_id, name, amount, category, date, direction, note, person_id)
                       VALUES (?, ?, ?, ?, ?, ?, ?, ?)""",
                    (user["user_id"], tx.get("name", ""), tx.get("amount"), tx.get("category"),
                     tx.get("date"), tx.get("direction"), tx.get("note", ""), person_id),
                )
                inserted += 1
            except Exception as e:
                errors.append(f"第{i+1}行: {str(e)}")

        conn.commit()

        if errors and inserted == 0:
            raise HTTPException(status_code=400, detail=f"全部导入失败: {'; '.join(errors)}")

        return {
            "count": inserted,
            "skipped": len(tx_list) - inserted,
            "errors": errors[:10],
            "message": f"成功导入 {inserted}/{len(tx_list)} 条记录" + (f"\n错误: {'; '.join(errors[:3])}" if errors else ""),
        }
    except HTTPException:
        raise
    except Exception as e:
        conn.rollback()
        raise HTTPException(status_code=400, detail=f"导入失败: {str(e)}")
    finally:
        conn.close()


@router.get("")
def list_transactions(
    date_start: Optional[str] = Query(None),
    date_end: Optional[str] = Query(None),
    name: Optional[str] = Query(None),
    category: Optional[str] = Query(None),
    direction: Optional[str] = Query(None),
    person_id: Optional[int] = Query(None),
    sort: str = Query("date"),
    order: str = Query("desc"),
    page: int = Query(1, ge=1),
    size: int = Query(20, ge=1, le=100),
    request: Request = None,
):
    """查询交易记录列表"""
    user = get_current_user(request)
    conn = get_connection()
    try:
        where = ["t.user_id = ?"]
        params = [user["user_id"]]

        if date_start:
            where.append("t.date >= ?")
            params.append(date_start)
        if date_end:
            where.append("t.date <= ?")
            params.append(date_end)
        if name:
            where.append("t.name LIKE ?")
            params.append(f"%{name}%")
        if category:
            where.append("t.category = ?")
            params.append(category)
        if direction:
            where.append("t.direction = ?")
            params.append(direction)
        if person_id:
            where.append("t.person_id = ?")
            params.append(person_id)

        # 排序
        valid_sorts = {"date": "t.date", "amount": "t.amount", "name": "t.name", "id": "t.id"}
        sort_field = valid_sorts.get(sort, "t.date")
        order_dir = "DESC" if order.lower() == "desc" else "ASC"

        offset = (page - 1) * size
        count_sql = f"SELECT COUNT(*) FROM transactions t WHERE {' AND '.join(where)}"
        total = conn.execute(count_sql, params).fetchone()[0]

        # LEFT JOIN people 获取地址
        rows = conn.execute(
            f"""SELECT t.id, t.name, t.amount, t.category,
                       t.date, t.direction, t.note, t.person_id, t.created_at,
                       p.address as person_address
                FROM transactions t
                LEFT JOIN people p ON t.person_id = p.id
                WHERE {' AND '.join(where)}
                ORDER BY {sort_field} {order_dir}, t.id DESC
                LIMIT ? OFFSET ?""",
            params + [size, offset],
        ).fetchall()

        return {
            "data": [dict(r) for r in rows],
            "total": total,
            "page": page,
            "size": size,
        }
    finally:
        conn.close()


@router.get("/{tx_id}")
def get_transaction(tx_id: int, request: Request):
    """获取单条交易记录"""
    user = get_current_user(request)
    conn = get_connection()
    try:
        row = conn.execute(
            "SELECT * FROM transactions WHERE id = ? AND user_id = ?",
            (tx_id, user["user_id"]),
        ).fetchone()
        if not row:
            raise HTTPException(status_code=404, detail="记录不存在")
        return dict(row)
    finally:
        conn.close()


@router.put("/{tx_id}")
def update_transaction(tx_id: int, tx: TransactionUpdate, request: Request):
    """更新交易记录"""
    user = get_current_user(request)
    conn = get_connection()
    try:
        # 先检查记录是否存在且属于当前用户
        existing = conn.execute(
            "SELECT * FROM transactions WHERE id = ? AND user_id = ?",
            (tx_id, user["user_id"]),
        ).fetchone()
        if not existing:
            raise HTTPException(status_code=404, detail="记录不存在")

        updates = []
        params = []
        for field in ["name", "amount", "category", "date", "direction", "note"]:
            val = getattr(tx, field, None)
            if val is not None:
                updates.append(f"{field} = ?")
                params.append(val)

        if not updates and tx.person_id is None:
            raise HTTPException(status_code=400, detail="没有提供更新字段")

        # 处理 person_id
        if tx.person_id is not None:
            # 前端传了 person_id，直接使用
            updates.append("person_id = ?")
            params.append(tx.person_id)
        elif tx.name is not None:
            # 只更新了 name，尝试查找人员
            person_id = _resolve_person(conn, user["user_id"], tx.name)
            updates.append("person_id = ?")
            params.append(person_id)

        params.append(tx_id)
        params.append(user["user_id"])
        conn.execute(
            f"UPDATE transactions SET {', '.join(updates)} WHERE id = ? AND user_id = ?",
            params,
        )
        conn.commit()
        return {"message": "记录更新成功"}
    finally:
        conn.close()


@router.delete("/{tx_id}")
def delete_transaction(tx_id: int, request: Request):
    """删除交易记录"""
    user = get_current_user(request)
    conn = get_connection()
    try:
        result = conn.execute(
            "DELETE FROM transactions WHERE id = ? AND user_id = ?",
            (tx_id, user["user_id"]),
        )
        conn.commit()
        if result.rowcount == 0:
            raise HTTPException(status_code=404, detail="记录不存在")
        return {"message": "记录删除成功"}
    finally:
        conn.close()


@router.delete("/batch")
def delete_transactions_batch(req: BatchDeleteRequest, request: Request):
    """批量删除交易记录"""
    user = get_current_user(request)
    if not req.ids:
        return {"count": 0, "message": "空列表，无记录需要删除"}

    conn = get_connection()
    try:
        placeholders = ",".join("?" for _ in req.ids)
        # 添加用户权限检查
        params = list(req.ids) + [user["user_id"]]
        result = conn.execute(
            f"DELETE FROM transactions WHERE id IN ({placeholders}) AND user_id = ?",
            params,
        )
        conn.commit()
        return {"count": result.rowcount, "message": f"成功删除 {result.rowcount} 条记录"}
    finally:
        conn.close()
