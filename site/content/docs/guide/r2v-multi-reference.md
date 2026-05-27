---
title: "多图参考视频生成（r2v Multi-Reference）"
weight: 16
description: "用 happyhorse-1.0-r2v 多图参考能力让镜头里的商品与项目挂载的 ProductImage 视觉对齐，按 product_focus_level 自动选 view_angle 优先级序列。"
---

本指南面向「镜头里要出现具体商品、且要在多镜头之间保持视觉一致」的场景。我们已经在 W16 把 `happyhorse-1.0-r2v` 接入 DashScope 视频任务系统，可以在一次生成里最多塞 9 张参考图，再由后端按 `product_focus_level` 自动选角度、自动按预算分配名额。

下面所有路径与字段名都对齐当前 `dev` 分支的实现，照着做就能跑通。

## 你将获得

- 一套可上传多角度商品图的 UI：`ProductImageGrid` 7 个 `view_angle` × 4 个 `quality_level` 槽位。
- `product_focus_level` 4 档（`hero` / `functional` / `subtle` / `none`）到 `view_angle` 优先级序列的固定映射，前端选什么后端就按什么挑图。
- 9 槽 `ReferenceImageBudget` 自动分配规则：商品 3-5 张、人物 2-3 张、场景 1-2 张，超出按优先级丢弃并写 task warning。
- 一次完整的 `happyhorse-1.0-r2v` 多图参考视频任务：从挂载商品到拿到 file_id，再链路派发字幕或配音任务。
- 1080P / 720P 两档分辨率的成本知情：`1080P=1.6 元/秒`、`720P=0.9 元/秒`，先用 720P 验稿，验完再升 1080P 出片。

## 前置准备

### 1. 后端环境

```bash
cd backend
cp .env.example .env
uv sync
uv run alembic upgrade head
uv run uvicorn app.main:app --reload --host 0.0.0.0 --port 8088
```

### 2. DashScope Key 与配额

- 在 `.env` 设置 `DASHSCOPE_API_KEY`。
- 该账号需要开通 `happyhorse-1.0-r2v` 的视频生成配额，DashScope 默认会按 RPS 限流（参考上限 RPS=20）。
- 在「模型管理」里把 `happyhorse-1.0-r2v` 加到 `category=video` 的可选模型，或确认它已被 bootstrap 注册（详见 `backend/app/core/integrations/aliyun/video_capabilities.py`）。

### 3. ProductImage 数据准备

每个要做主推的商品建议至少先 seed 3 张 `ProductImage`，覆盖核心 `view_angle`：

- `FRONT` 必须有，是 `hero` / `subtle` 优先级序列的第一/第二档。
- `THREE_QUARTER` 强烈推荐，三个 focus level 都用得上。
- `DETAIL` 用于 `functional` 镜头的近距特写，没有就只能退回 `THREE_QUARTER`。

`quality_level` 起步建议 `HIGH`，关键素材升 `ULTRA`。

### 4. Celery worker

视频任务不在 `fast` 队列，按现有部署文档启动视频队列的 worker，确保 `task_kind=video_generation` 能被消费。

## 操作步骤

下面以「为商品 `prod-001` 在项目 `proj-009` 里跑一个 `hero` 镜头」为例。

### Step 1：上传多角度商品图

**入口**：`/commerce/products/{product_id}/images`

前端是 `ProductImageGrid`，把 7 个 `view_angle` 摆在横轴、4 个 `quality_level` 摆在纵轴，每个交叉格点一次就能上传一张图并把元信息绑死。

后端两步：

```bash
# 1) 上传文件
curl -X POST http://127.0.0.1:8088/api/v1/studio/files \
  -F "file=@product_front_high.png"

# 2) 绑定到商品的指定角度 + 质量
curl -X POST http://127.0.0.1:8088/api/v1/studio/products/prod-001/images \
  -H 'Content-Type: application/json' \
  -d '{
    "file_id": "<file_id_from_step_1>",
    "view_angle": "FRONT",
    "quality_level": "HIGH"
  }'
```

推荐起步配置：

| view_angle | quality_level | 用途 |
| --- | --- | --- |
| `FRONT` | `HIGH` | hero / subtle 的主选 |
| `THREE_QUARTER` | `HIGH` | 三档 focus 都能复用 |
| `DETAIL` | `HIGH` | functional 近距特写主选 |

### Step 2：把商品挂到项目

`ProjectProductLink` 决定这个商品在剧情里的角色与出场时机：

```bash
curl -X POST http://127.0.0.1:8088/api/v1/studio/story-projects/proj-009/products/prod-001 \
  -H 'Content-Type: application/json' \
  -d '{
    "role_in_story": "savior",
    "appearance_timing": "climax",
    "appearance_duration_sec": 12
  }'
```

### Step 3：建镜头时设 product_focus_level

