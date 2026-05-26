---
title: "剧情带货数据模型"
description: "剧情带货 (Story-Driven Commerce) 的数据模型、状态语义、关系图与模块边界。"
weight: 50
---

> 本文属于"当前架构"文档，描述 P1 与 P2 阶段已经落库生效的剧情带货数据
> 模型与模块边界。P3 扩展计划见 [任务计划](/docs/plans/)。

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

P2 已经落库的范围（W11–W14）：

- 6 条国际叙事公式（Hero's Journey / Pixar / 三幕 / SCQA / SB7 / PAS-BAB），
  公式总数 12（W11-T1 commit `0895303`）；
- `hook_patterns` / `cta_patterns` / `brand_archetypes` 3 张模式库表
  + 27 条内置 seed（10 钩子 + 5 CTA + 12 品牌人格，
  W11-T2 commits `a87b45f` + `1e8b475`，alembic `0007`）；
- `BrandArchetype`（12 值）+ `ToneDimension`（10 值）枚举（W11-T3
  commit `4bb1345`），用于 `commerce_story_configs.archetype` /
  `tone_grid` + `StoryVariant.archetype`；
- `cn_mainland_health` + `overseas_default` 两个新合规 profile
  + 9 条新规则（W11-T4 commit `9483962`），合规规则总数 17；
- 3 个 P2 Agent：`HookWriterAgent` / `CTAWriterAgent` /
  `ArchetypeVoiceRewriterAgent`（W12 commits `8c8c6e9` `2a5b340`
  `450431d`）；
- 4 个 P2 task_kind：`hook_writer` / `cta_writer` /
  `archetype_rewrite` / `story_video_batch_generate`
  （W12-T4 + W14-T1）；
- A/B 变体克隆 + Champion 标记 API（W14-T3 commit `1d89126`）；
- 商品图生成 API（W14-T2 commit `145e776`）；
- 模式库只读 API（W14-T4 commit `c59fa4a`）；
- 批量剧本生成 API（W14-T1 commit `860b09f`）。

P3 不在范围（仍待实现）：效果数据写入与分析、Partner API
启用、多平台导出预设、Slack/邮件合规告警、品牌资产保险柜。

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

### P2 内置 6 条国际公式（W11-T1 commit `0895303`）

定义同样在 `app/services/commerce/builtin_story_formulas.py`，与 P1 公
式一同由 `bootstrap_builtin_story_formulas(db)` 幂等写入；`region` 统
一为 `global`。

| `id` | 名称 | `region` | 典型时长 | 典型镜头数 | `risk_flags` |
| --- | --- | --- | ---: | ---: | --- |
| `heros_journey` | 英雄之旅 | global | 150s | 7 | `unverifiable_outcome` |
| `pixar_story_spine` | Pixar 故事脊柱 | global | 75s | 6 | — |
| `three_act` | 三幕结构 | global | 120s | 7 | — |
| `scqa` | SCQA 商务叙事 | global | 45s | 4 | `unverifiable_outcome` |
| `storybrand_sb7` | StoryBrand SB7 | global | 75s | 7 | — |
| `pas_bab` | PAS / BAB 直效响应 | global | 35s | 3 | `unverifiable_outcome` |

公式总数：**12（P1 6 + P2 6）**。

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

## 模式库（P2 引入）

P2 在 alembic `0007_create_pattern_libraries` 中新增 3 张系统级模式表
（W11-T2 commits `a87b45f` + `1e8b475`），所有内置 seed 由
`bootstrap_builtin_pattern_libraries` 在应用启动时幂等写入。

### `hook_patterns` 表

10 条内置钩子模式，覆盖 `KNOWN_PATTERN_TYPES` 受控词汇表，每条记录包
含 `template_text`（Jinja2 渲染时作为 `HookWriterAgent` 的核心
prompt）、`psychology`、`use_cases`、`avoid_cases` 字段。

