/**
 * 合规中心 (ComplianceCenter) 独立页面，路径：`/commerce/compliance`。
 *
 * 页面定位（参照 W13 计划与 AGENTS.md「分镜带货」职责边界约定）：
 * - 这是一个**只读**的合规可视化入口。P1 阶段后端只暴露查询接口
 *   （profile 列表/详情、按 variant 拉 finding），写入接口（创建 profile、
 *   标记 finding 已解决等）暂未开放，本页因此**不提供任何编辑能力**。
 * - 写规则编辑器属于 P3 范围，落地前不要在本页插入临时表单——
 *   保持「只读 viewer」语义清晰。
 *
 * 三个 Tab：
 * 1. 规则集 Profile：列出系统预置 profile（默认 3 条），点击展开规则速览。
 * 2. findings 历史：按 variant_id (+ 严重度) 拉取该变体下的检测结果。
 * 3. 规则浏览：选中某 profile 后以 pretty-printed JSON 展示其 rules 数组。
 *
 * 视觉规则：
 * - 严重度色板：blocker = red，warning = orange，info = blue；
 *   与 backend `ComplianceFindingRead.severity` 字符串严格对齐。
 * - 地域色板：cn_mainland = blue（合规重灾区），hk_tw = purple，overseas = geekblue；
 *   仅作直观区分，无业务语义。
 */
import React, { useEffect, useMemo, useState } from 'react'
import {
  Alert,
  Button,
  Card,
  Empty,
  Input,
  message,
  Select,
  Space,
  Spin,
  Table,
  Tabs,
  Tag,
  Typography,
} from 'antd'
import { CopyOutlined, ReloadOutlined } from '@ant-design/icons'
import type { ColumnsType } from 'antd/es/table'
import { ScrollablePage } from '../../components/ScrollablePage'
import {
  useComplianceFindingList,
  useComplianceProfileDetail,
  useComplianceProfileList,
} from './queries'
import type {
  ComplianceFindingRead,
  ComplianceProfileRead,
} from '../../../../services/generated'

const { Text, Paragraph } = Typography

/**
 * 严重度 → antd Tag color 映射；任何未列出值统一回退到 default 灰色，
 * 避免后端新增 severity 时前端崩溃。
 */
const SEVERITY_COLOR: Record<string, string> = {
  blocker: 'red',
  warning: 'orange',
  info: 'blue',
}

/**
 * 严重度 → 中文显示名映射；同样兜底原始字符串。
 */
const SEVERITY_LABEL: Record<string, string> = {
  blocker: '阻断',
  warning: '警告',
  info: '提示',
}

/**
 * 地域 → 中文显示名映射，与 StoryProjectLobby 保持一致以避免视觉跳变。
 */
const REGION_LABEL: Record<string, string> = {
  cn_mainland: '中国大陆',
  hk_tw: '港澳台',
  overseas: '海外',
}

const REGION_COLOR: Record<string, string> = {
  cn_mainland: 'blue',
  hk_tw: 'purple',
  overseas: 'geekblue',
}

type ComplianceTabKey = 'profiles' | 'findings' | 'rules'

/**
 * 安全的 JSON 美化函数。任何序列化异常都回退到 `String(value)`，
 * 避免 viewer 因循环引用等极端输入直接白屏。
 */
function prettyJson(value: unknown): string {
  try {
    return JSON.stringify(value, null, 2)
  } catch {
    return String(value)
  }
}

/** ---------------- Tab 1: 规则集 Profile ---------------- */

/**
 * 列出所有系统预置 profile。点击行时展开内嵌的「规则速览」表格，
 * 展示每条规则的 id / kind / severity / 简要描述（若有）。
 *
 * Profile 列表本身不分页，规模极小（默认 3 条），全部铺平在 Card 下即可。
 */
