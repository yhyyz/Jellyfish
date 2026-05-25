---
title: "剧情带货数据模型"
description: "剧情带货 (Story-Driven Commerce) 的数据模型、状态语义、关系图与模块边界。"
weight: 50
---

> 本文属于"当前架构"文档，描述 P1 阶段已经落库生效的剧情带货数据模型与
> 模块边界。P2 / P3 的扩展计划见 [任务计划](/docs/plans/)。

## Overview

剧情带货（Story-Driven Commerce）在 Jellyfish 现有的
`Project / Chapter / Shot` 体系上扩展，把"商品"作为新的核心叙事资产，
通过预置剧情公式与合规规则，让带货短视频以"剧情演绎"形态生产，而不是
作为独立产品广告。

设计上的关键取舍：

- **复用而非分叉**：仍然走 `Project → Chapter → Shot → ShotDetail` 的
  生产骨架，仅通过 `Project.kind` 区分两种业务形态；章节、镜头、任务、
  生成媒资体系全部直接复用。
- **商品独立于项目存在**：`Product` 全库唯一，可跨项目复用，类似 `Prop`，
  与项目的关联通过 `ProjectProductLink` 三层（project / chapter / shot）
  挂载。
- **公式与合规作为系统级资产**：`StoryFormula` 与 `ComplianceProfile`
  都带 `is_system=True`，由仓库内的 bootstrap 逻辑幂等写入，不允许业务
  侧直接删除。
- **状态语义不复用**：`shot.status` 仍然只承载"信息提取确认状态"；
  脚本变体的运行状态由 `StoryVariant.status` 单独管理；合规分数是
  计算字段，由检查任务回写。

P1 已经落库的范围：

- `Project.kind` 字段及向后兼容回填；
- `Product` / `ProductImage` / `ProjectProductLink` /
  `CommerceStoryConfig` 4 张表；
- `StoryFormula` / `StoryVariant` / `StoryOutcome` 3 张表（其中
  `StoryOutcome` P1 仅建表，不写入）；
- `ComplianceProfile` / `ComplianceFinding` 2 张表，含 1 个
  `cn_mainland_default` profile + 8 条规则；
- `ApiKeyQuota` 1 张表（P3 partner API 预留）；
- 6 条 P1 内置剧情公式与配套提示词模板。

P1 不在范围（需查阅 `plans` 文档）：A/B 变体克隆 + Champion 标记、
国际叙事公式（Hero's Journey 等）、HookPattern / CTAPattern /
BrandArchetype 库、健康/海外专项合规 profile、效果数据写入与分析、
Partner API 启用、多平台导出预设。

## 项目类型 (Project Kind)

### `ProjectKind` 枚举

`ProjectKind` 定义在 `backend/app/models/types.py`，承载在
`Project.kind` 字段上：

| 值 | 含义 | 默认 | 备注 |
| --- | --- | --- | --- |
| `drama` | 传统短剧项目 | 是 | 历史项目全部回填为该值，行为与 P1 之前一致 |
| `commerce_story` | 剧情带货项目 | 否 | 1:1 绑定一份 `CommerceStoryConfig` |

迁移 `0002_add_project_kind` 落库步骤为：

1. 添加 `kind VARCHAR(32)`，先允许为空、`server_default = 'drama'`；
2. 显式 UPDATE 历史行；
3. 列改为 `NOT NULL`，保留 `server_default` 兼容裸 INSERT。

`Project.kind` 加了 `index=True`，便于按项目类型做列表筛选与统计。

## 商品资源 (Product)

### `products` 表

商品是剧情带货的"故事主角"实体，结构镜像 `Prop`（同样具备
`name / description / style / visual_style / prompt_template_id`），
但语义更偏向商业资源：可跨项目复用，承载品牌、定价、卖点、目标受众、
金句、合规相关字段。

