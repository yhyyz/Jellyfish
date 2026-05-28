---
title: "投放效果与归因分析"
weight: 48
description: "StoryOutcome 录入、CSV 批量导入、4 维归因 chart 与 KPI / 变体对比表当前生效的实现与边界。"
---

> 本文属于"当前架构"文档，描述 P4 Wave 22 落地后 `dev` 分支真实生效的投放效果数据闭环。
> 数据模型基础参见 [剧情带货数据模型](/docs/architecture/commerce-story-data-model/)。

## 边界

剧情带货变体上线后，效果数据需要回灌到系统才能驱动后续归因优化。当前真实生效的链路：

- 录入入口：`StoryWorkbench` 顶部「投放效果」按钮 + Drawer，分「列表」/「录入」两个 Tab。
- 数据模型：复用 P1 已建的 `StoryOutcome` 表（不新增 schema）。
- 归因维度：按 `StoryFormula` / hook / archetype / 平台 4 个维度聚合。
- 可视化：统一 `PerformanceChart` wrapper（@ant-design/charts v2）。
- 路由：`/commerce/analytics`，挂在 MainLayout 「商业化」分组下。

不包含：

- 自动从平台拉取数据（仍是手工录入或 CSV 上传）。
- 跨项目、跨账号的全局归因（仅当前 project 范围内聚合）。
- ROI 实时计算：`StoryVariant` 当前缺 `estimated_cost` 字段，KPI 中 ROI 永远返回 None（DESIGN GAP，待 P5 解）。

## StoryOutcome 数据模型

P1 已建表（不在本 wave 修改），当前生效字段：

- `id` / `variant_id` (FK → `story_variants.id`) / `recorded_at` (timestamp，禁止未来时间)
- 播放与互动指标：`plays` (BigInteger) / `completion_rate_3s` (Float ∈ [0, 1]) / `like_count` / `comment_count` / `share_count`
- 转化指标：`add_to_cart_count` / `order_count` / `gmv` (Decimal ≥ 0)
- 平台标识：`platform` (str，与 `PlatformExportPreset.platform_code` 对齐)

校验规则（落在 `app/services/commerce/outcome_service.py`）：

- `gmv ≥ 0`（拒绝负数）
- `completion_rate_3s ∈ [0, 1]`（拒绝越界）
- `recorded_at <= now()`（拒绝未来时间戳）
- `variant_id` FK 存在性兜底（防孤儿 outcome）

## 录入 API

落在 `app/api/v1/routes/commerce/outcomes.py`：

| Method | Path | 行为 |
| --- | --- | --- |
| `GET` | `/api/v1/commerce/outcomes` | 列表（支持 `variant_id` / `platform` filter） |
| `POST` | `/api/v1/commerce/outcomes` | 单条录入，body = `StoryOutcomeCreate` |
| `PATCH` | `/api/v1/commerce/outcomes/{id}` | 部分更新，body = `StoryOutcomeUpdate` |
| `DELETE` | `/api/v1/commerce/outcomes/{id}` | 软/硬删除（按当前实现） |

响应统一 `ApiResponse<StoryOutcomeRead>` 信封，前端走 OpenAPI generated `CommerceOutcomesService`。

录入失败的语义：

- 422（pydantic 校验失败，字段越界）
- 404（variant_id 不存在）
- 409（业务规则冲突，例如 recorded_at 重复）

## CSV 批量导入

落在 `app/api/v1/routes/commerce/outcomes_import.py` + `app/services/commerce/outcome_csv_importer.py`。

入口：

```text
POST /api/v1/commerce/outcomes/import
Content-Type: multipart/form-data
fields:
  - file (required, ≤ 5 MB)
  - mapping_profile ∈ {"douyin", "xiaohongshu", "default"}
```

实现要点：

- 零 pandas 依赖，纯 stdlib `csv` 流式 parser。
- 3 个 mapping profile：
  - `douyin`：抖音原始字段（如「播放量」/「完播率」/「成交金额」）→ `StoryOutcome` 字段映射
  - `xiaohongshu`：小红书原始字段映射
  - `default`：与 OpenAPI schema 字段同名直通
- 行错误恢复语义：单行失败不阻塞整批，错误行收集进 `RowError` 列表（行号 + 原始内容 + 失败原因）；valid 行进入 `INSERT`。
- batch commit：每 200 行 commit 一次，避免一次性 commit 大事务把 SQLite/MySQL WAL 撑爆。
- 响应：`ApiResponse<ImportSummary>`，含 `total_rows` / `imported_rows` / `failed_rows` / `errors` 列表。

前端组件：`OutcomeCsvImport.tsx`（antd `Upload` drag-drop + 错误行 `Table`）。

## 4 个归因 chart

聚合层落在 `app/services/commerce/analytics_service.py`（SQLAlchemy 2.0 `select(...).group_by(...)`），路由层落在 `app/api/v1/routes/commerce/analytics.py`：