const ProfilesTab: React.FC = () => {
  const { data, isLoading, isFetching, refetch } = useComplianceProfileList()
  const profiles = data ?? []

  const columns: ColumnsType<ComplianceProfileRead> = [
    {
      title: 'Profile ID',
      dataIndex: 'id',
      key: 'id',
      width: 220,
      render: (id: string) => <Text code>{id}</Text>,
    },
    {
      title: '名称',
      dataIndex: 'name',
      key: 'name',
      width: 200,
    },
    {
      title: '地域',
      dataIndex: 'region',
      key: 'region',
      width: 120,
      render: (region: string) => (
        <Tag color={REGION_COLOR[region] ?? 'default'}>
          {REGION_LABEL[region] ?? region}
        </Tag>
      ),
    },
    {
      title: '规则数',
      key: 'rule_count',
      width: 100,
      render: (_, record) => (
        <Text strong>{record.rules?.length ?? 0}</Text>
      ),
    },
    {
      title: '类型',
      dataIndex: 'is_system',
      key: 'is_system',
      width: 100,
      render: (isSystem: boolean) =>
        isSystem ? (
          <Tag color="gold">系统预置</Tag>
        ) : (
          <Tag color="default">自定义</Tag>
        ),
    },
    {
      title: '说明',
      dataIndex: 'description',
      key: 'description',
      ellipsis: true,
    },
  ]

  return (
    <div className="space-y-3">
      <Space>
        <Button
          icon={<ReloadOutlined />}
          onClick={() => void refetch()}
          loading={isFetching}
        >
          刷新
        </Button>
        <Text type="secondary">
          共 {profiles.length} 条预置 profile（点击展开查看规则速览）
        </Text>
      </Space>
      <Table<ComplianceProfileRead>
        rowKey="id"
        loading={isLoading}
        columns={columns}
        dataSource={profiles}
        pagination={false}
        expandable={{
          expandedRowRender: (record) => (
            <RuleSummaryTable rules={record.rules ?? []} />
          ),
          rowExpandable: (record) => (record.rules?.length ?? 0) > 0,
        }}
      />
    </div>
  )
}

/**
 * 在 ProfilesTab 行展开区域里展示每条规则的关键字段。
 *
 * 与「规则浏览」Tab 的 JSON viewer 互补：
 * - 此处偏摘要，便于快速扫读规则结构；
 * - JSON viewer 给出完整原文，供后端/审计核对。
 */
const RuleSummaryTable: React.FC<{ rules: Array<Record<string, any>> }> = ({
  rules,
}) => {
  const columns: ColumnsType<Record<string, any>> = [
    {
      title: 'rule_id',
      dataIndex: 'id',
      key: 'id',
      width: 220,
      render: (v: unknown) => <Text code>{String(v ?? '-')}</Text>,
    },
    {
      title: 'kind',
      dataIndex: 'kind',
      key: 'kind',
      width: 160,
      render: (v: unknown) => <Tag>{String(v ?? '-')}</Tag>,
    },
    {
      title: 'severity',
      dataIndex: 'severity',
      key: 'severity',
      width: 120,
      render: (v: unknown) => {
        const s = String(v ?? 'info')
        return (
          <Tag color={SEVERITY_COLOR[s] ?? 'default'}>
            {SEVERITY_LABEL[s] ?? s}
          </Tag>
        )
      },
    },
    {
      title: '说明',
      dataIndex: 'description',
      key: 'description',
      ellipsis: true,
      render: (v: unknown) => String(v ?? '-'),
    },
  ]
  if (!rules.length) {
    return <Empty description="该 profile 暂无规则" />
  }
  return (
    <Table
      rowKey={(row, idx) => String((row as { id?: unknown }).id ?? idx)}
      columns={columns}
      dataSource={rules}
      pagination={false}
      size="small"
    />
  )
}

/** ---------------- Tab 2: findings 历史 ---------------- */

/**
 * 按 variant_id + 严重度过滤展示 finding 历史。
 *
 * 后端要求 `variant_id` 必填，因此本 Tab 在用户输入前显示引导提示，
 * 用户输入并按下「查询」后才真正发请求。`severity` 可选，'all' 表示不过滤。
 */
