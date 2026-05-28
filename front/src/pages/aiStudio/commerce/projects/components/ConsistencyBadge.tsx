/**
 * ConsistencyBadge（W27-T3）。
 *
 * 紧凑展示 ``Shot.consistency_score`` 的色档徽章。视觉一致性得分由
 * W27-T1 DINOv2 sidecar 计算并落到 ``Shot.consistency_score``；本组件
 * 把数值映射到统一色档语义：
 *
 * - score >= 0.85 → 绿色（``success``）
 * - 0.75 <= score < 0.85 → 琥珀（``warning``）
 * - score < 0.75 → 红色（``error``）
 * - score === null → 灰色（``default``，"未评估"语义）
 *
 * 阈值与后端 ``app.services.commerce.shot_consistency_service`` 单一真
 * 相来源；调整阈值需同步两侧。
 *
 * 设计要点：
 * - 仅依赖 antd Tag + 可选数值显示，零网络请求；
 * - 点击行为通过外部 ``onClick`` 注入（典型用法：打开
 *   ``ConsistencyReviewDrawer``）。
 */
import React from 'react'
import { Tag, Tooltip } from 'antd'

/** 色档状态字面量；与 OpenAPI generated ``ConsistencyEvidenceRead.status`` 对齐 */
export type ConsistencyStatus = 'green' | 'amber' | 'red' | 'unknown'

/** 阈值常量；与 backend `SCORE_THRESHOLD_*` 单一真相同步。 */
export const SCORE_THRESHOLD_GREEN = 0.85
export const SCORE_THRESHOLD_AMBER = 0.75

/**
 * 把 score 数值映射到色档状态。
 *
 * - 入参 ``null`` / ``undefined`` 都视为"未评估"（unknown）。
 * - NaN / 非有限数同样落到 unknown，避免渲染异常颜色。
 */
export function deriveConsistencyStatus(
  score: number | null | undefined,
): ConsistencyStatus {
  if (score === null || score === undefined || !Number.isFinite(score)) {
    return 'unknown'
  }
  if (score >= SCORE_THRESHOLD_GREEN) return 'green'
  if (score >= SCORE_THRESHOLD_AMBER) return 'amber'
  return 'red'
}

/** antd Tag 颜色 token 与色档状态的映射。 */
const STATUS_COLOR: Record<ConsistencyStatus, string> = {
  green: 'success',
  amber: 'warning',
  red: 'error',
  unknown: 'default',
}

/** 色档语义中文标签，给 hover tooltip 用。 */
const STATUS_LABEL: Record<ConsistencyStatus, string> = {
  green: '一致性优',
  amber: '一致性中',
  red: '一致性差',
  unknown: '未评估',
}

export interface ConsistencyBadgeProps {
  /** ``Shot.consistency_score``；null/undefined 走 unknown 灰档 */
  score: number | null | undefined
  /** 可选 shot_id，仅用于业务标识；本身不影响渲染 */
  shotId?: string
  /** 点击徽章时回调；通常用来打开 ``ConsistencyReviewDrawer`` */
  onClick?: (shotId: string | undefined) => void
  /** 是否在徽章内显示数值（默认 true，已知 score 时显示两位小数） */
  showScore?: boolean
  /** 自定义类名 */
  className?: string
}

/**
 * 视觉一致性色档徽章。
 *
 * 渲染 antd ``Tag``：
 * - color 根据色档状态映射；
 * - 文本：``一致性优 0.92`` / ``一致性中 0.78`` / ``未评估``；
 * - 提供 ``onClick`` 时整张 Tag 可点；带 ``data-testid`` 便于单测定位。
 */
export const ConsistencyBadge: React.FC<ConsistencyBadgeProps> = ({
  score,
  shotId,
  onClick,
  showScore = true,
  className,
}) => {
  const status = deriveConsistencyStatus(score)
  const color = STATUS_COLOR[status]
  const label = STATUS_LABEL[status]
  const hasScore = score !== null && score !== undefined && Number.isFinite(score)
  const text = showScore && hasScore ? `${label} ${(score as number).toFixed(2)}` : label

  const tooltipTitle =
    status === 'unknown'
      ? '尚未评估视觉一致性，可能缺少参考图或 sidecar 不可达'
      : `视觉一致性得分（DINOv2）：${hasScore ? (score as number).toFixed(4) : '—'}`

  const handleClick = onClick
    ? () => {
        onClick(shotId)
      }
    : undefined

  return (
    <Tooltip title={tooltipTitle}>
      <Tag
        color={color}
        onClick={handleClick}
        className={className}
        style={onClick ? { cursor: 'pointer' } : undefined}
        data-testid="consistency-badge"
        data-status={status}
      >
        {text}
      </Tag>
    </Tooltip>
  )
}

export default ConsistencyBadge
