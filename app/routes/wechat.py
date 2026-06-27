"""WeChat callback integration for natural-language gift queries."""
from __future__ import annotations

import hashlib
import re
import secrets
import time
import xml.etree.ElementTree as ET
from datetime import datetime, timedelta

from fastapi import APIRouter, HTTPException, Query, Request
from fastapi.responses import PlainTextResponse, Response

from app.config import settings
from app.database import get_connection
from app.routes.transactions import get_current_user
from app.services.gift_query import answer_gift_question

router = APIRouter(prefix="/api/wechat", tags=["wechat"])


def _verify_signature(signature: str, timestamp: str, nonce: str) -> bool:
    token = settings.wechat_token
    if not token:
        return True
    raw = "".join(sorted([token, timestamp or "", nonce or ""]))
    digest = hashlib.sha1(raw.encode("utf-8")).hexdigest()
    return digest == signature


def _xml_text(root: ET.Element, name: str, default: str = "") -> str:
    node = root.find(name)
    return node.text if node is not None and node.text is not None else default


def _cdata(value: str) -> str:
    return (value or "").replace("]]>", "]]]]><![CDATA[>")


def _text_reply(to_user: str, from_user: str, content: str) -> Response:
    body = (
        "<xml>"
        f"<ToUserName><![CDATA[{_cdata(to_user)}]]></ToUserName>"
        f"<FromUserName><![CDATA[{_cdata(from_user)}]]></FromUserName>"
        f"<CreateTime>{int(time.time())}</CreateTime>"
        "<MsgType><![CDATA[text]]></MsgType>"
        f"<Content><![CDATA[{_cdata(content)}]]></Content>"
        "</xml>"
    )
    return Response(content=body, media_type="application/xml")


def _get_user_id(channel: str, external_id: str) -> int | None:
    conn = get_connection()
    try:
        row = conn.execute(
            "SELECT user_id FROM wechat_accounts WHERE channel = ? AND external_id = ?",
            (channel, external_id),
        ).fetchone()
        if row:
            return int(row["user_id"])
    finally:
        conn.close()
    if settings.wechat_require_binding:
        return None
    return settings.wechat_default_user_id


def _generate_bind_code() -> str:
    alphabet = "ABCDEFGHJKLMNPQRSTUVWXYZ23456789"
    return "".join(secrets.choice(alphabet) for _ in range(6))


def _parse_bind_code(content: str) -> str | None:
    match = re.match(r"^\s*(?:绑定|bind)\s*[:：]?\s*([A-Za-z0-9]{4,12})\s*$", content or "", re.I)
    return match.group(1).upper() if match else None


def _bind_wechat_account(channel: str, external_id: str, code: str) -> str:
    now = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    conn = get_connection()
    try:
        row = conn.execute(
            """
            SELECT id, user_id FROM wechat_bind_codes
            WHERE code = ? AND status = 'pending' AND expires_at >= ?
            """,
            (code, now),
        ).fetchone()
        if not row:
            return "绑定码无效或已过期。请登录礼金系统网页重新生成绑定码。"

        conn.execute(
            """
            INSERT INTO wechat_accounts (user_id, channel, external_id)
            VALUES (?, ?, ?)
            ON CONFLICT(channel, external_id) DO UPDATE SET user_id = excluded.user_id
            """,
            (row["user_id"], channel, external_id),
        )
        conn.execute(
            "UPDATE wechat_bind_codes SET status = 'used', used_at = ? WHERE id = ?",
            (now, row["id"]),
        )
        conn.commit()
        return "绑定成功。以后你可以直接问：张三送了我多少礼金？"
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()


def _save_message(
    channel: str,
    external_id: str,
    message_id: str,
    content: str,
    intent: str,
    status: str,
    response: str,
) -> bool:
    """Save a message. Returns False when it was already processed."""
    if not message_id:
        message_id = f"{external_id}:{int(time.time() * 1000)}"

    conn = get_connection()
    try:
        conn.execute(
            """
            INSERT INTO chat_messages (channel, external_id, message_id, content, intent, status, response)
            VALUES (?, ?, ?, ?, ?, ?, ?)
            """,
            (channel, external_id, message_id, content, intent, status, response),
        )
        conn.commit()
        return True
    except Exception as exc:
        conn.rollback()
        if "UNIQUE" in str(exc).upper():
            return False
        raise
    finally:
        conn.close()


@router.get("/callback", response_class=PlainTextResponse)
def verify_callback(
    signature: str = Query(""),
    timestamp: str = Query(""),
    nonce: str = Query(""),
    echostr: str = Query(""),
):
    """Verify WeChat server callback configuration."""
    if not _verify_signature(signature, timestamp, nonce):
        raise HTTPException(status_code=403, detail="invalid wechat signature")
    return echostr