| 列 | 类型 | 说明 |
| --- | --- | --- |
| `id` | `String(64)` PK | 商品唯一标识 |
| `name` | `String(255)` | 商品名称（**全库唯一**） |
| `brand` | `String(128)` | 品牌名 |
| `category` | `ProductCategory` | electronics / beauty / food / apparel / home / health / other |
| `description` | `Text` | 卖点摘要 |
| `price_anchor` | `Float?` | 锚定价（人民币） |
| `sku` | `String(64)?` | SKU / 货号 |
| `selling_points` | `JSON list[str]` | 卖点列表（建议 ≤5） |
| `pain_points_solved` | `JSON list[str]` | 解决的痛点 |
| `target_audience` | `JSON dict` | 受众画像（见下） |
| `catchphrases` | `JSON list[str]` | 金句台词，用于嵌入剧情对白 |
| `competitor_names` | `JSON list[str]` | 禁止提及的竞品名（合规检查使用） |
| `health_disclaimer_required` | `Boolean` | 是否需要健康类免责声明 |
| `visual_style` | `ProjectVisualStyle` | 复用项目枚举 |
| `style` | `ProjectStyle` | 复用项目枚举 |
| `prompt_template_id` | `String(64)?` FK→`prompt_templates` ON DELETE SET NULL | 商品级提示词模板 |

`target_audience` 在 P1 的 schema：

```json
{
  "age_range": "25-35",
  "gender": "female|male|all",
  "region_tier": "tier1|tier2|tier3|rural",
  "pain_points": ["..."]
}
```

P2 将再补 `interests` 与 `income_band`。

约束（D1 决策，与 `Prop` 一致）：

- `UNIQUE(name)` 全库唯一（`uq_products_name`）；
- 索引 `ix_products_name`；
- 不做项目级 scope，便于跨项目素材去重。

### `product_images` 表

每个商品的多角度图片，结构镜像 `PropImage`：

| 列 | 类型 | 说明 |
| --- | --- | --- |
| `id` | `Integer` PK | 自增主键 |
| `product_id` | `String(64)` FK→`products` ON DELETE CASCADE | 所属商品 |
| `file_id` | `String(64)?` FK→`files` ON DELETE CASCADE | 关联文件 |
| `quality_level` | `AssetQualityLevel` | LOW / MEDIUM / HIGH / ULTRA |
| `view_angle` | `AssetViewAngle` | FRONT / LEFT / RIGHT / BACK / THREE_QUARTER / TOP / DETAIL |
| `is_primary` | `Boolean` | 应用层保证同一 product_id 下至多一张主图 |
| `width / height / fmt` | `Integer? / Integer? / String?` | 图片元信息 |

`UNIQUE(product_id, quality_level, view_angle)`：每个
`(商品, 精度, 视角)` 组合至多一张图，便于按精度等级与视角幂等替换。

`file_usages.usage_kind` 在 P1 已扩展三个用途，配合 file 系统跟踪商品
图片：`product_image`、`product_hero_shot`、`commerce_reference`。

### `project_product_links` 表

商品与项目的多对多关联，可挂在 project / chapter / shot 任一层，结构
镜像 `ProjectPropLink`：

| 列 | 类型 | 说明 |
| --- | --- | --- |
| `id` | `Integer` PK | 自增主键 |
| `project_id` | `String(64)` FK→`projects` ON DELETE CASCADE | 必填 |
| `chapter_id` | `String(64)?` FK→`chapters` ON DELETE SET NULL | 可选 |
| `shot_id` | `String(64)?` FK→`shots` ON DELETE SET NULL | 可选 |
| `product_id` | `String(64)` FK→`products` ON DELETE CASCADE | 关联商品 |
| `role_in_story` | `ProductRoleInStory` | savior / catalyst / conflict_source / easter_egg / protagonist_companion |
| `appearance_timing` | `ProductAppearanceTiming` | opening / middle / climax / ending |
| `appearance_duration_sec` | `Integer` | 出现时长（秒） |

`UNIQUE(product_id, project_id, chapter_id, shot_id)` 即
`uq_project_product_links_scope`。**注意**：SQL UNIQUE 在 NULL 值上的
语义是"NULL ≠ NULL"，因此同一 `(product_id, project_id)` 组合下若都
不指定 chapter / shot，会被允许重复入库；服务层
（`app/services/commerce/products.py`）需要补强幂等校验，避免出现
逻辑重复挂载。

