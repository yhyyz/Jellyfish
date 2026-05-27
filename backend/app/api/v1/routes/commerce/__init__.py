"""``/api/v1/commerce`` 路由聚合（W6-T3 / W20-T0b）。

P1 阶段聚焦异步任务入口（商品信息抽取、剧情脚本生成、合规检查）；W20
前端工作室升级期补齐 2 条只读列表入口（音色包 / 字幕样式），供
VoicePackPicker / SubtitleStylePicker 等组件消费 P3 W17/W18 已落地的
内置 seed。后续 wave 会继续扩展商品 / 故事项目等 CRUD 端点。

按照分层约定，路由层只做收参 + 调 service + 包装 ``ApiResponse``，业务
逻辑全部下沉到 ``app/services/commerce``。
"""

from fastapi import APIRouter

from app.api.v1.routes.commerce import subtitle_styles, tasks, voice_packs

router = APIRouter()

router.include_router(tasks.router, tags=["commerce/tasks"])
router.include_router(voice_packs.router, tags=["commerce-voice-packs"])
router.include_router(subtitle_styles.router, tags=["commerce-subtitle-styles"])

__all__ = ["router"]
