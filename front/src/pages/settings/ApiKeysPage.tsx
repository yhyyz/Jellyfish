/**
 * ApiKeysPage — admin 用 API Key 管理页（W24-T5，P4 Wave B 7/11）。
 *
 * 路由：``/settings/api-keys``。
 *
 * 页面职责：
 *   - 列表：拉取 ``GET /api/v1/settings/api-keys``（默认仅 active），
 *     由 ``include_inactive`` 切换是否包含已 revoke。
 *   - 创建：弹 ``ApiKeyCreateModal`` 调用 ``POST /api/v1/settings/api-
 *     keys``，成功后只展示一次明文 + 自动刷新列表。
 *   - 撤销：表格内 ``Popconfirm`` 触发 ``POST /api/v1/settings/api-
 *     keys/revoke`` 软删，更新缓存。
 *   - 用量聚合条：在页头展示「全局活跃 key 总数 + 当日总消耗 + 当月
 *     总消耗」三项静态指标，作为 sparkline 的兜底实现；后端单条
 *     ``ApiKeyUsageRead`` 仅有标量，没有时序点位，故此处不引入
 *     @ant-design/charts 重 chunk。
 *
 * 权限门：当前 SaaS admin 接口尚无 RBAC，沿用 ``settings.api_key``
 *   的静态 admin token 占位（由请求头透传，未在 UI 显式暴露）；
 *
 *   TODO(P5)：接 RBAC 后用 ``useAppStore`` 的 user.role/permissions 控
 *   制本页可见性，并替换占位。当前阶段保持任何登录用户可访问以解
 *   锁前端验收链路。
 */
import React, { useMemo, useState } from 'react'
import {
  Alert,
  Button,
  Card,
  Col,
  Divider,
  Row,
  Space,
  Statistic,
  Switch,
  Typography,
  message,
} from 'antd'
import { PlusOutlined, ReloadOutlined } from '@ant-design/icons'
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'

import {
  SettingsApiKeysService,
  type ApiKeyCreateRequest,
  type ApiKeyCreated,
  type ApiKeyRead,
} from '../../services/generated'
import { ScrollablePage } from '../aiStudio/components/ScrollablePage'
import { ApiKeyCreateModal } from './components/ApiKeyCreateModal'
import { ApiKeyTable } from './components/ApiKeyTable'

const { Title, Paragraph, Text } = Typography

/**
 * react-query key factory：列表按 ``includeInactive`` 维度分槽，避免
 * 切换过滤态后命中过期缓存。
 */
const apiKeyQueryKeys = {
  all: ['settings', 'api-keys'] as const,
  list: (includeInactive: boolean) =>
    [...apiKeyQueryKeys.all, 'list', includeInactive] as const,
}

/**
 * 拉取 API key 列表；薄封装 generated client，统一兜底为 ``[]``。
 */
function useApiKeyList(includeInactive: boolean) {
  return useQuery({
    queryKey: apiKeyQueryKeys.list(includeInactive),
    queryFn: async (): Promise<ApiKeyRead[]> => {
      const res =
        await SettingsApiKeysService.listApiKeysEndpointApiV1SettingsApiKeysGet({
          includeInactive,
        })
      return res.data ?? []
    },
  })
}

/**
 * 计算页头聚合统计：活跃 key 数 / 全列表当日总消耗 / 当月总消耗。
 * 抽函数便于单测；输入空数组返回全 0。
 */
export function aggregateUsage(keys: ApiKeyRead[]): {
  activeCount: number
  totalToday: number
  totalMonth: number
  totalKeys: number
} {
  let activeCount = 0
  let totalToday = 0
  let totalMonth = 0
  for (const k of keys) {
    if (k.is_active) activeCount += 1
    totalToday += k.consumed_today ?? 0
    totalMonth += k.consumed_this_month ?? 0
  }
  return {
    activeCount,
    totalToday,
    totalMonth,
    totalKeys: keys.length,
  }
}