`product_focus_level` 是这套多图参考能力的核心调度参数，4 档语义：

| focus_level | 含义 | view_angle 优先级序列 |
| --- | --- | --- |
| `hero` | 主角化展示，高聚焦 | `[FRONT, THREE_QUARTER, DETAIL]` |
| `functional` | 功能展示，近距 | `[DETAIL, THREE_QUARTER, FRONT]` |
| `subtle` | 弱植入，画面主体不是商品 | `[THREE_QUARTER, FRONT]` |
| `none` | 不挂参考图，走 t2v | （不传参考图） |

序列的含义：`ShotProductReferenceResolver` 会按这个顺序去 `ProductImage` 里挑图，能挑到的全部进入候选池，挑不到就跳过。所以同一个商品，给 `hero` 镜头会优先吃 `FRONT`，给 `functional` 镜头会优先吃 `DETAIL`。

建镜头：

```bash
curl -X POST http://127.0.0.1:8088/api/v1/studio/shots \
  -H 'Content-Type: application/json' \
  -d '{
    "chapter_id": "ch-007",
    "title": "客厅特写",
    "audio_strategy": "silent_with_tts",
    "product_focus_level": "hero",
    "linked_product_id": "prod-001"
  }'
```

`audio_strategy` 决定生成完视频后下一棒派发的是 `tts_generate` 还是 `asr_subtitle_generate`，这条会被链路派发用，详见 Step 5。

### Step 4：派发 video_generation

```bash
curl -X POST http://127.0.0.1:8088/api/v1/film/tasks/video \
  -H 'Content-Type: application/json' \
  -d '{
    "shot_id": "shot-042",
    "model": "happyhorse-1.0-r2v",
    "reference_mode": "multi_ref",
    "resolution": "720P"
  }'
```

后端在派发时自动跑这套流水：

1. `ShotProductReferenceResolver` 按 `product_focus_level` 的优先级序列从 `ProductImage` 里挑商品参考图。
2. `ReferenceImageBudget` 按 9 槽规则分配：商品 3-5 张、人物 2-3 张、场景 1-2 张。
3. 任何超过 9 张的素材按优先级丢弃，并把丢弃明细写入 task `warning` 字段，前端「任务中心」可以看到。
4. 多个镜头并发派发时按 1.5s 串行 `stagger`，避开 SQLite 写锁与 DashScope 突发限流。
5. 实际请求 DashScope 时，`dashscope_videos.py` 的 `multi_ref` 模式会把这批图组装成 `input.media: [{type:reference_image, url:...}]` 提交。

#### 9 槽分配的具体决策

`ReferenceImageBudget` 不是一刀切，会按当前镜头的真实需求伸缩：

| focus_level | Product 槽 | Character 槽 | Scene 槽 | 备注 |
| --- | --- | --- | --- | --- |
| `hero` | 5 | 3 | 1 | 商品占主导，人物次之，场景压到最少 |
| `functional` | 4 | 2 | 2 | 平衡商品细节与使用场景 |
| `subtle` | 3 | 3 | 2 或 3 | 商品不抢戏，场景与人物拉满 |

如果某个槽对应的素材数量没到上限（比如商品只挂了 3 张 ProductImage、`hero` 槽是 5），剩余名额会让给优先级次高的类目，**不会浪费**。整张参考图清单永远填到 9 张为止，多了截断、少了不补假图。

> 想精细确认实际入参，可以在 worker 日志里 grep `build_run_args` 行，里面会打印出最终提交给 DashScope 的 `input.media` 列表。

### Step 5：轮询任务结果与链路派发

```bash
# 5s 间隔轮询
curl http://127.0.0.1:8088/api/v1/film/tasks/<task_id>/status

# 完成后取结果
curl http://127.0.0.1:8088/api/v1/film/tasks/<task_id>/result
```

`result` 里会带视频 `file_id`。后端在 `success` 时按 `audio_strategy` 自动 chain dispatch：

- `silent_with_tts` → 派发 `tts_generate`，把对白配音上去。
- `keep_native` → 派发 `asr_subtitle_generate`，从原声拉字幕。
- `dubbed_video_file_id` 已存在时跳过 TTS。

链路任务在「任务中心」可见，业务上下文（提示词、参考图明细）回到分镜工作室对应面板看，不在任务中心展开。

#### 一图看清整条派发链

```
POST /film/tasks/video (multi_ref)
        ↓
ShotProductReferenceResolver  ← product_focus_level 选 view_angle
        ↓
ReferenceImageBudget (9 槽)    ← Product/Character/Scene 配额
        ↓
dashscope_videos.multi_ref     ← input.media[] 提交 DashScope
        ↓
任务完成 → audio_strategy 决定下一棒
        ├─ silent_with_tts  → tts_generate
        └─ keep_native      → asr_subtitle_generate
```

