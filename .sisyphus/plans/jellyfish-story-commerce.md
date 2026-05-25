# Jellyfish 剧情带货 (Story-Driven Commerce) 完整实施计划

## Overview
- **目标**: 在 Jellyfish 现有架构上扩展支持「剧情带货」短视频生产 — 把商品融入有故事性的短剧，不是纯商品广告。
- **核心价值**: 同类项目里 Jellyfish 唯一适合"故事化营销"的开源工作台（多镜头叙事 + 角色一致性 + 分镜精控 + 商业合规）。
- **行业数据支撑**: 剧情广告在 A3 高意向人群转化率 5–10%（vs 特性广告 1–3%）；前 3 秒决定 78% 完播；韩束 × 姜十七 案例：¥45M 投入 → 5B 播放 → 营收 ¥3.09B (+143.8% YoY)。
- **总工作量**: ~64 人天（P1: 14d / P2: 20d / P3: 30d+），并行执行下约 2.5–3 个月。
- **分支**: 主开发在 `dev` 分支，每个 Wave 独立 PR。

---

## Pre-Decisions (基于研究的预先决策)

| # | 议题 | 决策 | 理由 |
|---|------|------|------|
| 1 | Project.kind 扩展 vs 新实体 | **扩展 `Project.kind` 枚举** | 复用现有章节/分镜/任务体系，0 迁移成本 |
| 2 | 受众建模深度 | P1 仅 `age_range, gender, region_tier, pain_points`；P2 加 `interests, income_band` | 14d MVP 必须聚焦 |
| 3 | 合规严格度 | P1 blocker 仅在 `banned_phrase` + `required_label`；LLM 模糊判断 = warning | 减少 P1 误报，确保可用 |
| 4 | Champion + 变体克隆 | 推迟到 P2 | P1 先打通单链路 |
| 5 | 前端测试框架 | Vitest 推迟到 P2 | 14d MVP 已饱和 |
| 6 | 多租户配额 | **P1 即建 `api_key_quotas` 表** | 避免未来迁移 |
| 7 | 数据回灌 | P3 同时支持手动 + CSV 批量 | 边际成本低 |
| 8 | URL 命名 | `/commerce/products`, `/commerce/projects` 显式 IA | 信息架构更清晰 |
| 9 | i18n 范围 | 仅新增的 commerce 页面；不动现有页面 | 与 AGENTS.md 现状一致 |
| 10 | Celery routing 修复 | 独立小 PR 放在 P1 之前 | 干净基线 |

---

## A. 数据模型设计

### A.1 枚举扩展 (`backend/app/models/types.py`)

```python
class ProjectKind(str, enum.Enum):
    DRAMA = "drama"                # 默认，向后兼容
    COMMERCE_STORY = "commerce_story"

class ProductCategory(str, enum.Enum):
    ELECTRONICS = "electronics"
    BEAUTY = "beauty"
    FOOD = "food"
    APPAREL = "apparel"
    HOME = "home"
    HEALTH = "health"               # 触发额外免责声明
    OTHER = "other"

class FormulaRegion(str, enum.Enum):
    CN = "cn"      # 中国市场公式（凡人逆袭等）
    GLOBAL = "global"  # 西方框架（Hero's Journey 等）

class ComplianceRegion(str, enum.Enum):
    CN_MAINLAND = "cn_mainland"
    HK_TW = "hk_tw"
    OVERSEAS = "overseas"

class ComplianceSeverity(str, enum.Enum):
    INFO = "info"
    WARNING = "warning"
    BLOCKER = "blocker"

class StoryVariantStatus(str, enum.Enum):
    DRAFT = "draft"
    GENERATING = "generating"
    READY = "ready"
    FAILED = "failed"

# 扩展现有枚举
class FileUsageKind(str, enum.Enum):
    # ... 现有 8 个值 ...
    PRODUCT_IMAGE = "product_image"          # 新增
    PRODUCT_HERO_SHOT = "product_hero_shot"  # 新增
    COMMERCE_REFERENCE = "commerce_reference" # 新增

class PromptCategory(str, enum.Enum):
    # ... 现有 21 个值 ...
    # 12 个新增：
    PRODUCT_EXTRACTION = "product_extraction"
    STORY_FORMULA_GENERATOR = "story_formula_generator"
    HOOK_PATTERN_WRITER = "hook_pattern_writer"
    CTA_PATTERN_WRITER = "cta_pattern_writer"
    ARCHETYPE_VOICE_REWRITER = "archetype_voice_rewriter"
    COMPLIANCE_CHECKER = "compliance_checker"
    PRODUCT_IMAGE_FRONT = "product_image_front"
    PRODUCT_IMAGE_OTHER = "product_image_other"
    PRODUCT_PLACEMENT_PROMPT = "product_placement_prompt"
    PRODUCT_HERO_PROMPT = "product_hero_prompt"
    AUDIENCE_INSIGHT = "audience_insight"
    BRAND_VOICE_PROFILE = "brand_voice_profile"
```

### A.2 新增模型 (4 个新文件)

