---
title: "字幕样式配置（SubtitleStyle Config）"
weight: 15
description: "挑选系统级 douyin_default / tiktok_viral / reels_lower_third 模板，或自定义字号/颜色/描边/位置生成项目级覆盖。"
---

短剧导出到抖音 / TikTok / Reels 这类 9:16 竖屏场景时，字幕能不能在「下巴位置」显示、有没有被刘海或互动条挡住、字芯和描边颜色对比度够不够，全部由 `SubtitleStyle` 决定。系统已经准备了 3 个内置平台模板，自定义场景再走 `SubtitleStylePicker` 调字号、颜色、描边、位置。

## 你将获得

完成本指南后，你应该能：

- 区分 W18 内置 3 个平台模板（`douyin_default` / `tiktok_viral` / `reels_lower_third`）的字号、颜色、底距差异。
- 在 `StoryWorkbench` 视频面板或 `/commerce/subtitle-styles` 页面挑选并预览模板。
- 看懂 `alignment` 字段的 numpad 1-9 编码，以及 `primary_colour` / `outline_colour` 在 ASS 格式里 `&HAABBGGRR` BGR 字节序与 web hex `#RRGGBB` 之间的转换。
- 通过 `subtitle_safe_zone.py` 的安全区 lint 校验底距、左右边距、最小字号、字芯 vs 描边 WCAG 4.5:1 对比度。
- 知道项目级覆盖入口（W21+ 实装中）的占位位置。

## 前置准备

正式跑流程前确认这些条件成立：

- 后端 dev server 跑在 `:8088`，bootstrap 阶段已执行 `bootstrap_builtin_subtitle_styles()`，3 条 `SubtitleStyle` 系统行（`is_system=true`）入库。
- 前端 i18n 已注册 `commerce` 命名空间（W20-T7 完成），`SubtitleStylePicker` 组件能拿到文案。
- 镜头（Shot）已进入 `ready` 状态，且字幕路径已确定：
  - `silent_with_tts`：TTS 完成后由 `tts_generate` 派发 `shot_subtitle_render`。
  - `keep_native`：ASR 字幕生成后由 `asr_subtitle_generate` 链式派发 `shot_subtitle_render`。
- 至少一条 `Provider` 已配置可用的 LLM / TTS / ASR 能力（参考 [LLM 供应商注册与扩展](/docs/guide/llm-provider-registration/)）。

## 操作步骤

下面 5 步覆盖：浏览模板 → 自定义编辑 → 触发渲染 → 安全区校验 → 烧录导出。

### Step 1：浏览 3 个内置平台模板

最简单的入口是页面：

```bash
cd front
pnpm dev
# 浏览器打开 http://localhost:7788/commerce/subtitle-styles
```

也可以直接调 API 看原始字段：

```bash
cd backend
curl 'http://127.0.0.1:8088/api/v1/commerce/subtitle-styles?is_system=true'
```

返回 3 条 `SubtitleStyleRead`，`alignment` 是 numpad int 1-9，颜色是 ASS BGR 格式字符串。三个模板的关键差异：

| 字段 | `douyin_default` | `tiktok_viral` | `reels_lower_third` |
| --- | --- | --- | --- |
| `font_family` | 思源黑体 Heavy | Arial Black | Inter |
| `font_size` | 64 px | 84 px | 52 px |
| `primary_colour`（字芯） | 白 `#FFFFFF` | 金黄 `#FFD400` | 白 `#FFFFFF` |
| `outline_colour`（描边） | 青色高亮 `#00E5FF` | 黑 `#000000` 6 px | 黑 `#000000` |
| `alignment`（numpad） | 2（底中） | 2（底中） | 2（底中） |
| `margin_v`（底距） | 200 px | 400 px | 360 px |
| 左右边距 | 0 / 0 | 0 / 0 | 90 / 90 |
| `play_res_x` × `play_res_y` | 1080 × 1920 | 1080 × 1920 | 1080 × 1920 |

实际定义在 `backend/app/services/studio/builtin_subtitle_styles.py`，bootstrap 时会按 `key` 幂等 upsert，重复跑 bootstrap 不会产生重复行。

### Step 2：在 SubtitleStylePicker 切到自定义 tab 调参数

`SubtitleStylePicker` 顶部两个 tab：

- **系统模板**：列出 `is_system=true` 的 3 条，点选直接套用。
- **自定义编辑**：基于当前选中的模板深拷贝出可改的字段。

