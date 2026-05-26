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

## Phase 3 — Visual Production Layer（约 22 工作日）

### P3 总目标

把"剧本 → 真实可发布带货成片"的视听执行层补齐：

- **商品视觉一致性**：剧本里 `product_focus_level ∈ {hero, functional, subtle}` 的镜头，画面里出现的商品必须与项目挂载的 `ProductImage` 真实视觉一致；通过阿里 `happyhorse-1.0-r2v`（多图参考生视频，1–9 张）+ 多角度 `ProductImage` 自动绑定实现。`focus_level=none` 镜头继续走 `t2v`。
- **音频一等公民**：视频画面与音频解耦——`happyhorse` 出无声画面，DashScope `CosyVoice` TTS 合成精确剧本台词，`ffmpeg` 替换原音轨。声纹按 `Character.voice_pack_id` / `StoryVariant.narration_voice_pack_id` 跨镜头保持一致。
- **字幕一等公民**：默认硬烧 ASS 字幕（保留 ASS 源文件作为 derivative），支持抖音 / TikTok / Reels 三套平台模板，逐词高亮 (`\k` / `\kf`)；时间戳由 TTS 输出 word-level alignment 直接给，不依赖 ASR 反推。
- **章节 AV 合成**：新 `chapter_av_export` task_kind 替代当前 `chapter_timeline_export` 的"裸视频拼接"，支持视频 + TTS 音频 + 字幕 + 响度归一化（`loudnorm I=-16:TP=-1.5:LRA=11`）一次合成。老接口标 deprecated 并保留至 v0.7.0。
- **多语言准备**：voice_pack 加 `language_code`、subtitle_style 加 `font_fallback_chain`，schema 一次到位避免出海二次迁移；具体英 / 日 / 韩内置音色与字幕模板的接入推迟到 P5。
- **跨帧/跨镜一致性引擎（DINOv2 / CLIP）推迟到 P4**，本阶段不做硬性视觉一致性检查。

### P3 关键架构决策

| 决策 | 内容 | 来源 |
| ---- | ---- | ---- |
| A | `happyhorse-1.0-t2v/i2v/r2v` 自带音轨**一律丢弃**：模型不接受指定台词文本、跨镜音色漂移、机械感明显，违反"剧本即真相"契约 | Oracle 评审 + 阿里官方 API 文档（无音频参数）+ 36kr 实测 |
| B | 完全不做 lip-sync：带货短剧 90% 镜头演员不张嘴或不出现，旁白驱动 + 大字幕是工业默认 | tkfff 2026 攻略 + 字节小云雀官方建议 |
| C | `r2v` **不拆 task_kind**：扩 `video_generation` 内部分支，按 capability（非 model name 字符串）走 `multi_ref` 路径 | explore agent 改动面分析 |
| D | `Shot.audio_strategy: silent_with_tts \| keep_native`：默认 `silent_with_tts`，给极个别需要原音的镜头逃生口，**默认不开** | Oracle 修正项 |
| E | 字幕默认 **hardsub + ASS 源文件存档**：抖音 / TikTok 算法对外挂字幕减分，但 ASS 源文件必须独立保留以便后续换语言 / 换字号免重生整段视频 | 路由通 2026 + Blitzcut |
| F | `chapter_av_planner`（W17 内嵌子任务）：TTS 合成前先估时长（CosyVoice ≈ 3 字 / 秒），mismatch > 15% 回灌 LLM 改剧本；LLM prompt 一并加 "本镜头 N 秒，旁白 ≤ 3·N 个汉字" 硬约束 | Oracle 评审最被低估的硬骨头 |
| G | 9 槽 `ReferenceImageBudget`：Product 3–5 / Character 2–3 / Scene 1–2，超出按优先级丢弃并 warning | Oracle 修正项 |
| H | `product_focus_level` → `view_angle` 用**优先级序列**而非 1:1：hero=`[FRONT,THREE_QUARTER,DETAIL]` / functional=`[DETAIL,THREE_QUARTER,FRONT]` / subtle=`[THREE_QUARTER,FRONT]` | Oracle 修正项 |

### P3 Wave 16 — r2v 多图参考 + ProductImage 自动绑定（约 4 工作日）