#### `backend/app/models/commerce_assets.py`
```python
class Product(Base):
    """商品主体 — 镜像 Prop 结构，但语义为'故事中的主角'"""
    __tablename__ = "products"
    id: Mapped[str]                    # 主键
    name: Mapped[str]                  # 商品名（unique）
    brand: Mapped[str]
    category: Mapped[ProductCategory]
    description: Mapped[str]           # 卖点描述
    price_anchor: Mapped[float | None] # 锚定价
    sku: Mapped[str | None]
    selling_points: Mapped[list[str]]  # JSON 数组，最多 5 个
    pain_points_solved: Mapped[list[str]]  # JSON 数组
    target_audience: Mapped[dict]       # JSON: {age_range, gender, region_tier, pain_points}
    catchphrases: Mapped[list[str]]     # 金句台词
    competitor_names: Mapped[list[str]] # 禁止提及的竞品
    health_disclaimer_required: Mapped[bool] = False
    visual_style: Mapped[ProjectVisualStyle]
    style: Mapped[ProjectStyle]
    prompt_template_id: Mapped[str | None]
    created_at: Mapped[datetime]
    updated_at: Mapped[datetime]

class ProductImage(Base):
    """商品多角度图片 — 镜像 PropImage"""
    __tablename__ = "product_images"
    id: Mapped[int]
    product_id: Mapped[str]            # FK
    file_id: Mapped[str | None]
    quality_level: Mapped[QualityLevel]
    view_angle: Mapped[ViewAngle]      # front/back/side/detail/in_use
    is_primary: Mapped[bool] = False
    created_at: Mapped[datetime]
    # UNIQUE(product_id, quality_level, view_angle)

class ProjectProductLink(Base):
    """项目-商品多对多，scope 与现有 ProjectXxxLink 一致"""
    __tablename__ = "project_product_links"
    id: Mapped[int]
    project_id: Mapped[str]
    chapter_id: Mapped[str | None]
    shot_id: Mapped[str | None]
    product_id: Mapped[str]
    role_in_story: Mapped[ProductRoleInStory]  # 救星/催化剂/冲突源/彩蛋/主角伴侣
    appearance_timing: Mapped[ProductAppearanceTiming]  # opening/middle/climax/ending
    appearance_duration_sec: Mapped[int]
    # UNIQUE(product_id, project_id, chapter_id, shot_id)

class CommerceStoryConfig(Base):
    """剧情带货项目专属配置"""
    __tablename__ = "commerce_story_configs"
    project_id: Mapped[str]            # 主键 (1:1 with Project)
    target_platform: Mapped[Platform]  # douyin/kuaishou/xiaohongshu/youtube/tiktok
    target_duration_sec: Mapped[int]   # 30/45/60/90/180
    formula_id: Mapped[str | None]     # 选定的 StoryFormula
    archetype: Mapped[BrandArchetype]  # Hero/Sage/Caregiver/...
    tone_grid: Mapped[dict]            # JSON: {funny_serious, formal_casual, ...}
    audience_override: Mapped[dict | None]  # 覆盖 Product 默认受众
    compliance_region: Mapped[ComplianceRegion]
    compliance_profile_id: Mapped[str]
    target_kpi: Mapped[str | None]     # awareness/clicks/conversion
```

#### `backend/app/models/story_formula.py`
```python
class StoryFormula(Base):
    """剧情公式注册表 — 系统级模板，is_system=True"""
    __tablename__ = "story_formulas"
    id: Mapped[str]                    # 'underdog_triumph', 'heros_journey', ...
    name: Mapped[str]
    region: Mapped[FormulaRegion]
    category: Mapped[str]              # cn_viral / western_classic / modern_short
    structure: Mapped[dict]            # JSON: 完整 beat 定义
    risk_flags: Mapped[list[str]]      # 'family_conflict_compliance', 'requires_yanyi_label'
    sample_dialog: Mapped[str]         # 完整示例脚本
    typical_duration_sec: Mapped[int]
    typical_shot_count: Mapped[int]
    psychology: Mapped[str]            # 为什么有效
    use_cases: Mapped[list[str]]
    avoid_cases: Mapped[list[str]]
    prompt_template_id: Mapped[str]    # 关联的 PromptTemplate
    is_system: Mapped[bool] = True     # 系统模板不可删
    sort_order: Mapped[int]

class StoryVariant(Base):
    """脚本变体 — 同一项目下多个 A/B 版本"""
    __tablename__ = "story_variants"
    id: Mapped[str]
    project_id: Mapped[str]
    chapter_id: Mapped[str]
    formula_id: Mapped[str]
    hook_pattern_id: Mapped[str]
    cta_pattern_id: Mapped[str]
    archetype: Mapped[BrandArchetype]
    script_full_text: Mapped[str]      # 完整剧本
    script_breakdown: Mapped[dict]     # JSON: 镜头分解结果
    status: Mapped[StoryVariantStatus]
    is_champion: Mapped[bool] = False  # P2 加入
    compliance_score: Mapped[int]      # 0-100
    generated_by_task_id: Mapped[str | None]
    created_at: Mapped[datetime]
    updated_at: Mapped[datetime]

class StoryOutcome(Base):
    """脚本变体的效果数据 — P3 启用，P1 仅建表"""
    __tablename__ = "story_outcomes"
    id: Mapped[int]
    variant_id: Mapped[str]
    platform: Mapped[Platform]
    plays: Mapped[int]
    completion_rate_3s: Mapped[float | None]
    completion_rate_full: Mapped[float | None]
    interactions: Mapped[int]
    cart_clicks: Mapped[int]
    orders: Mapped[int]
    gmv: Mapped[float]
    notes: Mapped[str]
    raw_payload: Mapped[dict]          # 平台原始数据，未来 schema 兼容
    recorded_at: Mapped[datetime]
```

