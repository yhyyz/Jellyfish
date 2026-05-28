---
title: "Partner API（第三方调用入口）"
weight: 49
description: "ApiKey middleware + bcrypt 配额、/api/v1/public/* 第三方调用入口、slowapi per-key 限流与日/月配额重置当前生效的实现。"
---

> 本文属于"当前架构"文档，描述 P4 Wave 24 落地后 `dev` 分支真实生效的第三方 SaaS 调用入口子系统。

## 边界

Partner API 是给**外部 SaaS 客户**调用 Jellyfish 生成能力的入口子系统，与系统内 admin / 用户登录路径完全分离。当前真实生效的边界：

- 路径前缀：`/api/v1/public/*` 与 `/public/*`（向后兼容）。
- 鉴权：`X-API-Key` HTTP header，bcrypt(cost=12) 哈希校验。
- 配额：per-key 日 / 月配额 + per-key rate-per-minute 限流，全部生效。
- 数据隔离：通过 `GenerationTask.payload.run_args.api_key_hash` 实现租户隔离。
- 不暴露内部 task 细节：响应仅 4 个最小表面字段。

**与 P5 RBAC 的边界**（重要）：

- Partner API 的 `ApiKey` 鉴权体系**仅服务于 `/api/v1/public/*` 第三方调用**。
- 它**不是**用户登录鉴权（admin / 内部 UI 仍走 `settings.api_key` 静态 token，P5 才会进入 user-based RBAC）。
- 两套体系互不替代，P5 RBAC 落地后两者并存。

## 中间件层

实现：`backend/app/core/api_key_auth.py` + `backend/app/core/auth.py`。

启动时挂载顺序（FastAPI middleware 栈）：

```text
HTTP 请求
   |
   v
core/auth.py：路径分支
   ├── /public/*  或  /api/v1/public/*  →  enforce_public_request (per-key)
   └── 其它路径                          →  legacy admin static-key 通道（不变）
   |
   v
enforce_public_request (api_key_auth.py)
   ├── 取 X-API-Key header
   ├── 反查 ApiKeyQuota（按 hash 列）
   ├── bcrypt.checkpw(plaintext, stored_hash, cost=12)
   ├── 校验 is_active
   ├── 原子配额扣减（UPDATE WHERE consumed<limit RETURNING）
   ├── 注入 request.state.api_key_quota
   └── 失败 → JSONResponse 信封（401 / 429 / 403）
   |
   v
路由 handler 拿到 request.state.api_key_quota 做租户判定
```

`PUBLIC_PATH_PREFIX` 当前为 tuple `("/public/", "/api/v1/public/")`，保留向后兼容历史 `/public/*` 挂载点。

## bcrypt 哈希存储

校验路径：

```python
# 简化伪代码
stored = ApiKeyQuota.api_key_hash  # bcrypt hash
ok = bcrypt.checkpw(plaintext.encode(), stored.encode())
```

key 生命周期：

1. **创建**：`POST /api/v1/settings/api-keys` 生成 `secrets.token_urlsafe(32)` 明文 → bcrypt 哈希入库 → 响应**仅本次返回明文一次**，后续无法找回。
2. **存储**：DB 永远只存 hash，明文不落库。
3. **撤销**：`DELETE` 软删 `is_active=False`，请求时直接 401。
4. **轮换**：当前不做自动轮换，需手工撤销 + 创建新 key。

## 原子配额扣减

并发安全的 SQL（PostgreSQL / MySQL / SQLite 通用）：

```sql
UPDATE api_key_quotas
SET consumed_today = consumed_today + 1
WHERE api_key_hash = :id
  AND is_active = TRUE
  AND consumed_today < daily_limit;
```

实证：50 个 `asyncio.gather(...)` 并发请求 vs `daily_limit = 50`，最终 `consumed_today = 50`，从不 overshoot 到 51。

`/public/.../tasks/{id}` 状态查询路径走白名单：跳过配额扣减，但仍要求合法 `X-API-Key`（防止客户端轮询自我 DoS，同时保留可追责性）。

## 第三方调用 endpoint

### POST /api/v1/public/commerce/generate

实现：`backend/app/api/v1/routes/public/generate.py`。

- 入参：`PublicGenerateRequest`
  - `product_id` (str, required) — 必须真实存在
  - `formula_id` (str, required) — 必须真实存在
  - `archetype` / `platform_preset_id` / `variant_count`
- 行为：
  1. middleware 已注入 `request.state.api_key_quota`
  2. 校验 `Product` / `StoryFormula` 存在性（404 if not）
  3. 通过 `task_dispatch` 入队（当前阶段占位走 `story_video_batch_generate` task_kind，commerce 完整 task 不在 P4 范围）
  4. 写入 `GenerationTask.run_args["api_key_hash"]`（这是 T24-3 跨租户隔离的关键）
- 响应：`PublicGenerateResponse`：

```typescript
{
  task_id: string;
  estimated_eta_sec: number;
  status: "queued";
}
```

### GET /api/v1/public/commerce/tasks/{task_id}

实现：`backend/app/api/v1/routes/public/tasks.py`。

- 租户隔离：通过比对 `GenerationTask.payload.run_args.api_key_hash` 与 `request.state.api_key_quota.api_key_hash`。
- **跨租户访问 → 404（不返回 403）**：与任务真不存在统一错误信号，防止枚举攻击与归属嗅探。
- 响应：`PublicTaskStatusRead` 极简信封（仅 4 字段）：

```typescript
{
  status: string;
  progress: number;
  result_file_id: string | null;
  error: string | null;
}
```

