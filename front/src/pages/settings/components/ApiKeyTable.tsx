/**
 * ApiKeyTable — admin 用 API key 列表表格（W24-T5，P4 Wave B 7/11）。
 *
 * 列设计：
 *   - description（备注）：admin 辨认归属的主入口；空值降级为
 *     ``<Tag>未命名</Tag>`` 提示，避免空字符串 + 不可读的 hash。
 *   - api_key_hash：紧凑展示 hash 前 8 + 后 6 字符，便于事后比对，
 *     不展示明文（明文只在创建 Modal 一次性给出，由 ApiKeyCreateModal
 *     负责）。
 *   - daily_limit / consumed_today / monthly_limit / consumed_month：
 *     直接显示绝对值；上限为 0 用 ``Tag color="default"`` 标记 "不限"，
 *     语义与后端 ``ApiKeyQuota`` 默认行为对齐。
 *   - is_active：active → ``green Tag`` / revoked → ``red Tag``，便于
 *     扫一眼定位失效 key。
 *   - actions：仅当 ``is_active`` 时渲染「Revoke」按钮，外裹
 *     ``Popconfirm`` 二次确认，避免误操作。已 revoke 的行渲染成不可
 *     交互的灰色文本。
 *
 * 数据流：
 *   - 父组件 ``ApiKeysPage`` 持有 useQuery 数据，本组件保持纯展示 +
 *     回调，便于单测 mock + 复用。
 *   - revoke 调用走父级 mutation，本组件只触发 ``onRevoke(hash)``。
 */
import React from 'react'
import { Button, Popconfirm, Space, Table, Tag, Typography } from 'antd'
import type { ColumnsType } from 'antd/es/table'
import type { ApiKeyRead } from '../../../services/generated'

const { Text } = Typography

export interface ApiKeyTableProps {
  /** 当前列表数据；外部 useQuery 注入 */
  data: ApiKeyRead[]
  /** 列表 loading 状态；映射到 antd Table loading prop */
  loading?: boolean
  /** Revoke 回调；点击 Popconfirm 确认后触发，传入目标 hash */
  onRevoke: (hash: string) => void
  /** 单条 revoke 是否正在进行；用于禁用按钮防抖 */
  revokingHash?: string | null
}

/**
 * 紧凑展示 hash：前 8 字符 + 省略号 + 后 6 字符，适合表格定宽列。
 * 输入异常（短于 16 字符）直接返回原值，避免越界。
 */
export function formatHash(hash: string): string {
  if (!hash || hash.length <= 16) return hash
  return `${hash.slice(0, 8)}…${hash.slice(-6)}`
}

/**
 * 渲染配额单元格：limit=0 用 "不限" Tag；否则展示 ``consumed / limit``。
 */
function renderQuotaCell(consumed: number, limit: number): React.ReactNode {
  if (limit <= 0) {
    return (
      <Space size={4}>
        <Text style={{ fontVariantNumeric: 'tabular-nums' }}>{consumed}</Text>
        <Tag>不限</Tag>
      </Space>
    )
  }
  return (
    <Text style={{ fontVariantNumeric: 'tabular-nums' }}>
      {consumed} / {limit}
    </Text>
  )
}

export const ApiKeyTable: React.FC<ApiKeyTableProps> = ({
  data,
  loading,
  onRevoke,
  revokingHash,
}) => {
  const columns: ColumnsType<ApiKeyRead> = [
    {
      title: '备注',
      dataIndex: 'description',
      key: 'description',
      width: 200,
      render: (desc: string) =>
        desc ? <Text strong>{desc}</Text> : <Tag color="default">未命名</Tag>,
    },
    {
      title: 'Hash',
      dataIndex: 'api_key_hash',
      key: 'api_key_hash',
      width: 180,
      render: (hash: string) => (
        <Text code style={{ fontFamily: 'monospace' }}>
          {formatHash(hash)}
        </Text>
      ),
    },
    {
      title: '创建时间',
      dataIndex: 'created_at',
      key: 'created_at',
      width: 180,
      render: (value: string) => (
        <Text type="secondary" style={{ fontVariantNumeric: 'tabular-nums' }}>
          {value}
        </Text>
      ),
    },
    {
      title: '日配额',
      key: 'daily',
      width: 160,
      render: (_: unknown, record: ApiKeyRead) =>
        renderQuotaCell(record.consumed_today, record.daily_limit),
    },
    {
      title: '月配额',
      key: 'monthly',
      width: 160,
      render: (_: unknown, record: ApiKeyRead) =>
        renderQuotaCell(record.consumed_this_month, record.monthly_limit),
    },
    {
      title: '状态',
      dataIndex: 'is_active',
      key: 'is_active',
      width: 100,
      render: (active: boolean) =>
        active ? <Tag color="green">active</Tag> : <Tag color="red">revoked</Tag>,
    },
    {
      title: '操作',
      key: 'actions',
      width: 140,
      render: (_: unknown, record: ApiKeyRead) => {
        if (!record.is_active) {
          return <Text type="secondary">已撤销</Text>
        }
        return (
          <Popconfirm
            title="撤销该 API key？"
            description="撤销后调用方将立即失效，此操作不可逆。"
            okText="确认撤销"
            cancelText="取消"
            okButtonProps={{ danger: true }}
            onConfirm={() => onRevoke(record.api_key_hash)}
          >
            <Button
              size="small"
              danger
              loading={revokingHash === record.api_key_hash}
              data-testid={`revoke-btn-${record.api_key_hash}`}
            >
              Revoke
            </Button>
          </Popconfirm>
        )
      },
    },
  ]

  return (
    <Table<ApiKeyRead>
      rowKey="api_key_hash"
      data-testid="api-key-table"
      columns={columns}
      dataSource={data}
      loading={loading}
      pagination={{ pageSize: 20, showSizeChanger: true, showQuickJumper: true }}
      scroll={{ x: 'max-content' }}
      size="middle"
    />
  )
}

export default ApiKeyTable