#### `backend/app/models/compliance.py`
```python
class ComplianceProfile(Base):
    """合规规则集 — 按地域分组"""
    __tablename__ = "compliance_profiles"
    id: Mapped[str]                    # 'cn_mainland_default', 'cn_mainland_health', 'overseas_default'
    name: Mapped[str]
    region: Mapped[ComplianceRegion]
    rules: Mapped[list[dict]]          # JSON: 规则数组
    is_system: Mapped[bool] = True
    created_at: Mapped[datetime]

class ComplianceFinding(Base):
    """合规检查发现的问题"""
    __tablename__ = "compliance_findings"
    id: Mapped[int]
    variant_id: Mapped[str]
    severity: Mapped[ComplianceSeverity]
    rule_id: Mapped[str]               # 触发的规则 ID
    rule_kind: Mapped[str]             # banned_phrase/required_label/required_disclaimer/brand_mention_cap
    description: Mapped[str]
    location: Mapped[str | None]       # 在脚本中的位置（如 "Shot 3, dialog line 2"）
    suggested_fix: Mapped[str | None]
    is_resolved: Mapped[bool] = False
    detected_at: Mapped[datetime]
```

#### `backend/app/models/api_quota.py` (P1 即建)
```python
class ApiKeyQuota(Base):
    """每个 API key 的配额 — P3 partner API 用"""
    __tablename__ = "api_key_quotas"
    api_key_hash: Mapped[str]           # 主键，bcrypt of API key
    daily_limit: Mapped[int] = 1000
    monthly_limit: Mapped[int] = 30000
    rate_per_minute: Mapped[int] = 60
    consumed_today: Mapped[int] = 0
    consumed_this_month: Mapped[int] = 0
    last_reset_daily: Mapped[date]
    last_reset_monthly: Mapped[date]
```

### A.3 迁移策略

使用已就位的 Alembic：

```
0002_add_project_kind.py            # ALTER projects ADD kind
0003_create_commerce_assets.py      # products + product_images + project_product_links + commerce_story_configs
0004_create_story_formulas.py       # story_formulas + story_variants + story_outcomes
0005_create_compliance.py           # compliance_profiles + compliance_findings
0006_extend_enums.py                # 扩展 file_usage_kind + prompt_category 枚举
0007_create_api_key_quotas.py       # api_key_quotas
```

并行写入 `backend/sql/010..016` 保留与 init_db.py 兼容。

### A.4 ER 关系图

```
Project (kind=commerce_story)
  ├── 1:1  CommerceStoryConfig
  ├── 1:N  Chapter ─── 1:N  Shot ─── 1:1  ShotDetail
  ├── M:N  Product (via ProjectProductLink, with role_in_story / appearance_timing)
  └── 1:N  StoryVariant (脚本 A/B 版本)
                ├── N:1  StoryFormula
                ├── 1:N  ComplianceFinding
                └── 1:N  StoryOutcome (P3)

Product
  ├── 1:N  ProductImage (multi-angle)
  └── M:N  Character (via CharacterProductLink, optional - endorsement)
```

---

## B. 故事生成引擎

### B.1 12 个新 Prompt 类别 (内置 PromptTemplate seed)

新建 `backend/app/services/studio/builtin_prompts.py`：

```python
def bootstrap_builtin_prompts(db: AsyncSession) -> None:
    """
    幂等启动函数 - 在 app.bootstrap 中调用。
    
    同时修复了现有 21 个类别没有 seed 的历史遗留问题。
    系统级模板 is_system=True，用户不可删除。
    """
```

每个 PromptTemplate 包含完整 jinja2 模板和变量定义：

| 类别 | 用途 | 主要变量 |
|------|------|---------|
| `product_extraction` | 从 URL/描述提取商品结构化信息 | `raw_text`, `target_fields` |
| `story_formula_generator` | 根据公式生成完整剧本 | `formula`, `product`, `audience`, `archetype`, `target_duration` |
| `hook_pattern_writer` | 生成前 3 秒钩子 | `pattern_id`, `product`, `audience` |
| `cta_pattern_writer` | 生成结尾转化语句 | `hardness`, `product`, `urgency_type` |
| `archetype_voice_rewriter` | 按品牌人格调整语气 | `archetype`, `tone_grid`, `script` |
| `compliance_checker` | LLM 二次合规检查 | `script`, `region`, `product_category` |
| `product_image_front` | 商品正面参考图 prompt | `product`, `style` |
| `product_image_other` | 商品其他角度 | `product`, `view_angle` |
| `product_placement_prompt` | 商品在镜头中自然出现的视觉 prompt | `product`, `scene`, `interaction` |
| `product_hero_prompt` | 商品高光时刻特写 | `product`, `dramatic_moment` |
| `audience_insight` | 受众洞察分析 | `product`, `target_audience` |
| `brand_voice_profile` | 品牌语调画像 | `archetype`, `tone_grid`, `competitor_voice` |

