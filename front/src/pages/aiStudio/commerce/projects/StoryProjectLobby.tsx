/**
 * 剧情带货项目大厅（Story Project Lobby）。
 *
 * 镜像 `aiStudio/project/ProjectLobby` 的「网格 + 右侧速览侧栏」布局，
 * 但只展示 commerce_story 类型项目；过滤 / 数据加载 / 提交均通过
 * TanStack Query hooks（queries.ts）完成，不直接接触 service。
 *
 * 页面职责（参照 jellyfish-product-boundary 与 W8 计划）：
 * - 展示已创建的剧情带货项目卡片列表。
 * - 悬停 / 点击项目卡片更新右侧速览。
 * - 通过「新建」按钮唤起 StoryProjectCreateModal 进入创建流。
 * - 不承担提取确认 / 视频生成职责（后者由 W8-T3 StoryWorkbench 负责）。
 */
import React, { useMemo, useState } from 'react'
import { useNavigate } from 'react-router-dom'
import { Card, Row, Col, Button, Input, Space, Tag, Empty } from 'antd'
import { PlusOutlined, EnterOutlined } from '@ant-design/icons'
import { useStoryProjectList, useStoryFormulaList } from './queries'
import StoryProjectCard from './StoryProjectCard'
import StoryProjectCreateModal from './StoryProjectCreateModal'
import type { StoryFormulaRead, StoryProjectRead } from '../../../../services/generated'

/** 平台 → 中文映射（与 StoryProjectCard 保持一致以避免视觉跳变） */
const PLATFORM_LABEL: Record<string, string> = {
  douyin: '抖音',
  kuaishou: '快手',
  xiaohongshu: '小红书',
  youtube: 'YouTube',
  tiktok: 'TikTok',
}

const COMPLIANCE_REGION_LABEL: Record<string, string> = {
  cn_mainland: '中国大陆',
  hk_tw: '港澳台',
  overseas: '海外',
}

