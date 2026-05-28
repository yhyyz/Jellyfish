/**
 * 投放效果手动录入表单（W22-T1，P4 Wave A 1/6）。
 *
 * 用于在分镜工作台「Outcomes」tab 内对某个变体录入一条新的 StoryOutcome：
 *
 * - 字段使用本地 useState 受控（与 SubtitleStyleEditor 相同模式），便于
 *   在测试中通过 InputNumber 的 `value` prop 同步更新；同时避免 antd
 *   Form 的 name binding 在 jsdom 下与 fireEvent 难以协同。
 * - 校验规则镜像后端 schema：``gmv ≥ 0``、``completion_rate ∈ [0, 1]``、
 *   ``recorded_at ≤ now``；任一规则失败时显示行内错误，不调后端。
 * - 提交时调用 `useCreateOutcome` mutation；mutation pending 期间提交按
 *   钮 loading + disabled，杜绝重复提交。
 */
import React, { useState } from 'react'
import { Button, DatePicker, Form, Input, InputNumber, Select, Space, message } from 'antd'
import dayjs, { Dayjs } from 'dayjs'
import type { StoryOutcomeCreate } from '../../../../../services/commerce/outcomeApi'
import { useCreateOutcome } from '../outcome.queries'

const PLATFORM_OPTIONS: Array<{ value: string; label: string }> = [
  { value: 'douyin', label: '抖音' },
  { value: 'kuaishou', label: '快手' },
  { value: 'xiaohongshu', label: '小红书' },
  { value: 'youtube', label: 'YouTube' },
  { value: 'tiktok', label: 'TikTok' },
]

interface OutcomeFormState {
  platform: string
  plays: number
  completion_rate_3s: number | null
  completion_rate_full: number | null
  interactions: number
  cart_clicks: number
  orders: number
  gmv: number
  notes: string
  recorded_at: Dayjs
}

interface OutcomeEntryFormProps {
  variantId: string
  onSuccess?: () => void
}

function makeDefaults(): OutcomeFormState {
  return {
    platform: 'douyin',
    plays: 0,
    completion_rate_3s: null,
    completion_rate_full: null,
    interactions: 0,
    cart_clicks: 0,
    orders: 0,
    gmv: 0,
    notes: '',
    recorded_at: dayjs(),
  }
}

const validators = {
  plays: (v: number): string | null => (v < 0 ? '播放量必须 ≥ 0' : null),
  rate: (v: number | null, name: string): string | null =>
    v == null ? null : v < 0 || v > 1 ? `${name} 必须在 [0, 1]` : null,
  gmv: (v: number): string | null => (v < 0 ? 'GMV 必须 ≥ 0' : null),
  recordedAt: (v: Dayjs): string | null =>
    v.isAfter(dayjs().add(1, 'minute')) ? '记录时点不能晚于当前时间' : null,
}