### B.2 6 个中国市场公式 + 6 个国际公式 (Phase 1: 6 cn / Phase 2: +6 global)

新建 `backend/app/services/commerce/builtin_story_formulas.py`：

```python
CN_FORMULAS = [
    {
        "id": "underdog_triumph",
        "name": "凡人逆袭",
        "region": "cn",
        "category": "cn_viral",
        "structure": {
            "beats": [
                {"id": "low_point", "duration_sec": 18, "function": "建立羞辱处境", "shot_type": "close_up"},
                {"id": "turning_point", "duration_sec": 12, "function": "产品/装备入场", "shot_type": "hand_object_face"},
                {"id": "triumph", "duration_sec": 30, "function": "反转 + 见证者", "shot_type": "wide_zoom"},
            ],
            "total_shots": "3-5",
            "duration_sec_range": [60, 90],
        },
        "risk_flags": ["requires_yanyi_label"],
        "psychology": "替代性满足 (vicarious satisfaction) - 85% 短剧主角是下沉市场用户",
        "use_cases": ["职场逆袭", "校园逆袭", "农村逆袭", "性别逆袭"],
        "avoid_cases": ["丑化原雇主/家庭成员"],
        "sample_dialog": "[完整60s脚本，变量化]",
    },
    # underdog_triumph, contrast_surprise, workplace_hero,
    # family_conflict (HIGH RISK), mystery_twist, time_travel
]

GLOBAL_FORMULAS = [  # P2
    "heros_journey", "pixar_story_spine", "three_act",
    "scqa", "storybrand_sb7", "pas_bab"
]
```

### B.3 钩子模式库 (10 patterns) + CTA 模式库 (5 patterns) + 12 品牌人格

P2 阶段加入 `builtin_hook_patterns.py`、`builtin_cta_patterns.py`、`builtin_archetypes.py`。

---

## C. 4 个新 AI Agent

每个 Agent 继承 `AgentBase[T]`，使用结构化 Pydantic 输出。

### C.1 ProductExtractorAgent
**位置**: `backend/app/chains/agents/commerce/product_extractor_agent.py`
**输入**: 商品页 URL 或粘贴文本
**输出 Pydantic**: `ProductExtractionResult` (完整商品 schema)
**用途**: 用户输入商品链接/描述 → 自动结构化为 Product 实体

### C.2 StoryFormulaSelectorAgent (P2)
**输入**: Product + 受众 + 平台 + 时长
**输出**: 推荐的 3 个 formula_id + 理由
**用途**: 当用户不知道选哪个公式时辅助决策

### C.3 StoryScriptGeneratorAgent
**位置**: `backend/app/chains/agents/commerce/story_script_generator_agent.py`
**输入**: formula + product + audience + archetype + tone_grid + duration
**输出 Pydantic**: `StoryScript` 包含 `shots[]` 数组（每个有 duration_sec、dialog、camera、product_focus_level、is_punchline、is_brand_mention）
**关键约束**: 总 duration_sec 误差 ≤10% target_duration_sec；商品出现 3 次（subtle / functional / hero）；品牌口播 ≤2 次/60s

### C.4 ComplianceCheckerAgent
**位置**: `backend/app/chains/agents/commerce/compliance_checker_agent.py`
**输入**: script + region + product_category
**输出 Pydantic**: `ComplianceReport` 包含 `findings[]` 数组（severity/rule_kind/description/location/suggested_fix）
**双引擎**: 规则引擎（精确匹配）+ LLM Agent（语义判断）合并结果

---

## D. 新任务类型 (Task Kinds)

| task_kind | 队列 | 超时 | 用途 | Phase |
|-----------|------|------|------|-------|
| `product_info_extract` | fast | 300s | 商品信息提取 | P1 |
| `story_script_generate` | fast | 600s | 单脚本生成 | P1 |
| `compliance_check` | fast | 180s | 合规扫描 | P1 |
| `story_video_batch_generate` | slow | 7200s | 批量 A/B 多版本生成 | P2 |

均通过 `register_task_adapter` 注册到 `core/tasks/registry.py`，executor 在 `services/worker/`。

---

## E. 后端 API 端点