const StoryProjectLobby: React.FC = () => {
  const navigate = useNavigate()
  const [search, setSearch] = useState('')
  const [createOpen, setCreateOpen] = useState(false)
  const [selectedId, setSelectedId] = useState<string | null>(null)

  const { data: projects, isLoading } = useStoryProjectList()
  const { data: formulas } = useStoryFormulaList()

  /**
   * 公式 id → 公式对象的索引，便于 O(1) 查找用于卡片展示。
   * 公式列表为系统级且数量极小（≤10），构建索引几乎零成本。
   */
  const formulaById = useMemo<Record<string, StoryFormulaRead>>(() => {
    const acc: Record<string, StoryFormulaRead> = {}
    for (const f of formulas ?? []) {
      acc[f.id] = f
    }
    return acc
  }, [formulas])

  /**
   * 关键词过滤（项目名 + 描述）。
   * 排序保留接口默认顺序（创建时间倒序），暂不引入额外排序键。
   */
  const filtered = useMemo<StoryProjectRead[]>(() => {
    const list: StoryProjectRead[] = projects ?? []
    const keyword = search.trim().toLowerCase()
    if (!keyword) return list
    return list.filter((p: StoryProjectRead) => {
      return (
        p.name.toLowerCase().includes(keyword) ||
        (p.description ?? '').toLowerCase().includes(keyword)
      )
    })
  }, [projects, search])

  const selectedProject = useMemo<StoryProjectRead | null>(() => {
    if (!filtered.length) return null
    if (selectedId) {
      return filtered.find((p: StoryProjectRead) => p.id === selectedId) ?? filtered[0]
    }
    return filtered[0]
  }, [filtered, selectedId])

  const selectedFormula =
    selectedProject?.config?.formula_id ? formulaById[selectedProject.config.formula_id] : null

  const handleEnter = (projectId: string) => {
    navigate(`/commerce/projects/${projectId}`)
  }

  return (
    <div className="flex min-h-0 flex-1 flex-col overflow-hidden">
      {/* 顶部操作区：标题 / 搜索 / 新建 */}
      <div className="sticky top-0 z-10 flex-shrink-0 bg-gradient-to-b from-[rgba(249,250,251,0.96)] to-[rgba(249,250,251,0.9)] pb-2 backdrop-blur">
        <div className="flex flex-wrap items-center justify-between gap-2">
          <Space size="small" className="min-w-[240px] flex-1">
            <h2 className="m-0 text-base font-semibold text-gray-800">剧情带货项目</h2>
            <Input.Search
              placeholder="搜索项目名称或描述"
              allowClear
              size="small"
              className="w-64 max-w-full"
              onSearch={setSearch}
              onChange={(e) => setSearch(e.target.value)}
            />
          </Space>
          <Space size="small">
            <Button
              type="primary"
              size="small"
              className="text-[11px]"
              icon={<PlusOutlined />}
              onClick={() => setCreateOpen(true)}
            >
              新建
            </Button>
          </Space>
        </div>
      </div>

      {/* 主体区：左侧卡片网格 + 右侧速览侧栏 */}
      <div className="min-h-0 flex-1 overflow-auto">
        <Row gutter={12}>
          <Col xs={24} lg={18}>
            <Row gutter={[12, 12]}>
              {!isLoading && filtered.length === 0 && (
                <Col span={24}>
                  <Card>
                    <Empty
                      description={
                        search
                          ? '没有匹配的剧情带货项目'
                          : '暂无剧情带货项目，点击右上角创建第一个'
                      }
                    >
                      {!search && (
                        <Button
                          type="primary"
                          icon={<PlusOutlined />}
                          onClick={() => setCreateOpen(true)}
                        >
                          新建剧情带货项目
                        </Button>
                      )}
                    </Empty>
                  </Card>
                </Col>
              )}
              {filtered.map((p: StoryProjectRead) => (
                <Col key={p.id} xs={24} sm={12} lg={8}>
                  <StoryProjectCard
                    project={p}
                    formula={p.config?.formula_id ? formulaById[p.config.formula_id] ?? null : null}
                    selected={selectedProject?.id === p.id}
                    onSelect={setSelectedId}
                    onEnter={handleEnter}
                  />
                </Col>
              ))}
            </Row>
          </Col>

          <Col xs={24} lg={6} className="flex-shrink-0">
            <div className="h-full">
              <Card
                size="small"
                title="项目速览"
                className="mb-1.5"
                bodyStyle={{ padding: 10 }}
                headStyle={{ minHeight: 36, paddingInline: 10 }}
              >
                {selectedProject ? (
                  <div className="space-y-2">
                    <div>
                      <div className="mb-0.5 text-[11px] text-gray-500">项目名称</div>
                      <div className="font-medium">{selectedProject.name}</div>
                    </div>
                    <div>
                      <div className="mb-0.5 text-[11px] text-gray-500">描述</div>
                      <div className="line-clamp-3 text-xs text-gray-600">
                        {selectedProject.description || '暂无描述'}
                      </div>
                    </div>
                    <div>
                      <div className="mb-0.5 text-[11px] text-gray-500">题材 / 视觉</div>
                      <div className="flex flex-wrap gap-1">
                        <Tag color="geekblue" className="mr-0 text-[11px] leading-4">
                          {selectedProject.style}
                        </Tag>
                        <Tag color="default" className="mr-0 text-[11px] leading-4">
                          {selectedProject.visual_style}
                        </Tag>
                      </div>
                    </div>
                    <div>
                      <div className="mb-0.5 text-[11px] text-gray-500">带货配置</div>
                      <div className="space-y-0.5 text-[11px] text-gray-600">
                        <div>
                          目标平台：
                          {PLATFORM_LABEL[selectedProject.config?.target_platform ?? 'douyin'] ??
                            selectedProject.config?.target_platform ??
                            '—'}
                        </div>
                        <div>目标时长：{selectedProject.config?.target_duration_sec ?? '—'} 秒</div>
                        <div>剧情公式：{selectedFormula?.name ?? '未选公式'}</div>
                        <div>
                          合规地域：
                          {COMPLIANCE_REGION_LABEL[
                            selectedProject.config?.compliance_region ?? 'cn_mainland'
                          ] ??
                            selectedProject.config?.compliance_region ??
                            '—'}
                        </div>
                        <div>种子：{selectedProject.seed}</div>
                      </div>
                    </div>
                    <Button
                      type="primary"
                      block
                      size="small"
                      className="text-[11px]"
                      icon={<EnterOutlined />}
                      onClick={() => handleEnter(selectedProject.id)}
                    >
                      进入工作台
                    </Button>
                  </div>
                ) : (
                  <div className="py-6 text-center text-sm text-gray-500">
                    悬停或点击项目卡片查看详情
                  </div>
                )}
              </Card>
            </div>
          </Col>
        </Row>
      </div>

      <StoryProjectCreateModal open={createOpen} onClose={() => setCreateOpen(false)} />
    </div>
  )
}

export default StoryProjectLobby
