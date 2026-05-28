---
title: "视觉一致性引擎"
weight: 52
description: "DINOv2 ViT-B/14 sidecar、shot_consistency_check task、阈值规则与 chapter_av_export 前置门当前生效的实现。"
---

> 本文属于"当前架构"文档，描述 P4 Wave 27 落地后 `dev` 分支真实生效的视觉一致性引擎子系统。

## 边界

视觉一致性引擎在每个 r2v 视频生成产出后，抽样 N 帧，与 `ProductImage` 参考图做 cosine 相似度比对，给镜头打 `consistency_score`。当前真实生效的边界：

- 触发：`generated_video` 视频成功后 chain dispatch 触发 `shot_consistency_check` task。
- 模型：HF `facebook/dinov2-base` ViT-B/14，768-dim L2-归一化 embedding。
- 部署：**ML stack 完全隔离在独立 sidecar 服务**（决策 D-VISION-DEPLOY=sidecar），主镜像不引入 torch / transformers。
- 阈值：≥ 0.85 通过 / 0.75–0.85 警告 / < 0.75 自动重生（最多 2 次）。
- 集成：`chapter_av_export` 前置门校验所有镜头的 consistency_status，fail 即拒绝导出。

## 整体架构

```text
[backend 主进程]
    |
    | (httpx async POST)
    v
[inference-dinov2 sidecar (FastAPI)]
    ├── lifespan startup → 懒加载模型权重 (HF_HOME 持久化卷)
    ├── POST /embed (multipart/form b64/url)
    ├── POST /embed-json (JSON b64)
    ├── POST /similarity (frame_b64 + reference_b64)
    └── GET /health (status / model_loaded / device / embed_dim)
```

主镜像与 sidecar 独立打包：

- 主镜像保持轻量（不增 torch / transformers / pillow GPU 依赖）。
- sidecar 镜像基于 `python:3.11-slim`，CPU 优先 / GPU 可选。
- sidecar 仅暴露 HTTP 接口，零业务逻辑泄漏到 ML 进程。

## DINOv2 sidecar

实现：`deploy/inference-dinov2/`。

### Dockerfile + requirements

- base image：`python:3.11-slim`
- 依赖：`torch + transformers + pillow + fastapi + uvicorn`
- HF 权重缓存：`HF_HOME=/models`（compose 中挂卷 `dinov2_models`，避免重启重新下载 ~330 MB）
- 启动方式：`uvicorn app.main:app`，端口 8001（`DINOV2_SIDECAR_PORT` 可覆盖）

### app/main.py + app/model.py

- lifespan startup hook 触发懒加载权重，避免 docker build 阶段下载
- 进程级模型互斥锁（同一个进程内 inference 串行，避免显存竞争）
- POST `/embed` 接受 multipart 文件 / form b64 / form url 三种输入形态 → 返回 768-dim L2-归一 embedding
- POST `/embed-json` 用 JSON body 传 b64（适合 backend HTTP 调用）
- POST `/similarity` 接受 `frame_b64 + reference_b64` 同时计算两端 embedding + cosine
- GET `/health` 返回 `{status, model_loaded, device, embed_dim}`
- 503 失败语义（模型未加载 / 加载失败时）

### compose 接入

`deploy/compose/docker-compose.yml` 加 `inference-dinov2` service：

- 端口：`${DINOV2_SIDECAR_PORT:-8001}:8001`
- volume：`dinov2_models:/models`（HF_HOME）
- healthcheck：`/health` interval=30s start_period=120s
- GPU 加速段（`deploy.resources.reservations.devices`）以注释形式存在，按需启用

## Backend 接入层

### 契约

`backend/app/core/contracts/visual_consistency.py`：

- `EmbedRequest` / `EmbedResponse` (768-dim float list)
- `SimilarityRequest` / `SimilarityResponse` (cosine ∈ [-1, 1])
- `ConsistencyScoreResult` (worker 输出 DTO)

### httpx adapter

