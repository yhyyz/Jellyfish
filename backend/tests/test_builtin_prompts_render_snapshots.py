"""12 个 commerce 提示词的金样本（golden snapshot）渲染测试。

为什么这样做：
    提示词是“面向 LLM 的 API”——任何对模板的修改都可能在线上引发难以
    复现的输出回归。因此本测试用一组固定 fixture 渲染每个 commerce
    模板，把渲染结果钉在 ``_snapshots_builtin_prompts/<id>.txt`` 里；
    任何改动都必须主动 ``UPDATE_SNAPSHOTS=1 pytest ...`` 重新生成快照，
    强制写入者意识到“我在改对外契约”。

工作模式：
    - 默认：与磁盘上的快照做 ``==`` 比对，不一致即失败；
    - ``UPDATE_SNAPSHOTS=1``：把当前渲染结果重写到磁盘（首次落库或
      模板被刻意调整时使用）。

不引入第三方 snapshot 库（如 syrupy）以保持本仓 backend 测试栈最小化。
"""

from __future__ import annotations

import os
from pathlib import Path

import pytest

from app.services.studio.builtin_prompts import (
    BUILTIN_PROMPT_DEFINITIONS,
    PromptDefinition,
    render_template,
)
from tests._fixtures_builtin_prompts import COMMERCE_FIXTURES

_SNAPSHOT_DIR = Path(__file__).parent / "_snapshots_builtin_prompts"


def _commerce_definitions() -> list[PromptDefinition]:
    """返回 12 个 commerce 模板（按 fixture 中的 id 顺序）。"""

    by_id = {d.id: d for d in BUILTIN_PROMPT_DEFINITIONS}
    return [by_id[tid] for tid in COMMERCE_FIXTURES]


def _snapshot_path(template_id: str) -> Path:
    return _SNAPSHOT_DIR / f"{template_id}.txt"


def _update_mode() -> bool:
    """通过环境变量决定是否进入“重写快照”模式。"""

    return os.environ.get("UPDATE_SNAPSHOTS") == "1"


@pytest.mark.parametrize(
    "definition",
    _commerce_definitions(),
    ids=lambda d: d.id,
)
def test_commerce_template_render_matches_snapshot(definition: PromptDefinition) -> None:
    fixture = COMMERCE_FIXTURES[definition.id]
    rendered = render_template(definition.template_content, fixture, strict=True)

    path = _snapshot_path(definition.id)

    if _update_mode() or not path.exists():
        _SNAPSHOT_DIR.mkdir(parents=True, exist_ok=True)
        path.write_text(rendered, encoding="utf-8")
        if not _update_mode():
            # 首次落库：测试通过，但提醒维护者将快照纳入版本控制。
            pytest.skip(f"snapshot bootstrapped at {path}; please git-add it.")

    expected = path.read_text(encoding="utf-8")
    assert rendered == expected, (
        f"snapshot drift for {definition.id}; "
        "rerun with UPDATE_SNAPSHOTS=1 if change is intentional."
    )


def test_all_12_snapshots_present_on_disk() -> None:
    """守护：12 个 commerce 模板都必须有对应快照文件被提交。"""

    missing = [
        definition.id
        for definition in _commerce_definitions()
        if not _snapshot_path(definition.id).exists()
    ]
    assert not missing, f"missing snapshots: {missing}"