@router.post("/bind-code")
def create_bind_code(request: Request):
    """Create a short-lived bind code for the logged-in web user."""
    user = get_current_user(request)
    expires_at = (datetime.now() + timedelta(minutes=10)).strftime("%Y-%m-%d %H:%M:%S")
    conn = get_connection()
    try:
        conn.execute(
            """
            UPDATE wechat_bind_codes
            SET status = 'expired'
            WHERE user_id = ? AND status = 'pending'
            """,
            (user["user_id"],),
        )

        for _ in range(5):
            code = _generate_bind_code()
            try:
                conn.execute(
                    "INSERT INTO wechat_bind_codes (user_id, code, expires_at) VALUES (?, ?, ?)",
                    (user["user_id"], code, expires_at),
                )
                conn.commit()
                return {
                    "code": code,
                    "expires_at": expires_at,
                    "message": f"请在微信发送：绑定 {code}",
                }
            except Exception as exc:
                if "UNIQUE" not in str(exc).upper():
                    raise
        raise HTTPException(status_code=500, detail="生成绑定码失败，请重试")
    except HTTPException:
        raise
    except Exception as exc:
        conn.rollback()
        raise HTTPException(status_code=400, detail=f"生成绑定码失败: {exc}")
    finally:
        conn.close()


@router.get("/bindings")
def list_bindings(request: Request):
    """List WeChat accounts bound to the logged-in web user."""
    user = get_current_user(request)
    conn = get_connection()
    try:
        rows = conn.execute(
            """
            SELECT id, channel, external_id, nickname, created_at
            FROM wechat_accounts
            WHERE user_id = ?
            ORDER BY created_at DESC
            """,
            (user["user_id"],),
        ).fetchall()
        return {"data": [dict(row) for row in rows]}
    finally:
        conn.close()


@router.delete("/bindings/{binding_id}")
def delete_binding(binding_id: int, request: Request):
    """Unbind one WeChat account from the logged-in web user."""
    user = get_current_user(request)
    conn = get_connection()
    try:
        result = conn.execute(
            "DELETE FROM wechat_accounts WHERE id = ? AND user_id = ?",
            (binding_id, user["user_id"]),
        )
        conn.commit()
        if result.rowcount == 0:
            raise HTTPException(status_code=404, detail="绑定不存在")
        return {"message": "解绑成功"}
    finally:
        conn.close()


@router.post("/callback")
async def receive_message(
    request: Request,
    signature: str = Query(""),
    timestamp: str = Query(""),
    nonce: str = Query(""),
):
    """Receive WeChat text messages and reply with a gift-money answer."""
    if not _verify_signature(signature, timestamp, nonce):
        raise HTTPException(status_code=403, detail="invalid wechat signature")

    raw_body = await request.body()
    try:
        root = ET.fromstring(raw_body)
    except ET.ParseError:
        raise HTTPException(status_code=400, detail="invalid xml")

    to_user = _xml_text(root, "ToUserName")
    from_user = _xml_text(root, "FromUserName")
    msg_type = _xml_text(root, "MsgType")
    msg_id = _xml_text(root, "MsgId") or _xml_text(root, "MsgID")

    if msg_type != "text":
        reply = "目前先支持文字查询。你可以发：张三送了我多少礼金？"
        _save_message("wechat", from_user, msg_id, "", "unsupported_message", "ignored", reply)
        return _text_reply(from_user, to_user, reply)

    content = _xml_text(root, "Content").strip()
    bind_code = _parse_bind_code(content)
    if bind_code:
        reply = _bind_wechat_account("wechat", from_user, bind_code)
        _save_message("wechat", from_user, msg_id, content, "bind_account", "replied", reply)
        return _text_reply(from_user, to_user, reply)

    user_id = _get_user_id("wechat", from_user)
    if user_id is None:
        reply = "请先绑定礼金系统账号：登录网页后生成微信绑定码，然后在这里发送“绑定 绑定码”。"
        _save_message("wechat", from_user, msg_id, content, "binding_required", "replied", reply)
        return _text_reply(from_user, to_user, reply)

    answer = answer_gift_question(user_id, content)
    reply = answer["reply"]

    inserted = _save_message(
        "wechat",
        from_user,
        msg_id,
        content,
        answer.get("intent", ""),
        "replied",
        reply,
    )
    if not inserted:
        return PlainTextResponse("success")

    return _text_reply(from_user, to_user, reply)