```
# 商品 CRUD
GET    /api/v1/studio/products                  # 列表（分页+过滤）
POST   /api/v1/studio/products                  # 创建
GET    /api/v1/studio/products/{id}             # 详情
PATCH  /api/v1/studio/products/{id}             # 更新
DELETE /api/v1/studio/products/{id}             # 删除
POST   /api/v1/studio/products/{id}/images      # 上传角度图
DELETE /api/v1/studio/products/{id}/images/{img_id}

# 公式库（只读）
GET    /api/v1/studio/story-formulas            # 列表
GET    /api/v1/studio/story-formulas/{id}       # 详情

# 剧情项目
GET    /api/v1/studio/story-projects            # 列表（kind=commerce_story）
POST   /api/v1/studio/story-projects            # 创建（含 CommerceStoryConfig）
GET    /api/v1/studio/story-projects/{id}       # 详情
PATCH  /api/v1/studio/story-projects/{id}/config # 更新配置
POST   /api/v1/studio/story-projects/{id}/products/{product_id} # 关联商品
DELETE /api/v1/studio/story-projects/{id}/products/{product_id}

# 变体
GET    /api/v1/studio/story-variants?project_id=
POST   /api/v1/studio/story-variants            # 创建（手动）
PATCH  /api/v1/studio/story-variants/{id}/champion  # 标记冠军 (P2)

# 异步任务
POST   /api/v1/commerce/products/extract        # 商品提取（异步）
POST   /api/v1/commerce/script-generate         # 脚本生成（异步）
POST   /api/v1/commerce/compliance/check        # 合规检查（异步）
POST   /api/v1/commerce/story-batches           # 批量生成（异步, P2）

# 合规
GET    /api/v1/studio/compliance/profiles       # 列表
GET    /api/v1/studio/compliance/profiles/{id}
GET    /api/v1/studio/compliance/findings?variant_id=

# 效果数据 (P3)
POST   /api/v1/commerce/outcomes                # 录入
GET    /api/v1/commerce/outcomes?variant_id=    # 查询
POST   /api/v1/commerce/outcomes/import         # CSV 批量

# Partner API (P3)
POST   /api/v1/public/commerce/generate         # 第三方调用
GET    /api/v1/public/commerce/tasks/{id}
```

---

## F. 前端页面与流程

### F.1 商品库 `/commerce/products`
**模板**: 复制 `pages/aiStudio/assets/tabs/ActorsTab.tsx`
**关键组件**: `ProductCard`, `ProductFormModal`, `URLExtractModal`
**核心交互**:
- 卡片网格展示商品 + 主图 + 卖点
- "URL 提取" 模态：粘贴商品页链接 → 后台 ProductExtractorAgent → 自动填表
- 多角度图片上传

### F.2 剧情项目大厅 `/commerce/projects`
**模板**: 复制 `pages/aiStudio/project/ProjectLobby.tsx`
**过滤**: `kind=commerce_story`
**创建模态新增字段**: 目标平台、目标时长、合规地域、目标受众

### F.3 剧情工作台 `/commerce/projects/:id`
**全新页面**，整合：
- 顶部：商品配置面板（关联商品列表 + role/timing 配置）
- 左侧：FormulaPicker（公式选择，带预览）
- 中部：脚本编辑器（变体 Tab 切换）
- 右侧：ComplianceWarningBanner（实时风险）
- 底部：ShotTimeline（含商品出现标记）+ "生成视频"按钮

### F.4 公式库 `/commerce/formulas`
只读浏览，按 region/category 过滤，详情抽屉展示完整 beat 结构 + 示例 + use cases。

### F.5 合规中心 `/commerce/compliance`
- Tab 1: 规则配置（JSON 编辑器，schema 校验）
- Tab 2: 待处理 findings（按项目分组）
- Tab 3: 历史报告

### F.6 效果分析 `/commerce/analytics` (P3)
- KPI 卡片
- 4 个图表（按公式/钩子/人格/平台）
- 变体对比表
- CSV 导出

---

## G. 新前端组件

| 组件 | Props | Phase |
|------|-------|-------|
| `ProductCard` | `product, onClick, onEdit, onDelete` | P1 |
| `ProductFormModal` | `mode (create/edit), initial, onSubmit` | P1 |
| `URLExtractModal` | `onExtracted` | P1 |
| `FormulaPicker` | `value, onChange, region` | P1 |
| `ComplianceWarningBanner` | `findings, onDismiss` | P1 |
| `ScriptEditor` | `variant, readOnly, onChange` | P1 |
| `HookPatternSelector` | `value, onChange` | P2 |
| `ArchetypeVoiceSlider` | `archetype, toneGrid, onChange` | P2 |
| `BatchGenerationProgress` | `taskIds, onComplete` | P2 |
| `StoryShotTimelineWithProductMarkers` | `shots, products` | P2 |
| `OutcomeEntryModal` | `variantId, onSave` | P3 |
| `PerformanceChart` | `dimension, data` | P3 |

---

## H. 商业能力层

### H.1 合规系统 (P1 必备)

```python
class ComplianceRule(BaseModel):
    id: str
    kind: Literal['banned_phrase', 'required_label', 'required_disclaimer', 'brand_mention_cap']
    severity: ComplianceSeverity
    pattern: str | None       # 关键字/正则
    required_label: str | None  # "演绎" / "虚构"
    cap: int | None            # 出现次数上限
    suggested_fix: str
```

**P1 内置规则**:
1. `cn_yanyi_label` (BLOCKER) - 必须包含 "演绎/虚构" 标识
2. `cn_banned_maicai` (BLOCKER) - 禁止 "卖惨" 关键词族
3. `cn_banned_fake_credentials` (WARNING) - "悉尼大学Linda教授" 类伪造身份
4. `cn_banned_group_denigration` (WARNING) - 丑化群体
5. `cn_brand_mention_cap_60s` (WARNING) - 60s 内品牌口播 ≤2 次
6. `cn_health_disclaimer` (BLOCKER, 仅 ProductCategory.HEALTH) - "非医疗器械 仅辅助放松"
7. `cn_unverifiable_urgency` (WARNING) - "仅限xx天" 类不可验证宣称
8. `cn_fake_policy_claim` (BLOCKER) - "国补下线倒计时" 等

