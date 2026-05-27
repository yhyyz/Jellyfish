---
title: "W19b 发布说明 — 商品剧情 keep_native 平台 e2e 落地"
date: 2026-05-27
description: "Jellyfish W19b 通过 12+ 后端修复打通商品剧情 keep_native 链路：100% 平台 HTTP API 跑通 5-shot 1080×1920 自带原音 + ASR 反推字幕成片，消除 dev DB 跨连接 visibility race 与 chain dispatch 时序漏洞。"
tags:
  - release
  - w19b
  - commerce
  - keep-native
  - chapter-av-export
  - mysql
  - dev-experience
authors:
  - Jellyfish Team
---

`W19b` 是 W19 章节级 AV 合成（chapter_av_export）能力闭环后的一次稳定性收尾。
本 wave 不引入新功能，仅通过 12 个后端修复彻底解决了「dev SQLite WAL 锁竞争 / MySQL 跨连接 visibility race / chain dispatch send_task before commit / ASR→subtitle 缺失链 / 多个 REST 错误码与 FK 顺序问题」。
落地结果：商品剧情 `keep_native` 链路通过 100% 平台 HTTP API 跑通，无需任何 worker 内置 hack 或脚本桥接，输出 5-shot 1080×1920 25.8s 自带原音 + ASR 反推字幕烧录的成片。

## Highlights

- 🎬 **keep_native 商品剧情 e2e 100% 平台 HTTP API 跑通**：从 `POST /api/v1/studio/products` 到 `POST /api/v1/studio/chapters/{id}/av-export` 全链路无脚本兜底。
- 🎵 **chapter_av_export 自带原音 + ASR 反推字幕烧录**：输出 1080×1920 25.8s H.264 + AAC 成片，字幕走 `douyin_default` 风格安全区烧录。
- 🛠️ **12 个后端修复消除 dev DB 跨请求 visibility race**：覆盖 SQLite WAL / sync_engine / busy_timeout / SAVEPOINT retry / FastAPI yield-after-response / aiomysql init_command 全链路。
- 🔁 **chain dispatch 时序契约固化**：`send_task` 必须在 service-layer commit 之后调用，消除 worker 早于 DB 可见的偶发失败。
- 📊 **公网示例**：`https://dxs9dnjebzm6y.cloudfront.net/tmp/W19b-FINAL-platform-keepnative-1779858873.mp4`。
- ⏱️ **生成耗时 680.9 秒**：5 路 r2v 并发 + ASR 反推 + render + export，含全程平台调度。

## Added

- `app/api/v1/commerce/`：5 个 commerce HTTP routes（W19-finalize 已落地，W19b 中保持稳定，无新增端点）。
- chain dispatch ASR→subtitle 自动接通：`audio_strategy=keep_native` 镜头在 r2v 完成后自动派发 ASR 反推 + subtitle generate，无需调用方显式触发（commit `6453706`）。
- service-layer **commit-before-dispatch 契约**：所有跨 worker chain 在 service 层显式 `await session.commit()` 后再 `send_task`，固化为新写 worker 的强约束（commit `6453706`）。

## Changed

- 后端 dev DB 引擎推荐切换到 **MySQL 8 + READ COMMITTED**：SQLite 仍兼容，但在多 worker 并发场景下有写锁竞争上限。
- aiomysql 连接初始化注入 `init_command='SET SESSION TRANSACTION ISOLATION LEVEL READ COMMITTED'`：消除 InnoDB 默认 REPEATABLE READ 在长连接 session 内导致的跨请求 stale read（commit `2597db8`）。
- SQLite sync engine 改用 `NullPool` + `connect_args={"isolation_level": None, "timeout": 60}`：避免连接池缓存 WAL session 状态导致 `database is locked`（commit `c63f06d`）。
- file insert SAVEPOINT retry budget 6 → 30：在并发 r2v 写入压力下覆盖 SQLite busy_timeout 抖动（commit `afdd75c`）。
- `bootstrap_async_state` 在 dev MySQL 流程下增加显式 `init_db.py` + `alembic upgrade head` 步骤（见 Migration Guide）。

