"""剧情带货项目（kind=commerce_story）服务（W6-T2，P1 阶段）。

职责边界：

- 创建：在单事务内同时落 :class:`app.models.studio.Project` 与
  :class:`app.models.commerce_assets.CommerceStoryConfig`，强制
  ``Project.kind = ProjectKind.commerce_story.value`` 以避免普通短剧项目
  被错误归类。
- 列表：只返回 ``kind=commerce_story`` 的项目，不返回 drama 项目。
- 详情：联表读出 Project + CommerceStoryConfig；config 缺失时仍正常
  返回（仅 ``config=None``），保留容错。
- 配置 patch：仅更新 CommerceStoryConfig 的字段，不动 Project 核心
  字段（避免与 ``/api/v1/studio/projects`` PATCH 路径双入口冲突）。
- 商品挂载：``link_product`` / ``unlink_product`` 在
  ``project_product_links`` 表上 INSERT / DELETE，按 UNIQUE 约束去重。

本 service 故意不依赖已有 ``StudioProjectsService`` 的通用 CRUD：
- commerce_story 的创建路径需要跨表事务，与 drama 项目 1 表创建语义不同；
- 复用通用 CRUD 反而会让 ``kind`` 注入与单事务保证更隐晦。
"""

from __future__ import annotations

from typing import Any

from fastapi import HTTPException, status
from sqlalchemy import delete, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.commerce_assets import CommerceStoryConfig, ProjectProductLink
from app.models.studio import Project
from app.models.types import ProjectKind
from app.schemas.commerce.story_project import (
    ProjectProductLinkCreate,
    StoryProjectConfigUpdate,
    StoryProjectCreate,
)
from app.services.common.errors import entity_not_found