| `pattern_type` | 含义 |
| --- | --- |
| `question` | 提问钩子（"你有没有遇到过…"） |
| `conflict` | 冲突钩子（直接抛出对立情境） |
| `contrast` | 对比钩子（前后差异冲击） |
| `numerical` | 数字钩子（"3 个动作"） |
| `curiosity` | 好奇心缺口钩子 |
| `shock` | 震惊钩子 |
| `relatable` | 共鸣钩子（"是不是你也…"） |
| `dialogue` | 对白钩子（直接以台词开场） |
| `visual` | 视觉冲击钩子 |
| `pov` | POV / 第一视角钩子 |

### `cta_patterns` 表

5 条内置 CTA 模式，按 `hardness × urgency_type` 二维分类：

- `hardness`：`soft` / `medium` / `hard`
- `urgency_type`：`scarcity` / `urgency` / `social_proof` / `benefit` /
  `risk_removal`

由 `CTAWriterAgent` 在结尾镜头生成转化文本时引用。

### `brand_archetypes` 表

12 条内置品牌人格原型，参照 tonethief 标准词汇表，`id` 与
`BrandArchetype` 枚举一一对应：`sage` / `jester` / `rebel` /
`provocateur` / `maverick` / `friend` / `expert` / `cheerleader` /
`storyteller` / `analyst` / `coach` / `minimalist`。每条记录额外保留
`motivation` / `voice_traits` / `speech_patterns` / `sample_brands`
字段，用于 `ArchetypeVoiceRewriterAgent` 渲染 prompt。

### `BrandArchetype` 与 `ToneDimension` 枚举（W11-T3 commit `4bb1345`）

`BrandArchetype` 为前述 12 个 archetype 的 enum，应用层 DTO
（`commerce_story_configs.archetype` / `StoryVariant.archetype` /
`ArchetypeRewriteVars.target_archetype`）统一以该 enum 校验取值。

`ToneDimension` 是 10 个语调维度，每个维度 0–10 分，组合形成
`commerce_story_configs.tone_grid`：

| 维度 | 语义两端 |
| --- | --- |
| `formality` | Formal ↔ Casual |
| `seriousness` | Serious ↔ Playful |
| `technicality` | Technical ↔ Accessible |
| `enthusiasm` | Reserved ↔ Enthusiastic |
| `humanity` | Corporate ↔ Human |
| `activity` | Passive ↔ Active |
| `specificity` | Vague ↔ Specific |
| `conciseness` | Long-winded ↔ Concise |
| `conventionality` | Conventional ↔ Irreverent |
| `safety` | Safe ↔ Provocative |

## 脚本变体 (Story Variant)

### `story_variants` 表

A/B 变体容器，同一项目可生成多版剧本：

| 列 | 类型 | 说明 |
| --- | --- | --- |
| `id` | `String(64)` PK | 变体唯一 ID |
| `project_id` | `String(64)` FK→`projects` ON DELETE CASCADE | 所属项目 |
| `chapter_id` | `String(64)` FK→`chapters` ON DELETE CASCADE | 所属章节 |
| `formula_id` | `String(64)` FK→`story_formulas` ON DELETE RESTRICT | 公式被引用时禁止删除 |
| `hook_pattern_id / cta_pattern_id` | `String(64)?` | P2 已启用，软引用 `hook_patterns` / `cta_patterns` |
| `archetype` | `String(32)?` | 品牌人格，P2 取值受 `BrandArchetype` enum 约束 |
| `script_full_text` | `Text` | 完整剧本文本 |
| `script_breakdown` | `JSON dict` | 镜头分解结果 JSON（StoryScript 序列化） |
| `status` | `StoryVariantStatus` | draft / generating / ready / failed |
| `is_champion` | `Boolean` | A/B 优胜标记（P2 启用，见下方语义） |
| `compliance_score` | `Integer` | 合规评分 0–100（合规检查器写入） |
| `generated_by_task_id` | `String(64)?` | 触发它的 GenerationTask（无硬 FK） |

`script_breakdown` 是 `StoryScript`（见
`app/core/contracts/story.py`）的 JSON 序列化形态，包含 `shots[]`、
总时长、镜头总数、所用公式、开场钩子、CTA 文案与品牌口播次数等
统计字段。

