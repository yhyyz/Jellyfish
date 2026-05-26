"""0010 - 创建 subtitle_styles / subtitle_tracks 表（W18 T18-3 字幕引擎配套迁移）。

为 P3 W18 字幕引擎引入：

- ``subtitle_styles``：跨项目复用的 ASS Style 定义。系统级样式由启动期
  builtin_subtitle_styles 幂等 seed（DOUYIN_DEFAULT / TIKTOK_VIRAL /
  REELS_LOWER_THIRD），用户也可在项目层创建自定义样式。
- ``subtitle_tracks``：单镜头级别的字幕实例，关联具体 .ass / .srt / .vtt
  文件 FileItem 与所用 SubtitleStyle，记录字级时间戳来源
  （``source`` 字段对齐 W17 收尾的 audio_strategy 双路径产出）。

设计要点：

- ``subtitle_tracks.shot_id`` 使用 ``ON DELETE CASCADE``：镜头删除时字幕
  轨道随之清理，避免悬挂记录。
- ``subtitle_tracks.style_id`` / ``file_id`` 使用 ``ON DELETE SET NULL``：
  样式或源文件被删除时不应级联清空轨道行（保留 metadata 便于排障）。
- 索引覆盖 UI/查询所需字段：``ix_subtitle_styles_format_lang`` 用于按
  格式+语言筛选；``ix_subtitle_tracks_shot_lang`` 用于"取镜头某语言最新
  字幕"的快路径。
- 颜色字段统一存为 ``&HAABBGGRR`` 字符串（VARCHAR(16)），渲染时直接拼
  到 .ass 文件，避免二次格式转换。

Revision ID: 0010
Revises: 0009
Create Date: 2026-05-26
"""

# pylint: disable=invalid-name,no-member

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op


