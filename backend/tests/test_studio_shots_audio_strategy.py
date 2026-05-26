"""Shot ORM 上 audio_strategy / product_focus_level 字段的单元测试（W16 T16-8）。

覆盖目标：

- 两个新列在 ``Shot`` 模型上确实存在；
- 列类型为 ``String``，长度为规范要求的 32 / 16；
- ``nullable=False``，确保业务侧永远拿到具体取值；
- ``server_default`` 与 P3 决策一致：silent_with_tts / none；
- ``default`` 指向 ``AudioStrategy`` / ``ProductFocusLevel`` 枚举成员；
- 字段 comment 非空，遵循 AGENTS.md 注释要求。
"""

from __future__ import annotations

from sqlalchemy import String

from app.models.studio_shots import Shot
from app.models.types import AudioStrategy, ProductFocusLevel


def _column(name: str):
    """从 ``Shot.__table__`` 中取出对应列；用于在多个测试中统一访问。"""
    return Shot.__table__.columns[name]


def test_audio_strategy_column_definition() -> None:
    """audio_strategy 列必须为 String(32)、NOT NULL、server_default=silent_with_tts。"""
    col = _column("audio_strategy")
    assert isinstance(col.type, String)
    assert col.type.length == 32
    assert col.nullable is False
    assert col.default is not None
    assert col.default.arg is AudioStrategy.silent_with_tts
    assert col.server_default is not None
    # server_default.arg 在 SQLAlchemy 中为 TextClause；其 ``text`` 属性是字面量。
    assert getattr(col.server_default.arg, "text", str(col.server_default.arg)) == (
        "silent_with_tts"
    )
    assert col.comment and "silent_with_tts" in col.comment


def test_product_focus_level_column_definition() -> None:
    """product_focus_level 列必须为 String(16)、NOT NULL、server_default=none。"""
    col = _column("product_focus_level")
    assert isinstance(col.type, String)
    assert col.type.length == 16
    assert col.nullable is False
    assert col.default is not None
    assert col.default.arg is ProductFocusLevel.none
    assert col.server_default is not None
    assert getattr(col.server_default.arg, "text", str(col.server_default.arg)) == "none"
    assert col.comment and "Decision H" in col.comment


def test_new_columns_appear_after_generated_video_file_id() -> None:
    """新列应位于 generated_video_file_id 之后，保留 ORM 定义顺序的语义分组。"""
    column_names = [col.name for col in Shot.__table__.columns]
    idx_video = column_names.index("generated_video_file_id")
    idx_audio = column_names.index("audio_strategy")
    idx_focus = column_names.index("product_focus_level")
    assert idx_audio == idx_video + 1
    assert idx_focus == idx_audio + 1
