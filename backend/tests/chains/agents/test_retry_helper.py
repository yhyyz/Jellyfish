"""retry_with_validator helper 单元测试。

覆盖：
- 首次输出干净 → 直接返回，不重试
- 首次脏 / 第二次干净 → 第二次 attempt 时携带 retry guidance；返回干净结果
- 永远脏 → max_attempts 用尽后抛 ValidatorRejected，包含最后一次 issues
"""

from __future__ import annotations

import pytest

from app.chains.agents._retry import (
    ValidatorRejected,
    retry_with_validator,
)


@pytest.mark.asyncio
async def test_retry_helper_passes_through_when_validator_clean() -> None:
    """validator 一上来就干净，agent_run 只调一次，返回原始输出。"""

    call_log: list[str] = []

    async def agent_run(retry_guidance: str) -> str:
        call_log.append(retry_guidance)
        return "clean output"

    def clean_validator(_: str) -> list[str]:
        return []

    result = await retry_with_validator(
        agent_run,
        validators=[clean_validator],
        max_attempts=2,
    )

    assert result == "clean output"
    assert len(call_log) == 1, "干净通过时不应触发重试"
    assert call_log[0] == "", "首次调用 retry_guidance 应为空"


@pytest.mark.asyncio
async def test_retry_helper_retries_with_guidance_when_dirty() -> None:
    """首次脏 / 二次干净：第二次调用必须收到含 issues 的 retry_guidance。"""

    call_log: list[str] = []
    outputs = iter(["dirty output", "clean output"])

    async def agent_run(retry_guidance: str) -> str:
        call_log.append(retry_guidance)
        return next(outputs)

    def boundary_validator(text: str) -> list[str]:
        if text == "dirty output":
            return ["输出包含禁止内容：BrandX"]
        return []

    result = await retry_with_validator(
        agent_run,
        validators=[boundary_validator],
        max_attempts=2,
    )

    assert result == "clean output"
    assert len(call_log) == 2, "应当重试一次"
    assert call_log[0] == "", "首次 retry_guidance 应为空"
    assert "BrandX" in call_log[1], "重试 guidance 应包含 issue 文本"
    assert "修正" in call_log[1] or "重新生成" in call_log[1], "guidance 应明确要求修正/重生"


@pytest.mark.asyncio
async def test_retry_helper_gives_up_after_max_attempts_and_raises_validator_rejected() -> None:
    """validator 始终拒绝时，达到 max_attempts 后抛 ValidatorRejected。"""

    call_log: list[str] = []

    async def agent_run(retry_guidance: str) -> str:
        call_log.append(retry_guidance)
        return "still dirty"

    def always_dirty(_: str) -> list[str]:
        return ["命中竞品 BrandX"]

    with pytest.raises(ValidatorRejected) as exc_info:
        _ = await retry_with_validator(
            agent_run,
            validators=[always_dirty],
            max_attempts=2,
        )

    assert len(call_log) == 2, "max_attempts=2 时应总共调用 2 次"
    assert exc_info.value.issues == ["命中竞品 BrandX"]
    assert exc_info.value.last_output == "still dirty"


@pytest.mark.asyncio
async def test_retry_helper_aggregates_issues_from_multiple_validators() -> None:
    """多 validator 时 issues 应聚合送入 retry_guidance。"""

    call_log: list[str] = []
    outputs = iter(["bad", "good"])

    async def agent_run(retry_guidance: str) -> str:
        call_log.append(retry_guidance)
        return next(outputs)

    def validator_a(text: str) -> list[str]:
        return ["issue-A"] if text == "bad" else []

    def validator_b(text: str) -> list[str]:
        return ["issue-B"] if text == "bad" else []

    result = await retry_with_validator(
        agent_run,
        validators=[validator_a, validator_b],
        max_attempts=2,
    )

    assert result == "good"
    assert len(call_log) == 2
    assert "issue-A" in call_log[1]
    assert "issue-B" in call_log[1]