revision: str = "0010"
down_revision: Union[str, Sequence[str], None] = "0009"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """创建 subtitle_styles / subtitle_tracks 表 + 关联索引。"""
    # === subtitle_styles ===================================================
    op.create_table(
        "subtitle_styles",
        sa.Column(
            "id",
            sa.String(length=64),
            primary_key=True,
            comment="字幕样式 ID（如 douyin_default / tiktok_viral / reels_lower_third）",
        ),
        sa.Column(
            "name",
            sa.String(length=255),
            nullable=False,
            comment="展示名称",
        ),
        sa.Column(
            "description",
            sa.Text(),
            nullable=False,
            server_default="",
            comment="样式描述",
        ),
        sa.Column(
            "language_code",
            sa.String(length=16),
            nullable=False,
            server_default="zh-CN",
            comment="主语言代码",
        ),
        sa.Column(
            "format",
            sa.String(length=8),
            nullable=False,
            server_default="ass",
            comment="字幕文件格式：ass / srt / vtt",
        ),
        sa.Column(
            "font_family",
            sa.String(length=128),
            nullable=False,
            comment="主字体 family name",
        ),
        sa.Column(
            "font_fallback_chain",
            sa.JSON(),
            nullable=False,
            comment="字体回退链 list[str]",
        ),
        sa.Column(
            "font_size",
            sa.Integer(),
            nullable=False,
            comment="字号（脚本像素，按 PlayResY=1920 计）",
        ),
        sa.Column(
            "primary_colour",
            sa.String(length=16),
            nullable=False,
            server_default="&H00FFFFFF",
            comment="主填充色 &HAABBGGRR",
        ),
        sa.Column(
            "secondary_colour",
            sa.String(length=16),
            nullable=False,
            server_default="&H00FFFFFF",
            comment="预高亮色 &HAABBGGRR",
        ),
        sa.Column(
            "outline_colour",
            sa.String(length=16),
            nullable=False,
            server_default="&H00000000",
            comment="描边色 &HAABBGGRR",
        ),
        sa.Column(
            "back_colour",
            sa.String(length=16),
            nullable=False,
            server_default="&H80000000",
            comment="阴影色 &HAABBGGRR",
        ),
        sa.Column(
            "bold",
            sa.Boolean(),
            nullable=False,
            server_default="1",
            comment="是否粗体",
        ),
        sa.Column(
            "italic",
            sa.Boolean(),
            nullable=False,
            server_default="0",
            comment="是否斜体",
        ),
        sa.Column(
            "border_style",
            sa.Integer(),
            nullable=False,
            server_default="1",
            comment="ASS BorderStyle：1=描边+阴影 / 3=实心矩形盒",
        ),
        sa.Column(
            "outline",
            sa.Float(),
            nullable=False,
            server_default="3.0",
            comment="描边宽度（像素）",
        ),
        sa.Column(
            "shadow",
            sa.Float(),
            nullable=False,
            server_default="1.0",
            comment="阴影偏移（像素）",
        ),
        sa.Column(
            "alignment",
            sa.String(length=16),
            nullable=False,
            server_default="bottom_center",
            comment="ASS Alignment 语义化映射",
        ),
        sa.Column(
            "margin_l",
            sa.Integer(),
            nullable=False,
            server_default="60",
            comment="左边距（像素）",
        ),
        sa.Column(
            "margin_r",
            sa.Integer(),
            nullable=False,
            server_default="60",
            comment="右边距（像素）",
        ),
        sa.Column(
            "margin_v",
            sa.Integer(),
            nullable=False,
            server_default="200",
            comment="垂直边距（像素）",
        ),
        sa.Column(
            "play_res_x",
            sa.Integer(),
            nullable=False,
            server_default="1080",
            comment="ASS PlayResX",
        ),
        sa.Column(
            "play_res_y",
            sa.Integer(),
            nullable=False,
            server_default="1920",
            comment="ASS PlayResY",
        ),
        sa.Column(
            "is_system",
            sa.Boolean(),
            nullable=False,
            server_default="0",
            comment="系统级样式标记",
        ),
        sa.Column(
            "sort_order",
            sa.Integer(),
            nullable=False,
            server_default="0",
            comment="UI 列表显示顺序",
        ),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.func.now(),
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.func.now(),
        ),
        comment="字幕样式表（W18：DOUYIN_DEFAULT / TIKTOK_VIRAL / REELS_LOWER_THIRD 三套系统级 + 用户自定义）",
    )
    op.create_index(
        "ix_subtitle_styles_format_lang",
        "subtitle_styles",
        ["format", "language_code"],
    )
    op.create_index(
        "ix_subtitle_styles_language_code",
        "subtitle_styles",
        ["language_code"],
    )
    op.create_index(
        "ix_subtitle_styles_format",
        "subtitle_styles",
        ["format"],
    )

    # === subtitle_tracks ===================================================
    op.create_table(
        "subtitle_tracks",
        sa.Column(
            "id",
            sa.String(length=64),
            primary_key=True,
            comment="字幕轨道 ID（uuid4().hex）",
        ),
        sa.Column(
            "shot_id",
            sa.String(length=64),
            sa.ForeignKey(
                "shots.id",
                name="fk_subtitle_tracks_shot_id",
                ondelete="CASCADE",
            ),
            nullable=False,
            comment="所属镜头 ID",
        ),
        sa.Column(
            "style_id",
            sa.String(length=64),
            sa.ForeignKey(
                "subtitle_styles.id",
                name="fk_subtitle_tracks_style_id",
                ondelete="SET NULL",
            ),
            nullable=True,
            comment="使用的 SubtitleStyle ID",
        ),
        sa.Column(
            "file_id",
            sa.String(length=64),
            sa.ForeignKey(
                "files.id",
                name="fk_subtitle_tracks_file_id",
                ondelete="SET NULL",
            ),
            nullable=True,
            comment="渲染产物 FileItem ID",
        ),
        sa.Column(
            "language_code",
            sa.String(length=16),
            nullable=False,
            server_default="zh-CN",
            comment="字幕语言代码",
        ),
        sa.Column(
            "format",
            sa.String(length=8),
            nullable=False,
            server_default="ass",
            comment="字幕文件格式",
        ),
        sa.Column(
            "source",
            sa.String(length=32),
            nullable=False,
            server_default="tts_word_timestamps",
            comment="字级时间戳来源（与 W17 收尾 audio_strategy 双路径对齐）",
        ),
        sa.Column(
            "duration_ms",
            sa.Integer(),
            nullable=False,
            server_default="0",
            comment="字幕末尾时间戳（覆盖音频时长）",
        ),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.func.now(),
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.func.now(),
        ),
        comment="字幕轨道实例表（W18：单镜头级 .ass/.srt/.vtt 文件实例）",
    )
    op.create_index(
        "ix_subtitle_tracks_shot_id",
        "subtitle_tracks",
        ["shot_id"],
    )
    op.create_index(
        "ix_subtitle_tracks_style_id",
        "subtitle_tracks",
        ["style_id"],
    )
    op.create_index(
        "ix_subtitle_tracks_file_id",
        "subtitle_tracks",
        ["file_id"],
    )
    op.create_index(
        "ix_subtitle_tracks_language_code",
        "subtitle_tracks",
        ["language_code"],
    )
    op.create_index(
        "ix_subtitle_tracks_source",
        "subtitle_tracks",
        ["source"],
    )
    op.create_index(
        "ix_subtitle_tracks_shot_lang",
        "subtitle_tracks",
        ["shot_id", "language_code"],
    )


def downgrade() -> None:
    """反向：先 drop 子表 subtitle_tracks 再 drop 主表 subtitle_styles。"""
    op.drop_index("ix_subtitle_tracks_shot_lang", table_name="subtitle_tracks")
    op.drop_index("ix_subtitle_tracks_source", table_name="subtitle_tracks")
    op.drop_index("ix_subtitle_tracks_language_code", table_name="subtitle_tracks")
    op.drop_index("ix_subtitle_tracks_file_id", table_name="subtitle_tracks")
    op.drop_index("ix_subtitle_tracks_style_id", table_name="subtitle_tracks")
    op.drop_index("ix_subtitle_tracks_shot_id", table_name="subtitle_tracks")
    op.drop_table("subtitle_tracks")

    op.drop_index("ix_subtitle_styles_format", table_name="subtitle_styles")
    op.drop_index("ix_subtitle_styles_language_code", table_name="subtitle_styles")
    op.drop_index("ix_subtitle_styles_format_lang", table_name="subtitle_styles")
    op.drop_table("subtitle_styles")
