"""W21-T1: ``backend/scripts/p3_e2e_smoke.py`` 离线 TDD 闸门测试。

本测试文件只验证 ``--help`` / ``--dry-run`` / ``import`` 三类离线场景，
**绝不**触发真实 HTTP 请求或真实 worker 流程：

1. ``test_help_exits_zero``
   - 子进程执行 ``python scripts/p3_e2e_smoke.py --help``，退出码必须是 0。
   - stdout 必须包含 argparse 标准的 ``usage:`` 字样和 ``--product-id`` 参数。
2. ``test_dry_run_without_product_id_exits_2``
   - 缺少必填 ``--product-id`` 时，``--dry-run`` 必须以 2 退出（配置缺失）。
   - stderr 中必须出现 ``product-id`` 关键字，方便运维定位错误。
3. ``test_dry_run_with_product_id_exits_zero``
   - 给齐 ``--dry-run --product-id <id>`` 时退出码 0，stdout 含管线计划标记。
   - 通过 ``PYTEST_DISABLE_HTTP=1`` 环境变量从外部强制约束：脚本在 dry-run
     路径上不允许新建 ``httpx.AsyncClient`` 也不允许真正发请求。
4. ``test_module_imports_clean``
   - 直接 ``importlib.import_module("scripts.p3_e2e_smoke")`` 不抛异常，
     验证 ``sys.path`` 注入与依赖解析在 ``backend`` 目录下完整。

为什么用 subprocess 而不是 asyncio 直接 ``await main()``：
    脚本本身的"运维入口"语义就是子进程；用 subprocess 才能验证
    ``sys.exit(0/1/2)`` 的退出码契约，与 CI / 运维实际调用方式一致。
"""

# pylint: disable=invalid-name

from __future__ import annotations

import importlib
import os
import subprocess
import sys
from pathlib import Path

import pytest

# ---------------------------------------------------------------------------
# 路径常量：测试既可能从仓库根目录运行（pytest backend/tests），也可能从
# backend 目录运行（cd backend && pytest）。统一通过 ``backend/scripts``
# 的绝对路径定位，避免相对路径在不同 cwd 下解析不同。
# ---------------------------------------------------------------------------
_BACKEND_ROOT = Path(__file__).resolve().parent.parent
_SCRIPT_PATH = _BACKEND_ROOT / "scripts" / "p3_e2e_smoke.py"


def _run_script(*args: str, env_overrides: dict[str, str] | None = None) -> subprocess.CompletedProcess[str]:
    """在子进程中执行 p3_e2e_smoke.py 并捕获 stdout/stderr。

    Args:
        args: 透传给脚本的 CLI 参数（例如 ``"--help"`` / ``"--dry-run"``）。
        env_overrides: 注入子进程的环境变量增量；默认会强制
            ``PYTEST_DISABLE_HTTP=1`` 来在 dry-run 路径双重约束"零网络"。

    Returns:
        subprocess.CompletedProcess：可读 returncode/stdout/stderr。

    Notes:
        ``cwd`` 固定为 ``backend/``，让脚本顶部 ``sys.path.insert(_BACKEND_ROOT)``
        与 ``app.*`` 解析路径与运维脚本调用语义保持一致。
    """
    base_env = dict(os.environ)
    base_env.setdefault("PYTEST_DISABLE_HTTP", "1")
    if env_overrides:
        base_env.update(env_overrides)
    return subprocess.run(
        [sys.executable, str(_SCRIPT_PATH), *args],
        cwd=str(_BACKEND_ROOT),
        env=base_env,
        capture_output=True,
        text=True,
        check=False,
        timeout=30,
    )


def test_help_exits_zero() -> None:
    """``--help`` 必须退出 0 并打印 argparse 标准 usage。"""
    result = _run_script("--help")
    assert result.returncode == 0, (
        f"--help 应退出 0，实际 {result.returncode}\n"
        f"stdout={result.stdout}\nstderr={result.stderr}"
    )
    # argparse 自动渲染的 usage 行必有 "usage:" 关键字。
    assert "usage:" in result.stdout.lower(), (
        f"--help 输出缺少 usage 行：{result.stdout!r}"
    )
    # 必填参数必须出现在 help 文本中，避免运维误以为参数被废弃。
    assert "--product-id" in result.stdout, (
        f"--help 输出缺少 --product-id 参数说明：{result.stdout!r}"
    )


def test_dry_run_without_product_id_exits_2() -> None:
    """缺 ``--product-id`` 时 ``--dry-run`` 必须以 2 退出（参数校验失败）。"""
    result = _run_script("--dry-run")
    assert result.returncode == 2, (
        f"缺 --product-id 应退出 2（参数校验失败），实际 {result.returncode}\n"
        f"stdout={result.stdout}\nstderr={result.stderr}"
    )
    # 错误信息必须能让运维定位"是 product-id 缺了"。
    combined = (result.stderr or "") + (result.stdout or "")
    assert "product-id" in combined.lower() or "product_id" in combined.lower(), (
        f"错误信息缺少 product-id 关键字：stderr={result.stderr!r} stdout={result.stdout!r}"
    )


def test_dry_run_with_product_id_exits_zero() -> None:
    """``--dry-run --product-id <id>`` 必须退出 0 且打印 5 段管线计划。"""
    result = _run_script("--dry-run", "--product-id", "test-prod")
    assert result.returncode == 0, (
        f"--dry-run --product-id 应退出 0，实际 {result.returncode}\n"
        f"stdout={result.stdout}\nstderr={result.stderr}"
    )
    # dry-run 必须显式声明自己处于 dry-run 状态，并枚举 5 段管线计划。
    out = result.stdout
    assert "DRY-RUN" in out.upper() or "DRY RUN" in out.upper(), (
        f"dry-run stdout 缺少 DRY-RUN 标记：{out!r}"
    )
    # 5 段管线必须以 "Step 1" ~ "Step 5" 形式出现，让运维一眼看到管线骨架。
    for marker in ("Step 1", "Step 2", "Step 3", "Step 4", "Step 5"):
        assert marker in out, (
            f"dry-run stdout 缺少管线计划标记 {marker!r}：{out!r}"
        )


def test_module_imports_clean() -> None:
    """``importlib.import_module('scripts.p3_e2e_smoke')`` 不应抛异常。

    用途：捕获顶层 import 错误（例如缺依赖、循环 import、sys.path 错位）。
    要求脚本在 import 时不能产生副作用（不能直接发 HTTP / 启动事件循环）。
    """
    # 让 ``scripts`` 包能被 import：把 backend/ 加进 sys.path。
    backend_root_str = str(_BACKEND_ROOT)
    if backend_root_str not in sys.path:
        sys.path.insert(0, backend_root_str)

    # 强制走 import_module 而不是 from-import，确保命中模块 cache 路径。
    try:
        module = importlib.import_module("scripts.p3_e2e_smoke")
    except Exception as exc:  # noqa: BLE001  # pylint: disable=broad-exception-caught
        pytest.fail(f"import scripts.p3_e2e_smoke 失败: {type(exc).__name__}: {exc}")

    # 关键符号必须存在，作为接口契约的早期断言（GREEN 阶段会落地）。
    assert hasattr(module, "main"), "scripts.p3_e2e_smoke 必须暴露 main()"
    assert hasattr(module, "build_argparser") or hasattr(module, "_build_argparser"), (
        "scripts.p3_e2e_smoke 必须暴露 (build|_build)_argparser"
    )
