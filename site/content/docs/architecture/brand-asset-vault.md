---
title: "品牌资产保险柜"
weight: 50
description: "competitor_names 自动过滤 validator、archetype/tone 强制约束 validator 与 BrandStyleGuide 1:1 per-Product 数据模型当前生效的实现。"
---

> 本文属于"当前架构"文档，描述 P4 Wave 25 落地后 `dev` 分支真实生效的品牌资产保险柜子系统。

## 边界

品牌资产保险柜是把"品牌不可让步"的内容（竞品名禁用 / 品牌人格 / 强制金句 / 禁用句式）固化下来，并在 LLM 生成阶段自动校验的子系统。当前真实生效的边界：

- 触发时机：仅在 LLM 生成阶段（hook / CTA / archetype / script generator agent）触发 validator。
- 失败处理：违反约束时**生成阶段 reject**，retry helper 把 issues 拼成 retry guidance 重新调用 agent，最多 N 次；彻底失败抛 `ValidatorRejected` 不进入 `StoryVariant`。
- 范围：仅作用于带货剧情生成路径，不影响其它非 commerce agent。

**与合规规则的边界**（重要）：

- `BrandStyleGuide` = **品牌一侧不可让步的话术资产**（金句 / 禁用句式 / 品牌人格）
- `ComplianceProfile` = **监管一侧不可触发的法规规则**（虚假宣传 / 医疗保健 / 资质要求）
- 两者职责互不替代：一个看品牌资产保护，一个看监管合规风险，前后并行触发。

## 通用 retry helper

实现：`backend/app/chains/agents/_retry.py`。

签名：

```python
async def retry_with_validator(
    agent_run: Callable[[], Awaitable[T]],
    validators: list[Callable[[T], list[str]]],
    max_attempts: int = 2,
) -> T
```

行为：

1. 调用 `agent_run()` 拿到 output
2. 串行跑所有 validator，收集 `issues: list[str]`
3. 若 issues 为空 → 返回 output
4. 若 issues 非空 → 把 issues 拼成 retry guidance 字符串，注入下一次 `agent_run` 的 prompt
5. 重试到 `max_attempts`，仍失败抛 `ValidatorRejected(issues, last_output)`

特性：

- validator 签名统一：`(output) -> list[str] issues`，issues 为空表示通过
- 多 validator 聚合：所有 validator 一次性跑完，issues 全收集再决定是否 retry
- 上层降级：`ValidatorRejected` 挂着 issues 与 last_output，业务层可拒绝写库或人工介入

## T25-1 competitor_names 自动过滤

实现：`backend/app/services/commerce/validators/competitor_filter.py`。

数据来源：`Product.competitor_names: JSON list[str]`（P1 已建字段）。

匹配引擎：`pyahocorasick` 自动机（多模式扫描，O(n+m+z)）。

匹配规则：

- ASCII 名 → word boundary 匹配（"Apple" 命中 "Apple Pie"，不命中 "pineapple"）
- CJK 名 → 纯子串匹配（中文无空格分词）
- 大小写不敏感（统一 `lower()`）

入口：

```python
build_competitor_validator(competitor_names: list[str]) -> Callable[[output], list[str]]
```

返回的 validator 在生成 output 文本中扫到任何竞品名 → issues 列表加该竞品名 + 命中文本片段；retry guidance 引导 agent 用替换词重写。

仅作纯函数 validator，不接入 orchestrator。后续 wave 通过 `retry_with_validator + ArchetypeVoiceRewriterAgent` 串入。

## T25-2 archetype/tone 强制约束

实现：`backend/app/services/commerce/validators/archetype_tone_validator.py`。

签名：

```python
validate_archetype_tone(
    variant_payload: dict,
    brand_style_guide: BrandStyleGuide | None,
    product_archetype: str | None,
) -> list[str]
```

检查规则：

| 规则 | 来源 | 行为 |
| --- | --- | --- |
| `banned_patterns` | `BrandStyleGuide.banned_patterns` | 命中即 issue |
| `required_endings` | `BrandStyleGuide.required_endings` | 文末必须命中其一 |
| `brand_persona_tagline` | `BrandStyleGuide.brand_persona_tagline` | 必备金句必须出现 |
| archetype keyword 词频 | `product_archetype` 关键词字典 | 命中率 ≥ 0.05 阈值才算"贴合人格" |

落地为纯函数（无 DB 副作用），便于单测覆盖与重用。同样不接入 orchestrator，后续 wave 通过 `retry_with_validator` 串入。

## T25-3 BrandStyleGuide 数据模型

数据模型：`backend/app/models/brand_style_guide.py`。