### H.2 A/B 变体（P2）
单脚本 → 同公式不同钩子 / 同钩子不同人格 / 不同公式同商品 一键生成 N 版本。

### H.3 效果追踪（P3）
手动 + CSV 录入；按公式 / 钩子 / 人格 / 平台维度聚合分析。

### H.4 品牌资产保护（P3）
`Product.competitor_names` 自动过滤；archetype + tone_grid 强制约束生成；品牌话术规范库。

---

## I. 集成与迁移策略

### I.1 共存方式
- 添加 `Project.kind` 枚举（默认 `drama` 保持向后兼容）
- 现有所有项目自动 backfill 为 `kind=drama`
- 章节/分镜/任务系统**完全复用**，不做分支
- 通过 `kind` 在前端路由和菜单中分流

### I.2 侧栏菜单重组
```
🎬 短剧创作 (kind=drama 入口)
   - 项目大厅
   - 资产库（角色/场景/道具/服装）
   
🛍️ 剧情带货 (kind=commerce_story 入口) ⬅️ 新增
   - 商品库
   - 剧情项目
   - 公式库
   - 合规中心
   - 效果分析 (P3)
   
🤖 模型管理
📁 文件管理
📝 提示词模板
🎨 Agent 管理
⚙️ 设置
```

### I.3 文档更新（per AGENTS.md）
- `site/content/docs/architecture/commerce-story-data-model.md` (P1 完成后)
- `site/content/docs/architecture/commerce-story-flow.md` (P2)
- `site/content/docs/architecture/commerce-story-compliance.md` (P2)
- `site/content/docs/guide/commerce-story-quickstart.md` (P1)
- `site/content/docs/plans/jellyfish-story-commerce.md` (本文件)
- `site/content/docs/reference/commerce-story-prompts.md` (P2 — 12 公式 + 10 钩子 + 12 人格目录)
- 每阶段 release note: `blog/v0-4-0.md` (P1) / `v0-5-0.md` (P2) / `v0-6-0.md` (P3)

---

## J. 阶段交付计划

### Phase 1 — MVP (~14 工作日)

**交付**:
- ✅ Product/ProductImage/ProjectProductLink/CommerceStoryConfig 模型 + 迁移
- ✅ StoryFormula/StoryVariant/StoryOutcome 模型
- ✅ ComplianceProfile/ComplianceFinding 模型
- ✅ ApiKeyQuota 表（预留）
- ✅ 12 个新 PromptCategory + seed 初始化器（含修复历史 21 个）
- ✅ 6 个中国市场公式 seed
- ✅ 8 条核心合规规则 + cn_mainland_default profile
- ✅ 3 个核心 Agent (Product/Script/Compliance)
- ✅ 3 个 task_kind 注册 + 执行器
- ✅ 完整 Products/StoryProjects/StoryVariants API
- ✅ ProductLibrary + StoryProjectLobby + StoryWorkbench 三个核心页面
- ✅ FormulaPicker + ComplianceWarningBanner + ScriptEditor 组件
- ✅ 侧栏菜单 commerce 分组

**验收标准**:
- 端到端：建项目 → 提取商品 → 选公式 → 生成脚本 → 合规检查 → 镜头落库
- `pnpm exec tsc --noEmit` 0 错误
- `pytest -q` 全绿
- drama 流程零回归
- 必备文档已更新

### Phase 2 — Production (~20 工作日)

**交付**:
- ✅ +6 个国际公式（Hero's Journey, Pixar, 3-Act, SCQA, SB7, PAS/BAB）
- ✅ HookWriter / CTAWriter / ArchetypeVoice 三个 Agent
- ✅ HookPatternSelector + ArchetypeVoiceSlider + CTASelector 组件
- ✅ 变体克隆 + 维度互换 + Champion 标记
- ✅ `cn_mainland_health` + `overseas_default` 合规 profile
- ✅ 合规中心独立页面（含规则编辑器）
- ✅ 公式库浏览页
- ✅ 批量生成 (story_video_batch_generate)
- ✅ ProductImage 接入图片任务流水线
- ✅ Vitest 前端测试基础（顺带解锁 jellyfish-improvements P3-2）
- ✅ commerce 命名空间 i18n 完整翻译
- ✅ Celery routing 修复

### Phase 3 — Scale (~30 工作日)

**交付**:
- ✅ StoryOutcome 完整启用 + 效果分析页
- ✅ 多平台导出预设（抖音/快手/小红书/YT/TikTok）
- ✅ Partner API + ApiKeyQuota 启用
- ✅ 品牌资产保险柜（competitor 过滤 / archetype 强制）
- ✅ 合规阻断 Slack/邮件通知
- ✅ CSV 批量导入效果数据

---

## K. Wave 执行图（Phase 1 详细）

