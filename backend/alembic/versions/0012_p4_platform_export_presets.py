"""0012 - 创建 platform_export_presets 表（W23-T1，P4 Wave A 多平台导出预设）。

为 P4 Wave A 引入：

- ``platform_export_presets``：跨项目复用的"平台导出预设"配置表，集中
  承载抖音 / 快手 / 小红书 / YouTube Shorts / TikTok 5 套系统预设的
  画幅、时长、字幕、配音、水印、贴纸、编码、响度参数。系统级预设由启动期
  ``bootstrap_export_presets`` 幂等 seed（``is_system=True``），用户也可
  在此基础上派生 ``is_system=False`` 的自定义预设。

设计要点：

- 3 个 FK 列均使用 ``ON DELETE SET NULL``：上游字幕样式 / 音色包 / 水印
  文件被删除时不应级联清空预设行（保留预设 metadata 便于排障）；与 0009
  / 0010 / 0011 的 FK 设计保持一致。
- ``platform`` 列存 :class:`Platform` 枚举的 ``str`` 值（VARCHAR(32)），
  与 0010 ``subtitle_styles.format`` / 0009 ``voice_packs.provider`` 风格
  一致。
- ``sticker_specs`` 用 JSON 列承载 ``[{type, position, asset_id}, ...]``
  可变结构；W23-T1 不约束 schema，留给 W23-T2 渲染管线消费。
- 复合索引 ``ix_platform_export_presets_platform_aspect`` 覆盖前端按平台 +
  画幅检索的快路径。

Revision ID: 0012
Revises: 0011
Create Date: 2026-05-28
"""

# pylint: disable=invalid-name,no-member

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op


revision: str = "0012"
down_revision: Union[str, Sequence[str], None] = "0011"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """创建 platform_export_presets 表 + 关联索引。"""
    op.create_table(
        "platform_export_presets",
        sa.Column(
            "id",
            sa.String(length=64),
            primary_key=True,
            comment="预设 ID（如 douyin_default / tiktok_default）",
        ),
        sa.Column(
            "name",
            sa.String(length=255),
            nullable=False,
            comment="展示名称（如 抖音默认 / TikTok 默认）",
        ),
        sa.Column(
            "platform",
            sa.String(length=32),
            nullable=False,
            comment="目标投放平台（douyin / kuaishou / xiaohongshu / youtube / tiktok）",
        ),
        sa.Column(
            "aspect_ratio",
            sa.String(length=8),
            nullable=False,
            server_default="9:16",
            comment="画幅比例（9:16 / 1:1 / 16:9）",
        ),
        sa.Column(
            "max_duration_sec",
            sa.Integer(),
            nullable=False,
            server_default="60",
            comment="平台允许的最大单条时长（秒）",
        ),
        sa.Column(
            "subtitle_style_id",
            sa.String(length=64),
            sa.ForeignKey(
                "subtitle_styles.id",
                name="fk_platform_export_presets_subtitle_style_id",
                ondelete="SET NULL",
            ),
            nullable=True,
            comment="可选：默认字幕样式 ID",
        ),
        sa.Column(
            "voice_pack_id",
            sa.String(length=64),
            sa.ForeignKey(
                "voice_packs.id",
                name="fk_platform_export_presets_voice_pack_id",
                ondelete="SET NULL",
            ),
            nullable=True,
            comment="可选：默认音色包 ID",
        ),
        sa.Column(
            "watermark_file_id",
            sa.String(length=64),
            sa.ForeignKey(
                "files.id",
                name="fk_platform_export_presets_watermark_file_id",
                ondelete="SET NULL",
            ),
            nullable=True,
            comment="可选：水印 PNG/SVG 的 FileItem ID",
        ),
        sa.Column(
            "sticker_specs",
            sa.JSON(),
            nullable=False,
            comment="贴纸装配规则数组 [{type, position, asset_id}, ...]",
        ),
        sa.Column(
            "file_format",
            sa.String(length=16),
            nullable=False,
            server_default="mp4",
            comment="导出容器格式（mp4 / mov）",
        ),
        sa.Column(
            "codec_preset",
            sa.String(length=32),
            nullable=False,
            server_default="h264_high_4_1",
            comment="编码预设（h264_high_4_1 / hevc_main_10 等）",
        ),
        sa.Column(
            "loudness_lufs",
            sa.Float(),
            nullable=False,
            server_default="-16.0",
            comment="目标响度 LUFS",
        ),
        sa.Column(
            "is_system",
            sa.Boolean(),
            nullable=False,
            server_default="0",
            comment="系统级预设标记，true 时不可被业务层删除",
        ),
        sa.Column(
            "sort_order",
            sa.Integer(),
            nullable=False,
            server_default="0",
            comment="UI 列表排序权重",
        ),
        sa.Column(
            "description",
            sa.Text(),
            nullable=False,
            server_default="",
            comment="预设描述（运营备注）",
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
        comment=(
            "平台导出预设表（W23-T1：抖音/快手/小红书/YouTube Shorts/TikTok 5 套"
            "系统级预设 + 用户自定义）"
        ),
    )
    op.create_index(
        "ix_platform_export_presets_platform",
        "platform_export_presets",
        ["platform"],
    )
    op.create_index(
        "ix_platform_export_presets_subtitle_style_id",
        "platform_export_presets",
        ["subtitle_style_id"],
    )
    op.create_index(
        "ix_platform_export_presets_voice_pack_id",
        "platform_export_presets",
        ["voice_pack_id"],
    )
    op.create_index(
        "ix_platform_export_presets_watermark_file_id",
        "platform_export_presets",
        ["watermark_file_id"],
    )
    op.create_index(
        "ix_platform_export_presets_platform_aspect",
        "platform_export_presets",
        ["platform", "aspect_ratio"],
    )


def downgrade() -> None:
    """反向：先 drop 索引，再 drop 表。"""
    op.drop_index(
        "ix_platform_export_presets_platform_aspect",
        table_name="platform_export_presets",
    )
    op.drop_index(
        "ix_platform_export_presets_watermark_file_id",
        table_name="platform_export_presets",
    )
    op.drop_index(
        "ix_platform_export_presets_voice_pack_id",
        table_name="platform_export_presets",
    )
    op.drop_index(
        "ix_platform_export_presets_subtitle_style_id",
        table_name="platform_export_presets",
    )
    op.drop_index(
        "ix_platform_export_presets_platform",
        table_name="platform_export_presets",
    )
    op.drop_table("platform_export_presets")
