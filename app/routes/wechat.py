"""WeChat callback integration for natural-language gift queries."""
from __future__ import annotations

import hashlib
import io
import re
import secrets
import time
import urllib.parse
import xml.etree.ElementTree as ET
from datetime import datetime, timedelta

import jwt
import qrcode
from fastapi import APIRouter, HTTPException, Query, Request
from fastapi.responses import HTMLResponse, JSONResponse, PlainTextResponse, Response
from pydantic import BaseModel

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


# ── 一键授权绑定 (snsapi_base, 免费拿 openid) ──
# 用户只需在网页点一次"绑定微信"，授权全程静默，无需输入、无需短信。


def _issue_bind_state(user_id: int) -> str:
    """签发一个短时 state 令牌，把一次 OAuth 回调绑定到网页登录用户。"""
    expire = datetime.utcnow() + timedelta(minutes=5)
    return jwt.encode(
        {"purpose": "wechat_bind", "user_id": user_id, "exp": expire},
        settings.jwt_secret,
        algorithm=settings.jwt_algorithm,
    )


def _resolve_bind_state(state: str) -> int | None:
    try:
        payload = jwt.decode(state, settings.jwt_secret, algorithms=[settings.jwt_algorithm])
        if payload.get("purpose") != "wechat_bind":
            return None
        return int(payload["user_id"])
    except (jwt.ExpiredSignatureError, jwt.InvalidTokenError, KeyError, TypeError, ValueError):
        return None


# ── 渠道一键绑定链接 (channel-agnostic) ──
# 未绑定用户收到的绑定链接用短码 ?c=CODE，避免长 JWT URL 在聊天客户端被截断，
# 也便于延长有效期。点开链接 → 网页登录/确认 → (channel, external_id) 绑定到账号。

_CHANNEL_BIND_TTL_MINUTES = 30


def _generate_channel_bind_code() -> str:
    alphabet = "ABCDEFGHJKLMNPQRSTUVWXYZ23456789"
    return "".join(secrets.choice(alphabet) for _ in range(8))


def _issue_channel_bind_code(channel: str, external_id: str) -> str:
    """生成并持久化一个短时绑定码，返回码本身（用于拼接 ?c=CODE 链接）。"""
    expires = (datetime.now() + timedelta(minutes=_CHANNEL_BIND_TTL_MINUTES)).strftime("%Y-%m-%d %H:%M:%S")
    conn = get_connection()
    try:
        for _ in range(5):
            code = _generate_channel_bind_code()
            try:
                conn.execute(
                    """
                    INSERT INTO channel_bind_codes (code, channel, external_id, status, expires_at)
                    VALUES (?, ?, ?, 'pending', ?)
                    """,
                    (code, channel, external_id, expires),
                )
                conn.commit()
                return code
            except Exception:
                conn.rollback()
                continue
        raise RuntimeError("failed to allocate channel bind code")
    finally:
        conn.close()


def _bind_channel_code(user_id: int, code: str) -> tuple[bool, str]:
    """原子地消费绑定码并绑定到 user_id。返回 (ok, 消息)。"""
    now = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    conn = get_connection()
    try:
        row = conn.execute(
            """
            SELECT id, channel, external_id FROM channel_bind_codes
            WHERE code = ? AND status = 'pending' AND expires_at >= ?
            """,
            (code, now),
        ).fetchone()
        if not row:
            return False, "绑定链接无效或已过期。请回到聊天里重新发送查询，点新的绑定链接。"
        conn.execute(
            """
            INSERT INTO wechat_accounts (user_id, channel, external_id)
            VALUES (?, ?, ?)
            ON CONFLICT(channel, external_id) DO UPDATE SET user_id = excluded.user_id
            """,
            (user_id, row["channel"], row["external_id"]),
        )
        conn.execute(
            "UPDATE channel_bind_codes SET status = 'used', used_at = ? WHERE id = ?",
            (now, row["id"]),
        )
        conn.commit()
        label = {"wechat": "微信", "feishu": "飞书"}.get(str(row["channel"]), row["channel"])
        return True, f"绑定成功：已把「{label}」账号绑定到当前礼金账号，回 {label} 里继续问就行。"
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()


def build_channel_bind_link(channel: str, external_id: str) -> str:
    """构造一键绑定链接：?c=短码，点开 → 网页登录/确认 → (channel, external_id) 绑定到账号。"""
    code = _issue_channel_bind_code(channel, external_id)
    return f"{settings.web_base_url.rstrip('/')}/bind?c={code}"