| 任务 ID | 内容                                                                                                                                                                                          |
| ------- | --------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| T16-1   | 新建 `backend/app/core/integrations/aliyun/video_capabilities.py`：声明 happyhorse-1.0-t2v/i2v/r2v 三个模型的 `max_reference_images`（1/1/9）、`supports_r2v`、`supported_reference_modes` |
| T16-2   | `core/integrations/video_capabilities.py:66-73` 重构：`resolve_video_capability` 加 `aliyun_bailian` 分支，结束 fallback 到 volcengine；`VideoModelCapability` 加 r2v 三字段                  |
| T16-3   | `core/contracts/video_generation.py`：`VideoGenerationInput` 加 `reference_images_base64: list[str] \| None`；`require_prompt_or_any_reference` validator 接受新字段                            |
| T16-4   | `core/integrations/aliyun/dashscope_videos.py`：`_dashscope_video_mode` 识别 r2v / multi_ref；`_build_dashscope_video_body` 在 multi_ref 模式发 `input.media: [{type:reference_image,url:...}]` |
| T16-5   | `services/studio/generation/video/build_context.py`：`REQUIRED_FRAMES_BY_MODE` 加 `multi_ref`，与 first / last / key 解耦；新建 `ShotProductReferenceResolver`（按 `product_focus_level` 优先级序列选 ProductImage）|
| T16-6   | 新建 `services/studio/reference_image_budget.py`：`ReferenceImageBudget` 类管 9 槽分配，`apply(shot, products, characters, scenes)` 按优先级丢弃并写 task warning                              |
| T16-7   | `api/v1/routes/film/video_request.py`：`reference_mode` Literal 加 `multi_ref`；`images: list[str]` 数量上限按 capability 动态校验；`Shot` 模型加 `audio_strategy` 字段（默认 silent_with_tts）|
| T16-8   | alembic `0008_p3_r2v_audio_strategy.py`：`shots` 加 `audio_strategy: VARCHAR(32)`；无新表                                                                                                       |
| T16-9   | `services/film/generated_video.py:165-224` `build_run_args`：multi_ref 分支跳过 frame_map，把 `images: list[file_id]` 全部读成 b64 数组；i2v / t2v 路径不变                                    |
| T16-10  | pytest 新增：r2v 单元测试（mock dashscope 验证 body schema、ReferenceImageBudget 优先级丢弃、ShotProductReferenceResolver 优先级序列降级）                                                    |
| T16-11  | `pnpm run openapi:update`；前端 generated types 同步                                                                                                                                          |
| T16-12  | manual QA：用 P1+P2 已建项目跑一遍真实 r2v（hero 镜头 multi_ref 取 3 张 ProductImage），验证产出 mp4 商品与参考图视觉一致                                                                       |

### P3 Wave 17 — TTS 与音色管理 + chapter_av_planner（约 5 工作日）

