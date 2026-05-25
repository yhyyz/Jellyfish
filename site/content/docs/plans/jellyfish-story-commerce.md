---
title: "剧情带货后续计划"
weight: 60
description: "P2 / P3 阶段的剩余工作。已完成的 P1 已沉淀到 architecture/commerce-story-data-model.md。"
---

> 本文属于"任务计划"文档，仅描述剧情带货 (story-driven commerce) 当前**仍在推进**或**待推进**的工作。
> 已完成的 P1（数据模型 / 公式 / 合规规则 / Agents / 任务系统 / API / 前端核心三页）请参见
> [当前架构 — 剧情带货数据模型](/docs/architecture/commerce-story-data-model/)。

# 剧情带货后续计划

## P1 已完成（仅作引用）

P1 已经在 `dev` 分支落地并沉淀到架构文档，本计划不再重复展开。要点如下：

- 数据模型：`Product` / `ProductImage` / `ProjectProductLink` / `CommerceStoryConfig` / `StoryFormula` / `StoryVariant` / `StoryOutcome` / `ComplianceProfile` / `ComplianceFinding` / `ApiKeyQuota`
- 6 个 cn 剧情公式 builtin（凡人逆袭 / 反转对比 / 职场逆袭 / 家庭冲突 / 悬念反转 / 时间穿越）
- 8 条核心合规规则 + `cn_mainland_default` profile
- 27 个 prompt template seed（12 新增 commerce 类别 + 15 个历史空缺补齐）
- 3 个 commerce agent：`ProductExtractorAgent` / `StoryScriptGeneratorAgent` / `ComplianceCheckerAgent`
- 3 个 task worker：`product_info_extract` / `story_script_generate` / `compliance_check`
- 22 个 commerce API endpoint（products / story-projects / story-variants / story-formulas / compliance）
- 4 个前端页面：`ProductLibrary` / `StoryProjectLobby` / `StoryWorkbench` + `MainLayout` 侧栏分组

详见：[commerce-story-data-model.md](/docs/architecture/commerce-story-data-model/)。

---

## Phase 2 — Production（约 20 工作日）

### P2 总目标

让平台从"P1 单链路 MVP"进入"团队/工作室级"使用：

- 多版本 A/B 测试 + 冠军变体管理
- 海外 / 健康类目专项合规
- 国际公式 + 钩子 / CTA / 品牌人格库
- 批量生成（一键 N 个变体）
- 前端测试基础（Vitest + RTL）

### P2 Wave 11 — Foundation（约 3 工作日）

| 任务 ID  | 内容                                                                                                                       |
| -------- | -------------------------------------------------------------------------------------------------------------------------- |
| T11-1    | 6 个国际公式 builtin：Hero's Journey / Pixar Story Spine / 3-Act / SCQA / StoryBrand SB7 / PAS-BAB                          |
| T11-2    | 10 个 hook patterns + 5 个 CTA patterns + 12 个品牌 archetype（3 个新 builtin 注册器 + seed）                               |
| T11-3    | `BrandArchetype` enum + `types.py` 枚举扩展（hook / cta 关联类型）                                                         |
| T11-4    | `cn_mainland_health` 合规 profile + `overseas_default` 合规 profile（含海外禁忌词、健康类目专项免责声明）                  |

### P2 Wave 12 — Agents（约 5 工作日）

| 任务 ID  | 内容                                                                                                |
| -------- | --------------------------------------------------------------------------------------------------- |
| T12-1    | `HookWriterAgent`（调用 `hook_pattern_writer` 模板，按 `pattern_id` 生成前 3s 钩子）                |
| T12-2    | `CTAWriterAgent`（调用 `cta_pattern_writer`，按 `hardness` 生成结尾转化语）                         |
| T12-3    | `ArchetypeVoiceRewriterAgent`（调用 `archetype_voice_rewriter`，按品牌人格 + 12 维 tone grid 重写） |
| T12-4    | 3 个新 task worker：`hook_writer` / `cta_writer` / `archetype_rewrite`（全部 fast queue）           |

### P2 Wave 13 — UI（约 5 工作日）

| 任务 ID | 内容                                                                                                       |
| ------- | ---------------------------------------------------------------------------------------------------------- |
| T13-1   | `HookPatternSelector` 组件（10 pattern 卡片 + 预览）                                                       |
| T13-2   | `CTASelector` 组件（5 pattern + hardness 滑块）                                                            |
| T13-3   | `ArchetypeVoiceSlider` 组件（12 archetype × 10 tone 维度的 2D 网格）                                       |
| T13-4   | 合规中心独立页 `/commerce/compliance`（独立 RouteHistory + 规则 JSON 编辑器 + 待处理 findings + 历史报告） |
| T13-5   | 公式库浏览页 `/commerce/formulas`（只读，按 region / category 过滤，详情抽屉展示 beat 结构）               |
| T13-6   | A/B 变体克隆 UI（`StoryWorkbench` 内 Tab 切换） + Champion 标记按钮                                        |

