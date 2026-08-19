# EvoMemory Skill ↔ vps_bundle（Hub）对接说明

本仓库的 `scripts/setup.py`（browse / share / wizard）与 `evomemory_sync` 中的上传/同步逻辑，与 **vps_bundle** 部署的 FastAPI 应用使用同一套 HTTP 契约。

## 环境变量

| 变量 | 含义 |
|------|------|
| `EVOMEMORY_API_BASE_URL` | Hub **规范**根地址（无尾斜杠），默认写入 **`https://evomem.club`**。生产环境客户端**直连**该地址（无 HTTP / 备用 IP 自动降级）。 |
| `EVOMEMORY_API_TOKEN` | 登录/注册得到的 JWT（`access_token`），与网站一致。 |

### 历史：备案 / 测试阶段的 URL 探测（默认已关闭）

实现位于 `evomemory_sync/hub_url.py`。当前 **`ENABLE_HUB_URL_TESTING_FALLBACKS=false`**（默认），`build_hub_candidate_urls` 仅返回规范地址，`setup.py share` / 运行时客户端不再尝试 HTTP 或备用 IP。

若极少数自建环境仍需旧行为，可将源码中该常量改为 `True`（不推荐用于公网 Hub）。

## 认证（与网站同源）

| 端点 | 方法 | 请求体（JSON） | 响应（成功） |
|------|------|----------------|--------------|
| `/auth/register` | POST | `{"email": "...", "password": "..."}`（密码 ≥ 8 位） | `{"access_token": "...", "token_type": "bearer"}` |
| `/auth/login` | POST | `{"email": "...", "password": "..."}` | 同上 |

`setup.py share` / `wizard` 选项 2、3 会调用上述接口，并将 `access_token` 写入 `.env` 的 **`EVOMEMORY_API_TOKEN`**。

后续请求在 `Authorization: Bearer <access_token>` 头中携带该 token（与 vps_bundle `evomemory/auth.py` 的 `HTTPBearer` 一致）。

## 与 vps_bundle 路由的对应关系

vps_bundle 中 `memory_router` 挂载在应用根路径（无 `/api` 前缀），因此 skill 中使用的路径如 `/auth/login`、`/memory/...` 与服务器路由一一对应。

## 构思 / 实验 / 工作流关联（与 vps_bundle 对齐）

- **实验 → 构思**：上传实验时 JSON 可带 `parent_ideation_id`（需指向已存在且**公开**的构思）。`evomemory_sync.uploader.json_to_experiment_payload` 与 `agent_tools.share_experiment` 已支持该字段。
- **工作流 → 构思 / 实验**：`POST /memory/workflow/upload` 可带 `parent_ideation_id`、`parent_experiment_id`（实验须为**当前用户**所有且父构思校验通过）。Extractor 在 `memory_type: "workflow"` 时由 `json_to_workflow_payload` 映射；Agent 可调用 **`share_workflow`**（已挂中间件时勿与自动上传双写）。
- **检索**：构思 / 实验 / 工作流 / **经验卡**均为向量检索：`POST /memory/ideation|experiment|workflow|recipe/search`（`QueryRequest` 支持 `query_text`；skill 只发 `query_text`）。Agent 工具 `search_evomemory` 四种 kind 都支持；CLI **`python scripts/search.py`** 仅 `ideation` / `experiment` / `workflow`（无 recipe）。看见候选**不计** download；`apply_evomemory` 用 `HUB_APPLY_PROOF` 换 `POST /memory/{id}/applications` 时才记账。
- **仅改父级链接**：`PATCH /memory/experiment/{id}/parent`（body: `parent_ideation_id`）、`PATCH /memory/workflow/{id}/parents`（可只传要改的字段，服务端会与其余字段合并）。skill 提供 **`patch_experiment_parent_link` / `patch_workflow_parent_links`** 与 CLI **`scripts/patch_links.py`**。

## 自检

1. 浏览器打开规范地址 `https://evomem.club`（或你的 Hub），确认服务可访问。
2. `python scripts/setup.py share --base-url https://evomem.club`，完成注册或登录，检查 `.env` 中 **`EVOMEMORY_API_BASE_URL`**（HTTPS）与 **`EVOMEMORY_API_TOKEN`**。
3. 在 Cursor 中触发一次同步或搜索，确认无 401/连接错误。
4. 可选：`python scripts/search.py workflow "关键词" --insecure`（若使用 HTTPS+IP）。
