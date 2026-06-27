"""Minimal MCP-over-HTTP endpoint for gift-money tools."""
from __future__ import annotations

import json
from typing import Any, Callable, Dict

from fastapi import APIRouter, Header, HTTPException, Request

from app.config import settings
from app.database import get_connection
from app.services.gift_query import (
    answer_gift_question,
    get_person_gift_summary,
    list_person_transactions,
    search_people,
)

router = APIRouter(prefix="/mcp", tags=["mcp"])


def _check_token(x_mcp_token: str = "") -> None:
    if settings.mcp_api_token and x_mcp_token != settings.mcp_api_token:
        raise HTTPException(status_code=401, detail="invalid MCP token")


def _jsonrpc_result(request_id: Any, result: Any) -> Dict[str, Any]:
    return {"jsonrpc": "2.0", "id": request_id, "result": result}


def _jsonrpc_error(request_id: Any, code: int, message: str) -> Dict[str, Any]:
    return {"jsonrpc": "2.0", "id": request_id, "error": {"code": code, "message": message}}


def _user_id(args: Dict[str, Any]) -> int:
    return int(args.get("user_id") or settings.wechat_default_user_id)


def _bound_user_id(channel: str, external_id: str) -> int | None:
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


def _call_search_people(args: Dict[str, Any]) -> Dict[str, Any]:
    return {"people": search_people(_user_id(args), str(args.get("name", "")), int(args.get("limit", 10)))}


def _call_person_summary(args: Dict[str, Any]) -> Dict[str, Any]:
    user_id = _user_id(args)
    person_id = int(args["person_id"])
    summary = get_person_gift_summary(user_id, person_id, int(args.get("detail_limit", 10)))
    return {"summary": summary}


def _call_person_transactions(args: Dict[str, Any]) -> Dict[str, Any]:
    user_id = _user_id(args)
    person_id = int(args["person_id"])
    limit = int(args.get("limit", 20))
    return {"transactions": list_person_transactions(user_id, person_id, limit)}


def _call_answer_question(args: Dict[str, Any]) -> Dict[str, Any]:
    return answer_gift_question(_user_id(args), str(args.get("text", "")))


def _call_answer_wechat_message(args: Dict[str, Any]) -> Dict[str, Any]:
    channel = str(args.get("channel") or "wechat")
    external_id = str(args.get("external_id") or "")
    if not external_id:
        return {
            "intent": "binding_required",
            "reply": "缺少微信用户标识 external_id，无法确认要查询哪个账本。",
        }

    user_id = _bound_user_id(channel, external_id)
    if user_id is None:
        return {
            "intent": "binding_required",
            "channel": channel,
            "external_id": external_id,
            "reply": "请先绑定礼金系统账号：登录网页后生成微信绑定码，然后在微信发送“绑定 绑定码”。",
        }
    return answer_gift_question(user_id, str(args.get("text", "")))


TOOLS: Dict[str, Dict[str, Any]] = {
    "search_people": {
        "description": "Search gift-money people by name and return aggregate totals for disambiguation.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "name": {"type": "string"},
                "user_id": {"type": "integer", "default": 1},
                "limit": {"type": "integer", "default": 10},
            },
            "required": ["name"],
        },
        "handler": _call_search_people,
    },
    "get_person_gift_summary": {
        "description": "Get one person's received gifts, sent gifts, balance, and recent records.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "person_id": {"type": "integer"},
                "user_id": {"type": "integer", "default": 1},
                "detail_limit": {"type": "integer", "default": 10},
            },
            "required": ["person_id"],
        },
        "handler": _call_person_summary,
    },
    "list_person_transactions": {
        "description": "List gift-money transactions for a person.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "person_id": {"type": "integer"},
                "user_id": {"type": "integer", "default": 1},
                "limit": {"type": "integer", "default": 20},
            },
            "required": ["person_id"],
        },
        "handler": _call_person_transactions,
    },
    "answer_gift_question": {
        "description": "Answer a Chinese natural-language gift-money question, such as 张三送了我多少礼金.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "text": {"type": "string"},
                "user_id": {"type": "integer", "default": 1},
            },
            "required": ["text"],
        },
        "handler": _call_answer_question,
    },
    "answer_wechat_message": {
        "description": "Answer a WeChat user's gift-money question by resolving channel/external_id to the bound system user.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "text": {"type": "string"},
                "external_id": {"type": "string"},
                "channel": {"type": "string", "default": "wechat"},
            },
            "required": ["text", "external_id"],
        },
        "handler": _call_answer_wechat_message,
    },
}


def _tool_descriptors():
    return [
        {
            "name": name,
            "description": tool["description"],
            "inputSchema": tool["inputSchema"],
        }
        for name, tool in TOOLS.items()
    ]


@router.post("")
async def handle_mcp(request: Request, x_mcp_token: str = Header("")):
    """Handle a small MCP JSON-RPC subset used by Lobster/agent callers."""
    _check_token(x_mcp_token)
    try:
        payload = await request.json()
    except json.JSONDecodeError:
        return _jsonrpc_error(None, -32700, "parse error")

    method = payload.get("method")
    request_id = payload.get("id")
    params = payload.get("params") or {}

    if method == "initialize":
        return _jsonrpc_result(
            request_id,
            {
                "protocolVersion": "2024-11-05",
                "capabilities": {"tools": {}},
                "serverInfo": {"name": "gift-money-mcp", "version": "0.1.0"},
            },
        )

    if method == "tools/list":
        return _jsonrpc_result(request_id, {"tools": _tool_descriptors()})

    if method == "tools/call":
        name = params.get("name")
        args = params.get("arguments") or {}
        tool = TOOLS.get(name)
        if not tool:
            return _jsonrpc_error(request_id, -32602, f"unknown tool: {name}")

        try:
            handler: Callable[[Dict[str, Any]], Any] = tool["handler"]
            data = handler(args)
        except KeyError as exc:
            return _jsonrpc_error(request_id, -32602, f"missing argument: {exc}")
        except Exception as exc:
            return _jsonrpc_error(request_id, -32000, str(exc))

        return _jsonrpc_result(
            request_id,
            {
                "content": [
                    {
                        "type": "text",
                        "text": data.get("reply") if isinstance(data, dict) and "reply" in data else str(data),
                    }
                ],
                "structuredContent": data,
            },
        )

    return _jsonrpc_error(request_id, -32601, f"method not found: {method}")
