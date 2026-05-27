#!/usr/bin/env python3
"""W21-T1: 商业化 keep_native 5 段管线 e2e 烟测脚本。

本脚本由 W19b 验证产物 ``/tmp/jellyfish-test/commerce_e2e_keep_native.py``
固化而来，按 ``backend/scripts/verify_dashscope_image.py`` 风格升级：

- argparse 参数化（``--base-url`` / ``--product-id`` / ``--subtitle-style-id`` / ...）；
- env 兜底：``JELLYFISH_BASE_URL`` 等环境变量优先于硬编码默认值；
- 三模式：``--help`` / ``--dry-run``（不发任何 HTTP）/ 默认 production（真跑 5 段管线）；
- 显式退出码：``0=成功`` / ``1=管线失败`` / ``2=参数校验失败``。

5 段管线（与 W19b-FINAL-platform-keepnative-1779858873.mp4 同口径）::

    Step 1 → 准备项目：products.GET → story-projects.POST → chapters.POST → 关联
    Step 2 → 5 镜头串行建模（shots / shot-details / shot-dialog-lines）
    Step 3 → 5 视频生成（reference_mode=multi_ref，1.5s stagger）+ 并行轮询
    Step 4 → ASR 链路（chain-race 兜底 + 字幕渲染）
    Step 5 → chapter timeline + chapter_av_export + 拿公网 url

运行（在 backend 目录）::

    # dry-run，不发请求
    uv run python scripts/p3_e2e_smoke.py --dry-run --product-id prod-xxx

    # production：需要 backend 在 :8088 跑 + 完整 API key
    uv run python scripts/p3_e2e_smoke.py --product-id prod-xxx
"""

# pylint: disable=invalid-name,too-many-arguments,too-many-locals,too-many-statements,too-many-branches

from __future__ import annotations

import argparse
import asyncio
import json
import os
import sys
import time
from pathlib import Path
from typing import Any

# 让 ``import app.*`` 在 backend/ 之外也能解析（脚本通常在 backend 目录跑）。
_BACKEND_ROOT = Path(__file__).resolve().parent.parent
if str(_BACKEND_ROOT) not in sys.path:
    sys.path.insert(0, str(_BACKEND_ROOT))

# ---------------------------------------------------------------------------
# 顶层常量：与 W19b 验证脚本一致；硬编码部分仅作 argparse 默认值，
# 真正运行时优先读 CLI / env。
# ---------------------------------------------------------------------------
DEFAULT_BASE_URL = "http://127.0.0.1:8088"
DEFAULT_SUBTITLE_STYLE_ID = "douyin_default"
DEFAULT_AUDIO_STRATEGY = "keep_native"
DEFAULT_SHOT_COUNT = 5
DEFAULT_VIDEO_POLL_TIMEOUT = 1800
DEFAULT_ASR_POLL_TIMEOUT = 600
DEFAULT_RENDER_POLL_TIMEOUT = 300
DEFAULT_EXPORT_POLL_TIMEOUT = 1800
DEFAULT_SUMMARY_PATH = "/tmp/jellyfish-test/p3-e2e-summary.json"

# ASR chain-race 兜底窗口：若 chain-dispatch 在该秒数内仍未把 ASR 任务落表，
# 走手动 POST /commerce/asr-subtitle-generate 兜底。
ASR_RACE_TIMEOUT_S = 90.0

# 5 镜头睡衣 keep_native 范本：与 W19b 验证用脚本一字一句对齐，
# 视觉描述 + 对白同时写进 video_prompt（r2v native audio 模式需要）。
SHOTS_PLAN: list[dict[str, Any]] = [
    {
        "title": "夜晚翻来覆去",
        "duration": 5.0,
        "dialog": "这睡衣摸起来就是凉凉的，皮肤一碰就舒服。",
        "video_prompt": (
            "亚洲女性主播身穿灰蓝色冰丝睡衣坐在白色床边，特写表情温柔，"
            "镜头慢推近，柔和暖光。她对镜头说话："
            "「这睡衣摸起来就是凉凉的，皮肤一碰就舒服。」"
            "口型清晰，温柔甜美的声音。9:16 竖屏。"
        ),
    },
    {
        "title": "面料展示",
        "duration": 5.0,
        "dialog": "你看这个垂感，一甩一甩的，不黏身。",
        "video_prompt": (
            "中近景，亚洲女性轻提睡衣袖口展示面料垂感，背景虚化温馨卧室。"
            "她笑着说：「你看这个垂感，一甩一甩的，不黏身。」"
            "动作自然，声音清亮。9:16 竖屏。"
        ),
    },
    {
        "title": "穿着体验",
        "duration": 5.0,
        "dialog": "晚上睡觉翻身都不会缠住，太透气了。",
        "video_prompt": (
            "亚洲女性穿着灰蓝睡衣慵懒躺在床上，慢镜头翻身展示版型。"
            "她轻声说：「晚上睡觉翻身都不会缠住，太透气了。」"
            "声音放松带着惬意。9:16 竖屏。"
        ),
    },
    {
        "title": "细节质感",
        "duration": 5.0,
        "dialog": "这个走线、这个滚边，都是高级品质。",
        "video_prompt": (
            "近景特写灰蓝睡衣领口走线和滚边细节，手指轻抚面料。"
            "画外女声温柔：「这个走线、这个滚边，都是高级品质。」"
            "9:16 竖屏。"
        ),
    },
    {
        "title": "购买引导",
        "duration": 5.0,
        "dialog": "今晚就给自己买一套，睡得香人就漂亮。",
        "video_prompt": (
            "亚洲女性身穿灰蓝睡衣坐在床上对镜头温柔微笑，伸手指向画面下方。"
            "她说：「今晚就给自己买一套，睡得香人就漂亮。」"
            "结尾收音明亮。9:16 竖屏。"
        ),
    },
]