### `is_champion` 语义（W14-T3 commit `1d89126`）

`is_champion` 在同一 `(project_id, chapter_id)` 维度内是**互斥单选**
状态：

- 标记一个变体为 champion 时（`PATCH /studio/story-variants/{id}/champion`），
  service 层自动将同 `(project, chapter)` 下其他变体的 `is_champion`
  置为 `False`，确保任意时刻只有一个 champion；
- `is_champion` 不参与 `StoryVariantStatus` 状态机判断，仅作为业务侧
  的"已选定上线版本"标记；
- 删除 champion 变体后不会自动指派新 champion，由前端在变体列表中重新
  选择；
- A/B 克隆（`POST /studio/story-variants/{id}/clone`）出来的新变体
  默认 `is_champion=False`，不会继承源变体的 champion 标记。

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
发布。`cn_mainland_health` / `overseas_default` 已在 P2 落库（见下），
`hk_tw` 仍保留给后续阶段。

### P2 新增 9 条规则与 2 个 profile（W11-T4 commit `9483962`）

`builtin_rules.py` 在 P2 阶段补齐 `cn_mainland_health` 与
`overseas_default` 两个新 profile，配合 `bootstrap_compliance.py` 幂等
写入 `compliance_profiles.rules`。

#### `cn_mainland_health` profile

继承 `cn_mainland_default` 的 8 条基础规则，再叠加 4 条针对健康类商品
的强约束：

| `rule_id` | `kind` | `severity` | 说明 |
| --- | --- | --- | --- |
| `cn_health_no_efficacy_claim` | `banned_phrase` | **blocker** | 禁止暗示治疗效果 |
| `cn_health_required_disclaimer` | `required_disclaimer` | **blocker** | 必须含完整健康类免责声明 |
| `cn_health_no_medical_terms` | `banned_phrase` | warning | 禁医疗术语 |
| `cn_health_no_age_specific_claim` | `banned_phrase` | warning | 禁年龄绝对承诺 |

#### `overseas_default` profile

5 条独立规则，针对海外平台（YouTube / TikTok 等）的认证、宣称与品牌
口播节奏：

| `rule_id` | `kind` | `severity` | 说明 |
| --- | --- | --- | --- |
| `overseas_no_made_up_credentials` | `banned_phrase` | warning | 禁伪造资历 |
| `overseas_no_unverifiable_outcome` | `banned_phrase` | warning | 禁不可验证宣称 |
| `overseas_no_misleading_urgency` | `banned_phrase` | warning | 禁虚假紧迫 |
| `overseas_required_authentic_label` | `required_label` | warning | 必须含 `Dramatization` / `Ad` / `Sponsored` 标识 |
| `overseas_brand_mention_cap_60s` | `brand_mention_cap` | warning | 海外品牌口播 60s 内 ≤ 3 次（较国内宽松） |

合规 profile 总数：**3（P1 `cn_mainland_default` + P2
`cn_mainland_health` + P2 `overseas_default`）**。

合规规则总数：**17（P1 8 + P2 9）**。

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

## P2 新增 Agents（W12）

P2 在 `app/chains/agents/commerce/` 下落地 3 个新的 LangChain Agent，
对应剧情带货生产链路中"开场钩子重写 / CTA 重写 / 整体语调改写"
三个细分任务：

| Agent | 文件 | 输入 DTO | 输出 DTO |
| --- | --- | --- | --- |
| `HookWriterAgent` | `hook_writer_agent.py` | `HookWriteVars` | `ShotHook` |
| `CTAWriterAgent` | `cta_writer_agent.py` | `CTAWriteVars` | `CTAText` |
| `ArchetypeVoiceRewriterAgent` | `archetype_voice_rewriter_agent.py` | `ArchetypeRewriteVars` | `StoryScript`（结构保留） |

`ArchetypeVoiceRewriterAgent` 额外定义了两条静态 validator：

- `validate_structure_preserved`：确保改写前后的镜头数量、`shot.id`、
  `duration`、`shot_type`、`camera_angle`、`camera_movement`、
  `brand_mention_count` 完全一致；
