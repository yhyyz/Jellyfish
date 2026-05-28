"""自定义音色训练 4 endpoints（P5 W29 引入）。

为什么存在：
    P3 W17 的 ``voice_packs.py`` 只暴露只读列表给 VoicePackPicker 使用；
    P5 W29 把"用户上传 → DashScope voice clone → 异步轮询 → 写入 VoicePack
    可被 TTS 合成路径选用"完整管线落到 HTTP API 上：

    - ``POST /api/v1/commerce/voice-packs/custom`` (multipart upload)
    - ``GET  /api/v1/commerce/voice-packs/custom/{voice_pack_id}/status``
    - ``GET  /api/v1/commerce/voice-packs/custom`` (分页列表)
    - ``DELETE /api/v1/commerce/voice-packs/custom/{voice_pack_id}``

按 AGENTS.md §4 严格分层：
    - 本路由层只负责收参 / size cap 校验 / 调 service / 包装 ApiResponse；
    - 业务逻辑全部下沉到 :mod:`app.services.studio.voice_clone_service` +
      :class:`CommerceTaskDispatchService`；
    - W19b 双引擎事务边界契约：``persist_voice_pack`` 内部 commit；caller
      必须在 commit 后才能调 ``dispatch_after_commit``。
"""

from __future__ import annotations

from fastapi import (
    APIRouter,
    Depends,
    File,
    Form,
    HTTPException,
    Query,
    Request,
    UploadFile,
    status,
)
from pydantic import ValidationError
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.contracts.voice_pack_contracts import (
    CustomVoiceCreateRequest,
    CustomVoiceCreateResponse,
    CustomVoiceStatusResponse,
)
from app.dependencies import get_db
from app.models.types import VoiceCloneStatus, VoiceRegion
from app.models.voice_pack import VoicePack
from app.schemas.commerce.voice_pack import CustomVoiceListItem
from app.schemas.common import (
    ApiResponse,
    PaginatedData,
    created_response,
    empty_response,
    paginated_response,
    success_response,
)
from app.services.commerce.task_dispatch import CommerceTaskDispatchService
from app.services.studio.voice_clone_service import (
    create_voice_remote,
    delete_voice_remote,
    persist_voice_pack,
    upload_sample_to_oss,
    validate_audio_metadata,
)


router = APIRouter()


# DashScope 单条 sample 文件最大 10 MB；与 voice_clone_service 同源约束。
_MAX_UPLOAD_BYTES = 10 * 1024 * 1024


def _enforce_size_limit(request: Request) -> None:
    """根据 ``Content-Length`` header 做前置体积检查。

    与 ``outcomes_import.py`` 同样的双重校验思路：先按 header 提前 reject
    超大请求，再让底层 read 时硬截断。本路由不需要流式 reader，因为 sample
    文件本身就已被 size 限制（10MB），整体读入内存可接受。
    """
    raw = request.headers.get("content-length")
    if not raw:
        return
    try:
        size = int(raw)
    except ValueError:
        return
    if size > _MAX_UPLOAD_BYTES:
        raise HTTPException(
            status_code=status.HTTP_413_REQUEST_ENTITY_TOO_LARGE,
            detail=f"file size {size} exceeds {_MAX_UPLOAD_BYTES} bytes limit",
        )


def _format_from_filename(filename: str | None) -> str:
    """从文件名后缀推断 declared_format（小写）。

    voice clone 严格限制 ``wav`` / ``mp3`` / ``m4a``；非法后缀直接 reject。
    """
    if not filename or "." not in filename:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="filename must include extension (.wav / .mp3 / .m4a)",
        )
    suffix = filename.rsplit(".", 1)[-1].lower().strip()
    if suffix not in {"wav", "mp3", "m4a"}:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"unsupported audio format: {suffix}",
        )
    return suffix