# ---------------------------------------------------------------------------
# argparse：参数化所有可调项 + env 兜底。
# ---------------------------------------------------------------------------


def build_argparser() -> argparse.ArgumentParser:
    """构造 ``p3_e2e_smoke.py`` 的 CLI 参数表。

    将"参数定义"独立成函数有两层作用：

    1. 让单元测试可以通过 ``import_module`` + ``build_argparser()`` 反射出
       完整 CLI 表面，避免 GREEN 阶段误删任意必填参数；
    2. 让 ``--help`` 输出和 ``main()`` 的实际处理路径共用同一个 parser，
       消除两边描述漂移。

    Returns:
        argparse.ArgumentParser：已注册全部参数（含 env 兜底）。
    """
    parser = argparse.ArgumentParser(
        prog="p3_e2e_smoke",
        description=(
            "Commerce keep_native 5 段管线 e2e 烟测："
            "products / story-projects / chapters / shots → r2v video → ASR → 字幕 → chapter_av_export"
        ),
        formatter_class=argparse.ArgumentDefaultsHelpFormatter,
    )
    parser.add_argument(
        "--base-url",
        default=os.environ.get("JELLYFISH_BASE_URL", DEFAULT_BASE_URL),
        help=(
            "Backend base URL（默认读环境变量 JELLYFISH_BASE_URL，"
            f"未设置则用 {DEFAULT_BASE_URL}）"
        ),
    )
    parser.add_argument(
        "--product-id",
        default=os.environ.get("JELLYFISH_PRODUCT_ID"),
        help="必填：要绑定到 story-project 的商品 ID（也可通过 JELLYFISH_PRODUCT_ID 提供）",
    )
    parser.add_argument(
        "--subtitle-style-id",
        default=os.environ.get("JELLYFISH_SUBTITLE_STYLE_ID", DEFAULT_SUBTITLE_STYLE_ID),
        help="字幕风格 ID（POST /commerce/shot-subtitle-render 用）",
    )
    parser.add_argument(
        "--audio-strategy",
        default=DEFAULT_AUDIO_STRATEGY,
        choices=["keep_native", "silent_with_tts"],
        help="音频策略：keep_native（保留模型原声）或 silent_with_tts（静音 + TTS 合成）",
    )
    parser.add_argument(
        "--shot-count",
        type=int,
        default=DEFAULT_SHOT_COUNT,
        help="镜头数量；当前内置 SHOTS_PLAN 仅 5 条，超出会复用末尾或被截断",
    )
    parser.add_argument(
        "--video-poll-timeout",
        type=int,
        default=DEFAULT_VIDEO_POLL_TIMEOUT,
        help="视频任务轮询超时（秒）",
    )
    parser.add_argument(
        "--asr-poll-timeout",
        type=int,
        default=DEFAULT_ASR_POLL_TIMEOUT,
        help="ASR 任务轮询超时（秒）",
    )
    parser.add_argument(
        "--render-poll-timeout",
        type=int,
        default=DEFAULT_RENDER_POLL_TIMEOUT,
        help="字幕渲染任务轮询超时（秒）",
    )
    parser.add_argument(
        "--export-poll-timeout",
        type=int,
        default=DEFAULT_EXPORT_POLL_TIMEOUT,
        help="chapter_av_export 任务轮询超时（秒）",
    )
    parser.add_argument(
        "--summary-path",
        default=os.environ.get("JELLYFISH_E2E_SUMMARY_PATH", DEFAULT_SUMMARY_PATH),
        help="管线汇总 JSON 写盘路径（包含 task_ids / file_ids / public_url）",
    )
    parser.add_argument(
        "--project-id-prefix",
        default="proj-p3-e2e",
        help="自动派生的 story-project ID 前缀（实际 ID 会拼接时间戳）",
    )
    parser.add_argument(
        "--chapter-id-prefix",
        default="ch-p3-e2e",
        help="自动派生的 chapter ID 前缀",
    )
    parser.add_argument(
        "--shot-id-prefix",
        default="sh-p3-e2e",
        help="自动派生的 shot ID 前缀（最终 ID = prefix-{idx}）",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="不发任何 HTTP 请求，仅打印管线计划和参数；用于 CI / 离线 smoke",
    )
    return parser


# 兼容老接口（测试既允许 ``build_argparser`` 也允许 ``_build_argparser``）。
_build_argparser = build_argparser


