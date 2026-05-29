---
title: "章节时间线与导出成片"
weight: 45
description: "章节级镜头编排时间线（仍存）；裸视频拼接导出 chapter_timeline_export 已于 v0.7.2 删除，章节合成统一走 chapter_av_export。"
---

## 当前事实

章节级时间线编辑能力**保留**：

- 表 `chapter_timeline_states`：每章一行可选状态，`layout_version` 在每次成功 `PUT` 后递增，用于与客户端 `layout_version` 对比（冲突时 HTTP 409）。
- 表 `chapter_timeline_segments`：每章内每镜至多一条，按 `position` 排序；`trim_start_ms` / `trim_end_ms` 表示**相对镜头成片文件**的裁剪毫秒坐标：**二者均为空表示全长**；否则区间为**左闭右开** `[start, end)`，缺省入点为 `0`、缺省出点为源成片时长。`PUT` 在设置任一端非空时会 **ffprobe 下载校验** 成片时长（镜头须已有 `generated_video`）。
- API 仍保留 `GET/PUT /api/v1/studio/chapters/{chapter_id}/timeline` 与新增的 `PATCH .../segments/{segment_id}/audio`（W31 BGM/SFX）。

章节级**成片导出**已统一收口到 `chapter_av_export`：详见下一节"含字幕配音的合成流水线"。

## v0.7.2 删除：chapter_timeline_export

历史背景：

- v0.6.0 引入 `chapter_av_export` 作为章节级合成新主路径，将原 `chapter_timeline_export`（裸视频 ffmpeg concat 拼接）标记为 `deprecated`，原计划 v0.7.0 删除。
- v0.7.0 因 W31 BGM/SFX 链路兼容窗口未关，删除节点延期至 v0.8.0。
- v0.7.2 W31 BGM/SFX 已落地、兼容窗口闭合，提前于 v0.7.2 正式删除。

具体删除项（v0.7.2）：

- `app/services/studio/chapter_timeline_export.py` / `chapter_timeline_export_task.py` 文件删除
- `task_kind="chapter_timeline_export"` 注册项从 `task_executor_registry` 移除
- 路由 `POST /api/v1/studio/chapters/{chapter_id}/timeline/export` 删除（OpenAPI generated client 同步重生成）
- Schema `ChapterTimelineExportRequest` / `ChapterTimelineEncodeMode` 从 `app/schemas/studio/chapter_timeline.py` 删除
- 枚举 `FileUsageKind.chapter_master_video` 从 `app/models/types.py` 删除（产物用途由 `chapter_master_dubbed` 表达）
- 前端 `front/src/pages/aiStudio/editor/VideoEditor.tsx` 的"导出成片"按钮迁移至分镜工作室 `AVPreviewPanel`

下游升级要点：

- 调用方应改用 `chapter_av_export` task_kind（W19 落地，W31 加 BGM/SFX）；触发入口为分镜工作室 `AVPreviewPanel` 的"立即生成成片"按钮。
- `FileItem.usage_kind="chapter_master_video"` 在 v0.7.2 之后将无法反序列化（如有历史数据需在 DB 层迁移到 `chapter_master_dubbed` 或保留为字符串 raw 字段）。
- 前 v0.6.0 客户端调用 `/timeline/export` 路由会收到 404。

## chapter_av_export：含字幕配音的合成流水线

章节级现仅提供 `chapter_av_export` 路径，用来一次合成"视频 + TTS/原音 + 字幕 + 响度归一化"成片。

- task_kind：`chapter_av_export`（slow queue, 1800s 超时）
- 编排层：`services/studio/chapter_av_export.py`（v0.7.2 起承接原 `chapter_timeline_export.py` 的 `ensure_timeline_exportable` 校验函数），worker 实装在 `services/studio/chapter_av_export_task.py`

输出文件类型：

- `FileUsageKind.chapter_master_dubbed`：含字幕硬烧 + 配音 + 响度归一化的最终成片
- `FileUsageKind.chapter_master_audio` / `chapter_master_subtitle`：中间产物（音轨 / ASS 源文件）按需保留

合成时按 `Shot.audio_strategy` 走两条对称路径：

- `silent_with_tts`：每段视频静音 + 对应 ShotDialogLine 的 TTS 音频通过 `amix(normalize=0)` + `apad` / `atrim` 对齐到段长。
- `keep_native`：直接保留 r2v / i2v / t2v 模型自带原音，按 `[v_idx:a]` 直通到 concat。

字幕处理：

- 默认 `subtitles=` filter 硬烧 ASS 到最终 mp4
- ASS 源文件已经在 `shot_subtitle_render` 阶段独立落 minio，可以单独下载用于换语言 / 换字号而不必重生整段视频

响度：concat 之后统一接 `loudnorm I=-16:TP=-1.5:LRA=11`，目标 -16 LUFS（移动端标准 ±1）。

入参信任规则：runner 只信任 `run_args.chapter_id`，再进库重新解析镜头顺序、`generated_video_file_id` / `dubbed_video_file_id` / `subtitle_track_file_id`，避免请求时刻与执行时刻数据漂移。

成片可见性依赖前置链路：`chapter_av_export` 之前必须完成 video_generation → ASR/TTS chain dispatch → shot_subtitle_render，详见 [持久化引擎与事务边界](/docs/architecture/persistence-engine/) 与 [任务执行架构](/docs/architecture/task-execution/)。

## 与产品边界

- 分镜编辑页/分镜工作室职责不变；"章节剪辑"页 `VideoEditor.tsx` 仅负责章节内镜头顺序与裁剪入出点编辑，不再承担成片导出入口。
- 章节级成片导出统一由分镜工作室 `AVPreviewPanel` 触发 `chapter_av_export`，对应"工作室 = 生成"边界（AGENTS.md 前端页面职责小节）。
