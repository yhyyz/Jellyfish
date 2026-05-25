/* generated using openapi-typescript-codegen -- do not edit */
/* istanbul ignore file */
/* tslint:disable */
/* eslint-disable */
/**
 * ``POST /api/v1/commerce/products/extract`` 请求体。
 *
 * Attributes:
 * raw_text: 商品原始文本来源（详情页拷贝、口述描述、SEO 标题等），
 * 由 worker 层做长度截断与归一化，schema 层只保证字段存在。
 * target_fields: 期望提取的字段白名单；``None`` 表示按 worker 默认
 * 策略提取全部可识别字段，传空列表与 ``None`` 同义。
 */
export type ProductExtractRequest = {
    /**
     * 商品原始文本（详情页 / 描述 / 链接抓取后的纯文本）
     */
    raw_text: string;
    /**
     * 期望提取的字段白名单；不传或传 null 表示提取全部可识别字段
     */
    target_fields?: (Array<string> | null);
};

