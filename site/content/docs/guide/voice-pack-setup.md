---
title: "音色包配置（VoicePack Setup）"
weight: 14
description: "在剧情带货项目里挑选系统级 CosyVoice 音色或上传自定义 sample，让多镜头跨章节声纹保持一致。"
---

剧情带货视频里，旁白和角色对白如果每一镜的声纹都不一样，观众会立刻出戏。VoicePack 把「这个角色说话用什么声音」抽成一个可复用的实体，绑到 `Character` 或 `StoryVariant` 之后，所有镜头的 TTS 都会复用同一份音色配置。

本文回答的是「怎么用」，不展开音色包数据结构与生成链路细节，那些请看 [/docs/architecture/commerce-story-data-model/](/docs/architecture/commerce-story-data-model/)。

## 你将获得

- 在「音色包」页一次性浏览 6 个系统级 CosyVoice zh-CN 音色
- 点卡片即可试听 sample，单 active player 不会多条同时响
- 把音色绑到 `Character.voice_pack_id` 或 `StoryVariant.narration_voice_pack_id`，跨镜跨章节声纹保持一致
- 知道 W21+ 自定义音色训练入口在哪个 stub 占位（点击不报错，提示「敬请期待」）
- 配合 `silent_with_tts` 默认策略，视频生成完毕自动接 TTS，不用手动触发

## 前置准备

### 1. 后端跑在 :8088

剧情带货后端默认端口是 **8088**，不是 README 里那个 8000。本地起：

```bash
cd backend
uv run uvicorn app.main:app --reload --host 0.0.0.0 --port 8088
```

### 2. DashScope Key 配好

CosyVoice 走 DashScope，sample 试听和 TTS 生成都要用：

```bash
cd backend
echo 'DASHSCOPE_API_KEY=sk-xxxxxxxx' >> .env
```

如果还没确认 Key 可用，先按 [/docs/guide/verify-aliyun-bailian-image/](/docs/guide/verify-aliyun-bailian-image/) 的脚本跑一遍，确认 Key 与网络都没问题再继续。

### 3. bootstrap 让系统级音色入库

应用启动时由 `bootstrap_async_state` 自动 seed 6 个系统级 VoicePack。日志里能看到：

```
[BOOTSTRAP] voice_packs seeded: 6 system packs (zh-CN, cosyvoice_v2)
```

如果日志里没这行，说明 bootstrap 没跑，下面的 API 查询会返回空数组。

### 4. 前端 i18n commerce 命名空间

W20-T7 之后，前端 commerce 模块默认走 zh-CN，不用额外切语言。如果你 fork 了改过 `front/src/i18n/`，确认 commerce ns 还在注册列表里：

```bash
cd front
grep -r "commerce" src/i18n/
```

## 操作步骤

### Step 1：浏览系统级音色库

前端入口：

```bash
cd front
pnpm dev
```

浏览器打开 `http://localhost:5173/commerce/voice-packs`，会看到 6 个系统级卡片，包括但不限于：

- `cosyvoice_v2_longxiaochun`（中性，默认旁白推荐）
- `cosyvoice_v2_longwan`（女声）
- 其它 4 个 zh-CN 音色

也可以直接 curl 后端 API 确认：

```bash
curl 'http://localhost:8088/api/v1/commerce/voice-packs?language_code=zh-CN&is_system=true'
```

期望返回 6 条 `VoicePackRead`，每条包含 `id` / `provider` / `provider_voice_id` / `sample_url` / `language_code`。

### Step 2：试听 sample

在 `/commerce/voice-packs` 页面，每张卡片右上角有播放按钮。点击行为：

- 当前卡片开始播 sample
- 上一张正在播的卡片自动 `pause()`，避免两条音频重叠
- 再点同一张卡片切换播放/暂停

如果点了没声音，先打开浏览器控制台看 network：sample 是 DashScope 直链，401 通常是 Key 没生效。

### Step 3：在 StoryWorkbench 选音色

打开任一 chapter 的 StoryWorkbench：

1. 顶部点「音视频预览」按钮，右侧抽屉滑出
2. 抽屉里展开「音色」collapse 区域
3. `VoicePackPicker` 默认按当前 chapter 的 `language_code` 过滤
4. 点击列表行触发 `onChange(voicePackId)`，被选中行 `aria-selected="true"`