class StoryProjectsService:
    """剧情带货项目业务编排 service。

    所有方法都依赖一个外部注入的 ``AsyncSession``；事务由会话生命周期
    维护（FastAPI 路由 ``get_db`` 在请求结束时统一 ``commit``）。
    单方法内若需要两表同时落库，使用同一会话保证原子性。
    """

    def __init__(self, db: AsyncSession) -> None:
        """绑定异步数据库会话。"""
        self._db = db

    # ------------------------------------------------------------------
    # 内部工具
    # ------------------------------------------------------------------

    async def _get_project_or_404(self, project_id: str) -> Project:
        """获取 commerce_story 项目；非该类型或不存在均视为 404。"""
        obj = await self._db.get(Project, project_id)
        if obj is None or obj.kind != ProjectKind.commerce_story.value:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail=entity_not_found("StoryProject"),
            )
        return obj

    async def _get_config(self, project_id: str) -> CommerceStoryConfig | None:
        """读取 1:1 配置行；不存在返回 ``None``。"""
        return await self._db.get(CommerceStoryConfig, project_id)

    @staticmethod
    def _project_to_dict(project: Project) -> dict[str, Any]:
        """把 Project ORM 投影为可被 ``StoryProjectRead.model_validate`` 直接消费的 dict。"""
        return {
            "id": project.id,
            "name": project.name,
            "description": project.description,
            "style": project.style,
            "visual_style": project.visual_style,
            "seed": project.seed,
            "kind": project.kind if isinstance(project.kind, str) else project.kind.value,
            "unify_style": project.unify_style,
            "progress": project.progress,
            "default_video_ratio": project.default_video_ratio,
            "stats": project.stats or {},
        }

    @staticmethod
    def _config_to_dict(config: CommerceStoryConfig | None) -> dict[str, Any] | None:
        """把 CommerceStoryConfig ORM 投影为响应 dict；缺失时返回 ``None``。"""
        if config is None:
            return None
        return {
            "project_id": config.project_id,
            "target_platform": config.target_platform,
            "target_duration_sec": config.target_duration_sec,
            "formula_id": config.formula_id,
            "archetype": config.archetype,
            "tone_grid": config.tone_grid or {},
            "audience_override": config.audience_override,
            "compliance_region": config.compliance_region,
            "compliance_profile_id": config.compliance_profile_id,
            "target_kpi": config.target_kpi,
        }

    def _combine(
        self, project: Project, config: CommerceStoryConfig | None
    ) -> dict[str, Any]:
        """合成 Project + CommerceStoryConfig 的响应负载。"""
        payload = self._project_to_dict(project)
        payload["config"] = self._config_to_dict(config)
        return payload

    # ------------------------------------------------------------------
    # 主流程：创建 / 列表 / 详情
    # ------------------------------------------------------------------

    async def create(self, body: StoryProjectCreate) -> dict[str, Any]:
        """同事务创建 Project + CommerceStoryConfig。

        ``Project.kind`` 由服务端强制写入为 ``commerce_story``，避免客户
        端错填导致项目类型混乱。任意一步失败都会触发 SQLAlchemy 的事务
        回滚（由 ``get_db`` 在异常时执行 ``rollback``）。

        Args:
            body: 包含 Project 核心字段与 CommerceStoryConfig 嵌套字段。

        Returns:
            合并后的项目详情 dict（与 ``StoryProjectRead`` 字段对齐）。

        Raises:
            HTTPException: 当 ID 已存在或字段冲突时返回 409 / 400。
        """
        existing = await self._db.get(Project, body.id)
        if existing is not None:
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail="StoryProject id already exists",
            )

        project = Project(
            id=body.id,
            name=body.name,
            description=body.description,
            style=body.style,
            visual_style=body.visual_style,
            seed=body.seed,
            kind=ProjectKind.commerce_story.value,
            unify_style=body.unify_style,
            progress=body.progress,
            default_video_ratio=body.default_video_ratio,
            stats=body.stats or {},
        )
        cfg = body.config
        config = CommerceStoryConfig(
            project_id=body.id,
            target_platform=cfg.target_platform,
            target_duration_sec=cfg.target_duration_sec,
            formula_id=cfg.formula_id,
            archetype=cfg.archetype,
            tone_grid=cfg.tone_grid or {},
            audience_override=cfg.audience_override,
            compliance_region=cfg.compliance_region,
            compliance_profile_id=cfg.compliance_profile_id,
            target_kpi=cfg.target_kpi,
        )

        self._db.add(project)
        try:
            await self._db.flush()
            self._db.add(config)
            await self._db.flush()
        except IntegrityError as exc:
            await self._db.rollback()
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail=f"StoryProject create conflict: {exc.orig}",
            ) from exc
        await self._db.refresh(project)
        await self._db.refresh(config)
        return self._combine(project, config)

    async def list_projects(self) -> list[dict[str, Any]]:
        """返回所有 ``kind=commerce_story`` 项目（含其 1:1 config）。

        说明：当前不引入分页参数，剧情带货项目数量预期较少；如后续规模
        变大，可在路由层补 ``page`` / ``page_size``，此处保持 service 形
        状稳定即可。
        """
        stmt = (
            select(Project)
            .where(Project.kind == ProjectKind.commerce_story.value)
            .order_by(Project.created_at.desc())
        )
        result = await self._db.execute(stmt)
        projects = list(result.scalars().all())

        out: list[dict[str, Any]] = []
        for proj in projects:
            cfg = await self._get_config(proj.id)
            out.append(self._combine(proj, cfg))
        return out

    async def get_detail(self, project_id: str) -> dict[str, Any]:
        """读取项目详情（Project + CommerceStoryConfig）。

        Raises:
            HTTPException: 项目不存在或非 commerce_story 类型时 404。
        """
        project = await self._get_project_or_404(project_id)
        config = await self._get_config(project.id)
        return self._combine(project, config)

    # ------------------------------------------------------------------
    # 配置 PATCH
    # ------------------------------------------------------------------

    async def update_config(
        self,
        project_id: str,
        body: StoryProjectConfigUpdate,
    ) -> dict[str, Any]:
        """仅更新 CommerceStoryConfig 字段。

        Project 核心字段（name/style/...）走通用 PATCH，不在本接口处理。
        若该项目的 config 行缺失，视为 404，让客户端走"先补 config"路径
        而不是默默创建（避免静默偏离创建链路约束）。

        Returns:
            合并后的项目详情 dict（含最新 config）。
        """
        project = await self._get_project_or_404(project_id)
        config = await self._get_config(project.id)
        if config is None:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail=entity_not_found("CommerceStoryConfig"),
            )
        updates = body.model_dump(exclude_unset=True)
        for key, value in updates.items():
            setattr(config, key, value)
        await self._db.flush()
        await self._db.refresh(config)
        return self._combine(project, config)

    # ------------------------------------------------------------------
    # 商品挂载
    # ------------------------------------------------------------------

    async def link_product(
        self,
        project_id: str,
        product_id: str,
        body: ProjectProductLinkCreate,
    ) -> ProjectProductLink:
        """为项目挂载一个商品（项目级 link，不绑定 chapter / shot）。

        SQL 三大常见方言（SQLite / MySQL / PostgreSQL <15）均把 NULL 视
        为不相等，UNIQUE 约束无法在 ``chapter_id`` / ``shot_id`` 同时为
        NULL 时阻止重复。因此本方法先用显式 ``IS NULL`` 查询做项目级
        scope 的去重，再尝试 INSERT；同时保留对 ``IntegrityError`` 的
        兜底捕获，覆盖未来 chapter / shot 维度扩展时由 DB 拒绝重复的
        路径。

        Raises:
            HTTPException:
                - 404：项目不存在或非 commerce_story 项目。
                - 409：同 scope 下已挂载该商品。
        """
        await self._get_project_or_404(project_id)
        existing_stmt = select(ProjectProductLink).where(
            ProjectProductLink.project_id == project_id,
            ProjectProductLink.product_id == product_id,
            ProjectProductLink.chapter_id.is_(None),
            ProjectProductLink.shot_id.is_(None),
        )
        existing = (await self._db.execute(existing_stmt)).scalar_one_or_none()
        if existing is not None:
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail="ProjectProductLink already exists for this scope",
            )

        link = ProjectProductLink(
            project_id=project_id,
            product_id=product_id,
            chapter_id=None,
            shot_id=None,
            role_in_story=body.role_in_story,
            appearance_timing=body.appearance_timing,
            appearance_duration_sec=body.appearance_duration_sec,
        )
        self._db.add(link)
        try:
            await self._db.flush()
        except IntegrityError as exc:
            await self._db.rollback()
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail="ProjectProductLink already exists for this scope",
            ) from exc
        await self._db.refresh(link)
        return link

    async def unlink_product(
        self,
        project_id: str,
        product_id: str,
    ) -> None:
        """删除项目-商品挂载（按 (project_id, product_id) + 项目级 scope 匹配）。

        Raises:
            HTTPException: 项目不存在 → 404；挂载记录不存在 → 404。
        """
        await self._get_project_or_404(project_id)
        stmt = select(ProjectProductLink).where(
            ProjectProductLink.project_id == project_id,
            ProjectProductLink.product_id == product_id,
            ProjectProductLink.chapter_id.is_(None),
            ProjectProductLink.shot_id.is_(None),
        )
        result = await self._db.execute(stmt)
        link = result.scalar_one_or_none()
        if link is None:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail=entity_not_found("ProjectProductLink"),
            )
        # 显式 DELETE 比 ``db.delete(link)`` 更直接，避免触发 ORM 关系级联
        # 副作用（当前模型未声明反向 relationship，二者等效）。
        await self._db.execute(
            delete(ProjectProductLink).where(ProjectProductLink.id == link.id)
        )
        await self._db.flush()


__all__ = [
    "StoryProjectsService",
]
