---
title: "合规阻断告警子系统"
weight: 51
description: "ComplianceFinding BLOCKER 级触发 Slack/email webhook、3 次指数退避重试、24h 滑动窗口 escalation rules 当前生效的实现。"
---

> 本文属于"当前架构"文档，描述 P4 Wave 26 落地后 `dev` 分支真实生效的合规阻断告警子系统。

## 边界

合规阻断告警子系统在 `ComplianceFinding` 写入 BLOCKER 级 finding 后，**5 秒 SLA 内**把告警发到 Slack / email 渠道；累计 N 次后升级到团队 owner。当前真实生效的边界：

- 触发条件：仅 BLOCKER 级 finding 触发（warning / info 级不触发）。
- SLA 目标：finding commit 到通知送达 ≤ 5s。
- 渠道：Slack（block-kit）+ email（aiosmtplib），并发派发。
- 重试：3 次指数退避（1s / 2s / 4s），失败入 `NotificationDelivery` 表持久化。
- escalation：24h 滑动窗口内连续 3 次 BLOCKER → 升级到 owner（默认值，可 per-profile 覆盖）。

不包含：

- 钉钉 / 企业微信 / 飞书 / SMS 等其它渠道（未实装）。
- 用户级订阅（当前是 per-profile 配置，不是 per-user 订阅）。
- 已读 / ACK 状态机（仅单向派发，不追踪客户端 ACK）。

## 数据模型

### NotificationChannel

实现：`backend/app/models/notification_channel.py` + alembic `0014_p4_notification_channels.py`。

| 字段 | 类型 | 说明 |
| --- | --- | --- |
| `id` | str | 主键 |
| `profile_id` | str FK → `compliance_profiles.id` | 关联合规 profile |
| `kind` | str enum: `slack` \| `email` | 渠道类型 |
| `target` | str | Slack webhook url 或 email 地址 |
| `enabled` | bool | 是否启用 |
| `created_at` / `updated_at` | timestamp | |

### NotificationDelivery

失败日志表：

| 字段 | 类型 | 说明 |
| --- | --- | --- |
| `id` | str | 主键 |
| `channel_id` | str FK → `notification_channels.id` | |
| `finding_id` | str FK → `compliance_findings.id` | |
| `status` | str: `success` \| `failed` | |
| `attempts` | int | 已重试次数 |
| `error` | str \| null | 最后一次失败信息 |
| `created_at` | timestamp | |

### EscalationState

实现：`backend/app/models/escalation_state.py` + alembic `0016_p4_escalation_state.py`。

| 字段 | 类型 | 说明 |
| --- | --- | --- |
| `id` | str | 主键 |
| `profile_id` | str FK → `compliance_profiles.id` | |
| `team_scope` | str | 团队/项目维度（profile_id + 可选 scope key） |
| `count` | int | 当前窗口内 BLOCKER 计数 |
| `window_started_at` | timestamp | 当前 24h 窗口起点 |
| `last_escalated_at` | timestamp \| null | 最近一次 owner 通知时间 |

## 渠道实现

### Slack 渠道

实现：`backend/app/integrations/notifications/slack.py`。

- 依赖：`slack-sdk >= 3.27`（异步 webhook client）
- 消息格式：block-kit
  - header block：`合规 BLOCKER 告警`
  - section block：`finding.code` / `severity` / `message` / `evidence_excerpt`
  - context block：`profile.name` / `created_at` / 跳转链接
- 重试：3 次指数退避（1s / 2s / 4s）
- 超时：单次 5s
- 失败兜底：写入 `NotificationDelivery(status=failed)`，不阻塞其它渠道

### Email 渠道

实现：`backend/app/integrations/notifications/email.py`。

- 依赖：`aiosmtplib >= 3.0`
- 配置（`backend/app/config.py`）：
  - `SMTP_HOST` / `SMTP_PORT`
  - `SMTP_USERNAME` / `SMTP_PASSWORD`
  - `SMTP_USE_TLS` / `SMTP_START_TLS`
  - `SMTP_SENDER`
- 主题模板：`[Jellyfish 合规告警] {finding.code} - BLOCKER`
- 正文：HTML + plaintext 双格式，含 finding 详情与跳转链接
- 重试 / 超时 / 失败兜底：与 Slack 渠道同源

## 派发器

实现：`backend/app/services/notifications/compliance_dispatcher.py`。

签名：

```python
async def dispatch_blocker_finding(
    session: AsyncSession,
    finding: ComplianceFinding,
) -> None
```

行为：

1. 校验 `finding.severity == BLOCKER`，否则跳过（warning / info 不派发）
2. 反查 `finding.profile_id` 关联的所有 `NotificationChannel(enabled=True)`
3. 按 channel.kind 分桶，构造 Slack / email payload
4. `asyncio.gather(*senders)` 并发派发（多渠道并行，不串行）
5. 单渠道 3 次指数退避内成功 → `NotificationDelivery(status=success, attempts=N)`
6. 3 次仍失败 → `NotificationDelivery(status=failed, error=last_exception)`
7. fan-out 完成后调用 `escalation_engine.maybe_escalate(...)`（不阻塞任何 channel 失败）