## Fixed

| ID | 修复内容 | Commit |
|----|----------|--------|
| W19b-T1 | SQLite WAL 跨 session visibility race（B1）：commit 后另一个 connection 仍读不到 | `f434bee` |
| W19b-T1b | story-project create FK 顺序错误（先 link 后 entity 导致 IntegrityError） | `42c634b` |
| W19b-T1c | `db_sync.py` 同步引擎漏配 `isolation_level=None` + 显式 `begin()` | `153e6d4` |
| W19b-T1d | SQLite `busy_timeout` 15s → 60s 容忍并发 r2v 写入 | `f9a8c66` |
| W19b-T1e | `busy_timeout` 走 `connect_args` + sync engine 切 `NullPool` 避免连接池缓存锁状态 | `c63f06d` |
| W19b-T1f | file insert 在 `database is locked` 上加 SAVEPOINT retry | `7f6cab3` |
| W19b-T1g | SAVEPOINT retry budget 6 → 30 + 显式 PRAGMA 兜底 | `afdd75c` |
| W19b-T2 | chain dispatch `send_task` 必须在 service commit 之后（B2）+ ASR→subtitle 自动接通（B3/B6） | `6453706` |
| W19b-T2a | MySQL READ COMMITTED 隔离级别消除跨请求 visibility race | `b76e29d` |
| W19b-T2b | aiomysql `connect_args.init_command` 强制 READ COMMITTED（修补 SQLAlchemy 不传隔离级别给 driver） | `2597db8` |
| W19b-FK | shot_id linkage 在 chapter_av_export 中按 narrative order 显式重建（消除遗留空 linkage） | 收敛在 `6453706` |
| W19b-REST | create endpoint 重复 ID 错误码 400 → 409（符合 REST 语义） | 收敛在 `5446050` / `42c634b` |

## Breaking Changes

- **dev DB 推荐切 MySQL**：SQLite 在 4+ 并发 r2v worker 写入场景下有写锁竞争上限，本 wave 不再保证 SQLite 在 commerce e2e 全链路稳定通过；功能仍兼容，但**不再作为推荐 dev 配置**。
- **create endpoint 重复 ID 现在返回 `409 Conflict`**（旧版本是 `400 Bad Request`）：
  - 影响范围：`POST /api/v1/studio/products`、`POST /api/v1/commerce/story-projects` 等所有 create 路由。
  - 调用方需更新错误码处理：`if status == 409` 表示资源已存在，`400` 现在仅用于参数校验失败。

## Deprecations

无。本 wave 未引入新的废弃路径。

## Security

- 无新增依赖、无凭证轮换。
- aiomysql `init_command` 注入仅作用于 SESSION 级隔离级别，不修改 DB 全局配置。

## Known Issues

- SQLite 在 dev 环境下若仍坚持使用，需手动设置 `JF_DB_BUSY_TIMEOUT=60` 且并发 worker 数 ≤ 2，否则可能在 chapter_av_export 阶段命中 `database is locked`。
- ASR 反推字幕在 `audio_strategy=keep_native` 路径下依赖 r2v 输出包含可识别人声，如 r2v 输出为纯环境音则 subtitle 为空（属预期行为，不计入失败）。
- 本 wave 输出成片由 5 路 r2v + ASR + render 串联，长链路总耗时 ~680s；后续 wave 计划在 r2v 与 ASR 之间引入并行调度。

## Migration Guide

### 从 SQLite 切到 MySQL（推荐 dev 路径）

