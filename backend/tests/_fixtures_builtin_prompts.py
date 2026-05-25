"""``test_builtin_prompts_render_snapshots`` 的 canonical 渲染 fixture。

每个 key 必须是 BUILTIN_PROMPT_DEFINITIONS 中某个 commerce 模板的 ``id``，
value 是用于 ``render_template(..., variables=value)`` 的上下文字典。

为保证 snapshot 稳定，请勿在此处使用：
    - 时间 / UUID / 随机数；
    - 依赖外部状态的对象。
仅使用纯字面量。任何修改都会引发 snapshot drift，需有意识地用
``UPDATE_SNAPSHOTS=1 uv run pytest ...`` 重新生成。
"""

from __future__ import annotations

# ---------------------------------------------------------------------------
# 共享子结构
# ---------------------------------------------------------------------------

_PRODUCT = {
    "name": "DemoSerum",
    "brand": "DemoLab",
    "category": "beauty",
    "description": "纯净配方精华，敏肌可用",
    "selling_points": ["快速补水", "提亮肤色", "舒缓泛红"],
    "pain_points_solved": ["晨起暗沉", "换季干痒"],
    "target_audience": {"age_range": "25-34", "city_tier": "T1"},
}

_AUDIENCE = {
    "age_range": "25-34",
    "gender": "F",
    "city_tier": "T1",
    "motivation": "通勤前 30 秒护肤",
}

_TONE_GRID = {
    "formal": 4,
    "energy": 7,
    "humor": 6,
    "warmth": 7,
    "specificity": 8,
}

_FORMULA = {
    "id": "underdog_triumph",
    "name": "凡人逆袭",
    "beats": [
        {"id": "low_point", "duration_sec": 18, "function": "羞辱处境"},
        {"id": "turning_point", "duration_sec": 12, "function": "商品入场"},
        {"id": "triumph", "duration_sec": 30, "function": "反转高光"},
    ],
}

_SCRIPT_PLACEHOLDER = {
    "shots": [
        {"id": "shot_001", "duration_sec": 4, "dialog": "我又被同事说气色差。"},
        {"id": "shot_002", "duration_sec": 4, "dialog": "今晚试试这瓶。"},
    ],
    "opening_hook": "你以为是熬夜，其实是脸已经罢工。",
    "cta_text": "购物车低价 30 单可见。",
}


# ---------------------------------------------------------------------------
# 12 个 commerce 模板的 canonical 渲染上下文
# ---------------------------------------------------------------------------

COMMERCE_FIXTURES: dict[str, dict[str, object]] = {
    "product_extraction_v1": {
        "raw_text": "DemoLab 纯净配方精华 30ml，敏肌可用，含烟酰胺与神经酰胺。",
        "target_fields": [
            "name",
            "brand",
            "category",
            "selling_points",
            "pain_points_solved",
            "target_audience",
        ],
    },
    "story_formula_generator_v1": {
        "formula": _FORMULA,
        "product": _PRODUCT,
        "audience": _AUDIENCE,
        "archetype": "sage",
        "tone_grid": _TONE_GRID,
        "target_duration_sec": 60,
        "platform": "douyin",
    },
    "hook_pattern_writer_v1": {
        "pattern_id": "question",
        "product": _PRODUCT,
        "audience": _AUDIENCE,
    },
    "cta_pattern_writer_v1": {
        "hardness": "medium",
        "product": _PRODUCT,
        "urgency_type": "scarcity",
    },
    "archetype_voice_rewriter_v1": {
        "archetype": "rebel",
        "tone_grid": _TONE_GRID,
        "original_script": _SCRIPT_PLACEHOLDER,
        "words_to_avoid": ["无敌", "最", "首选"],
        "preferred_vocab": ["实测", "稳", "顺手"],
    },
    "compliance_checker_v1": {
        "script": _SCRIPT_PLACEHOLDER,
        "region": "cn_mainland",
        "product_category": "beauty",
    },
    "product_image_front_v1": {
        "product": _PRODUCT,
        "style": "minimalist clean",
    },
    "product_image_other_v1": {
        "product": _PRODUCT,
        "view_angle": "detail",
    },
    "product_placement_prompt_v1": {
        "product": _PRODUCT,
        "scene": "bathroom morning",
        "interaction": "拿起瓶子，按压一滴在虎口",
    },
    "product_hero_prompt_v1": {
        "product": _PRODUCT,
        "dramatic_moment": "镜头慢推近瓶身，背光勾出轮廓",
    },
    "audience_insight_v1": {
        "product": _PRODUCT,
        "target_audience": _AUDIENCE,
    },
    "brand_voice_profile_v1": {
        "archetype": "sage",
        "tone_grid": _TONE_GRID,
        "competitor_voice": "高冷、专家口吻、长句堆参数",
    },
}


__all__ = ["COMMERCE_FIXTURES"]
