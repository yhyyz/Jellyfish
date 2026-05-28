"""0023 - W31-followup ChapterTimelineSegment 加 ``sfx_offset_ms`` 列。

P5 W31 落 BGM/SFX 拼装时，``chapter_av_export_filter._build_full_mix_chain``
已经接受 ``sfx_offset_ms`` 参数并把它喂给 ffmpeg ``adelay``，但
``chapter_av_export_task._build_specs_for_chapter`` 在构造
``SegmentFilterSpec`` 时把 ``sfx_offset_ms`` 写死成 0：

    SegmentFilterSpec(
        ...
        sfx_input_index=sfx_input_index,
        sfx_offset_ms=0,  # ← 写死，segment 永远从 0 起播 SFX
        bgm_ducking_db=float(seg.bgm_ducking_db),
    )

W31-followup #6 在 DB 层补一列 ``sfx_offset_ms INTEGER NOT NULL DEFAULT 0``
打通时间轴：

- 前端 AVPreviewPanel 在 SFX 选择器旁加 InputNumber/Slider 0..30000ms；
- ``PATCH /chapters/{cid}/timeline/segments/{sid}/audio`` 接受新字段；
- ``chapter_av_export_task`` 把 ``seg.sfx_offset_ms`` 透传到
  ``SegmentFilterSpec``，filter graph 真正用上。

为什么取值范围 [0, 30000]：
    - 下界 0：把 SFX 放在 segment 起点；不允许负值（adelay 要求非负）。
    - 上界 30000ms = 30s：单镜头时长上限的两倍以上，足够覆盖任何场景；
      过大值会让 SFX 落在 segment 之外被 ffmpeg ``atrim=duration`` 截掉，
      属于"安静失败"，前端 slider 限制在 30s 给用户更明确的预期。
    - DB 层只用 ``CHECK (0 <= sfx_offset_ms AND sfx_offset_ms <= 30000)``
      做硬兜底；service 层 Pydantic ``ge=0 le=30000`` 兜在前面，前端
      slider 本身又限制了输入。三层防护，挡住任何脏写入。

为什么 INTEGER 而非 FLOAT：
    SFX 触发精度按毫秒已经足够（人耳难辨 <10ms 偏差）；INTEGER 既省
    一字节又规避浮点舍入；与 alembic 0011 ``trim_start_ms`` /
    ``trim_end_ms`` 同一类型，便于复用 ``adelay={ms}|{ms}`` 拼接逻辑。

幂等保障：
    ``DEFAULT 0`` 让存量行升级后自动取 0（与原"写死 0"行为完全等价），
    无需 backfill；``downgrade`` 直接 ``drop_column`` 即可。

CHECK 约束在 SQLite 上落地，但部分 MySQL 8 版本默认不强制 CHECK；
依赖 Pydantic ``ge=0 le=30000`` 作 application 层硬约束。

Revision ID: 0023
Revises: 0022
Create Date: 2026-05-29
"""

# pylint: disable=invalid-name,no-member

from __future__ import annotations

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op


revision: str = "0023"
down_revision: Union[str, Sequence[str], None] = "0022"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """在 ``chapter_timeline_segments`` 上加 ``sfx_offset_ms`` 列。"""

    with op.batch_alter_table("chapter_timeline_segments") as batch:
        batch.add_column(
            sa.Column(
                "sfx_offset_ms",
                sa.Integer(),
                nullable=False,
                server_default="0",
                comment=(
                    "P5 W31-followup：SFX 在 segment 内的起始毫秒（0..30000），"
                    "传给 ffmpeg adelay；缺省 0 表示从 segment 起点播放"
                ),
            ),
        )


def downgrade() -> None:
    """反向 drop ``sfx_offset_ms`` 列。"""

    with op.batch_alter_table("chapter_timeline_segments") as batch:
        batch.drop_column("sfx_offset_ms")
