# Jellyfish Architecture Improvements Plan

## Overview
- **Goal**: 将 Jellyfish 从"能跑"提升到"生产级"
- **Branch**: `dev` (yhyyz/Jellyfish)
- **Total Effort**: ~33-48 人天
- **Timeline**: 2-3 months

---

## TODOs

### P0 — 立即修复（影响开发效率和稳定性）

- [x] P0-3: 清理死代码（aiStudioApi.ts / http.ts / axios 依赖 / mocks/data.ts 重构）
- [x] P0-1: 拆分 ChapterStudio.tsx（6537行 → 5-6 子组件 + 3 hooks + 消除 24 个 any）
- [x] P0-2: 引入 TanStack Query（替换原始 useEffect+useState 数据获取模式）

### P1 — 短期改进（1-2 周）

- [x] P1-3: 前端路由懒加载（React.lazy + Suspense）
- [x] P1-4: CI 补全前端检查（tsc + build + lint workflow）
- [x] P1-1: 拆分 script_processing.py（1041行 → routes/script/ 子包）
- [x] P1-2: 引入 Alembic 替换手写 SQL 迁移
- [x] P1-5: 替换 openapi-typescript-codegen 为 @hey-api/openapi-ts

### P2 — 中期改进（1-2 月）

- [ ] P2-2: 认证系统（Phase 1: API Key / Phase 2: JWT + 用户）
- [ ] P2-4: 监控 & 可观测性（Prometheus + Grafana + structlog）
- [ ] P2-3: Storage 优化（连接池 + 流式下载 + presigned URL）
- [ ] P2-5: 替换过时依赖（react-beautiful-dnd → dnd-kit / LangChain 版本锁定）
- [ ] P2-1: 任务系统统一（合并双重系统为单一入口）

### P3 — 长期优化（2-3 月）

- [ ] P3-1: WebSocket 替换轮询（任务状态实时推送）
- [ ] P3-2: 前端测试体系（Vitest 单元 + Playwright E2E）
- [ ] P3-3: 安全加固（容器扫描 + 依赖审计 + 限流 + Key 加密）
- [ ] P3-4: 性能优化（DB 连接池 + Redis 缓存 + CDN + 任务队列分离）

---

## Final Verification Wave

- [ ] F1: 全量 TypeScript 类型检查通过（pnpm exec tsc --noEmit）
- [ ] F2: 后端 pylint + 测试通过
- [ ] F3: Docker Compose 完整启动验证
- [ ] F4: 关键路径手动 QA（项目→章节→分镜→生成→导出）

---

## Task Details

### P0-3: 清理死代码
**Effort**: 0.7d | **Risk**: Low | **Dependencies**: None

**Scope**:
- 删除 `front/src/services/aiStudioApi.ts`
- 删除 `front/src/services/http.ts`
- 从 `package.json` 移除 `axios` 依赖
- 验证无其他文件引用这些模块
- 确认 MSW mock 系统仍可正常工作

**Acceptance Criteria**:
- `pnpm exec tsc --noEmit` 通过
- `pnpm run build` 成功
- 无文件引用已删除模块
- MSW 开发模式 (`VITE_USE_MOCK=true`) 可选地仍然可用

---

### P0-1: 拆分 ChapterStudio.tsx
**Effort**: 4d | **Risk**: Medium | **Dependencies**: P0-3

**Scope**:
- 分析 ChapterStudio 内部 state 依赖图
- 提取 3 个自定义 hooks:
  - `useChapterGeneration.ts` (生成逻辑 + 任务状态)
  - `useChapterShots.ts` (镜头列表 + 选择 + 排序)
  - `useChapterSettings.ts` (模型配置 + 参数)
- 拆分 5-6 个 UI 子组件:
  - `GenerationPanel.tsx` (生成参数 + 触发按钮)
  - `PreviewPane.tsx` (视频/图片预览区域)
  - `ShotList.tsx` (镜头列表 + 状态标记)
  - `BatchToolbar.tsx` (批量操作工具栏)
  - `SettingsDrawer.tsx` (模型/参数配置抽屉)
- 消除所有 24 个 `any` 类型，替换为 generated types
- 壳层 ChapterStudio.tsx 控制在 200 行以内

