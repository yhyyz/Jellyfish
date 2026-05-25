/**
 * 剧情工作台（StoryWorkbench）。
 *
 * 路径：`/commerce/projects/:projectId`。
 *
 * 这是带货剧情项目的中央创作页：
 * - 顶部：项目头（项目名 + 关键配置 + 关联商品）
 * - 中部：左 VariantList + FormulaPicker + 中 ScriptEditor + 右 ComplianceWarningBanner
 * - 底部：ShotTimelineStrip
 * - 浮动 CTA：「生成新脚本」「合规检查」
 *
 * 数据组合策略：
 * - 项目详情：`useStoryProjectDetail(projectId)` —— 含 1:1 CommerceStoryConfig。
 * - 公式列表：`useStoryFormulaList(region)`，由 FormulaPicker 自行加载。
 * - 变体列表：`useStoryVariants(projectId)`，默认选中第一个作为 activeVariant。
 * - findings：`useComplianceFindings(activeVariant.id)`，仅在变体存在时启用。
 * - 关联商品：当前 `StoryProjectRead.products` 字段尚未在生成类型中暴露，
 *   P1 阶段以全局商品列表的首条作为「主推商品」兜底（足以构造
 *   ScriptGenerateRequest），并在 UI 上标注「已选首个可用商品」。
 *
 * 任务编排：
 * - `handleGenerateScript`：组合 project.config + selectedFormulaId + 主推商品快照
 *   → 调用 `useTriggerScriptGenerate()` 入队；P1 不轮询，仅 message.success 提示。
 * - `handleComplianceCheck`：基于 activeVariant.id + region + product_category
 *   入队，同样只提示，不轮询。
 *
 * 视觉要点：
 * - 全页面 `flex flex-col h-full`，中部 `flex-1 min-h-0` 防止 grid 溢出。
 * - 浮动 CTA 用 Affix 钉在右下角，与三栏布局解耦。
 */
import React, { useEffect, useMemo, useState } from 'react'
import {
  Affix,
  Alert,
  Button,
  Card,
  Col,
  Empty,
  Modal,
  Row,
  Space,
  Spin,
  Tag,
  Tooltip,
  message,
} from 'antd'
import { ArrowLeftOutlined, EditOutlined } from '@ant-design/icons'
import { useNavigate, useParams, Link } from 'react-router-dom'
import { useStoryProjectDetail } from './queries'
import {
  useComplianceFindings,
  useStoryVariants,
  useTriggerComplianceCheck,
  useTriggerScriptGenerate,
} from './workbench.queries'
import { useProductList } from '../products/queries'
import { StudioChaptersService } from '../../../../services/generated'
import type {
  ComplianceCheckRequest,
  ScriptGenerateRequest,
  StoryProjectRead,
  StoryVariantRead,
} from '../../../../services/generated'
import type { ProductRead } from '../products/queries'
import { FormulaPicker } from './components/FormulaPicker'
import { ScriptEditor } from './components/ScriptEditor'
import { ComplianceWarningBanner } from './components/ComplianceWarningBanner'
import { ShotTimelineStrip } from './components/ShotTimelineStrip'
import { VariantList } from './components/VariantList'
import { useQuery } from '@tanstack/react-query'

/** Platform 枚举 → 中文展示 */
const PLATFORM_LABEL: Record<string, string> = {
  douyin: '抖音',
  kuaishou: '快手',
  xiaohongshu: '小红书',
  youtube: 'YouTube',
  tiktok: 'TikTok',
}

/** ComplianceRegion 枚举 → 中文展示 */
const COMPLIANCE_REGION_LABEL: Record<string, string> = {
  cn_mainland: '中国大陆',
  hk_tw: '港澳台',
  overseas: '海外',
}

/**
 * 项目头组件：展示名称 / 关键配置 Tag / 关联商品摘要。
 *
 * 编辑按钮 P1 阶段先跳回 lobby（用户在 lobby 已具备配置编辑入口）；
 * 后续可以改为内联弹窗编辑。
 */
