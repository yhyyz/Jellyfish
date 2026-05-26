"""0009 - 创建 voice_packs / tts_cache 表 + 关联 FK 列（W17 T17-3 配套迁移）。

为 P3 W17 TTS pipeline 引入：

- ``voice_packs``：跨镜头/项目复用的 TTS 音色定义。系统级音色由启动期
  builtin_voice_packs 幂等 seed（``is_system=True``），用户也可上传
  自定义 voice clone。
- ``tts_cache``（D15）：(text, voice_pack_id, speed) 三元组 sha256
  hash 缓存表，命中即复用既有 FileItem 音频，避免重复调用供应商。
- ``characters.voice_pack_id``：角色默认音色，``ShotDialogLine`` 解析
  时若未显式指定则回退到此值。
- ``story_variants.voice_pack_id`` / ``narration_voice_pack_id``：
  变体级音色（覆盖角色默认）+ 旁白音色（``line_mode=VOICE_OVER`` 时
  使用）。
- ``shot_dialog_lines.start_time_ms`` / ``end_time_ms``：对白在镜头时间线
  内的起始/结束毫秒，由 chapter_av_planner 写入；用于 TTS 音频时长上限。
- ``shot_dialog_lines.tts_voice_id``：本行强制使用的音色（覆盖角色默认）。
- ``shot_dialog_lines.tts_audio_file_id``：本行 TTS 合成结果音频
  FileItem ID（命中 tts_cache 时回填）。

设计要点：

- 5 个 FK 列均使用 ``ON DELETE SET NULL``：音色被删除时不应级联清空业务行。
- ``tts_cache.voice_pack_id`` / ``audio_file_id`` 使用 ``CASCADE``：缓存
  必须随依赖资源消失，避免悬挂记录。
- 索引仅覆盖 UI/查询所需字段（FK 列、provider+language 复合索引、
  cache_key 唯一索引），避免冗余写开销。

Revision ID: 0009
Revises: 0008
Create Date: 2026-05-26
"""

# pylint: disable=invalid-name,no-member

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op


