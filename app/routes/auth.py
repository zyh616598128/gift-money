"""Authentication routes."""
from fastapi import APIRouter, HTTPException, Depends, Request
from pydantic import BaseModel, Field, validator
from typing import Optional
from app.database import get_connection, create_token, verify_token
from app.password_policy import validate_password, hash_password, verify_password

router = APIRouter(prefix="/api/auth", tags=["auth"])


class LoginRequest(BaseModel):
    username: str
    password: str


class RegisterRequest(BaseModel):
    username: str
    password: str
    display_name: str = ""


class PasswordChange(BaseModel):
    old_password: str
    new_password: str


def _get_current_user(request: Request):
    auth_header = request.headers.get("Authorization")
    if not auth_header or not auth_header.startswith("Bearer "):
        raise HTTPException(status_code=401, detail="未登录")
    token = auth_header[7:]
    user = verify_token(token)
    if not user:
        raise HTTPException(status_code=401, detail="登录已过期")
    return user


@router.post("/login")
def login(req: LoginRequest):
    conn = get_connection()
    try:
        user = conn.execute(
            "SELECT id, username, password_hash, is_admin, display_name FROM users WHERE username = ?",
            (req.username,),
        ).fetchone()
        if not user:
            raise HTTPException(status_code=401, detail="用户名或密码错误")

        if not verify_password(req.password, user["password_hash"]):
            raise HTTPException(status_code=401, detail="用户名或密码错误")

        token = create_token(user["id"], user["username"], user["is_admin"])
        return {
            "token": token,
            "user": {
                "id": user["id"],
                "username": user["username"],
                "display_name": user["display_name"] or user["username"],
                "is_admin": bool(user["is_admin"]),
            },
        }
    finally:
        conn.close()


@router.post("/register", status_code=201)
def register(req: RegisterRequest):
    # 密码强度验证
    is_valid, error_msg = validate_password(req.password)
    if not is_valid:
        raise HTTPException(status_code=400, detail=error_msg)

    conn = get_connection()
    try:
        existing = conn.execute(
            "SELECT id FROM users WHERE username = ?",
            (req.username,),
        ).fetchone()
        if existing:
            raise HTTPException(status_code=400, detail="用户名已存在")

        password_hash = hash_password(req.password)
        conn.execute(
            "INSERT INTO users (username, password_hash, display_name, is_admin) VALUES (?, ?, ?, ?)",
            (req.username, password_hash, req.display_name, 0),
        )
        conn.commit()
        return {"message": "注册成功"}
    finally:
        conn.close()


@router.get("/me")
def get_me(user: dict = Depends(_get_current_user)):
    """获取当前用户信息（从数据库查询最新数据）"""
    conn = get_connection()
    try:
        db_user = conn.execute(
            "SELECT id, username, display_name, is_admin FROM users WHERE id = ?",
            (user["user_id"],)
        ).fetchone()
        if not db_user:
            raise HTTPException(status_code=404, detail="用户不存在")
        return {
            "id": db_user["id"],
            "username": db_user["username"],
            "display_name": db_user["display_name"] or db_user["username"],
            "is_admin": bool(db_user["is_admin"]),
        }
    finally:
        conn.close()


@router.put("/password")
def change_password(req: PasswordChange, user: dict = Depends(_get_current_user)):
    # 验证新密码强度
    is_valid, error_msg = validate_password(req.new_password)
    if not is_valid:
        raise HTTPException(status_code=400, detail=error_msg)

    conn = get_connection()
    try:
        db_user = conn.execute(
            "SELECT password_hash FROM users WHERE id = ?",
            (user["user_id"],),
        ).fetchone()
        if not db_user:
            raise HTTPException(status_code=404, detail="用户不存在")

        if not verify_password(req.old_password, db_user["password_hash"]):
            raise HTTPException(status_code=400, detail="原密码错误")

        new_hash = hash_password(req.new_password)
        conn.execute(
            "UPDATE users SET password_hash = ? WHERE id = ?",
            (new_hash, user["user_id"]),
        )
        conn.commit()
        return {"message": "密码修改成功"}
    finally:
        conn.close()