- `validate_words_to_avoid`：扫描输出文本，确认没有命中
  `ArchetypeRewriteVars.words_to_avoid` 中的禁用词。

入参 / 出参 DTO 全部下沉到 `app/core/contracts/story.py`，遵循 AGENTS.md
约束（`tasks` 不持有跨层 DTO）。

## P2 新增 task_kinds（W12-T4 + W14-T1）

| `task_kind` | 队列 | 默认 timeout | runner 行为 |
| --- | --- | --- | --- |
| `hook_writer` | fast | 180s | 在已存在的变体上重写 `opening_hook` |
| `cta_writer` | fast | 120s | 在已存在的变体上重写 `cta_text` |
| `archetype_rewrite` | fast | 600s | 整脚本改写 + 更新 `StoryVariant.archetype` |
| `story_video_batch_generate` | slow | 7200s | 批量入队 N 个 `story_script_generate` 子任务 |

剧情带货链路 task_kind 总数：**8**（P1 3 个 + P2 4 个 + 现有
`image_generation` / `video_generation` 等通用任务）。

## P2 新增 API 端点（W14）

P2 在 `api/v1/routes/studio/` 与 `api/v1/routes/commerce/` 下新增 12
个端点，统一走 `ApiResponse` 响应壳。

### 变体管理（W14-T3 commit `1d89126`）

- `POST /api/v1/studio/story-variants/{id}/clone` —— 克隆变体，
  可选覆盖 `archetype` / `formula_id` / `hook_pattern_id` /
  `cta_pattern_id`；
- `PATCH /api/v1/studio/story-variants/{id}/champion` —— 标记 champion，
  自动将同 `(project, chapter)` 下其他变体置为非 champion。

### 商品图生成（W14-T2 commit `145e776`）

- `POST /api/v1/studio/products/{id}/images/generate` —— 触发
  `image_generation` 任务，按 `quality_level × view_angle` 维度生成
  商品图。

### 批量生成（W14-T1 commit `860b09f`）

- `POST /api/v1/commerce/story-batches` —— 一次入队 1–10 个
  `story_script_generate` 子任务，由 `story_video_batch_generate`
  父任务统一编排。

### 模式库只读 API（W14-T4 commit `c59fa4a`）

- `GET /api/v1/studio/hook-patterns[?pattern_type=...]` +
  `/api/v1/studio/hook-patterns/{id}`
- `GET /api/v1/studio/cta-patterns[?hardness=&urgency_type=]` +
  `/api/v1/studio/cta-patterns/{id}`
- `GET /api/v1/studio/brand-archetypes` +
  `/api/v1/studio/brand-archetypes/{id}`

剧情带货链路 API 端点总数：**34（P1 22 + P2 12）**。

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

## Alembic 迁移链 (P1 + P2 + P3)

P1 阶段落库 6 个迁移，P2 阶段新增 1 个，P3 阶段已新增 3 个，共 10 个迁移按顺序执行：

| Revision | 文件 | 说明 |
| --- | --- | --- |
| `0001` | `0001_baseline.py` | 历史 schema 的基线 stamp |
| `0002` | `0002_add_project_kind.py` | `Project.kind` 列 + 历史回填 + NOT NULL |
| `0003` | `0003_create_commerce_assets.py` | `products` / `product_images` / `project_product_links` / `commerce_story_configs` |
| `0004` | `0004_create_story_formulas.py` | `story_formulas` / `story_variants` / `story_outcomes` |
| `0005` | `0005_create_compliance.py` | `compliance_profiles` / `compliance_findings` |
| `0006` | `0006_create_api_key_quotas.py` | `api_key_quotas` |
| `0007` | `0007_create_pattern_libraries.py` | **P2**: `hook_patterns` / `cta_patterns` / `brand_archetypes` |
| `0008` | `0008_p3_r2v_audio_strategy.py` | **P3 W16**: `shots.audio_strategy` (VARCHAR(32), default `silent_with_tts`) + `shots.product_focus_level` |
| `0009` | `0009_p3_voice_pack_tts.py` | **P3 W17**: `voice_packs` / `tts_cache` 两表 + `Character.voice_pack_id` (FK) + `StoryVariant.voice_pack_id` / `narration_voice_pack_id` (FK) + `ShotDialogLine.start_time_ms` / `end_time_ms` / `tts_voice_id` (FK) / `tts_audio_file_id` (FK) |
| `0010` | `0010_p3_subtitle_engine.py` | **P3 W18**: `subtitle_styles` 表（含 ASS Style 全字段 + font_fallback_chain JSON）+ `subtitle_tracks` 表（关联 shot_id CASCADE / style_id SET NULL / file_id SET NULL，记录 SubtitleSource 区分 TTS vs ASR 来源） |