const FindingsTab: React.FC = () => {
  const [variantInput, setVariantInput] = useState('')
  const [variantQuery, setVariantQuery] = useState('')
  const [severity, setSeverity] = useState<string>('all')

  const { data, isFetching, isLoading } = useComplianceFindingList(
    variantQuery || undefined,
    severity,
  )
  const findings = data ?? []

  const handleQuery = () => {
    const trimmed = variantInput.trim()
    if (!trimmed) {
      void message.warning('请先输入 variant_id')
      return
    }
    setVariantQuery(trimmed)
  }

  const columns: ColumnsType<ComplianceFindingRead> = [
    {
      title: '严重度',
      dataIndex: 'severity',
      key: 'severity',
      width: 100,
      render: (s: string) => (
        <Tag color={SEVERITY_COLOR[s] ?? 'default'}>
          {SEVERITY_LABEL[s] ?? s}
        </Tag>
      ),
    },
    {
      title: 'rule_id',
      dataIndex: 'rule_id',
      key: 'rule_id',
      width: 200,
      render: (v: string) => <Text code>{v}</Text>,
    },
    {
      title: 'rule_kind',
      dataIndex: 'rule_kind',
      key: 'rule_kind',
      width: 160,
      render: (v: string) => <Tag>{v}</Tag>,
    },
    {
      title: '描述',
      dataIndex: 'description',
      key: 'description',
      ellipsis: true,
    },
    {
      title: '位置',
      dataIndex: 'location',
      key: 'location',
      width: 200,
      ellipsis: true,
      render: (v: string | null | undefined) => v ?? '-',
    },
    {
      title: '建议修复',
      dataIndex: 'suggested_fix',
      key: 'suggested_fix',
      ellipsis: true,
      render: (v: string | null | undefined) => v ?? '-',
    },
    {
      title: '检测时间',
      dataIndex: 'detected_at',
      key: 'detected_at',
      width: 180,
      render: (v: string) => new Date(v).toLocaleString(),
    },
    {
      title: '已解决',
      dataIndex: 'is_resolved',
      key: 'is_resolved',
      width: 100,
      render: (v: boolean) =>
        v ? (
          <Tag color="green">已解决</Tag>
        ) : (
          <Tag color="default">未解决</Tag>
        ),
    },
  ]

  return (
    <div className="space-y-3">
      <Space wrap>
        <Input
          placeholder="输入 variant_id 后回车或点击查询"
          value={variantInput}
          onChange={(e) => setVariantInput(e.target.value)}
          onPressEnter={handleQuery}
          style={{ width: 320 }}
          allowClear
        />
        <Select
          value={severity}
          onChange={setSeverity}
          style={{ width: 140 }}
          options={[
            { value: 'all', label: '全部严重度' },
            { value: 'blocker', label: '阻断 blocker' },
            { value: 'warning', label: '警告 warning' },
            { value: 'info', label: '提示 info' },
          ]}
        />
        <Button type="primary" onClick={handleQuery} loading={isFetching}>
          查询
        </Button>
      </Space>

      {!variantQuery ? (
        <Alert
          showIcon
          type="info"
          message="请先输入 variant_id 查询合规检测历史"
          description="后端按变体维度记录 finding；P1 阶段未提供「全量列表」入口，仅支持按 variant 拉取。"
        />
      ) : (
        <Spin spinning={isLoading}>
          <Table<ComplianceFindingRead>
            rowKey="id"
            columns={columns}
            dataSource={findings}
            pagination={{ pageSize: 20, showSizeChanger: false }}
            locale={{ emptyText: '该变体暂无 finding 记录' }}
          />
        </Spin>
      )}
    </div>
  )
}

/** ---------------- Tab 3: 规则浏览（只读 JSON viewer） ---------------- */

/**
 * 选中一个 profile 后以 pretty-printed JSON 展示其 rules 数组。
 *
 * 设计要点：
 * - **只读**：本页明确不提供编辑能力，避免与 P3 的写规则编辑器冲突。
 * - 复制按钮直接调用 `navigator.clipboard`；失败时回退到提示。
 * - JSON 文本块用等宽字体 + 浅灰背景，避免与正文字体冲突。
 */
