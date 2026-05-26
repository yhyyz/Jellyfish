"""0011 - W19 章节级 AV 合成（chapter_av_export）配套迁移。

为 P3 W19 跨路径合成 worker 引入 3 个新 FK 列：

- ``shots.dubbed_video_file_id``：章节合成输出的"配音 + 字幕成片" FileItem
  指针（``FileUsageKind.chapter_master_dubbed``）。同一镜头可重复合成；
  老 ``shots.generated_video_file_id`` 仍指向 r2v / t2v / i2v 的"裸视频"
  原始产物，两者并存。
- ``chapter_timeline_segments.subtitle_track_file_id``：本段渲染好的 ``.ass``
  字幕文件 FileItem（W18 ``shot_subtitle_render_worker`` 产出），合成阶段
  用 ffmpeg ``subtitles=`` 滤镜硬烧。
- ``chapter_timeline_segments.tts_audio_file_id``：本段 TTS 合成音频
  FileItem 指针，``audio_strategy=silent_with_tts`` 时由 ffmpeg ``amix``
  混入；``keep_native`` 时此列为 NULL。

设计要点：

- 3 个 FK 列均使用 ``ON DELETE SET NULL``：上游资源被删除时不应级联清空
  业务行（与 0009 的 5 个 FK 列设计一致）。
- 索引仅覆盖 FK 列，便于按 file_id 反查所属 shot / segment。
- 复用 0009 的 batch_alter_table + 显式 FK name 模式（SQLite-safe）。

Revision ID: 0011
Revises: 0010
Create Date: 2026-05-26
"""

# pylint: disable=invalid-name,no-member

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op


revision: str = "0011"
down_revision: Union[str, Sequence[str], None] = "0010"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """给 shots / chapter_timeline_segments 各加 FK 列 + 索引。"""
    # === shots.dubbed_video_file_id =======================================
    with op.batch_alter_table("shots") as batch:
        batch.add_column(
            sa.Column(
                "dubbed_video_file_id",
                sa.String(length=64),
                sa.ForeignKey(
                    "files.id",
                    name="fk_shots_dubbed_video_file_id",
                    ondelete="SET NULL",
                ),
                nullable=True,
                comment=(
                    "章节合成（chapter_av_export）输出的成片 FileItem ID；"
                    "与 generated_video_file_id 共存，前者指向裸视频，本字段"
                    "指向带字幕带配音的最终成片"
                ),
            ),
        )
    op.create_index(
        "ix_shots_dubbed_video_file_id", "shots", ["dubbed_video_file_id"]
    )

    # === chapter_timeline_segments: 2 个 FK 列 ============================
    with op.batch_alter_table("chapter_timeline_segments") as batch:
        batch.add_column(
            sa.Column(
                "subtitle_track_file_id",
                sa.String(length=64),
                sa.ForeignKey(
                    "files.id",
                    name="fk_chapter_timeline_segments_subtitle_track_file_id",
                    ondelete="SET NULL",
                ),
                nullable=True,
                comment=(
                    "本段渲染好的 .ass 字幕 FileItem（W18 shot_subtitle_render"
                    "_worker 产出），合成阶段用 ffmpeg subtitles= 滤镜硬烧"
                ),
            ),
        )
        batch.add_column(
            sa.Column(
                "tts_audio_file_id",
                sa.String(length=64),
                sa.ForeignKey(
                    "files.id",
                    name="fk_chapter_timeline_segments_tts_audio_file_id",
                    ondelete="SET NULL",
                ),
                nullable=True,
                comment=(
                    "本段 TTS 合成音频 FileItem；audio_strategy=silent_with_tts "
                    "时合成阶段 amix 混入，keep_native 时为 NULL"
                ),
            ),
        )
    op.create_index(
        "ix_chapter_timeline_segments_subtitle_track_file_id",
        "chapter_timeline_segments",
        ["subtitle_track_file_id"],
    )
    op.create_index(
        "ix_chapter_timeline_segments_tts_audio_file_id",
        "chapter_timeline_segments",
        ["tts_audio_file_id"],
    )


def downgrade() -> None:
    """反向：先 drop 索引 → 再 batch.drop_column（与 0009 模式一致）。"""
    op.drop_index(
        "ix_chapter_timeline_segments_tts_audio_file_id",
        table_name="chapter_timeline_segments",
    )
    op.drop_index(
        "ix_chapter_timeline_segments_subtitle_track_file_id",
        table_name="chapter_timeline_segments",
    )
    with op.batch_alter_table("chapter_timeline_segments") as batch:
        batch.drop_column("tts_audio_file_id")
        batch.drop_column("subtitle_track_file_id")

    op.drop_index("ix_shots_dubbed_video_file_id", table_name="shots")
    with op.batch_alter_table("shots") as batch:
        batch.drop_column("dubbed_video_file_id")
