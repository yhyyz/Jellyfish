"""参考图预算分配器（Decision G / W16 T16-6）。

提供 `ReferenceImageBudget`，用于将上游候选的三类参考图
（Product / Character / Scene）裁剪为模型可接受的 9 槽参考图列表。

为什么需要这个模块：
- 多图参考视频模型（如 happyhorse-1.0-r2v）对参考图数量有硬上限；
- 不同类别有不同业务优先级，剧情带货场景下 Product > Character > Scene；
- 任务系统需要一份稳定可复现的裁剪结果以及对应的 warning 列表，
  以便在任务元数据中记录“为什么少了几张参考图”。

模块只负责按规则裁剪，不负责候选来源的获取与解析。
"""
from __future__ import annotations

from collections.abc import Iterable
from dataclasses import dataclass, field
import typing
from typing import Final

DEFAULT_PRODUCT_SLOTS: Final[int] = 5
DEFAULT_CHARACTER_SLOTS: Final[int] = 3
DEFAULT_SCENE_SLOTS: Final[int] = 2
DEFAULT_TOTAL_CAP: Final[int] = 9


@dataclass(frozen=True)
class ReferenceImageBudgetSpec:
    """单次视频生成的参考图槽位配额。

    slot allocation 用于 happyhorse-1.0-r2v 等多图参考视频模型，按类别分配槽位
    （Product 最高优先），超额按提供顺序的尾部丢弃并发出 warning。

    Attributes:
        product_slots: 商品图最多保留多少张（默认 5）。
        character_slots: 角色图最多保留多少张（默认 3）。
        scene_slots: 场景图最多保留多少张（默认 2）。
        total_cap: 三类合计最多保留多少张（默认 9）。
    """

    product_slots: int = DEFAULT_PRODUCT_SLOTS
    character_slots: int = DEFAULT_CHARACTER_SLOTS
    scene_slots: int = DEFAULT_SCENE_SLOTS
    total_cap: int = DEFAULT_TOTAL_CAP


@dataclass(frozen=True)
class ReferenceImageBudgetResult:
    """`ReferenceImageBudget.apply` 返回值。

    Attributes:
        product_refs: 裁剪后的商品图引用列表。
        character_refs: 裁剪后的角色图引用列表。
        scene_refs: 裁剪后的场景图引用列表。
        warnings: 因超额而丢弃的告警字符串，便于写入任务元数据。
    """

    product_refs: list[str] = field(default_factory=list)
    character_refs: list[str] = field(default_factory=list)
    scene_refs: list[str] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)

    @property
    def all_refs(self) -> list[str]:
        """按 Product → Character → Scene 顺序拼接的最终参考列表。"""
        return [*self.product_refs, *self.character_refs, *self.scene_refs]


def _normalize(refs: list[str] | Iterable[str] | None) -> list[str]:
    """将 None 或任意可迭代输入归一化为 list。"""
    if refs is None:
        return []
    return list(refs)


def _clip_with_warning(
    refs: list[str],
    cap: int,
    category: str,
) -> tuple[list[str], list[str]]:
    """按 cap 裁掉尾部，超额时生成 1 条 warning。

    Args:
        refs: 候选参考列表（顺序即优先级，前者优先保留）。
        cap: 该类别的槽位上限。
        category: 类别名（product / character / scene），用于 warning 文本。

    Returns:
        (kept_refs, warnings) 二元组。
    """
    if len(refs) <= cap:
        return refs, []
    dropped = len(refs) - cap
    warning = f"{category} overflow: dropped {dropped} refs (cap={cap})"
    return refs[:cap], [warning]