@router.post(
    "/voice-packs/custom",
    response_model=ApiResponse[CustomVoiceCreateResponse],
    status_code=status.HTTP_202_ACCEPTED,
    summary="上传 voice sample 创建自定义音色（异步训练）",
)
async def create_custom_voice_pack_endpoint(
    request: Request,
    sample_file: UploadFile = File(
        ..., description="voice sample 音频文件（wav / mp3 / m4a，<=10 MB，10-60 秒）"
    ),
    prefix: str = Form(
        ...,
        description="DashScope voice clone prefix；<=10 字符，仅数字/字母/下划线",
    ),
    target_model: str = Form(
        ...,
        description="DashScope 目标合成模型（cosyvoice-v3.5-plus / cosyvoice-v3-plus）",
    ),
    region: str = Form(
        ..., description="DashScope 区域端点（cn-beijing / ap-singapore）"
    ),
    display_name: str = Form(..., description="用户可见的音色展示名称"),
    language_hints: str | None = Form(
        None,
        description="可选 language hints（逗号分隔，如 'zh' 或 'en,fr'）",
    ),
    description: str | None = Form(None, description="可选业务描述（<=255 字符）"),
    archetype_hint: str | None = Form(None, description="可选 BrandArchetype 提示"),
    db: AsyncSession = Depends(get_db),
) -> ApiResponse[CustomVoiceCreateResponse]:
    """multipart 接收 sample 文件 + 元信息，链式触发 DashScope create_voice + 异步轮询。

    流程：
        1. 前置 size cap（``Content-Length`` header，413 早 reject）。
        2. 解析 declared_format（从文件名后缀）+ 校验 form 字段（CustomVoiceCreateRequest）。
        3. 读取 sample 字节流（受 size cap 限制）。
        4. ``validate_audio_metadata`` 二次校验音频元信息。
        5. ``upload_sample_to_oss`` 转存到 minio bucket。
        6. ``create_voice_remote`` 调 DashScope 拿到 voice_id（仍 DEPLOYING）。
        7. ``persist_voice_pack`` 写 VoicePack(is_system=False, clone_status=deploying)
           + commit（W19b 契约：commit 后才能 dispatch）。
        8. ``enqueue_voice_clone_poll`` 落 GenerationTask 行 + commit + dispatch。
        9. 返回 ``202 Accepted`` + voice_pack_id。
    """
    _enforce_size_limit(request)
    declared_format = _format_from_filename(sample_file.filename)

    parsed_hints: list[str] | None = None
    if language_hints:
        parsed_hints = [item.strip() for item in language_hints.split(",") if item.strip()]
        if not parsed_hints:
            parsed_hints = None

    try:
        region_enum = VoiceRegion(region)
    except ValueError as exc:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail=f"unsupported region: {region}",
        ) from exc

    try:
        create_request = CustomVoiceCreateRequest(
            prefix=prefix,
            target_model=target_model,  # type: ignore[arg-type]
            region=region_enum,
            display_name=display_name,
            language_hints=parsed_hints,
            description=description,
            archetype_hint=archetype_hint,
        )
    except ValidationError as exc:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail={
                "message": "form validation failed",
                "errors": exc.errors(),
            },
        ) from exc

    file_bytes = await sample_file.read()
    if len(file_bytes) > _MAX_UPLOAD_BYTES:
        raise HTTPException(
            status_code=status.HTTP_413_REQUEST_ENTITY_TOO_LARGE,
            detail=f"file body exceeds {_MAX_UPLOAD_BYTES} bytes limit",
        )

    validation, failures = validate_audio_metadata(file_bytes, declared_format)
    if validation is None:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail={
                "message": "audio metadata validation failed",
                "failures": [f.to_dict() for f in failures],
            },
        )

    oss_key, public_url = await upload_sample_to_oss(file_bytes, declared_format)

    dashscope_voice_id = await create_voice_remote(
        target_model=create_request.target_model,
        prefix=create_request.prefix,
        sample_url=public_url,
        region=create_request.region,
        language_hints=create_request.language_hints,
    )

    voice_pack = await persist_voice_pack(
        db,
        request=create_request,
        sample_audio_oss_key=oss_key,
        dashscope_voice_id=dashscope_voice_id,
    )

    dispatcher = CommerceTaskDispatchService(db)
    descriptor = await dispatcher.enqueue_voice_clone_poll(
        {"voice_pack_id": voice_pack.id}
    )
    await db.commit()
    dispatcher.dispatch_after_commit(descriptor)

    response_payload = CustomVoiceCreateResponse(
        voice_pack_id=voice_pack.id,
        clone_status=VoiceCloneStatus(voice_pack.clone_status),
        created_at=voice_pack.created_at,
    )
    return created_response(response_payload)