## 剧情带货项目配置 (CommerceStoryConfig)

`commerce_story_configs` 与 `Project` 形成 1:1（`project_id` 即 PK，
ON DELETE CASCADE）：

| 列 | 类型 | 说明 |
| --- | --- | --- |
| `project_id` | `String(64)` PK / FK→`projects` | 1:1 |
| `target_platform` | `Platform` | douyin / kuaishou / xiaohongshu / youtube / tiktok |
| `target_duration_sec` | `Integer` | 目标时长（秒），默认 60 |
| `formula_id` | `String(64)?` | 选定的剧情公式（无硬 FK） |
| `archetype` | `String(32)?` | 品牌人格（P1 仅存储；P2 启用 BrandArchetype 枚举） |
| `tone_grid` | `JSON dict` | 语调维度（P2 完整启用） |
| `audience_override` | `JSON dict?` | 覆盖商品默认受众 |
| `compliance_region` | `ComplianceRegion` | cn_mainland / hk_tw / overseas |
| `compliance_profile_id` | `String(64)` | 合规规则集 ID，默认 `cn_mainland_default` |
| `target_kpi` | `String(32)?` | awareness / clicks / conversion |

`formula_id` 故意不挂硬 FK，避免删除非系统公式时影响项目记录；运行时
由 service 层负责一致性。

## 剧情公式 (Story Formula)

### `story_formulas` 表

系统级剧情公式注册表（如"凡人逆袭""开局打脸"等叙事模板），
`is_system=True` 表示来自内置初始化脚本，禁止通过应用层接口删除/编辑。

| 列 | 类型 | 说明 |
| --- | --- | --- |
| `id` | `String(64)` PK | 公式 ID（如 `underdog_triumph`） |
| `name` | `String(255)` | 中文名称 |
| `region` | `FormulaRegion` | cn / global |
| `category` | `String(64)` | 分类标签（cn_viral / cn_workplace / ...） |
| `structure` | `JSON dict` | 完整 beat 结构：`{beats[], total_shots_range, duration_sec_range}` |
| `risk_flags` | `JSON list[str]` | 风险标记（必须取自 `KNOWN_RISK_FLAGS`） |
| `sample_dialog` | `Text` | 完整示例剧本（变量化） |
| `typical_duration_sec` | `Integer` | 典型时长 |
| `typical_shot_count` | `Integer` | 典型镜头数 |
| `psychology` | `Text` | 心理学原理 |
| `use_cases` | `JSON list[str]` | 适用场景 |
| `avoid_cases` | `JSON list[str]` | 禁忌场景 |
| `prompt_template_id` | `String(64)` FK→`prompt_templates` ON DELETE RESTRICT | 强外键，防止悬空 |
| `is_system` | `Boolean` | 默认 True |
| `sort_order` | `Integer` | UI 升序展示 |

联合索引 `ix_story_formulas_region_category (region, category)` 加速
"按地域 + 分类"筛选。

`prompt_template_id` 的 ON DELETE RESTRICT 保障：模板不存在时启动直接
报错，强制 `bootstrap_builtin_prompts` 必须先于
`bootstrap_builtin_story_formulas` 运行。

### P1 内置 6 条中国市场公式

定义在 `app/services/commerce/builtin_story_formulas.py`，由
`bootstrap_builtin_story_formulas(db)` 幂等写入：

| `id` | 名称 | 典型时长 | 典型镜头数 | 心理学原理（一句话） |
| --- | --- | --- | --- | --- |
| `underdog_triumph` | 凡人逆袭 | 60s | 4 | 替代性满足 + 自我投射，刺激多巴胺翻转节奏 |
| `contrast_surprise` | 对比反转 | 45s | 3 | 对比效应 + 锚定偏差，"前后差异"远强于绝对值 |
| `workplace_hero` | 职场逆袭 | 90s | 5 | 职业焦虑替代满足，把产品塑造成"个人能力的延伸" |
| `family_conflict` | 家庭冲突 ⚠️ HIGH RISK | 75s | 5 | 家庭关系修复幻想，平台高压区 |
| `mystery_twist` | 悬疑反转 | 60s | 4 | 好奇心缺口理论（Loewenstein 1994） |
| `time_travel` | 时空穿越 | 80s | 5 | 自我对话 + 后悔规避，"避免后悔"而非"消费冲动" |