@typing.final
class ReferenceImageBudget:
    """9 槽参考图预算（Decision G）。

    职责：
    - 接收 3 个类别的候选参考列表（顺序即优先级，前面的优先保留）；
    - 按 spec 分配槽位（Product 5 / Character 3 / Scene 2，总额 9）；
    - 按 ``max_total_override`` 动态收紧（如模型能力 max_reference_images < 9）；
    - 超额按尾部丢弃，每次丢弃产生一条 warning 字符串供任务元数据记录。

    本类是纯计算的无状态工具，可在任务编排层重复构造，无副作用。
    """

    def __init__(self, spec: ReferenceImageBudgetSpec | None = None) -> None:
        """构造预算分配器。

        Args:
            spec: 自定义槽位配额。None 时使用默认 5/3/2/9 配置。
        """
        self.spec = spec or ReferenceImageBudgetSpec()

    def apply(
        self,
        *,
        product_refs: list[str] | None = None,
        character_refs: list[str] | None = None,
        scene_refs: list[str] | None = None,
        max_total_override: int | None = None,
    ) -> ReferenceImageBudgetResult:
        """按预算裁剪候选参考列表。

        裁剪算法：
            1. 输入归一化（None → []）。
            2. 计算实际总额上限 effective_total_cap =
               min(spec.total_cap, max_total_override or +∞)。
            3. 第一遍：按各类别 cap 裁剪，超额生成 warning。
            4. 第二遍：若三类合计仍超 effective_total_cap，
               按 Scene → Character → Product 顺序从尾部继续丢，
               并追加一条 total overflow warning。

        Args:
            product_refs: 商品图候选（如 ProductImage.file_id 列表）。
            character_refs: 角色图候选。
            scene_refs: 场景图候选。
            max_total_override: 动态总额上限（None=用 spec.total_cap）。

        Returns:
            ReferenceImageBudgetResult 包含裁剪后的 3 个类别列表 + warnings。
        """
        product_list = _normalize(product_refs)
        character_list = _normalize(character_refs)
        scene_list = _normalize(scene_refs)

        warnings: list[str] = []

        # 第一遍：每类按自身 cap 裁剪
        product_kept, w = _clip_with_warning(
            product_list, self.spec.product_slots, "product"
        )
        warnings.extend(w)

        character_kept, w = _clip_with_warning(
            character_list, self.spec.character_slots, "character"
        )
        warnings.extend(w)

        scene_kept, w = _clip_with_warning(
            scene_list, self.spec.scene_slots, "scene"
        )
        warnings.extend(w)

        # 第二遍：受 effective_total_cap 约束再裁
        if max_total_override is not None:
            effective_total_cap = min(self.spec.total_cap, max_total_override)
        else:
            effective_total_cap = self.spec.total_cap

        # 防御性下界，避免负数
        effective_total_cap = max(effective_total_cap, 0)

        total_now = len(product_kept) + len(character_kept) + len(scene_kept)
        if total_now > effective_total_cap:
            overflow = total_now - effective_total_cap
            scene_kept, character_kept, product_kept = self._drop_by_priority(
                product_kept, character_kept, scene_kept, overflow
            )
            warnings.append(
                f"total overflow: dropped {overflow} refs (effective_total_cap={effective_total_cap})"
            )

        return ReferenceImageBudgetResult(
            product_refs=product_kept,
            character_refs=character_kept,
            scene_refs=scene_kept,
            warnings=warnings,
        )

    @staticmethod
    def _drop_by_priority(
        product_kept: list[str],
        character_kept: list[str],
        scene_kept: list[str],
        overflow: int,
    ) -> tuple[list[str], list[str], list[str]]:
        """按低优先级顺序丢弃尾部元素。

        丢弃顺序：Scene → Character → Product。
        每个类别先丢光自身尾部再切到下一个类别。

        Args:
            product_kept: 当前 product 列表。
            character_kept: 当前 character 列表。
            scene_kept: 当前 scene 列表。
            overflow: 还需要丢弃多少个。

        Returns:
            裁剪后的 (scene, character, product) 三元组（注意返回顺序与签名一致）。
        """
        remaining = overflow

        drop_from_scene = min(remaining, len(scene_kept))
        if drop_from_scene > 0:
            scene_kept = scene_kept[: len(scene_kept) - drop_from_scene]
            remaining -= drop_from_scene

        if remaining > 0:
            drop_from_character = min(remaining, len(character_kept))
            if drop_from_character > 0:
                character_kept = character_kept[
                    : len(character_kept) - drop_from_character
                ]
                remaining -= drop_from_character

        if remaining > 0:
            drop_from_product = min(remaining, len(product_kept))
            if drop_from_product > 0:
                product_kept = product_kept[
                    : len(product_kept) - drop_from_product
                ]

        return scene_kept, character_kept, product_kept