const ProjectHeader: React.FC<{
  project: StoryProjectRead
  primaryProduct: ProductRead | null
}> = ({ project, primaryProduct }) => {
  const config = project.config ?? null
  const platformKey = config?.target_platform ?? 'douyin'
  const platformLabel = PLATFORM_LABEL[platformKey] ?? platformKey
  const regionKey = config?.compliance_region ?? 'cn_mainland'
  const regionLabel = COMPLIANCE_REGION_LABEL[regionKey] ?? regionKey

  return (
    <Card size="small" className="mb-2">
      <div className="flex items-start justify-between gap-3">
        <div className="min-w-0 flex-1">
          <div className="flex items-center gap-2">
            <Link to="/commerce/projects" className="text-gray-500 hover:text-gray-700">
              <ArrowLeftOutlined />
            </Link>
            <span className="truncate text-lg font-semibold">{project.name}</span>
            <Tag color="magenta">带货剧情</Tag>
            <Tooltip title="返回项目大厅修改配置">
              <Link to="/commerce/projects">
                <Button size="small" icon={<EditOutlined />}>
                  编辑
                </Button>
              </Link>
            </Tooltip>
          </div>
          {project.description ? (
            <div className="mt-1 line-clamp-2 text-xs text-gray-500">{project.description}</div>
          ) : null}
          <Space size={4} wrap className="mt-2">
            <Tag color="blue">{platformLabel}</Tag>
            <Tag color="cyan">{config?.target_duration_sec ?? 60}s</Tag>
            <Tag color="purple">{config?.archetype ?? '未设原型'}</Tag>
            <Tag>{regionLabel}</Tag>
            {config?.target_kpi ? <Tag color="green">KPI: {config.target_kpi}</Tag> : null}
          </Space>
        </div>
        <div className="w-72 flex-shrink-0">
          <div className="text-xs font-medium text-gray-700">关联商品</div>
          {primaryProduct ? (
            <div className="mt-1 rounded border border-gray-100 p-2">
              <div className="truncate text-sm font-medium">{primaryProduct.name}</div>
              <div className="mt-0.5 line-clamp-2 text-xs text-gray-500">
                {primaryProduct.brand ? `${primaryProduct.brand} · ` : ''}
                {primaryProduct.category}
              </div>
              <div className="mt-0.5 text-[11px] text-gray-400">
                P1 简化：使用首个可用商品作为主推
              </div>
            </div>
          ) : (
            <Alert type="warning" message="暂无关联商品" showIcon className="mt-1" />
          )}
        </div>
      </div>
    </Card>
  )
}

/**
 * 剧情工作台主组件。
 */
