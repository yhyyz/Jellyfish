/**
 * 镜头时间轴条（ShotTimelineStrip）。
 *
 * StoryWorkbench 底部条带：把当前激活变体的镜头分解以横向滚动卡片
 * 形式渲染，每张卡片宽度按 `duration_sec` 等比缩放，便于直观看到
 * 哪些镜头时长更长、哪些是品牌口播 / Hero 焦点。
 *
 * P1 限定：仅做展示与简单着色，不支持拖拽改时长（P2）。
 *
 * 设计要点：
 * - 镜头宽度策略：`max(80, duration_sec * 8)`，下限保证短镜头仍可读，
 *   线性缩放保证长镜头视觉占比更大。
 * - 没有镜头时直接 return null，避免渲染空 Card 占据底部空间。
 */
import React from 'react'
import { Card, Tag } from 'antd'
import type { StoryVariantRead } from '../../../../../services/generated'

export interface ShotTimelineStripProps {
  /** 当前激活变体；为空或没镜头时不渲染 */
  variant: StoryVariantRead | null
}

/**
 * 单镜头精简结构（与 ScriptEditor 一致）；可选字段全部用 ?? 兜底。
 */
type StripShot = {
  duration_sec?: number
  is_brand_mention?: boolean
  product_focus_level?: 'none' | 'background' | 'foreground' | 'hero' | string
}

type StripBreakdown = {
  shots?: StripShot[]
}

/**
 * 镜头时间轴条主组件。
 */
export const ShotTimelineStrip: React.FC<ShotTimelineStripProps> = ({ variant }) => {
  const breakdown = (variant?.script_breakdown ?? null) as StripBreakdown | null
  const shots = breakdown?.shots ?? []
  if (!shots.length) return null

  return (
    <Card size="small" className="mt-2" title="镜头时间轴">
      <div className="flex gap-2 overflow-x-auto pb-2">
        {shots.map((shot, i) => {
          const dur = shot.duration_sec ?? 3
          const width = Math.max(80, dur * 8)
          return (
            <div
              key={i}
              className="flex-shrink-0 rounded border border-gray-200 p-2 min-w-[80px]"
              style={{ width: `${width}px` }}
            >
              <div className="text-xs font-medium">Shot {i + 1}</div>
              <div className="text-xs text-gray-500">{dur}s</div>
              {shot.is_brand_mention ? (
                <Tag color="purple" className="mt-1 text-[11px]">
                  品牌
                </Tag>
              ) : null}
              {shot.product_focus_level === 'hero' ? (
                <Tag color="gold" className="mt-1 text-[11px]">
                  Hero
                </Tag>
              ) : null}
            </div>
          )
        })}
      </div>
    </Card>
  )
}

export default ShotTimelineStrip
