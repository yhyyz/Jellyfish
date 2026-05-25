/* generated using openapi-typescript-codegen -- do not edit */
/* istanbul ignore file */
/* tslint:disable */
/* eslint-disable */
/**
 * 克隆变体的请求体；可选覆盖字段（W14-T3，A/B 变体管理）。
 *
 * 用于 ``POST /story-variants/{id}/clone`` 接口：基于已有变体快速派生一
 * 个新的 ``draft`` 变体，业务方可在克隆同时调整 ``archetype`` /
 * ``hook_pattern_id`` / ``cta_pattern_id`` / ``formula_id`` 等关键 A/B
 * 维度，无需重复传递剧本文本与镜头分解。
 *
 * 设计要点：
 *
 * * ``extra="forbid"``：阻止客户端通过未知字段（例如 ``status``、
 * ``is_champion``、``compliance_score``）绕过服务端固定值，保持与
 * :class:`StoryVariantCreate` 一致的"只读字段"语义。
 * * 全部字段可选（``None`` 即 "保持源变体值"），调用方仅传需要变更的
 * 维度即可触发针对性 A/B；``label`` 仅作业务备注，不写库。
 */
export type StoryVariantCloneRequest = {
    /**
     * 覆盖 archetype（None 表示保持源变体）
     */
    new_archetype?: (string | null);
    /**
     * 覆盖 hook_pattern_id（P2 钩子模式 A/B）
     */
    new_hook_pattern_id?: (string | null);
    /**
     * 覆盖 cta_pattern_id（P2 CTA 模式 A/B）
     */
    new_cta_pattern_id?: (string | null);
    /**
     * 覆盖 formula_id（切换剧情公式做更激进的 A/B）
     */
    new_formula_id?: (string | null);
    /**
     * 备注，仅供调用方记录派生意图，不会写入数据库
     */
    label?: (string | null);
};

