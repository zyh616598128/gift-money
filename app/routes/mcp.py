"""Standard MCP server exposing gift-money query tools.

Uses the official MCP Python SDK (``mcp``) so the tool list, input schemas,
error codes, and lifecycle follow the protocol natively instead of a hand-rolled
JSON-RPC subset. Mounted as a Streamable HTTP transport at ``/mcp`` on the
existing FastAPI application, with ``x-mcp-token`` bearer-style auth preserved.
"""
from __future__ import annotations

import json
from typing import Dict, Optional

from mcp.server.mcpserver import MCPServer
from starlette.middleware.base import BaseHTTPMiddleware, RequestResponseEndpoint
from starlette.requests import Request
from starlette.responses import JSONResponse, Response

from app.config import settings
from app.database import get_connection
from app.services import gift_query as gift
from app.services.validators import date_error, normalize_date

mcp = MCPServer("gift-money-mcp")


# --------------------------------------------------------------------------- #
# Tool helpers
# --------------------------------------------------------------------------- #
def _user_id(user_id: Optional[int]) -> int:
    return int(user_id) if user_id is not None else settings.wechat_default_user_id


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


def _summary_reply(person_name: str, detail: Optional[Dict]) -> str:
    """Render a concise human-readable summary for a person's ledger."""
    if not detail:
        return f"{person_name}：暂无礼金记录。"
    stats = detail.get("summary") or {}
    info = detail.get("person") or {}
    address = f"（{info.get('address')}）" if info.get("address") else ""
    lines = [
        f"{info.get('name') or person_name}{address}",
        f"收礼：{_money(stats.get('total_income', 0))} 元，{stats.get('income_count', 0)} 笔",
        f"送礼：{_money(stats.get('total_expense', 0))} 元，{stats.get('expense_count', 0)} 笔",
        f"净额：{_money(stats.get('balance', 0))} 元",
    ]
    transactions = detail.get("transactions") or []
    if transactions:
        lines.append("明细：")
        for tx in transactions:
            direction = "收" if tx.get("direction") == "income" else "送"
            note = f"（{tx.get('note')}）" if tx.get("note") else ""
            lines.append(f"{tx.get('date')} {direction}{_money(tx.get('amount', 0))} {tx.get('category')}{note}")
    return "\n".join(lines)


def _money(value: object) -> str:
    try:
        return f"{float(value):.2f}"
    except (TypeError, ValueError):
        return "0.00"


# --------------------------------------------------------------------------- #
# Tools
# --------------------------------------------------------------------------- #
@mcp.tool()
def search_people(name: str, user_id: Optional[int] = None, limit: int = 10) -> Dict:
    """Search gift-money people by name and return aggregate totals for disambiguation."""
    return {"people": gift.search_people(_user_id(user_id), name, limit)}


@mcp.tool()
def get_person_gift_summary(
    person_id: int, user_id: Optional[int] = None, detail_limit: int = 10
) -> Dict:
    """Get one person's received gifts, sent gifts, balance, and recent records."""
    return {
        "summary": gift.get_person_gift_summary(_user_id(user_id), person_id, detail_limit)
    }


@mcp.tool()
def list_person_transactions(
    person_id: int, user_id: Optional[int] = None, limit: int = 20
) -> Dict:
    """List gift-money transactions for a person."""
    return {"transactions": gift.list_person_transactions(_user_id(user_id), person_id, limit)}


@mcp.tool()
def query_wechat_gift(
    name: str,
    external_id: str,
    channel: str = "wechat",
    detail_limit: int = 10,
) -> Dict:
    """Query a person's gift-money ledger for a WeChat user.

    ``name`` is the exact person name (e.g. 张三); the model extracts it from the
    user's message. ``external_id`` is the channel-side sender id (WeChat openid)
    used to resolve the bound ledger. Returns the person's summary and recent
    records, or a structured not-found/binding-required result.
    """
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

    people = gift.search_people(user_id, name, limit=10)
    if not people:
        return {
            "intent": "person_not_found",
            "name": name,
            "reply": f"没有找到“{name}”的人员记录。可以先在系统里添加人员，或换个名字再查。",
        }

    person = people[0]
    detail = gift.get_person_gift_summary(user_id, person["id"], detail_limit)
    return {
        "intent": "person_summary" if detail else "person_found",
        "name": person["name"],
        "person": detail["person"] if detail else person,
        "summary": detail["summary"] if detail else None,
        "transactions": detail["transactions"] if detail else [],
        "candidates": people if len(people) > 1 else None,
        "reply": _summary_reply(person["name"], detail),
    }