总迁移数：**10（baseline + 6 P1 + 1 P2 + 3 P3）**。

迁移之外的"系统级数据"（提示词模板、剧情公式、合规 profile、模式库
seed）通过应用启动时 `app.bootstrap` 调用的 `bootstrap_*` 幂等函数写
入，避免把 SQLite 测试与 MySQL 生产的差异写进 SQL 文件。

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

## Visual Production Layer (P3 W16 + W17 已落地)

P3 阶段为剧情带货链路引入"画面 + 音轨 + 字幕"完整视听生成层。W16 落地 r2v 多图参考管线，W17 + W17 收尾落地 TTS / ASR 双音轨路径与字级时间戳基础设施。本章节覆盖**当前已生效**的实现，未落地的字幕渲染与 chapter_av_export 升级仍在计划文档（[plans/jellyfish-story-commerce.md](/docs/plans/jellyfish-story-commerce/) Wave 18-21）。

### Shot 层新增字段

| 字段 | 类型 | 默认值 | 用途 |
| --- | --- | --- | --- |
| `Shot.audio_strategy` | `String(32)` enum | `silent_with_tts` | 镜头音频策略双路径分流（详见下方 audio_strategy 章节） |
| `Shot.product_focus_level` | `String(16)` enum | `none` | 商品视觉聚焦级别（hero / functional / subtle / none），决定 r2v multi_ref 取图角度优先级（Decision H） |
| `Shot.generated_video_file_id` | `String(64)` FK | NULL | 生成视频对应 `FileItem.id`（type=video） |

### 镜头音频策略（audio_strategy）双路径分流

`Shot.audio_strategy` 是 W16 引入字段、W17 收尾接通业务消费链的核心枚举，控制单镜头从视频生成到字幕产出的整条链路：

| 路径 | 枚举值 | 视频生成 prompt hint | chapter_av_planner 决策 | 字幕来源 |
| --- | --- | --- | --- | --- |
| **默认（旁白驱动）** | `silent_with_tts` | "若镜头出现真人，请保持安静（不张嘴说话），优先侧脸/背影/聚焦商品；避免对镜头连续说话的特写，画面音轨将由独立 TTS 替换。" | 完整跑 Decision F（estimate → speed_adjust → llm_rewrite → hold） | CosyVoice synthesize 输出的 `word_timestamps` |
| **逃生口（演员对话）** | `keep_native` | "若需要演员对话，鼓励自然口型与情感表达；本镜头将保留生成的原音作为最终音轨。" | 整树跳过，产出 `skip_native` 决策（占位 estimated_ms == shot_duration_ms） | Paraformer-v2 异步 ASR 反推的字级 `word_timestamps` |

两条路径在 W17 收尾后**完全对称 first-class**：

- **prompt hint 注入点**：`backend/app/services/studio/generation/video/build_context.py` 维护 `_AUDIO_STRATEGY_PROMPT_HINTS` dict + `get_audio_strategy_prompt_hint()` 公共 API；`build_run_args` 在拼装 `final_prompt` 之后、调用 DashScope 之前把 hint 拼到末尾。
- **路由元信息**：`build_run_args` 把 `audio_strategy` 写入 `run_args["meta"]["audio_strategy"]`，下游 chapter_av_export / 字幕渲染据此分流。
- **planner 分流**：`chapter_av_planner.plan_dialog_line(audio_strategy=...)` 在 keep_native 时早返回 `DurationDecision(action="skip_native")`，跳过 voice_pack 解析与 LLM rewrite，避免误烧 token。
- **DecisionAction 枚举**：`accept` / `speed_adjust` / `llm_rewrite` / `hold`（前 4 项 silent_with_tts 路径产出）/ `skip_native`（keep_native 路径专属）。

