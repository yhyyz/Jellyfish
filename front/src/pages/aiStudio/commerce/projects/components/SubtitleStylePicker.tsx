/**
 * SubtitleStylePicker（W20-T3）—— 字幕样式选择器。
 *
 * 提供两种交互入口：
 * 1. **系统模板** tab：列出 W18 已 seed 的 3 个 SubtitleStyle
 *    （DOUYIN_DEFAULT / TIKTOK_VIRAL / REELS_LOWER_THIRD），用户单击
 *    某张卡片即选定该模板，触发 `onChange(style)`。
 * 2. **自定义** tab：嵌 `SubtitleStyleEditor`，用户调字号 / 颜色 /
 *    描边 / 对齐 / 底距，提交时通过 `colorCodec.toAss` 校验颜色合法
 *    性，校验通过才触发 `onChange(override)`。
 *
 * 设计要点：
 * - 数据走 `useSubtitleStyles({ isSystem: true })`，封装在 sibling
 *   `workbench.queries.ts` 的 OpenAPI generated client（AGENTS.md 规
 *   则 #2，禁手写 service）。
 * - 跟 W20-T20-2 `VoicePackPicker` 同款 list-card 模式，但暂不抽公
 *   共组件（留待 W20-T3.5 评估），以免过早抽象损伤可读性
 *   （AGENTS.md 规则 #3）。
 * - 选中态由 `value` prop 决定（受控）；切到自定义 tab 再切回，原
 *   系统模板选中保留——该选中只跟 `value` 比对，不依赖临时 ui
 *   state。
 * - 卡片选中可视化：选中态 `border-blue-500`，未选中 `border-gray-200`，
 *   并通过 `data-selected` 属性给测试断言。
 */
import React, { useState } from 'react'
import { Card, Tabs, Tag, Spin, Empty } from 'antd'
import type { SubtitleStyleRead } from '../../../../../services/generated'
import { useSubtitleStyles } from '../workbench.queries'
import {
  SubtitleStyleEditor,
  type SubtitleStyleOverride,
} from './SubtitleStyleEditor'
import { fromAss } from './_subtitle/colorCodec'

/**
 * 选中值类型：可能是后端拉来的 system 模板，也可能是编辑器吐出的
 * override 载荷。
 */
export type SubtitleStyleValue = SubtitleStyleRead | SubtitleStyleOverride

export interface SubtitleStylePickerProps {
  /**
   * 当前选中的字幕样式。
   * - 传 `SubtitleStyleRead` 表示选中某 system 模板（按 `id` 比对）
   * - 传 `SubtitleStyleOverride` 表示当前是 custom override
   * - 不传表示尚未选中
   */
  value?: SubtitleStyleValue
  /** 选中变化回调（系统模板 click / 自定义 submit 都走它） */
  onChange: (style: SubtitleStyleValue) => void
}

/**
 * 类型守卫：判断当前 value 是否为后端 `SubtitleStyleRead`。
 *
 * 后端 schema 的强制字段 `id` / `is_system` 在 override 上不存在，可
 * 以用作判别。
 */
const isSystemStyleValue = (
  v: SubtitleStyleValue | undefined,
): v is SubtitleStyleRead => {
  if (!v) return false
  return typeof (v as SubtitleStyleRead).id === 'string'
}

/**
 * 字幕样式预览块（卡片内迷你示例）。
 *
 * 把 ASS 颜色字面量转回 web hex 后注入 `style`，让用户在选择前能直
 * 观看到字号 / 主色 / 描边大致效果。预览仅取主要视觉变量
 * （font_family / font_size / primary_colour / outline + outline_colour），
 * 完全保真渲染交给后续 ASS 渲染管线。
 */
const StylePreviewBlock: React.FC<{ style: SubtitleStyleRead }> = ({
  style,
}) => {
  // toAss 严格校验，但 fromAss 这里做容错：seed 数据格式异常不应让 UI 整张卡崩
  let primary = '#FFFFFF'
  let outline = '#000000'
  try {
    primary = fromAss(style.primary_colour)
  } catch {
    /* keep default */
  }
  try {
    outline = fromAss(style.outline_colour)
  } catch {
    /* keep default */
  }

  return (
    <div
      className="flex h-16 items-center justify-center rounded bg-gray-900 px-2"
      style={{
        fontFamily: style.font_family,
        // 卡片预览缩放：font_size 是基于 PlayResY=1920 的脚本像素，
        // 直接用会撑爆卡片，按 1/3 缩放给个体感
        fontSize: Math.max(12, Math.round(style.font_size / 3)),
        color: primary,
        fontWeight: style.bold ? 700 : 400,
        fontStyle: style.italic ? 'italic' : 'normal',
        WebkitTextStroke:
          style.outline > 0 ? `${style.outline / 2}px ${outline}` : undefined,
      }}
    >
      示例字幕预览
    </div>
  )
}

/**
 * 字幕样式选择器主组件。
 *
 * Tabs 模式 + 受控 selected：
 * - 「系统模板」tab：3 列网格，每张卡片含名称 / 平台 tag / mini preview
 * - 「自定义」tab：嵌 SubtitleStyleEditor
 */
export const SubtitleStylePicker: React.FC<SubtitleStylePickerProps> = ({
  value,
  onChange,
}) => {
  const [activeTab, setActiveTab] = useState<'system' | 'custom'>('system')
  const { data: systemStyles, isLoading } = useSubtitleStyles({ isSystem: true })

  // 选中 system 模板的 ID（仅当 value 是 SubtitleStyleRead 时有值）
  const selectedSystemId = isSystemStyleValue(value) ? value.id : null

  return (
    <Card size="small" title="字幕样式">
      <Tabs
        activeKey={activeTab}
        onChange={(k) => setActiveTab(k as 'system' | 'custom')}
        items={[
          {
            key: 'system',
            label: '系统模板',
            children: (
              <Spin spinning={isLoading}>
                {systemStyles && systemStyles.length > 0 ? (
                  <div className="grid grid-cols-1 gap-3 md:grid-cols-3">
                    {systemStyles.map((style: SubtitleStyleRead) => {
                      const selected = selectedSystemId === style.id
                      return (
                        <button
                          key={style.id}
                          type="button"
                          data-testid={`subtitle-style-card-${style.id}`}
                          data-selected={selected ? 'true' : 'false'}
                          onClick={() => onChange(style)}
                          className={`flex flex-col gap-2 rounded border-2 p-3 text-left transition ${
                            selected
                              ? 'border-blue-500 bg-blue-50'
                              : 'border-gray-200 hover:border-gray-400'
                          }`}
                        >
                          <div className="flex items-center justify-between">
                            <span className="font-medium">{style.name}</span>
                            <Tag color="blue">{style.format.toUpperCase()}</Tag>
                          </div>
                          <StylePreviewBlock style={style} />
                          {style.description && (
                            <div className="text-xs text-gray-500">
                              {style.description}
                            </div>
                          )}
                        </button>
                      )
                    })}
                  </div>
                ) : (
                  <Empty description="暂无可用系统字幕样式" />
                )}
              </Spin>
            ),
          },
          {
            key: 'custom',
            label: '自定义',
            children: (
              <SubtitleStyleEditor
                onSubmit={(override) => onChange(override)}
              />
            ),
          },
        ]}
      />
    </Card>
  )
}

export default SubtitleStylePicker