const RulesViewerTab: React.FC = () => {
  const { data: profiles, isLoading: isListLoading } =
    useComplianceProfileList()
  const [selectedId, setSelectedId] = useState<string | null>(null)

  // 当 profile 列表首次加载完成时，默认选中第一项，避免空状态
  useEffect(() => {
    if (!selectedId && profiles && profiles.length > 0) {
      setSelectedId(profiles[0].id)
    }
  }, [profiles, selectedId])

  const { data: detail, isFetching: isDetailFetching } =
    useComplianceProfileDetail(selectedId)

  const jsonText = useMemo(
    () => prettyJson(detail?.rules ?? []),
    [detail?.rules],
  )

  const handleCopy = async () => {
    try {
      await navigator.clipboard.writeText(jsonText)
      void message.success('已复制规则 JSON 到剪贴板')
    } catch {
      void message.error('复制失败：浏览器拒绝访问剪贴板')
    }
  }

  const profileOptions = (profiles ?? []).map((p: ComplianceProfileRead) => ({
    value: p.id,
    label: `${p.name} (${p.id})`,
  }))

  return (
    <div className="space-y-3">
      <Space wrap>
        <Select
          loading={isListLoading}
          value={selectedId ?? undefined}
          onChange={(v) => setSelectedId(v)}
          options={profileOptions}
          style={{ minWidth: 320 }}
          placeholder="选择要查看的 profile"
        />
        <Button
          icon={<CopyOutlined />}
          onClick={() => void handleCopy()}
          disabled={!detail}
        >
          复制 JSON
        </Button>
        {detail && (
          <Tag color={REGION_COLOR[detail.region] ?? 'default'}>
            {REGION_LABEL[detail.region] ?? detail.region}
          </Tag>
        )}
        {detail && (
          <Text type="secondary">
            共 {detail.rules?.length ?? 0} 条规则
          </Text>
        )}
      </Space>

      <Spin spinning={isDetailFetching}>
        {detail ? (
          <pre
            style={{
              margin: 0,
              padding: 16,
              background: '#0f172a',
              color: '#e2e8f0',
              borderRadius: 6,
              fontFamily:
                '"JetBrains Mono", "SF Mono", "Fira Code", Consolas, monospace',
              fontSize: 12.5,
              lineHeight: 1.6,
              maxHeight: '60vh',
              overflow: 'auto',
            }}
          >
            <code>{jsonText}</code>
          </pre>
        ) : (
          <Empty description="请先选择 profile" />
        )}
        {detail?.description && (
          <Paragraph type="secondary" style={{ marginTop: 8 }}>
            {detail.description}
          </Paragraph>
        )}
      </Spin>
    </div>
  )
}

/** ---------------- 主页面 ---------------- */

/**
 * 渲染合规中心三 Tab 容器。Tag extra 上标注 P1 当前规则总量，
 * 与 W11-T4 规则扩展保持一致：3 profile + 8 cn 规则 + 9 P2 扩展规则。
 */
const ComplianceCenter: React.FC = () => {
  const [activeTab, setActiveTab] = useState<ComplianceTabKey>('profiles')

  return (
    <ScrollablePage className="pr-1">
      <div className="space-y-4">
        <Card
          title="合规中心"
          extra={<Tag color="processing">P1：3 profiles + 8 cn 规则 + 9 P2 扩展规则</Tag>}
        >
          <Tabs
            activeKey={activeTab}
            onChange={(k) => setActiveTab(k as ComplianceTabKey)}
            items={[
              {
                key: 'profiles',
                label: '规则集 Profile',
                children: <ProfilesTab />,
              },
              {
                key: 'findings',
                label: 'findings 历史',
                children: <FindingsTab />,
              },
              {
                key: 'rules',
                label: '规则浏览',
                children: <RulesViewerTab />,
              },
            ]}
          />
        </Card>
      </div>
    </ScrollablePage>
  )
}

export default ComplianceCenter
