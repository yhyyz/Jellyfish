/**
 * OutcomeCsvImport（W22-T2，P4 Wave B 1/11）。
 *
 * 在「投放效果」抽屉里提供 CSV 批量导入入口，与 OutcomeEntryForm 共存：
 * - 拖拽 / 点击上传 ``.csv``；前端先做 5MB 体积预检，避免恶意大文件浪费
 *   后端带宽。
 * - mapping_profile 下拉：``douyin`` / ``xiaohongshu`` / ``default``。
 * - 提交后展示 :class:`ImportSummary`：``inserted`` / ``failed`` /
 *   ``mapping_profile``，并把 ``errors[]`` 用 antd Table 列出（带行号、
 *   原始 row、reason），便于运营同学回到原 CSV 修正。
 *
 * 严守 AGENTS.md 第 2 条：通过 OpenAPI generated client 直接调用，不
 * 再额外手写 service wrapper；mutation 缓存编排放在 outcome.queries 中。
 */
import React, { useMemo, useState } from 'react'
import {
  Alert,
  Button,
  Descriptions,
  message,
  Select,
  Space,
  Table,
  Typography,
  Upload,
} from 'antd'
import type { UploadFile, UploadProps } from 'antd/es/upload/interface'
import { InboxOutlined, UploadOutlined } from '@ant-design/icons'
import { useMutation, useQueryClient } from '@tanstack/react-query'
import {
  CommerceOutcomesImportService,
  type ImportSummary,
  type RowError,
} from '../../../../../services/generated'
import { outcomeKeys } from '../outcome.queries'

/** 与后端保持一致的 5MB 上限，前端先拦一道避免大文件浪费带宽。 */
const MAX_UPLOAD_BYTES = 5 * 1024 * 1024

const PROFILE_OPTIONS: Array<{ value: string; label: string }> = [
  { value: 'douyin', label: '抖音（douyin）' },
  { value: 'xiaohongshu', label: '小红书（xiaohongshu）' },
  { value: 'default', label: '默认（英文 header）' },
]

interface OutcomeCsvImportProps {
  variantId: string
  onSuccess?: () => void
}

/**
 * 把 ``ImportSummary.errors`` 转为 Table 行；保持原 ``row_index`` 顺序，
 * 让运营同学按 CSV 行号定位。
 */
function makeErrorRows(
  errors: RowError[],
): Array<{ key: number; row_index: number; reason: string; raw_row: string }> {
  return errors.map((err) => ({
    key: err.row_index,
    row_index: err.row_index,
    reason: err.reason,
    raw_row: JSON.stringify(err.raw_row),
  }))
}

