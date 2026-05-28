/**
 * 商品创建/编辑表单弹窗。
 *
 * 镜像 ProjectLobby 中“新建项目 / 编辑项目”弹窗的范式：
 * - 使用 `Form.useForm()` 受控表单，避免裸 useState 难以维护字段联动；
 * - mode === 'create' 时调用 useCreateProduct；mode === 'edit' 时调用
 *   useUpdateProduct，由 TanStack Query 完成缓存失效；
 * - target_audience 是 dict 字段，P1 暂不在 UI 暴露（P2 接入“画像编辑器”），
 *   后端默认为空 dict 即可，不会丢字段。
 *
 * 校验策略：仅 name/style 强制必填（与后端 Pydantic 模型对齐），
 * 其余字段允许为空字符串/空数组/None。
 */
import React, { useEffect } from 'react'
import {
  Button,
  Form,
  Input,
  InputNumber,
  Modal,
  Select,
  Space,
  Switch,
  Tabs,
  message,
} from 'antd'
import type { ProductCategory, ProductCreate, ProjectStyle, ProjectVisualStyle } from '../../../../services/generated'
import { BrandStyleGuideForm } from './components/BrandStyleGuideForm'
import { useCreateProduct, useUpdateProduct, type ProductRead } from './queries'

type Props = {
  mode: 'create' | 'edit'
  open: boolean
  initial?: ProductRead | null
  /** 用于“从 URL 提取”后的预填表单；P1 通常不会触达，预留 P2 扩展 */
  prefill?: Partial<ProductCreate> | null
  onCancel: () => void
  onSuccess: () => void
}

/** 商品品类选项；与 backend `ProductCategory` 枚举严格对齐 */
const CATEGORY_OPTIONS: { value: ProductCategory; label: string }[] = [
  { value: 'electronics', label: '电子' },
  { value: 'beauty', label: '美妆' },
  { value: 'food', label: '食品' },
  { value: 'apparel', label: '服饰' },
  { value: 'home', label: '家居' },
  { value: 'health', label: '健康' },
  { value: 'other', label: '其他' },
]

/**
 * 视觉风格选项。当前后端 `ProjectVisualStyle` 仅暴露“现实”，
 * 留作 enum 扩展占位；codegen 更新后会自动同步可选项数量。
 */
const VISUAL_STYLE_OPTIONS: { value: ProjectVisualStyle; label: string }[] = [
  { value: '现实', label: '现实' },
]

/**
 * 项目题材风格选项；与 backend `ProjectStyle` 枚举对齐。
 * 与 ProjectLobby 中的下拉一致，便于后续扩展统一选项。
 */
const PROJECT_STYLE_OPTIONS: { value: ProjectStyle; label: string }[] = [
  { value: '真人都市', label: '真人都市' },
  { value: '动漫3D', label: '动漫3D' },
]

type FormValues = {
  name: string
  brand?: string
  category?: ProductCategory
  description?: string
  style: ProjectStyle
  visual_style: ProjectVisualStyle
  price_anchor?: number | null
  sku?: string | null
  selling_points?: string[]
  pain_points_solved?: string[]
  catchphrases?: string[]
  competitor_names?: string[]
  health_disclaimer_required?: boolean
}

/**
 * 渲染商品创建/编辑弹窗。父级负责控制 open/initial/prefill。
 */
export const ProductFormModal: React.FC<Props> = ({
  mode,
  open,
  initial,
  prefill,
  onCancel,
  onSuccess,
}) => {
  const [form] = Form.useForm<FormValues>()
  const createMutation = useCreateProduct()
  const updateMutation = useUpdateProduct()

  // mode + open + initial/prefill 变化时同步表单内容；避免残留上一条记录数据
  useEffect(() => {
    if (!open) return
    if (mode === 'edit' && initial) {
      form.setFieldsValue({
        name: initial.name,
        brand: initial.brand,
        category: (initial.category || 'other') as ProductCategory,
        description: initial.description,
        style: (initial.style || '真人都市') as ProjectStyle,
        visual_style: (initial.visual_style || '现实') as ProjectVisualStyle,
        price_anchor: initial.price_anchor ?? undefined,
        sku: initial.sku ?? undefined,
        selling_points: initial.selling_points ?? [],
        pain_points_solved: initial.pain_points_solved ?? [],
        catchphrases: initial.catchphrases ?? [],
        competitor_names: initial.competitor_names ?? [],
        health_disclaimer_required: initial.health_disclaimer_required ?? false,
      })
    } else {
      form.resetFields()
      if (prefill) {
        form.setFieldsValue({
          name: prefill.name ?? '',
          brand: prefill.brand,
          category: prefill.category,
          description: prefill.description,
          price_anchor: prefill.price_anchor ?? undefined,
          sku: prefill.sku ?? undefined,
          selling_points: prefill.selling_points,
          pain_points_solved: prefill.pain_points_solved,
          catchphrases: prefill.catchphrases,
          competitor_names: prefill.competitor_names,
          health_disclaimer_required: prefill.health_disclaimer_required,
          style: (prefill.style ?? '真人都市') as ProjectStyle,
          visual_style: (prefill.visual_style ?? '现实') as ProjectVisualStyle,
        })
      }
    }
  }, [mode, initial, prefill, open, form])

  const submitting = createMutation.isPending || updateMutation.isPending

  const handleSubmit = async (values: FormValues) => {
    try {
      // 统一收口字段，避免 undefined 值污染后端 Pydantic 校验
      const payload = {
        name: values.name,
        brand: values.brand ?? '',
        category: (values.category ?? 'other') as ProductCategory,
        description: values.description ?? '',
        style: values.style,
        visual_style: values.visual_style,
        price_anchor: values.price_anchor ?? null,
        sku: values.sku || null,
        selling_points: values.selling_points ?? [],
        pain_points_solved: values.pain_points_solved ?? [],
        catchphrases: values.catchphrases ?? [],
        competitor_names: values.competitor_names ?? [],
        health_disclaimer_required: values.health_disclaimer_required ?? false,
      }
      if (mode === 'create') {
        await createMutation.mutateAsync(payload satisfies ProductCreate)
        message.success('商品创建成功')
      } else if (initial) {
        await updateMutation.mutateAsync({ id: initial.id, body: payload })
        message.success('商品更新成功')
      }
      onSuccess()
    } catch {
      message.error('操作失败，请检查必填项是否完整')
    }
  }

  return (
    <Modal
      title={mode === 'create' ? '新建商品' : '编辑商品'}
      open={open}
      onCancel={onCancel}
      footer={null}
      width={720}
      destroyOnClose
    >
      {mode === 'edit' && initial ? (
        <Tabs
          defaultActiveKey="basic"
          items={[
            {
              key: 'basic',
              label: '基础信息',
              children: (
                <BasicInfoForm
                  form={form}
                  submitting={submitting}
                  onCancel={onCancel}
                  onFinish={handleSubmit}
                  mode={mode}
                />
              ),
            },
            {
              key: 'brand-style-guide',
              label: '品牌话术规范',
              children: <BrandStyleGuideForm productId={initial.id} />,
            },
          ]}
        />
      ) : (
        <BasicInfoForm
          form={form}
          submitting={submitting}
          onCancel={onCancel}
          onFinish={handleSubmit}
          mode={mode}
        />
      )}
    </Modal>
  )
}

