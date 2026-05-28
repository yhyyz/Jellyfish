/**
 * 投放效果列表组件（W22-T1，P4 Wave A 1/6）。
 *
 * 在分镜工作台「Outcomes」tab 内展示某变体下的全部 StoryOutcome：
 *
 * - 表格按 `recorded_at desc` 排序（后端已保证顺序），列出关键 KPI 列。
 * - 每行提供「编辑」「删除」操作；编辑通过弹窗调用 `useUpdateOutcome`，
 *   删除通过 antd Popconfirm 二次确认调用 `useDeleteOutcome`。
 *
 * 设计要点：
 * - 不持有数据：列表数据由 `useOutcomeList(variantId)` 提供。
 * - 不直接构造 PATCH payload；编辑弹窗复用 antd Form，仅更新被修改字段
 *   （schema PATCH 语义：仅显式字段被覆盖）。
 */
import React, { useState } from 'react'
import {
  Button,
  Empty,
  Form,
  InputNumber,
  Modal,
  Popconfirm,
  Space,
  Table,
  Tag,
  Tooltip,
  message,
} from 'antd'
import { DeleteOutlined, EditOutlined } from '@ant-design/icons'
import dayjs from 'dayjs'
import type { ColumnsType } from 'antd/es/table'
import type {
  StoryOutcomeRead,
  StoryOutcomeUpdate,
} from '../../../../../services/commerce/outcomeApi'
import {
  useDeleteOutcome,
  useOutcomeList,
  useUpdateOutcome,
} from '../outcome.queries'

interface OutcomeListProps {
  /** 必填：所属变体 ID。 */
  variantId: string
}

/** Platform 字符串 → 中文 Tag label。 */
const PLATFORM_LABEL: Record<string, string> = {
  douyin: '抖音',
  kuaishou: '快手',
  xiaohongshu: '小红书',
  youtube: 'YouTube',
  tiktok: 'TikTok',
}

/** 用于编辑弹窗的最小受控字段集。 */
interface EditFormValues {
  plays: number
  completion_rate_3s: number | null
  completion_rate_full: number | null
  gmv: number
  orders: number
}

/**
 * 投放效果列表组件。
 */