| 字段 | 类型 | 说明 |
| --- | --- | --- |
| `id` | str (uuid) | 主键 |
| `product_id` | str FK → `products.id` (CASCADE, **unique**) | 1:1 per-Product |
| `must_say_phrases` | JSON list[str] | 强制金句 |
| `banned_patterns` | JSON list[str] | 禁用句式 |
| `required_endings` | JSON list[str] | 必备结尾 |
| `brand_persona_tagline` | str | 品牌人格短描述 |
| `created_at` / `updated_at` | timestamp | |

迁移：`alembic/versions/0013_p4_brand_style_guides.py`。

约束：

- 1:1 per-Product（`unique=True` on `product_id`）
- 删除 Product 时 CASCADE 删除 BrandStyleGuide（避免孤儿）
- 4 个 JSON list 字段允许空数组（`[]`），不要求必填

## CRUD API

实现：`backend/app/api/v1/routes/studio/brand_style_guides.py`。

挂在 `/api/v1/studio/products/{product_id}/brand-style-guide`：

| Method | Path | 行为 |
| --- | --- | --- |
| `GET` | `.../brand-style-guide` | 读取（不存在 → 204 / null） |
| `PUT` | `.../brand-style-guide` | upsert（存在改、不存在建） |
| `DELETE` | `.../brand-style-guide` | 删除 |

服务层：`backend/app/services/commerce/brand_style_guide_service.py`。

响应统一 `ApiResponse<BrandStyleGuideRead>` 信封。

## 前端表单

实现：`front/src/pages/aiStudio/commerce/products/components/BrandStyleGuideForm.tsx`。

入口：`ProductLibrary` 详情 Drawer 加 Tab「品牌话术规范」，挂 `BrandStyleGuideForm`。

字段：

- `must_say_phrases` — antd `Select mode="tags"`，自由输入多条
- `banned_patterns` — antd `Select mode="tags"`
- `required_endings` — antd `Select mode="tags"`
- `brand_persona_tagline` — antd `Input.TextArea` 单行短描述

OpenAPI generated client：`StudioBrandStyleGuidesService` + `BrandStyleGuideRead` / `BrandStyleGuideUpsert` model。

数据查询：`useBrandStyleGuide(productId)` TanStack Query hook。

## 与 ComplianceProfile 的协作关系

```text
LLM 生成阶段
        |
        v
agent_run() → output (variant_payload)
        |
        v
retry_with_validator([
    competitor_filter,        # T25-1: 品牌资产 - 不能提竞品
    archetype_tone_validator, # T25-2: 品牌资产 - 必须贴人格 / 金句 / 禁用句式
])
        |
        ├── issues 非空 → retry guidance 重生（最多 N 次）
        ├── 彻底失败 → ValidatorRejected (不入 StoryVariant)
        |
        v 通过
StoryVariant 行入库
        |
        v
ComplianceCheckerAgent (走独立任务，不在 retry 闭环内)
        |
        v
ComplianceFinding 写入 + (P4 W26) BLOCKER 触发 webhook
```

两个体系独立运行：

- **品牌资产保险柜**（T25）：阻止 LLM 输出违反品牌话术约束的内容，**生成阶段拦截**。
- **ComplianceProfile + ComplianceFinding**：阻止 LLM 输出违反法规约束的内容，**生成后检查**，BLOCKER 触发 webhook（详见 [合规阻断告警子系统](/docs/architecture/compliance-notifications/)）。

## 测试覆盖

后端：

- `tests/services/commerce/validators/test_competitor_filter.py` — 10 cases，词边界正反例 / 中文子串 / 大小写 / 空输入 / validator 集成
- `tests/services/commerce/validators/test_archetype_tone_validator.py` — banned_patterns / required_endings / persona / archetype keyword 命中率
- `tests/chains/agents/test_retry_helper.py` — 4 cases，pass-through / retry-with-guidance / 重试用尽抛错 / 多 validator 聚合
- `tests/services/commerce/test_brand_style_guide_service.py` — service 层 upsert / delete
- `tests/api/v1/routes/studio/test_brand_style_guides.py` — endpoint 层 GET / PUT / DELETE
- `tests/alembic/test_0013_brand_style_guides.py` — schema migration

前端：

- `BrandStyleGuideForm.test.tsx`

## 已知限制

- T25-1 / T25-2 validator 当前**仅纯函数**，未接入实际 orchestrator。后续 wave 通过 `retry_with_validator + ArchetypeVoiceRewriterAgent` 串入生成主路径。
- archetype keyword 词频阈值（0.05）当前硬编码，未做 per-Product 可调。
- BrandStyleGuide 是 per-Product 1:1，跨 Product 共享（如同一品牌多个产品）暂不支持。

后续演进路线放 `plans/jellyfish-story-commerce.md`，本文不展开。