# ---------------------------------------------------------------------------
# helpers：从源脚本搬过来 + 重新写中文注释。延迟 import httpx，避免
# dry-run 路径在缺 httpx 的环境下也能跑通。
# ---------------------------------------------------------------------------


async def call(client: Any, method: str, path: str, *, base_url: str, **kw: Any) -> dict[str, Any]:
    """统一 HTTP 调用封装。

    功能：包装后端 ``ApiResponse{code,message,data}`` 协议，4xx/5xx 时
    打印响应 body 前 500 字再抛出 ``HTTPStatusError``，方便定位远端错误。

    Args:
        client: ``httpx.AsyncClient`` 实例（dry-run 模式下不会进入此函数）。
        method: HTTP 动词（GET/POST/PUT 等）。
        path: 相对路径，会拼到 ``{base_url}/api/v1`` 之后。
        base_url: 后端 base URL，对应 ``--base-url``。
        **kw: 透传给 ``client.request``（``json=`` / ``params=`` 等）。

    Returns:
        dict：解析后的 ApiResponse JSON（含顶层 ``code``/``message``/``data``）。

    Raises:
        httpx.HTTPStatusError: 4xx/5xx 状态码。
        RuntimeError: ApiResponse 中 ``code >= 400`` 的业务错误。
    """
    import httpx  # 局部 import：dry-run 路径不依赖 httpx 也能跑

    api_root = f"{base_url}/api/v1"
    resp = await client.request(method, f"{api_root}{path}", **kw)
    if resp.status_code >= 400:
        try:
            body_text = resp.text
        except Exception:  # noqa: BLE001
            body_text = "<no body>"
        print(f"  HTTP {resp.status_code} on {method} {path}: {body_text[:500]}")
        resp.raise_for_status()
    body = resp.json()
    if isinstance(body, dict) and body.get("code", 200) >= 400:
        raise RuntimeError(f"API error {method} {path}: {body}")
    # mypy/pyright 友好：保证返回 dict 类型。
    if not isinstance(body, dict):
        return {"data": body}
    return body


async def poll_task_resilient(
    client: Any,
    task_id: str,
    *,
    base_url: str,
    timeout_s: float = DEFAULT_VIDEO_POLL_TIMEOUT,
) -> dict[str, Any]:
    """容忍短暂网络抖动地轮询任务状态，直到 succeeded/failed/cancelled/超时。

    Args:
        client: ``httpx.AsyncClient`` 实例。
        task_id: 任务 ID（来自各 dispatch 接口）。
        base_url: 后端 base URL。
        timeout_s: 总轮询超时；超过则抛 ``TimeoutError``。

    Returns:
        dict：``GET /film/tasks/{id}/result`` 的 ``result`` 子字段（若有）。

    关键内部逻辑：
        - 连续 8 次 ``ReadError`` / ``RemoteProtocolError`` 才放弃，让短暂
          网络断连不影响长任务（视频生成可能 3-5 分钟）。
        - progress 变化时才打印日志，避免刷屏。
    """
    import httpx

    deadline = time.time() + timeout_s
    consecutive_errors = 0
    last_progress = -1
    while time.time() < deadline:
        try:
            data = (
                await call(client, "GET", f"/film/tasks/{task_id}/status", base_url=base_url)
            ).get("data", {})
            consecutive_errors = 0
            status = data.get("status")
            progress = data.get("progress", 0)
            if progress != last_progress:
                print(f"  task={task_id[:8]} status={status} progress={progress}%")
                last_progress = progress
            if status == "succeeded":
                result = (
                    await call(client, "GET", f"/film/tasks/{task_id}/result", base_url=base_url)
                ).get("data", {})
                return result.get("result") or result
            if status in ("failed", "cancelled"):
                err = data.get("error_message") or data.get("error") or "(no error message)"
                raise RuntimeError(f"task {task_id} {status}: {err}")
        except (
            httpx.ReadError,
            httpx.RemoteProtocolError,
            httpx.ConnectError,
            httpx.PoolTimeout,
        ) as exc:
            consecutive_errors += 1
            if consecutive_errors > 8:
                raise
            print(
                f"  transient {type(exc).__name__} on task {task_id[:8]}; "
                f"retry {consecutive_errors}/8"
            )
            await asyncio.sleep(3.0)
            continue
        await asyncio.sleep(5.0)
    raise TimeoutError(f"task {task_id} not done within {timeout_s}s")