实现：`backend/app/core/integrations/dinov2/client.py`。

- 基于 `httpx.AsyncClient`
- 503 / connect / read-timeout 指数退避重试（默认 3 次 × 1.5s base）
- 4xx 立即抛 `Dinov2SidecarError`，不重试（防止把客户端 bug 当成服务端不可用）
- 维度防御：返回的 embedding `dim != 768` 直接拒绝
- `async with` 自动释放 owned client；外部传入 client 时不双关

env 配置（`backend/app/config.py`）：

| 变量 | 默认 | 说明 |
| --- | --- | --- |
| `DINOV2_SIDECAR_BASE_URL` | `http://inference-dinov2:8001` | sidecar 基址 |
| `DINOV2_TIMEOUT_S` | 5 | 单次 HTTP 超时 |
| `DINOV2_RETRIES` | 3 | 重试次数 |
| `DINOV2_RETRY_BACKOFF_S` | 1.5 | 退避基数 |

`timeout × retries = 15s << worker 600s`，留足兜底窗口。

## shot_consistency_check task

实现：`backend/app/services/visual_consistency/consistency_worker.py`。

注册：`task_kind = shot_consistency_check`，slow 队列，超时 600s。

### 抽帧

实现：`backend/app/services/visual_consistency/sampler.py`（纯函数 ffmpeg / ffprobe 参数构造器）：

- `compute_step` / `make_plan`：按总帧数 vs 目标采样数（默认 6）规划抽样：
  - `total < target` → 全部抽
  - `total = target` → 1:1
  - `total >> target` → 等距采样
- `parse_probe_total_frames`：`nb_read_packets > nb_frames > duration*fps` 三档回退（不同容器 ffprobe 输出字段不一致）
- `build_sample_args`：严格转义 `select` 表达式中的逗号（防 shell injection）

### 主路径

```text
1. shot_id → 反查 GeneratedVideo（最新成功）的 storage_key
2. ffprobe 取 mp4 总帧数
3. ffmpeg 抽 N=6 帧（base64 in-memory，不落盘）
4. 6 次 sidecar /embed → 平均 + L2 归一化（纯 Python，主镜像不引 numpy）
5. 反查 ProductImage：FRONT 角度优先，THREE_QUARTER 兜底
6. ProductImage → /embed → reference_embedding
7. cosine(avg_frame_embedding, reference_embedding) → score ∈ [-1, 1]
8. 写 GenerationTask.result 与 Shot.consistency_score
9. 接入 threshold_engine 决定 status + 是否触发 regen
```

### 失败兜底

- 缺 reference ProductImage → `score = null`，`reason = "no_reference"`
- 抽帧 0 帧 → `score = null`，`reason = "no_frames"`
- sidecar 不可达 → `score = null`，`reason = "sidecar_unavailable"`
- 不抛异常阻塞主流程（视觉一致性是质量门，不是硬阻断）

数据落地：

- `models/studio_shots.py` 加 `consistency_score: Mapped[float | None]`
- alembic `0015_p4_shot_consistency_score`：`ALTER TABLE shots ADD COLUMN consistency_score FLOAT NULL`

## 阈值规则与自动 regen

实现：`backend/app/services/visual_consistency/threshold_engine.py`。

判定函数（纯函数）：

```python
def evaluate(
    score: float | None,
    retry_count: int,
) -> tuple[Literal["pass", "warning", "fail", "unknown"], bool]
```

返回 `(status, should_regen)`：

| score | retry_count | status | should_regen |
| --- | --- | --- | --- |
| `>= 0.85` | any | `pass` | `False` |
| `0.75 <= s < 0.85` | any | `warning` | `False` |
| `< 0.75` | `< 2` | `fail` | `True` |
| `< 0.75` | `>= 2` | `fail` | `False`（用尽 budget） |
| `None` | any | `unknown` | `False` |

数据落地：

- alembic `0017_p4_consistency_status_retry`：shots 表加 `consistency_status` 字符串 + `consistency_retry_count` 整数