不暴露：`payload` / `executor_*` / `cancel_reason` / 任何内部任务字段。

## 限流与配额重置

### slowapi per-key 限流

实现：`backend/app/core/rate_limit.py`。

- composite `key_func`：
  - admin path → IP-keyed（保持 legacy 行为）
  - public path → 命中 `request.state.api_key_quota.api_key_hash`，缺则 fallback IP
- `per_key_rate_limit` 装饰器动态读取 `quota.rate_per_minute`（不同 key 可有不同 rpm）
- 触发时返回 429 + `Retry-After` header

### Celery beat 重置

实现：`backend/app/tasks/quota_reset.py` + `backend/app/core/celery_app.py`。

- `redbeat.schedulers.RedBeatScheduler`：multi-process safe scheduler，比默认 celery-beat 更稳。
- `reset_daily_quotas` — `crontab(0, 0, UTC)` 每日 00:00 UTC 把所有 active key 的 `consumed_today` 清零。
- `reset_monthly_quotas` — `crontab(0, 0, day_of_month=1, UTC)` 每月 1 日 00:00 UTC 清零 `consumed_this_month`。
- 跳过 inactive key（`is_active = False`）。
- compose 中独立服务 `celery-beat`（`celery -A app.core.celery_app beat -l info -S redbeat.schedulers.RedBeatScheduler`）。

## Admin /settings/api-keys UI

实现：`front/src/pages/settings/ApiKeysPage.tsx`。

页面结构：

```text
ApiKeysPage
├── UsageStatsBar             // antd Progress 条 (consumed/daily_limit)
├── 创建按钮 → ApiKeyCreateModal
└── ApiKeyTable               // server-side pagination + revoke Popconfirm
```

`ApiKeyCreateModal` 关键约束：

- 创建成功后**仅本次返回明文**，antd `Result` + 复制按钮。
- checkbox gate：用户必须勾选「已保存」才能关闭，防止误关丢失明文。
- 关闭后明文从前端 state 清空，回不来。

`ApiKeyTable` 列：

- key 名称 / 哈希前缀（脱敏显示）
- 日 / 月配额
- 当前已用量
- rate_per_minute
- 创建时间 / 状态 / 撤销操作（Popconfirm 二次确认）

`UsageStatsBar`：

- antd `Progress` 兜底（antd-charts Tiny line 在该页暂未引入）
- 显示日配额消耗百分比

权限门：当前用 `settings.api_key` 静态 token 占位，RBAC 推迟 P5。

## ApiKeyQuota 表当前字段

P1 已建表（不在本 wave 修改）：

- `id` / `api_key_hash` (unique) / `name` / `description`
- 配额：`daily_limit` / `monthly_limit` / `rate_per_minute`
- 用量：`consumed_today` / `consumed_this_month` / `last_used_at`
- 生命周期：`is_active` (bool) / `created_at` / `revoked_at`

## 调用流程

完整 partner 调用 → 配额扣减 → 重置闭环：

```text
1. Admin 创建 key
   /settings/api-keys 创建
        |
        v
   secrets.token_urlsafe(32) → plaintext
   bcrypt.hashpw(plaintext, cost=12) → DB
   plaintext 一次性返回前端 → 用户复制保存

2. Partner 调用
   POST /api/v1/public/commerce/generate
   X-API-Key: <plaintext>
        |
        v
   middleware: bcrypt.checkpw + rate limit + 原子扣减 consumed_today
        |
        v
   route: 创建 GenerationTask, run_args.api_key_hash 写入
        |
        v
   返回 task_id

3. Partner 轮询状态
   GET /api/v1/public/commerce/tasks/{task_id}
   X-API-Key: <plaintext>
        |
        v
   middleware: 校验 X-API-Key（不扣额度）
        |
        v
   route: 比对 run_args.api_key_hash == request.state.api_key_quota.api_key_hash
        |
        v
   不匹配 → 404；匹配 → PublicTaskStatusRead

4. 配额重置
   redbeat scheduler:
   每日 00:00 UTC → reset_daily_quotas (consumed_today = 0)
   每月 1 日 00:00 UTC → reset_monthly_quotas (consumed_this_month = 0)
```

## 测试覆盖

后端：

- `tests/core/test_api_key_auth.py` — 8 cases，含 50 并发 vs limit=50 race 验证
- `tests/services/api_quota/test_quota_service.py` — create/revoke/list/usage
- `tests/api/v1/routes/settings/test_api_keys.py` — admin CRUD endpoint
- `tests/api/v1/routes/public/test_generate.py` — 6 cases，含 cross-tenant 隔离 + quota consume
- `tests/api/v1/routes/public/test_tasks.py` — 5 cases，cross-tenant 攻击者 → 404
- `tests/core/test_rate_limit_per_key.py` — composite key / per-key 60rpm vs 30rpm 独立 / fallback IP
- `tests/tasks/test_quota_reset.py` — daily / monthly reset / 跨日跨月顺序

前端：

- `pages/settings/__tests__/ApiKeysPage.test.tsx`
- `components/__tests__/ApiKeyCreateModal.test.tsx` — checkbox gate / 明文一次性显示

## 已知限制

- legacy `/api/v1/*` 静态 `settings.api_key` 通道保留向后兼容，未在本 wave 切走。
- key 自动轮换未实现，需手工撤销 + 创建。
- 配额重置错过窗口不补偿（redbeat 默认不 catchup）。
- 用量历史聚合（按月统计）未做，仅当前周期数字。

后续演进路线放 `plans/jellyfish-story-commerce.md`。