| Endpoint | 维度 | 主键聚合字段 |
| --- | --- | --- |
| `GET /api/v1/commerce/analytics/by-formula` | StoryFormula | `formula_id` / `formula_name` |
| `GET /api/v1/commerce/analytics/by-hook` | Hook archetype | `hook` 字段 |
| `GET /api/v1/commerce/analytics/by-archetype` | Archetype | `archetype` 字段 |
| `GET /api/v1/commerce/analytics/by-platform` | Platform | `platform` 字段 |

返回 `ChartDataResponse`：

```typescript
{
  dimension: "formula" | "hook" | "archetype" | "platform";
  metric: "gmv" | "completion_rate_3s" | "add_to_cart_count" | ...;
  points: ChartDataPoint[];  // {label, value}
}
```

前端 wrapper：

- `components/charts/PerformanceChart.tsx`：通用 `Column` / `Line` / `Pie` 三种 antd-charts 类型选择，3 态走 `Skeleton` / `Alert` / `Empty`。
- 4 个具体 chart 组件：`ByFormulaChart` / `ByHookChart` / `ByArchetypeChart` / `ByPlatformChart`，每个仅约 30 行，复用同一 `PerformanceChart`。
- antd-charts theme="academy"，颜色继承全局 token。
- lazy chunk：`@ant-design/charts` 通过 `lazy(() => import(...))` 隔离，不进 main bundle。

## KPI 卡片 + 变体对比表

落在 `front/src/pages/aiStudio/commerce/analytics/components/`：

- `KpiCardsRow.tsx`：4 卡（GMV / ROI / 完播率 / 加购率）
  - sample_size = 0 时显示 N/A，避免 0/0 NaN
  - ROI 当前永远 None，原因见上文 Boundary section
- `VariantComparisonTable.tsx`：antd `Table` server-side
  - 排序：`sort_by` 限定枚举（防 SQL 注入），可按 GMV / 完播率 / 加购率 / 互动率
  - 排序方向：`sort_dir ∈ {asc, desc}`
  - 分页：服务端分页，默认 pageSize=20
- `AnalyticsPage.tsx` 整体布局：
  - 顶部 `Segmented` 时间范围（当前 / 7d / 30d / all-time）
  - 中部 KPI 卡 + metric `Segmented`（切换 4 chart 显示的 metric）+ 4 chart 网格
  - 底部 `VariantComparisonTable`

后端聚合 endpoint：

- `GET /api/v1/commerce/analytics/kpis`：返回 `KpiSummary` `{gmv, roi, completion_rate_3s, add_to_cart_rate, sample_size}`，受 `KpiRange` 控制
- `GET /api/v1/commerce/analytics/variants`：返回 `VariantAggregateListResponse`，分页 + 排序

## 调用流程

```text
[StoryWorkbench Drawer]                    [/commerce/analytics 页面]
         |                                            |
         v (single insert / patch)                    v (聚合查询)
   POST /commerce/outcomes              GET /commerce/analytics/by-{dim}
         |                                            |
         |                                            v
         |                              analytics_service.aggregate(...)
         |                                            |
         |                                            v
         |                                   SELECT ... GROUP BY ...
         v                                            |
   outcome_service.create(...)                        |
         |                                            v
         v                                  ChartDataResponse → PerformanceChart
   StoryOutcome 行入库
         |
         v
   后续聚合查询命中 (按 variant_id / platform 索引)
```

CSV 批量导入路径（独立分支）：

```text
[OutcomeCsvImport.tsx]
         |
         v multipart upload
   POST /commerce/outcomes/import (file, mapping_profile)
         |
         v
   stdlib csv parser → mapping_profile 字段重写
         |
         v 行错误收集
   per-200-row batch commit
         |
         v
   ImportSummary {imported, failed, errors[]}
```

## 测试覆盖

- 后端：
  - `tests/api/v1/routes/commerce/test_outcomes_crud.py` — 单条 CRUD（含校验失败场景）
  - `tests/services/commerce/test_outcome_service.py` — service 层校验规则
  - `tests/api/v1/routes/commerce/test_outcomes_import.py` — multipart 上传 + 3 mapping_profile
  - `tests/services/commerce/test_outcome_csv_importer.py` — parser + mapping + 错误行
  - `tests/api/v1/routes/commerce/test_analytics_endpoints.py` — 4 个 by-{dim} endpoint + KPI + 变体对比
- 前端：
  - `OutcomeEntryForm.test.tsx` / `OutcomeCsvImport.test.tsx`
  - `PerformanceChart.test.tsx`（Skeleton / Alert / Empty 三态）
  - `AnalyticsPage.test.tsx`（含 matchMedia / ResizeObserver polyfill）

## 已知限制

- 单一 project 范围聚合：跨项目对比目前不支持。
- ROI = None：依赖 `StoryVariant.estimated_cost` 字段（缺）。
- 平台抓取：仍需手工 CSV，没有平台 OAuth 拉取。

跨项目对比 / ROI 计算 / 平台 OAuth 拉取的演进路线放 `plans/jellyfish-story-commerce.md`，本文不展开。