| 任务 ID | 内容                                                                                                                                                                                                       |
| ------- | ---------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| T17-1   | 新建 `models/voice_pack.py`：`VoicePack(id, name, provider, provider_voice_id, language_code, gender, archetype_hint, sample_file_id, is_system)`；`tts_cache(hash, file_id, created_at)`                  |
| T17-2   | `models/types.py`：新增 `TtsClipStatus` (pending/generating/ready/failed)；`FileUsageKind` 加 `tts_audio` / `bgm_track` / `sfx_track`                                                                       |
| T17-3   | alembic `0009_p3_voice_pack_tts.py`：`voice_packs` 表 + `tts_cache` 表 + `Character.voice_pack_id` (FK) + `StoryVariant.voice_pack_id` / `narration_voice_pack_id` + `ShotDialogLine.start_time_ms / end_time_ms / tts_voice_id / tts_audio_file_id` |
| T17-4   | `services/studio/builtin_voice_packs.py`：bootstrap 内置 6 个 CosyVoice 音色（zh-CN：中性 / 男 / 女 / 少年 / 中年 / 老者），首次启动幂等 seed                                                              |
| T17-5   | 新建 `services/studio/tts_generate_worker.py`：`tts_generate` task_kind（fast queue），输入 (text, voice_pack_id, speed)，输出 (audio_file_id, word_timestamps[])；按 hash 命中 `tts_cache` 直接返回       |
| T17-6   | DashScope CosyVoice provider adapter：`core/integrations/aliyun/dashscope_tts.py`，调 `audio/tts/long-text`，输出 word-level alignment；失败 fallback 到 `paraformer-v2` 反推时间戳                       |
| T17-7   | **W17 关键路径** 新建 `services/studio/chapter_av_planner.py`：TTS 合成前对每段 `(dialog/narration, voice_pack)` 估时长（按 voice_pack 默认语速）；mismatch > 15% 决策树：speed 0.95–1.15 微调 → 失败回灌 LLM 改剧本（缩字）→ 再失败 hold 等用户介入 |
| T17-8   | LLM prompt 升级：`builtin_prompts.py` `_STORY_FORMULA_GENERATOR` 增加 "本镜头 {{ duration_sec }} 秒，dialog/narration 字符总数 ≤ 3 × duration_sec" 硬约束；snapshot 测试更新                          |
| T17-9   | `commerce/task_dispatch.py`：`enqueue_tts_generate` + `enqueue_chapter_av_plan`（slow queue）                                                                                                                |
| T17-10  | pytest 新增：tts_cache hash 命中、chapter_av_planner duration 决策、CosyVoice provider mock                                                                                                                  |
| T17-11  | `pnpm run openapi:update`；前端 generated types 同步                                                                                                                                                       |
| T17-12  | manual QA：champion 变体 1 跑完整 TTS 配音（6 镜头 ≈ 60s），验证音色跨镜头一致 + ShotDialogLine.tts_audio_file_id 全部落库                                                                                |

### P3 Wave 18 — 字幕引擎（约 3 工作日）

| 任务 ID | 内容                                                                                                                                                                                          |
| ------- | --------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| T18-1   | 新建 `models/subtitle.py`：`SubtitleStyle(id, name, font_family, font_size, primary_color, outline_color, position, margin_v, font_fallback_chain JSON, is_system)`；`SubtitleTrack(id, shot_id, language, format, file_id, style_id, source)` |
| T18-2   | `models/types.py`：新增 `SubtitleFormat` (srt/ass/vtt) / `SubtitleSource` (manual/from_dialog/from_asr)                                                                                       |
| T18-3   | alembic `0010_p3_subtitle.py`：`subtitle_styles` 表 + `subtitle_tracks` 表 + `shots.subtitle_track_file_id` + `StoryVariant.subtitle_style_id`                                                |
| T18-4   | `services/studio/builtin_subtitle_styles.py`：bootstrap 内置 3 个平台模板（DOUYIN_DEFAULT 字号 80 / 黑描边 / MarginV=300、TIKTOK_VIRAL Bold + 黄高亮 + ASS karaoke、REELS_LOWER_THIRD 字号 60）|
| T18-5   | 新建 `services/studio/shot_subtitle_render.py`：`shot_subtitle_render` task_kind，输入 ShotDialogLine 列表 + 风格 ID，输出 `.ass` 文件落 minio；ASS 模板支持 `\k` / `\kf` 逐词高亮            |
| T18-6   | 安全区 lint：渲染前用 `services/studio/subtitle_safe_zone.py` 检查（抖音底部 ≥ 250–300px / TikTok 左右 ≥ 120px / WCAG 对比度 ≥ 4.5:1），违规返回 warning                                       |
| T18-7   | 句子切分策略：单句 ≤ 15 字（中文）/ 单屏 ≤ 2 行 / 停留 1.8–3.0s / 4–7 cps；超出按标点重切                                                                                                       |
| T18-8   | pytest 快照测试：3 个内置 SubtitleStyle × 5 段示例 dialog → ASS 输出 snapshot；安全区 lint 单测（含违规用例）                                                                                  |
| T18-9   | `pnpm run openapi:update`                                                                                                                                                                     |

### P3 Wave 19 — AV 合成升级（约 3 工作日）