/**
 * BasicInfoForm —— 商品基础信息表单（从主组件抽出，便于在 Tabs 与单一入口之间复用）。
 *
 * 接收主组件的 ``form`` 实例，避免 Form 状态分裂；仅承担 UI 渲染与
 * "保存 / 取消" 按钮联动，不持有任何业务副作用。
 */
const BasicInfoForm: React.FC<{
  form: ReturnType<typeof Form.useForm<FormValues>>[0]
  submitting: boolean
  onCancel: () => void
  onFinish: (values: FormValues) => Promise<void> | void
  mode: 'create' | 'edit'
}> = ({ form, submitting, onCancel, onFinish, mode }) => {
  return (
    <Form
      form={form}
      layout="vertical"
      onFinish={onFinish}
      initialValues={{
        visual_style: '现实',
        style: '真人都市',
        category: 'other',
        health_disclaimer_required: false,
      }}
    >
      <Form.Item
        name="name"
        label="商品名称"
        rules={[{ required: true, message: '请输入商品名称' }]}
      >
        <Input placeholder="例如：XYZ 美白精华液 50ml" maxLength={120} />
      </Form.Item>

      <Form.Item name="brand" label="品牌">
        <Input placeholder="例如：CleanLab" maxLength={64} />
      </Form.Item>

      <div className="grid grid-cols-1 sm:grid-cols-2 gap-x-4">
        <Form.Item name="category" label="类目">
          <Select options={CATEGORY_OPTIONS} placeholder="选择品类" />
        </Form.Item>
        <Form.Item name="visual_style" label="视觉风格">
          <Select options={VISUAL_STYLE_OPTIONS} />
        </Form.Item>
      </div>

      <Form.Item
        name="style"
        label="项目题材"
        rules={[{ required: true, message: '请选择项目题材' }]}
      >
        <Select options={PROJECT_STYLE_OPTIONS} />
      </Form.Item>

      <Form.Item name="description" label="商品描述">
        <Input.TextArea rows={3} placeholder="一句话描述商品的核心卖点" />
      </Form.Item>

      <div className="grid grid-cols-1 sm:grid-cols-2 gap-x-4">
        <Form.Item name="price_anchor" label="价格锚点">
          <InputNumber min={0} step={0.01} className="w-full" placeholder="例如：199.00" />
        </Form.Item>
        <Form.Item name="sku" label="SKU">
          <Input placeholder="可选；用于内部对账" maxLength={64} />
        </Form.Item>
      </div>

      <Form.Item name="selling_points" label="核心卖点（多选）">
        <Select mode="tags" placeholder="输入后回车添加" tokenSeparators={[',', '，']} />
      </Form.Item>

      <Form.Item name="pain_points_solved" label="解决的痛点（多选）">
        <Select mode="tags" placeholder="输入后回车添加" tokenSeparators={[',', '，']} />
      </Form.Item>

      <Form.Item name="catchphrases" label="标语 / catchphrase（多选）">
        <Select mode="tags" placeholder="输入后回车添加" tokenSeparators={[',', '，']} />
      </Form.Item>

      <Form.Item name="competitor_names" label="竞品名称（多选）">
        <Select mode="tags" placeholder="输入后回车添加" tokenSeparators={[',', '，']} />
      </Form.Item>

      <Form.Item
        name="health_disclaimer_required"
        label="是否需要健康类免责声明"
        valuePropName="checked"
        tooltip="健康类商品建议开启；合规检查会强制提示"
      >
        <Switch />
      </Form.Item>

      <Form.Item>
        <Space className="w-full justify-end">
          <Button onClick={onCancel}>取消</Button>
          <Button type="primary" htmlType="submit" loading={submitting}>
            {mode === 'create' ? '创建' : '保存'}
          </Button>
        </Space>
      </Form.Item>
    </Form>
  )
}

export default ProductFormModal