```
═══════════════════════════════════════════════════════════════════
PHASE 1 — MVP (~14 工作日)
═══════════════════════════════════════════════════════════════════

PRE-WAVE (单独 PR, P1 之前) — 0.5d
  [PRE-T1] 修复 Celery task_routes globs (backend/app/core/celery_app.py)
           匹配 task.execute* 命名 (category=quick, deps=[])

Wave 1 (并行, 无依赖) — 1d
  [W1-T1] backend/app/models/types.py: 添加 7 个枚举 + 扩展 2 个
          (category=quick, effort=0.5d)
  [W1-T2] backend/app/core/contracts/story.py + 注册 barrel
          (category=quick, effort=0.5d)
  [W1-T3] notepad seeds (research/issues/decisions)
          (category=quick, effort=0.25d)
  [W1-T4] front/src/locales/{zh-CN,en-US}/commerce.json + i18n.ts wire
          (category=quick, effort=0.25d)

Wave 2 (并行, 依赖 W1) — 2d
  [W2-T1] Alembic 0002 + sql/010 + tests
          (category=unspecified-low, effort=0.5d, deps=[W1-T1])
  [W2-T2] commerce_assets.py 模型 + Alembic 0003 + sql/011 + tests
          (category=unspecified-high, effort=1d, deps=[W1-T1])
  [W2-T3] story_formula.py 模型 + Alembic 0004 + sql/012 + tests
          (category=unspecified-low, effort=0.75d, deps=[W1-T1])
  [W2-T4] compliance.py 模型 + Alembic 0005 + sql/013 + tests
          (category=unspecified-low, effort=0.5d, deps=[W1-T1])
  [W2-T5] api_quota.py 模型 + Alembic 0007 (预留)
          (category=quick, effort=0.25d, deps=[W1-T1])
  [W2-T6] Alembic 0006 枚举扩展
          (category=quick, effort=0.5d, deps=[W1-T1])

Wave 3 (并行, 依赖 W2) — 2d
  [W3-T1] builtin_prompts.py + bootstrap (12 新 + 6 现有未 seed) + tests
          (category=ultrabrain, effort=1d, deps=[W2-T2,W2-T6])
          ⚠️ 用 ultrabrain - prompt 质量决定一切
  [W3-T2] builtin_story_formulas.py (6 cn formulas) + tests
          (category=ultrabrain, effort=1d, deps=[W2-T3])
  [W3-T3] compliance/rule_engine.py + 8 条规则 + cn_mainland_default + tests
          (category=ultrabrain, effort=1.5d, deps=[W2-T4])

Wave 4 (并行, 依赖 W3) — 1.5d
  [W4-T1] chains/agents/commerce/product_extractor_agent.py + tests
          (category=unspecified-high, effort=0.75d, deps=[W3-T1])
  [W4-T2] chains/agents/commerce/story_script_generator_agent.py + tests
          (category=ultrabrain, effort=1d, deps=[W3-T1,W3-T2])
  [W4-T3] chains/agents/commerce/compliance_checker_agent.py + tests
          (category=unspecified-high, effort=0.75d, deps=[W3-T1,W3-T3])

Wave 5 (并行, 依赖 W4) — 1.5d
  [W5-T1] services/commerce/product_info_extract_worker.py + 注册
          (category=unspecified-low, effort=0.5d, deps=[W4-T1])
  [W5-T2] services/commerce/story_script_generate_worker.py + 注册
          (category=unspecified-high, effort=1d, deps=[W4-T2,W2-T2])
  [W5-T3] services/commerce/compliance_check_worker.py + 注册
          (category=unspecified-low, effort=0.5d, deps=[W4-T3,W3-T3])

Wave 6 (并行, 依赖 W5) — 2d
  [W6-T1] api/v1/routes/studio/products.py + service + tests
          (category=unspecified-low, effort=0.75d, deps=[W2-T2])
  [W6-T2] api/v1/routes/studio/{story_formulas,story_projects,story_variants}.py
          + services + tests
          (category=unspecified-low, effort=1d, deps=[W2-T2,W2-T3])
  [W6-T3] api/v1/routes/commerce/{product_extract,script_generate,compliance}.py
          + tests (任务入队端点)
          (category=unspecified-low, effort=0.5d, deps=[W5-T1,W5-T2,W5-T3])

Wave 7 (顺序, 依赖 W6) — 0.5d
  [W7-T1] front/: pnpm run openapi:update; 单独 chore(openapi) 提交
          (category=quick, skills=[git-master], effort=0.25d)
  [W7-T2] backend 验证: pytest + pylint
          (category=quick, effort=0.25d)

Wave 8 (并行, 依赖 W7) — 4.5d
  [W8-T1] front/src/pages/aiStudio/commerce/products/ProductLibrary.tsx
          + queries.ts + ProductCard + ProductFormModal + URLExtractModal
          (category=visual-engineering, skills=[frontend-design,ui-ux-pro-max],
           effort=1.5d, deps=[W7-T1])
  [W8-T2] front/src/pages/aiStudio/commerce/projects/StoryProjectLobby.tsx
          (category=visual-engineering, skills=[frontend-design],
           effort=0.75d, deps=[W7-T1])
  [W8-T3] front/src/pages/aiStudio/commerce/projects/StoryWorkbench.tsx
          + FormulaPicker + ComplianceWarningBanner + ScriptEditor (read-only)
          (category=visual-engineering, skills=[frontend-design,ui-ux-pro-max],
           effort=2d, deps=[W7-T1])
  [W8-T4] MainLayout.tsx 三处更新（菜单/selectedKeys/breadcrumb）
          (category=quick, effort=0.25d, deps=[])

Wave 9 (并行, 依赖 W8) — 1d
  [W9-T1] tsc --noEmit 全仓清洁
          (category=quick, effort=0.25d)
  [W9-T2] E2E 烟雾: 创建项目→提取商品→生成脚本→合规检查
          (category=quick, effort=0.5d)
  [W9-T3] drama 回归: 旧项目流程零变化
          (category=quick, effort=0.25d)

Wave 10 (并行, 依赖 W9) — 1d
  [W10-T1] docs/architecture/commerce-story-data-model.md
          (category=writing, effort=0.5d)
  [W10-T2] docs/guide/commerce-story-quickstart.md
          (category=writing, effort=0.25d)
  [W10-T3] docs/plans/jellyfish-story-commerce.md (本文件迁出 P1, 仅留 P2/P3)
          (category=writing, effort=0.25d)
  [W10-T4] blog/v0-4-0.md release note
          (category=writing, effort=0.5d)

═══════════════════════════════════════════════════════════════════
P1 总计：14 个工作日（最长关键路径）
═══════════════════════════════════════════════════════════════════
```

