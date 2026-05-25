/**
 * 剧情公式选择器（FormulaPicker）。
 *
 * StoryWorkbench 左侧栏：列出所有可用的剧情公式（受 region 过滤），
 * 由用户点击选中作为当前生成脚本时的叙事框架。带详情按钮可展开公式
 * 的节拍 / 心理学原理 / 适用场景等元数据。
 *
 * 设计要点：
 * - 数据加载走 `useStoryFormulaList(region)`，缓存由 sibling
 *   `queries.ts` 维护，与 lobby 页共享。
 * - 风险标记（如 `family_conflict_compliance`）以红色 Tag 标出，
 *   便于运营在选公式时即看到合规风险。
 * - 详情按钮触发 Modal 展示完整结构；点击时 stopPropagation 防止误选。
 */
import React, { useState } from 'react'
import { Card, List, Spin, Tag, Tooltip, Button, Modal, Empty, Space, Descriptions } from 'antd'
import { InfoCircleOutlined } from '@ant-design/icons'
import type { FormulaRegion, StoryFormulaRead } from '../../../../../services/generated'
import { useStoryFormulaList } from '../queries'

export interface FormulaPickerProps {
  /** 当前选中的公式 ID；未选中传 null */
  selectedId: string | null
  /** 选中变化回调：传入新选中的公式 ID */
  onChange: (id: string) => void
  /** 过滤地域，默认 cn（中国大陆视角） */
  region?: FormulaRegion
}

/**
 * 公式详情弹窗。
 *
 * 展示公式的中文名 / 心理学原理 / 节拍数 / 风险标记 / 适用与禁忌场景。
 * P1 仅做只读展示，编辑公式由系统级管理员通过种子数据维护。
 */
const FormulaDetailModal: React.FC<{
  formula: StoryFormulaRead | null
  open: boolean
  onClose: () => void
}> = ({ formula, open, onClose }) => {
  if (!formula) return null
  return (
    <Modal
      title={`公式详情：${formula.name}`}
      open={open}
      onCancel={onClose}
      footer={null}
      width={640}
    >
      <Descriptions column={1} size="small" bordered>
        <Descriptions.Item label="心理学原理">{formula.psychology}</Descriptions.Item>
        <Descriptions.Item label="典型时长">{formula.typical_duration_sec}s</Descriptions.Item>
        <Descriptions.Item label="典型镜头数">{formula.typical_shot_count} 镜</Descriptions.Item>
        <Descriptions.Item label="适用地域">{formula.region}</Descriptions.Item>
        <Descriptions.Item label="分类">{formula.category}</Descriptions.Item>
        <Descriptions.Item label="风险标记">
          {formula.risk_flags && formula.risk_flags.length > 0 ? (
            <Space size={4} wrap>
              {formula.risk_flags.map((flag) => (
                <Tag key={flag} color="red">
                  {flag}
                </Tag>
              ))}
            </Space>
          ) : (
            <span className="text-gray-400">无</span>
          )}
        </Descriptions.Item>
        <Descriptions.Item label="适用场景">
          {formula.use_cases && formula.use_cases.length > 0 ? (
            <Space size={4} wrap>
              {formula.use_cases.map((c) => (
                <Tag key={c} color="green">
                  {c}
                </Tag>
              ))}
            </Space>
          ) : (
            <span className="text-gray-400">无</span>
          )}
        </Descriptions.Item>
        <Descriptions.Item label="禁忌场景">
          {formula.avoid_cases && formula.avoid_cases.length > 0 ? (
            <Space size={4} wrap>
              {formula.avoid_cases.map((c) => (
                <Tag key={c} color="orange">
                  {c}
                </Tag>
              ))}
            </Space>
          ) : (
            <span className="text-gray-400">无</span>
          )}
        </Descriptions.Item>
        <Descriptions.Item label="示例剧本">
          <pre className="m-0 max-h-48 overflow-auto whitespace-pre-wrap text-xs text-gray-700">
            {formula.sample_dialog}
          </pre>
        </Descriptions.Item>
      </Descriptions>
    </Modal>
  )
}

/**
 * 剧情公式选择器主组件。
 *
 * 卡片包裹一个可滚动的公式列表；每行显示公式名 / 风险标记 / 心理学摘要 /
 * 时长 / 镜头数。点击卡片选中；点击右侧详情按钮弹窗查看完整信息。
 */
export const FormulaPicker: React.FC<FormulaPickerProps> = ({
  selectedId,
  onChange,
  region = 'cn',
}) => {
  const { data: formulas, isLoading } = useStoryFormulaList(region)
  const [detailFormula, setDetailFormula] = useState<StoryFormulaRead | null>(null)

  const showDetail = (formula: StoryFormulaRead) => {
    setDetailFormula(formula)
  }

  return (
    <Card title="剧情公式" size="small" className="h-full overflow-auto">
      <Spin spinning={isLoading}>
        {(!formulas || formulas.length === 0) && !isLoading ? (
          <Empty description="暂无可用公式" />
        ) : (
          <List
            dataSource={formulas ?? []}
            renderItem={(formula: StoryFormulaRead) => {
              const isHighRisk = formula.risk_flags?.some((flag) =>
                flag.includes('compliance') || flag.includes('conflict'),
              )
              const psychologyExcerpt = formula.psychology
                ? `${formula.psychology.slice(0, 60)}${formula.psychology.length > 60 ? '...' : ''}`
                : ''
              return (
                <List.Item
                  className={`cursor-pointer ${
                    selectedId === formula.id ? 'bg-blue-50' : ''
                  }`}
                  onClick={() => onChange(formula.id)}
                  actions={[
                    <Tooltip title="查看详情" key="detail">
                      <Button
                        size="small"
                        icon={<InfoCircleOutlined />}
                        onClick={(e) => {
                          e.stopPropagation()
                          showDetail(formula)
                        }}
                      />
                    </Tooltip>,
                  ]}
                >
                  <List.Item.Meta
                    title={
                      <Space size={4} wrap>
                        <span className="font-medium">{formula.name}</span>
                        {isHighRisk ? <Tag color="red">高风险</Tag> : null}
                      </Space>
                    }
                    description={
                      <div className="text-xs text-gray-500">{psychologyExcerpt}</div>
                    }
                  />
                  <div className="text-xs text-gray-400">
                    {formula.typical_duration_sec}s · {formula.typical_shot_count} 镜
                  </div>
                </List.Item>
              )
            }}
          />
        )}
      </Spin>
      <FormulaDetailModal
        formula={detailFormula}
        open={!!detailFormula}
        onClose={() => setDetailFormula(null)}
      />
    </Card>
  )
}

export default FormulaPicker
