"""Standard MCP server exposing gift-money query tools.

Uses the official MCP Python SDK (``mcp``) so the tool list, input schemas,
error codes, and lifecycle follow the protocol natively instead of a hand-rolled
JSON-RPC subset. Mounted as a Streamable HTTP transport at ``/mcp`` on the
existing FastAPI application, with ``x-mcp-token`` bearer-style auth preserved.
"""
from __future__ import annotations

from typing import Dict, Optional

from mcp.server.mcpserver import MCPServer
from starlette.middleware.base import BaseHTTPMiddleware, RequestResponseEndpoint
from starlette.requests import Request
from starlette.responses import JSONResponse, Response

from app.config import settings
from app.database import get_connection
from app.services import gift_query as gift

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
mcp_app = mcp.streamable_http_app(streamable_http_path="/")
mcp_app.add_middleware(BaseHTTPMiddleware, dispatch=_check_token)


def get_mcp_app():
    """Return the mounted Starlette MCP application for FastAPI inclusion."""
    return mcp_app