@mcp.tool()
def answer_gift_question(text: str, user_id: Optional[int] = None) -> Dict:
    """Answer a Chinese natural-language gift-money question, such as 张三送了我多少礼金."""
    return gift.answer_gift_question(_user_id(user_id), text)


@mcp.tool()
def answer_wechat_message(text: str, external_id: str, channel: str = "wechat") -> Dict:
    """Answer a WeChat user's gift-money question by resolving channel/external_id to the bound system user."""
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
    return gift.answer_gift_question(user_id, text)


def _require_bound(channel: str, external_id: str) -> tuple[int | None, Dict]:
    """Resolve channel/external_id to the bound system user; returns (user_id, error_result)."""
    if not external_id:
        return None, {
            "ok": False,
            "intent": "binding_required",
            "reply": "缺少微信用户标识 external_id，无法确认要操作哪个账本。",
        }
    user_id = _bound_user_id(channel, external_id)
    if user_id is None:
        return None, {
            "ok": False,
            "intent": "binding_required",
            "channel": channel,
            "external_id": external_id,
            "reply": "请先绑定礼金系统账号：登录网页后生成微信绑定码，然后在微信发送“绑定 绑定码”。",
        }
    return user_id, {}


@mcp.tool()
def record_gift_transaction(
    external_id: str,
    name: str,
    amount: float,
    direction: str,
    category: str,
    date: str,
    note: str = "",
    channel: str = "wechat",
) -> Dict:
    """Record one gift-money transaction for a WeChat user's own ledger.

    ``external_id`` is the channel-side sender id (WeChat openid) that resolves
    to the bound ledger owner. ``name`` is the person name (e.g. 张三),
    ``direction`` is 'income' (我收了/对方随礼给我) or 'expense' (我送出/回礼),
    ``amount`` > 0, ``category`` is an event type (e.g. 满月酒, 婚礼随礼),
    ``date`` is YYYY-MM-DD. The person is auto-linked or created. Returns the
    new transaction id and a human reply. This writes the owner's OWN ledger —
    the subject is the caller, authorized by the deployed slice, no approval step.
    """
    user_id, err = _require_bound(channel, external_id)
    if err:
        return err
    normalized = normalize_date(date)
    if normalized is None:
        return {"ok": False, "intent": "invalid_date", "error": date_error(date)}
    result = gift.create_transaction(user_id, name, amount, direction, category, normalized, note)
    if not result.get("ok"):
        return {"ok": False, "error": result.get("error")}
    direction_word = "收到" if direction == "income" else "送出"
    return {
        "ok": True,
        "intent": "transaction_recorded",
        "id": result["id"],
        "person_id": result["person_id"],
        "person_name": result["person_name"],
        "amount": amount,
        "direction": direction,
        "category": category,
        "date": normalized,
        "reply": f"已记下：{normalized} {direction_word} {name} {amount:g} 元（{category}）"
        + (f"，备注：{note}" if note else ""),
    }


@mcp.tool()
def update_gift_transaction(
    external_id: str,
    tx_id: int,
    name: str = "",
    amount: float | None = None,
    direction: str = "",
    category: str = "",
    date: str = "",
    note: str = "",
    channel: str = "wechat",
) -> Dict:
    """Update fields of one of the WeChat user's own gift transactions.

    ``external_id`` resolves the ledger owner; ``tx_id`` is the transaction id
    returned when it was recorded. Only non-empty fields are updated. Returns
    ok/reply. Writes the owner's own ledger, no approval step.
    """
    user_id, err = _require_bound(channel, external_id)
    if err:
        return err
    fields: Dict = {}
    if name:
        fields["name"] = name
    if amount is not None:
        fields["amount"] = amount
    if direction:
        fields["direction"] = direction
    if category:
        fields["category"] = category
    if date:
        normalized = normalize_date(date)
        if normalized is None:
            return {"ok": False, "intent": "invalid_date", "error": date_error(date)}
        fields["date"] = normalized
    if note:
        fields["note"] = note
    result = gift.update_transaction(user_id, tx_id, fields)
    if not result.get("ok"):
        return {"ok": False, "error": result.get("error")}
    return {"ok": True, "intent": "transaction_updated", "id": tx_id, "reply": f"记录 {tx_id} 已更新。"}


@mcp.tool()
def delete_gift_transaction(
    external_id: str, tx_id: int, channel: str = "wechat"
) -> Dict:
    """Delete one of the WeChat user's own gift transactions by id."""
    user_id, err = _require_bound(channel, external_id)
    if err:
        return err
    result = gift.delete_transaction(user_id, tx_id)
    if not result.get("ok"):
        return {"ok": False, "error": result.get("error")}
    return {"ok": True, "intent": "transaction_deleted", "id": tx_id, "reply": f"记录 {tx_id} 已删除。"}


