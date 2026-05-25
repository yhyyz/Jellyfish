---
title: "剧情带货快速上手"
weight: 30
description: "从环境准备到完成第一个剧情带货项目的完整流程指南。"
---

# 剧情带货快速上手

本指南面向开发者与运营，目标是把剧情带货能力从零跑通到出第一支视频。所有路径与字段名都对齐当前 `dev` 分支已合并的实现，可直接照做。

## 你将获得

- 一条端到端的剧情带货生产流程：商品 → 项目 → 脚本 → 合规 → 视频
- 6 个面向中国市场的爆款公式可选
- LLM 二次合规检查 + 内置 8 条规则的自动化合规校验
- 视频生成沿用现有 `image_generation` / `video_generation` 任务系统，无需重新接入

## 前置准备

### 1. 后端环境

```bash
cd backend
cp .env.example .env
uv sync
uv run alembic upgrade head
uv run uvicorn app.main:app --reload --host 0.0.0.0 --port 8000
```

确认 `.env` 中以下条目可用：

- `DATABASE_URL`（默认 SQLite 即可，生产建议 MySQL）
- `REDIS_URL`（Celery broker / result backend）
- `RUSTFS_*` 或对象存储相关变量（图片上传依赖）

### 2. Celery worker

剧情带货使用 `fast` 队列，启动一个监听该队列的 worker：

```bash
cd backend
uv run celery -A app.celery_app worker -Q fast -l info
```

如果只跑文本类任务（脚本生成、合规检查、商品抽取），`fast` 队列即可。视频生成仍走原有队列，按现有部署文档启动相应 worker。

### 3. 前端环境

```bash
cd front
pnpm install
pnpm dev
```

默认访问 `http://localhost:5173`。

### 4. LLM Provider 配置

至少需要配置一个文本模型才能跑脚本生成与合规检查：

- 进入「模型管理」→「供应商」，添加 OpenAI / Qwen / Volcengine 等 Provider 并填入 API Key
- 添加文本类模型（`category=text`）
- 在「默认模型设置」里把该模型设为 **default text model**

推荐选型：

- 优先选 strict `json_schema` 支持良好的模型（OpenAI `gpt-4o`、`gpt-5.x` 等）
- Qwen / Volcengine 系列也能跑通，但需关注其结构化输出兼容性

### 5. 系统级数据初始化（首次启动自动）

后端启动时由 `bootstrap_async_state` 触发，自动 seed：

- **27 个 PromptTemplate**（包含 `story_formula_generator_v1`、`compliance_checker_v1` 等）
- **6 个剧情公式**（cn 区域，下文列出）
- **`cn_mainland_default` 合规 profile**（含 8 条内置规则）

验证方式：

```bash
curl http://127.0.0.1:8000/api/v1/studio/story-formulas
# 期望返回 6 条记录

curl http://127.0.0.1:8000/api/v1/studio/compliance/profiles?region=cn_mainland
# 期望至少返回 cn_mainland_default
```

如果数量对不上，参考下文「故障排查」。

## 完整用户旅程

下面以「为某个新商品做一支 60 秒的剧情带货短剧」为目标走完整流程。

### Step 1：创建商品

**入口**：`/commerce/products`

操作：

1. 点击「新建商品」或「从 URL 提取」
2. 必填项：`name`、`style`、`description`
3. 推荐填写：
   - `selling_points`：3-5 项，越具体越能进剧情
   - `pain_points_solved`：3-5 项，给冲突点提供素材
   - `catchphrases`：品牌口号 / 转化语
   - `target_audience`：决定脚本的人物设定与对白基调
4. 上传至少一张 `ProductImage`（推荐 `quality=high`、`view_angle=front`），后续视频生成会校验商品图存在性

> **提示**：当商品类目为 `health`（保健类），合规检查会自动启用 `cn_health_disclaimer` 规则，要求脚本中出现疗效免责声明。

### Step 2：创建剧情带货项目

**入口**：`/commerce/projects`

操作：

1. 点击「新建项目」
2. 必填项：
   - 项目名称
   - 题材（`style`）
   - 视觉风格（`visual_style`）
   - 目标平台（抖音 / 视频号 / 小红书 / ...）
   - 目标时长（`target_duration_sec`）
   - **剧情公式**（见下表）
   - 合规地域（默认 `cn_mainland`）
3. 创建后自动跳转到 `StoryWorkbench`（`/commerce/projects/:projectId`）

