/**
 * 脚本展示器（ScriptEditor）。
 *
 * StoryWorkbench 中部主区：渲染当前激活变体（StoryVariant）的剧本结构。
 * P1 仅做只读展示，包含开场钩子、镜头分解、结尾 CTA 三段式；
 * P2 将引入分镜级的内联编辑（行内修改对白 / 旁白 / 时长）。
 *
 * 数据契约：
 * - `variant.script_breakdown` 是后端写入的 `Record<string, any>`，
 *   严格说不可控。本组件以 `as` cast + 安全访问的方式做防御读取，
 *   单字段缺失不会破坏整体渲染。
 *
 * 视觉策略：
 * - 顶部用 Tag 表达：版本号 / 状态 / 是否冠军 / 总时长 / 镜头数 / 合规分数。
 * - 合规分数按 80 / 60 阈值切换 green / orange / red 颜色。
 * - 镜头列表逐项渲染：编号 / 时长 / 景别 / 品牌口播 / 爆点 / 商品出现等元数据。
 */
import React from 'react'
import { Card, Empty, Tag, Space, List, Divider } from 'antd'
import type { StoryVariantRead } from '../../../../../services/generated'

export interface ScriptEditorProps {
  /** 当前激活的变体；为空时显示 Empty 占位 */
  variant: StoryVariantRead | null
  /** P1 阶段固定为 true（只读）；P2 才接入内联编辑 */
  readOnly: boolean
}

/**
 * 单个镜头的最小结构（与后端 `app/services/commerce/story_script_generator_agent.py`
 * 输出对齐）。所有字段都设为可选 + 兜底渲染，避免后端字段缺失时崩溃。
 */
type ShotItem = {
  duration_sec?: number
  shot_type?: string
  function?: string
  dialog?: string | null
  narration?: string | null
  is_brand_mention?: boolean
  is_punchline?: boolean
  product_focus_level?: 'none' | 'background' | 'foreground' | 'hero' | string
}

/**
 * 剧本分解结构；从 `script_breakdown` JSON 解析得到。
 */
type ScriptBreakdown = {
  total_duration_sec?: number
  opening_hook?: string
  cta_text?: string
  shots?: ShotItem[]
}

/**
 * 根据合规分数返回对应 Tag 颜色。
 */
function getComplianceColor(score: number): string {
  if (score >= 80) return 'green'
  if (score >= 60) return 'orange'
  return 'red'
}

/**
 * 单镜头渲染：把 ShotItem 的元数据拆分为 Tag + 文本块的组合。
 */
const ShotRow: React.FC<{ shot: ShotItem; index: number }> = ({ shot, index }) => {
  return (
    <List.Item>
      <Space direction="vertical" size={4} className="w-full">
        <Space size={4} wrap>
          <Tag>Shot {index + 1}</Tag>
          {shot.duration_sec != null ? <Tag>{shot.duration_sec}s</Tag> : null}
          {shot.shot_type ? <Tag>{shot.shot_type}</Tag> : null}
          {shot.is_brand_mention ? <Tag color="purple">品牌口播</Tag> : null}
          {shot.is_punchline ? <Tag color="gold">爆点</Tag> : null}
        </Space>
        {shot.function ? (
          <div className="text-xs text-gray-500">功能: {shot.function}</div>
        ) : null}
        {shot.dialog ? <div className="text-sm">对白: {shot.dialog}</div> : null}
        {shot.narration ? (
          <div className="text-sm italic text-gray-700">旁白: {shot.narration}</div>
        ) : null}
        {shot.product_focus_level && shot.product_focus_level !== 'none' ? (
          <Tag color="blue">商品出现 ({shot.product_focus_level})</Tag>
        ) : null}
      </Space>
    </List.Item>
  )
}

/**
 * 脚本展示器主组件。
 */
export const ScriptEditor: React.FC<ScriptEditorProps> = ({ variant }) => {
  if (!variant) {
    return (
      <Card title="脚本" size="small" className="h-full">
        <Empty description="暂无脚本，请点击下方“生成新脚本”" />
      </Card>
    )
  }

  // script_breakdown 后端是 Record<string, any>，做一次窄化方便读字段。
  const breakdown = (variant.script_breakdown ?? null) as ScriptBreakdown | null
  const shots = breakdown?.shots ?? []

  return (
    <Card
      title={
        <Space size={4} wrap>
          <span>脚本 v{variant.id.slice(0, 8)}</span>
          <Tag color={variant.status === 'ready' ? 'green' : 'orange'}>{variant.status}</Tag>
          {variant.is_champion ? <Tag color="gold">Champion</Tag> : null}
        </Space>
      }
      size="small"
      extra={
        <Space size={4} wrap>
          <Tag>{breakdown?.total_duration_sec ?? '—'}s</Tag>
          <Tag>{shots.length} 镜</Tag>
          <Tag color={getComplianceColor(variant.compliance_score)}>
            合规 {variant.compliance_score}
          </Tag>
        </Space>
      }
      className="h-full overflow-y-auto"
    >
      {breakdown?.opening_hook ? (
        <div className="mb-3">
          <div className="mb-1 text-xs text-gray-500">前 3 秒钩子</div>
          <div className="text-base font-medium">{breakdown.opening_hook}</div>
        </div>
      ) : null}

      {shots.length > 0 ? (
        <List
          dataSource={shots}
          renderItem={(shot, i) => <ShotRow shot={shot} index={i} />}
        />
      ) : (
        <Empty description="该变体暂无镜头分解（可能仍在生成中）" />
      )}

      {breakdown?.cta_text ? (
        <>
          <Divider />
          <div>
            <div className="mb-1 text-xs text-gray-500">结尾 CTA</div>
            <div className="text-base font-medium">{breakdown.cta_text}</div>
          </div>
        </>
      ) : null}

      {variant.script_full_text && shots.length === 0 ? (
        <>
          <Divider />
          <div>
            <div className="mb-1 text-xs text-gray-500">完整剧本</div>
            <pre className="m-0 max-h-72 overflow-auto whitespace-pre-wrap text-sm text-gray-800">
              {variant.script_full_text}
            </pre>
          </div>
        </>
      ) : null}
    </Card>
  )
}

export default ScriptEditor
