/**
 * 公式库 (FormulaLibrary) 页面。
 *
 * 页面定位：
 * - 系统级剧情公式的**只读浏览面板**（W11-T1 后总计 12 条：6 cn + 6 global）。
 * - P2 阶段不提供编辑能力，与商品库的"准备/编辑"双形态截然不同；这里只做"查阅"。
 *
 * 范式锚点：
 * - 列表数据走 `useFormulaLibraryList`（TanStack Query），与 ProductLibrary 保持一致。
 * - 详情通过 Drawer 展示，单选受控；关闭后清空 `selectedId`，防止脏 Query 被反复触发。
 * - 顶部仅提供地域过滤；分类过滤通过表头 `filters` 内联（避免新增控件影响布局）。
 */
import React, { useMemo, useState } from 'react'
import {
  Button,
  Card,
  Collapse,
  Descriptions,
  Drawer,
  Empty,
  List,
  Select,
  Space,
  Spin,
  Table,
  Tag,
  Typography,
} from 'antd'
import type { ColumnsType } from 'antd/es/table'
import { ScrollablePage } from '../../components/ScrollablePage'
import {
  useFormulaLibraryDetail,
  useFormulaLibraryList,
} from './queries'
import type { StoryFormulaRead } from '../../../../services/generated'

const { Paragraph, Text } = Typography

/** 地域过滤下拉选项；与后端 `FormulaRegion` 严格对齐。 */
const REGION_FILTER_OPTIONS = [
  { value: 'cn', label: '中国 (cn)' },
  { value: 'global', label: '国际 (global)' },
]

/**
 * 把 region 字符串渲染为带颜色的 Tag。
 * - cn → red（醒目，强调本土向）
 * - global → blue（与 cn 对比，沉稳）
 */
function renderRegionTag(region: string) {
  return <Tag color={region === 'cn' ? 'red' : 'blue'}>{region}</Tag>
}

/**
 * 公式详情视图：完整呈现一条 StoryFormula 的所有字段。
 *
 * 布局：
 * - 顶部用 Descriptions 紧凑展示元信息（名称 / 地域 / 分类 / 时长 / 镜头数 / 模板）。
 * - 心理学原理 / 适用场景 / 禁忌场景 / 风险标记 各占一节，便于编辑/合规人员对照阅读。
 * - 节拍结构使用 List 展开，逐条 beat 显示功能、时长、景别、运镜。
 * - 示例剧本默认折叠（Collapse），避免长文本压垮抽屉首屏。
 */
const FormulaDetailView: React.FC<{ formula: StoryFormulaRead }> = ({
  formula,
}) => {
  const beats = formula.structure?.beats ?? []
  const totalShotsRange = formula.structure?.total_shots_range
  const durationRange = formula.structure?.duration_sec_range
  const useCases = formula.use_cases ?? []
  const avoidCases = formula.avoid_cases ?? []
  const riskFlags = formula.risk_flags ?? []

  return (
    <div className="space-y-4">
      <Descriptions column={2} size="small" bordered>
        <Descriptions.Item label="ID">{formula.id}</Descriptions.Item>
        <Descriptions.Item label="地域">
          {renderRegionTag(formula.region)}
        </Descriptions.Item>
        <Descriptions.Item label="分类">{formula.category}</Descriptions.Item>
        <Descriptions.Item label="排序">{formula.sort_order}</Descriptions.Item>
        <Descriptions.Item label="典型时长">
          {`${formula.typical_duration_sec}s`}
          {durationRange && durationRange.length === 2
            ? `（范围 ${durationRange[0]}~${durationRange[1]}s）`
            : null}
        </Descriptions.Item>
        <Descriptions.Item label="典型镜头数">
          {formula.typical_shot_count}
          {totalShotsRange && totalShotsRange.length === 2
            ? `（范围 ${totalShotsRange[0]}~${totalShotsRange[1]}）`
            : null}
        </Descriptions.Item>
        <Descriptions.Item label="提示词模板" span={2}>
          <Text code>{formula.prompt_template_id}</Text>
        </Descriptions.Item>
      </Descriptions>

      <Card size="small" title="心理学原理">
        <Paragraph className="!mb-0 whitespace-pre-wrap">
          {formula.psychology}
        </Paragraph>
      </Card>

      <div className="grid grid-cols-1 md:grid-cols-2 gap-3">
        <Card size="small" title="适用场景">
          {useCases.length === 0 ? (
            <Empty image={Empty.PRESENTED_IMAGE_SIMPLE} description="无" />
          ) : (
            <ul className="!mb-0 pl-5 list-disc">
              {useCases.map((c) => (
                <li key={c}>{c}</li>
              ))}
            </ul>
          )}
        </Card>
        <Card size="small" title="禁忌场景">
          {avoidCases.length === 0 ? (
            <Empty image={Empty.PRESENTED_IMAGE_SIMPLE} description="无" />
          ) : (
            <ul className="!mb-0 pl-5 list-disc">
              {avoidCases.map((c) => (
                <li key={c}>{c}</li>
              ))}
            </ul>
          )}
        </Card>
      </div>

      <Card
        size="small"
        title={
          <Space>
            <span>风险标记</span>
            <Tag>{riskFlags.length}</Tag>
          </Space>
        }
      >
        {riskFlags.length === 0 ? (
          <Text type="secondary">无</Text>
        ) : (
          <Space wrap>
            {riskFlags.map((flag) => (
              <Tag key={flag} color="orange">
                {flag}
              </Tag>
            ))}
          </Space>
        )}
      </Card>

      <Card
        size="small"
        title={
          <Space>
            <span>节拍结构</span>
            <Tag>{beats.length} 拍</Tag>
          </Space>
        }
      >
        {beats.length === 0 ? (
          <Empty image={Empty.PRESENTED_IMAGE_SIMPLE} description="暂无节拍" />
        ) : (
          <List
            size="small"
            dataSource={beats}
            renderItem={(beat, idx) => (
              <List.Item key={beat.id}>
                <List.Item.Meta
                  title={
                    <Space>
                      <Tag color="purple">{`#${idx + 1}`}</Tag>
                      <Text strong>{beat.id}</Text>
                      <Tag>{`${beat.duration_sec}s`}</Tag>
                      <Tag color="geekblue">{beat.shot_type}</Tag>
                      {beat.recommended_camera_movement ? (
                        <Tag color="cyan">{beat.recommended_camera_movement}</Tag>
                      ) : (
                        <Tag>静态</Tag>
                      )}
                    </Space>
                  }
                  description={beat.function}
                />
              </List.Item>
            )}
          />
        )}
      </Card>

      <Collapse
        items={[
          {
            key: 'sample',
            label: '示例剧本（变量化）',
            children: (
              <Paragraph className="!mb-0 whitespace-pre-wrap">
                {formula.sample_dialog}
              </Paragraph>
            ),
          },
        ]}
      />
    </div>
  )
}