### 公式选择建议（6 条 cn 公式）

| 公式 ID | 名称 | 推荐时长 | 适用场景 | 备注 |
| --- | --- | --- | --- | --- |
| `contrast_surprise` | 对比反转 | 30-60s | 普通商品快节奏带货 | 默认首选 |
| `underdog_triumph` | 凡人逆袭 | 60-90s | 励志故事、个人成长类商品 | |
| `workplace_hero` | 职场逆袭 | 60-90s | 职场工具、效率类商品 | |
| `family_conflict` | 家庭冲突 | 60-90s | 家庭情感、亲子 / 夫妻类商品 | ⚠️ 容易踩到 `cn_banned_group_denigration`，注意角色设定 |
| `mystery_twist` | 悬疑反转 | 45-75s | 神秘成分、好奇心驱动型商品 | |
| `time_travel` | 时空穿越 | 60-90s | 怀旧 / 后悔类情绪驱动商品 | |

公式 ID 与 `backend/app/services/commerce/builtin_story_formulas.py` 严格保持一致，前端选项直接来自 `GET /api/v1/studio/story-formulas`。

### Step 3：关联商品到项目

在 `StoryWorkbench` 顶部，点击「关联商品」：

1. 选择 Step 1 创建的商品
2. 设置 `role_in_story`：`savior` / `catalyst` / `conflict_source` / `easter_egg` / `protagonist_companion`
3. 设置 `appearance_timing`：`opening` / `middle` / `climax` / `ending`
4. 设置 `appearance_duration_sec`：商品在镜头中应当占据的总时长

一个项目可关联多个商品，但一般不超过 2 个，避免脚本失焦。

### Step 4：生成剧本

操作：

1. 在 `StoryWorkbench` 中确认公式已选定
2. 点击「生成新脚本」按钮

后台行为：

- 创建 `task_kind=story_script_generate` 的 `GenerationTask`
- 投递到 `fast` 队列，超时 600s
- worker 调用文本模型生成脚本，落库为 `StoryVariant`

约 30-60s 后刷新页面，可在 `ScriptEditor` 看到新变体。`status=ready` 表示生成成功。

关键字段说明：

- `opening_hook`：前 3 秒钩子文案，约束在 18 字以内
- `shots[].duration_sec`：累加 ≈ `target_duration_sec` ±10%
- `shots[].product_focus_level`：`subtle` / `functional` / `hero`，对应「弱植入 / 功能展示 / 主角化展示」三种程度，全片应至少出现 3 次商品镜头
- `cta_text`：结尾转化文案
- `brand_mention_count`：品牌口播次数，60 秒内不超过 2 次（合规检查会校验）

### Step 5：合规检查

操作：

1. 在 `ScriptEditor` 旁，针对当前 `ready` 变体点击「合规检查」按钮

后台行为：

- 创建 `task_kind=compliance_check`，投递到 `fast` 队列，超时 180s
- 引擎执行两步：
  1. **规则引擎**：跑 `cn_mainland_default` profile 关联的 8 条内置规则
  2. **LLM 二次审核**：用 `compliance_checker_v1` 模板让模型再扫一遍语义级风险

5-10s 后查看 `ComplianceWarningBanner`，`findings` 按 `severity` 分组：

- `blocker`：阻断项，必须修复后才能进入视频生成
- `warning`：警告项，建议修复
- `info`：提示项

#### 内置 8 条规则（`cn_mainland_default`）

| Rule ID | 拦截内容 |
| --- | --- |
| `cn_yanyi_label` | 缺少「演绎 / 虚构 / 仅供参考」类标识 |
| `cn_banned_maicai` | 涉及买菜 / 团长等违禁组织化营销词 |
| `cn_banned_fake_credentials` | 编造资质（医师 / 主任 / 国家级 等） |
| `cn_banned_group_denigration` | 贬低特定群体（家庭、地域、职业） |
| `cn_brand_mention_cap_60s` | 60 秒内品牌口播超 2 次 |
| `cn_health_disclaimer` | 保健类商品缺少免责声明 |
| `cn_unverifiable_urgency` | 不可验证的紧迫性话术（仅剩 N 件 / 限时几小时） |
| `cn_fake_policy_claim` | 虚假政策背书（国家补贴 / 政府指定 等） |

规则定义见 `backend/app/services/compliance/builtin_rules.py`，可继续扩展。

### Step 6：进入视频生成（沿用现有流程）

当 `compliance_score ≥ 60` 且无 `blocker` 项时：