export const OutcomeCsvImport: React.FC<OutcomeCsvImportProps> = ({
  variantId,
  onSuccess,
}) => {
  const [fileList, setFileList] = useState<UploadFile[]>([])
  const [profile, setProfile] = useState<string>('douyin')
  const [summary, setSummary] = useState<ImportSummary | null>(null)
  const qc = useQueryClient()

  /** 是否存在文件且尺寸合法；驱动提交按钮启用状态。 */
  const validFile = useMemo(() => {
    if (fileList.length === 0) return null
    const first = fileList[0]
    const blob = (first.originFileObj as File | undefined) ?? null
    if (!blob) return null
    return blob.size <= MAX_UPLOAD_BYTES ? blob : null
  }, [fileList])

  const oversized = useMemo(() => {
    if (fileList.length === 0) return false
    const blob = fileList[0].originFileObj as File | undefined
    if (!blob) return false
    return blob.size > MAX_UPLOAD_BYTES
  }, [fileList])

  const importMutation = useMutation({
    mutationFn: async (blob: File): Promise<ImportSummary> => {
      const res =
        await CommerceOutcomesImportService.importOutcomesCsvApiV1CommerceOutcomesImportPost({
          // codegen 把 file 标成 string，但 runtime 接受 Blob/File；
          // 这里用 unknown 中转避免污染调用方类型。
          formData: {
            file: blob as unknown as string,
            mapping_profile: profile,
          },
        })
      if (!res.data) throw new Error('empty import summary')
      return res.data
    },
    onSuccess: (data) => {
      setSummary(data)
      // 列表缓存失效，让上一个 tab 切回时能拿到新增数据。
      void qc.invalidateQueries({ queryKey: outcomeKeys.list(variantId) })
      onSuccess?.()
    },
  })

  /**
   * antd Upload beforeUpload 返回 false 阻止自动上传；只把文件登记到
   * fileList，让用户先确认 mapping_profile 再点击「开始导入」。
   */
  const uploadProps: UploadProps = {
    accept: '.csv',
    multiple: false,
    fileList,
    beforeUpload: (file) => {
      if (file.size > MAX_UPLOAD_BYTES) {
        message.error('文件超过 5MB 上限，请拆分后再上传')
      }
      setFileList([
        {
          uid: file.uid,
          name: file.name,
          status: 'done',
          size: file.size,
          originFileObj: file,
        },
      ])
      return false
    },
    onRemove: () => {
      setFileList([])
      setSummary(null)
    },
  }

  const handleSubmit = (): void => {
    if (!validFile) return
    importMutation.mutate(validFile)
  }

  return (
    <div data-testid="outcome-csv-import">
      <Space direction="vertical" size={12} style={{ width: '100%' }}>
        <Space size={12} wrap>
          <span>列名映射：</span>
          <Select
            options={PROFILE_OPTIONS}
            value={profile}
            onChange={setProfile}
            style={{ width: 220 }}
            data-testid="outcome-csv-profile-select"
          />
        </Space>

        <Upload.Dragger {...uploadProps} data-testid="outcome-csv-upload-dragger">
          <p className="ant-upload-drag-icon">
            <InboxOutlined />
          </p>
          <p className="ant-upload-text">点击或拖拽 CSV 文件到此区域上传</p>
          <p className="ant-upload-hint">
            仅支持 ``.csv``；UTF-8 编码；文件 ≤ 5MB；header 行为列名。
          </p>
        </Upload.Dragger>

        {oversized ? (
          <Alert
            type="error"
            showIcon
            message="文件超过 5MB 上限"
            description="请拆分 CSV 后再上传，或先用脚本聚合精简列。"
            data-testid="outcome-csv-oversized-alert"
          />
        ) : null}

        <Button
          type="primary"
          icon={<UploadOutlined />}
          loading={importMutation.isPending}
          disabled={!validFile || importMutation.isPending}
          onClick={handleSubmit}
          data-testid="outcome-csv-submit"
        >
          开始导入
        </Button>

        {summary ? (
          <div data-testid="outcome-csv-summary">
            <Descriptions
              bordered
              size="small"
              column={2}
              items={[
                { key: 'profile', label: '映射方案', children: summary.mapping_profile },
                { key: 'total', label: '总行数', children: String(summary.total_rows) },
                { key: 'inserted', label: '成功写入', children: String(summary.inserted) },
                { key: 'failed', label: '失败行数', children: String(summary.failed) },
              ]}
            />
            {(summary.errors?.length ?? 0) > 0 ? (
              <>
                <Typography.Title level={5} style={{ marginTop: 12 }}>
                  失败行（{summary.errors?.length ?? 0} 条）
                </Typography.Title>
                <Table
                  size="small"
                  pagination={{ pageSize: 10 }}
                  dataSource={makeErrorRows(summary.errors ?? [])}
                  data-testid="outcome-csv-error-table"
                  columns={[
                    {
                      title: '行号',
                      dataIndex: 'row_index',
                      key: 'row_index',
                      width: 80,
                    },
                    {
                      title: '原因',
                      dataIndex: 'reason',
                      key: 'reason',
                      width: 240,
                    },
                    {
                      title: '原始数据',
                      dataIndex: 'raw_row',
                      key: 'raw_row',
                      ellipsis: true,
                    },
                  ]}
                />
              </>
            ) : null}
          </div>
        ) : null}
      </Space>
    </div>
  )
}

export default OutcomeCsvImport
