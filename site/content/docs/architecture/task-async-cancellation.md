---
title: "任务异步与取消架构"
weight: 16
description: "Jellyfish 当前已落地的脚本类长耗时智能体任务化方案：async 路由集合、relation_type 列表、cancel_requested 字段与 worker 协作式取消。"
---

> 本文属于"当前架构"文档，描述当前真实生效的实现。早期推进过程见 commit 36200e9。

## 定位

`script-processing` 下原本一批同步直接调用 Agent 的接口，已统一接入项目内通用任务系统：

- 创建任务后立即返回 `task_id`
- 页面按业务实体（章节、分镜等）恢复任务状态
- 支持请求取消，并由 worker 协作式停止

整套能力围绕已有任务设施落地，不引入独立任务模型：

- `TaskManager`
- `GenerationTask`
- `GenerationTaskLink`
- `/api/v1/film/tasks/{task_id}/status`
- `/api/v1/film/tasks/{task_id}/result`

## Async 路由列表

当前已任务化并接入真实页面的 `script-processing` 异步接口：

```text
POST /api/v1/script-processing/divide-async
POST /api/v1/script-processing/extract-async
POST /api/v1/script-processing/check-consistency
POST /api/v1/script-processing/optimize-script
POST /api/v1/script-processing/simplify-script
POST /api/v1/script-processing/analyze-character-portrait
POST /api/v1/script-processing/analyze-prop-info
POST /api/v1/script-processing/analyze-scene-info
POST /api/v1/script-processing/analyze-costume-info
```

并保留若干接口作为预备能力（已任务化，但当前无真实前端入口）：

```text
POST /api/v1/script-processing/merge-entities
POST /api/v1/script-processing/analyze-variants
```

预备能力策略是：保留后端实现、测试与 OpenAPI；在路由描述与代码注释中标明"预备能力"；等待未来真实页面入口出现后再接入。

同步版接口（如 `/divide`、`/extract`）当前仍保留，仅用于管理端调试、单测与回归。

### 创建任务的返回结构

异步路由统一返回：

```json
{
  "success": true,
  "code": 200,
  "message": "Task created",
  "data": {
    "task_id": "uuid",
    "status": "pending",
    "reused": false,
    "relation_type": "chapter_division",
    "relation_entity_id": "..."
  }
}
```

### 同业务实体活跃任务复用

同一业务实体在同一时刻只允许存在一个活跃任务（活跃状态 = `pending` / `running` / `streaming`）。  
若已有活跃任务，直接返回已有 `task_id` 并将 `reused` 置为 `true`。这条约束用于解决：

- 重复点击
- 页面刷新后再次点击
- 多标签页并发触发

## relation_type 约定

任务通过 `relation_type` + `relation_entity_id` 与业务实体绑定。当前已落地的 11 个 `relation_type`：

```text
chapter_division
script_extraction
consistency_check
script_optimization
script_simplification
character_portrait_analysis
prop_info_analysis
scene_info_analysis
costume_info_analysis
entity_merge
variant_analysis
```

页面进入时按 `relation_entity_id` 查询最新活跃任务并恢复轮询，例如：

- 章节页 / 项目工作台：`chapter_division`
- 分镜编辑页：`script_extraction`

页面不依赖本地缓存的 `task_id`，刷新后仍能定位到正在运行的任务。

## 取消能力

### 数据模型

`generation_tasks` 表上新增的取消相关字段：

- `cancel_requested`
- `cancel_requested_at`
- `cancel_reason`
- `cancelled_at`

### 取消接口

```text
POST /api/v1/film/tasks/{task_id}/cancel
```

调用后会写入 `cancel_requested = true`，但不保证立即停止。

### Worker 协作式取消

worker 在以下检查点检测 `cancel_requested`：

1. 任务启动前
2. 调用下一个 Agent 前
3. 多阶段流程的阶段边界
4. 写库前

一旦检测到取消请求，worker 会：

- 停止后续步骤
- 将任务写为 `cancelled`
- 记录 `cancelled_at`

如果当前正卡在单次同步模型调用或阻塞式 SDK 调用中，必须等待当前步骤结束后才能停下。当前阶段不提供强终止能力。

### 对外语义

任务面板与页面提示统一使用：

- 任务进行中
- 已请求取消
- 已完成
- 已失败

取消请求的标准提示文案：

> 已请求取消，系统会在当前步骤结束后停止。

## 前端约束

页面恢复任务状态的标准做法：

```text
页面打开
→ 根据业务实体查最新活跃任务
→ 恢复轮询
→ 根据任务状态更新 UI
```

不以"页面是否被刷新"作为前提条件。

## 未启用的扩展方向

以下能力当前未启用，仅作为后续可能的演进方向：

- 运行句柄注册表（`task_id -> asyncio.Task`）以支持对部分任务的 `task.cancel()`
- 独立 worker 进程 / 队列系统以支持 kill worker 级别的强终止

如果未来业务明确要求"立即终止长任务"，再行评估。当前阶段保持现有协作式取消方案。