const StoryWorkbench: React.FC = () => {
  const { projectId } = useParams<{ projectId: string }>()
  const navigate = useNavigate()

  // ---------- 数据加载 ----------
  const { data: project, isLoading: projectLoading } = useStoryProjectDetail(projectId)
  const { data: variantsData, isLoading: variantsLoading } = useStoryVariants(projectId)
  const variants: StoryVariantRead[] = variantsData ?? []
  // 全局商品列表（P1 兜底），仅取首条作为主推商品快照来源。
  const { data: productsResp } = useProductList({ page: 1, pageSize: 1 })
  const primaryProduct: ProductRead | null = productsResp?.items?.[0] ?? null

  // 当前激活变体：默认第一个；用户可在多变体场景下手动切换。
  const [activeVariantId, setActiveVariantId] = useState<string | null>(null)
  useEffect(() => {
    if (!activeVariantId && variants.length > 0) {
      setActiveVariantId(variants[0].id)
    }
  }, [variants, activeVariantId])
  const activeVariant: StoryVariantRead | null = useMemo(
    () => variants.find((v) => v.id === activeVariantId) ?? null,
    [variants, activeVariantId],
  )

  // findings：仅在 activeVariant 存在时拉取。
  const { data: findings = [] } = useComplianceFindings(activeVariant?.id ?? null)

  // 选中的剧情公式：默认跟随 project.config.formula_id。
  const [selectedFormulaId, setSelectedFormulaId] = useState<string | null>(null)
  useEffect(() => {
    if (project?.config?.formula_id && !selectedFormulaId) {
      setSelectedFormulaId(project.config.formula_id)
    }
  }, [project, selectedFormulaId])

  // 构造章节兜底：如果项目尚无章节，commerce/script-generate 需要 chapter_id。
  // P1 简化：取项目下第一个章节；没有则提示用户先创建章节。
  const { data: firstChapterId } = useQuery({
    queryKey: ['commerce', 'first-chapter', projectId ?? ''],
    enabled: !!projectId,
    queryFn: async (): Promise<string | null> => {
      if (!projectId) return null
      const res = await StudioChaptersService.listChaptersApiV1StudioChaptersGet({
        projectId,
        order: 'index',
        isDesc: false,
        page: 1,
        pageSize: 1,
      })
      const data = res.data as { items?: Array<{ id: string }> } | undefined
      return data?.items?.[0]?.id ?? null
    },
  })

  // ---------- mutations ----------
  const triggerScriptGenerate = useTriggerScriptGenerate()
  const triggerComplianceCheck = useTriggerComplianceCheck()

  /**
   * 入队脚本生成任务。
   *
   * P1 简化：从 project.config + selectedFormulaId + primaryProduct 拼装请求体；
   * 缺章节时提示用户先建章节（前端不自动创建，避免误导业务流）。
   */
  const handleGenerateScript = async () => {
    if (!project) {
      message.warning('项目尚未加载完成')
      return
    }
    if (!selectedFormulaId) {
      message.warning('请先在左侧选择一个剧情公式')
      return
    }
    if (!primaryProduct) {
      message.warning('系统暂无商品数据，请先在商品库录入至少一条商品')
      return
    }
    if (!firstChapterId) {
      Modal.confirm({
        title: '缺少章节',
        content: '当前项目还没有章节，无法发起脚本生成。是否前往项目工作台创建章节？',
        okText: '去创建章节',
        cancelText: '取消',
        onOk: () => {
          navigate(`/projects/${project.id}?tab=chapters`)
        },
      })
      return
    }
    const config = project.config
    const body: ScriptGenerateRequest = {
      project_id: project.id,
      chapter_id: firstChapterId,
      formula_id: selectedFormulaId,
      // 商品快照：worker 不会再回查 DB，确保历史可追溯。
      product: {
        id: primaryProduct.id,
        name: primaryProduct.name,
        brand: primaryProduct.brand,
        category: primaryProduct.category,
        description: primaryProduct.description,
        selling_points: primaryProduct.selling_points,
        pain_points_solved: primaryProduct.pain_points_solved,
        catchphrases: primaryProduct.catchphrases,
        price_anchor: primaryProduct.price_anchor,
        target_audience: primaryProduct.target_audience,
        health_disclaimer_required: primaryProduct.health_disclaimer_required,
      },
      audience: (config?.audience_override as Record<string, unknown> | null) ??
        (primaryProduct.target_audience as Record<string, unknown>) ?? {},
      archetype: config?.archetype ?? 'Sage',
      tone_grid: (config?.tone_grid as Record<string, unknown> | undefined) ?? {},
      target_duration_sec: config?.target_duration_sec ?? 60,
      platform: config?.target_platform ?? 'douyin',
    }
    try {
      const res = await triggerScriptGenerate.mutateAsync(body)
      message.success(`已入队脚本生成任务（task_id: ${res.task_id}），请约 30 秒后刷新查看新变体`)
    } catch (e) {
      const errMsg = e instanceof Error ? e.message : '未知错误'
      message.error(`入队失败：${errMsg}`)
    }
  }

  /**
   * 入队合规检查任务。
   *
   * 必须有 activeVariant 才能发起；region 取项目配置，product_category 取主推商品。
   */
  const handleComplianceCheck = async () => {
    if (!project) {
      message.warning('项目尚未加载完成')
      return
    }
    if (!activeVariant) {
      message.warning('请先生成或选择一个变体，再发起合规检查')
      return
    }
    const config = project.config
    const body: ComplianceCheckRequest = {
      variant_id: activeVariant.id,
      region: config?.compliance_region ?? 'cn_mainland',
      product_category: primaryProduct?.category ?? 'other',
      brand_aliases: primaryProduct?.brand ? [primaryProduct.brand, primaryProduct.name] : [],
    }
    try {
      const res = await triggerComplianceCheck.mutateAsync(body)
      message.success(
        `已入队合规检查任务（task_id: ${res.task_id}），请约 30 秒后刷新查看 findings`,
      )
    } catch (e) {
      const errMsg = e instanceof Error ? e.message : '未知错误'
      message.error(`入队失败：${errMsg}`)
    }
  }

  // ---------- 渲染 ----------
  if (projectLoading) {
    return (
      <div className="flex h-full items-center justify-center">
        <Spin size="large" />
      </div>
    )
  }

  if (!project) {
    return (
      <div className="flex h-full items-center justify-center">
        <Empty description="项目不存在或已删除" />
      </div>
    )
  }

  return (
    <div className="flex h-full flex-col p-2">
      {/* 顶部项目头 */}
      <ProjectHeader project={project} primaryProduct={primaryProduct} />

      {variantsLoading && variants.length === 0 ? (
        <div className="mb-2 text-xs text-gray-400">变体加载中...</div>
      ) : null}

      {/* 中部四栏：变体列表 / 公式选择 / 剧本编辑 / 合规提醒 */}
      <Row gutter={12} className="min-h-0 flex-1">
        <Col xs={24} lg={5} className="min-h-0">
          <VariantList
            variants={variants}
            activeVariantId={activeVariantId}
            onSelect={setActiveVariantId}
          />
        </Col>
        <Col xs={24} lg={4} className="min-h-0">
          <FormulaPicker
            selectedId={selectedFormulaId}
            onChange={setSelectedFormulaId}
            region="cn"
          />
        </Col>
        <Col xs={24} lg={10} className="min-h-0">
          <ScriptEditor variant={activeVariant} readOnly />
        </Col>
        <Col xs={24} lg={5} className="min-h-0">
          <ComplianceWarningBanner findings={findings} variant={activeVariant} />
        </Col>
      </Row>

      {/* 底部时间轴 */}
      <ShotTimelineStrip variant={activeVariant} />

      {/* 浮动 CTA */}
      <Affix offsetBottom={20}>
        <div className="flex justify-end pr-4">
          <Space>
            <Button
              type="primary"
              loading={triggerScriptGenerate.isPending}
              onClick={handleGenerateScript}
            >
              生成新脚本
            </Button>
            <Button
              loading={triggerComplianceCheck.isPending}
              onClick={handleComplianceCheck}
              disabled={!activeVariant}
            >
              合规检查
            </Button>
          </Space>
        </div>
      </Affix>
    </div>
  )
}

export default StoryWorkbench
