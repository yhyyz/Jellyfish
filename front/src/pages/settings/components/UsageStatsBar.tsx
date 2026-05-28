/**
 * UsageStatsBar — API key 配额用量条（W24-T5，P4 Wave B 7/11）。
 *
 * 设计取舍：
 *   - 后端 ``ApiKeyUsageRead`` 仅提供 ``consumed_today`` /
 *     ``consumed_this_month`` 两个标量，不存在按小时/按天的时序点位，
 *     因此 sparkline 真正的 x 轴时间数据并不存在。强行造图反而会误
 *     导运营。
 *   - 兜底策略：用 antd ``Progress`` 双条（日 + 月）直接表达「已用
 *     比例」，与配额语义 1:1 对齐；无需引入 @ant-design/charts 重 chunk。
 *   - 当 ``limit === 0`` 视为「不限/禁用」语义，按规范不渲染百分比，
 *     退化为纯计数文本。
 *   - 颜色阈值由 ``percent`` 决定：>=90% 红色告警 / >=70% 橙色提示 /
 *     默认 antd token 蓝色。所有阈值集中常量便于后续调整。
 */
import React from 'react'
import { Progress, Space, Typography } from 'antd'

const { Text } = Typography

/** 告警阈值：超过该百分比即认为「即将到顶」，配色升级为 warning */
const WARN_THRESHOLD = 70
/** 危险阈值：超过该百分比即视为「严重接近上限」，配色升级为 danger */
const DANGER_THRESHOLD = 90

export interface UsageStatsBarProps {
  /** 今日已消耗调用次数 */
  consumedToday: number
  /** 当日上限；0 表示不限/禁用 */
  dailyLimit: number
  /** 本月已消耗调用次数 */
  consumedThisMonth: number
  /** 当月上限；0 表示不限/禁用 */
  monthlyLimit: number
}

/**
 * 计算「已用 / 上限」的百分比；当上限为 0 返回 null（视作不限）。
 * 抽成纯函数以便单测；返回值锁定 0~100 之间的整数。
 */
export function calcUsagePercent(consumed: number, limit: number): number | null {
  if (limit <= 0) return null
  const pct = Math.round((consumed / limit) * 100)
  if (pct < 0) return 0
  if (pct > 100) return 100
  return pct
}

/**
 * 根据百分比映射 antd Progress 的 status；空值（不限）走默认 active。
 */
function pickStatus(percent: number | null): 'normal' | 'active' | 'exception' | 'success' {
  if (percent === null) return 'normal'
  if (percent >= DANGER_THRESHOLD) return 'exception'
  if (percent >= WARN_THRESHOLD) return 'active'
  return 'normal'
}

export const UsageStatsBar: React.FC<UsageStatsBarProps> = ({
  consumedToday,
  dailyLimit,
  consumedThisMonth,
  monthlyLimit,
}) => {
  const dayPct = calcUsagePercent(consumedToday, dailyLimit)
  const monthPct = calcUsagePercent(consumedThisMonth, monthlyLimit)

  const renderRow = (
    label: string,
    consumed: number,
    limit: number,
    percent: number | null,
    testId: string,
  ) => (
    <div data-testid={testId} className="flex flex-col gap-1">
      <div className="flex items-center justify-between">
        <Text strong>{label}</Text>
        <Text type="secondary" style={{ fontVariantNumeric: 'tabular-nums' }}>
          {limit > 0 ? `${consumed} / ${limit}` : `${consumed} / 不限`}
        </Text>
      </div>
      {percent === null ? (
        <Text type="secondary" italic>
          未设置上限
        </Text>
      ) : (
        <Progress
          percent={percent}
          size="small"
          status={pickStatus(percent)}
          showInfo
        />
      )}
    </div>
  )

  return (
    <Space
      direction="vertical"
      size="small"
      className="w-full"
      data-testid="usage-stats-bar"
    >
      {renderRow('今日用量', consumedToday, dailyLimit, dayPct, 'usage-day-row')}
      {renderRow('本月用量', consumedThisMonth, monthlyLimit, monthPct, 'usage-month-row')}
    </Space>
  )
}

export default UsageStatsBar
