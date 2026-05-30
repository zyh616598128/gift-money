"""Category routes."""
from fastapi import APIRouter, HTTPException, Query, Depends, Request
from pydantic import BaseModel, Field
from typing import Optional
from app.database import get_connection
from app.routes.transactions import get_current_user

router = APIRouter(prefix="/api/categories", tags=["categories"])


class CategoryCreate(BaseModel):
    name: str = Field(..., min_length=1, max_length=50)
    color: str = Field("#6366f1")


@router.get("")
def list_categories(request: Request):
    """获取分类列表"""
    user = get_current_user(request)
    conn = get_connection()
    try:
        rows = conn.execute(
            "SELECT id, name, color FROM categories WHERE user_id = ? ORDER BY name",
            (user["user_id"],),
        ).fetchall()
        return [dict(r) for r in rows]
    finally:
        conn.close()


@router.post("", status_code=201)
def create_category(cat: CategoryCreate, request: Request):
    """创建分类"""
    user = get_current_user(request)
    conn = get_connection()
    try:
        # 检查是否已存在同名分类
        existing = conn.execute(
            "SELECT id FROM categories WHERE user_id = ? AND name = ?",
            (user["user_id"], cat.name)
        ).fetchone()
        if existing:
            raise HTTPException(status_code=400, detail=f"分类 '{cat.name}' 已存在")

        cur = conn.execute(
            "INSERT INTO categories (user_id, name, color) VALUES (?, ?, ?)",
            (user["user_id"], cat.name, cat.color),
        )
        conn.commit()
        return {"id": cur.lastrowid, "message": "分类创建成功"}
    finally:
        conn.close()


@router.delete("/{cat_id}")
def delete_category(cat_id: int, request: Request):
    """删除分类"""
    user = get_current_user(request)
    conn = get_connection()
    try:
        result = conn.execute(
            "DELETE FROM categories WHERE id = ? AND user_id = ?",
            (cat_id, user["user_id"]),
        )
        conn.commit()
        if result.rowcount == 0:
            raise HTTPException(status_code=404, detail="分类不存在")
        return {"message": "分类删除成功"}
    finally:
        conn.close()