所有公式硬绑定到提示词模板 `story_formula_generator_v1`（由
`app/services/studio/builtin_prompts.py` 在更早阶段写入）。

### Risk Flag 受控词汇表

`KNOWN_RISK_FLAGS` 是公式 `risk_flags` 的允许集合，新增类型必须同步到
合规检查器与本文档：

| 标记 | 触发场景 |
| --- | --- |
| `requires_yanyi_label` | 必须在画面上显著标注"演绎/虚构"字样 |
| `family_conflict_compliance` | 含家庭冲突，需避免婆媳互骂/亲子控诉式画面 |
| `class_sensitivity` | 阶层/收入差距叙事，避免对原雇主/家庭/母校的丑化 |
| `health_claim_risk` | 易触发隐性健康功效宣称，需配健康类合规 |
| `gender_sensitivity` | 涉及性别角色/性别对立 |
| `unverifiable_outcome` | 含"你也能…/你将会…"等无法验证的承诺 |

`FormulaDefinition` 在 Pydantic 校验阶段就拒绝未知 flag，避免脏数据
入库。

## 脚本变体 (Story Variant)

### `story_variants` 表

A/B 变体容器，同一项目可生成多版剧本：

| 列 | 类型 | 说明 |
| --- | --- | --- |
| `id` | `String(64)` PK | 变体唯一 ID |
| `project_id` | `String(64)` FK→`projects` ON DELETE CASCADE | 所属项目 |
| `chapter_id` | `String(64)` FK→`chapters` ON DELETE CASCADE | 所属章节 |
| `formula_id` | `String(64)` FK→`story_formulas` ON DELETE RESTRICT | 公式被引用时禁止删除 |
| `hook_pattern_id / cta_pattern_id` | `String(64)?` | P2 启用，无硬 FK |
| `archetype` | `String(32)?` | 品牌人格（P2 启用枚举） |
| `script_full_text` | `Text` | 完整剧本文本 |
| `script_breakdown` | `JSON dict` | 镜头分解结果 JSON（StoryScript 序列化） |
| `status` | `StoryVariantStatus` | draft / generating / ready / failed |
| `is_champion` | `Boolean` | A/B 优胜标记（P2 启用） |
| `compliance_score` | `Integer` | 合规评分 0–100（合规检查器写入） |
| `generated_by_task_id` | `String(64)?` | 触发它的 GenerationTask（无硬 FK） |

`script_breakdown` 是 `StoryScript`（见
`app/core/contracts/story.py`）的 JSON 序列化形态，包含 `shots[]`、
总时长、镜头总数、所用公式、开场钩子、CTA 文案与品牌口播次数等
统计字段。

### `story_outcomes` 表（P1 建表，P3 写入）

| 列 | 类型 | 说明 |
| --- | --- | --- |
| `id` | `Integer` PK | |
| `variant_id` | `String(64)` FK→`story_variants` ON DELETE CASCADE | |
| `platform` | `Platform` | |
| `plays` | **`BigInteger`** | 爆款短视频播放量极易超 `2^31`，避免溢出 |
| `completion_rate_3s / completion_rate_full` | `Float?` | 未回传时 NULL，与 0 区分 |
| `interactions / cart_clicks / orders` | `Integer` | |
| `gmv` | `Float` | |
| `notes` | `Text` | |
| `raw_payload` | `JSON dict` | 平台原始 JSON，作为 schema 变化缓冲层 |
| `recorded_at` | `DateTime(timezone=True)` | 业务侧统计窗口截止时点 |

P1 仅建表，不暴露写入接口；P3 在 partner API 启用时同时支持手动录入与
CSV 批量回灌。