### P2 Wave 14 — Backend Integrations（约 3 工作日）

| 任务 ID | 内容                                                                                                                |
| ------- | ------------------------------------------------------------------------------------------------------------------- |
| T14-1   | `story_video_batch_generate` task_kind（slow queue, 7200s 超时, 并发批 ≤ 2）                                        |
| T14-2   | `ProductImage` → `image_generation` 流水线接入（使用 `prompt_template_id`，复用 `PRODUCT_IMAGE_FRONT/OTHER/HERO`）  |
| T14-3   | 变体克隆 API + Champion 标记 API：                                                                                  |
|         | `POST /api/v1/studio/story-variants/{id}/clone`                                                                     |
|         | `PATCH /api/v1/studio/story-variants/{id}/champion`                                                                 |

### P2 Wave 15 — Verification（约 2 工作日）

| 任务 ID | 内容                                                                                                                                            |
| ------- | ----------------------------------------------------------------------------------------------------------------------------------------------- |
| T15-1   | Vitest + RTL 前端测试基础（顺带把 [jellyfish-improvements](/docs/plans/development-plan/) P3-2 的"前端测试空白"一并解决）                       |
| T15-2   | `commerce` 命名空间 i18n 完整翻译（如调整 i18n 方向）                                                                                           |
| T15-3   | Celery routing 终态修复（确认所有 commerce task_kind 正确分流到 fast / slow queue）                                                             |
| T15-4   | 端到端 6 变体批量生成 smoke test（产品 → 公式 × 钩子 × archetype 笛卡尔积 → 合规 → 入库）                                                       |

### P2 风险登记

- **R-P2-1**：LLM 输出 JSON drift 在长脚本（target_duration_sec > 120s）下显著增加。
  - 缓解：复用现有 `json-repair` fallback；`with_structured_output` + Pydantic 严格校验；prompt 加 "shot count must equal N" 显式约束。
- **R-P2-2**：`ArchetypeVoiceRewriterAgent` 改写过程中容易丢失原 shot id / duration / camera 字段。
  - 缓解：使用 ModelRetry validator，校验改写后的 `shots[].id` 与原集合完全一致，否则触发 retry。
- **R-P2-3**：合规规则演变速度快（监管文件、平台规则、商品类目变化），需要热更新。
  - 缓解：`ComplianceProfile.rules` 已是 JSON 字段，profile 复制 + 改字段即可，不需要改表；规则编辑器（T13-4）支持运行时校验。
- **R-P2-4**：批量生成成本飙升 + 队列堆积。
  - 缓解：parallel batch ≤ 2 默认；租户级 `ApiKeyQuota` 配额（P1 已建表）；批量任务前显式预估 token 用量并提示。

### P2 完成标准

- 6 个国际公式可在 `FormulaPicker` 中选择 + 12 archetype × 10 tone 维度可调
- 单个商品支持一键生成 6 个变体（不同公式 / 钩子 / 人格组合）
- `cn_mainland_health` profile 触发健康类专项免责声明；`overseas_default` profile 启用海外专属禁忌词
- 至少 30 个前端组件 Vitest 单元测试
- `pnpm exec tsc --noEmit` 通过；`pytest -q` 全绿
- drama 流程零回归

---

## Phase 3 — Scale（约 30 工作日）

### P3 总目标

商业化 + 数据驱动 + 第三方开放：

- 真实投放数据回灌驱动归因分析
- 多平台导出预设
- Partner API（第三方 SaaS 调用）
- 品牌资产保险柜
- 合规阻断告警通知

### P3 Wave 21 — Outcome + Analytics（约 8 工作日）

| 任务 ID | 内容                                                                                              |
| ------- | ------------------------------------------------------------------------------------------------- |
| T21-1   | `StoryOutcome` 录入 API + 前端表单（手动录入完播率 / 互动率 / 加购 / 订单 / GMV）                 |
| T21-2   | CSV 批量导入端点（`POST /api/v1/commerce/outcomes/import`，支持抖音 / 小红书原始字段映射）        |
| T21-3   | 4 个分析图表（按公式 / 钩子 / 人格 / 平台 4 个维度归因），使用统一 `PerformanceChart` 组件        |
| T21-4   | KPI 卡片（GMV / ROI / 完播率 / 加购率） + 变体对比表                                              |
| 路由    | `/commerce/analytics`                                                                             |

### P3 Wave 22 — Multi-Platform Export（约 5 工作日）

| 任务 ID | 内容                                                                                                                                                          |
| ------- | ------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| T22-1   | 5 个平台预设（抖音 / 快手 / 小红书 / YouTube Shorts / TikTok），覆盖尺寸（9:16 / 1:1 / 16:9）/ 时长上限 / 字幕规则 / 结尾水印 / 平台特定贴纸                   |
| T22-2   | 导出任务：`task_kind = commerce_export`，slow queue，输出落到 `FileUsageKind.PRODUCT_EXPORT`                                                                  |

### P3 Wave 23 — Partner API（约 8 工作日）

