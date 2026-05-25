/**
 * 商品 URL/文本提取弹窗。
 *
 * P1 范围：
 * - 提交一段 raw_text（商品页 URL 或粘贴的描述文本）；
 * - 入队 `product_info_extract` 异步任务，返回 task_id；
 * - 不做轮询（P2 才补任务进度面板），仅以 message.success 提示用户
 *   稍后回到商品库刷新列表查看结果。
 *
 * 与 ProductFormModal 的关系：
 * - 当前 P1 仅“提交即关闭”，不会把抽取到的字段直接回填到表单；
 * - `onExtracted` 回调留作 P2 引入轮询完成后的“一键预填”入口。
 */
import React, { useState } from 'react'
import { Alert, Button, Input, Modal, message } from 'antd'
import type { ProductCreate } from '../../../../services/generated'
import { useExtractProductFromText } from './queries'

type Props = {
  open: boolean
  onCancel: () => void
  /** P2 预留：在轮询到结果后用抽取出的字段预填创建表单 */
  onExtracted?: (data: Partial<ProductCreate>) => void
}

/**
 * 渲染“从 URL/文本提取商品”弹窗。
 *
 * 行为：
 * - 文本框非空时启用“提交提取”按钮；
 * - 点击提交后调用 `useExtractProductFromText` 入队任务；
 * - 成功后清空 textarea 并关闭弹窗，提示 task_id 前 8 位以便排查。
 */
export const URLExtractModal: React.FC<Props> = ({ open, onCancel }) => {
  const [text, setText] = useState('')
  const extractMutation = useExtractProductFromText()

  const handleExtract = async () => {
    const trimmed = text.trim()
    if (!trimmed) {
      message.warning('请粘贴 URL 或商品描述文本')
      return
    }
    try {
      const res = await extractMutation.mutateAsync(trimmed)
      const shortId = res.task_id ? res.task_id.slice(0, 8) : '—'
      message.success(`提取任务已提交（task_id=${shortId}），请稍后刷新商品库查看`)
      setText('')
      onCancel()
    } catch {
      message.error('提取请求失败')
    }
  }

  const handleCancel = () => {
    setText('')
    onCancel()
  }

  return (
    <Modal
      title="从 URL/文本提取商品"
      open={open}
      onCancel={handleCancel}
      width={520}
      footer={[
        <Button key="cancel" onClick={handleCancel}>
          取消
        </Button>,
        <Button
          key="submit"
          type="primary"
          loading={extractMutation.isPending}
          onClick={handleExtract}
        >
          提交提取
        </Button>,
      ]}
    >
      <Alert
        message="粘贴商品页 URL 或商品描述文本，AI 会在后台异步提取结构化字段"
        description="P1 阶段仅入队任务并返回 task_id；提取完成后回到商品库点击“刷新”即可查看新增条目。"
        type="info"
        showIcon
        className="mb-3"
      />
      <Input.TextArea
        rows={6}
        value={text}
        onChange={(e) => setText(e.target.value)}
        placeholder="例如：https://item.example.com/123 或粘贴商品详情文本……"
        maxLength={4000}
        showCount
      />
    </Modal>
  )
}

export default URLExtractModal
