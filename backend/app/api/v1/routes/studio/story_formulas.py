"""StoryFormula 只读接口（W6-T2，P1 阶段）。

仅暴露列表与详情两个 GET 路径：

- ``GET /api/v1/studio/story-formulas``：按 ``region`` / ``category`` /
  ``sort_order`` 检索系统级公式注册表。
- ``GET /api/v1/studio/story-formulas/{id}``：按 ID 取详情；不存在 →
  404。

写入路径不开放给 API：种子数据由
:func:`app.services.commerce.builtin_story_formulas.bootstrap_builtin_story_formulas`
在启动期幂等加载，避免运营误改。
"""

from __future__ import annotations

from fastapi import APIRouter, Depends, Query
from sqlalchemy.ext.asyncio import AsyncSession

from app.dependencies import get_db
from app.models.types import FormulaRegion
from app.schemas.commerce.story_formula import StoryFormulaRead
from app.schemas.common import ApiResponse, success_response
from app.services.commerce.story_formulas import StoryFormulasService

router = APIRouter()


def _formula_to_read(obj) -> StoryFormulaRead:  # noqa: ANN001
    """把 ORM 实例展开为 :class:`StoryFormulaRead`。

    ``structure`` 是 JSON dict，无法直接 ``model_validate(orm)`` 自动
    映射到嵌套 ``StoryFormulaStructureRead``，因此手动构造响应字典再走
    Pydantic 校验。
    """
    payload = {
        "id": obj.id,
        "name": obj.name,
        "region": obj.region,
        "category": obj.category,
        "structure": obj.structure or {},
        "risk_flags": obj.risk_flags or [],
        "sample_dialog": obj.sample_dialog,
        "typical_duration_sec": obj.typical_duration_sec,
        "typical_shot_count": obj.typical_shot_count,
        "psychology": obj.psychology,
        "use_cases": obj.use_cases or [],
        "avoid_cases": obj.avoid_cases or [],
        "prompt_template_id": obj.prompt_template_id,
        "is_system": obj.is_system,
        "sort_order": obj.sort_order,
    }
    return StoryFormulaRead.model_validate(payload)


@router.get(
    "",
    response_model=ApiResponse[list[StoryFormulaRead]],
    summary="剧情公式列表（按 region / category 过滤，sort_order 升序）",
)
async def list_story_formulas(
    db: AsyncSession = Depends(get_db),
    region: FormulaRegion | None = Query(None, description="过滤地域 cn / global"),
    category: str | None = Query(None, description="过滤分类（如 cn_workplace）"),
) -> ApiResponse[list[StoryFormulaRead]]:
    """列出所有系统级剧情公式（不分页，规模 ≤10 条）。"""
    service = StoryFormulasService(db)
    formulas = await service.list_formulas(region=region, category=category)
    return success_response([_formula_to_read(item) for item in formulas])


@router.get(
    "/{formula_id}",
    response_model=ApiResponse[StoryFormulaRead],
    summary="剧情公式详情",
)
async def get_story_formula(
    formula_id: str,
    db: AsyncSession = Depends(get_db),
) -> ApiResponse[StoryFormulaRead]:
    """按 ID 获取公式详情，不存在返回 404。"""
    service = StoryFormulasService(db)
    obj = await service.get_formula(formula_id)
    return success_response(_formula_to_read(obj))