1. 点击「进入分镜工作台」，跳转到现有 `ChapterStudio` 路径
2. 后续走标准的：
   - 视频准备度（video-readiness）检查
   - 关键帧 / 参考图准备
   - `image_generation` 任务
   - `video_generation` 任务

剧情带货不引入新的视频生成链路，所有规则与现有「分镜工作室」一致，详见 [前端说明](/docs/guide/frontend/) 与 [AI 工作流](/docs/guide/ai-workflow/)。

## 常见任务

### 修改商品信息

- 入口：`/commerce/products` → 点击编辑
- 改动会更新所有引用此商品的 `ProjectProductLink`，对已生成的 `StoryVariant` 不追溯重写

### 删除项目

- 入口：`/commerce/projects` 列表，或工作台右上角的删除按钮
- 级联删除：`CommerceStoryConfig` + `ProjectProductLink` + `StoryVariant` + `ComplianceFinding`
- `Product` 不会被级联删除，可在商品库继续复用

### 切换 / 重新生成脚本变体

- 在 `StoryWorkbench` 点击「生成新脚本」会产生新变体，不覆盖旧的
- 当前实现以「最新 `ready` 变体」作为活跃变体
- P1 阶段暂不支持手动切换 `active` 变体；P2 启用 `is_champion` 标记后再开放手动选择

## 故障排查

### 公式列表为空

```bash
# 检查 PromptTemplate 是否种子完成
curl 'http://127.0.0.1:8000/api/v1/studio/prompts?category=story_formula_generator'

# 应当能看到 story_formula_generator_v1
```

如果为空，重启后端触发 `bootstrap_async_state`，或检查启动日志确认 bootstrap 步骤未抛错。

### 脚本生成超时

- 默认 `time_limit=600s`，长脚本场景下接近上限属正常
- 检查 LLM provider 连通性与限流（4xx / 429）
- 确认 Celery worker 在 `fast` 队列上监听
- 在「任务中心」看 `story_script_generate` 任务的 `error` 字段

### 合规检查不返回 findings

不一定是 bug：

- 真正「干净」的脚本（包含演绎 / 虚构标识、无违禁词、品牌口播在阈值内）可以返回 0 findings，此时 `compliance_score=100`
- 如果怀疑规则未跑，检查：

```bash
curl http://127.0.0.1:8000/api/v1/studio/compliance/profiles/cn_mainland_default
# 应当返回 8 条 rule 关联

curl 'http://127.0.0.1:8000/api/v1/studio/prompts?category=compliance_checker'
# 应当能看到 compliance_checker_v1
```

### 视频生成报「商品图缺失」

- 进 `/commerce/products`，给目标商品上传至少一张 `ProductImage`
- 推荐 `quality=high`、`view_angle=front`，便于关键帧引用
- 重新进入分镜工作台再次执行准备度检查

### 任务一直 pending

- 检查 Celery worker 日志，确认任务被拉起
- 检查 Redis 连接（broker / result backend）
- 在「任务中心」点击任务进入详情，查看 `error` 字段

## 命令速查

| 场景 | 命令 |
| --- | --- |
| 启动后端 | `uv run uvicorn app.main:app --reload --port 8000` |
| 跑迁移 | `uv run alembic upgrade head` |
| 启动 fast 队列 worker | `uv run celery -A app.celery_app worker -Q fast -l info` |
| 启动前端 | `pnpm dev` |
| 同步 OpenAPI 客户端 | `pnpm run openapi:update` |
| 查看公式 | `curl http://127.0.0.1:8000/api/v1/studio/story-formulas` |
| 查看合规 profile | `curl http://127.0.0.1:8000/api/v1/studio/compliance/profiles/cn_mainland_default` |
| 查看变体合规结果 | `curl 'http://127.0.0.1:8000/api/v1/studio/compliance/findings?variant_id=<id>'` |

## 相关文档

- 数据模型：[commerce-story-data-model](/docs/architecture/commerce-story-data-model/)
- 实施计划：[jellyfish-story-commerce](/docs/plans/jellyfish-story-commerce/)
- 公式源码：`backend/app/services/commerce/builtin_story_formulas.py`
- 合规规则源码：`backend/app/services/compliance/builtin_rules.py`
- LLM 接入与扩展：[LLM 供应商注册与扩展](/docs/guide/llm-provider-registration/)
- AI 工作流总览：[AI 工作流](/docs/guide/ai-workflow/)
