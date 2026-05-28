"""0018 - W29-T1 自定义音色训练字段扩展。

P5 W29 在 ``voice_packs`` 表上落 5 个新字段，把 P3 W17 仅有的"系统级
seed"音色目录扩成"系统级 + 用户自定义 voice clone"双栈：

- ``target_model`` (``VARCHAR(64)``，nullable)：DashScope CosyVoice
  voice clone 的目标合成模型（如 ``cosyvoice-v3.5-plus`` /
  ``cosyvoice-v3-plus``）。一旦写入即与 voice_id 绑死，跨模型升级 = 重新
  ``create_voice``；系统行（``is_system=TRUE``）此列可保持 ``NULL``。
- ``region`` (``VARCHAR(32)``，nullable)：DashScope 区域端点（北京
  ``cn-beijing`` / 新加坡 ``ap-singapore``）。同一 voice 在两区不通用，因此
  必须随 voice_id 一起持久化。
- ``clone_status`` (``VARCHAR(32)``，nullable)：voice clone 训练 / 服务状态
  ``deploying`` / ``ready`` / ``failed`` / ``deleted``，对应
  :class:`app.models.types.VoiceCloneStatus` 枚举。``upgrade`` 后需要 backfill
  历史 ``is_system=TRUE`` 行为 ``ready``，让既有读路径不再误判系统行尚未训练。
- ``sample_audio_oss_key`` (``VARCHAR(255)``，nullable)：用户上传的 voice
  sample 在 minio bucket 内的 object key；用于审计 + 后续二次训练（如
  日后允许"重新训练此 voice"）。
- ``cloned_at`` (``DATETIME(timezone=True)``，nullable)：克隆完成时间戳。
  仅 ``ready`` 状态有意义；``failed`` / ``deploying`` 行保留 ``NULL`` 以避
  免被误读为"已可用"。

为什么不复用 ``shots.consistency_status`` 那种 ``VARCHAR(16)``：
    voice clone 状态语义集合更大（含 ``deleted``），且未来还会扩展
    ``deprecated`` / ``quota_exceeded`` 等，留 ``32`` 字符余量。

幂等保障：
    所有列均 ``nullable=True``，不需要业务侧默认值；``upgrade`` 后用一条
    ``UPDATE`` 把历史 ``is_system=TRUE`` 行回填为 ``clone_status='ready'``，
    保证前端"系统音色直接可用"路径不被破坏；新建系统行（如 W29-T10
    seed_overseas_voice_packs）由调用方显式写 ``ready`` 状态。

Revision ID: 0018
Revises: 0017
Create Date: 2026-05-28
"""

# pylint: disable=invalid-name,no-member

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op


revision: str = "0018"
down_revision: Union[str, Sequence[str], None] = "0017"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """在 ``voice_packs`` 上加 5 列并 backfill 系统行 ``clone_status='ready'``。"""

    op.add_column(
        "voice_packs",
        sa.Column(
            "target_model",
            sa.String(length=64),
            nullable=True,
            comment=(
                "DashScope voice clone 目标合成模型（cosyvoice-v3.5-plus 等）；"
                "一旦写入即与 voice_id 绑死；系统行可为 NULL"
            ),
        ),
    )
    op.add_column(
        "voice_packs",
        sa.Column(
            "region",
            sa.String(length=32),
            nullable=True,
            comment=(
                "DashScope 区域端点：cn-beijing / ap-singapore；"
                "同一 voice 不能跨区使用，因此随 voice_id 一起持久化"
            ),
        ),
    )
    op.add_column(
        "voice_packs",
        sa.Column(
            "clone_status",
            sa.String(length=32),
            nullable=True,
            comment=(
                "voice clone 状态：deploying / ready / failed / deleted；"
                "系统行启动后 backfill 为 ready"
            ),
        ),
    )
    op.add_column(
        "voice_packs",
        sa.Column(
            "sample_audio_oss_key",
            sa.String(length=255),
            nullable=True,
            comment="用户上传 voice sample 在 minio bucket 内的 object key（仅自定义音色）",
        ),
    )
    op.add_column(
        "voice_packs",
        sa.Column(
            "cloned_at",
            sa.DateTime(timezone=True),
            nullable=True,
            comment="voice clone 完成时间戳；仅 ready 状态有意义",
        ),
    )

    # Backfill：历史 is_system=TRUE 行的 clone_status 一律置为 ready，
    # 避免读路径在 W29 上线后把系统音色误判为"未训练"。
    op.execute(
        sa.text(
            "UPDATE voice_packs SET clone_status='ready' WHERE is_system = true"
        )
    )


def downgrade() -> None:
    """反向 drop 5 列；不回退 backfill（被 drop 列后已无意义）。"""

    op.drop_column("voice_packs", "cloned_at")
    op.drop_column("voice_packs", "sample_audio_oss_key")
    op.drop_column("voice_packs", "clone_status")
    op.drop_column("voice_packs", "region")
    op.drop_column("voice_packs", "target_model")