自定义 tab 里要注意三件事：

1. **颜色用 web hex `#RRGGBB`**。`SubtitleStylePicker` 内部的 `colorCodec.toAss(hex)` 会把 `#FFD400` 转成 ASS 的 `&H0000D4FF`（注意顺序：alpha → BB → GG → RR）。回读时 `colorCodec.fromAss()` 反向转回 hex 给 color picker。**不要**直接往输入框填 ASS 字符串。
2. **`alignment` 用 9 宫格 numpad 选择器**：

   ```
   7 顶左   8 顶中   9 顶右
   4 中左   5 中中   6 中右
   1 底左   2 底中   3 底右
   ```

   这套编码直接对应 ASS 的 `\an` 标签语义，不需要做任何映射。9:16 短剧 99% 选 `2`（底中）；下三分之一台词条形式（Reels 风）也是 `2`，靠 `margin_v` 抬高。

3. **非法 hex 不静默 fallback**。`colorCodec.toAss('#GGGGGG')` 会抛 `Error: invalid hex color`，`SubtitleStylePicker` 在输入框下方行内显示红字提示，禁用「保存」按钮。这是为了避免静默写入 `&H00000000` 导致字幕变全黑透明。

### Step 3：触发 `shot_subtitle_render`

字幕渲染由专门的 worker 跑，入口因路径而异：

- **`silent_with_tts` 路径**：TTS 任务（`tts_generate`）成功完成后，可由用户在 `StoryWorkbench` 手动派发 `shot_subtitle_render`，或由编排策略自动派发。Worker 拿到 `Shot` + `SubtitleStyle` + `DialogueLine[]` + 时间戳 → 生成 `.ass` 文件 → 落 MinIO → 写一行 `SubtitleTrack`。
- **`keep_native` 路径**：ASR 字幕生成（`asr_subtitle_generate`）完成后链式派发 `shot_subtitle_render`，输入换成 ASR 输出的逐句时间戳。

Worker 实现位于 `backend/app/services/studio/shot_subtitle_render_worker.py`。.ass 落 MinIO 的 object key 形如 `subtitle/{shot_id}/{track_id}.ass`，对应 `SubtitleTrack.subtitle_track_file_id` 指向的 `File` 行。

手动触发单镜头渲染（开发调试常用）：

```bash
cd backend
curl -X POST 'http://127.0.0.1:8088/api/v1/commerce/shots/{shot_id}/subtitle-render' \
  -H 'Content-Type: application/json' \
  -d '{"subtitle_style_id": "uuid-of-style"}'
```

### Step 4：安全区 lint 检查

渲染前 worker 会调 `backend/app/services/studio/subtitle_safe_zone.py` 的 `lint(style, platform)` 跑一遍硬阈值。三个平台目前的阈值：

| 平台 | `margin_v` 底距 | 左右边距 | 最小 `font_size` | 字芯 vs 描边对比度 |
| --- | --- | --- | --- | --- |
| 抖音 | ≥ 180 px | 0 | ≥ 36 px | WCAG 4.5:1 |
| TikTok | ≥ 380 px | 0 | ≥ 60 px | WCAG 4.5:1 |
| Reels | ≥ 350 px | ≥ 90 px | ≥ 32 px | WCAG 4.5:1 |

底距阈值是为了避开各平台的互动条 / 进度条 / 评论按钮区。Reels 左右 90 px 是为了避开右侧竖排互动按钮。

**违规返回 warning，不阻塞渲染**。warning 会写进 `SubtitleTrack.lint_warnings`（JSON 数组），前端 `StoryWorkbench` 视频面板展示黄色感叹号。如果你确认想压安全区（比如剧情需要顶部 banner），warning 可以无视；如果不是有意为之，回 Step 2 调 `SubtitleStyle` 字段。

### Step 5：`chapter_av_export` 烧录到 mp4

章节最终导出由 `chapter_av_export` worker 处理。它会：

1. 按 `ChapterTimelineSegment` 顺序拉每个 shot 的视频和 `subtitle_track_file_id` 指向的 `.ass`。
2. 用 `ffmpeg` 的 `subtitles=` filter 把字幕**硬烧**进 mp4 视频流（不走软字幕轨）。
3. 同时保留 `.ass` derivative 文件，挂到 `ChapterExport.subtitle_artifact_files`，供后续语言切换 / 字号微调免重新生成视频。