```bash
# 1. 起 MySQL（compose 已带）
cd deploy/compose
cp .env.example .env  # 编辑 MYSQL_PASSWORD
docker compose --env-file .env -f docker-compose.yml up -d mysql

# 2. 设置 backend .env
cd backend
cat >> .env <<'EOF'
DATABASE_URL=mysql+aiomysql://jellyfish:<password>@127.0.0.1:3306/jellyfish_dev
DATABASE_SYNC_URL=mysql+pymysql://jellyfish:<password>@127.0.0.1:3306/jellyfish_dev
EOF

# 3. 初始化 schema + bootstrap seed
uv run python -m app.scripts.init_db
uv run alembic upgrade head
uv run python -m app.scripts.bootstrap

# 4. 起 backend + worker
uv run uvicorn app.main:app --reload --host 0.0.0.0 --port 8000
uv run celery -A app.worker_app worker -l info
```

### 错误码迁移（client 侧）

```diff
- if response.status_code == 400 and "already exists" in body:
+ if response.status_code == 409:
      handle_duplicate_resource()
```

## Rollback Notes

本 wave 全部为修复型 commit，未变更 schema、未引入 alembic migration，可安全回滚到 W19-finalize（commit `5446050`）：

```bash
GIT_MASTER=1 git checkout 5446050
```

回滚后行为：
- chapter_av_export 仍可用，但失去 chain dispatch commit-before-send 保障，并发场景下偶发 worker 取不到刚写入的记录。
- create endpoint 错误码恢复 400。

不需要 DB 数据回滚动作。

## Compatibility Matrix

| 组件 | 版本 | 状态 |
|------|------|------|
| Python | 3.12+ | 不变 |
| FastAPI | unchanged | 不变 |
| SQLAlchemy | unchanged | 不变 |
| Celery | unchanged | 不变 |
| MySQL | 8.0+ | **推荐**（dev + prod 一致） |
| SQLite | 3.40+ | 兼容但不推荐（dev 多 worker 场景） |
| aiomysql | unchanged | 需要支持 `init_command` |
| 前端 generated client | 无 schema 变化 | 不需要重新生成 |

## Validation Commands

```bash
# 后端单元 + 服务层测试
cd backend
uv run pytest -q

# 后端静态校验
uv run pylint app

# 端到端：起完整栈后，跑 keep_native 商品剧情完整链路
uv run pytest backend/tests/test_commerce_keepnative_e2e_smoke.py -v

# 前端类型校验（本 wave 无 OpenAPI 变化，仅做兜底）
cd front
pnpm exec tsc --noEmit
```

## Upgrade Checklist

- [ ] 已起 MySQL 8 容器，`DATABASE_URL` / `DATABASE_SYNC_URL` 已切换。
- [ ] 已运行 `init_db.py` + `alembic upgrade head` + `bootstrap`。
- [ ] 已重启 backend 与所有 celery worker（旧连接池需丢弃）。
- [ ] 已更新 client 侧 create 错误码处理（400 → 409）。
- [ ] 已用 `pytest -q` 跑通后端测试。
- [ ] 已尝试一次 `chapter_av_export`，确认输出包含原音 + 字幕。

## References

- 公网示例成片：<https://dxs9dnjebzm6y.cloudfront.net/tmp/W19b-FINAL-platform-keepnative-1779858873.mp4>
- 关联 commit 范围：`5446050..2597db8`（含 W19-finalize 与 W19b-T1 / T1b–T1g / T2 / T2a / T2b 共 11 个 commit）。
- 上一个 wave：[v0.5.0 发布说明](./v0-5-0.md) — 剧情带货生产级。
- 章节级 AV 合成（chapter_av_export）落地说明详见 `site/content/docs/architecture/`。

## Notes for Contributors

- 新写 chain dispatch worker 必须遵守 **commit-before-send_task** 契约：
  - 在 service 层显式 `await session.commit()`，再调用 `send_task`。
  - 任何跨连接读取另一 worker 写入的记录都按 W19b-T2a / T2b 路径处理（READ COMMITTED + 显式 commit）。
- 新增 SQLite 兼容代码需走 `connect_args` 而非 SQLAlchemy `execution_options`，避免连接池层级配置丢失。
- create 路由重复 ID 必须返回 `409`，并附 `detail` 说明 conflict 字段。

## Acknowledgements

- 后端稳定性收尾：Jellyfish Team
- e2e 跑通验证：Jellyfish Team