revision: str = "0009"
down_revision: Union[str, Sequence[str], None] = "0008"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """创建 voice_packs / tts_cache 表，并在既有 3 张表上新增 5 个 FK 列。"""
    # === voice_packs ======================================================
    op.create_table(
        "voice_packs",
        sa.Column(
            "id",
            sa.String(length=64),
            primary_key=True,
            comment="音色包 ID（如 cosyvoice_v2_longxiaochun）",
        ),
        sa.Column(
            "name",
            sa.String(length=255),
            nullable=False,
            comment="展示名称（如 龙小淳）",
        ),
        sa.Column(
            "provider",
            sa.String(length=32),
            nullable=False,
            server_default="aliyun_cosyvoice",
            comment="TTS 供应商",
        ),
        sa.Column(
            "provider_voice_id",
            sa.String(length=128),
            nullable=False,
            comment="供应商侧音色 ID（如 longxiaochun_v2）",
        ),
        sa.Column(
            "language_code",
            sa.String(length=16),
            nullable=False,
            server_default="zh-CN",
            comment="语言代码（zh-CN / en-US / ja-JP 等）",
        ),
        sa.Column(
            "gender",
            sa.String(length=16),
            nullable=False,
            server_default="neutral",
            comment="声纹性别",
        ),
        sa.Column(
            "archetype_hint",
            sa.String(length=64),
            nullable=True,
            comment="可选：与 BrandArchetype / 角色原型的语义匹配提示",
        ),
        sa.Column(
            "sample_file_id",
            sa.String(length=64),
            sa.ForeignKey("files.id", ondelete="SET NULL"),
            nullable=True,
            comment="试听样本音频 file_id（自定义克隆音色为训练样本）",
        ),
        sa.Column(
            "description",
            sa.Text(),
            nullable=False,
            server_default="",
            comment="音色描述（适用场景、特质等）",
        ),
        sa.Column(
            "default_speed",
            sa.Float(),
            nullable=False,
            server_default="1.0",
            comment="默认语速（0.5-2.0），TTS 估时长用",
        ),
        sa.Column(
            "is_system",
            sa.Boolean(),
            nullable=False,
            server_default="0",
            comment="系统级音色标记，true 时不可被用户删除",
        ),
        sa.Column(
            "sort_order",
            sa.Integer(),
            nullable=False,
            server_default="0",
            comment="UI 列表显示顺序（升序）",
        ),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        comment="音色包：跨镜头/项目复用的 TTS 音色定义（W17 T17-3）",
    )
    op.create_index(
        "ix_voice_packs_provider", "voice_packs", ["provider"]
    )
    op.create_index(
        "ix_voice_packs_language_code", "voice_packs", ["language_code"]
    )
    op.create_index(
        "ix_voice_packs_sample_file_id", "voice_packs", ["sample_file_id"]
    )
    op.create_index(
        "ix_voice_packs_provider_lang",
        "voice_packs",
        ["provider", "language_code"],
    )

    # === tts_cache ========================================================
    op.create_table(
        "tts_cache",
        sa.Column(
            "id",
            sa.Integer(),
            primary_key=True,
            autoincrement=True,
            comment="自增主键",
        ),
        sa.Column(
            "cache_key",
            sa.String(length=64),
            nullable=False,
            comment="(text, voice_pack_id, speed) 的 sha256 hash",
        ),
        sa.Column(
            "voice_pack_id",
            sa.String(length=64),
            sa.ForeignKey("voice_packs.id", ondelete="CASCADE"),
            nullable=False,
            comment="所用音色包",
        ),
        sa.Column(
            "text_preview",
            sa.String(length=255),
            nullable=False,
            server_default="",
            comment="原文前 255 字符（仅供调试，hash 才是命中依据）",
        ),
        sa.Column(
            "speed",
            sa.Float(),
            nullable=False,
            server_default="1.0",
            comment="合成时的语速参数",
        ),
        sa.Column(
            "audio_file_id",
            sa.String(length=64),
            sa.ForeignKey("files.id", ondelete="CASCADE"),
            nullable=False,
            comment="合成结果音频 FileItem ID",
        ),
        sa.Column(
            "duration_ms",
            sa.Integer(),
            nullable=False,
            server_default="0",
            comment="音频时长毫秒（合成时回写）",
        ),
        sa.Column(
            "word_timestamps",
            sa.JSON(),
            nullable=False,
            comment="字级时间戳 [{text, begin_ms, end_ms}]",
        ),
        sa.Column(
            "hit_count",
            sa.Integer(),
            nullable=False,
            server_default="0",
            comment="累计命中次数（运营 metrics）",
        ),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        comment="TTS 输出 hash 缓存（D15）：避免相同三元组重复合成",
    )
    op.create_index(
        "ix_tts_cache_cache_key", "tts_cache", ["cache_key"], unique=True
    )
    op.create_index(
        "ix_tts_cache_voice_pack_id", "tts_cache", ["voice_pack_id"]
    )
    op.create_index(
        "ix_tts_cache_audio_file_id", "tts_cache", ["audio_file_id"]
    )

    # === characters.voice_pack_id =========================================
    with op.batch_alter_table("characters") as batch:
        batch.add_column(
            sa.Column(
                "voice_pack_id",
                sa.String(length=64),
                sa.ForeignKey(
                    "voice_packs.id",
                    name="fk_characters_voice_pack_id",
                    ondelete="SET NULL",
                ),
                nullable=True,
                comment="角色默认音色（T17）。ShotDialogLine.tts_voice_id "
                "为空时落到此值",
            ),
        )
    op.create_index(
        "ix_characters_voice_pack_id", "characters", ["voice_pack_id"]
    )

    # === story_variants.voice_pack_id / narration_voice_pack_id ===========
    with op.batch_alter_table("story_variants") as batch:
        batch.add_column(
            sa.Column(
                "voice_pack_id",
                sa.String(length=64),
                sa.ForeignKey(
                    "voice_packs.id",
                    name="fk_story_variants_voice_pack_id",
                    ondelete="SET NULL",
                ),
                nullable=True,
                comment="变体级主角默认音色（T17，覆盖 Character.voice_pack_id）",
            ),
        )
        batch.add_column(
            sa.Column(
                "narration_voice_pack_id",
                sa.String(length=64),
                sa.ForeignKey(
                    "voice_packs.id",
                    name="fk_story_variants_narration_voice_pack_id",
                    ondelete="SET NULL",
                ),
                nullable=True,
                comment="变体级旁白音色（T17，line_mode=VOICE_OVER 时使用）",
            ),
        )
    op.create_index(
        "ix_story_variants_voice_pack_id",
        "story_variants",
        ["voice_pack_id"],
    )
    op.create_index(
        "ix_story_variants_narration_voice_pack_id",
        "story_variants",
        ["narration_voice_pack_id"],
    )

    # === shot_dialog_lines: 4 列 ==========================================
    with op.batch_alter_table("shot_dialog_lines") as batch:
        batch.add_column(
            sa.Column(
                "start_time_ms",
                sa.Integer(),
                nullable=True,
                comment="对白在镜头时间线内的起始毫秒；T17 chapter_av_planner 写入",
            ),
        )
        batch.add_column(
            sa.Column(
                "end_time_ms",
                sa.Integer(),
                nullable=True,
                comment="对白结束毫秒；end - start = TTS 音频时长上限",
            ),
        )
        batch.add_column(
            sa.Column(
                "tts_voice_id",
                sa.String(length=64),
                sa.ForeignKey(
                    "voice_packs.id",
                    name="fk_shot_dialog_lines_tts_voice_id",
                    ondelete="SET NULL",
                ),
                nullable=True,
                comment="本行强制使用的音色（覆盖角色默认）；空则按 "
                "speaker_character.voice_pack_id 解析",
            ),
        )
        batch.add_column(
            sa.Column(
                "tts_audio_file_id",
                sa.String(length=64),
                sa.ForeignKey(
                    "files.id",
                    name="fk_shot_dialog_lines_tts_audio_file_id",
                    ondelete="SET NULL",
                ),
                nullable=True,
                comment="本行 TTS 合成结果音频 FileItem ID；命中 tts_cache 时回填",
            ),
        )
    op.create_index(
        "ix_shot_dialog_lines_tts_voice_id",
        "shot_dialog_lines",
        ["tts_voice_id"],
    )
    op.create_index(
        "ix_shot_dialog_lines_tts_audio_file_id",
        "shot_dialog_lines",
        ["tts_audio_file_id"],
    )


