---
title: "平台导出（commerce_export）"
weight: 47
description: "把章节成片按 PlatformExportPreset 转换为多平台发布版本的 ffmpeg 二级管线（slow 队列，1800s 超时）。"
---

## 边界

`commerce_export` 是 P4 W23 引入的"二次衍生"导出管线，与既有 `chapter_av_export` 显式区分：

- `chapter_av_export` = 主合成。跨路径合成（`silent_with_tts` amix / `keep_native` pass-through）+ 字幕硬烧 + loudnorm 响度归一化，每个章节通常只跑一次，产物 `FileUsageKind.chapter_master_dubbed`。
- `commerce_export` = 二次衍生。基于已存在的章节成片，按 :code:`PlatformExportPreset` 做画幅 / 编码 / 水印 / 贴纸 / 响度等差异化转换，每个 `(variant, preset)` 组合都跑一次，产物 `FileUsageKind.product_export`。

二级管线**不重复**主合成的字幕烧录，只做"已合成成片 → 平台版本"的转换。

## 数据

- 输入：
  - `StoryVariant.id` → 反查 `chapter_id` / `project_id`。
  - 最新一行 `FileUsage(usage_kind=chapter_master_dubbed, chapter_id=<variant.chapter_id>)` → 定位章节成片 `FileItem`。
  - `PlatformExportPreset.id` → 拿到 `aspect_ratio` / `codec_preset` / `loudness_lufs` / `file_format` / `watermark_file_id` / `sticker_specs` / `subtitle_style_id` / `voice_pack_id`。
- 输出：
  - 新建 `FileItem(type=video)`，`storage_key` 落 `generated-videos/commerce-export/<variant_id>/<preset_id>/<uuid>.<ext>`。
  - `FileUsage(usage_kind=product_export, project_id, chapter_id, source_ref=variant:<variant>:preset:<preset>:task:<task>)`。
  - `GenerationTaskLink.file_id` 回写（路由层创建时未知 file_id）。

## API

- `POST /api/v1/commerce/export`
  - body: `{"variant_id": str, "preset_id": str}`（`extra="forbid"`）
  - 行为：落 `GenerationTask` 行（`task_kind=commerce_export`），commit 后 Celery `task.execute` 投递到 **slow** 队列（与 `chapter_av_export` / `chapter_av_plan` 同档），返回 202 + `task_id`。

## Worker 行为

- `task_kind=commerce_export`，`AbstractAsyncDelegatingExecutor`，超时 1800s。
- 生命周期模板与 `chapter_av_export_task` 同源（hotfix-4 canonical）：`set_status(running)` → cancel check → 业务 → cancel check → `set_result` → `set_status(succeeded)`；失败时 rollback + 独立会话写 `failed`。
- ffmpeg 命令构建落在 `app.services.commerce.ffmpeg_preset_transform`（纯函数，便于单测）：
  - `aspect_ratio` → `scale={W}:{H}:force_original_aspect_ratio=decrease, pad=:(ow-iw)/2:(oh-ih)/2:black, setsar=1`（保留全部内容 + 黑边居中，不裁剪）。
  - `watermark_file_id` 非空 → 追加 `[v0][1:v]overlay=W-w-24:24:format=auto[v1]`（右上角 24px 边距）。
  - `sticker_specs[i]` → 追加 `[vk][n:v]overlay={x}:{y}:format=auto:enable='between(t,start,end)'[v{k+1}]`，缺映射条目静默丢弃。
  - `loudness_lufs != -16.0` → 追加 `[0:a]loudnorm=I=...:TP=-1.5:LRA=11[aout]`，`-map [aout]`；否则 `-map 0:a?` 直接 pass-through。
  - `codec_preset` → `h264_high_4_1` / `hevc_main_10` / `prores_proxy` 三档输出参数。
  - `file_format` → `-f mp4` / `-f mov`（决定容器；输出后缀由 worker 与 preset 对齐）。

## 队列与 SLA

- `slow` 队列：commerce_export 与 chapter_av_export / chapter_av_plan 同档分钟级，避免与 fast 队列上的合规检查 / TTS 等争抢消费者（W19b 决策）。
- 1800s 超时：典型耗时 1-5 分钟（取决于源时长与 codec）；3x 余量。

## 测试

- `tests/test_ffmpeg_preset_transform.py`：纯函数 8 cases（aspect / 水印 / 贴纸 / codec / loudnorm / 非法值 / 容器 / sticker 兜底）。
- `tests/test_commerce_export_worker.py`：worker 7 cases（注册 / 超时 / 入参兜底 / 完整生命周期 / FileItem+FileUsage 落地 / master 缺失 → failed）。
- `tests/test_commerce_export_dispatcher.py`：dispatcher 3 cases（task_kind 同源 / slow queue 路由 / run_args 透传）。