### TTS / ASR 双引擎（DashScope）

W17 抽象出统一的 `DashScopeTtsApiAdapter`（`backend/app/core/integrations/aliyun/dashscope_tts.py`），底层共用 `aliyun_bailian` Provider 的 api_key，对外暴露两条非对称能力：

| 方法 | 输入 | 输出 | 用途 |
| --- | --- | --- | --- |
| `synthesize(cfg, input_, timeout_s)` | `TtsRequest(text, voice_pack_id, provider_voice_id, speed, audio_format, enable_word_timestamps)` | `(audio_bytes, list[TtsWordTimestamp])` | CosyVoice WebSocket，文本 → 音频 + 字级时间戳 |
| `estimate_audio_via_asr(cfg, audio_url, timeout_s=600)` | 公网 HTTP/HTTPS audio/video URL | `list[TtsWordTimestamp]` | Paraformer-v2 异步 ASR（submit → poll → fetch transcription_url 三段式），音频 → 字级时间戳 |

`TtsWordTimestamp` 是跨引擎共享的字级时间戳契约（`text` / `begin_ms` / `end_ms`），下游字幕渲染不需要区分来源。

### 音色与缓存

| 表 | 字段 | 说明 |
| --- | --- | --- |
| `voice_packs` | `id` / `name` / `provider` / `provider_voice_id` / `language_code` / `gender` / `archetype_hint` / `sample_file_id` / `default_speed` / `is_system` / `sort_order` | 音色包；W17 内置 6 个 CosyVoice zh-CN 音色（`cosyvoice_v2_longxiaochun` / `longanlang` / `longanwen` / `longniuniu` / `longsanshu` / `longlaobo`） |
| `tts_cache` | `cache_key` (sha256 of `(text, voice_pack_id, speed)` 三元组) / `voice_pack_id` (FK) / `text_preview` / `speed` / `audio_file_id` (FK) / `duration_ms` / `word_timestamps` (JSON) / `hit_count` | 同 `(text, voice_pack_id, speed)` 重复合成时直接命中，避免重复计费（D15） |

`Character.voice_pack_id` / `StoryVariant.voice_pack_id` / `StoryVariant.narration_voice_pack_id` / `ShotDialogLine.tts_voice_id` 全部 FK 到 `voice_packs.id`，确保跨章节同一项目内声纹一致（D9 + D15）。

### Worker / 任务编排

P3 已注册的 worker（`task_executor_registry`）：

| `task_kind` | 队列 | 超时 | 输入 | 输出 |
| --- | --- | --- | --- | --- |
| `tts_generate` | fast | 300s | `text` / `voice_pack_id` / `speed` / `audio_format` / `enable_word_timestamps` | `TtsResult(audio_file_id, duration_ms, word_timestamps[], cache_hit)` |
| `chapter_av_plan` | slow | 7200s | `chapter_id` | `{decisions[], holds[], warnings[]}`，按 audio_strategy 分流 silent_with_tts 走 Decision F、keep_native 产出 skip_native |
| `asr_subtitle_generate` | fast | 600s | `video_file_id` / `language_hints?` | `{source_file_id, audio_url, language_hints, duration_ms, word_timestamps[]}` |
| `shot_subtitle_render` | fast | 120s | `shot_id` / `style_id` / `word_timestamps` / `language_code?` / `source?` | `{subtitle_track_id, file_id, style_id, language_code, source, cue_count, duration_ms, warnings[]}` |

dispatcher 入口在 `backend/app/services/commerce/task_dispatch.py`：