@mcp.tool()
def create_gift_person(
    external_id: str,
    name: str,
    phone: str = "",
    address: str = "",
    note: str = "",
    channel: str = "wechat",
) -> Dict:
    """Create a person in the WeChat user's own ledger (e.g. when a query says person not found)."""
    user_id, err = _require_bound(channel, external_id)
    if err:
        return err
    result = gift.create_person(user_id, name, phone, address, note)
    if not result.get("ok"):
        return {"ok": False, "exists": result.get("exists", False), "id": result.get("id"), "error": result.get("error")}
    return {"ok": True, "id": result["id"], "reply": f"已添加人员“{name}”。"}


@mcp.tool()
def update_gift_person(
    external_id: str,
    person_id: int,
    name: str = "",
    phone: str = "",
    address: str = "",
    note: str = "",
    channel: str = "wechat",
) -> Dict:
    """Update fields of one person in the WeChat user's own ledger."""
    user_id, err = _require_bound(channel, external_id)
    if err:
        return err
    fields: Dict = {}
    if name:
        fields["name"] = name
    if phone:
        fields["phone"] = phone
    if address:
        fields["address"] = address
    if note:
        fields["note"] = note
    result = gift.update_person(user_id, person_id, fields)
    if not result.get("ok"):
        return {"ok": False, "error": result.get("error")}
    return {"ok": True, "intent": "person_updated", "id": person_id, "reply": f"人员 {person_id} 已更新。"}


@mcp.tool()
def get_ledger_summary(external_id: str, channel: str = "wechat") -> Dict:
    """Global gift ledger summary for the WeChat user: totals, monthly trend,
    category breakdown, and top people by balance."""
    user_id, err = _require_bound(channel, external_id)
    if err:
        return err
    summary = gift.ledger_summary(user_id)
    reply_lines = [
        f"总收礼：{_money(summary['total_income'])} 元（{summary['income_count']} 笔）",
        f"总送出：{_money(summary['total_expense'])} 元（{summary['expense_count']} 笔）",
        f"净结余：{_money(summary['balance'])} 元",
    ]
    if summary["monthly"]:
        latest = summary["monthly"][0]
        reply_lines.append(
            f"最近月份 {latest['month']}：收 {_money(latest['income'])} / 送 {_money(latest['expense'])}"
        )
    if summary["top_people"]:
        top = summary["top_people"][0]
        reply_lines.append(
            f"往来最多：{top['name']}，收 {_money(top['total_income'])} / 送 {_money(top['total_expense'])}"
        )
    return {"ok": True, "intent": "ledger_summary", "summary": summary, "reply": "\n".join(reply_lines)}


@mcp.tool()
def list_gift_categories(external_id: str, channel: str = "wechat") -> Dict:
    """List the WeChat user's gift categories (event types)."""
    user_id, err = _require_bound(channel, external_id)
    if err:
        return err
    categories = gift.list_categories(user_id)
    names = [cat["name"] for cat in categories]
    return {
        "ok": True,
        "categories": categories,
        "reply": f"现有分类：{'、'.join(names)}" if names else "还没有分类，可以直接用如“满月酒”“婚礼随礼”等分类记账。",
    }


@mcp.tool()
def create_gift_category(
    external_id: str, name: str, channel: str = "wechat"
) -> Dict:
    """Create a gift category (event type) in the WeChat user's own ledger."""
    user_id, err = _require_bound(channel, external_id)
    if err:
        return err
    result = gift.create_category(user_id, name)
    if not result.get("ok"):
        return {"ok": False, "exists": result.get("exists", False), "id": result.get("id"), "error": result.get("error")}
    return {"ok": True, "id": result["id"], "reply": f"已添加分类“{name}”。"}


# --------------------------------------------------------------------------- #
# HTTP auth + Starlette app
# --------------------------------------------------------------------------- #
async def _check_token(request: Request, call_next: RequestResponseEndpoint) -> Response:
    if settings.mcp_api_token and request.headers.get("x-mcp-token") != settings.mcp_api_token:
        return JSONResponse(
            {"jsonrpc": "2.0", "id": None, "error": {"code": -32000, "message": "unauthorized"}},
            status_code=401,
        )
    return await call_next(request)


