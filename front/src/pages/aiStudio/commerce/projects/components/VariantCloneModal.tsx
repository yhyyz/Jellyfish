/**
 * 变体克隆 Modal（W13-T6 / W14-T3 配套）。
 *
 * 使用场景：在 StoryWorkbench 的变体列表里点击「克隆」按钮后弹出，
 * 允许运营/开发在不重写剧本文本的前提下，针对 A/B 关键维度
 * （`archetype` / `hook_pattern_id` / `cta_pattern_id` / `formula_id`）
 * 快速派生新变体。
 *
 * 设计要点：
 * - 所有 override 字段均可选，留空 → 沿用源变体值（后端
 *   `StoryVariantCloneRequest` 语义：`None` 表示"保持源变体"）。
 * - 提交前剥离 `undefined` / 空字符串，避免把 `""` 当作显式覆盖发到后端。
 * - 通过 `open={!!sourceVariant}` 控制显隐，外部传 `null` 即关闭，
 *   保持单一受控来源；`destroyOnClose` 让每次重新打开都拿到干净表单。
 * - 文案完全使用 zh-CN（与本页其它组件一致）。
 */
import React from 'react'
import { Alert, Button, Form, Input, Modal, Space, message } from 'antd'
import type { StoryVariantRead } from '../../../../../services/generated'
import { useCloneStoryVariant } from '../workbench.queries'

type Props = {
  /** 待克隆的源变体；为 null 时 Modal 关闭 */
  sourceVariant: StoryVariantRead | null
  /** 用户取消（点击关闭按钮 / 取消按钮） */
  onCancel: () => void
  /** 克隆成功后回调（通常用于关闭 Modal + 触发外部刷新） */
  onSuccess: () => void
}

/**
 * 表单字段类型；与 `StoryVariantCloneRequest` 字段一一对应。
 *
 * 所有字段均可选，提交前会过滤掉空值。
 */
type CloneFormValues = {
  new_archetype?: string
  new_formula_id?: string
  new_hook_pattern_id?: string
  new_cta_pattern_id?: string
  label?: string
}

/**
 * 变体克隆 Modal 组件。
 */
export const VariantCloneModal: React.FC<Props> = ({ sourceVariant, onCancel, onSuccess }) => {
  const [form] = Form.useForm<CloneFormValues>()
  const cloneMutation = useCloneStoryVariant()

  // 切换源变体（或重新打开）时清空旧表单值，避免上次输入残留。
  React.useEffect(() => {
    if (sourceVariant) {
      form.resetFields()
    }
  }, [sourceVariant, form])

  /**
   * 表单提交：剥离空值后发起克隆。
   *
   * - `undefined` / `''`：视为「不覆盖」，从请求体中删除字段；
   * - 其它非空值：按用户输入透传给后端。
   */
  const handleSubmit = async (values: CloneFormValues) => {
    if (!sourceVariant) return
    const body = Object.fromEntries(
      Object.entries(values).filter(([, v]) => v !== undefined && v !== ''),
    ) as Record<string, string>
    try {
      await cloneMutation.mutateAsync({ variantId: sourceVariant.id, body })
      message.success('变体已克隆')
      onSuccess()
    } catch (e) {
      const errMsg = e instanceof Error ? e.message : '未知错误'
      message.error(`克隆失败：${errMsg}`)
    }
  }

  return (
    <Modal
      title="克隆变体"
      open={!!sourceVariant}
      onCancel={onCancel}
      footer={null}
      destroyOnClose
      width={520}
    >
      <Form<CloneFormValues> form={form} layout="vertical" onFinish={handleSubmit}>
        <Alert
          type="info"
          message={`从源变体 ${sourceVariant?.id?.slice(0, 8) ?? ''} 克隆`}
          description="可选填写下面任一字段以替换原值；留空表示沿用源变体设置。"
          showIcon
          className="mb-3"
        />
        <Form.Item name="new_archetype" label="新 archetype（可选）">
          <Input placeholder="如 Sage / Jester（参考品牌人格列表）" />
        </Form.Item>
        <Form.Item name="new_formula_id" label="新 formula_id（可选）">
          <Input placeholder="如 underdog_triumph" />
        </Form.Item>
        <Form.Item name="new_hook_pattern_id" label="新 hook_pattern_id（可选）">
          <Input placeholder="如 question_hook" />
        </Form.Item>
        <Form.Item name="new_cta_pattern_id" label="新 cta_pattern_id（可选）">
          <Input placeholder="如 scarcity_cta" />
        </Form.Item>
        <Form.Item name="label" label="备注 label（可选）">
          <Input placeholder="如 v2-rebel-strong" maxLength={64} showCount />
        </Form.Item>
        <Form.Item className="mb-0">
          <Space className="w-full justify-end">
            <Button onClick={onCancel}>取消</Button>
            <Button type="primary" htmlType="submit" loading={cloneMutation.isPending}>
              克隆
            </Button>
          </Space>
        </Form.Item>
      </Form>
    </Modal>
  )
}
