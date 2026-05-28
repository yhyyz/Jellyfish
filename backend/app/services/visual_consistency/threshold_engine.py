"""DINOv2 视觉一致性阈值判定引擎（P4 W27-T2）。

为什么存在
----------

W27-T1 的 :mod:`consistency_worker` 已经把 cosine similarity 算到
``shot.consistency_score``，但分数本身只是数值；要把它变成"通过 / 警告 /
失败 + 是否要重生"这一组**业务决策**，还差一层显式规则。

把这一层抽成纯函数有两个好处：

- 规则可被单元测试覆盖（不依赖 DB / 不依赖 sidecar），用例数与边界条件
  数量一一对应；
- 调用方（worker / 管理面板 / 未来的 chapter_av_export pre-gate）共享同
  一份判定，避免阈值在各处漂移。

阈值规则（与 W27 规范对齐）
---------------------------

- ``score >= 0.85``                         → ``("pass", False)``
- ``0.75 <= score < 0.85``                  → ``("warning", False)``
- ``score <  0.75 AND retry_count <  2``    → ``("fail", True)``    （触发重生）
- ``score <  0.75 AND retry_count >= 2``    → ``("fail", False)``   （达到 hard cap）
- ``score is None``                         → ``("warning", False)``（degraded path：
  缺 reference / sidecar 不可达 / 抽帧失败时不阻塞流程，但也不静默 pass）

边界与不变量
------------

- ``retry_count`` 的 hard cap 为 **2**：第 0 / 1 次（retry_count<2）允许重生；
  第 2 次开始锁死成 fail，不再无限循环。这条上限不能被外部参数修改，避免
  把 sidecar 推到无限重试。
- score 等于 0.85 / 0.75 这种边界值采用左闭右开（``>=``）的约定，与文档
  字面 "≥0.85 pass / 0.75-0.85 warning / <0.75 fail" 一致。
- 函数纯粹 (no I/O)：不写库、不发消息、不打 log。调用方负责把返回值落地
  到 ``Shot.consistency_status`` / ``consistency_retry_count``，并按
  ``should_regen`` 决定是否走 W19b commit-then-send 重派
  ``video_generation``。
"""

from __future__ import annotations

from typing import Literal


#: 通过阈值：cosine similarity ≥ 此值视为视觉一致性合格。
PASS_THRESHOLD: float = 0.85

#: 警告下限：[``WARNING_LOWER`` , ``PASS_THRESHOLD``) 区间为 warning。
WARNING_LOWER: float = 0.75

#: 自动重生硬上限：retry_count ≥ 此值后即使分数低也不再重派 video_generation。
#: 这一上限刻意写成模块级常量、不接受外部参数，避免上游把它调大造成
#: sidecar 无限重试。
MAX_AUTO_REGEN_RETRY: int = 2


#: ``Shot.consistency_status`` 列允许写入的字面量集合。
ConsistencyStatus = Literal["pass", "warning", "fail"]


def evaluate(
    score: float | None, retry_count: int
) -> tuple[ConsistencyStatus, bool]:
    """根据一致性分数 + 当前重试次数给出业务判定。

    Args:
        score: ``Shot.consistency_score``。``None`` 表示未跑成功（缺
            reference / sidecar 不可达 / 抽帧失败），按 degraded 分支
            返回 warning，**不**触发重生（缺 reference 重生也是徒劳）。
        retry_count: ``Shot.consistency_retry_count``，本镜头当前累计的
            自动重生次数；低于 :data:`MAX_AUTO_REGEN_RETRY` 时低分会触发
            一次重生，达到上限后停止。

    Returns:
        ``(status, should_regen)`` 二元组。``status`` 直接对应
        ``Shot.consistency_status``；``should_regen=True`` 时调用方应该
        按 W19b commit-then-send 契约重派 ``video_generation``，并把
        ``Shot.consistency_retry_count`` 自增 1。
    """

    # degraded path：score 为空说明流程没真正算出分数，不能当成 pass，但也
    # 不应该再花一轮算力重生（缺 reference 的情况下重生没意义）。
    if score is None:
        return "warning", False

    if score >= PASS_THRESHOLD:
        return "pass", False

    if score >= WARNING_LOWER:
        return "warning", False

    # 进入低分分支：是否还有自动重生预算？
    if retry_count < MAX_AUTO_REGEN_RETRY:
        return "fail", True
    return "fail", False


__all__ = [
    "ConsistencyStatus",
    "MAX_AUTO_REGEN_RETRY",
    "PASS_THRESHOLD",
    "WARNING_LOWER",
    "evaluate",
]