抽屉里的 picker 和独立页 `/commerce/voice-packs` 共用一个组件，行为一致。

### Step 4：把音色绑到 Character 或 StoryVariant

绑定有两个层级，按用途选：

- **角色级**：`Character.voice_pack_id` 决定这个角色所有对白的音色
- **变体级**：`StoryVariant.narration_voice_pack_id` 决定整条变体里旁白的音色

ORM 字段：

```python
character.voice_pack_id = voice_pack.id
session.add(character)
await session.commit()
```

只要多个镜头引用的 Character / StoryVariant 都指向同一个 VoicePack，跨镜声纹就会保持一致。CosyVoice 模型本身已知有 5-10% 的轻微漂移，属正常范围，不算 bug。

### Step 5：触发 silent_with_tts 路径生成

`shot.audio_strategy` 默认就是 `silent_with_tts`，不用改。流程是：

1. 你正常发起 `video_generation` 任务
2. 视频生成完成后，链路自动 dispatch `tts_generate`（Decision D 里的 chain dispatch）
3. TTS 命中缓存走 `(text, voice_pack_id, speed)` 的 hash 查 `tts_cache` 表
4. 没命中才真调 CosyVoice，结果写回 cache

这意味着同一段对白同一个 voice_pack 重跑不会重复扣费。

## 故障排查

**「`/commerce/voice-packs` 页面看不到 6 个音色」**  
bootstrap 没跑。检查后端启动日志，找 `[BOOTSTRAP] voice_packs seeded`。如果没有，可能是 DB 迁移未到位或 seeder 抛异常被吞掉，启动时加 `--log-level debug` 复跑。

**「试听 sample 报 401」**  
DashScope Key 没配或失效。先回 `.env` 检查 `DASHSCOPE_API_KEY`，再按 [/docs/guide/verify-aliyun-bailian-image/](/docs/guide/verify-aliyun-bailian-image/) 跑脚本验证。

**「跨镜音色明显不一致」**  
排查顺序：

1. 确认所有相关 `Character.voice_pack_id` 是同一个 ID
2. 确认 `StoryVariant.narration_voice_pack_id` 没被某个镜头单独覆盖
3. 如果以上都对，但听感仍有 5-10% 差异，是 CosyVoice 模型本身的漂移特性，不是配置问题

**「上传定制按钮点了显示『敬请期待』」**  
不是 bug。自定义音色训练在 W21+ 计划范围内，当前版本只放了 stub 占位。

**「Picker 抽屉里点了没反应」**  
检查浏览器控制台是否有 `onChange` 报错。常见原因是 chapter 还没绑定 `language_code`，picker 过滤后列表为空。

## 命令速查

| 场景 | 命令 |
| --- | --- |
| Bootstrap seed 6 个系统级音色（启动后端即可） | `cd backend && uv run uvicorn app.main:app --port 8088` |
| 查询 zh-CN 系统级音色列表 | `curl 'http://localhost:8088/api/v1/commerce/voice-packs?language_code=zh-CN&is_system=true'` |
| 查询某个 provider 的全部音色 | `curl 'http://localhost:8088/api/v1/commerce/voice-packs?provider=cosyvoice_v2'` |
| 启动前端预览 voice-packs 页 | `cd front && pnpm dev`（再访问 `/commerce/voice-packs`） |
| 重跑 OpenAPI 同步前端类型 | `cd front && pnpm run openapi:update` |
| 触发某 chapter 的视频生成（自动接 TTS） | 在 StoryWorkbench 点「生成视频」即可，silent_with_tts 是默认策略 |

## 相关文档

- [/docs/architecture/commerce-story-data-model/#visual-production-layerw16w21-落地版](/docs/architecture/commerce-story-data-model/#visual-production-layerw16w21-落地版)：VoicePack / Character / StoryVariant 的字段与关系
- [/docs/guide/subtitle-style-config/](/docs/guide/subtitle-style-config/)：字幕样式配置（和 TTS 同属音视频后处理）
- [/docs/guide/r2v-multi-reference/](/docs/guide/r2v-multi-reference/)：多参考图视频生成（视觉一致性的姊妹篇）
- `backend/app/services/studio/builtin_voice_packs.py`：6 个系统级 VoicePack 的 seed 定义
- `backend/app/api/v1/routes/commerce/voice_packs.py`：`GET /api/v1/commerce/voice-packs` 路由实现