**Acceptance Criteria**:
- `pnpm exec tsc --noEmit` 零 error
- 拆分后功能与原始完全一致
- 无 `any` 类型逃逸
- 每个子组件 < 500 行

---

### P0-2: 引入 TanStack Query
**Effort**: 2.5d | **Risk**: Low-Medium | **Dependencies**: P0-1

**Scope**:
- 安装 `@tanstack/react-query` + `@tanstack/react-query-devtools`
- 在 App 根层加入 `QueryClientProvider`
- 迁移 5 个核心页面的数据获取:
  - ProjectLobby (项目列表)
  - ChapterShotsPage (镜头列表)
  - AssetManager (资产列表)
  - ModelManagement (模型列表)
  - FileManager (文件列表)
- 为 mutation 操作加乐观更新
- 任务轮询改用 `useQuery` 的 `refetchInterval`

**Acceptance Criteria**:
- 所有迁移页面加载正常
- 导航间数据缓存生效（不重复请求）
- `tsc --noEmit` 通过
- DevTools 可正常显示 query 状态

---

### P1-3: 前端路由懒加载
**Effort**: 0.8d | **Risk**: Low | **Dependencies**: None

**Scope**:
- 对 6 个大页面加 `React.lazy()`:
  - ChapterStudio / VideoEditor / AssetManager / ModelManagement / AgentManagement / PromptTemplateManager
- 添加统一 `<Suspense fallback={<PageSkeleton />}>` 组件
- 可选：加 `vite-plugin-visualizer` 分析 bundle 变化

**Acceptance Criteria**:
- 路由切换正常，无白屏
- 首屏 bundle 明显减小
- `pnpm run build` 输出多个 chunk

---

### P1-4: CI 补全前端检查
**Effort**: 0.8d | **Risk**: Low | **Dependencies**: None

**Scope**:
- 新建 `.github/workflows/frontend-check.yml`
- 触发条件：PR 修改 `front/**` 文件
- 步骤：pnpm install → tsc --noEmit → pnpm run build → pnpm run lint
- 修复现有 lint/type 存量告警

**Acceptance Criteria**:
- Workflow 在 PR 中自动触发
- 当前代码可通过全部检查
- 告警为零或记录在案

---

### P1-1: 拆分 script_processing.py
**Effort**: 1d | **Risk**: Low | **Dependencies**: None

**Scope**:
- 创建 `backend/app/api/v1/routes/script/` 子包
- 按职责拆分:
  - `divide.py` (剧本分镜)
  - `extract.py` (角色/场景/道具/服装提取)
  - `consistency.py` (一致性检查)
  - `optimization.py` (优化/精简)
  - `analysis.py` (人物画像/场景分析)
- 更新 `v1/__init__.py` router 注册
- 验证 OpenAPI spec 输出不变

**Acceptance Criteria**:
- `openapi.json` diff 仅有排序变化（无语义变化）
- 后端启动正常
- 原有测试通过

---

### P1-2: 引入 Alembic
**Effort**: 3d | **Risk**: Medium | **Dependencies**: None

**Scope**:
- `alembic init backend/alembic` + 配置 async engine
- 从现有 ORM 生成 baseline migration
- 将 9 个 SQL 文件逻辑转为 Alembic versions
- 修改 docker-compose 使用 `alembic upgrade head`
- 保留 `init_db.py` 作为 fallback

**Acceptance Criteria**:
- 空库执行 `alembic upgrade head` 可创建完整 schema
- 现有数据库执行 `alembic stamp head` 标记 baseline
- docker-compose 启动正常
- `alembic downgrade -1` 可回退最后一次迁移

---

### P1-5: 替换 openapi-typescript-codegen
**Effort**: 1.3d | **Risk**: Low-Medium | **Dependencies**: None

**Scope**:
- 评估 `@hey-api/openapi-ts` 迁移兼容性
- 替换 package.json 生成脚本
- 调整 import 路径适配新 client 结构
- 全量 typecheck 验证

**Acceptance Criteria**:
- `pnpm run openapi:update` 正常生成
- `pnpm exec tsc --noEmit` 通过
- API 调用行为不变

---

### P2-2: 认证系统
**Effort**: 4d | **Risk**: Medium | **Dependencies**: P1-2 (需要迁移支持新表)