async def discover_chained_asr_task(
    client: Any, video_file_id: str, *, base_url: str
) -> str | None:
    """通过任务中心 HTTP 接口反查 chain-dispatched ASR 任务 ID。

    Args:
        client: ``httpx.AsyncClient`` 实例。
        video_file_id: 视频任务产出的 file_id；ASR worker 会把它写进 result.source_file_id。
        base_url: 后端 base URL。

    Returns:
        匹配的 ASR ``task_id``；若窗口内未发现则返回 ``None``。

    关键内部逻辑：
        1. 列举最近 600s 内的 asr_subtitle_generate 任务（pending/running/succeeded）；
        2. 对每条任务读取 result.source_file_id，命中 ``video_file_id`` 则返回。
        3. pending/running 阶段 result 还没写，调用方需用 ``ensure_asr_for_video``
           兜底超时 + 手动 POST。
    """
    import httpx

    try:
        listing_resp = await call(
            client,
            "GET",
            "/film/tasks",
            base_url=base_url,
            params=[
                ("task_kind", "asr_subtitle_generate"),
                ("statuses", "pending"),
                ("statuses", "running"),
                ("statuses", "succeeded"),
                ("recent_seconds", "600"),
                ("page_size", "50"),
            ],
        )
    except (httpx.HTTPError, RuntimeError):
        return None
    items = ((listing_resp.get("data") or {}).get("items")) or []
    for item in items:
        tid = item.get("task_id")
        if not tid:
            continue
        try:
            result_resp = (
                await call(client, "GET", f"/film/tasks/{tid}/result", base_url=base_url)
            ).get("data") or {}
        except (httpx.HTTPError, RuntimeError):
            continue
        result_payload = result_resp.get("result") or {}
        if isinstance(result_payload, dict) and result_payload.get("source_file_id") == video_file_id:
            return tid
    return None


async def ensure_asr_for_video(
    client: Any, video_file_id: str, *, base_url: str
) -> tuple[str, bool]:
    """确保给定视频一定有 ASR 任务：先等 chain-race，再走兜底 POST。

    Args:
        client: ``httpx.AsyncClient`` 实例。
        video_file_id: 视频任务产出 file_id。
        base_url: 后端 base URL。

    Returns:
        ``(task_id, used_fallback)``：``used_fallback=True`` 代表走了
        手动 POST ``/commerce/asr-subtitle-generate`` 兜底路径。
    """
    deadline = time.time() + ASR_RACE_TIMEOUT_S
    while time.time() < deadline:
        tid = await discover_chained_asr_task(client, video_file_id, base_url=base_url)
        if tid:
            print(f"  chained ASR task discovered: {tid[:8]} (video={video_file_id[:8]})")
            return tid, False
        await asyncio.sleep(2.0)
    print(f"  chain-race miss for video={video_file_id[:8]}; falling back to manual POST")
    body = {"video_file_id": video_file_id}
    resp = (
        await call(client, "POST", "/commerce/asr-subtitle-generate", base_url=base_url, json=body)
    ).get("data", {})
    return resp["task_id"], True


def _is_already_exists(exc: Any) -> bool:
    """判断后端冲突错误：兼容 409 与 400+'already exists'/'已存在' 两种风格。

    Args:
        exc: ``httpx.HTTPStatusError`` 实例。

    Returns:
        bool：True 表示资源已存在，调用方可吞掉错误继续复用。
    """
    if exc.response.status_code == 409:
        return True
    if exc.response.status_code == 400:
        try:
            msg = (exc.response.json() or {}).get("message", "")
        except Exception:  # noqa: BLE001
            return False
        return "already exists" in msg.lower() or "已存在" in msg
    return False


# ---------------------------------------------------------------------------
# 5 段 stage：每段一个 async 函数，main() 串起来。
# ---------------------------------------------------------------------------


async def prepare_project(
    client: Any,
    *,
    base_url: str,
    project_id: str,
    chapter_id: str,
    product_id: str,
) -> None:
    """Step 1：准备项目 / 章节 / 商品关联（全部 409 容忍，复用已存在资源）。

    功能：覆盖源脚本 Step 0 ~ 2.5：
        - GET /studio/products/{pid} 校验商品存在；
        - POST /studio/story-projects 创建项目（已存在则复用）；
        - POST /studio/chapters 创建章节；
        - POST /studio/story-projects/{pid}/products/{pid} 关联商品（multi_ref 必备）。

    Args:
        client: httpx AsyncClient 实例。
        base_url: 后端 base URL。
        project_id: 期望使用的 story-project ID。
        chapter_id: 期望使用的 chapter ID。
        product_id: 已存在商品 ID（需先在 product 库里创建好）。
    """
    import httpx

    prod_resp = await call(client, "GET", f"/studio/products/{product_id}", base_url=base_url)
    print(f"product OK: {prod_resp['data']['name']}")

    try:
        await call(
            client,
            "POST",
            "/studio/story-projects",
            base_url=base_url,
            json={"id": project_id, "name": "P3 keep_native e2e"},
        )
        print(f"story-project created: {project_id}")
    except httpx.HTTPStatusError as exc:
        if _is_already_exists(exc):
            print(f"story-project exists, reusing: {project_id}")
        else:
            raise

    try:
        await call(
            client,
            "POST",
            "/studio/chapters",
            base_url=base_url,
            json={
                "id": chapter_id,
                "project_id": project_id,
                "index": 1,
                "title": "P3 e2e 25s 带货 (native audio)",
            },
        )
        print(f"chapter created: {chapter_id}")
    except httpx.HTTPStatusError as exc:
        if _is_already_exists(exc):
            print(f"chapter exists, reusing: {chapter_id}")
        else:
            raise

    try:
        await call(
            client,
            "POST",
            f"/studio/story-projects/{project_id}/products/{product_id}",
            base_url=base_url,
            json={
                "role_in_story": "protagonist_companion",
                "appearance_timing": "middle",
                "appearance_duration_sec": 5,
            },
        )
        print(f"product linked to project: {product_id} → {project_id}")
    except httpx.HTTPStatusError as exc:
        if _is_already_exists(exc):
            print("product link exists, reusing")
        else:
            raise


