# EvoMemory Skill ↔ vps_bundle（Hub）对接说明

本仓库的 `scripts/setup.py`（browse / share / wizard）与 `evomemory_sync` 中的上传/同步逻辑，与 **vps_bundle** 部署的 FastAPI 应用使用同一套 HTTP 契约。

## 环境变量

| 变量 | 含义 |
|------|------|
| `EVOMEMORY_API_BASE_URL` | Hub 根地址，无尾斜杠，例如 `http://evomem.club` 或 `http://你的 VPS IP:端口` |

`evomemory_sync.hub_url.canonicalize_hub_base_url` 会将公网 Hub 的 `https://` 规范为 `http://`（与历史 uploader 行为一致；若 Hub 仅监听 HTTP，请使用 `http://`）。

## 认证（与网站同源）

| 端点 | 方法 | 请求体（JSON） | 响应（成功） |
|------|------|----------------|--------------|
| `/auth/register` | POST | `{"email": "...", "password": "..."}`（密码 ≥ 8 位） | `{"access_token": "...", "token_type": "bearer"}` |
| `/auth/login` | POST | `{"email": "...", "password": "..."}` | 同上 |

`setup.py share` / `wizard` 选项 2、3 会调用上述接口，并将 `access_token` 写入 `.env` 的 `EVOMEMORY_ACCESS_TOKEN`。

后续请求在 `Authorization: Bearer <access_token>` 头中携带该 token（与 vps_bundle `evomemory/auth.py` 的 `HTTPBearer` 一致）。

## 与 vps_bundle 路由的对应关系

vps_bundle 中 `memory_router` 挂载在应用根路径（无 `/api` 前缀），因此 skill 中使用的路径如 `/auth/login`、`/memory/...` 与服务器路由一一对应。

## 自检

1. 浏览器打开 `EVOMEMORY_API_BASE_URL`，确认 Hub 可访问。
2. `python scripts/setup.py share --base-url <你的 Hub>`，选择注册或登录，检查 `.env` 中是否出现 `EVOMEMORY_ACCESS_TOKEN`。
3. 在 Cursor 中触发一次同步或搜索，确认无 401/连接错误。