**Scope**:
- Phase 1 (0.5d): API Key 中间件 (Header X-API-Key + config)
- Phase 2 (3.5d): JWT 登录 / 用户表 / 前端登录页 / token 管理 / 路由守卫

**Acceptance Criteria**:
- 无 token 请求返回 401
- 登录流程完整可用
- Token 刷新机制正常

---

### P2-4: 监控 & 可观测性
**Effort**: 2d | **Risk**: Low | **Dependencies**: None

**Scope**:
- docker-compose 添加 Prometheus + Grafana
- FastAPI prometheus middleware
- Celery metrics exporter
- structlog 替换标准 logging + correlation ID
- 基础 Dashboard（请求延迟/任务队列/错误率）

**Acceptance Criteria**:
- Grafana Dashboard 可展示实时指标
- 日志包含 request_id
- Prometheus targets 全部 UP

---

### P2-3: Storage 优化
**Effort**: 1.8d | **Risk**: Low | **Dependencies**: None

**Scope**:
- S3 客户端单例 + 连接复用
- 流式下载 API (`download_file_stream`)
- Presigned URL 生成（浏览器直传大文件）
- 文件清理策略（orphan detection）

**Acceptance Criteria**:
- 大文件下载不 OOM
- Presigned URL 可在浏览器直接上传
- 孤立文件可被检测

---

### P2-5: 替换过时依赖
**Effort**: 1.2d | **Risk**: Medium | **Dependencies**: None

**Scope**:
- `react-beautiful-dnd` → `@dnd-kit/core` (API 重写)
- LangChain 版本上限锁定 (`<0.4.0`)

**Acceptance Criteria**:
- 拖拽功能正常
- LangChain 不会意外升级到 breaking version

---

### P2-1: 任务系统统一
**Effort**: 7.5d | **Risk**: High | **Dependencies**: P2-4 (监控先行，方便验证)

**Scope**:
- task_manager 作为唯一生命周期入口
- Celery worker 退化为纯分发层
- 去掉 SyncSqlAlchemyTaskStore
- 迁移 13 个 task_kind
- 全量回归测试

**Acceptance Criteria**:
- 所有 13 个 task_kind 正常执行
- 无双重状态更新
- 任务取消/超时/重试正常

---

### P3-1: WebSocket 替换轮询
**Effort**: 2.3d | **Risk**: Medium | **Dependencies**: P2-1

**Scope**:
- 后端 WebSocket endpoint + Redis pub/sub
- 前端 useWebSocket hook (自动重连 + 心跳)
- 迁移 TaskRuntimeProvider
- Fallback polling 机制

**Acceptance Criteria**:
- 任务状态 < 1s 延迟推送
- 断线自动重连
- WS 不可用时自动回退 polling

---

### P3-2: 前端测试体系
**Effort**: 6d | **Risk**: Low | **Dependencies**: P0-1 (组件拆分后更易测试)

**Scope**:
- Vitest 配置 + 核心 hooks 单测 (10-15)
- 核心组件快照测试 (5-8)
- Playwright E2E 配置 + 关键路径 (3-5 flows)
- CI 集成

**Acceptance Criteria**:
- 单测覆盖核心 hooks 80%+
- E2E 覆盖主流程
- CI 自动运行

---

### P3-3: 安全加固
**Effort**: 1.7d | **Risk**: Low | **Dependencies**: P2-2

**Scope**:
- CI trivy 容器扫描
- CI pip-audit 依赖扫描
- API 限流 (slowapi)
- API Key 加密存储 (Fernet)
- HTTPS + CSP header

**Acceptance Criteria**:
- CI 扫描通过
- 暴力请求被限流
- DB 中 Key 字段加密

---

### P3-4: 性能优化
**Effort**: 1.7d | **Risk**: Low | **Dependencies**: P2-4

**Scope**:
- DB 连接池调优
- Redis 缓存热数据
- 前端图片懒加载 + CDN
- Celery 任务优先级队列

**Acceptance Criteria**:
- DB 连接不泄漏
- 热数据响应 < 50ms
- 慢任务不阻塞快任务

---

## Execution Notes

- P0 系列先行，是后续所有改进的基础
- P1/P2 中前后端任务可并行
- P2-1（任务统一）风险最高，建议最后执行
- 每完成一个 task 后运行 `pnpm exec tsc --noEmit` + `pnpm run build` 验证
