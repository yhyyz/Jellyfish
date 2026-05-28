/* generated using openapi-typescript-codegen -- do not edit */
/* istanbul ignore file */
/* tslint:disable */
/* eslint-disable */
/**
 * 项目级 SubtitleStyle 写入 DTO（W30-T3 POST 入参）。
 *
 * 仅暴露用户可编辑字段；``id`` / ``project_id`` / ``is_system`` /
 * ``sort_order`` / ``created_at`` / ``updated_at`` 等服务端管理字段
 * 在 service 层注入，不允许调用方传入。
 *
 * 校验由 service 层做 ``(project_id, name)`` 唯一性 enforce；schema
 * 层只做基础形态约束（必填、长度、numeric 范围）。
 */
export type ProjectSubtitleStyleCreateInput = {
    /**
     * 展示名称
     */
    name: string;
    /**
     * 样式描述（适用平台、视觉特点等）
     */
    description?: (string | null);
    /**
     * 主语言代码
     */
    language_code?: string;
    /**
     * 字幕文件格式：ass / srt / vtt
     */
    format?: string;
    /**
     * 主字体 family name（ASS Fontname）
     */
    font_family: string;
    /**
     * 字号（脚本像素）
     */
    font_size: number;
    /**
     * 主填充色 &HAABBGGRR
     */
    primary_colour?: string;
    /**
     * 预高亮色 &HAABBGGRR
     */
    secondary_colour?: string;
    /**
     * 描边色 &HAABBGGRR
     */
    outline_colour?: string;
    /**
     * 阴影色 &HAABBGGRR
     */
    back_colour?: string;
    /**
     * 是否粗体
     */
    bold?: boolean;
    /**
     * 是否斜体
     */
    italic?: boolean;
    /**
     * ASS BorderStyle：1=描边+阴影 / 3=实心矩形盒
     */
    border_style?: number;
    /**
     * 描边宽度（像素）
     */
    outline?: number;
    /**
     * 阴影偏移（像素）
     */
    shadow?: number;
    /**
     * ASS Alignment numpad（1-9）：1=底左 / 2=底中 / 3=底右 / 4=中左 / 5=中中 / 6=中右 / 7=顶左 / 8=顶中 / 9=顶右
     */
    alignment?: number;
    /**
     * 左边距（像素）
     */
    margin_l?: number;
    /**
     * 右边距（像素）
     */
    margin_r?: number;
    /**
     * 垂直边距（像素）
     */
    margin_v?: number;
    /**
     * ASS PlayResX
     */
    play_res_x?: number;
    /**
     * ASS PlayResY
     */
    play_res_y?: number;
    /**
     * 字体回退链 list[str]
     */
    font_fallback_chain?: (Array<string> | null);
};