## 合规 (Compliance)

### `compliance_profiles` 表

| 列 | 类型 | 说明 |
| --- | --- | --- |
| `id` | `String(64)` PK | 如 `cn_mainland_default` |
| `name` | `String(255)` | 显示名 |
| `region` | `ComplianceRegion` | cn_mainland / hk_tw / overseas |
| `rules` | `JSON list[dict]` | 规则数组，每条 RuleSpec |
| `is_system` | `Boolean` | 系统预置不可删 |
| `description` | `Text` | profile 用途说明 |

P1 只内置 1 个 profile：`cn_mainland_default`，由
`bootstrap_builtin_compliance_profiles` 幂等写入。

### `compliance_findings` 表

| 列 | 类型 | 说明 |
| --- | --- | --- |
| `id` | `Integer` PK | |
| `variant_id` | `String(64)` FK→`story_variants` ON DELETE CASCADE | |
| `severity` | `ComplianceSeverity` | info / warning / blocker |
| `rule_id` | `String(64)` | 触发的规则 ID |
| `rule_kind` | `String(32)` | banned_phrase / required_label / required_disclaimer / brand_mention_cap |
| `description` | `Text` | 问题描述 |
| `location` | `String(255)?` | 如 `"Shot 3, dialog line 2"` |
| `suggested_fix` | `Text?` | 建议修复方案 |
| `is_resolved` | `Boolean` | 状态机：未修 / 已修 |
| `detected_at` | `DateTime` | 检测时间 |

联合索引 `ix_compliance_findings_variant_severity (variant_id,
severity)` 加速"按 variant 快速过滤 blocker"。

### P1 内置 8 条规则 (`cn_mainland_default`)

由 `app/services/compliance/builtin_rules.py` 定义并由
bootstrap 幂等序列化进 `compliance_profiles.rules`：

| `rule_id` | `kind` | `severity` | 说明 |
| --- | --- | --- | --- |
| `cn_yanyi_label` | `required_label` | **blocker** | 必须包含"演绎"或"虚构"标识 |
| `cn_banned_maicai` | `banned_phrase` | **blocker** | 卖惨/哭穷套路（"卖惨""跪求"等） |
| `cn_banned_fake_credentials` | `banned_phrase` | warning | 伪造身份/学历（"悉尼大学Linda教授"等） |
| `cn_banned_group_denigration` | `banned_phrase` | warning | 群体丑化（"农村人""屌丝"等） |
| `cn_brand_mention_cap_60s` | `brand_mention_cap` | warning | 60 秒内品牌口播 ≤ 2 次（`brand_aliases` 运行时注入） |
| `cn_health_disclaimer` | `required_disclaimer` | **blocker** | 仅对 `ProductCategory.health` 触发，必须含"非医疗器械"声明 |
| `cn_unverifiable_urgency` | `banned_phrase` | warning | 不可验证的紧迫性宣称（"仅限今日"等） |
| `cn_fake_policy_claim` | `banned_phrase` | **blocker** | 虚假政策/补贴宣称（"国补下线倒计时"等） |

D3 决策：**P1 blocker 仅在 `banned_phrase` + `required_label`
+ `required_disclaimer`**；LLM 模糊判断一律为 warning，避免误报阻塞
发布。`cn_mainland_health` / `overseas_default` / `hk_tw` 保留给 P2。

### 双引擎合并策略

合规检查由 `ComplianceCheckerAgent` 与
`ComplianceRuleEngine` 双路并行：

- **规则引擎**：基于 pyahocorasick 多模式串匹配（`banned_phrase`、
  `required_label`、`required_disclaimer`、`brand_mention_cap`），
  确定性产出。
- **LLM Agent**：对剧本做软语义判断，输出 `ComplianceCheckResult`。

合并策略（详见 `compliance_check_worker.py`）：

- **去重键**：`(rule_id, location)`。
- **severity 取较高者**：`blocker > warning > info`。
- **评分公式**：`score = 100 - 25*blockers - 5*warnings - 1*infos`，
  并 clamp 到 `[0, 100]`，写回 `StoryVariant.compliance_score`。

