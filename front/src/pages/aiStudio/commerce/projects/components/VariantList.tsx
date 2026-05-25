/**
 * 变体列表（W13-T6）。
 *
 * 在 StoryWorkbench 左侧以紧凑卡片形式展示当前项目下所有 StoryVariant，
 * 提供两类一级操作：
 *
 * - 克隆：弹出 `VariantCloneModal`，基于该变体派生新变体（可选覆盖
 *   archetype / hook / cta / formula）。
 * - 标记冠军：调用 `PATCH /story-variants/{id}/champion`，同章节单选语义
 *   由后端保证；UI 上仅在该项目内做 loading 反馈与 toast 提示。
 *
 * 设计要点：
 * - 不持有变体数据，全部由父组件传入；保持纯展示 + 受控选择。
 * - `activeVariantId` 由父组件传入并驱动高亮，与 ScriptEditor /
 *   ComplianceWarningBanner 共享同一来源，避免出现两个"当前变体"。
 * - 操作按钮使用 Tooltip 提示语义；冠军按钮根据 `is_champion` 同时切换
 *   `type` 与 hover 文案，避免重复触发请求时无视觉反馈。
 * - 列表项点击事件冒泡到 `<List.Item>`，按钮自身阻断冒泡（通过
 *   `stopPropagation` 显式处理），保证「点击变体卡片切换激活」与
 *   「点击操作按钮触发对应动作」的边界清晰。
 */
import React, { useState } from 'react'
import { Button, Card, List, Space, Tag, Tooltip, message } from 'antd'
import { CopyOutlined, CrownOutlined } from '@ant-design/icons'
import type { StoryVariantRead } from '../../../../../services/generated'
import { useMarkVariantChampion } from '../workbench.queries'
import { VariantCloneModal } from './VariantCloneModal'

type Props = {
  /** 当前项目下的全部变体（已按 created_at desc 排序） */
  variants: StoryVariantRead[]
  /** 当前激活变体 id（用于高亮） */
  activeVariantId: string | null
  /** 用户选中变体时回调，用于把激活态同步给父组件 */
  onSelect: (id: string) => void
}

/** 变体状态 → Tag 颜色映射，与工作台其它位置保持一致 */
const STATUS_TAG_COLOR: Record<string, string> = {
  ready: 'green',
  failed: 'red',
}

/**
 * 变体列表组件。
 */
export const VariantList: React.FC<Props> = ({ variants, activeVariantId, onSelect }) => {
  const [cloneOpenFor, setCloneOpenFor] = useState<StoryVariantRead | null>(null)
  const championMutation = useMarkVariantChampion()
  // 记录正在标记冠军的 variantId，用于在按钮上做局部 loading
  // （避免 mutation.isPending 给所有按钮统一加 loading）。
  const [pendingChampionId, setPendingChampionId] = useState<string | null>(null)

  /**
   * 标记冠军；同章节互斥由后端保证，前端只做 toast 与 loading 反馈。
   */
  const handleChampion = async (id: string) => {
    setPendingChampionId(id)
    try {
      await championMutation.mutateAsync(id)
      message.success('已标记为冠军变体')
    } catch (e) {
      const errMsg = e instanceof Error ? e.message : '未知错误'
      message.error(`标记失败：${errMsg}`)
    } finally {
      setPendingChampionId(null)
    }
  }

  return (
    <Card
      size="small"
      title={
        <Space size={6}>
          <span>变体列表</span>
          <Tag>{variants.length}</Tag>
        </Space>
      }
      bodyStyle={{ padding: 0, maxHeight: '100%', overflow: 'auto' }}
    >
      <List<StoryVariantRead>
        size="small"
        dataSource={variants}
        locale={{ emptyText: '暂无变体' }}
        renderItem={(v) => {
          const tagColor = STATUS_TAG_COLOR[v.status] ?? 'orange'
          const isActive = activeVariantId === v.id
          return (
            <List.Item
              className={`cursor-pointer transition-colors ${isActive ? 'bg-blue-50' : ''}`}
              onClick={() => onSelect(v.id)}
              actions={[
                <Tooltip key="clone" title="克隆此变体">
                  <Button
                    size="small"
                    icon={<CopyOutlined />}
                    onClick={(e) => {
                      e.stopPropagation()
                      setCloneOpenFor(v)
                    }}
                  />
                </Tooltip>,
                <Tooltip key="champion" title={v.is_champion ? '已是冠军变体' : '标记为冠军'}>
                  <Button
                    size="small"
                    icon={<CrownOutlined />}
                    type={v.is_champion ? 'primary' : 'default'}
                    loading={pendingChampionId === v.id}
                    disabled={v.is_champion || championMutation.isPending}
                    onClick={(e) => {
                      e.stopPropagation()
                      void handleChampion(v.id)
                    }}
                  />
                </Tooltip>,
              ]}
            >
              <List.Item.Meta
                title={
                  <Space size={4} wrap>
                    <span className="font-mono text-xs">{v.id.slice(0, 8)}</span>
                    <Tag color={tagColor}>{v.status}</Tag>
                    {v.is_champion ? (
                      <Tag color="gold" icon={<CrownOutlined />}>
                        Champion
                      </Tag>
                    ) : null}
                  </Space>
                }
                description={
                  <Space size={4} wrap className="text-xs text-gray-500">
                    <span>合规 {v.compliance_score}</span>
                    {v.archetype ? <span>· {v.archetype}</span> : null}
                    {v.formula_id ? <span>· {v.formula_id}</span> : null}
                  </Space>
                }
              />
            </List.Item>
          )
        }}
      />

      <VariantCloneModal
        sourceVariant={cloneOpenFor}
        onCancel={() => setCloneOpenFor(null)}
        onSuccess={() => setCloneOpenFor(null)}
      />
    </Card>
  )
}