# The Streamable HTTP transport is mounted at /mcp on the FastAPI application.
# streamable_http_path="/" keeps the endpoint at the mount root so the full
# path is /mcp (FastAPI strips the mount prefix before dispatching to the sub-app).
# host="0.0.0.0" disables the SDK's Host-header allowlist so proxied requests
# (Nginx -> uvicorn) with a public Host header are not rejected with 421.
mcp_app = mcp.streamable_http_app(streamable_http_path="/", host="0.0.0.0")
mcp_app.add_middleware(BaseHTTPMiddleware, dispatch=_check_token)


def get_mcp_app():
    """Return the mounted Starlette MCP application for FastAPI inclusion."""
    return mcp_app


# --------------------------------------------------------------------------- #
# Sessionless JSON-RPC binding (legacy MCP-over-HTTP)
# --------------------------------------------------------------------------- #
# The interop-fabric's `json-rpc` transport (legacy 2024-era MCP binding) is a
# stateless plain-JSON-RPC POST with no SSE stream and no mcp-session-id. This
# handler reuses the SAME MCPServer tool registry (`mcp`/`_tool_manager`) so the
# tool list and call behavior stay identical to the Streamable HTTP binding —
# no business-logic or tool-declaration duplication.
_LEGACY_PROTOCOL_VERSION = "2024-11-05"


def _jsonrpc_error(msg_id, code: int, message: str) -> dict:
    return {"jsonrpc": "2.0", "id": msg_id, "error": {"code": code, "message": message}}


def _tool_list_payload() -> list[dict]:
    return [
        {
            "name": tool.name,
            "description": tool.description,
            "inputSchema": tool.parameters,
        }
        for tool in mcp._tool_manager.list_tools()
    ]


async def handle_jsonrpc_message(message: dict) -> dict | None:
    """Dispatch one JSON-RPC message. Returns None for notifications (id=None)."""
    method = message.get("method")
    msg_id = message.get("id")

    if method == "initialize":
        return {
            "jsonrpc": "2.0",
            "id": msg_id,
            "result": {
                "protocolVersion": _LEGACY_PROTOCOL_VERSION,
                "capabilities": {"elicitation": {}, "sampling": {}, "roots": {}, "tools": {}},
                "serverInfo": {"name": "gift-money-mcp", "version": "0.1.0"},
            },
        }

    # Notifications (no id) require no response.
    if msg_id is None:
        return None

    if method == "ping":
        return {"jsonrpc": "2.0", "id": msg_id, "result": {}}

    if method == "tools/list":
        return {"jsonrpc": "2.0", "id": msg_id, "result": {"tools": _tool_list_payload()}}

    if method == "tools/call":
        params = message.get("params") or {}
        name = params.get("name")
        arguments = params.get("arguments") or {}
        try:
            # Drive the same MCPServer tool registry, but build a clean 2025/2026
            # compliant CallToolResult payload ourselves (the SDK's convert_result
            # emits `annotations: null` which the fabric's 2026 client rejects).
            raw = await mcp._tool_manager.call_tool(name, arguments, None, convert_result=False)
            if isinstance(raw, str):
                text: str = raw
            else:
                text = json.dumps(raw, ensure_ascii=False)
            payload = {
                "content": [{"type": "text", "text": text}],
                "structuredContent": raw if isinstance(raw, dict) else None,
            }
            return {"jsonrpc": "2.0", "id": msg_id, "result": payload}
        except Exception as exc:  # noqa: BLE001 - surface as JSON-RPC error
            return _jsonrpc_error(msg_id, -32602, f"Tool call failed: {exc}")

    return _jsonrpc_error(msg_id, -32601, f"Method not found: {method}")


async def json_rpc_endpoint(request: Request) -> Response:
    """Sessionless MCP-over-HTTP endpoint (legacy JSON-RPC, no SSE)."""
    if request.method != "POST":
        return JSONResponse({"message": "Method Not Allowed"}, status_code=405)
    # Same x-mcp-token auth as the Streamable HTTP binding (no-op when unset).
    if settings.mcp_api_token and request.headers.get("x-mcp-token") != settings.mcp_api_token:
        return JSONResponse(
            {"jsonrpc": "2.0", "id": None, "error": {"code": -32000, "message": "unauthorized"}},
            status_code=401,
        )
    try:
        body = await request.json()
    except Exception:  # noqa: BLE001
        return JSONResponse(_jsonrpc_error(None, -32700, "Parse error"), status_code=400)
    if not isinstance(body, dict):
        return JSONResponse(_jsonrpc_error(None, -32700, "Parse error: expected object"), status_code=400)
    response = await handle_jsonrpc_message(body)
    if response is None:
        return JSONResponse(content=None, status_code=202)
    return JSONResponse(response)