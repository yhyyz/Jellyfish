/**
 * BrandStyleGuideForm —— 商品的"品牌话术规范"表单（W25-T3, P4 Wave A）。
 *
 * 设计要点：
 * - 嵌入 ProductLibrary 详情 drawer 的 BrandStyleGuide tab；
 * - 通过 `useBrandStyleGuide` 拉取已有规范（404 视作"尚未创建"，UI 进入空态）；
 * - "保存"统一走 POST upsert（后端把首次保存当作创建，再次保存视为部分更新），
 *   减少前端分支判断；
 * - "清空规范"使用独立 DELETE 按钮，仅在已有规范时显示；
 * - 4 个数组字段（forced_phrases / banned_patterns / required_endings）使用
 *   antd `Select mode="tags"`，体验与 ProductFormModal 一致；
 *   tagline 使用普通 `Input.TextArea`（255 字符上限对齐后端）。
 *
 * 与 T25-1/T25-2 LLM validator 的关系：
 * - 本表单只负责 CRUD；validator 后续会读取这张表的字段做生成端校验，
 *   本任务不做集成。
 */
import React, { useEffect } from 'react'
import {
  Alert,
  Button,
  Form,
  Input,
  Popconfirm,
  Select,
  Space,
  Spin,
  message,
} from 'antd'
import { ApiError } from '../../../../../services/generated'
import {
  useBrandStyleGuide,
  useDeleteBrandStyleGuide,
  useUpsertBrandStyleGuide,
} from '../queries'

/**
 * 表单内部值；与 backend ``BrandStyleGuideUpsert`` 字段同名同形。
 */
type FormValues = {
  forced_phrases?: string[]
  banned_patterns?: string[]
  required_endings?: string[]
  brand_persona_tagline?: string
}

type Props = {
  /** 当前商品 ID；未选中时 form 处于禁用空态，避免误请求。*/
  productId: string | null | undefined
}

/**
 * 渲染品牌话术规范编辑面板。父级（ProductLibrary 详情面板）只需透传
 * ``productId``；本组件内部完成数据拉取、保存、清空与错误展示。
 */
export const BrandStyleGuideForm: React.FC<Props> = ({ productId }) => {
  const [form] = Form.useForm<FormValues>()

  const { data, isLoading, isError, error } = useBrandStyleGuide(productId)
  const upsertMutation = useUpsertBrandStyleGuide()
  const deleteMutation = useDeleteBrandStyleGuide()

  // 后端 404 表示"尚未创建规范"，视为正常空态；其他错误才提示。
  const guideMissing =
    isError && error instanceof ApiError && error.status === 404
  const fatalError = isError && !guideMissing

  // 拉到数据后回填到表单；清空时也要重置，避免残留上一次内容。
  useEffect(() => {
    if (!productId) {
      form.resetFields()
      return
    }
    if (data) {
      form.setFieldsValue({
        forced_phrases: data.forced_phrases ?? [],
        banned_patterns: data.banned_patterns ?? [],
        required_endings: data.required_endings ?? [],
        brand_persona_tagline: data.brand_persona_tagline ?? '',
      })
    } else if (guideMissing) {
      form.setFieldsValue({
        forced_phrases: [],
        banned_patterns: [],
        required_endings: [],
        brand_persona_tagline: '',
      })
    }
  }, [productId, data, guideMissing, form])

  const handleSubmit = async (values: FormValues) => {
    if (!productId) return
    try {
      await upsertMutation.mutateAsync({
        productId,
        body: {
          forced_phrases: values.forced_phrases ?? [],
          banned_patterns: values.banned_patterns ?? [],
          required_endings: values.required_endings ?? [],
          brand_persona_tagline: values.brand_persona_tagline ?? '',
        },
      })
      message.success('品牌话术规范已保存')
    } catch (err) {
      message.error('保存失败，请稍后重试')
    }
  }

  const handleDelete = async () => {
    if (!productId) return
    try {
      await deleteMutation.mutateAsync(productId)
      form.setFieldsValue({
        forced_phrases: [],
        banned_patterns: [],
        required_endings: [],
        brand_persona_tagline: '',
      })
      message.success('品牌话术规范已清空')
    } catch (err) {
      message.error('清空失败，请稍后重试')
    }
  }

  if (!productId) {
    return (
      <Alert
        type="info"
        showIcon
        message="选择一个商品后再编辑品牌话术规范"
        data-testid="brand-style-guide-empty-product"
      />
    )
  }

  if (isLoading) {
    return (
      <div className="py-6 text-center" data-testid="brand-style-guide-loading">
        <Spin />
      </div>
    )
  }

  if (fatalError) {
    return (
      <Alert
        type="error"
        showIcon
        message="加载品牌话术规范失败"
        description={String((error as Error)?.message ?? '未知错误')}
        data-testid="brand-style-guide-error"
      />
    )
  }

  const submitting = upsertMutation.isPending
  const removing = deleteMutation.isPending
  const hasGuide = !!data && !guideMissing

  return (
    <Form
      form={form}
      layout="vertical"
      onFinish={handleSubmit}
      data-testid="brand-style-guide-form"
    >
      {guideMissing ? (
        <Alert
          className="mb-3"
          type="info"
          showIcon
          message="该商品尚未配置品牌话术规范，保存后将自动创建。"
        />
      ) : null}

      <Form.Item
        name="brand_persona_tagline"
        label="品牌人格短描述"
        tooltip="一句话品牌调性，会注入到 LLM system prompt"
      >
        <Input.TextArea
          rows={2}
          maxLength={255}
          showCount
          placeholder="例如：理性的成分党闺蜜，不夸张不煽情"
        />
      </Form.Item>

      <Form.Item
        name="forced_phrases"
        label="强制金句（生成时必须包含）"
        tooltip="生成器会确保脚本/对白包含这些短语"
      >
        <Select
          mode="tags"
          placeholder="输入金句后回车，例如：今天买不亏"
          tokenSeparators={[',', '，']}
        />
      </Form.Item>

      <Form.Item
        name="banned_patterns"
        label="禁用句式（生成器需回避）"
        tooltip="出现在脚本中的句子若命中其中任一短语，将触发后续 validator 重写"
      >
        <Select
          mode="tags"
          placeholder="输入禁语后回车，例如：宇宙第一"
          tokenSeparators={[',', '，']}
        />
      </Form.Item>

      <Form.Item
        name="required_endings"
        label="必备结尾（CTA / 免责声明）"
        tooltip="脚本结尾必须出现的固定话术"
      >
        <Select
          mode="tags"
          placeholder="输入必备结尾后回车，例如：详情见详情页"
          tokenSeparators={[',', '，']}
        />
      </Form.Item>

      <Form.Item>
        <Space className="w-full justify-end">
          {hasGuide ? (
            <Popconfirm
              title="清空当前品牌话术规范？"
              okText="确认清空"
              cancelText="取消"
              onConfirm={() => void handleDelete()}
            >
              <Button danger loading={removing} data-testid="brand-style-guide-delete">
                清空规范
              </Button>
            </Popconfirm>
          ) : null}
          <Button
            type="primary"
            htmlType="submit"
            loading={submitting}
            data-testid="brand-style-guide-submit"
          >
            保存
          </Button>
        </Space>
      </Form.Item>
    </Form>
  )
}

export default BrandStyleGuideForm
