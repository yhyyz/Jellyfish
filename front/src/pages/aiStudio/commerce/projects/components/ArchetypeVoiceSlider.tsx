/**
 * 品牌人格 + 10 维语气调节器（ArchetypeVoiceSlider，Wave 13 P2）。
 *
 * StoryWorkbench P2 选择器矩阵中的"品牌人格"维度：
 * - 顶部 Select 让用户从 12 个 BrandArchetype 中选一个（智者 / 小丑 /
 *   英雄 / ...）。
 * - 下方 10 个 Slider（0-10 分）映射 W11-T3 引入的 ToneDimension 枚举，
 *   每条 Slider 两端展示对偶语义（如"正式↔随意"）。
 *
 * 设计要点：
 * - 完全受控：父组件持有 `selectedArchetype` + `toneGrid`，本组件仅
 *   通过 `onArchetypeChange` / `onToneGridChange` 回传变更。
 * - `toneGrid` 缺失某维时默认 5（中位）；改动单维不重写其他维度，
 *   保持父组件状态最小化。
 * - 10 个维度 zh-CN 硬编码（与 W11-T3 ToneDimension 对齐）。新增维度
 *   需同步：后端 ToneDimension enum + 此处 `TONE_DIMENSIONS` 常量。
 * - 标签布局采用 Form.Item 内含 Space 两端对齐，左端为低分语义、右端
 *   为高分语义，符合"向右滑 = 数值变大"的直觉。
 */
import React from 'react'
import { Card, Divider, Form, Select, Slider, Space } from 'antd'
import type { BrandArchetypeRead } from '../../../../../services/generated'
import { useBrandArchetypeList } from '../pattern_queries'

export interface ArchetypeVoiceSliderProps {
  /** 当前选中的人格原型 ID；未选中传 null */
  selectedArchetype: string | null
  /** 当前 10 维语气取值，缺失维度按 5 视作中位 */
  toneGrid: Record<string, number>
  /** 人格原型选中变化回调 */
  onArchetypeChange: (archetype: string) => void
  /** 语气网格变化回调；本组件每次变更只会修改一个维度的值 */
  onToneGridChange: (grid: Record<string, number>) => void
}

/**
 * 10 维语气网格定义（zh-CN，左低右高对偶语义）。
 *
 * `key` 与后端 ToneDimension 枚举字面量一一对应，写入下游 prompt 上下
 * 文时直接以 `{key: value}` 形式扁平传递。新增/删除维度时务必同步
 * 后端 enum + 本常量。
 */
const TONE_DIMENSIONS: Array<{
  key: string
  leftLabel: string
  rightLabel: string
}> = [
  { key: 'formality', leftLabel: '正式', rightLabel: '随意' },
  { key: 'seriousness', leftLabel: '严肃', rightLabel: '轻松' },
  { key: 'technicality', leftLabel: '技术', rightLabel: '通俗' },
  { key: 'enthusiasm', leftLabel: '克制', rightLabel: '热情' },
  { key: 'humanity', leftLabel: '专业', rightLabel: '亲人' },
  { key: 'activity', leftLabel: '被动', rightLabel: '主动' },
  { key: 'specificity', leftLabel: '抽象', rightLabel: '具体' },
  { key: 'conciseness', leftLabel: '冗长', rightLabel: '简洁' },
  { key: 'conventionality', leftLabel: '常规', rightLabel: '反常' },
  { key: 'safety', leftLabel: '保守', rightLabel: '挑衅' },
]

/**
 * 品牌人格 + 10 维语气调节主组件。
 *
 * 卡片布局：上部为人格 Select；中部为 Divider 分割；下部为 10 个
 * 标签滑块。整体高度由父容器约束，本组件不主动控制 overflow。
 */
export const ArchetypeVoiceSlider: React.FC<ArchetypeVoiceSliderProps> = ({
  selectedArchetype,
  toneGrid,
  onArchetypeChange,
  onToneGridChange,
}) => {
  const { data: archetypes } = useBrandArchetypeList()

  /**
   * 单维 Slider onChange 桥接：合并旧值生成新对象后回传。
   * 仅修改入参 `dimKey` 对应的维度，避免把 0 误当作"未填"清掉。
   */
  const handleDimChange = (dimKey: string, value: number) => {
    onToneGridChange({ ...toneGrid, [dimKey]: value })
  }

  return (
    <Card title="品牌人格 & 语气调节" size="small">
      <Form layout="vertical">
        <Form.Item label="品牌人格 Archetype">
          <Select
            value={selectedArchetype ?? undefined}
            onChange={onArchetypeChange}
            placeholder="选择 12 个 archetype 之一"
            options={(archetypes ?? []).map((a: BrandArchetypeRead) => ({
              value: a.id,
              label: (
                <Space>
                  <span>{a.name_zh}</span>
                  <span className="text-xs text-gray-500">({a.name})</span>
                </Space>
              ),
            }))}
          />
        </Form.Item>

        <Divider orientation="left">10 维语气网格 (0-10)</Divider>

        {TONE_DIMENSIONS.map((dim) => (
          <Form.Item
            key={dim.key}
            label={
              <Space className="w-full justify-between">
                <span>{dim.leftLabel}</span>
                <span>{dim.rightLabel}</span>
              </Space>
            }
          >
            <Slider
              min={0}
              max={10}
              value={toneGrid[dim.key] ?? 5}
              onChange={(v) => handleDimChange(dim.key, v as number)}
              marks={{ 0: '0', 5: '5', 10: '10' }}
            />
          </Form.Item>
        ))}
      </Form>
    </Card>
  )
}

export default ArchetypeVoiceSlider
