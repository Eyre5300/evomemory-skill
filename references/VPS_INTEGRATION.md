# EvoMemory Skill ↔ vps_bundle（Hub）对接说明

本仓库的 `scripts/setup.py`（browse / share / wizard）与 `evomemory_sync` 中的上传/同步逻辑，与 **vps_bundle** 部署的 FastAPI 应用使用同一套 HTTP 契约。

## 环境变量

| 变量 | 含义 |
|------|------|
| `EVOMEMORY_API_BASE_URL` | Hub **规范**根地址（无尾斜杠），默认写入 **`https://evomem.club`**。备案/测试阶段运行时可能自动改用可连通的 HTTP 或备用 IP，但 `.env` 中仍保存 HTTPS 规范域名。 |
| `EVOMEMORY_API_TOKEN` | 登录/注册得到的 JWT（`access_token`），与网站一致。 |

### 备案 / 测试阶段的降级（上线后可关闭）

实现位于 `evomemory_sync/hub_url.py`：

- **`ENABLE_HUB_URL_TESTING_FALLBACKS`**：为 `True` 时启用探测与多源重试；正式上线后可改为 `False` 并删去 IP 等降级分支。
- **运行时解析**（`resolve_working_hub_base_url_cached`）：对已配置的规范 URL，按顺序 **探测** 是否可达：`https://主机` → `http://主机` →（仅当主机为 `evomem.club` 时）`https://8.130.132.246` → `http://8.130.132.246`。端口与路径会尽量沿用配置（公网默认无路径）。
- **自建域名**：若也需要在测试阶段走备用 IP，可设置环境变量 **`EVOMEMORY_HUB_IP_FALLBACK=1`**（或 `true`/`yes`），此时会追加 IP 候选（仍受 `ENABLE_HUB_URL_TESTING_FALLBACKS` 控制）。
- **备用 IP**：默认 **`8.130.132.246`**，可通过 **`EVOMEMORY_HUB_FALLBACK_IP`** 覆盖。
- **探测超时**：**`EVOMEMORY_HUB_PROBE_TIMEOUT_SECONDS`**（默认 `5`）。

`scripts/setup.py` 的 **share / wizard（分享）** 在注册/登录时会对 **同一候选列表** 依次发起请求，直到拿到 `access_token`；写入 `.env` 的仍是 **规范 HTTPS** 的 `EVOMEMORY_API_BASE_URL`。

## 认证（与网站同源）

| 端点 | 方法 | 请求体（JSON） | 响应（成功） |
|------|------|----------------|--------------|
| `/auth/register` | POST | `{"email": "...", "password": "..."}`（密码 ≥ 8 位） | `{"access_token": "...", "token_type": "bearer"}` |
| `/auth/login` | POST | `{"email": "...", "password": "..."}` | 同上 |

`setup.py share` / `wizard` 选项 2、3 会调用上述接口，并将 `access_token` 写入 `.env` 的 **`EVOMEMORY_API_TOKEN`**。

后续请求在 `Authorization: Bearer <access_token>` 头中携带该 token（与 vps_bundle `evomemory/auth.py` 的 `HTTPBearer` 一致）。

## 与 vps_bundle 路由的对应关系

vps_bundle 中 `memory_router` 挂载在应用根路径（无 `/api` 前缀），因此 skill 中使用的路径如 `/auth/login`、`/memory/...` 与服务器路由一一对应。

## 自检

1. 浏览器打开规范地址 `https://evomem.club`（或你的 Hub），确认服务可访问。
2. `python scripts/setup.py share --base-url https://evomem.club`，完成注册或登录，检查 `.env` 中 **`EVOMEMORY_API_BASE_URL`**（HTTPS）与 **`EVOMEMORY_API_TOKEN`**。
3. 在 Cursor 中触发一次同步或搜索，确认无 401/连接错误。
