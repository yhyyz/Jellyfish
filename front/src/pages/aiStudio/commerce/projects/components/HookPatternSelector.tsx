/**
 * 钩子模式选择器（HookPatternSelector，Wave 13 P2）。
 *
 * StoryWorkbench P2 选择器矩阵中的"钩子"维度：列出系统级钩子模式
 * （HookPattern，规模 ≤10 条），用户点击选中后由父组件持有 ID。
 *
 * 设计要点：
 * - 数据加载走 `useHookPatternList(filterType)`，由 sibling
 *   `pattern_queries.ts` 维护缓存。
 * - 顶部 `pattern_type` 过滤器 zh-CN 硬编码，覆盖后端 builtin 种子的
 *   10 类钩子（question / conflict / contrast / numerical / curiosity /
 *   shock / relatable / dialogue / visual / pov）。
 * - 单卡片以选中态高亮（蓝色背景），右侧 Info 图标 hover 展示心理学
 *   原理 tooltip，避免一次性铺开过多说明文本。
 * - 受控接口仅暴露 `selectedId` + `onChange`，不在选择器内做副作用，
 *   选中后的下游业务（如塞进 prompt 上下文）留给父组件 StoryWorkbench
 *   处理。
 */
import React, { useState } from 'react'
import { Card, List, Select, Space, Spin, Tag, Tooltip } from 'antd'
import { InfoCircleOutlined } from '@ant-design/icons'
import type { HookPatternRead } from '../../../../../services/generated'
import { useHookPatternList } from '../pattern_queries'

export interface HookPatternSelectorProps {
  /** 当前选中的钩子 ID；未选中传 null */
  selectedId: string | null
  /** 选中变化回调：传入新选中的钩子 ID */
  onChange: (id: string) => void
}

/**
 * 钩子类型过滤选项（zh-CN 硬编码，覆盖 W11-T2b 10 类种子）。
 *
 * value 与后端 `pattern_type` 列保持一一对应，避免在 service 端做
 * label 翻译。新增钩子类型时需同步：后端 builtin_hook_patterns +
 * 此处选项数组。
 */
const HOOK_TYPE_OPTIONS = [
  { value: 'question', label: '问句' },
  { value: 'conflict', label: '冲突' },
  { value: 'contrast', label: '对比' },
  { value: 'numerical', label: '数字' },
  { value: 'curiosity', label: '好奇' },
  { value: 'shock', label: '震惊' },
  { value: 'relatable', label: '共鸣' },
  { value: 'dialogue', label: '对白' },
  { value: 'visual', label: '视觉' },
  { value: 'pov', label: 'POV' },
]

/**
 * 钩子模式选择器主组件。
 *
 * 卡片布局：标题区显示当前匹配条数；过滤行允许按 pattern_type 收窄；
 * 主体为可滚动的钩子列表，单击行选中。
 */
export const HookPatternSelector: React.FC<HookPatternSelectorProps> = ({
  selectedId,
  onChange,
}) => {
  const [filterType, setFilterType] = useState<string | undefined>(undefined)
  const { data: patterns, isLoading } = useHookPatternList(filterType)

  return (
    <Card
      size="small"
      title={
        <Space>
          <span>钩子模式选择</span>
          <Tag>{patterns?.length ?? 0}</Tag>
        </Space>
      }
    >
      <Space className="mb-2 flex-wrap">
        <Select
          allowClear
          placeholder="按类型过滤"
          style={{ width: 140 }}
          options={HOOK_TYPE_OPTIONS}
          value={filterType}
          onChange={(v) => setFilterType(v)}
        />
      </Space>
      <Spin spinning={isLoading}>
        <List
          dataSource={patterns ?? []}
          locale={{ emptyText: '暂无可用钩子' }}
          renderItem={(p: HookPatternRead) => (
            <List.Item
              className={`cursor-pointer ${
                selectedId === p.id ? 'bg-blue-50' : ''
              }`}
              onClick={() => onChange(p.id)}
              actions={[
                <Tooltip key="info" title={p.psychology}>
                  <InfoCircleOutlined />
                </Tooltip>,
              ]}
            >
              <List.Item.Meta
                title={
                  <Space size={4} wrap>
                    <span className="font-medium">{p.name}</span>
                    <Tag color="blue">{p.pattern_type}</Tag>
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

export default HookPatternSelector