| 任务 ID | 内容                                                                                                                                                                                                                  |
| ------- | --------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| T19-1   | 新建 `services/studio/chapter_av_export_task.py`：`chapter_av_export` task_kind（slow queue, 1800s 超时）；老 `chapter_timeline_export` 标 `@deprecated` 在 OpenAPI 描述（保留至 v0.7.0）                                |
| T19-2   | `models/types.py`：`FileUsageKind` 加 `chapter_master_audio` / `chapter_master_subtitle` / `chapter_master_dubbed`；新枚举 `AudioMixMode` (off/voice_only/voice_bgm/full)                                                |
| T19-3   | alembic `0011_p3_av_export.py`：`shots.dubbed_video_file_id`；`ChapterTimelineSegment` 加 `subtitle_track_file_id` / `tts_audio_file_id`                                                                                |
| T19-4   | ffmpeg filter_complex 改造：每 segment trim 后挂 `subtitles=...ass` filter（默认硬烧）；音频流 `amix` 合并 TTS + 可选 BGM；输出阶段 `loudnorm=I=-16:TP=-1.5:LRA=11` 跨段响度归一化                                       |
| T19-5   | 默认 hardsub + ASS 源文件 derivative：硬烧 mp4 落 `chapter_master_dubbed`，原始 .ass 单独落 `chapter_master_subtitle`，前端可选只下载字幕源文件做后期编辑                                                                |
| T19-6   | r2v 失败 fallback 策略：3 次失败后降级 t2v 并写 warning 到 task metadata，前端 task center 可见；可通过 `commerce_settings.r2v_failure_policy` 切换为 hold（人工介入）                                                  |
| T19-7   | pytest 新增：filter_complex 拼接 / loudnorm 归一化 / hardsub vs softsub 切换 / r2v 失败 fallback                                                                                                                       |
| T19-8   | manual QA：champion 变体 1 跑完整 chapter_av_export（含字幕 + 音频 + 响度归一化），验证产出与 P1+P2 真实测试一致 + 字幕逐词高亮在抖音 9:16 安全区内                                                                     |

### P3 Wave 20 — 前端工作室升级（约 4 工作日）

| 任务 ID | 内容                                                                                                                                                                                                          |
| ------- | ------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| T20-1   | 多角度 ProductImage 上传 / 选择 UI：`front/src/pages/aiStudio/commerce/products/ProductImageGrid.tsx`，按 7 种 view_angle 分组，支持每角度 LOW/MEDIUM/HIGH/ULTRA 四档质量                                       |
| T20-2   | `VoicePackPicker` 组件：列出可用 VoicePack（按 language_code 过滤），点击试听 sample；放在 StoryWorkbench 右侧抽屉                                                                                              |
| T20-3   | `SubtitleStylePicker` 组件：3 个内置预览 + 自定义编辑（字号 / 颜色 / 描边 / 位置）                                                                                                                              |
| T20-4   | StoryWorkbench AV 预览：当 `dubbed_video_file_id` 存在时优先播放有字幕版本，否则显示"等待 chapter_av_export"提示 + 触发按钮                                                                                     |
| T20-5   | 新页面 `/commerce/voice-packs`：音色包管理（系统级只读 + 用户上传 sample_file 训练定制音色入口，定制实现可推迟）                                                                                                |
| T20-6   | 新页面 `/commerce/subtitle-styles`：字幕样式管理（3 个内置只读 + 项目级覆盖）                                                                                                                                  |
| T20-7   | MainLayout 菜单 + i18n 翻译（commerce 命名空间硬编码 zh-CN，与 P1+P2 D4 决策一致）                                                                                                                              |
| T20-8   | 新增 Vitest 单测覆盖 ProductImageGrid / VoicePackPicker / SubtitleStylePicker（每个组件 ≥ 5 用例）                                                                                                              |
| T20-9   | `pnpm exec tsc --noEmit` 通过；`pnpm run openapi:update` 通过                                                                                                                                                   |

### P3 Wave 21 — 集成与发布 v0.6.0（约 3 工作日）