def downgrade() -> None:
    """回滚：先 drop 5 个 FK 列与索引，再 drop tts_cache，最后 drop voice_packs。"""
    # shot_dialog_lines: 4 列（FK 列必须用 batch_alter_table 重建表）
    op.drop_index(
        "ix_shot_dialog_lines_tts_audio_file_id",
        table_name="shot_dialog_lines",
    )
    op.drop_index(
        "ix_shot_dialog_lines_tts_voice_id", table_name="shot_dialog_lines"
    )
    with op.batch_alter_table("shot_dialog_lines") as batch:
        batch.drop_column("tts_audio_file_id")
        batch.drop_column("tts_voice_id")
        batch.drop_column("end_time_ms")
        batch.drop_column("start_time_ms")

    # story_variants: 2 列
    op.drop_index(
        "ix_story_variants_narration_voice_pack_id",
        table_name="story_variants",
    )
    op.drop_index(
        "ix_story_variants_voice_pack_id", table_name="story_variants"
    )
    with op.batch_alter_table("story_variants") as batch:
        batch.drop_column("narration_voice_pack_id")
        batch.drop_column("voice_pack_id")

    # characters: 1 列
    op.drop_index(
        "ix_characters_voice_pack_id", table_name="characters"
    )
    with op.batch_alter_table("characters") as batch:
        batch.drop_column("voice_pack_id")

    # tts_cache（依赖 voice_packs，先 drop）
    op.drop_index("ix_tts_cache_audio_file_id", table_name="tts_cache")
    op.drop_index("ix_tts_cache_voice_pack_id", table_name="tts_cache")
    op.drop_index("ix_tts_cache_cache_key", table_name="tts_cache")
    op.drop_table("tts_cache")

    # voice_packs
    op.drop_index(
        "ix_voice_packs_provider_lang", table_name="voice_packs"
    )
    op.drop_index(
        "ix_voice_packs_sample_file_id", table_name="voice_packs"
    )
    op.drop_index(
        "ix_voice_packs_language_code", table_name="voice_packs"
    )
    op.drop_index("ix_voice_packs_provider", table_name="voice_packs")
    op.drop_table("voice_packs")