@router.get(
    "/voice-packs/custom/{voice_pack_id}/status",
    response_model=ApiResponse[CustomVoiceStatusResponse],
    summary="查询单条自定义音色 clone_status（前端轮询用）",
)
async def get_custom_voice_status_endpoint(
    voice_pack_id: str,
    db: AsyncSession = Depends(get_db),
) -> ApiResponse[CustomVoiceStatusResponse]:
    """查询单条自定义音色当前状态。

    前端 VoicePackLibrary 凭此 endpoint 轮询 ``deploying`` 行直到终态
    （``ready`` / ``failed``）；终态后停止轮询。
    """
    voice_pack = await db.get(VoicePack, voice_pack_id)
    if voice_pack is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"voice_pack not found: {voice_pack_id}",
        )

    failure_reason: str | None = None
    if (
        voice_pack.clone_status == VoiceCloneStatus.failed.value
        or voice_pack.clone_status == VoiceCloneStatus.failed
    ):
        # description 末尾追加的失败原因由 voice_clone_poll_task 写入；这里
        # 解析回去给前端展示在 tooltip 里。
        desc = voice_pack.description or ""
        marker = "[clone_failed]"
        if marker in desc:
            failure_reason = desc.split(marker, 1)[1].strip()

    payload = CustomVoiceStatusResponse(
        voice_pack_id=voice_pack.id,
        clone_status=VoiceCloneStatus(voice_pack.clone_status)
        if voice_pack.clone_status
        else VoiceCloneStatus.deploying,
        provider_voice_id=voice_pack.provider_voice_id,
        failure_reason=failure_reason,
        cloned_at=voice_pack.cloned_at,
    )
    return success_response(payload)


@router.get(
    "/voice-packs/custom",
    response_model=ApiResponse[PaginatedData[CustomVoiceListItem]],
    summary="自定义音色分页列表（按 clone_status 可选过滤）",
)
async def list_custom_voice_packs_endpoint(
    clone_status: str | None = Query(
        None,
        description="按 clone_status 精确过滤（deploying / ready / failed / deleted）",
    ),
    page: int = Query(1, ge=1, description="页码（1 起）"),
    page_size: int = Query(20, ge=1, le=100, description="每页条数"),
    db: AsyncSession = Depends(get_db),
) -> ApiResponse[PaginatedData[CustomVoiceListItem]]:
    """列出全部自定义音色（``is_system=False``），按 created_at desc 排序。

    默认隐藏 ``deleted`` 状态行，让前端 VoicePackLibrary 不需要客户端再
    过滤；显式传 ``clone_status=deleted`` 可访问审计视图。
    """
    base = select(VoicePack).where(VoicePack.is_system.is_(False))

    if clone_status is not None:
        base = base.where(VoicePack.clone_status == clone_status)
    else:
        base = base.where(
            (VoicePack.clone_status.is_(None))
            | (VoicePack.clone_status != VoiceCloneStatus.deleted.value)
        )

    count_stmt = select(func.count()).select_from(base.subquery())
    total = (await db.execute(count_stmt)).scalar_one()

    stmt = (
        base.order_by(VoicePack.created_at.desc())
        .offset((page - 1) * page_size)
        .limit(page_size)
    )
    result = await db.execute(stmt)
    items = [
        CustomVoiceListItem.model_validate(row) for row in result.scalars().all()
    ]

    return paginated_response(
        items, page=page, page_size=page_size, total=int(total)
    )


@router.delete(
    "/voice-packs/custom/{voice_pack_id}",
    response_model=ApiResponse[None],
    summary="软删自定义音色 + 释放 DashScope 配额",
)
async def delete_custom_voice_pack_endpoint(
    voice_pack_id: str,
    db: AsyncSession = Depends(get_db),
) -> ApiResponse[None]:
    """软删自定义音色：标记 clone_status=deleted + 调 DashScope delete_voice 释放配额。

    幂等：voice_pack 不存在时返回 404；DashScope delete_voice 失败时容忍
    （:func:`delete_voice_remote` 内部捕获），仍把 DB 行标 deleted。

    系统级音色（``is_system=True``）禁止删除（403）。
    """
    voice_pack = await db.get(VoicePack, voice_pack_id)
    if voice_pack is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"voice_pack not found: {voice_pack_id}",
        )
    if voice_pack.is_system:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="system voice packs cannot be deleted",
        )

    region_value = voice_pack.region
    if isinstance(region_value, VoiceRegion):
        region_enum = region_value
    elif region_value:
        region_enum = VoiceRegion(region_value)
    else:
        region_enum = VoiceRegion.cn_beijing

    await delete_voice_remote(
        voice_id=voice_pack.provider_voice_id,
        region=region_enum,
    )

    voice_pack.clone_status = VoiceCloneStatus.deleted
    await db.commit()

    return empty_response()


__all__ = ["router"]