| 任务 ID | 内容                                                                                                                                                                                                                                                  |
| ------- | ----------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| T21-1   | 端到端 E2E：从空 DB → 多角度商品图 → r2v 视频生成 → TTS 配音 → 字幕渲染 → chapter_av_export → 真实 mp4（含字幕 + 配音 + 响度归一化）；脚本落 `backend/scripts/p3_e2e_smoke.py`                                                                          |
| T21-2   | regression：跑全量 pytest（`-k commerce or story or compliance or product or builtin_prompts or shot or chapter`）+ Vitest 全绿；确认 P1+P2 + drama 流程零回归                                                                                          |
| T21-3   | `site/content/docs/architecture/commerce-story-data-model.md` 同步：新增 "Visual Production Layer" 章节（VoicePack / SubtitleStyle / SubtitleTrack / 多图 r2v / chapter_av_export pipeline），下移已落地的 W16-W21 内容                              |
| T21-4   | `site/content/docs/guide/`：新增 `voice-pack-setup.md` / `subtitle-style-config.md` / `r2v-multi-reference.md` 三篇 how-to                                                                                                                              |
| T21-5   | `site/content/blog/v0-6-0.md` release note：Highlights / Added / Changed / Migration Guide / Compatibility Matrix / Validation Commands                                                                                                                |
| T21-6   | `pnpm run openapi:update` 终态校验；删除已落地的 W16-W21 任务表                                                                                                                                                                                          |

### P3 风险登记

- **R-P3-1**：`happyhorse-1.0-r2v` 生产配额限制（默认 RPS=20）+ 单价（720P 0.9 元 / 秒；1080P 1.6 元 / 秒）。
  - 缓解：前端在批量入队前显式预估总成本并提示；项目级 `r2v_quota_per_day` 配置；超出回退 i2v 单图首帧。
- **R-P3-2**：CosyVoice TTS 跨 shot 音色"理论一致"但实际有 5–10% 漂移（CosyVoice 已知问题）。
  - 缓解：声纹监测脚本（W19 加 ffmpeg `astats` 比较 RMS / spectral centroid），漂移 > 阈值时 warning；推迟到 P4 加 voice_clone 走"reference_voice"路径。
- **R-P3-3**：chapter_av_planner duration 估算误差累积导致 mismatch > 15% 频繁触发 LLM 回灌。
  - 缓解：CosyVoice 长文本 TTS 提供"预估时长"接口（不真合成）；prompt 端字数硬约束兜底；连续回灌 ≥ 3 次降级到 padding silence + 警告（而非无限循环）。
- **R-P3-4**：硬烧字幕后想换语言要重生整段视频，研发期高频迭代字幕样式成本高。
  - 缓解：v0.6.0 上线后**默认硬烧 + ASS 源文件保留**；StoryWorkbench 内 "字幕样式预览" 在 hardsub 之前用 HTML5 video + WebVTT 实时叠加，迭代时不调 chapter_av_export。
- **R-P3-5**：`AbstractAsyncDelegatingExecutor.run()` 成功路径不写状态的潜在 bug 在新 task_kind（tts_generate / shot_subtitle_render / chapter_av_export）会重现。
  - 缓解：所有新 worker 强制套用 `set_status(running) → set_result(payload) → set_status(succeeded) + commit` 模板（参照 hotfix 4 修过的 product_info_extract_worker）；统一抽出 `services/worker/async_status_helper.py` 装饰器避免漏写。

### P3 完成标准

- 单一项目从空 DB 到真实带货成片（含字幕 + 配音 + 响度归一化）≤ 8 分钟（不含 LLM 排队），用 `backend/scripts/p3_e2e_smoke.py` 一键复现
- `product_focus_level=hero/functional/subtle` 的镜头自动绑 ProductImage 走 r2v；DINOv2 一致性人工抽检（采用 P4 工具，本阶段不做硬性门）≥ 0.85 cosine 相似度
- `Character.voice_pack_id` 跨 chapter 同一项目内声纹一致；narration 走 `StoryVariant.narration_voice_pack_id`
- 3 个内置字幕模板（抖音 / TikTok / Reels）全部通过安全区 lint；ASS karaoke 逐词高亮在抖音 9:16 视频上目视无问题
- `chapter_av_export` 成片响度落在 -15 ~ -17 LUFS（移动端标准 ±1）
- `pnpm exec tsc --noEmit` 通过；`pytest -q` 全绿；新增至少 40 个后端单测 + 20 个前端 Vitest 单测
- drama 流程零回归
- `architecture/commerce-story-data-model.md` 同步完毕；`blog/v0-6-0.md` release note 上线

