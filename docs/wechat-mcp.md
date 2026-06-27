# 微信 + 龙虾 + MCP 接入说明

## 目标

让用户在微信里直接问礼金账本，不必打开网页或 Excel。

第一版已实现查询闭环：

- 微信文本消息回调：`/api/wechat/callback`
- MCP JSON-RPC 入口：`/mcp`
- 自然语言查询工具：`answer_gift_question`
- 人员搜索、人员礼金汇总、人员明细工具

## 微信后台配置

服务器地址：

```text
https://你的域名/api/wechat/callback
```

Token：

```text
GIFT_MONEY_WECHAT_TOKEN
```

EncodingAESKey 第一版可先用明文模式；如果后续开启安全模式，需要增加 AES 解密。

## 环境变量

```bash
GIFT_MONEY_WECHAT_TOKEN=微信后台配置的Token
GIFT_MONEY_WECHAT_DEFAULT_USER_ID=1
GIFT_MONEY_MCP_API_TOKEN=给龙虾调用MCP用的令牌
```

多用户正式模式应设置：

```bash
GIFT_MONEY_WECHAT_REQUIRE_BINDING=true
```

这样没有绑定的微信 openid 不能查询任何账本，只会收到绑定提示。

## 用户绑定流程

1. 用户登录礼金系统网页。
2. 调用：

```http
POST /api/wechat/bind-code
Authorization: Bearer <登录 token>
```

3. 服务返回：

```json
{
  "code": "A8K3P2",
  "expires_at": "2026-06-28 12:00:00",
  "message": "请在微信发送：绑定 A8K3P2"
}
```

4. 用户在微信里发送：

```text
绑定 A8K3P2
```

5. 服务器把微信 `openid` 绑定到当前系统用户，以后该微信用户只会查询自己的账本。

查看绑定：

```http
GET /api/wechat/bindings
Authorization: Bearer <登录 token>
```

解绑：

```http
DELETE /api/wechat/bindings/{binding_id}
Authorization: Bearer <登录 token>
```

## 龙虾 MCP 调用

Endpoint：

```text
POST https://你的域名/mcp
Header: X-MCP-Token: <GIFT_MONEY_MCP_API_TOKEN>
```

发现工具：

```json
{"jsonrpc":"2.0","id":1,"method":"tools/list","params":{}}
```

自然语言查询：

```json
{
  "jsonrpc": "2.0",
  "id": 2,
  "method": "tools/call",
  "params": {
    "name": "answer_gift_question",
    "arguments": {
      "text": "张三送了我多少礼金",
      "user_id": 1
    }
  }
}
```

如果龙虾直接接收微信消息，推荐调用按微信身份解析的工具，不要让模型自己传 `user_id`：

```json
{
  "jsonrpc": "2.0",
  "id": 3,
  "method": "tools/call",
  "params": {
    "name": "answer_wechat_message",
    "arguments": {
      "external_id": "微信openid",
      "channel": "wechat",
      "text": "张三送了我多少礼金"
    }
  }
}
```

## 支持的微信问法

```text
张三送了我多少礼金？
张三都送过哪几次？
查张三明细
张三礼金记录
```

如果出现重名，会返回候选人列表，让用户补充地址或备注。

## 后续计划

第二阶段再做写入，不建议第一版直接让 Agent 写数据库：

1. 用户发：`张三今天送了我500，结婚`
2. 系统返回待确认草稿
3. 用户回复：`确认`
4. 再写入 `transactions`

这样可以避免微信自然语言误识别造成脏账。