### 自动 regen 闭环

- `generated_video` 视频成功后 chain dispatch（W19b commit-then-send）触发 `shot_consistency_check`
- `shot_consistency_check` 跑完 → 接入 `threshold_engine.evaluate(...)`
- `should_regen = True` → 通过 `task_dispatch.enqueue_video_generation(...)` 重新入队视频生成
- `consistency_retry_count += 1`，2 次仍 fail → 停留 `fail` 状态，不再 regen

调度入口：`backend/app/services/commerce/task_dispatch.py`：

- `enqueue_video_generation(shot_id, ...)`
- `enqueue_shot_consistency_check(shot_id, ...)`

## consistency badge UI

### 只读端点

实现：`backend/app/api/v1/routes/commerce/shot_consistency.py`。

`GET /api/v1/commerce/shots/{shot_id}/consistency-evidence`：

- 复用 worker 已落地的 `Shot.consistency_score` + ProductImage 反查路径
- 响应 `ConsistencyEvidenceRead`：
  - `score: float | null`
  - `status: "green" | "amber" | "red" | "unknown"`（按 0.85 / 0.75 阈值映射）
  - `frames: list[ConsistencyFrame]`（抽样帧 url + per-frame score）
  - `reference_image_url: string | null`
  - `retry_count: int | null`
- 不存在的 shot → 404
- score = null → status = `unknown`

### 前端组件

实现位置：`front/src/pages/aiStudio/commerce/projects/components/`：

- `ConsistencyBadge.tsx`：score → 色档标签
  - green ≥ 0.85 / amber 0.75–0.85 / red < 0.75 / unknown null
  - onClick 透传 shotId 给上层
- `ConsistencyReviewDrawer.tsx`：抽屉展示
  - antd `Image.PreviewGroup` 横向 N 抽样帧 + 1 张参考图
  - 数值显示（score + per-frame score）
  - `retry_count > 0` 时显示「已重试 N 次」标签
- `ShotTimelineStrip.tsx`：在 breakdown shot 携带 `shot_id` / `consistency_score` 时叠加 `ConsistencyBadge`
- `StoryWorkbench.tsx`：接入 drawer state，点击徽章打开 `ConsistencyReviewDrawer`

OpenAPI generated client：`CommerceShotConsistencyService` + `ConsistencyEvidenceRead` model。

## chapter_av_export 前置门

实现：`backend/app/services/studio/chapter_av_export_task.py`。

新增函数 `_assert_consistency_gates_pass(chapter_id, shots, settings)`：

- `_CONSISTENCY_GATE_OK = frozenset({"pass", "warning", None})`
- 遍历章节涉及镜头：
  - `consistency_status == "fail"` → 收集进 `failing_shot_ids`
  - `consistency_status in {pass, warning}` → 放行
  - `consistency_status is None` → 兜底视为 warning（W27 之前旧数据不卡死现网）
- 若有 fail → 抛 `HTTPException(422, detail={"code": "consistency_gates_failed", "chapter_id": ..., "failing_shot_ids": [...]})`

worker entry 在 ffmpeg 主路径**之前**调用此函数：

```text
chapter_av_export_task.execute(...)
        |
        v
_assert_consistency_gates_pass(chapter_id, shots, settings)
        |
        ├── any shot fail → HTTPException(422) → 任务直接失败
        └── 全 pass / warning / None → 继续 ffmpeg 主合成
```

应急通道（`backend/app/config.py`）：

- `chapter_av_export_bypass_consistency: bool = False`
- env：`CHAPTER_AV_EXPORT_BYPASS_CONSISTENCY=1`
- 设置后跳过此前置门（救急用，不建议长期开）

## 整体调用流程