export const OutcomeList: React.FC<OutcomeListProps> = ({ variantId }) => {
  const { data: rows = [], isLoading } = useOutcomeList(variantId)
  const updateMutation = useUpdateOutcome()
  const deleteMutation = useDeleteOutcome()

  // 编辑弹窗的当前目标行；null 表示弹窗关闭。
  const [editing, setEditing] = useState<StoryOutcomeRead | null>(null)
  const [editForm] = Form.useForm<EditFormValues>()

  /** 打开编辑弹窗时把目标行字段初始化到 form。 */
  const handleOpenEdit = (row: StoryOutcomeRead): void => {
    setEditing(row)
    editForm.setFieldsValue({
      plays: row.plays,
      completion_rate_3s: row.completion_rate_3s ?? null,
      completion_rate_full: row.completion_rate_full ?? null,
      gmv: row.gmv,
      orders: row.orders,
    })
  }

  /** 提交编辑：仅 PATCH 用户改动过的字段。 */
  const handleSubmitEdit = async (): Promise<void> => {
    if (!editing) return
    try {
      const values = await editForm.validateFields()
      const patch: StoryOutcomeUpdate = {
        plays: values.plays,
        completion_rate_3s: values.completion_rate_3s ?? null,
        completion_rate_full: values.completion_rate_full ?? null,
        gmv: values.gmv,
        orders: values.orders,
      }
      await updateMutation.mutateAsync({ outcomeId: editing.id, patch })
      message.success('已更新投放效果')
      setEditing(null)
    } catch (e) {
      const errMsg = e instanceof Error ? e.message : '校验失败'
      message.error(`更新失败：${errMsg}`)
    }
  }

  /** 删除某行；删除前由 Popconfirm 做用户确认。 */
  const handleDelete = async (row: StoryOutcomeRead): Promise<void> => {
    try {
      await deleteMutation.mutateAsync({ outcomeId: row.id, variantId: row.variant_id })
      message.success('已删除一条投放效果')
    } catch (e) {
      const errMsg = e instanceof Error ? e.message : '未知错误'
      message.error(`删除失败：${errMsg}`)
    }
  }

  // 列定义；键以 `dataIndex` 标识 ORM 字段，便于排序/筛选扩展。
  const columns: ColumnsType<StoryOutcomeRead> = [
    {
      title: '记录时点',
      dataIndex: 'recorded_at',
      key: 'recorded_at',
      render: (val: string) => dayjs(val).format('YYYY-MM-DD HH:mm'),
    },
    {
      title: '平台',
      dataIndex: 'platform',
      key: 'platform',
      render: (val: string) => <Tag color="blue">{PLATFORM_LABEL[val] ?? val}</Tag>,
    },
    {
      title: '播放量',
      dataIndex: 'plays',
      key: 'plays',
      align: 'right',
    },
    {
      title: '3s 完播',
      dataIndex: 'completion_rate_3s',
      key: 'completion_rate_3s',
      align: 'right',
      render: (val: number | null) => (val == null ? '-' : (val * 100).toFixed(1) + '%'),
    },
    {
      title: '完整完播',
      dataIndex: 'completion_rate_full',
      key: 'completion_rate_full',
      align: 'right',
      render: (val: number | null) => (val == null ? '-' : (val * 100).toFixed(1) + '%'),
    },
    {
      title: '订单',
      dataIndex: 'orders',
      key: 'orders',
      align: 'right',
    },
    {
      title: 'GMV',
      dataIndex: 'gmv',
      key: 'gmv',
      align: 'right',
      render: (val: number) => `¥ ${val.toFixed(2)}`,
    },
    {
      title: '操作',
      key: 'actions',
      width: 130,
      render: (_, row) => (
        <Space size={4}>
          <Tooltip title="编辑">
            <Button
              size="small"
              icon={<EditOutlined />}
              onClick={() => handleOpenEdit(row)}
              data-testid={`outcome-row-edit-${row.id}`}
            />
          </Tooltip>
          <Popconfirm
            title="确认删除该条投放效果？"
            okText="删除"
            cancelText="取消"
            onConfirm={() => void handleDelete(row)}
          >
            <Tooltip title="删除">
              <Button
                size="small"
                danger
                icon={<DeleteOutlined />}
                data-testid={`outcome-row-delete-${row.id}`}
              />
            </Tooltip>
          </Popconfirm>
        </Space>
      ),
    },
  ]

  return (
    <>
      <Table<StoryOutcomeRead>
        size="small"
        rowKey="id"
        dataSource={rows}
        loading={isLoading}
        columns={columns}
        pagination={false}
        locale={{ emptyText: <Empty description="暂无投放效果记录" /> }}
        data-testid="outcome-list"
      />

      <Modal
        title="编辑投放效果"
        open={!!editing}
        onCancel={() => setEditing(null)}
        onOk={() => void handleSubmitEdit()}
        okText="保存"
        cancelText="取消"
        confirmLoading={updateMutation.isPending}
        destroyOnClose
      >
        <Form<EditFormValues> form={editForm} layout="vertical">
          <Form.Item
            label="播放量"
            name="plays"
            rules={[{ required: true, type: 'number', min: 0, message: '播放量必须 ≥ 0' }]}
          >
            <InputNumber min={0} style={{ width: '100%' }} />
          </Form.Item>
          <Form.Item
            label="3 秒完播率"
            name="completion_rate_3s"
            rules={[{ type: 'number', min: 0, max: 1 }]}
          >
            <InputNumber min={0} max={1} step={0.01} style={{ width: '100%' }} />
          </Form.Item>
          <Form.Item
            label="完整完播率"
            name="completion_rate_full"
            rules={[{ type: 'number', min: 0, max: 1 }]}
          >
            <InputNumber min={0} max={1} step={0.01} style={{ width: '100%' }} />
          </Form.Item>
          <Form.Item
            label="订单数"
            name="orders"
            rules={[{ type: 'number', min: 0, message: '订单数必须 ≥ 0' }]}
          >
            <InputNumber min={0} style={{ width: '100%' }} />
          </Form.Item>
          <Form.Item
            label="GMV"
            name="gmv"
            rules={[{ required: true, type: 'number', min: 0, message: 'GMV 必须 ≥ 0' }]}
          >
            <InputNumber min={0} step={0.01} style={{ width: '100%' }} />
          </Form.Item>
        </Form>
      </Modal>
    </>
  )
}

export default OutcomeList