### 接入点：commit-then-send

接入位置：`backend/app/services/commerce/compliance_check_worker.py`。

时序契约（W19b chain dispatch）：

```text
ComplianceCheckerAgent.run()
        |
        v
ComplianceFinding 写入 (multiple)
        |
        v
await session.commit()       <-- 关键：先 commit
        |
        v
dispatch_blocker_finding(...) <-- 后 fire webhook
```

不能在 commit 之前派发，否则下游消费者读不到 finding 行（跨请求 visibility race，详见 [持久化引擎](/docs/architecture/persistence-engine/)）。

## escalation 引擎

实现：`backend/app/services/notifications/escalation_engine.py`。

签名：

```python
async def maybe_escalate(
    session: AsyncSession,
    profile: ComplianceProfile,
    finding: ComplianceFinding,
) -> None
```

判定规则：

1. 取 `EscalationState(profile_id, team_scope)` 行（不存在则建）
2. 检查 `window_started_at`：若已超过 24h（窗口阈值，可被 `profile.rules.escalation.window_seconds` 覆盖）→ 重置窗口起点 + 计数清零
3. `count += 1`
4. 检查阈值：`count >= threshold`（默认 3，可被 `profile.rules.escalation.threshold` 覆盖）→ 触发升级
5. 升级行为：发邮件给 `ESCALATION_OWNER_EMAIL`（env 变量），重置窗口与计数
6. 缺 SMTP / owner email → 仍正常计数，跳过通知（不阻塞）
7. 任何升级判定异常 → 吞掉，不污染 fan-out 主路径

阈值与窗口可被 `ComplianceProfile.rules.escalation` 覆盖：

```yaml
ComplianceProfile.rules:
  escalation:
    threshold: 5         # 默认 3
    window_seconds: 3600 # 默认 86400 (24h)
```

不需要 RBAC / User 表：`team_scope` 当前用 `profile_id` 占位，owner 邮箱来自 env。P5 RBAC 落地后会切到真实 user / team 表。

## 完整事件流

```text
Compliance check worker 跑完
        |
        v
ComplianceFinding 行写入 (BLOCKER + warning + info ...)
        |
        v
await session.commit()
        |
        v
dispatch_blocker_finding(finding)
        ├── filter severity = BLOCKER (其它跳过)
        ├── 查 NotificationChannel(profile_id, enabled=True)
        ├── asyncio.gather 并发 fan-out:
        │       Slack channel (3 retry)  → NotificationDelivery(success/failed)
        │       Email channel (3 retry)  → NotificationDelivery(success/failed)
        ├── escalation_engine.maybe_escalate(profile, finding)
        │       ├── 24h 滑动窗口计数
        │       ├── 达阈值 → 邮件 owner + 重置
        │       └── 缺 owner email → 仅计数
        └── done (吞下任何 escalation 异常)
```

## 测试覆盖

后端：

- `tests/integrations/notifications/test_slack.py` — block-kit 构造 + 重试
- `tests/integrations/notifications/test_email.py` — `aiosmtpd` 真服务器接收
- `tests/services/notifications/test_compliance_dispatcher.py` — 并发 fan-out + profile 过滤 + 3 次重试落 NotificationDelivery
- `tests/services/notifications/test_escalation_engine.py` — 7 cases：
  - under / at / over threshold
  - 24h+1m 窗口重置
  - profile 自定义阈值生效
  - 无 scope 时跳过
  - 触发但缺 owner 邮箱时仍重置状态
  - rules 解析（list / dict / 默认）
- `tests/integration/test_compliance_webhook_e2e.py` — 真本地 Slack mock + smtpd ≤ 5s 端到端

## 配置项

env 变量（`backend/app/config.py`）：

| 变量 | 用途 | 默认 |
| --- | --- | --- |
| `SMTP_HOST` | SMTP 服务器主机 | - |
| `SMTP_PORT` | SMTP 端口 | 587 |
| `SMTP_USERNAME` / `SMTP_PASSWORD` | SMTP 凭据 | - |
| `SMTP_USE_TLS` | 直接 TLS | false |
| `SMTP_START_TLS` | STARTTLS | true |
| `SMTP_SENDER` | 发件人地址 | - |
| `ESCALATION_OWNER_EMAIL` | 升级目标邮箱 | - |

未配置 SMTP 时整个邮件链路降级为 noop（不报错），但 escalation 计数仍生效。

## 已知限制

- 仅 Slack + email 两渠道，未实装钉钉 / 企业微信 / 飞书 / SMS。
- `ESCALATION_OWNER_EMAIL` 当前是单值 env，不支持 per-team 路由（依赖 P5 RBAC）。
- escalation 触发后 24h 窗口立即重置，不做"冷却期"避免持续触发；这是默认行为，可由 profile.rules 自定义。
- `NotificationDelivery` 失败行不自动重投，需人工 / 离线脚本兜底重发。

后续演进路线放 `plans/jellyfish-story-commerce.md`。
