"""字幕样式 resolver service（P5 W30-T2）。

为什么存在：
    P3 W18 的 ``shot_subtitle_render_worker`` 通过 ``db.get(SubtitleStyle,
    style_id)`` 直接拿样式，所有镜头共用 W18 系统级 seed（DOUYIN_DEFAULT
    等）。P5 W30 引入项目级覆盖样式后，必须在 worker 与样式表之间补一层
    "项目级 → 系统级 fallback"的解析逻辑：

    - 项目可以维护与系统级同名（如 ``DOUYIN_DEFAULT``）的项目级覆盖行；
    - 渲染时同 project_id 的镜头优先取项目级行；
    - 项目级行不存在 / 被删除时自动 fallback 系统级；
    - 不在 worker 里缓存：用户在生成中途修改项目覆盖必须立即生效。

做什么：
    单入口 :func:`resolve_for_shot` 给定 ``shot_id`` 与可选的
    ``style_id_hint``，按以下优先级返回 :class:`SubtitleStyle`：

    1. 拿 ``shot.chapter.project_id``。
    2. 若 ``style_id_hint`` 给定且对应行 ``project_id == project_id``，
       直接返回。
    3. 否则按 (project_id, name) 查项目级行（``name`` 来自
       ``style_id_hint`` 对应行的 name，或系统默认 name）。
    4. fallback：按 (``project_id IS NULL``, name=系统默认) 查系统级行。
    5. 仍找不到 → 抛 :class:`LookupError`，与 W18 worker 内既有错误风格
       一致（worker 顶层捕获后落 ``failed`` 状态）。

边界与契约：
    - 不缓存任何样式：每次调用都重新走 SELECT，让用户改项目覆盖立即生效。
    - 不引入新的 cross-cutting concern；与 ``chapter_av_export_filter``
      等下游消费 ``SubtitleTrack.style_id`` 的路径解耦（filter 看到的是
      已落库的字幕轨道，不再需要二次解析）。
    - 抛 :class:`LookupError` 而非 :class:`HTTPException`：本 service 是
      worker 路径调用方，不能假设 FastAPI request context 存在。
"""

from __future__ import annotations

from typing import Final

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.studio_projects import Chapter
from app.models.studio_shots import Shot
from app.models.subtitle import SubtitleStyle


SYSTEM_DEFAULT_STYLE_ID: Final[str] = "douyin_default"
"""W18 系统级 seed 的默认样式 ID；当 ``style_id_hint`` 缺失时作为底层 lookup key。

这与 :func:`app.services.studio.builtin_subtitle_styles.bootstrap_builtin_subtitle_styles`
seed 的第一条系统行保持一致；任何变更都需要同步更新。
"""


async def _load_shot_project_id(
    db: AsyncSession, shot_id: str
) -> str:
    """加载 ``shot.chapter.project_id``，缺失时抛 :class:`LookupError`。

    Args:
        db: 当前 worker 绑定的 ``AsyncSession``。
        shot_id: 字幕所属镜头 ID。

    Returns:
        镜头所属项目的 ID。

    Raises:
        LookupError: 镜头或其章节不存在时。
    """

    shot = await db.get(Shot, shot_id)
    if shot is None:
        raise LookupError(f"Shot not found: shot_id={shot_id}")
    chapter = await db.get(Chapter, shot.chapter_id)
    if chapter is None:
        raise LookupError(
            f"Chapter not found for shot {shot_id}: "
            f"chapter_id={shot.chapter_id}"
        )
    return chapter.project_id


async def _find_project_style_by_name(
    db: AsyncSession,
    *,
    project_id: str,
    name: str,
) -> SubtitleStyle | None:
    """按 ``(project_id, name)`` 精确匹配项目级覆盖行。

    返回 ``None`` 表示当前项目没有同名覆盖；调用方据此 fallback 到系统级。
    """

    stmt = (
        select(SubtitleStyle)
        .where(SubtitleStyle.project_id == project_id)
        .where(SubtitleStyle.name == name)
        .limit(1)
    )
    result = await db.execute(stmt)
    return result.scalar_one_or_none()


async def _find_system_style_by_name(
    db: AsyncSession,
    *,
    name: str,
) -> SubtitleStyle | None:
    """按 ``(project_id IS NULL, name)`` 匹配系统级 seed 行。"""

    stmt = (
        select(SubtitleStyle)
        .where(SubtitleStyle.project_id.is_(None))
        .where(SubtitleStyle.name == name)
        .limit(1)
    )
    result = await db.execute(stmt)
    return result.scalar_one_or_none()


async def _load_style_by_id(
    db: AsyncSession, style_id: str
) -> SubtitleStyle | None:
    """直接按主键加载样式行，便于读取 ``name`` 字段做后续 fallback。"""

    return await db.get(SubtitleStyle, style_id)


async def resolve_for_shot(
    db: AsyncSession,
    *,
    shot_id: str,
    style_id_hint: str | None = None,
) -> SubtitleStyle:
    """解析当前镜头应使用的字幕样式（项目级优先 / 系统级 fallback）。

    Args:
        db: 当前 worker 绑定的 ``AsyncSession``。
        shot_id: 字幕所属镜头 ID，用于解析 ``project_id``。
        style_id_hint: 可选，调用方给的样式 ID 提示（通常来自 worker
            ``run_args['style_id']``）。会先按主键加载，命中且属于同
            project 直接返回；否则取其 ``name`` 作为后续 fallback 的 key。

    Returns:
        命中的 :class:`SubtitleStyle` ORM 对象。

    Raises:
        LookupError: 镜头或章节不存在；或所有 fallback 路径都未命中样式。

    关键内部逻辑：
        - 不缓存：每次调用都重新走 SELECT，让用户中途改项目覆盖立即生效。
        - hint 行 ``project_id`` 匹配当前 project 时短路返回，避免一次
          多余的 ``(project_id, name)`` 查询。
        - hint 行属于"系统级"（``project_id IS NULL``）时，仍用其 name 去
          查项目级覆盖：这是项目级"覆盖系统级"语义的关键路径。
    """

    project_id = await _load_shot_project_id(db, shot_id)

    target_name: str | None = None
    if style_id_hint:
        hint = await _load_style_by_id(db, style_id_hint)
        if hint is not None:
            if hint.project_id == project_id:
                return hint
            target_name = hint.name

    if target_name is None:
        fallback = await _load_style_by_id(db, SYSTEM_DEFAULT_STYLE_ID)
        target_name = (
            fallback.name if fallback is not None else SYSTEM_DEFAULT_STYLE_ID
        )

    project_hit = await _find_project_style_by_name(
        db, project_id=project_id, name=target_name
    )
    if project_hit is not None:
        return project_hit

    system_hit = await _find_system_style_by_name(db, name=target_name)
    if system_hit is not None:
        return system_hit

    raise LookupError(
        "SubtitleStyle not resolvable: "
        f"shot_id={shot_id}, project_id={project_id}, "
        f"style_id_hint={style_id_hint!r}, target_name={target_name!r}"
    )


__all__ = [
    "SYSTEM_DEFAULT_STYLE_ID",
    "resolve_for_shot",
]