- `enqueue_tts_generate(body)` → fast queue
- `enqueue_chapter_av_plan(body)` → slow queue
- `enqueue_asr_subtitle_generate(body)` → fast queue（W17 收尾新增）
- `enqueue_shot_subtitle_render(body)` → fast queue（W18 新增）

### W18 字幕渲染层

W18 把字级时间戳（来自 W17 双引擎之一）渲染为 `.ass` 字幕文件：

| 表 | 字段 | 说明 |
| --- | --- | --- |
| `subtitle_styles` | `id` / `name` / `description` / `language_code` / `format` (ass/srt/vtt) / `font_family` / `font_fallback_chain` (JSON list[str]) / `font_size` / `primary/secondary/outline/back_colour` (`&HAABBGGRR`) / `bold` / `italic` / `border_style` / `outline` / `shadow` / `alignment` (numpad 1-9 语义化) / `margin_l/r/v` / `play_res_x/y` / `is_system` / `sort_order` | ASS Style 行的语义化 ORM 封装；W18 内置 3 套样式（`douyin_default` / `tiktok_viral` / `reels_lower_third`） |
| `subtitle_tracks` | `id` (uuid hex) / `shot_id` (FK CASCADE) / `style_id` (FK SET NULL) / `file_id` (FK SET NULL) / `language_code` / `format` / `source` (SubtitleSource) / `duration_ms` | 单镜头级字幕实例，``source`` 与 W17 收尾双路径产出严格对应：silent_with_tts → `tts_word_timestamps`，keep_native → `asr_paraformer_v2` |

核心模块：

- `services/studio/subtitle_renderer.py` 纯函数：`format_ass_time(ms)` / `split_words_into_cues(words, language_code, max_chars/min_cue_ms/max_cue_ms)` / `render_ass(style, cues)`。中文按字数 + 强标点（`。！？…；：`）切分，英文按词数 + 强标点（`.!?;:`）切分；时长 > 3s 强制对半切，短 cue（< 500ms）前向合并到下一条以保留强标点切出的句界。
- `services/studio/subtitle_safe_zone.py` 安全区 lint：4 类静态规则（字号下限 / `alignment=bottom_*` 时底部 `margin_v` / 左右 `margin_l/r` / WCAG 4.5:1 字芯-描边对比度），不阻塞渲染只产出 warning。平台前缀启发式（`douyin_*` / `tiktok_*` / `reels_*`）走分平台阈值，未匹配走通用 9:16 兜底。
- `services/studio/shot_subtitle_render_worker.py` 执行层：完整复用 hotfix-4 canonical 模板；run_args 接收 word_timestamps + style_id + language_code + source，产出 `.ass` 文件落 minio（ACL=public-read，便于下游 chapter_av_export 烧录）+ 写 SubtitleTrack 行。

ASS 文件输出固定包含 `[Script Info]` + `[V4+ Styles]` + `[Events]` 三段；每条 Dialogue 用 `{\kf<duration_centiseconds>}<word>` 渲染逐词 karaoke 高亮，配合 SubtitleStyle 的 `secondary_colour` (起始色) → `primary_colour` (终态色) 实现 TikTok / 抖音流行的扫光视觉。

### W16 r2v 多图参考管线

| 模块 | 内容 |
| --- | --- |
| `core/integrations/aliyun/video_capabilities.py` | happyhorse-1.0-t2v/i2v/r2v 三个模型的 `max_reference_images` (1/1/9) + `supports_r2v` + `supported_reference_modes` |
| `core/contracts/video_generation.py` | `VideoGenerationInput.reference_images_base64: list[str] \| None`；`require_prompt_or_any_reference` validator 接受新字段 |
| `core/integrations/aliyun/dashscope_videos.py` | `_build_dashscope_video_body` 在 multi_ref 模式发 `input.media: [{type:reference_image, url:...}]` |
| `services/studio/generation/video/build_context.py` | `REQUIRED_FRAMES_BY_MODE['multi_ref'] = ()`（空 tuple，与 text_only 区分；参考图来源是 ProductImage 而非 ShotFrameImage） |
| `services/studio/generation/video/shot_product_reference_resolver.py` | 按 `Shot.product_focus_level` 优先级序列从 ProductImage 中选择参考图（Decision H：hero/functional/subtle 各自对应不同 angle 优先级序列） |
| `services/studio/reference_image_budget.py` | 9 槽预算管理（Product 3–5 / Character 2–3 / Scene 1–2，超出按优先级丢弃并 warning，Decision G） |

