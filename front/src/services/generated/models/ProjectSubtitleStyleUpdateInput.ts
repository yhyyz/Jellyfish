/* generated using openapi-typescript-codegen -- do not edit */
/* istanbul ignore file */
/* tslint:disable */
/* eslint-disable */
/**
 * 项目级 SubtitleStyle 更新 DTO（W30-T3 PATCH 入参）。
 *
 * 所有字段均 optional，service 层只更新 explicit 提供的字段（``model_dump
 * (exclude_unset=True)``）；不允许把项目级行的 ``project_id`` / ``id`` /
 * ``is_system`` 改写。
 */
export type ProjectSubtitleStyleUpdateInput = {
    name?: (string | null);
    description?: (string | null);
    language_code?: (string | null);
    format?: (string | null);
    font_family?: (string | null);
    font_size?: (number | null);
    primary_colour?: (string | null);
    secondary_colour?: (string | null);
    outline_colour?: (string | null);
    back_colour?: (string | null);
    bold?: (boolean | null);
    italic?: (boolean | null);
    border_style?: (number | null);
    outline?: (number | null);
    shadow?: (number | null);
    alignment?: (number | null);
    margin_l?: (number | null);
    margin_r?: (number | null);
    margin_v?: (number | null);
    play_res_x?: (number | null);
    play_res_y?: (number | null);
    font_fallback_chain?: (Array<string> | null);
};