```text
1. 视频生成 (r2v)
   GenerationTask(task_kind=video_generation) 跑完
        |
        v
   GeneratedVideo 行入库 → commit
        |
        v (chain dispatch, W19b commit-then-send)
   enqueue_shot_consistency_check(shot_id)

2. 一致性检查
   GenerationTask(task_kind=shot_consistency_check) 跑
        |
        v
   ffprobe → ffmpeg 抽 6 帧 → b64
        |
        v (httpx)
   sidecar /embed × 6 + /embed (reference)
        |
        v
   cosine(avg_frame, reference) → score
        |
        v
   threshold_engine.evaluate(score, retry_count)
        ├── pass / warning → done
        ├── fail + retry_count < 2 → enqueue_video_generation (regen)
        └── fail + retry_count >= 2 → 停留 fail 状态
        |
        v
   Shot.consistency_score / consistency_status / consistency_retry_count 落库

3. 章节合成前置门
   chapter_av_export 入口
        |
        v
   _assert_consistency_gates_pass(chapter_id, shots)
        ├── any fail → HTTPException(422) → 任务失败
        └── 全过 → ffmpeg 主合成

4. 前端反馈
   StoryWorkbench / ShotTimelineStrip
        ├── ConsistencyBadge (从 shot.consistency_score 直接渲染)
        └── 点击 → ConsistencyReviewDrawer
                    └── GET /commerce/shots/{shot_id}/consistency-evidence
                          └── 抽样帧 + 参考图 + score
```

## 测试覆盖

后端：

- `tests/services/visual_consistency/test_sampler.py` — 12 cases，纯函数白盒（compute_step / make_plan / parse_probe_total_frames / build_sample_args）
- `tests/core/integrations/dinov2/test_client.py` — 13 cases，`httpx.MockTransport`（503 重试 / 4xx 立即抛 / 维度防御）
- `tests/services/visual_consistency/test_consistency_worker.py` — 10 cases，file-backed SQLite + 全 stub
- `tests/services/visual_consistency/test_threshold_engine.py` — 9 cases，retry 上限 / 边界值 0.75 / 0.85 / chain 时序集成
- `tests/services/studio/test_chapter_av_export_precheck.py` — 5 cases：
  - blocks_when_any_shot_consistency_fail
  - passes_when_all_warning_or_pass_or_none
  - passes_for_empty_shots_list
  - bypass_env_skips_check
  - failing_shot_ids_in_detail (422 detail.code / chapter_id / failing_shot_ids)
- `tests/test_commerce_shot_consistency_api.py` — 6 cases（score_null / 边界 / 红黄绿 / 404）

前端：

- `ConsistencyBadge.test.tsx` — 6 cases
- `ConsistencyReviewDrawer.test.tsx` — 4 cases（含 matchMedia / ResizeObserver polyfill）

## 与 r2v multi_ref pipeline 的协作

- 视觉一致性引擎读的"参考图"来自 `ProductImage`：
  - `FRONT` 角度优先（最适合做整体一致性比对）
  - `THREE_QUARTER` 兜底（次优）
  - 多角度 / 多 ProductImage 当前未做加权平均，仅取单张
- 与 r2v multi_ref pipeline（详见 [guide / r2v 多图参考视频生成](/docs/guide/r2v-multi-reference/)）解耦：
  - r2v multi_ref 在生成阶段把多张参考图喂给视频模型
  - 一致性引擎在生成后用单张 `FRONT` 参考做评分
  - 两者不互相依赖，但同样依赖 `ProductImage` 数据底座

## 已知限制

- DINOv2 模型版本固定为 `facebook/dinov2-base`，未做多模型 / CLIP 备选。
- 抽样帧数固定 6（不可 per-shot 调）。
- 参考图当前仅取 1 张，多张加权未做。
- regen budget 固定 2 次，不可 per-product 配置。
- score < 0.75 但 retry 已用尽时只给 fail 状态，不自动降级到 warning（避免误放行）。
- 主镜像不引 numpy，平均 + L2 + cosine 全用纯 Python 实现，N=6 帧足够，扩到大批量时需重评。

后续演进路线放 `plans/jellyfish-story-commerce.md`，本文不展开。
