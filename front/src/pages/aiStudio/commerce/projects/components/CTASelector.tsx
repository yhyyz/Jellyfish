/**
 * CTA 模式选择器（CTASelector，Wave 13 P2）。
 *
 * StoryWorkbench P2 选择器矩阵中的 "CTA"（行动召唤）维度：列出系统级
 * CTA 模式（CtaPattern，规模 ≤5 条），用户点击选中后由父组件持有 ID。
 *
 * 与 HookPatternSelector 的区别：CTA 走双轴过滤
 * （`hardness` × `urgency_type`），单条目展示同时含两类 Tag，便于运营
 * 在挑选 CTA 时同时看到"硬度"与"心理驱动类型"两个维度。
 *
 * 设计要点：
 * - 数据加载走 `useCtaPatternList(filter)`，filter 在父组件 unmount 前
 *   保持稳定的 query key（all/all 默认值）。
 * - hardness / urgency_type 选项 zh-CN 硬编码，覆盖后端 builtin
 *   种子定义的全部枚举值。
 * - sample_phrases 不在列表上一次性渲染，避免行高跳动；如需查看由父
 *   组件后续打开详情弹窗（本期 P2 不做）。
 */
import React, { useState } from 'react'
import { Card, List, Select, Space, Spin, Tag, Tooltip } from 'antd'
import { InfoCircleOutlined } from '@ant-design/icons'
import type { CtaPatternRead } from '../../../../../services/generated'
import { useCtaPatternList } from '../pattern_queries'

export interface CTASelectorProps {
  /** 当前选中的 CTA ID；未选中传 null */
  selectedId: string | null
  /** 选中变化回调：传入新选中的 CTA ID */
  onChange: (id: string) => void
}

/**
 * CTA 硬度过滤选项（zh-CN 硬编码）。
 *
 * value 与后端 `hardness` 列保持一致。soft / medium / hard 对应
 * 由弱到强的"催单/催决策"压力级别。
 */
const HARDNESS_OPTIONS = [
  { value: 'soft', label: '软 (soft)' },
  { value: 'medium', label: '中 (medium)' },
  { value: 'hard', label: '硬 (hard)' },
]

/**
 * CTA 心理驱动类型过滤选项（zh-CN 硬编码）。
 *
 * value 与后端 `urgency_type` 列保持一致。覆盖 W11-T2b 5 类种子：
 * 稀缺 / 紧迫 / 社会证明 / 利益驱动 / 风险消除。
 */
const URGENCY_OPTIONS = [
  { value: 'scarcity', label: '稀缺' },
  { value: 'urgency', label: '紧迫' },
  { value: 'social_proof', label: '社会证明' },
  { value: 'benefit', label: '利益' },
  { value: 'risk_removal', label: '风险消除' },
]

/**
 * 把 hardness / urgency_type 映射为 antd Tag 颜色，避免每次渲染都
 * 走 switch；纯展示映射，可在后续根据品牌色调整。
 */
const HARDNESS_COLOR: Record<string, string> = {
  soft: 'green',
  medium: 'orange',
  hard: 'red',
}
const URGENCY_COLOR: Record<string, string> = {
  scarcity: 'volcano',
  urgency: 'magenta',
  social_proof: 'cyan',
  benefit: 'gold',
  risk_removal: 'geekblue',
}

/**
 * CTA 模式选择器主组件。
 *
 * 卡片布局：标题区显示当前匹配条数；过滤行同时提供 hardness 与
 * urgency_type 两个 Select；主体为可滚动列表，单击行选中。
 */
export const CTASelector: React.FC<CTASelectorProps> = ({
  selectedId,
  onChange,
}) => {
  const [hardness, setHardness] = useState<string | undefined>(undefined)
  const [urgencyType, setUrgencyType] = useState<string | undefined>(undefined)
  const { data: patterns, isLoading } = useCtaPatternList({
    hardness,
    urgency_type: urgencyType,
  })

  return (
    <Card
      size="small"
      title={
        <Space>
          <span>CTA 模式选择</span>
          <Tag>{patterns?.length ?? 0}</Tag>
        </Space>
      }
    >
      <Space className="mb-2 flex-wrap">
        <Select
          allowClear
          placeholder="按硬度过滤"
          style={{ width: 140 }}
          options={HARDNESS_OPTIONS}
          value={hardness}
          onChange={(v) => setHardness(v)}
        />
        <Select
          allowClear
          placeholder="按驱动类型过滤"
          style={{ width: 160 }}
          options={URGENCY_OPTIONS}
          value={urgencyType}
          onChange={(v) => setUrgencyType(v)}
        />
      </Space>
      <Spin spinning={isLoading}>
        <List
          dataSource={patterns ?? []}
          locale={{ emptyText: '暂无可用 CTA' }}
          renderItem={(p: CtaPatternRead) => (
            <List.Item
              className={`cursor-pointer ${
                selectedId === p.id ? 'bg-blue-50' : ''
              }`}
              onClick={() => onChange(p.id)}
              actions={[
                <Tooltip key="info" title={p.template_text}>
                  <InfoCircleOutlined />
                </Tooltip>,
              ]}
            >
              <List.Item.Meta
                title={
                  <Space size={4} wrap>
                    <span className="font-medium">{p.name}</span>
                    <Tag color={HARDNESS_COLOR[p.hardness] ?? 'default'}>
                      {p.hardness}
                    </Tag>
                    <Tag color={URGENCY_COLOR[p.urgency_type] ?? 'default'}>
                      {p.urgency_type}
                    </Tag>
                  </Space>
                }
                description={
                  <div className="text-xs text-gray-500">{p.description}</div>
                }
              />
            </List.Item>
          )}
        />
      </Spin>
    </Card>
  )
}

export default CTASelector
