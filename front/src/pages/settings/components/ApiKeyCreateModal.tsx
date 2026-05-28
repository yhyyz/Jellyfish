/**
 * ApiKeyCreateModal — 创建 API key 的两阶段 Modal（W24-T5，P4 Wave B 7/11）。
 *
 * 行为分两阶段：
 *
 *   stage = 'form'：渲染 antd Form 收集 description / daily_limit /
 *     monthly_limit / rate_per_minute 四个字段；提交时调用父级
 *     ``onCreate`` 并把返回的 ``ApiKeyCreated`` 通过 ``setCreated`` 切到
 *     第二阶段。
 *
 *   stage = 'reveal'：用 antd ``Result`` 展示一次性 plaintext，附复制按
 *     钮。关闭按钮触发 ``Modal.confirm`` 二次提示「已妥善保存？」，符
 *     合 "plaintext 仅本次返回" 的安全语义；用户确认后才允许关闭。
 *
 * 关键不变量：
 *   - plaintext 不写入 react-query 缓存；只通过本地 state 暂存。
 *   - 关闭后 state 清空，再次打开必须重新触发 create 才会再次出现明文。
 *   - 复制按钮使用 ``navigator.clipboard.writeText`` 优先，缺失时 fallback
 *     到 ``document.execCommand('copy')``，兼容 jsdom 测试环境。
 *
 * 不直接耦合 react-query：父组件（ApiKeysPage）持有 mutation，本组件
 * 只接受异步 ``onCreate`` 回调，便于单测注入 mock。
 */
import React, { useState } from 'react'
import {
  Alert,
  Button,
  Checkbox,
  Form,
  Input,
  InputNumber,
  Modal,
  Result,
  Space,
  Typography,
  message,
} from 'antd'
import { CopyOutlined } from '@ant-design/icons'
import type {
  ApiKeyCreateRequest,
  ApiKeyCreated,
} from '../../../services/generated'

const { Paragraph, Text } = Typography

/**
 * 安全复制到剪贴板：优先 navigator.clipboard，缺失时 fallback。
 * 单独抽函数便于在测试环境中替换实现。
 */
export async function copyToClipboard(text: string): Promise<boolean> {
  if (typeof navigator !== 'undefined' && navigator.clipboard?.writeText) {
    try {
      await navigator.clipboard.writeText(text)
      return true
    } catch {
      // fallthrough 到 execCommand
    }
  }
  try {
    const ta = document.createElement('textarea')
    ta.value = text
    ta.setAttribute('readonly', '')
    ta.style.position = 'absolute'
    ta.style.left = '-9999px'
    document.body.appendChild(ta)
    ta.select()
    const ok = document.execCommand('copy')
    document.body.removeChild(ta)
    return ok
  } catch {
    return false
  }
}

export interface ApiKeyCreateModalProps {
  /** Modal 是否打开 */
  open: boolean
  /** 用户主动取消 / 关闭（仅在 form 阶段或确认后生效） */
  onCancel: () => void
  /** 创建成功后通知父级刷新列表 */
  onCreated: (created: ApiKeyCreated) => void
  /** 异步创建函数；外部注入便于测试 */
  onCreate: (req: ApiKeyCreateRequest) => Promise<ApiKeyCreated>
}

type Stage = 'form' | 'reveal'