async def model_shots(
    client: Any,
    *,
    base_url: str,
    chapter_id: str,
    shot_ids: list[str],
    audio_strategy: str,
) -> None:
    """Step 2：5 镜头串行建模 —— shots / shot-details / shot-dialog-lines。

    功能：覆盖源脚本 Step 3。每个镜头依次创建：
        - Shot（``audio_strategy`` / ``product_focus_level=hero``）；
        - ShotDetail（camera_shot=MS, angle=EYE_LEVEL, duration=5s）；
        - ShotDialogLine（``DIALOGUE`` 模式，文本来自 SHOTS_PLAN）。

    Args:
        client: httpx AsyncClient 实例。
        base_url: 后端 base URL。
        chapter_id: 已存在的 chapter ID。
        shot_ids: 期望使用的 shot ID 列表（与 SHOTS_PLAN 对齐）。
        audio_strategy: 音频策略，CLI 透传（默认 keep_native）。

    关键内部逻辑：
        每个 POST 都用 ``_is_already_exists`` 容忍重跑场景；这让脚本
        在 W19b 验证那种"中途崩溃后重启"也能 idempotent。
    """
    import httpx

    plans = list(zip(shot_ids, SHOTS_PLAN[: len(shot_ids)]))
    for idx, (shot_id, plan) in enumerate(plans):
        shot_body = {
            "id": shot_id,
            "chapter_id": chapter_id,
            "index": idx + 1,
            "title": plan["title"],
            "audio_strategy": audio_strategy,
            "product_focus_level": "hero",
        }
        try:
            await call(client, "POST", "/studio/shots", base_url=base_url, json=shot_body)
        except httpx.HTTPStatusError as exc:
            if not _is_already_exists(exc):
                raise

        try:
            await call(
                client,
                "POST",
                "/studio/shot-details",
                base_url=base_url,
                json={
                    "id": shot_id,
                    "camera_shot": "MS",
                    "angle": "EYE_LEVEL",
                    "movement": "STATIC",
                    "duration": plan["duration"],
                },
            )
        except httpx.HTTPStatusError as exc:
            if not _is_already_exists(exc):
                raise

        try:
            await call(
                client,
                "POST",
                "/studio/shot-dialog-lines",
                base_url=base_url,
                json={
                    "shot_detail_id": shot_id,
                    "index": 0,
                    "text": plan["dialog"],
                    "line_mode": "DIALOGUE",
                },
            )
        except httpx.HTTPStatusError as exc:
            if not _is_already_exists(exc):
                raise

        print(f"  shot[{idx}] ready: {shot_id}")


async def generate_videos(
    client: Any,
    *,
    base_url: str,
    shot_ids: list[str],
    video_poll_timeout: int,
    summary: dict[str, Any],
) -> list[str]:
    """Step 3：5 视频生成（multi_ref + 1.5s stagger） + 并行轮询。

    功能：覆盖源脚本 Step 4-5：
        - 串行 POST /film/tasks/video（reference_mode=multi_ref / ratio=9:16）；
        - 1.5 秒 stagger，避免触发 SQLite 写锁竞争（生产 MySQL 也无害）；
        - asyncio.gather 并行轮询 5 个视频任务。

    Args:
        client: httpx AsyncClient 实例。
        base_url: 后端 base URL。
        shot_ids: 已建模的 shot ID 列表。
        video_poll_timeout: 单个视频任务轮询超时（秒）。
        summary: 全局 summary dict，会写入 ``video_task_ids`` / ``video_file_ids``。

    Returns:
        list[str]：5 个视频任务产出的 file_id（顺序与 shot_ids 一致）。
    """
    print("--- triggering video tasks (multi_ref r2v, staggered 1.5s) ---")
    plans = list(zip(shot_ids, SHOTS_PLAN[: len(shot_ids)]))
    video_task_resps = []
    for shot_id, plan in plans:
        resp = await call(
            client,
            "POST",
            "/film/tasks/video",
            base_url=base_url,
            json={
                "shot_id": shot_id,
                "reference_mode": "multi_ref",
                "ratio": "9:16",
                "prompt": plan["video_prompt"],
            },
        )
        video_task_resps.append(resp)
        await asyncio.sleep(1.5)
    video_task_ids = [r["data"]["task_id"] for r in video_task_resps]
    summary["video_task_ids"] = video_task_ids
    print(f"  {len(video_task_ids)} video tasks dispatched: {[t[:8] for t in video_task_ids]}")

    print(f"--- polling {len(video_task_ids)} videos (r2v ~3-5min each) ---")
    video_results = await asyncio.gather(
        *[
            poll_task_resilient(client, tid, base_url=base_url, timeout_s=video_poll_timeout)
            for tid in video_task_ids
        ]
    )
    video_file_ids: list[str] = []
    for r in video_results:
        fid = r.get("file_id") or r.get("video_file_id")
        if not fid:
            raise RuntimeError(f"video task missing file_id: {r}")
        video_file_ids.append(fid)
    summary["video_file_ids"] = video_file_ids
    print(f"  {len(video_file_ids)} videos done: {[f[:8] for f in video_file_ids]}")
    return video_file_ids


