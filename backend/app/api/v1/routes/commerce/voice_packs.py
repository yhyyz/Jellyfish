"""音色包只读接口（W20-T0b，P3 W17 配套）。

仅暴露列表 GET 路径：

- ``GET /api/v1/commerce/voice-packs``：按 ``language_code`` /
  ``is_system`` / ``provider`` 三轴过滤系统级与用户自定义音色包；默认
  按 ``is_system DESC`` + ``sort_order ASC`` + ``name ASC`` 三层稳定
  排序，让前端 VoicePackPicker 直接消费。

写入路径不开放给 API：系统级 seed 由
:func:`app.services.studio.builtin_voice_packs.bootstrap_builtin_voice_packs`
在启动期幂等加载；用户自定义 voice clone 上传走专门的语音克隆路径
（W20+ 在独立 wave 暴露），均不在本路由职责内。
"""

from __future__ import annotations

from fastapi import APIRouter, Depends, Query
from sqlalchemy.ext.asyncio import AsyncSession

from app.dependencies import get_db
from app.schemas.commerce.voice_packs import VoicePackRead
from app.schemas.common import ApiResponse, success_response
from app.services.commerce.voice_packs import list_voice_packs

router = APIRouter()


@router.get(
    "/voice-packs",
    response_model=ApiResponse[list[VoicePackRead]],
    summary="音色包列表（按语言 / 系统级 / 供应商过滤）",
)
async def list_voice_packs_endpoint(
    db: AsyncSession = Depends(get_db),
    language_code: str | None = Query(
        None,
        description="按语言代码过滤（如 zh-CN / en-US / ja-JP）",
    ),
    is_system: bool | None = Query(
        None,
        description="是否只列系统级 seed；true=仅系统 / false=仅用户自定义 / 缺省=全部",
    ),
    provider: str | None = Query(
        None,
        description="按 TTS 供应商过滤（如 aliyun_cosyvoice / openai_tts）",
    ),
) -> ApiResponse[list[VoicePackRead]]:
    """列出 ``voice_packs`` 表中的全部记录。

    路由职责保持瘦身：收参 → 调 service → ``model_validate`` →
    ``success_response``，不在此处做业务过滤或字段映射。
    """

    items = await list_voice_packs(
        db,
        language_code=language_code,
        is_system=is_system,
        provider=provider,
    )
    return success_response([VoicePackRead.model_validate(item) for item in items])
