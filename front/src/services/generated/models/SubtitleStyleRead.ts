/* generated using openapi-typescript-codegen -- do not edit */
/* istanbul ignore file */
/* tslint:disable */
/* eslint-disable */
/**
 * SubtitleStyle 只读响应。
 *
 * 用于 ``GET /api/v1/commerce/subtitle-styles`` 列表接口。字段直接映射
 * 自 ORM 列；``alignment`` 字段由 service 层从 ``SubtitleAlignment`` 字
 * 符串枚举换算为 ASS numpad int（1-9）后注入，因此本 schema 不开
 * ``from_attributes`` —— 路由层用 ``model_validate(dict)`` 走 dict 路径
 * 保证类型一致。
 */
export type SubtitleStyleRead = {
    /**
     * 字幕样式 ID（如 douyin_default / tiktok_viral / reels_lower_third）
     */
    id: string;
    /**
     * 展示名称（如 抖音默认 / TikTok 病毒式）
     */
    name: string;
    /**
     * 样式描述（适用平台、视觉特点等）
     */
    description?: (string | null);
    /**
     * 主语言代码（决定 font_fallback_chain 默认值与 ASS Encoding）
     */
    language_code: string;
    /**
     * 字幕文件格式：ass / srt / vtt
     */
    format: string;
    /**
     * 主字体 family name（ASS Fontname；缺失时由 font_fallback_chain 兜底）
     */
    font_family: string;
    /**
     * 字号（脚本像素，按 PlayResY=1920 计）
     */
    font_size: number;
    /**
     * 主填充色 &HAABBGGRR（高亮后 / \kf 终态色）
     */
    primary_colour: string;
    /**
     * 预高亮色 &HAABBGGRR（\kf 起始色，无逐词高亮时与 primary 一致）
     */
    secondary_colour?: (string | null);
    /**
     * 描边色 &HAABBGGRR（BorderStyle=1）或盒背景色（=3）
     */
    outline_colour: string;
    /**
     * 阴影色 &HAABBGGRR（透明度通过 alpha 字节控制）
     */
    back_colour?: (string | null);
    /**
     * 是否粗体（移动端可读性默认开启）
     */
    bold: boolean;
    /**
     * 是否斜体
     */
    italic: boolean;
    /**
     * ASS BorderStyle：1=描边+阴影 / 3=实心矩形盒
     */
    border_style: number;
    /**
     * 描边宽度（像素）
     */
    outline: number;
    /**
     * 阴影偏移（像素）
     */
    shadow: number;
    /**
     * ASS Alignment numpad（1-9）：1=底左 / 2=底中 / 3=底右 / 4=中左 / 5=中中 / 6=中右 / 7=顶左 / 8=顶中 / 9=顶右
     */
    alignment: number;
    /**
     * 左边距（像素）
     */
    margin_l: number;
    /**
     * 右边距（像素）
     */
    margin_r: number;
    /**
     * 垂直边距（像素）：alignment 为 bottom_* 时离底部，top_* 时离顶部
     */
    margin_v: number;
    /**
     * ASS PlayResX：脚本坐标系宽度，应等于视频原生宽（1080）
     */
    play_res_x: number;
    /**
     * ASS PlayResY：脚本坐标系高度，应等于视频原生高（1920）
     */
    play_res_y: number;
    /**
     * 字体回退链 list[str]（渲染前按系统字体逐项探测，找不到时下移）
     */
    font_fallback_chain?: (Array<string> | null);
    /**
     * 系统级样式标记，true 时不可被用户删除
     */
    is_system: boolean;
    /**
     * UI 列表显示顺序（升序）
     */
    sort_order: number;
    /**
     * 项目级覆盖归属的项目 ID；NULL=系统级 seed，非 NULL=该项目自定义
     */
    project_id?: (string | null);
    /**
     * 入库时间
     */
    created_at: string;
    /**
     * 最近一次更新时间
     */
    updated_at: string;
};