硬烧的好处是抖音 / TikTok / Reels 上传后字幕一定显示；副产物保留是为了之后改字号、做多语言版本时不用重跑视频生成（视频生成贵，字幕渲染便宜）。

## 故障排查

### 自定义颜色显示成「BGR 反色」

例：选了红 `#FF0000`，出来字芯是蓝色。

`ColorCodec.toAss()` 是对的，BGR 字节序是 ASS 规范本身的事。检查项：

- 输入有没有带 `#` 前缀。`#FF0000` 正确，`FF0000` 在 ASS 里会被当成 `&H00FF0000` 直接拼，结果是蓝。
- color picker 输出是不是 RGBA（带 alpha）。`SubtitleStylePicker` 只接受 6 位 hex，不要传 8 位 `#FF0000FF`。

### `alignment` 1-9 显示位置不对

复习 numpad 编码：键盘小键盘的 9 个数字键，方向就是字幕在画面的位置。`1` 在键盘左下，对应字幕底左。这套编码和 ASS `\an` 标签完全一致，**不是** SSA 旧版的 1-3 + tag 模式。

如果你看的是导出的 `.ass` 文件，找 `Alignment:` 字段或正文行里的 `\an2`，应该和 `SubtitleStyle.alignment` 数字一致。

### 安全区 lint 抛 warning

打开 `backend/app/services/studio/subtitle_safe_zone.py`，看 `_THRESHOLDS` 字典里对应平台的阈值。warning 信息会指出违规字段名（比如 `margin_v: 120 < 180`），回到 `SubtitleStylePicker` 把对应字段调到阈值以上。

WCAG 4.5:1 对比度违规通常发生在「白字 + 浅黄描边」「黄字 + 浅灰描边」这种组合。最稳的方案是字芯任意 + 描边纯黑，或字芯任意 + 描边深灰 `#1a1a1a`。

### 「项目级覆盖」按钮 disabled

W21+ 实装中。当前 `/commerce/subtitle-styles` 页只能浏览系统模板，不能保存项目级覆盖。需要项目级差异化时，先在 `SubtitleStylePicker` 自定义 tab 里临时调，确认效果后等 W21 项目级 `SubtitleStyle.project_id` 字段开放写入。

## 命令速查

| 场景 | 命令 |
| --- | --- |
| Bootstrap 内置 subtitle styles（启动后端时自动跑） | `cd backend && uv run uvicorn app.main:app --reload --port 8088` |
| 列出 3 个系统模板 | `cd backend && curl 'http://127.0.0.1:8088/api/v1/commerce/subtitle-styles?is_system=true'` |
| 按 project 过滤（W21+ 占位） | `cd backend && curl 'http://127.0.0.1:8088/api/v1/commerce/subtitle-styles?project_id={uuid}'` |
| 跑前端字幕样式页 | `cd front && pnpm dev` |
| 单镜头手动触发字幕渲染 | `cd backend && curl -X POST 'http://127.0.0.1:8088/api/v1/commerce/shots/{shot_id}/subtitle-render' -H 'Content-Type: application/json' -d '{"subtitle_style_id":"{uuid}"}'` |
| OpenAPI 同步前端 generated client | `cd front && pnpm run openapi:update` |

## 相关文档

- [Commerce Story 数据模型 / Visual Production Layer](/docs/architecture/commerce-story-data-model/)：`SubtitleStyle` 表 18 字段、`SubtitleTrack` / `ChapterTimelineSegment` / `ChapterExport` 关系。
- [Voice Pack 配置](/docs/guide/voice-pack-setup/)：上一篇 how-to，配 TTS 音色 → `silent_with_tts` 路径触发字幕渲染的前置条件。
- [r2v 多参考图配置](/docs/guide/r2v-multi-reference/)：视频生成路径，决定 `chapter_av_export` 烧录字幕时的底片。
- 实现源码：
  - `backend/app/services/studio/builtin_subtitle_styles.py` — 3 个内置模板定义 + bootstrap 函数。
  - `backend/app/services/studio/subtitle_safe_zone.py` — 三平台安全区阈值表 + WCAG 对比度计算。
  - `backend/app/services/studio/shot_subtitle_render_worker.py` — `.ass` 生成 + MinIO 落盘 + `SubtitleTrack` 写入。
  - `front/src/components/commerce/SubtitleStylePicker.tsx` — 系统模板 / 自定义 tab + `colorCodec` helper。
