"""0020 - W31-T1 chapter_timeline_segments 加 BGM / SFX / ducking 三列。

P5 W31 把 ``AudioMixMode`` 从 W19 仅实装的 ``voice_only`` 扩到 ``voice_bgm``
与 ``full`` 两个真实路径，需要在 ``chapter_timeline_segments`` 表上落三列：

- ``bgm_file_id`` (``VARCHAR(64)``，nullable, FK ``files.id`` ON DELETE SET NULL)：
  本段背景音乐 ``FileItem`` ID（``FileUsageKind.bgm_track``）。``voice_bgm``
  与 ``full`` 模式合成阶段从该列拉 BGM 音轨；``voice_only`` 路径忽略。
- ``sfx_file_id`` (``VARCHAR(64)``，nullable, FK ``files.id`` ON DELETE SET NULL)：
  本段音效 ``FileItem`` ID（``FileUsageKind.sfx_track``）。仅 ``full``
  模式合成阶段通过 ``amerge`` 加入；其它模式忽略。
- ``bgm_ducking_db`` (``FLOAT NOT NULL DEFAULT -12.0``)：``full`` 模式
  ``sidechaincompress`` ducking 增益（dB），范围 ``[-30.0, 0.0]``。
  ``voice_bgm`` 用静态 ``amix weights="1 0.4"``，不读这一列。

为什么 FK 列用 ``String(64)`` 而非 ``BIGINT``：
    与 0011 P3 W19 的 ``subtitle_track_file_id`` / ``tts_audio_file_id``
    保持一致，``files.id`` 在本仓库里是 ``VARCHAR(64)`` 主键。

为什么 ``ON DELETE SET NULL``：
    BGM / SFX 文件被删除时不应把整段 segment 一起带走（与 W19
    ``subtitle_track_file_id`` 一致策略）。``voice_bgm`` / ``full`` 模式
    在 worker 侧读到 NULL 时会自动降级到无 BGM / 无 SFX 路径。

为什么 ``bgm_ducking_db`` 设默认值 ``-12.0``：
    podcast / voice-over 行业常用的 ducking 强度起点；
    ``sidechaincompress makeup`` 参数取负值表示衰减。

幂等保障：
    所有列均 nullable 或带 server_default；``upgrade`` 不需要 backfill，
    ``downgrade`` 直接 ``drop_column`` 即可。

Revision ID: 0020
Revises: 0019
Create Date: 2026-05-28
"""

# pylint: disable=invalid-name,no-member

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op


revision: str = "0020"
down_revision: Union[str, Sequence[str], None] = "0019"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """在 ``chapter_timeline_segments`` 上加 BGM / SFX / ducking 三列与同名索引。"""

    with op.batch_alter_table("chapter_timeline_segments") as batch:
        batch.add_column(
            sa.Column(
                "bgm_file_id",
                sa.String(length=64),
                sa.ForeignKey(
                    "files.id",
                    name="fk_chapter_timeline_segments_bgm_file_id",
                    ondelete="SET NULL",
                ),
                nullable=True,
                comment=(
                    "P5 W31：本段 BGM 音轨 FileItem（usage_kind=bgm_track），"
                    "voice_bgm / full 模式合成时混入；voice_only 忽略"
                ),
            ),
        )
        batch.add_column(
            sa.Column(
                "sfx_file_id",
                sa.String(length=64),
                sa.ForeignKey(
                    "files.id",
                    name="fk_chapter_timeline_segments_sfx_file_id",
                    ondelete="SET NULL",
                ),
                nullable=True,
                comment=(
                    "P5 W31：本段 SFX 音轨 FileItem（usage_kind=sfx_track），"
                    "仅 full 模式合成时通过 amerge 加入"
                ),
            ),
        )
        batch.add_column(
            sa.Column(
                "bgm_ducking_db",
                sa.Float(),
                nullable=False,
                server_default="-12.0",
                comment=(
                    "P5 W31：full 模式 sidechaincompress 自动 ducking 增益（dB），"
                    "范围 [-30.0, 0.0]，默认 -12.0；voice_bgm 用静态 weights "
                    "不读此列"
                ),
            ),
        )

    op.create_index(
        "ix_chapter_timeline_segments_bgm_file_id",
        "chapter_timeline_segments",
        ["bgm_file_id"],
        unique=False,
    )
    op.create_index(
        "ix_chapter_timeline_segments_sfx_file_id",
        "chapter_timeline_segments",
        ["sfx_file_id"],
        unique=False,
    )


def downgrade() -> None:
    """反向 drop 三列与索引。"""

    op.drop_index(
        "ix_chapter_timeline_segments_sfx_file_id",
        table_name="chapter_timeline_segments",
    )
    op.drop_index(
        "ix_chapter_timeline_segments_bgm_file_id",
        table_name="chapter_timeline_segments",
    )
    with op.batch_alter_table("chapter_timeline_segments") as batch:
        batch.drop_column("bgm_ducking_db")
        batch.drop_column("sfx_file_id")
        batch.drop_column("bgm_file_id")