| 任务 ID | 内容                                                                                                                  |
| ------- | --------------------------------------------------------------------------------------------------------------------- |
| T23-1   | `ApiKeyQuota` 启用 + bcrypt 哈希存储 + API key 中间件（注入 quota 上下文）                                            |
| T23-2   | `POST /api/v1/public/commerce/generate` 第三方调用 endpoint（同步入队 + 返回 task_id）                                |
| T23-3   | `GET /api/v1/public/commerce/tasks/{id}` 状态查询                                                                     |
| T23-4   | `slowapi` 限流集成（`rate_per_minute` 字段生效） + 配额日 / 月重置 Celery beat 任务                                   |
| T23-5   | Admin UI 创建 / 撤销 API key（`/settings/api-keys`），含日 / 月配额配置 + 用量统计                                    |

### P3 Wave 24 — Brand Asset Vault（约 5 工作日）

| 任务 ID | 内容                                                                                                          |
| ------- | ------------------------------------------------------------------------------------------------------------- |
| T24-1   | `Product.competitor_names` 自动过滤管线（生成阶段 reject + suggest fix）                                      |
| T24-2   | `archetype` + `tone_grid` 强制约束（违反则在生成阶段 reject 并要求重写，不进入 variant 表）                   |
| T24-3   | 品牌话术规范库 `BrandStyleGuide` 表（强制金句 / 禁用句式 / 必备结尾 / 品牌人格短描述）                        |

### P3 Wave 25 — Compliance Notifications（约 4 工作日）

| 任务 ID | 内容                                                                                          |
| ------- | --------------------------------------------------------------------------------------------- |
| T25-1   | Slack / 邮件 webhook 合规阻断告警（BLOCKER 级 finding 触发）                                  |
| T25-2   | 团队级 escalation rules（连续 N 次阻断 → 升级到团队 owner）                                   |

### P3 完成标准

- 至少 1 个 partner 通过 Partner API 提交并产出 commerce 短剧
- 至少 10 个变体回灌真实投放数据后，归因报告（按公式 / 钩子 / 人格 / 平台 4 维度）可用
- 多平台导出预设覆盖率 100%（5 个目标平台）
- 合规 BLOCKER 告警在配置 webhook 后 5s 内送达

---

## 跨阶段决定（保持稳定）

| ID  | 决定                                                                                                                  |
| --- | --------------------------------------------------------------------------------------------------------------------- |
| D1  | `Product.name` 全局唯一（mirror `Prop` 设计），方便跨项目复用                                                         |
| D2  | 单 Celery `task.execute`，队列路由在 `apply_async` 时通过 `queue=` 参数指定，不在 worker 端硬编码                     |
| D3  | Python `bootstrap_builtin_prompts`（幂等，应用启动时调用），不依赖 SQL seed                                           |
| D4  | 前端 commerce 页面在 P1/P2 阶段 hardcoded zh-CN，i18n 完整化推迟到 P2 Wave 15                                         |
| D5  | 新增 commerce agents 全部使用 `method="json_schema", strict=True`，避免 P1 早期 JSON drift 问题                       |
| D6  | `ComplianceProfile.rules` 用 JSON 字段，规则演化不触发 schema migration                                               |
| D7  | `ApiKeyQuota` 表 P1 即建（避免 P3 二次迁移），但中间件与限流逻辑 P3 才启用                                            |
| D8  | A/B 变体使用同一 `StoryVariant` 表 + `is_champion` 标记，不引入独立 `Champion` 实体                                   |

---

## 进度追踪

- 进度以 `dev` 分支的 `[feat] W*-T*` commit 历史为准
- P1 完整 commit 序列：`PRE-WAVE → W1 → W2 → … → W10`，每个 Wave 内的 task 用独立 commit 标记
- P2 / P3 启动时：
  - 由 plan agent 重新生成详细 Wave 图（因为 P1 实际产出可能影响 P2 依赖关系）
  - 启动 Wave 前先确认对应阶段的"完成标准"是否仍然成立
  - 每完成一个 Wave 同步更新本文件（删除已完成任务 + 移交至 `architecture/`）

## 文档协作约定

- 本文件只记录**未完成**或**进行中**的计划，已完成内容必须在落地后立即移除并沉淀到 `architecture/commerce-story-data-model.md`
- P2 / P3 启动时的详细 Wave 拆解（任务粒度 / 依赖图 / 工作量估算）由 plan agent 生成后回写本文件
- release note 在每个 Phase 收官时写入 `site/content/blog/`：
  - P2 → `v0-5-0.md`
  - P3 → `v0-6-0.md`
- 与本计划相关的架构文档：
  - 当前数据模型：[commerce-story-data-model.md](/docs/architecture/commerce-story-data-model/)
  - 后续会沉淀：`commerce-story-flow.md`（P2 完成后）
  - 后续会沉淀：`commerce-story-compliance.md`（P2 完成后）
- 与本计划相关的 guide：
  - [commerce-story-quickstart.md](/docs/guide/commerce-story-quickstart/)