/**
 * 公式库主视图。
 *
 * 状态管理：
 * - `region`：地域过滤；`undefined` 表示全部。
 * - `selectedId`：当前查看详情的公式 ID；为 `null` 时抽屉关闭。
 *
 * 列定义：
 * - `category` 自动从当前数据集中聚合，作为表格内置过滤项，避免硬编码枚举。
 */
const FormulaLibrary: React.FC = () => {
  const [region, setRegion] = useState<string | undefined>(undefined)
  const [selectedId, setSelectedId] = useState<string | null>(null)

  const { data: formulas, isLoading } = useFormulaLibraryList(region)
  const { data: detail, isLoading: isDetailLoading } = useFormulaLibraryDetail(
    selectedId ?? '',
  )

  /** 从当前数据集中聚合分类，用于列内置过滤。 */
  const categoryFilters = useMemo(() => {
    const set = new Set<string>()
    const list: StoryFormulaRead[] = formulas ?? []
    list.forEach((f) => set.add(f.category))
    return Array.from(set).map((c) => ({ text: c, value: c }))
  }, [formulas])

  const columns: ColumnsType<StoryFormulaRead> = [
    {
      title: '名称',
      dataIndex: 'name',
      key: 'name',
      render: (value: string, record) => (
        <Space>
          <Text strong>{value}</Text>
          <Text type="secondary" className="text-xs">
            {record.id}
          </Text>
        </Space>
      ),
    },
    {
      title: '地域',
      dataIndex: 'region',
      key: 'region',
      width: 120,
      render: (v: string) => renderRegionTag(v),
    },
    {
      title: '分类',
      dataIndex: 'category',
      key: 'category',
      filters: categoryFilters,
      onFilter: (value, record) => record.category === value,
    },
    {
      title: '典型时长',
      dataIndex: 'typical_duration_sec',
      key: 'typical_duration_sec',
      width: 120,
      render: (v: number) => `${v}s`,
      sorter: (a, b) => a.typical_duration_sec - b.typical_duration_sec,
    },
    {
      title: '镜头数',
      dataIndex: 'typical_shot_count',
      key: 'typical_shot_count',
      width: 100,
      sorter: (a, b) => a.typical_shot_count - b.typical_shot_count,
    },
    {
      title: '风险标记',
      dataIndex: 'risk_flags',
      key: 'risk_flags',
      render: (flags?: string[]) => {
        const list = flags ?? []
        if (list.length === 0) return <Text type="secondary">—</Text>
        return (
          <Space wrap>
            {list.map((f) => (
              <Tag key={f} color="orange">
                {f}
              </Tag>
            ))}
          </Space>
        )
      },
    },
    {
      title: '操作',
      key: 'action',
      width: 110,
      render: (_value, record) => (
        <Button size="small" onClick={() => setSelectedId(record.id)}>
          查看详情
        </Button>
      ),
    },
  ]

  return (
    <ScrollablePage className="pr-1">
      <Card
        title={
          <Space>
            <span>剧情公式库</span>
            <Tag>{`${formulas?.length ?? 0} 个`}</Tag>
          </Space>
        }
        extra={
          <Space>
            <Select
              allowClear
              placeholder="按地域过滤"
              value={region}
              onChange={(v) => setRegion(v)}
              options={REGION_FILTER_OPTIONS}
              style={{ width: 160 }}
            />
          </Space>
        }
      >
        <Spin spinning={isLoading}>
          <Table<StoryFormulaRead>
            dataSource={formulas ?? []}
            rowKey="id"
            columns={columns}
            pagination={{ pageSize: 20, showSizeChanger: false }}
            size="middle"
            locale={{
              emptyText: (
                <Empty
                  image={Empty.PRESENTED_IMAGE_SIMPLE}
                  description="暂无公式"
                />
              ),
            }}
          />
        </Spin>
      </Card>

      <Drawer
        title={
          detail ? (
            <Space>
              <span>{detail.name}</span>
              {renderRegionTag(detail.region)}
              <Tag color="default">{detail.category}</Tag>
            </Space>
          ) : (
            '公式详情'
          )
        }
        open={selectedId !== null}
        onClose={() => setSelectedId(null)}
        width={760}
        destroyOnClose
      >
        <Spin spinning={isDetailLoading}>
          {detail ? (
            <FormulaDetailView formula={detail} />
          ) : (
            <Empty
              image={Empty.PRESENTED_IMAGE_SIMPLE}
              description="加载中…"
            />
          )}
        </Spin>
      </Drawer>
    </ScrollablePage>
  )
}

export default FormulaLibrary
