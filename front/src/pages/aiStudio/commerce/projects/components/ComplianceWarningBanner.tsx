/**
 * 合规警告面板（ComplianceWarningBanner）。
 *
 * StoryWorkbench 右侧栏：聚合展示当前激活变体（StoryVariant）的合规
 * findings。按 severity 分组：blocker（阻断）/ warning（警告）/
 * info（提示），分别用对应色调表达紧迫程度。
 *
 * 数据契约：
 * - `findings` 由 `useComplianceFindings(variantId)` 拉取，返回数组；
 * - `variant` 用于在没有 finding 时区分两种状态：
 *   - `compliance_score === 0` → 还没跑过检查，显示「尚未运行」。
 *   - `compliance_score > 0`  → 已检查通过 / 已修复，显示成功提示。
 *
 * 视觉策略：
 * - Card title 跟着 finding 数量动态显示阻断 / 警告 Tag，便于第一眼定位。
 * - Collapse 默认展开 blockers 面板，强迫用户优先处理高优问题。
 */
import React from 'react'
import { Alert, Card, Collapse, Empty, Space, Tag } from 'antd'
import type { ComplianceFindingRead, StoryVariantRead } from '../../../../../services/generated'

export interface ComplianceWarningBannerProps {
  /** findings 列表（按 detected_at desc 已排序） */
  findings: ComplianceFindingRead[]
  /** 当前激活变体；为空时显示 Empty 占位 */
  variant: StoryVariantRead | null
}

/**
 * 单条 finding 行渲染：规则类型 + 描述 + 命中位置 + 建议修复。
 */
const FindingItem: React.FC<{ finding: ComplianceFindingRead }> = ({ finding }) => {
  return (
    <div className="mb-2 border-b border-gray-100 pb-2 last:mb-0 last:border-b-0 last:pb-0">
      <Space size={4} wrap className="mb-1">
        <Tag>{finding.rule_kind}</Tag>
        <Tag>{finding.rule_id}</Tag>
        {finding.is_resolved ? <Tag color="green">已解决</Tag> : null}
      </Space>
      <div className="text-sm text-gray-800">{finding.description}</div>
      {finding.location ? (
        <div className="mt-0.5 text-xs text-gray-500">位置: {finding.location}</div>
      ) : null}
      {finding.suggested_fix ? (
        <div className="mt-0.5 text-xs text-blue-600">建议: {finding.suggested_fix}</div>
      ) : null}
    </div>
  )
}

/**
 * 合规警告面板主组件。
 */
export const ComplianceWarningBanner: React.FC<ComplianceWarningBannerProps> = ({
  findings,
  variant,
}) => {
  if (!variant) {
    return (
      <Card title="合规检查" size="small" className="h-full">
        <Empty description="先生成脚本" />
      </Card>
    )
  }

  // 按 severity 分组：blocker > warning > info。
  const blockers = findings.filter((f) => f.severity === 'blocker')
  const warnings = findings.filter((f) => f.severity === 'warning')
  const infos = findings.filter((f) => f.severity === 'info')

  // 构造 Collapse items（避免使用已废弃的 <Collapse.Panel> 子元素 API）。
  const collapseItems: { key: string; label: React.ReactNode; children: React.ReactNode }[] = []
  if (blockers.length > 0) {
    collapseItems.push({
      key: 'blockers',
      label: <span className="text-red-600">阻断项 ({blockers.length})</span>,
      children: (
        <div>
          {blockers.map((f) => (
            <FindingItem key={f.id} finding={f} />
          ))}
        </div>
      ),
    })
  }
  if (warnings.length > 0) {
    collapseItems.push({
      key: 'warnings',
      label: <span className="text-orange-600">警告 ({warnings.length})</span>,
      children: (
        <div>
          {warnings.map((f) => (
            <FindingItem key={f.id} finding={f} />
          ))}
        </div>
      ),
    })
  }
  if (infos.length > 0) {
    collapseItems.push({
      key: 'infos',
      label: <span className="text-blue-600">提示 ({infos.length})</span>,
      children: (
        <div>
          {infos.map((f) => (
            <FindingItem key={f.id} finding={f} />
          ))}
        </div>
      ),
    })
  }

  return (
    <Card
      title={
        <Space size={4} wrap>
          <span>合规检查</span>
          {blockers.length > 0 ? <Tag color="red">{blockers.length} 阻断</Tag> : null}
          {warnings.length > 0 ? <Tag color="orange">{warnings.length} 警告</Tag> : null}
        </Space>
      }
      size="small"
      className="h-full overflow-y-auto"
    >
      {findings.length === 0 && variant.compliance_score === 0 ? (
        <Alert type="info" message="尚未运行合规检查" showIcon />
      ) : null}
      {findings.length === 0 && variant.compliance_score > 0 ? (
        <Alert
          type="success"
          message={`合规检查通过 (${variant.compliance_score}/100)`}
          showIcon
        />
      ) : null}
      {findings.length > 0 ? (
        <Collapse defaultActiveKey={['blockers']} ghost items={collapseItems} />
      ) : null}
    </Card>
  )
}

export default ComplianceWarningBanner