const ApiKeysPage: React.FC = () => {
  const qc = useQueryClient()
  const [includeInactive, setIncludeInactive] = useState(false)
  const [createOpen, setCreateOpen] = useState(false)
  const [revokingHash, setRevokingHash] = useState<string | null>(null)

  const { data, isLoading, error, refetch, isFetching } = useApiKeyList(includeInactive)

  /** 创建 mutation：成功后由 modal 自行展示明文，外部仅刷新列表缓存 */
  const createMutation = useMutation({
    mutationFn: async (req: ApiKeyCreateRequest): Promise<ApiKeyCreated> => {
      const res =
        await SettingsApiKeysService.createApiKeyEndpointApiV1SettingsApiKeysPost({
          requestBody: req,
        })
      if (!res.data) {
        throw new Error('创建失败：后端未返回明文 key')
      }
      return res.data
    },
    onSuccess: () => {
      void qc.invalidateQueries({ queryKey: apiKeyQueryKeys.all })
    },
  })

  /** 撤销 mutation：成功后局部 invalidate；失败给 message 提示 */
  const revokeMutation = useMutation({
    mutationFn: async (hash: string): Promise<void> => {
      await SettingsApiKeysService.revokeApiKeyEndpointApiV1SettingsApiKeysRevokePost({
        requestBody: { api_key_hash: hash },
      })
    },
    onMutate: (hash) => {
      setRevokingHash(hash)
    },
    onSuccess: () => {
      message.success('已撤销')
      void qc.invalidateQueries({ queryKey: apiKeyQueryKeys.all })
    },
    onError: (err: unknown) => {
      message.error((err as Error)?.message ?? '撤销失败')
    },
    onSettled: () => {
      setRevokingHash(null)
    },
  })

  const list = data ?? []
  const stats = useMemo(() => aggregateUsage(list), [list])

  return (
    <ScrollablePage className="pr-1">
      <Card
        title={
          <div className="flex items-center gap-2">
            <Title level={4} className="!m-0">
              API Keys
            </Title>
            <Text type="secondary" style={{ fontSize: 13 }}>
              SaaS 调用方密钥管理
            </Text>
          </div>
        }
        extra={
          <Space>
            <Space size={4}>
              <Text type="secondary">含已撤销</Text>
              <Switch
                checked={includeInactive}
                onChange={setIncludeInactive}
                data-testid="toggle-include-inactive"
              />
            </Space>
            <Button
              icon={<ReloadOutlined />}
              onClick={() => void refetch()}
              loading={isFetching && !isLoading}
            >
              刷新
            </Button>
            <Button
              type="primary"
              icon={<PlusOutlined />}
              onClick={() => setCreateOpen(true)}
              data-testid="open-create-modal-btn"
            >
              新建 Key
            </Button>
          </Space>
        }
      >
        <Paragraph type="secondary" className="!mb-3">
          管理调用方使用的 API key、配额与状态。明文仅创建时一次性返回，请妥善保存。
        </Paragraph>

        <Row gutter={16} className="mb-4" data-testid="usage-stats-row">
          <Col xs={12} sm={6}>
            <Statistic title="活跃 Key" value={stats.activeCount} />
          </Col>
          <Col xs={12} sm={6}>
            <Statistic title="总 Key 数" value={stats.totalKeys} />
          </Col>
          <Col xs={12} sm={6}>
            <Statistic title="今日总消耗" value={stats.totalToday} />
          </Col>
          <Col xs={12} sm={6}>
            <Statistic title="本月总消耗" value={stats.totalMonth} />
          </Col>
        </Row>

        <Divider className="!my-3" />

        {error ? (
          <Alert
            type="error"
            showIcon
            message="加载 API Key 列表失败"
            description={(error as Error).message}
            action={
              <Button size="small" onClick={() => void refetch()}>
                重试
              </Button>
            }
          />
        ) : (
          <ApiKeyTable
            data={list}
            loading={isLoading}
            onRevoke={(hash) => revokeMutation.mutate(hash)}
            revokingHash={revokingHash}
          />
        )}
      </Card>

      <ApiKeyCreateModal
        open={createOpen}
        onCancel={() => setCreateOpen(false)}
        onCreated={() => {
          // modal 内已切到 reveal 阶段；这里只负责刷新列表缓存
          void qc.invalidateQueries({ queryKey: apiKeyQueryKeys.all })
        }}
        onCreate={(req) => createMutation.mutateAsync(req)}
      />
    </ScrollablePage>
  )
}

export default ApiKeysPage
