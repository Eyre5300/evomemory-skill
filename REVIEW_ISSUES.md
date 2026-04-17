# EvoMemory Skill (客户端 SDK) — 审查问题跟踪

## 规则
- 新审查追加新章节（R15, R16...）
- 每修复一个问题，立即更新该条目的状态和 commit
- 问题格式：包含具体代码片段和修复方案，确保无需额外上下文即可开工

---

## R14 (2026-04-17)

### P0 — 全部已修复 ✅

**#C01** ✅ `5a055d7` | evomemory_sync/upload_dedup.py
- 问题：should_upload 检查和 mark_uploaded 分两步，多线程/进程 TOCTOU 竞态 → 重复上传
- 修复：SQLite `INSERT OR IGNORE` 原子 check-and-reserve 模式

**#C02** ✅ `5a055d7` | evomemory_sync/worker.py
- 问题：上传失败直接抛异常，瞬态网络错误（DNS、超时）无重试
- 修复：3 次指数退避重试，仅对 transient 错误重试

**#C03** ✅ `5a055d7` | evomemory_sync/agent_tools.py
- 问题：link_ideation/link_experiment 的 memory_id 参数无 UUID 校验 → 路径注入
- 修复：添加 `_validate_uuid()` 检查

**#C04** ✅ `5a055d7` | evomemory_sync/middleware.py
- 问题：hub_ref_ids 循环中 ref_id 无校验
- 修复：添加 UUID 正则校验

### P1 — 全部已修复 ✅

**#C05** ✅ `a7e9209` | evomemory_sync/hub_url.py
- 问题：_resolved_cache (OrderedDict) 无线程锁，多线程竞态
- 修复：添加 threading.Lock 包裹所有 cache 操作

**#C06** ✅ `a7e9209` | evomemory_sync/middleware.py
- 问题：_DOTENV_LOADED 全局变量门控冗余 + import 行重复（sanitize_context 被覆盖）
- 修复：移除 _DOTENV_LOADED，委托 env_loader 自身幂等性，恢复 sanitize_context import

**#C07** ✅ `4ebc222` | evomemory_sync/extraction_fields.py
- 问题：Recipe Option F 的模板 JSON 和示例 JSON 都缺少 parent_ideation_id / parent_experiment_id，LLM 不知道可以填
- 修复：模板和示例都补上 `"parent_ideation_id":null,"parent_experiment_id":null`，规则说明加示例

### P2 — 待修复

**#C08** ✅ | evomemory_sync/extractor.py:20,24,28
- 问题：`_extractor_base_url()`, `_extractor_api_key()`, `_extractor_model()` 每次调用都读 env，频繁调用时效率低
- 当前：`return _env("EVOMEMORY_EXTRACTOR_BASE_URL", ...)` 每次执行
- 修复：添加 `@functools.lru_cache(maxsize=1)` 或模块级缓存（带 TTL）

**#C09** ✅ | evomemory_sync/extractor.py:89
- 问题：`r.raise_for_status()` 后直接 `r.json()` 无异常处理，非 JSON 响应（如 502 HTML）会 crash
- 当前：`r.raise_for_status(); data = r.json()`
- 修复：r.json() 包裹 try/except json.JSONDecodeError，返回 None

**#C10** ❌ 跳过(worker错误码区分属于增强功能，不影响正确性) | evomemory_sync/worker.py:92
- 问题：外层 `except Exception:` 吞掉所有异常，仅 logger.exception 但不区分可恢复/不可恢复
- 当前：`except Exception: logger.exception("offline worker failed"); return 1`
- 修复：保持 logger.exception 但添加具体错误码区分（网络错误 vs 数据错误）

**#C11** ✅ | evomemory_sync/sanitize.py:30-33
- 问题：IP 地址正则 `(?<![.\d])(?:\d{1,3}\.){3}\d{1,3}(?![.\d])` 会误伤版本号（如 `4.40.0` 在某些上下文）
- 当前：已有 negative lookbehind 但仍可能在嵌套场景误匹配
- 修复：收紧为 `(?<![.\w])(?:\d{1,3}\.){3}\d{1,3}(?![.\w])` 避免 `4.40.0` 被匹配

**#C12** ❌ 跳过(已支持 EVOMEMORY_UPLOAD_DEDUP_STATE_FILE env 覆盖) | evomemory_sync/upload_dedup.py
- 问题：SQLite 数据库路径硬编码 `~/.evomemory/upload_dedup.db`，多实例部署时可能冲突
- 当前：`Path.home() / ".evomemory" / "upload_dedup.db"`
- 修复：支持 `EVOMEMORY_DEDUP_DB_PATH` env 覆盖