export const OutcomeEntryForm: React.FC<OutcomeEntryFormProps> = ({ variantId, onSuccess }) => {
  const [state, setState] = useState<OutcomeFormState>(makeDefaults)
  const [errors, setErrors] = useState<Partial<Record<keyof OutcomeFormState, string>>>({})
  const createMutation = useCreateOutcome()
  const isPending = createMutation.isPending

  const update = <K extends keyof OutcomeFormState>(key: K, value: OutcomeFormState[K]): void => {
    setState((prev) => ({ ...prev, [key]: value }))
    if (errors[key]) setErrors((prev) => ({ ...prev, [key]: undefined }))
  }

  const handleSubmit = async (): Promise<void> => {
    const next: Partial<Record<keyof OutcomeFormState, string>> = {}
    const playsErr = validators.plays(state.plays)
    if (playsErr) next.plays = playsErr
    const rate3sErr = validators.rate(state.completion_rate_3s, 'completion_rate_3s')
    if (rate3sErr) next.completion_rate_3s = rate3sErr
    const rateFullErr = validators.rate(state.completion_rate_full, 'completion_rate_full')
    if (rateFullErr) next.completion_rate_full = rateFullErr
    const gmvErr = validators.gmv(state.gmv)
    if (gmvErr) next.gmv = gmvErr
    const tsErr = validators.recordedAt(state.recorded_at)
    if (tsErr) next.recorded_at = tsErr

    if (Object.keys(next).length > 0) {
      setErrors(next)
      return
    }
    setErrors({})

    const payload: StoryOutcomeCreate = {
      variant_id: variantId,
      platform: state.platform as StoryOutcomeCreate['platform'],
      plays: state.plays,
      completion_rate_3s: state.completion_rate_3s,
      completion_rate_full: state.completion_rate_full,
      interactions: state.interactions,
      cart_clicks: state.cart_clicks,
      orders: state.orders,
      gmv: state.gmv,
      notes: state.notes,
      raw_payload: {},
      recorded_at: state.recorded_at.toISOString(),
    }
    try {
      await createMutation.mutateAsync(payload)
      message.success('已录入投放效果')
      setState(makeDefaults())
      onSuccess?.()
    } catch (e) {
      const errMsg = e instanceof Error ? e.message : '未知错误'
      message.error(`录入失败：${errMsg}`)
    }
  }

  return (
    <Form layout="vertical" component="div" data-testid="outcome-entry-form">
      <Space size={12} wrap>
        <Form.Item label="平台">
          <Select
            options={PLATFORM_OPTIONS}
            value={state.platform}
            onChange={(v) => update('platform', v)}
            style={{ width: 140 }}
          />
        </Form.Item>
        <Form.Item
          label="记录时点"
          validateStatus={errors.recorded_at ? 'error' : undefined}
          help={errors.recorded_at}
        >
          <DatePicker
            showTime
            value={state.recorded_at}
            onChange={(v) => update('recorded_at', v ?? dayjs())}
            disabledDate={(current) => current && current.isAfter(dayjs())}
            style={{ width: 220 }}
          />
        </Form.Item>
      </Space>

      <Space size={12} wrap>
        <Form.Item
          label="播放量"
          validateStatus={errors.plays ? 'error' : undefined}
          help={errors.plays}
        >
          <div data-testid="outcome-form-plays">
            <InputNumber
              min={0}
              value={state.plays}
              onChange={(v) => update('plays', typeof v === 'number' ? v : 0)}
              style={{ width: 160 }}
            />
          </div>
        </Form.Item>
        <Form.Item
          label="3 秒完播率"
          validateStatus={errors.completion_rate_3s ? 'error' : undefined}
          help={errors.completion_rate_3s}
        >
          <div data-testid="outcome-form-completion-rate-3s">
            <InputNumber
              min={0}
              max={1}
              step={0.01}
              value={state.completion_rate_3s ?? undefined}
              onChange={(v) =>
                update('completion_rate_3s', typeof v === 'number' ? v : null)
              }
              style={{ width: 160 }}
            />
          </div>
        </Form.Item>
        <Form.Item
          label="完整完播率"
          validateStatus={errors.completion_rate_full ? 'error' : undefined}
          help={errors.completion_rate_full}
        >
          <div data-testid="outcome-form-completion-rate-full">
            <InputNumber
              min={0}
              max={1}
              step={0.01}
              value={state.completion_rate_full ?? undefined}
              onChange={(v) =>
                update('completion_rate_full', typeof v === 'number' ? v : null)
              }
              style={{ width: 160 }}
            />
          </div>
        </Form.Item>
      </Space>

      <Space size={12} wrap>
        <Form.Item label="互动量">
          <div data-testid="outcome-form-interactions">
            <InputNumber
              min={0}
              value={state.interactions}
              onChange={(v) => update('interactions', typeof v === 'number' ? v : 0)}
              style={{ width: 140 }}
            />
          </div>
        </Form.Item>
        <Form.Item label="加购点击">
          <div data-testid="outcome-form-cart-clicks">
            <InputNumber
              min={0}
              value={state.cart_clicks}
              onChange={(v) => update('cart_clicks', typeof v === 'number' ? v : 0)}
              style={{ width: 140 }}
            />
          </div>
        </Form.Item>
        <Form.Item label="订单数">
          <div data-testid="outcome-form-orders">
            <InputNumber
              min={0}
              value={state.orders}
              onChange={(v) => update('orders', typeof v === 'number' ? v : 0)}
              style={{ width: 140 }}
            />
          </div>
        </Form.Item>
        <Form.Item
          label="GMV"
          validateStatus={errors.gmv ? 'error' : undefined}
          help={errors.gmv}
        >
          <div data-testid="outcome-form-gmv">
            <InputNumber
              step={0.01}
              value={state.gmv}
              onChange={(v) => update('gmv', typeof v === 'number' ? v : 0)}
              style={{ width: 160 }}
            />
          </div>
        </Form.Item>
      </Space>

      <Form.Item label="备注">
        <Input.TextArea
          rows={2}
          maxLength={500}
          value={state.notes}
          onChange={(e) => update('notes', e.target.value)}
          data-testid="outcome-form-notes"
        />
      </Form.Item>

      <Form.Item>
        <Button
          type="primary"
          loading={isPending}
          disabled={isPending}
          onClick={() => void handleSubmit()}
          data-testid="outcome-form-submit"
        >
          保存
        </Button>
      </Form.Item>
    </Form>
  )
}

export default OutcomeEntryForm