export const ApiKeyCreateModal: React.FC<ApiKeyCreateModalProps> = ({
  open,
  onCancel,
  onCreated,
  onCreate,
}) => {
  const [form] = Form.useForm<ApiKeyCreateRequest>()
  const [stage, setStage] = useState<Stage>('form')
  const [submitting, setSubmitting] = useState(false)
  const [created, setCreated] = useState<ApiKeyCreated | null>(null)
  const [savedAck, setSavedAck] = useState(false)

  // eslint-disable-next-line no-console
  console.log('[ApiKeyCreateModal] render: stage=', stage, 'created=', !!created, 'open=', open)

  const resetState = () => {
    form.resetFields()
    setStage('form')
    setCreated(null)
    setSubmitting(false)
    setSavedAck(false)
  }

  const handleSubmit = async () => {
    try {
      const values = await form.validateFields()
      setSubmitting(true)
      const result = await onCreate({
        description: values.description ?? '',
        daily_limit: values.daily_limit ?? 0,
        monthly_limit: values.monthly_limit ?? 0,
        rate_per_minute: values.rate_per_minute ?? 0,
      })
      setCreated(result)
      setStage('reveal')
      onCreated(result)
    } catch (err) {
      if (err && typeof err === 'object' && 'errorFields' in err) {
        return
      }
      message.error((err as Error)?.message ?? '创建失败')
    } finally {
      setSubmitting(false)
    }
  }

  /**
   * reveal 阶段确认关闭：用户必须先勾选「我已妥善保存」才能点击关闭
   * 按钮。这是 plaintext 一次性策略的最后一道闸门——避免管理员误关
   * 弹窗导致明文丢失。改用 Checkbox + disabled Button 显式 gate 而非
   * Modal.confirm / Popconfirm：在 jsdom 测试环境下 portal-based 二次
   * 确认控件的事件链不可靠，inline gate 走标准 React 状态机更可测。
   */
  const handleConfirmClose = () => {
    // eslint-disable-next-line no-console
    console.log('[ApiKeyCreateModal] handleConfirmClose fired, stage=', stage, 'created=', !!created)
    resetState()
    onCancel()
    // eslint-disable-next-line no-console
    console.log('[ApiKeyCreateModal] handleConfirmClose done')
  }

  const handleCopy = async () => {
    if (!created) return
    const ok = await copyToClipboard(created.plaintext_key)
    if (ok) {
      message.success('已复制到剪贴板')
    } else {
      message.error('复制失败，请手动选中文本')
    }
  }

  /**
   * antd Modal 的 onCancel：form 阶段直接关闭；reveal 阶段忽略 ESC /
   * 蒙层关闭，强制用户走「勾选已保存 + 关闭按钮」显式路径。
   */
  const handleModalCancel = () => {
    if (stage === 'reveal') {
      return
    }
    resetState()
    onCancel()
  }

  return (
    <Modal
      title={stage === 'form' ? '创建 API Key' : 'API Key 创建成功'}
      open={open}
      onCancel={handleModalCancel}
      maskClosable={stage === 'form'}
      keyboard={stage === 'form'}
      destroyOnClose
      footer={
        stage === 'form'
          ? [
              <Button key="cancel" onClick={handleModalCancel} disabled={submitting}>
                取消
              </Button>,
              <Button
                key="submit"
                type="primary"
                loading={submitting}
                onClick={handleSubmit}
                data-testid="create-api-key-submit"
              >
                创建
              </Button>,
            ]
          : [
              <span key="ack" data-testid="saved-ack-checkbox" style={{ marginRight: 12 }}>
                <Checkbox
                  checked={savedAck}
                  onChange={(e) => setSavedAck(e.target.checked)}
                >
                  我已妥善保存
                </Checkbox>
              </span>,
              <button
                key="close"
                type="button"
                disabled={!savedAck}
                onClick={handleConfirmClose}
                data-testid="reveal-close-btn"
                className="ant-btn ant-btn-primary ant-btn-dangerous"
                style={{
                  background: savedAck ? '#ff4d4f' : '#f5f5f5',
                  color: savedAck ? '#fff' : '#bfbfbf',
                  border: 'none',
                  padding: '4px 16px',
                  borderRadius: 4,
                  cursor: savedAck ? 'pointer' : 'not-allowed',
                  height: 32,
                }}
              >
                关闭
              </button>,
            ]
      }
      width={560}
    >
      {open && stage === 'form' && (
        <Form<ApiKeyCreateRequest>
          form={form}
          layout="vertical"
          initialValues={{
            description: '',
            daily_limit: 1000,
            monthly_limit: 30000,
            rate_per_minute: 60,
          }}
        >
          <Form.Item
            label="备注"
            name="description"
            tooltip="便于在管理面板辨认归属，例如 'official-bot'"
          >
            <Input maxLength={120} placeholder="（可选）此 key 用途" />
          </Form.Item>
          <Form.Item
            label="日调用上限"
            name="daily_limit"
            tooltip="0 表示禁用调用，请按业务预估填写"
            rules={[{ required: true, message: '请填写日上限' }]}
          >
            <InputNumber min={0} className="w-full" />
          </Form.Item>
          <Form.Item
            label="月调用上限"
            name="monthly_limit"
            tooltip="0 表示禁用调用"
            rules={[{ required: true, message: '请填写月上限' }]}
          >
            <InputNumber min={0} className="w-full" />
          </Form.Item>
          <Form.Item
            label="每分钟请求上限"
            name="rate_per_minute"
            tooltip="作为限流参数，由后续中间件消费"
            rules={[{ required: true, message: '请填写 RPM' }]}
          >
            <InputNumber min={0} className="w-full" />
          </Form.Item>
        </Form>
      )}

      {open && stage === 'reveal' && created && (
        <div data-testid="api-key-reveal">
          <Result
            status="success"
            title="API Key 已生成"
            subTitle="该明文仅本次显示，请妥善保存；后端不存储明文。"
          />
          <Alert
            type="warning"
            showIcon
            message="保存到密码管理器或部署密钥仓后再关闭弹窗。"
            className="mb-3"
          />
          <Space direction="vertical" size="small" className="w-full">
            <Text strong>Plaintext API Key</Text>
            <Paragraph
              code
              copyable={false}
              data-testid="plaintext-key"
              style={{
                background: '#fafafa',
                padding: '8px 12px',
                borderRadius: 4,
                wordBreak: 'break-all',
                fontFamily: 'monospace',
              }}
            >
              {created.plaintext_key}
            </Paragraph>
            <Button
              icon={<CopyOutlined />}
              onClick={handleCopy}
              data-testid="copy-plaintext-btn"
            >
              复制明文
            </Button>
            <Text type="secondary" style={{ marginTop: 8 }}>
              Hash（管理面板可见）：
              <Text code>{created.api_key_hash}</Text>
            </Text>
          </Space>
        </div>
      )}
    </Modal>
  )
}

export default ApiKeyCreateModal