---

## Phase 4 — Scale（约 30 工作日）

> 原 P3 内容（效果数据 / 多平台导出 / Partner API / 品牌资产保险柜 / 合规告警）整体平移至 P4，与 Visual Production Layer（P3）解耦，等 P3 落地后再启动。

### P4 总目标

商业化 + 数据驱动 + 第三方开放：

- 真实投放数据回灌驱动归因分析
- 多平台导出预设
- Partner API（第三方 SaaS 调用）
- 品牌资产保险柜
- 合规阻断告警通知
- 跨帧 / 跨镜视觉一致性引擎（DINOv2 / CLIP，从 P3 推迟过来）

### P4 Wave 22 — Outcome + Analytics（约 8 工作日）

| 任务 ID | 内容                                                                                              |
| ------- | ------------------------------------------------------------------------------------------------- |
| T22-1   | `StoryOutcome` 录入 API + 前端表单（手动录入完播率 / 互动率 / 加购 / 订单 / GMV）                 |
| T22-2   | CSV 批量导入端点（`POST /api/v1/commerce/outcomes/import`，支持抖音 / 小红书原始字段映射）        |
| T22-3   | 4 个分析图表（按公式 / 钩子 / 人格 / 平台 4 个维度归因），使用统一 `PerformanceChart` 组件        |
| T22-4   | KPI 卡片（GMV / ROI / 完播率 / 加购率） + 变体对比表                                              |
| 路由    | `/commerce/analytics`                                                                             |

### P4 Wave 23 — Multi-Platform Export（约 5 工作日）

| 任务 ID | 内容                                                                                                                                                          |
| ------- | ------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| T23-1   | 5 个平台预设（抖音 / 快手 / 小红书 / YouTube Shorts / TikTok），覆盖尺寸（9:16 / 1:1 / 16:9）/ 时长上限 / 字幕规则 / 结尾水印 / 平台特定贴纸                   |
| T23-2   | 导出任务：`task_kind = commerce_export`，slow queue，输出落到 `FileUsageKind.PRODUCT_EXPORT`                                                                  |

### P4 Wave 24 — Partner API（约 8 工作日）

| 任务 ID | 内容                                                                                                                  |
| ------- | --------------------------------------------------------------------------------------------------------------------- |
| T24-1   | `ApiKeyQuota` 启用 + bcrypt 哈希存储 + API key 中间件（注入 quota 上下文）                                            |
| T24-2   | `POST /api/v1/public/commerce/generate` 第三方调用 endpoint（同步入队 + 返回 task_id）                                |
| T24-3   | `GET /api/v1/public/commerce/tasks/{id}` 状态查询                                                                     |
| T24-4   | `slowapi` 限流集成（`rate_per_minute` 字段生效） + 配额日 / 月重置 Celery beat 任务                                   |
| T24-5   | Admin UI 创建 / 撤销 API key（`/settings/api-keys`），含日 / 月配额配置 + 用量统计                                    |

### P4 Wave 25 — Brand Asset Vault（约 5 工作日）

| 任务 ID | 内容                                                                                                          |
| ------- | ------------------------------------------------------------------------------------------------------------- |
| T25-1   | `Product.competitor_names` 自动过滤管线（生成阶段 reject + suggest fix）                                      |
| T25-2   | `archetype` + `tone_grid` 强制约束（违反则在生成阶段 reject 并要求重写，不进入 variant 表）                   |
| T25-3   | 品牌话术规范库 `BrandStyleGuide` 表（强制金句 / 禁用句式 / 必备结尾 / 品牌人格短描述）                        |

### P4 Wave 26 — Compliance Notifications（约 4 工作日）

| 任务 ID | 内容                                                                                          |
| ------- | --------------------------------------------------------------------------------------------- |
| T26-1   | Slack / 邮件 webhook 合规阻断告警（BLOCKER 级 finding 触发）                                  |
| T26-2   | 团队级 escalation rules（连续 N 次阻断 → 升级到团队 owner）                                   |

### P4 Wave 27 — Visual Consistency Engine（约 4 工作日）