def _oauth_authorize_url(state: str) -> str:
    params = urllib.parse.urlencode({
        "appid": settings.wechat_app_id,
        "redirect_uri": settings.wechat_oauth_redirect_uri,
        "response_type": "code",
        "scope": "snsapi_base",
        "state": state,
    })
    return f"https://open.weixin.qq.com/connect/oauth2/authorize?{params}#wechat_redirect"


def _exchange_openid(code: str) -> str:
    """用授权 code 换 openid（测试号免费 snsapi_base 授权）。"""
    import urllib.request

    params = urllib.parse.urlencode({
        "appid": settings.wechat_app_id,
        "secret": settings.wechat_app_secret,
        "code": code,
        "grant_type": "authorization_code",
    })
    url = f"https://api.weixin.qq.com/sns/oauth2/access_token?{params}"
    with urllib.request.urlopen(url, timeout=10) as resp:
        data = resp.read().decode("utf-8")
    import json

    payload = json.loads(data)
    if "openid" not in payload:
        raise HTTPException(status_code=400, detail=f"微信授权失败: {payload.get('errmsg', data)}")
    return payload["openid"]


@router.get("/oauth/start")
def start_oauth(request: Request):
    """网页登录用户：返回微信一键绑定授权链接（静默 snsapi_base）。"""
    if not settings.wechat_app_id or not settings.wechat_app_secret or not settings.wechat_oauth_redirect_uri:
        raise HTTPException(status_code=503, detail="微信授权未配置，请联系管理员。")
    user = get_current_user(request)
    state = _issue_bind_state(user["user_id"])
    return {"url": _oauth_authorize_url(state)}


@router.get("/oauth/qr")
def oauth_qr(request: Request):
    """网页登录用户：返回绑定授权链接的二维码图片（PNG），供手机微信扫码。"""
    if not settings.wechat_app_id or not settings.wechat_app_secret or not settings.wechat_oauth_redirect_uri:
        raise HTTPException(status_code=503, detail="微信授权未配置，请联系管理员。")
    user = get_current_user(request)
    state = _issue_bind_state(user["user_id"])
    url = _oauth_authorize_url(state)
    img = qrcode.make(url)
    buf = io.BytesIO()
    img.save(buf, format="PNG")
    return Response(content=buf.getvalue(), media_type="image/png")


@router.get("/oauth/callback")
def oauth_callback(code: str = Query(""), state: str = Query("")):
    """微信授权回跳：换取 openid 并绑定到发起授权的网页用户。"""
    user_id = _resolve_bind_state(state)
    if user_id is None:
        return HTMLResponse(
            "<html><body style='font-family:sans-serif;text-align:center;padding-top:80px'>"
            "<h3>绑定链接无效或已过期</h3><p>请回到网页重新点击「绑定微信」。</p></body></html>",
            status_code=400,
        )
    if not code:
        return HTMLResponse(
            "<html><body style='font-family:sans-serif;text-align:center;padding-top:80px'>"
            "<h3>授权已取消</h3><p>未收到微信授权，可回到网页重试。</p></body></html>",
            status_code=400,
        )

    openid = _exchange_openid(code)

    conn = get_connection()
    try:
        conn.execute(
            """
            INSERT INTO wechat_accounts (user_id, channel, external_id)
            VALUES (?, 'wechat', ?)
            ON CONFLICT(channel, external_id) DO UPDATE SET user_id = excluded.user_id
            """,
            (user_id, openid),
        )
        conn.commit()
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()

    return HTMLResponse(
        "<!DOCTYPE html><html lang='zh'><head><meta charset='utf-8'>"
        "<meta name='viewport' content='width=device-width,initial-scale=1'>"
        "<title>绑定成功</title></head>"
        "<body style='margin:0;font-family:-apple-system,Segoe UI,sans-serif;background:#f5f6f8;color:#222;'>"
        "<div style='max-width:420px;margin:0 auto;padding:40px 24px;text-align:center;'>"
        "<div style='width:56px;height:56px;margin:0 auto 16px;border-radius:50%;background:#07c160;"
        "color:#fff;font-size:30px;line-height:56px;'>✓</div>"
        "<h2 style='margin:0 0 8px;font-size:22px;'>绑定成功</h2>"
        "<p style='margin:0 0 24px;color:#666;font-size:14px;line-height:1.7;'>"
        "账号已绑定微信。现在去测试号里发消息就能查询礼金了。</p>"
        "<div style='background:#fff;border-radius:12px;padding:20px;box-shadow:0 1px 4px rgba(0,0,0,.06);'>"
        "<div style='font-size:14px;font-weight:600;margin-bottom:12px;'>① 长按识别二维码，关注测试号</div>"
        f"<img src='https://open.weixin.qq.com/qr/code?username={settings.wechat_test_account}' "
        "alt='测试号二维码' style='width:200px;height:200px;border-radius:8px;object-fit:contain;'>"
        "<div style='font-size:13px;color:#666;margin-top:12px;line-height:1.7;'>"
        "② 关注后，到微信「订阅号消息」进入测试号对话<br>"
        "③ 发送：<strong>张三送了我多少礼金？</strong></div>"
        "</div></div></body></html>"
    )


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