async def asr_and_render_subtitles(
    client: Any,
    *,
    base_url: str,
    shot_ids: list[str],
    video_file_ids: list[str],
    subtitle_style_id: str,
    asr_poll_timeout: int,
    render_poll_timeout: int,
    summary: dict[str, Any],
) -> list[str]:
    """Step 4：ASR 链路（chain-race 兜底） + 字幕渲染（asr_paraformer_v2）。

    功能：覆盖源脚本 Step 6-7：
        - 对每个视频，先等 chain-dispatched ASR；超时则手动 POST 兜底；
        - 并行轮询 ASR 拿 word_timestamps；
        - 5 个 shot 并行 POST /commerce/shot-subtitle-render；
        - 并行轮询渲染任务，拿 subtitle_track_file_id。

    Args:
        client: httpx AsyncClient 实例。
        base_url: 后端 base URL。
        shot_ids: shot ID 列表（与 video_file_ids 一一对应）。
        video_file_ids: 5 个视频 file_id。
        subtitle_style_id: 字幕风格 ID。
        asr_poll_timeout: ASR 单任务轮询超时。
        render_poll_timeout: 渲染单任务轮询超时。
        summary: 全局 summary dict（写入 asr_*/subtitle_*）。

    Returns:
        list[str]：5 个字幕轨 file_id。
    """
    print("--- waiting/discovering chain-dispatched ASR (with fallback) ---")
    asr_task_ids: list[str] = []
    fallback_count = 0
    for vfid in video_file_ids:
        tid, used_fallback = await ensure_asr_for_video(client, vfid, base_url=base_url)
        if used_fallback:
            fallback_count += 1
        asr_task_ids.append(tid)
    summary["asr_task_ids"] = asr_task_ids
    summary["asr_fallback_count"] = fallback_count

    print(f"--- polling {len(asr_task_ids)} ASR ---")
    asr_results = await asyncio.gather(
        *[
            poll_task_resilient(client, tid, base_url=base_url, timeout_s=asr_poll_timeout)
            for tid in asr_task_ids
        ]
    )
    summary["asr_word_counts"] = [len(r.get("word_timestamps") or []) for r in asr_results]
    print(f"  {len(asr_results)} ASR done: word counts = {summary['asr_word_counts']}")

    print(f"--- rendering {len(shot_ids)} subtitles (asr_paraformer_v2) ---")
    render_task_resps = await asyncio.gather(
        *[
            call(
                client,
                "POST",
                "/commerce/shot-subtitle-render",
                base_url=base_url,
                json={
                    "shot_id": shot_ids[i],
                    "style_id": subtitle_style_id,
                    "word_timestamps": asr_results[i].get("word_timestamps") or [],
                    "language_code": "zh-CN",
                    "source": "asr_paraformer_v2",
                },
            )
            for i in range(len(shot_ids))
        ]
    )
    render_task_ids = [r["data"]["task_id"] for r in render_task_resps]
    summary["subtitle_task_ids"] = render_task_ids
    render_results = await asyncio.gather(
        *[
            poll_task_resilient(client, tid, base_url=base_url, timeout_s=render_poll_timeout)
            for tid in render_task_ids
        ]
    )
    subtitle_file_ids: list[str] = []
    for r in render_results:
        fid = r.get("file_id")
        if not fid:
            raise RuntimeError(f"subtitle render task missing file_id: {r}")
        subtitle_file_ids.append(fid)
    summary["subtitle_file_ids"] = subtitle_file_ids
    print(
        f"  {len(subtitle_file_ids)} subtitles rendered: "
        f"{[f[:8] for f in subtitle_file_ids]}"
    )
    return subtitle_file_ids