| 任务 ID | 内容                                                                                                                                                |
| ------- | --------------------------------------------------------------------------------------------------------------------------------------------------- |
| T27-1   | DINOv2 ViT-B/14 一致性服务：每个 r2v 产出抽样 4–8 帧 → CLIP image embedding → 与 ProductImage 参考做 cosine similarity                              |
| T27-2   | 阈值规则：≥ 0.85 通过；0.75–0.85 警告（人工复核）；< 0.75 自动重生成（最多 N 次）                                                                    |
| T27-3   | 一致性报告：StoryWorkbench 内每个 shot 显示 consistency_score，可点击查看抽样帧 vs 参考图对比                                                       |
| T27-4   | 集成到 `chapter_av_export` 前置门（可选）：消耗的镜头分数全部 ≥ 0.75 才允许导出，否则提示重生                                                       |

### P4 完成标准

- 至少 1 个 partner 通过 Partner API 提交并产出 commerce 短剧
- 至少 10 个变体回灌真实投放数据后，归因报告（按公式 / 钩子 / 人格 / 平台 4 维度）可用
- 多平台导出预设覆盖率 100%（5 个目标平台）
- 合规 BLOCKER 告警在配置 webhook 后 5s 内送达
- 一致性引擎对 hero 镜头平均 cosine 相似度 ≥ 0.85，<0.75 镜头比例 ≤ 5%

---

## 跨阶段决定（保持稳定）

| ID  | 决定                                                                                                                  |
| --- | --------------------------------------------------------------------------------------------------------------------- |
| D1  | `Product.name` 全局唯一（mirror `Prop` 设计），方便跨项目复用                                                         |
| D2  | 单 Celery `task.execute`，队列路由在 `apply_async` 时通过 `queue=` 参数指定，不在 worker 端硬编码                     |
| D3  | Python `bootstrap_builtin_prompts`（幂等，应用启动时调用），不依赖 SQL seed                                           |
| D4  | 前端 commerce 页面在 P1/P2/P3 阶段 hardcoded zh-CN，i18n 完整化推迟到 P5                                              |
| D5  | 新增 commerce agents 全部使用 `method="json_schema", strict=True`，避免 P1 早期 JSON drift 问题                       |
| D6  | `ComplianceProfile.rules` 用 JSON 字段，规则演化不触发 schema migration                                               |
| D7  | `ApiKeyQuota` 表 P1 即建（避免 P3 二次迁移），但中间件与限流逻辑 P4 才启用                                            |
| D8  | A/B 变体使用同一 `StoryVariant` 表 + `is_champion` 标记，不引入独立 `Champion` 实体                                   |
| D9  | `happyhorse-1.0-t2v/i2v/r2v` 自带音轨**一律丢弃**：模型不接受指定台词文本、跨镜音色漂移、官方无控制开关；所有音频走独立 TTS pipeline |
| D10 | 完全不做 lip-sync：剧本 prompt 偏向非张嘴构图；个别需要原音对口型的镜头通过 `Shot.audio_strategy=keep_native` 逃生口处理；数字人 / lip-sync 推迟 P5+ |
| D11 | r2v 不拆 task_kind：扩 `video_generation` 内部分支，按 capability 字段路由 multi_ref；按 model name 字符串判别仅作 fallback |
| D12 | 字幕默认 hardsub + ASS 源文件作为 derivative 独立保留：抖音 / TikTok 算法对外挂字幕减分，但 ASS 源文件保留以便后续换语言 / 字号免重生整段视频 |
| D13 | `chapter_av_export` 与老 `chapter_timeline_export` 并存（v0.6.0 标 deprecated，v0.7.0 删除）；不强行替代避免破坏既有前端 |
| D14 | 视觉一致性引擎（DINOv2 / CLIP）推迟 P4 W27：P3 优先解决"商品视觉对得上"的产品功能缺口，"质量门"作为后置检查项 |
| D15 | TTS 输出按 `(text, voice_pack_id, speed)` 三元组 hash 缓存到 `tts_cache` 表，避免重复计费 |
| D16 | 跨 chapter 音频响度统一归一化到 -16 LUFS（移动端标准），ffmpeg `loudnorm=I=-16:TP=-1.5:LRA=11` |

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
