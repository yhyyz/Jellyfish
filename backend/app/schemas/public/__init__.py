"""``/api/v1/public/*`` 第三方公开接口共享 Pydantic schema。

本子包仅服务于走 per-key bcrypt + 配额扣减的公开通道（参见
:mod:`app.core.api_key_auth`）。所有响应都遵循 *最小表面* 原则：

- 不暴露 ``GenerationTask`` 的内部字段（``payload`` / ``executor_*`` /
  ``cancel_reason`` 等），避免给嗅探者留下指纹；
- 与内部 admin schema 物理隔离，便于将来对外契约独立演进而不冲击
  仓库内既有 ``app.schemas.commerce.*`` / ``app.schemas.task`` 的
  响应形态。
"""

from app.schemas.public.task_status import PublicTaskStatusRead

__all__ = ["PublicTaskStatusRead"]