## 配额 (API Key Quota)

`api_key_quotas` 是 P3 阶段 partner / 外部 API key 配额管理的预留表，
P1 仅建表、不挂业务逻辑、不暴露读写接口。

| 列 | 类型 | 说明 |
| --- | --- | --- |
| `api_key_hash` | `String(128)` PK | API key 的 bcrypt 哈希（不持久化明文） |
| `daily_limit / monthly_limit` | `Integer` | 日 / 月调用上限 |
| `rate_per_minute` | `Integer` | 每分钟请求数上限 |
| `consumed_today / consumed_this_month` | `Integer` | 已消耗计数 |
| `last_reset_daily / last_reset_monthly` | `Date` | 上次重置 |
| `description` | `String(255)` | 用途备注 |
| `is_active` | `Boolean` (indexed) | 是否启用 |

D6 决策：P1 即建表避免未来迁移。

## ER 关系图

```text
Project (kind=commerce_story)
  ├── 1:1 CommerceStoryConfig
  │     ├── target_platform / target_duration_sec
  │     ├── formula_id  ──────┐ (软引用)
  │     ├── compliance_region │
  │     └── compliance_profile_id ──┐ (软引用)
  │                                 │
  ├── 1:N Chapter ── 1:N Shot ── 1:1 ShotDetail
  │
  ├── M:N Product (via ProjectProductLink)
  │     │  挂载层级: project / chapter / shot
  │     │  额外字段: role_in_story, appearance_timing,
  │     │           appearance_duration_sec
  │     │
  │     └── Product
  │           ├── 1:N ProductImage  (UNIQUE quality+angle)
  │           └── prompt_template_id ─→ PromptTemplate (SET NULL)
  │
  └── 1:N StoryVariant
        ├── N:1 StoryFormula  (RESTRICT)
        │       └── prompt_template_id ─→ PromptTemplate (RESTRICT)
        ├── 1:N ComplianceFinding  (CASCADE)
        │       └── 触发的 rule 来自 ──→ ComplianceProfile (软引用)
        └── 1:N StoryOutcome (P3 写入, P1 仅建表)

ApiKeyQuota (P1 建表, P3 启用 partner API 时使用)
```

## Alembic 迁移链 (P1)

P1 阶段共落库 6 个迁移，必须按顺序执行：

| Revision | 文件 | 说明 |
| --- | --- | --- |
| `0001` | `0001_baseline.py` | 历史 schema 的基线 stamp |
| `0002` | `0002_add_project_kind.py` | `Project.kind` 列 + 历史回填 + NOT NULL |
| `0003` | `0003_create_commerce_assets.py` | `products` / `product_images` / `project_product_links` / `commerce_story_configs` |
| `0004` | `0004_create_story_formulas.py` | `story_formulas` / `story_variants` / `story_outcomes` |
| `0005` | `0005_create_compliance.py` | `compliance_profiles` / `compliance_findings` |
| `0006` | `0006_create_api_key_quotas.py` | `api_key_quotas` |

迁移之外的"系统级数据"（提示词模板、剧情公式、合规 profile）通过
应用启动时 `app.bootstrap` 调用的 `bootstrap_*` 幂等函数写入，避免把
SQLite 测试与 MySQL 生产的差异写进 SQL 文件。

## 状态语义对齐

剧情带货链路涉及四种状态，必须严格区分，**禁止互相代用**：

- **`Project.kind`**：业务形态分类（`drama` / `commerce_story`），
  与 `shot.status` 解耦。剧情带货项目同样使用 `pending / ready` 的
  分镜状态机。
- **`shot.status`**：仍然只表示信息提取确认状态（`pending` /
  `ready`）。详见
  [分镜状态流转说明](/docs/architecture/shot-status-flow/)。
- **`StoryVariant.status`**：变体级状态机
  （`draft` → `generating` → `ready` / `failed`），描述脚本生成任务
  的产出状态。
- **`StoryVariant.compliance_score`**：计算字段，每次合规检查任务执行
  后由 `compliance_check_worker` 写入；并不参与 `status` 状态机判断。
