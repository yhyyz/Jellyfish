/* generated using openapi-typescript-codegen -- do not edit */
/* istanbul ignore file */
/* tslint:disable */
/* eslint-disable */
/**
 * 变体级聚合的单行（按 variant_id 折叠所有 outcome）。
 *
 * 业务语义：
 * - 数值列均使用 ``SUM(outcome.X)``；
 * - 完播率走 AVG（与 KPI 摘要一致，rate 类指标避免 SUM 累加）；
 * - ``cart_rate`` 由后端在 SQL 端算 ``SUM(cart_clicks) / NULLIF(SUM(plays), 0)``，
 * 前端不二次除法，避免视图各自实现导致不一致。
 */
export type VariantAggregateRow = {
    /**
     * 变体 ID（StoryVariant.id）
     */
    variant_id: string;
    /**
     * 变体可读名（暂取 ``script_full_text`` 首 32 字符，未来落地正式 ``name`` 字段后切换）。
     */
    variant_name?: string;
    /**
     * 所属公式 ID
     */
    formula_id?: (string | null);
    /**
     * 所属公式名（join StoryFormula）
     */
    formula_name?: (string | null);
    /**
     * 品牌人格 ID
     */
    archetype?: (string | null);
    /**
     * 是否冠军变体（A/B 决出后置位）
     */
    is_champion?: boolean;
    /**
     * 窗口内累计播放量
     */
    plays?: number;
    /**
     * 窗口内完播率均值；无数据时 None
     */
    completion_rate_full?: (number | null);
    /**
     * 窗口内累计加购点击
     */
    cart_clicks?: number;
    /**
     * 窗口内加购率（SUM(cart_clicks) / SUM(plays)）；总播放为 0 时返回 None
     */
    cart_rate?: (number | null);
    /**
     * 窗口内累计订单数
     */
    orders?: number;
    /**
     * 窗口内累计 GMV
     */
    gmv?: number;
    /**
     * 该变体在窗口内的 outcome 行数
     */
    outcome_count?: number;
};