async def assemble_chapter(
    client: Any,
    *,
    base_url: str,
    chapter_id: str,
    shot_ids: list[str],
    subtitle_file_ids: list[str],
    export_poll_timeout: int,
    summary: dict[str, Any],
) -> str:
    """Step 5：写 chapter timeline + chapter_av_export + 拿公网 URL。

    功能：覆盖源脚本 Step 8-10：
        - PUT /studio/chapters/{id}/timeline 写 5 个 segment（仅含 subtitle_track_file_id，
          不带 tts_audio，符合 keep_native 语义）；
        - POST /commerce/chapter-av-export 触发合成；
        - 轮询导出任务，拿 final mp4 file_id；
        - GET /studio/files/{id} 取 thumbnail/url/public_url。

    Args:
        client: httpx AsyncClient 实例。
        base_url: 后端 base URL。
        chapter_id: 章节 ID。
        shot_ids: shot ID 列表。
        subtitle_file_ids: 字幕轨 file_id 列表（与 shot_ids 一一对应）。
        export_poll_timeout: chapter_av_export 任务轮询超时。
        summary: 全局 summary dict（写入 av_export_task_id / final_file_id / public_url）。

    Returns:
        str：最终 mp4 的公网 URL（thumbnail / url / public_url 优先级取第一个非空）。
    """
    print("--- writing chapter timeline (subtitle_track_file_id only, NO tts_audio) ---")
    segments = [
        {"shot_id": shot_ids[i], "subtitle_track_file_id": subtitle_file_ids[i]}
        for i in range(len(shot_ids))
    ]
    await call(
        client,
        "PUT",
        f"/studio/chapters/{chapter_id}/timeline",
        base_url=base_url,
        json={"segments": segments},
    )
    print(f"  timeline persisted: {len(segments)} segments")

    print("--- triggering chapter_av_export (keep_native auto-detect) ---")
    export_resp = (
        await call(
            client,
            "POST",
            "/commerce/chapter-av-export",
            base_url=base_url,
            json={"chapter_id": chapter_id, "aspect": "9:16"},
        )
    ).get("data", {})
    export_task_id = export_resp["task_id"]
    summary["av_export_task_id"] = export_task_id
    export_result = await poll_task_resilient(
        client, export_task_id, base_url=base_url, timeout_s=export_poll_timeout
    )
    final_file_id = export_result.get("file_id")
    summary["final_file_id"] = final_file_id
    print(f"  final mp4 file_id: {final_file_id}")

    file_info = (
        await call(client, "GET", f"/studio/files/{final_file_id}", base_url=base_url)
    ).get("data", {})
    public_url = (
        file_info.get("thumbnail")
        or file_info.get("url")
        or file_info.get("public_url")
        or ""
    )
    summary["public_url"] = public_url
    summary["file_meta"] = {
        "size": file_info.get("size"),
        "mime": file_info.get("mime"),
        "duration_ms": file_info.get("duration_ms"),
    }
    print(f"  public URL: {public_url}")
    return public_url


# ---------------------------------------------------------------------------
# main：dry-run / production 路径分流。
# ---------------------------------------------------------------------------


def _print_dry_run_plan(args: argparse.Namespace, *, project_id: str, chapter_id: str, shot_ids: list[str]) -> None:
    """打印 dry-run 计划：5 段管线 + 关键参数 + 即将调用的 API 端点。

    Args:
        args: 解析后的 CLI namespace。
        project_id: 即将使用的 project ID（已派生）。
        chapter_id: 即将使用的 chapter ID。
        shot_ids: 即将使用的 shot ID 列表。

    关键内部逻辑：
        所有 print 必须显式打出 "DRY-RUN" 前缀和 "Step 1..5" 字样，
        让 CI 与运维一眼看出脚本在 dry-run 路径，且未漏一段。
    """
    print("=== DRY-RUN: p3_e2e_smoke pipeline plan ===")
    print(f"  base_url           = {args.base_url}")
    print(f"  product_id         = {args.product_id}")
    print(f"  project_id         = {project_id}")
    print(f"  chapter_id         = {chapter_id}")
    print(f"  shot_ids           = {shot_ids}")
    print(f"  audio_strategy     = {args.audio_strategy}")
    print(f"  subtitle_style_id  = {args.subtitle_style_id}")
    print(f"  shot_count         = {args.shot_count}")
    print(f"  video_poll_timeout = {args.video_poll_timeout}s")
    print(f"  asr_poll_timeout   = {args.asr_poll_timeout}s")
    print(f"  render_poll_timeout= {args.render_poll_timeout}s")
    print(f"  export_poll_timeout= {args.export_poll_timeout}s")
    print(f"  summary_path       = {args.summary_path}")
    print()
    print("  Step 1 prepare_project          → GET products / POST story-projects /")
    print("                                     POST chapters / POST project-product link")
    print("  Step 2 model_shots               → POST shots × N / shot-details × N /")
    print("                                     shot-dialog-lines × N (audio_strategy="
          f"{args.audio_strategy})")
    print("  Step 3 generate_videos           → POST /film/tasks/video × N (multi_ref, 1.5s stagger)")
    print("                                     + parallel poll (timeout="
          f"{args.video_poll_timeout}s)")
    print("  Step 4 asr_and_render_subtitles  → chain-race ASR (90s fallback)")
    print("                                     + POST /commerce/shot-subtitle-render × N")
    print("  Step 5 assemble_chapter          → PUT chapter timeline / POST")
    print("                                     /commerce/chapter-av-export (9:16) /")
    print("                                     GET /studio/files/{id}")
    print()
    print("DRY-RUN: no HTTP requests will be made; exit code 0.")