## 故障排查

### multi_ref 报「max 9 references」错误

正常路径下不应该报。`ReferenceImageBudget` 在派发前就已经截断到 9 张，请求体不可能超量。如果还报，按这个顺序查：

1. 看 task `warning` 字段是否记录了截断明细，没记录说明 budget 没跑。
2. 抓 worker 日志里的 `build_run_args` 行，确认提交给 DashScope 的 `input.media` 长度。
3. 检查是不是有手动绕过 resolver 直接传 `reference_images` 的旧调用方式（已不推荐）。

### 商品视觉不一致

按以下顺序排查：

1. **角度太单薄**：只挂了 `FRONT` 一张，模型只能基于一个角度推断其他视角。补 `THREE_QUARTER` 与 `DETAIL`。
2. **质量等级低**：把关键 `view_angle` 的 `quality_level` 升到 `ULTRA`。
3. **focus_level 不匹配**：`subtle` 镜头里画面主体不是商品，模型会自由发挥；这种镜头本来就不应该追求高一致性。要追一致性就用 `hero` 或 `functional`。
4. **同项目内 ProductImage 在不同镜头被随机挑**：检查 resolver 是否被多个镜头共享了同一组候选池，必要时手动锁定 `linked_product_id`。

### r2v 配额报 429

DashScope 默认 RPS 限流（参考 RPS=20）。前端批量入队前预估总并发，必要时调大派发的 `stagger` 间隔（默认 1.5s）。短时间反复触发可以把入队动作拉到后台串行队列。

### subtle 镜头还是出现商品大特写

`subtle` 只控制后端选图序列，不控制 prompt 里的镜头描述。模型最终听 prompt 多于听参考图。补救：

- prompt 里加 `background, blurred, out of focus, off-center` 这类抑制词。
- 检查参考图本身是不是全是大特写（`DETAIL`），换成 `THREE_QUARTER` 主导。
- 把 `product_focus_level` 改成 `none`，彻底走 t2v 不传参考图。

### 成本超预算

`happyhorse-1.0-r2v` 当前两档分辨率：

| resolution | 单价 |
| --- | --- |
| `720P` | 0.9 元/秒 |
| `1080P` | 1.6 元/秒 |

推荐流程：先用 `720P` 把 prompt、参考图组合验稿到位，再把同样的输入升到 `1080P` 出片。不要一上来就 1080P 反复试错。

## 命令速查

| 场景 | 命令 |
| --- | --- |
| 列商品的所有 ProductImage | `curl http://127.0.0.1:8088/api/v1/studio/products/prod-001/images` |
| 上传 ProductImage 文件 | `curl -X POST http://127.0.0.1:8088/api/v1/studio/files -F "file=@front.png"` |
| 绑定 ProductImage 到商品 | `curl -X POST http://127.0.0.1:8088/api/v1/studio/products/prod-001/images -H 'Content-Type: application/json' -d '{"file_id":"<id>","view_angle":"FRONT","quality_level":"HIGH"}'` |
| 挂商品到项目 | `curl -X POST http://127.0.0.1:8088/api/v1/studio/story-projects/proj-009/products/prod-001 -H 'Content-Type: application/json' -d '{"role_in_story":"savior","appearance_timing":"climax","appearance_duration_sec":12}'` |
| 建镜头并设 focus_level | `curl -X POST http://127.0.0.1:8088/api/v1/studio/shots -H 'Content-Type: application/json' -d '{"chapter_id":"ch-007","product_focus_level":"hero","audio_strategy":"silent_with_tts","linked_product_id":"prod-001"}'` |
| 触发 r2v multi_ref 视频生成 | `curl -X POST http://127.0.0.1:8088/api/v1/film/tasks/video -H 'Content-Type: application/json' -d '{"shot_id":"shot-042","model":"happyhorse-1.0-r2v","reference_mode":"multi_ref","resolution":"720P"}'` |
| 轮询任务状态 | `curl http://127.0.0.1:8088/api/v1/film/tasks/<task_id>/status` |
| 取任务结果 | `curl http://127.0.0.1:8088/api/v1/film/tasks/<task_id>/result` |
| 同步前端 OpenAPI 客户端 | `cd front && pnpm run openapi:update` |

## 相关文档

- 数据模型与 W16/W21 落地版：[commerce-story-data-model](/docs/architecture/commerce-story-data-model/#visual-production-layerw16w21-落地版)
- 配音音色配置：[voice-pack-setup](/docs/guide/voice-pack-setup/)
- 字幕样式配置：[subtitle-style-config](/docs/guide/subtitle-style-config/)
- 视频能力声明源码：`backend/app/core/integrations/aliyun/video_capabilities.py`
- 9 槽预算分配源码：`backend/app/services/studio/reference_image_budget.py`
