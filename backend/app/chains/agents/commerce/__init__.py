"""Story-Driven Commerce 链路下的 Agent 套件。

本子包承载 Wave 4 的三个 commerce Agent：

- ``ProductExtractorAgent`` (W4-T1)：从原始物料抽取商品结构化信息；
- ``StoryScriptGeneratorAgent`` (W4-T2)：按公式 + 商品 + 受众生成 StoryScript；
- ``ComplianceCheckerAgent`` (W4-T3)：对脚本做语义层合规审查。

设计要点（参见 ``.omo/notepads/jellyfish-story-commerce/decisions.md`` D5）：

- 三者一律使用 ``method="json_schema"`` 的 structured output；
- 提示词正文统一来自 ``app.services.studio.builtin_prompts.BUILTIN_PROMPT_DEFINITIONS``，
  确保提示词单一真相源；
- 输出契约统一来自 ``app.core.contracts.story``。

并发期容忍策略：W4-T1/T2/T3 三个文件由并行 sub-agent 分别落地，
任意一个先到达时该模块都应可正常导入；为此对子模块导入做容错。
"""

# pylint: disable=invalid-name
from __future__ import annotations

__all__: list[str] = []

try:
    from app.chains.agents.commerce.product_extractor_agent import (
        ProductExtractorAgent,
    )
except ImportError:  # pragma: no cover - 并行未落地时静默
    ProductExtractorAgent = None  # type: ignore[assignment,misc]
else:
    __all__.append("ProductExtractorAgent")

try:
    from app.chains.agents.commerce.story_script_generator_agent import (
        StoryScriptGeneratorAgent,
    )
except ImportError:  # pragma: no cover - 并行未落地时静默
    StoryScriptGeneratorAgent = None  # type: ignore[assignment,misc]
else:
    __all__.append("StoryScriptGeneratorAgent")

try:
    from app.chains.agents.commerce.compliance_checker_agent import (
        ComplianceCheckerAgent,
    )
except ImportError:  # pragma: no cover - 并行未落地时静默
    ComplianceCheckerAgent = None  # type: ignore[assignment,misc]
else:
    __all__.append("ComplianceCheckerAgent")