class ChannelBindConfirm(BaseModel):
    code: str


@router.post("/bind-confirm")
def confirm_channel_bind(req: ChannelBindConfirm, request: Request):
    """网页端确认：把绑定码携带的 (channel, external_id) 绑定到当前登录用户。

    由一键绑定页 /bind 调用（Bearer 登录态）。绑定后即可在对应聊天渠道查询。
    """
    user = get_current_user(request)
    ok, message = _bind_channel_code(user["user_id"], req.code.strip().upper())
    if not ok:
        return JSONResponse({"ok": False, "error": message}, status_code=400)
    return {"ok": True, "reply": message}


# ── 一键绑定页（channel 通用，无 /api 前缀）──
page_router = APIRouter(tags=["bind"])


@page_router.get("/bind")
def bind_page(c: str = Query("")):
    """一键绑定页：网页登录/确认后，把聊天渠道身份绑定到当前礼金账号。"""
    if not c:
        return HTMLResponse(_bind_html("链接无效", "缺少绑定参数，请回聊天里重新发送查询并点击新的绑定链接。"))
    return HTMLResponse(_bind_html("账号绑定", ""))


_BIND_PAGE = """<!DOCTYPE html>
<html lang="zh"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>{title} · 礼金管家</title>
<style>
  body {{ margin:0;font-family:-apple-system,"Segoe UI","PingFang SC",sans-serif;background:#f2f4f7;color:#1f2329; }}
  .wrap {{ max-width:420px;margin:0 auto;padding:48px 20px; }}
  .card {{ background:#fff;border-radius:14px;padding:28px 22px;box-shadow:0 2px 10px rgba(0,0,0,.06);text-align:center; }}
  h1 {{ font-size:20px;margin:0 0 6px; }}
  .sub {{ color:#8a919f;font-size:13px;margin-bottom:22px; }}
  .status {{ font-size:16px;line-height:1.8;color:#4e5969;margin:14px 0 4px; }}
  .btn {{ display:block;width:100%;margin-top:18px;padding:12px 0;border:0;border-radius:10px;
         background:#3370ff;color:#fff;font-size:16px;font-weight:600;cursor:pointer; }}
  .btn:disabled {{ opacity:.5; }}
  .link {{ color:#3370ff;text-decoration:none; }}
  input {{ display:block;width:100%;box-sizing:border-box;margin:10px 0;padding:12px 14px;border:1px solid #e5e6eb;
         border-radius:10px;font-size:15px;background:#f7f8fa; }}
  .err {{ color:#f53f3f;font-size:13px;margin-top:10px;min-height:18px; }}
</style></head><body><div class="wrap"><div class="card">
<h1>礼金管家</h1>
<div class="sub">一键绑定 · 渠道身份关联</div>
<div id="box"><div class="status">正在处理…</div></div>
</div></div>
<script>
const C = (new URLSearchParams(location.search).get('c') || '').toUpperCase();
const box = document.getElementById('box');
function view(html) {{ box.innerHTML = html; }}
function headerHtml(channel) {{
  const label = {{wechat:'微信',feishu:'飞书'}}[channel] || channel;
  return '<div style="margin:8px 0 2px;font-size:14px;color:#4e5969;">将绑定渠道：<b>' + label + '</b></div>';
}}
function successHtml(reply) {{
  view('<div style="width:56px;height:56px;margin:6px auto 14px;border-radius:50%;background:#07c160;color:#fff;' +
      'font-size:30px;line-height:56px;">✓</div><div class="status" style="font-size:18px;font-weight:600;color:#07c160;">绑定成功</div>' +
      '<div class="status" style="font-size:14px;">' + (reply||'') + '</div>' +
      '<div class="status" style="font-size:13px;color:#8a919f;">现在回聊天里直接问礼金即可。</div>');
}}
function errorHtml(msg) {{
  view('<div style="width:56px;height:56px;margin:6px auto 14px;border-radius:50%;background:#f53f3f;color:#fff;' +
      'font-size:30px;line-height:56px;">!</div><div class="status">' + (msg||'操作失败，请重试') + '</div>' +
      '<div class="status" style="font-size:13px;color:#8a919f;">可回聊天里重新发送查询，生成新的绑定链接。</div>');
}}
function expiredHtml(msg) {{
  view('<div class="status" style="font-size:16px;font-weight:600;">' + (msg||'链接无效或已过期') + '</div>' +
      '<div class="status" style="font-size:14px;color:#8a919f;">回聊天里重新发送查询，点新的绑定链接即可。</div>');
}}
function doConfirm(token) {{
  return fetch('/api/wechat/bind-confirm', {{
    method:'POST',
    headers:{{'Content-Type':'application/json','Authorization':'Bearer '+token}},
    body: JSON.stringify({{code:C}}),
  }}).then(r => r.json().catch(()=>({{ok:false,error:'网络错误，请重试'}})))
    .then(d => {{
      if (d && d.ok) {{ successHtml(d.reply); }}
      else {{ errorHtml((d&&d.error)||'绑定失败，请重试'); }}
    }});
}}
function showConfirm(token) {{
  let name = '当前登录账号';
  try {{
    const u = JSON.parse(localStorage.getItem('gift_user') || '{{}}');
    name = u.display_name || u.username || name;
  }} catch (e) {{}}
  view('<div style="font-size:15px;line-height:1.7;color:#4e5969;">将把你在聊天里的身份绑定到礼金账号：' +
      '<b style="font-size:17px;">' + name + '</b></div>' +
      '<div style="font-size:12px;color:#8a919f;margin-top:6px;">绑定后，微信/飞书都能查询这个账号的礼金账本。</div>' +
      '<button class="btn" id="b">确认绑定</button>');
  document.getElementById('b').onclick = () => {{
    const btn = document.getElementById('b');
    btn.disabled = true; btn.textContent = '绑定中…';
    doConfirm(token);
  }};
}}
function showLogin() {{
  view('<div class="status" style="font-weight:600;">请登录礼金账号以完成绑定</div>' +
      '<input id="u" placeholder="用户名" autocomplete="username">' +
      '<input id="p" type="password" placeholder="密码" autocomplete="current-password">' +
      '<button class="btn" id="b">登录并绑定</button><div class="err" id="e"></div>' +
      '<div style="font-size:12px;color:#8a919f;margin-top:6px;">没有账号？可在 <a class="link" href="/">礼金网页</a> 注册</div>');
  document.getElementById('b').onclick = async () => {{
    const u = document.getElementById('u').value.trim();
    const p = document.getElementById('p').value;
    const e = document.getElementById('e');
    const btn = document.getElementById('b');
    btn.disabled = true; btn.textContent = '登录中…';
    try {{
      const res = await fetch('/api/auth/login', {{
        method:'POST', headers:{{'Content-Type':'application/json'}},
        body: JSON.stringify({{username:u,password:p}}),
      }});
      const data = await res.json();
      if (!res.ok || !data.token) {{
        e.textContent = (data.detail||'登录失败');
        btn.disabled=false; btn.textContent='登录并绑定'; return;
      }}
      localStorage.setItem('gift_token', data.token);
      localStorage.setItem('gift_user', JSON.stringify(data.user));
      btn.disabled = false; btn.textContent = '登录成功';
      showConfirm(data.token);
    }} catch (err) {{
      e.textContent = '网络错误，请重试';
      btn.disabled=false; btn.textContent='登录并绑定';
    }}
  }};
}}
(async () => {{
  if (!C) {{ expiredHtml('缺少绑定参数'); return; }}
  const token = localStorage.getItem('gift_token');
  if (token) {{ showConfirm(token); }}
  else {{ showLogin(); }}
}})();
</script></body></html>"""


def _bind_html(title: str, note: str) -> str:
    return _BIND_PAGE.format(title=title, note=note)


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