### 模块边界增量（P3 W16 + W17 + W17 收尾 + W18）

```text
backend/app/
├── models/
│   ├── voice_pack.py                  # VoicePack + TtsCache (W17)
│   ├── subtitle.py                    # SubtitleStyle + SubtitleTrack (W18)
│   ├── studio_shots.py                # Shot.audio_strategy + product_focus_level (W16)
│   └── types.py                       # AudioStrategy + ProductFocusLevel + VoiceProvider + VoiceGender (W16/W17) + SubtitleFormat + SubtitleSource + SubtitleAlignment (W18)
├── core/
│   ├── contracts/
│   │   └── tts.py                     # TtsRequest / TtsResult / TtsCacheKey / TtsWordTimestamp (W17)
│   └── integrations/aliyun/
│       └── dashscope_tts.py           # DashScopeTtsApiAdapter: synthesize + estimate_audio_via_asr (W17)
└── services/studio/
    ├── builtin_voice_packs.py         # 6 个内置 CosyVoice 音色 seed (W17)
    ├── builtin_subtitle_styles.py     # 3 个内置 SubtitleStyle seed (W18)
    ├── tts_generate_worker.py         # task_kind=tts_generate (W17 T17-5)
    ├── chapter_av_planner.py          # Decision F 决策树 + skip_native 早返回 (W17 T17-7 + W17 收尾)
    ├── chapter_av_plan_worker.py      # task_kind=chapter_av_plan，加载 (Shot, ShotDetail, lines) 三元组 (W17 + W17 收尾)
    ├── asr_subtitle_generate_worker.py  # task_kind=asr_subtitle_generate (W17 收尾新增)
    ├── subtitle_renderer.py           # ASS 渲染纯函数 + 句子切分策略 (W18)
    ├── subtitle_safe_zone.py          # 字幕安全区 lint (W18)
    ├── shot_subtitle_render_worker.py  # task_kind=shot_subtitle_render (W18)
    └── generation/video/
        ├── build_context.py           # _AUDIO_STRATEGY_PROMPT_HINTS + get_audio_strategy_prompt_hint (W17 收尾)
        └── shot_product_reference_resolver.py  # Decision H multi_ref 取图 (W16)
```



P2 已经把下列原本"P1 未实现"项目全部落库（详见各章节注解）：

- ~~A/B 变体克隆与 Champion 标记~~ → 已完成 W14-T3
- ~~国际叙事公式（Hero's Journey、Pixar、SCQA、SB7、PAS-BAB 等）~~ →
  已完成 W11-T1
- ~~HookPattern / CTAPattern / BrandArchetype 库~~ → 已完成 W11-T2
- ~~`cn_mainland_health` / `overseas_default` 专项合规 profile~~ →
  已完成 W11-T4

下列项目仍未实现，将进入 P3 阶段，请勿基于现有代码假设其存在：

- 效果数据（`StoryOutcome`）写入与分析（P3）
- Partner API 启用与 `ApiKeyQuota` 业务逻辑（P3）
- 多平台导出预设（抖音/快手/小红书/YouTube/TikTok 不同导出参数）（P3）
- Slack / 邮件合规告警（P3）
- 品牌资产保险柜（P3）
- `hk_tw` 合规 profile（P3）

## References

- 计划文档：[剧情带货实施计划](/docs/plans/jellyfish-story-commerce/)
  （计划稳定落地后将沉淀至本目录）
- 状态语义对照：[分镜状态流转说明](/docs/architecture/shot-status-flow/)
- 任务分派与 Celery 路由：[任务执行架构](/docs/architecture/task-execution/)
- AGENTS.md：模块边界 + 状态语义约定
- 数据决策：仓库内 `.omo/notepads/jellyfish-story-commerce/decisions.md`
