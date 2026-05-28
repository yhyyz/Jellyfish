"""LLM agent 输出校验 + 有限重试通用 helper。

为什么存在：
    多个 LLM-stage 流程（剧情脚本、钩子、CTA、archetype 改写等）需要
    在拿到 agent 输出之后再做一道硬约束校验：
        - 是否混入禁止提及的竞品名（见 :mod:`app.services.commerce.validators`）；
        - 是否偏离品牌 archetype / tone（后续 T25-2 引入）；
        - 是否漏写了必备口播标识等。
    每条业务流自己写"调用 → 校验 → 失败拼 guidance → 再调一次"的样
    板代码会高度重复；本模块把这个模式抽成一个通用异步 helper。

参考样板：
    :func:`app.services.film.shot_frame_prompt_tasks.run_shot_frame_prompt_task`
    中的 ``_validate_generated_prompt`` + ``_build_retry_guidance`` 流程。

边界 / 不做什么：
    - 本 helper **不绑定**任何具体 agent；它只接收一个"接受 retry_guidance、
      返回输出"的异步 callable，让上层自由组合 ``agent.aextract`` 或
      ``agent.invoke`` 的入参。
    - 不内置兜底输出降级：达到 ``max_attempts`` 仍未通过校验时直接抛
      :class:`ValidatorRejected`，由上层决定降级、写 finding、还是冒泡
      为任务失败。
"""

from __future__ import annotations

from collections.abc import Awaitable, Callable, Sequence
from typing import TypeVar

T = TypeVar("T")


class ValidatorRejected(Exception):
    """达到 ``max_attempts`` 仍未通过 validator 时抛出。

    属性：
        issues: 最后一轮 validator 报告的 issues（合并自所有 validator）。
        last_output: 最后一次 agent 调用产出的输出，便于上层做兜底降级。
    """

    def __init__(
        self,
        *,
        issues: Sequence[str],
        last_output: object | None = None,
    ) -> None:
        self.issues: list[str] = list(issues)
        self.last_output: object | None = last_output
        super().__init__(
            f"Validator rejected agent output after retries: {self.issues}"
        )


def _build_retry_guidance(issues: Sequence[str]) -> str:
    """把 issues 列表拼成 agent 易读的 retry guidance。

    与 :mod:`app.services.film.shot_frame_prompt_tasks` 中的同名 helper
    保持一致的语气与排版，便于 prompt 模板沿用同一段提示语样板。
    """

    if not issues:
        return ""
    return "请严格修正以下问题后重新生成：\n- " + "\n- ".join(issues)


async def retry_with_validator(
    agent_run: Callable[[str], Awaitable[T]],
    validators: Sequence[Callable[[T], Sequence[str]]],
    *,
    max_attempts: int = 2,
    initial_guidance: str = "",
) -> T:
    """带 validator 的有限重试包装器。

    调用流程：
        1. 用 ``initial_guidance`` 调一次 ``agent_run``；
        2. 把输出依次交给 ``validators`` 校验，issues 合并；
        3. 若 issues 为空 → 返回输出；
        4. 否则把 issues 拼成 retry guidance，再次调用 ``agent_run``，
           直至累计 ``max_attempts`` 次仍失败时抛 :class:`ValidatorRejected`。

    Args:
        agent_run: 异步可调用，签名 ``(retry_guidance: str) -> Awaitable[T]``。
            上层负责把 ``retry_guidance`` 注入到 agent 入参（通常是 prompt
            模板里的占位变量），并保证返回值是已经组装好的最终输出。
        validators: validator 列表；每个签名 ``(output) -> Sequence[str]``，
            返回 issues 列表，空列表表示通过。多个 validator 的 issues 会
            合并到同一份 retry guidance 里反馈给 agent。
        max_attempts: 最大尝试次数（含首次）。``max_attempts=2`` 表示首
            次失败后只允许再试一次；这是 W25 默认策略。
        initial_guidance: 首次调用时传给 ``agent_run`` 的 guidance 文本，
            默认 ``""``。极少数场景（比如已经有上游 issues 想直接进入修
            正模式）可以显式传入。

    Returns:
        通过所有 validator 的 agent 输出。

    Raises:
        ValidatorRejected: 达到 ``max_attempts`` 仍未通过校验时抛出，
            异常对象上挂着最后一轮 issues 与 last_output 供上层使用。
        ValueError: 当 ``max_attempts < 1`` 时直接拒绝（防御性）。
    """

    if max_attempts < 1:
        raise ValueError("max_attempts 必须 ≥ 1")

    guidance = initial_guidance
    last_issues: list[str] = []
    last_output: T | None = None

    for _ in range(max_attempts):
        output = await agent_run(guidance)
        issues: list[str] = []
        for validator in validators:
            try:
                produced = validator(output)
            except Exception as exc:  # noqa: BLE001
                # 把 validator 自身崩溃也当作一次"软失败"，避免一个写
                # 坏的 validator 直接拖垮整条任务；issue 文本带类名便
                # 于排查。
                produced = [f"validator {type(validator).__name__} 抛出异常：{exc}"]
            issues.extend(produced)

        if not issues:
            return output

        last_issues = issues
        last_output = output
        guidance = _build_retry_guidance(issues)

    raise ValidatorRejected(issues=last_issues, last_output=last_output)


__all__ = [
    "ValidatorRejected",
    "retry_with_validator",
]