- **`ComplianceFinding.is_resolved`**：单条问题的修复状态机
  （False → True）。

页面展示与对话语境中，必须明确区分这四类状态，不要把"合规分数低"
说成"分镜未 ready"或"变体未 generating"。

## 模块边界

按 `AGENTS.md` 的"代码规范"约束，剧情带货按下列结构落位：

```text
backend/
  app/
    core/
      contracts/
        story.py                    # 跨层 DTO（StoryScript / Shot 等 Pydantic）
    models/
      types.py                      # 全部新增枚举
      commerce_assets.py            # Product / ProductImage / ProjectProductLink / CommerceStoryConfig
      story_formula.py              # StoryFormula / StoryVariant / StoryOutcome
      compliance.py                 # ComplianceProfile / ComplianceFinding
      api_quota.py                  # ApiKeyQuota
    services/
      commerce/
        products.py                 # 商品 CRUD 与挂载校验
        story_projects.py           # 剧情带货项目编排
        story_variants.py           # 脚本变体生命周期
        story_formulas.py           # 公式查询
        compliance_query.py         # findings 查询
        builtin_story_formulas.py   # 6 条公式 seed + bootstrap
        task_dispatch.py            # commerce 任务分派（沿用 D2 单 Celery task）
        product_info_extract_worker.py
        story_script_generate_worker.py
        compliance_check_worker.py
      compliance/
        rule_engine.py              # pyahocorasick 规则引擎
        builtin_rules.py            # 8 条规则 + cn_mainland_default profile
        bootstrap_compliance.py     # 幂等写入 profile
      studio/
        builtin_prompts.py          # 27 条提示词模板 seed
    chains/
      agents/
        commerce/
          product_extractor_agent.py
          story_script_generator_agent.py
          compliance_checker_agent.py
    api/
      v1/
        routes/
          studio/                   # 现有路由，已加 commerce 子模块的入口
          commerce/                 # 新增 commerce 路由（瘦身：收参 + 调 service）
```

关键边界约束：

- **`tasks` 模块只做任务封装**，不持有跨层 DTO；剧情带货所有跨层
  契约都收敛在 `app/core/contracts/story.py`。
- **`integrations` 只依赖 `contracts`**，不允许反向依赖 `tasks`。
- **API 层瘦身**：commerce 路由只负责收参、鉴权、调 service、组织
  `ApiResponse`；业务编排全部下沉到 `services/commerce/*`。
- **公式与合规作为系统级配置**放在 service 子模块下，提供
  `BUILTIN_*` 常量 + `bootstrap_*` 幂等加载函数，便于测试与启动时
  共同消费（详见
  `app/services/commerce/builtin_story_formulas.py` 与
  `app/services/compliance/builtin_rules.py`）。

## 不在 P1 范围

下列项目已知会进入后续阶段，但 P1 **未实现**，请勿基于现有代码假设
其存在：

- A/B 变体克隆与 Champion 标记（P2）
- 国际叙事公式（Hero's Journey、Pixar Pitch、Save the Cat 等）（P2）
- HookPattern / CTAPattern / BrandArchetype 库（P2）
- `cn_mainland_health` / `overseas_default` / `hk_tw` 等专项合规
  profile（P2）
- 效果数据（StoryOutcome）写入与分析（P3）
- Partner API 启用与 `ApiKeyQuota` 业务逻辑（P3）
- 多平台导出预设（抖音/快手/小红书/YouTube/TikTok 不同导出参数）（P3）

## References

- 计划文档：[剧情带货实施计划](/docs/plans/jellyfish-story-commerce/)
  （计划稳定落地后将沉淀至本目录）
- 状态语义对照：[分镜状态流转说明](/docs/architecture/shot-status-flow/)
- 任务分派与 Celery 路由：[任务执行架构](/docs/architecture/task-execution/)
- AGENTS.md：模块边界 + 状态语义约定
- 数据决策：仓库内 `.omo/notepads/jellyfish-story-commerce/decisions.md`