**Phase 2 / Phase 3 详细 Wave 图**：进入相应阶段时由 Plan Agent 重新生成（因为 P1 实际产出会影响后续依赖）。

---

## L. TDD + 提交规范

### L.1 提交粒度
- 每个 Task 一个 PR，按需拆为多个 atomic commit
- `test → feat → refactor → docs` 顺序
- `chore(openapi)` 永远独立提交
- 每个 commit < 400 行（除 OpenAPI 自动生成）
- 每个 commit 独立可编译可测试（bisect-friendly）

### L.2 测试分层
| 层 | 框架 | 命名 | 位置 |
|---|---|---|---|
| 后端 service | pytest + pytest-asyncio | `test_commerce_<feature>_service.py` | `backend/tests/services/` |
| 后端 API | TestClient | `test_commerce_<feature>_api.py` | `backend/tests/` |
| 后端 Agent | mock chat model | `test_<agent>_agent.py` | `backend/tests/services/` |
| 后端规则引擎 | data-driven | `test_compliance_rule_engine.py` | `backend/tests/services/` |
| 后端迁移 | sqlite memory | `test_migration_<rev>.py` | `backend/tests/` |
| 后端 prompt 渲染 | snapshot | `test_builtin_prompts_render.py` | `backend/tests/` |
| 前端类型 | tsc --noEmit | n/a | 全仓 |
| 前端行为 (P2+) | Vitest + RTL | `<Component>.test.tsx` | colocated |
| E2E (P3+) | Playwright | `commerce.spec.ts` | `front/e2e/` |

---

## M. 风险登记

| ID | 风险 | 缓解 |
|----|------|------|
| R1 | LLM 输出 JSON drift（长脚本） | 限制 `target_duration_sec ≤ 180`；用 `with_structured_output`；JSON 修复链 |
| R2 | Jinja2 变量不匹配 | `StoryGenerationVars` Pydantic schema 在 service 边界强制；12 类别 golden 测试 |
| R3 | 合规误报淹没 UI | P1 blocker 仅 banned_phrase + required_label；其余 warning |
| R4 | 前端 store 不一致 | 所有新 commerce queries 走 TanStack queries.ts；不再加 services/ 包装 |
| R5 | Alembic baseline 切换 | 文档说明 `alembic stamp head`；release note 写清升级步骤 |
| R6 | 批量生成成本飙升 | parallelism≤2 默认 + 租户级配额 |
| R7 | Celery routing pre-existing bug | 独立 PRE-WAVE 修复 |
| R8 | 合规规则演变 | rules 字段为 JSON，profile 易扩展，不需改表 |
| R9 | Partner API 滥用 | slowapi 限流 + ApiKeyQuota 表（P1 即建） |
| R10 | 平台数据格式变 | StoryOutcome 加 `raw_payload JSON` 容忍未来 schema |

---

## N. 完成标准 (per AGENTS.md DoD)

每个 Phase 收官必须：
1. ✅ 代码实现：功能落地、无 TODO 占位、必要注释齐全
2. ✅ 接口/类型：`pnpm run openapi:update` 已跑、generated types 已同步
3. ✅ 文档：架构文档反映当前实现、计划文档反映剩余工作、release note 已写
4. ✅ 页面职责：分镜编辑页/工作室定位不被破坏；新增 commerce 分组独立
5. ✅ 验证：tsc --noEmit 通过、pytest 通过、关键路径手动 QA
6. ✅ 汇报：明确改了什么/验证结果/未完成项

---

## O. Final TODO (Phase 1 — drop-into todowrite)

完整 33 项任务详见 P1 Wave 图。每条 TODO 格式遵循 `[文件路径/范围]: 动作 - expect [验证标准]`。