async def main(argv: list[str] | None = None) -> int:
    """脚本主入口：解析参数 → 校验 → dry-run 或 production 路径。

    Args:
        argv: 可选参数列表，缺省走 ``sys.argv[1:]``；用于单元测试。

    Returns:
        int：退出码。``0`` 成功，``1`` 管线失败，``2`` 参数校验/配置缺失。

    关键内部逻辑：
        - dry-run 路径**绝不**创建 ``httpx.AsyncClient``，仅打印计划；
        - production 路径将派生时间戳后缀作为 project/chapter/shot ID，
          确保多次运行不会冲突；
        - summary 始终写盘（dry-run 也会写），方便 CI 抓取产物。
    """
    parser = build_argparser()
    args = parser.parse_args(argv)

    # 必填参数校验：缺 product-id 直接退出 2（不走 argparse required，因为
    # 那会直接退出 2 但没有友好中文提示）。
    if not args.product_id:
        print(
            "错误：缺少必填参数 --product-id（或环境变量 JELLYFISH_PRODUCT_ID）。",
            file=sys.stderr,
        )
        return 2

    if args.shot_count <= 0:
        print(f"错误：--shot-count 必须为正整数，实际 {args.shot_count}", file=sys.stderr)
        return 2

    # 派生唯一 ID（基于时间戳），让脚本 idempotent：重跑时不会撞库。
    timestamp = int(time.time())
    project_id = f"{args.project_id_prefix}-{timestamp}"
    chapter_id = f"{args.chapter_id_prefix}-{timestamp}"
    actual_shot_count = min(args.shot_count, len(SHOTS_PLAN))
    shot_ids = [f"{args.shot_id_prefix}-{timestamp}-{i}" for i in range(actual_shot_count)]

    summary: dict[str, Any] = {
        "started_at": time.strftime("%Y-%m-%dT%H:%M:%S"),
        "mode": "dry-run" if args.dry_run else "production",
        "base_url": args.base_url,
        "product_id": args.product_id,
        "project_id": project_id,
        "chapter_id": chapter_id,
        "shot_ids": shot_ids,
        "audio_strategy": args.audio_strategy,
        "subtitle_style_id": args.subtitle_style_id,
    }

    if args.dry_run:
        _print_dry_run_plan(args, project_id=project_id, chapter_id=chapter_id, shot_ids=shot_ids)
        # dry-run 也写盘，方便 CI 抓取；但用 try 容忍权限错误（CI 可能受限）。
        try:
            Path(args.summary_path).parent.mkdir(parents=True, exist_ok=True)
            Path(args.summary_path).write_text(
                json.dumps(summary, ensure_ascii=False, indent=2)
            )
            print(f"DRY-RUN summary written: {args.summary_path}")
        except OSError as exc:
            print(f"DRY-RUN summary write skipped ({type(exc).__name__}: {exc})")
        return 0

    # production 路径：开始真跑。
    started_at = time.time()
    print(f"=== p3_e2e_smoke (production) START at {time.strftime('%H:%M:%S')} ===")
    print(f"  project_id={project_id} chapter_id={chapter_id} shots={len(shot_ids)}")

    import httpx  # 局部 import：让 dry-run 路径无 httpx 也可运行（极端 CI 场景）

    try:
        async with httpx.AsyncClient(timeout=httpx.Timeout(60.0)) as client:
            await prepare_project(
                client,
                base_url=args.base_url,
                project_id=project_id,
                chapter_id=chapter_id,
                product_id=args.product_id,
            )
            await model_shots(
                client,
                base_url=args.base_url,
                chapter_id=chapter_id,
                shot_ids=shot_ids,
                audio_strategy=args.audio_strategy,
            )
            video_file_ids = await generate_videos(
                client,
                base_url=args.base_url,
                shot_ids=shot_ids,
                video_poll_timeout=args.video_poll_timeout,
                summary=summary,
            )
            subtitle_file_ids = await asr_and_render_subtitles(
                client,
                base_url=args.base_url,
                shot_ids=shot_ids,
                video_file_ids=video_file_ids,
                subtitle_style_id=args.subtitle_style_id,
                asr_poll_timeout=args.asr_poll_timeout,
                render_poll_timeout=args.render_poll_timeout,
                summary=summary,
            )
            public_url = await assemble_chapter(
                client,
                base_url=args.base_url,
                chapter_id=chapter_id,
                shot_ids=shot_ids,
                subtitle_file_ids=subtitle_file_ids,
                export_poll_timeout=args.export_poll_timeout,
                summary=summary,
            )
    except (httpx.HTTPError, RuntimeError, TimeoutError) as exc:
        # 1 = 管线运行失败（HTTP / 任务 failed / 超时）。
        summary["error"] = f"{type(exc).__name__}: {exc}"
        summary["elapsed_s"] = round(time.time() - started_at, 1)
        try:
            Path(args.summary_path).parent.mkdir(parents=True, exist_ok=True)
            Path(args.summary_path).write_text(
                json.dumps(summary, ensure_ascii=False, indent=2)
            )
        except OSError:
            pass
        print(f"FATAL: {type(exc).__name__}: {exc}", file=sys.stderr)
        return 1

    summary["elapsed_s"] = round(time.time() - started_at, 1)
    Path(args.summary_path).parent.mkdir(parents=True, exist_ok=True)
    Path(args.summary_path).write_text(json.dumps(summary, ensure_ascii=False, indent=2))
    print(f"=== p3_e2e_smoke DONE in {summary['elapsed_s']}s ===")
    print(f"SUMMARY: {args.summary_path}")
    print(f"PUBLIC URL: {public_url}")
    return 0


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
