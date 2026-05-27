---
title: "持久化引擎与事务边界"
weight: 8
description: "记录当前真实生效的双引擎数据库接入、SQLite/MySQL 配置差异、事务边界契约与 chain dispatch 时序。"
---

> 本文属于"当前架构"文档，描述当前 `dev` 分支真实生效的持久化层接入方式与跨请求可见性约束。
> 与本文相关的任务执行细节见 [任务执行架构](/docs/architecture/task-execution/)。

## 双引擎设计

后端在同一进程内维护两套 SQLAlchemy 引擎，分别服务 Web runtime 与 worker runtime：

```text
async runtime (FastAPI / API 路由)
└── app/db.py         → AsyncEngine + AsyncSession

sync runtime (Celery worker / 一次性脚本)
└── app/db_sync.py    → Engine + Session
```

约束：

- API 层只允许通过 `app/db.py` 拿 `AsyncSession`。
- Worker 层只允许通过 `app/db_sync.py` 拿同步 `Session`。
- 两套引擎共用同一份 `DATABASE_URL` 配置，但驱动 / 连接参数按运行时分别处理（见下文）。

## SQLite 路径（开发态默认）

当 `DATABASE_URL` 指向 SQLite 时，两套引擎都需要满足以下约束才能在多进程 / 多请求并发下保持正确：

- `isolation_level = None` + 显式 `BEGIN` listener
  - SQLAlchemy 默认的 "autobegin" 在 SQLite 上与 WAL 配合不稳，必须把驱动隔离级别置为 None，再由应用层在每个事务起点显式 `BEGIN`。
  - sync 引擎已在 `app/db_sync.py` 注册等价 listener，与 async 引擎对齐。
- `journal_mode = WAL`
  - 启用 WAL 才能允许读写并发：写事务不会阻塞只读连接。
- `foreign_keys = ON`
  - SQLite 默认外键关闭；应用层强制开启，保证与 MySQL 行为一致。
- `busy_timeout = 60000` (60s)
  - 通过 `connect_args` 注入，覆盖驱动默认 5s。开发态多 worker 并行写时，60s 留出足够重试窗口避免立即报 `database is locked`。
- sync 引擎使用 `NullPool`
  - 不复用同步连接，避免长生命周期连接持有写锁造成跨请求阻塞。
- 文件 INSERT 使用 SAVEPOINT retry
  - 高并发下 `files` 表写入仍可能命中 `database is locked`。`file insert` 路径包了 SAVEPOINT 重试（预算 30 次）+ 显式 PRAGMA 兜底，超出预算才让异常向上抛。

## MySQL 路径（生产 / 部署态）

当 `DATABASE_URL` 指向 MySQL 时：

- 隔离级别 = `READ COMMITTED`
  - 通过 `connect_args.init_command = "SET SESSION TRANSACTION ISOLATION LEVEL READ COMMITTED"` 在每条新连接建立时强制设置。
  - 默认的 `REPEATABLE READ` 会让请求 A 看不到请求 B 已 commit 的新行（跨请求 visibility race），破坏 chain dispatch / 长链流水线。
- 连接池 = `NullPool`
  - 同样不复用连接：避免长连接的旧 snapshot 让随后的请求看不到新数据。
- service 层显式 commit
  - 见下一节"事务边界契约"。

## 事务边界契约

跨请求可见性的关键不在 SQLAlchemy，而在**何时 commit**。当前生效的契约是：

> **commit 必须在 service 层的 return 之前完成，不能依赖 FastAPI dependency 的 yield-after-response。**

- `create_and_refresh(...)` / `flush_and_refresh(...)` 等 service helper 内部已经显式 `await session.commit()`，并在 commit 后再 refresh 对象。
- 路由的 `Depends(get_session)` 依赖虽然在请求结束后会做兜底 commit，但那一步发生在响应已经发出之后。
- 反例：路由先返回 200，client 拿到 task_id 后立即发下一个请求查这条 task；如果 commit 还没执行，新请求看到的还是旧 snapshot，会判定"任务不存在"。

因此后端代码不允许"省略 service 层 commit、靠 dependency 兜底"。新加的 service 必须在 return 前 commit，否则 e2e 链路会出现间歇性 visibility race。

## Chain dispatch 时序契约

任务系统的级联派发（如 video_generation 成功 → 派发 ASR / TTS）必须满足：

> **send_task 只能在调用方 commit 之后发生。**

- API 层的 `CommerceTaskDispatchService` 把 `enqueue_*` 系列推迟到 caller commit 之后再真正调 Celery `send_task`。在请求事务里只是登记意图。
- Worker 层的链式派发（如 `run_video_generation_task` 成功路径里派发 `tts_generate` / `asr_subtitle_generate`）也使用 prepare-then-send 模式：先把状态 / 结果写库并 commit，再发 send_task。
- 反例：如果 send_task 早于 commit，被派发的下游任务可能立即被 worker pop 出来执行，而它要读的源行还没在数据库里可见，导致 `not found`。

这条契约在 SQLite 与 MySQL 两套后端上行为一致，是 keep_native / silent_with_tts 双路径流水线能在 100% HTTP API 级别跑通的前提之一。

## keep_native 视频流水线（端到端）

当前 `Shot.audio_strategy = keep_native` 路径在数据库与任务系统层面的真实链路：

```text
1. POST /studio/.../video-generations
   → video_generation worker（aliyun happyhorse-1.0-r2v）
   → 产出含原音的 mp4（Shot.generated_video_file_id）
   → 服务层 commit

2. video_generation 成功路径自动 chain dispatch
   → asr_subtitle_generate（fast queue）
   → DashScope Paraformer-v2 反推字级 word_timestamps
   → 写 ShotDialogLine.start_time_ms / end_time_ms
   → 服务层 commit

3. POST /studio/shots/{id}/subtitle-render
   → shot_subtitle_render worker（fast queue）
   → 输入 source = asr_paraformer_v2
   → 产出 .ass 落 minio + SubtitleTrack 行
   → 服务层 commit

4. PUT /studio/chapters/{id}/timeline
   → 在 ChapterTimelineSegment 上写 subtitle_track_file_id

5. POST /studio/chapters/{id}/av-export
   → chapter_av_export worker（slow queue）
   → ffmpeg 拼段 + concat + loudnorm I=-16:TP=-1.5:LRA=11
   → 字幕硬烧（subtitles= filter）
   → 输出 chapter_master_dubbed mp4
```

每一步之间的可见性都依赖前一节的两条契约：service 层 commit 先完成，下游 send_task 才发出。

silent_with_tts 路径与上面对称：第 2 步分发的是 `tts_generate`（按 ShotDialogLine 逐行），第 3 步字幕 source 改为 `tts_word_timestamps`，其余阶段保持一致。
