/**
 * 剧情带货项目卡片。
 *
 * 在 StoryProjectLobby 网格中展示单个项目的概览：项目名、目标平台 / 时长 /
 * 公式名等关键 commerce_story 配置；并提供「进入工作台」入口跳转到
 * StoryWorkbench（W8-T3）。
 *
 * 设计要点：
 * - 仅做纯展示与回调透传，不直接调用 service / 不持有数据加载逻辑。
 * - 缺失 `config` 时降级为「未配置」标签，避免空指针。
 * - 鼠标悬停时通过 `onSelect` 通知父组件更新右侧速览侧栏。
 */
import React from 'react'
import { Card, Tag, Button, Space } from 'antd'
import { EnterOutlined, FundProjectionScreenOutlined } from '@ant-design/icons'
import type { StoryProjectRead, StoryFormulaRead } from '../../../../services/generated'

/** 平台枚举 → 中文展示名映射（与后端 Platform 枚举严格对齐） */
const PLATFORM_LABEL: Record<string, string> = {
  douyin: '抖音',
  kuaishou: '快手',
  xiaohongshu: '小红书',
  youtube: 'YouTube',
  tiktok: 'TikTok',
}

/** 合规地域 → 中文展示名 */
const COMPLIANCE_REGION_LABEL: Record<string, string> = {
  cn_mainland: '中国大陆',
  hk_tw: '港澳台',
  overseas: '海外',
}

/**
 * 根据项目 ID 生成稳定的浅色渐变背景。
 *
 * 与 ProjectLobby 同样的策略：纯函数 + 哈希取模，确保同一项目每次渲染
 * 颜色一致。封面图缺失时作为兜底视觉。
 */
function getGradientByProjectId(id: string): string {
  const gradients = [
    'from-rose-100 via-rose-50 to-white',
    'from-orange-100 via-orange-50 to-white',
    'from-amber-100 via-amber-50 to-white',
    'from-emerald-100 via-emerald-50 to-white',
    'from-sky-100 via-sky-50 to-white',
    'from-indigo-100 via-indigo-50 to-white',
    'from-fuchsia-100 via-fuchsia-50 to-white',
  ]
  let hash = 0
  for (let i = 0; i < id.length; i += 1) {
    hash = (hash * 31 + id.charCodeAt(i)) >>> 0
  }
  return gradients[hash % gradients.length]
}

export interface StoryProjectCardProps {
  /** 项目数据，含 1:1 CommerceStoryConfig */
  project: StoryProjectRead
  /** 当前项目使用的剧情公式（用于显示中文名）；可为空 */
  formula?: StoryFormulaRead | null
  /** 是否处于选中态（外层控制），决定边框高亮 */
  selected?: boolean
  /** 卡片被选中（点击 / 悬停）时通知外层 */
  onSelect: (projectId: string) => void
  /** 「进入工作台」按钮被点击时通知外层导航 */
  onEnter: (projectId: string) => void
}

/**
 * 单个剧情带货项目展示卡片。
 *
 * 展示三部分信息：
 * 1. 头部色块：项目名 + 题材标签 + 渐变兜底封面。
 * 2. 中部信息：目标平台 / 目标时长 / 剧情公式 / 合规地域 标签。
 * 3. 底部操作：进入工作台。
 */
const StoryProjectCard: React.FC<StoryProjectCardProps> = ({
  project,
  formula,
  selected = false,
  onSelect,
  onEnter,
}) => {
  const config = project.config ?? null
  const platformKey = config?.target_platform ?? 'douyin'
  const platformLabel = PLATFORM_LABEL[platformKey] ?? platformKey
  const durationSec = config?.target_duration_sec ?? 60
  const formulaName = formula?.name ?? (config?.formula_id ? '未知公式' : '未选公式')
  const regionKey = config?.compliance_region ?? 'cn_mainland'
  const regionLabel = COMPLIANCE_REGION_LABEL[regionKey] ?? regionKey

  return (
    <Card
      hoverable
      size="small"
      className={`h-full cursor-pointer transition-all duration-200 ${
        selected ? 'ring-2 ring-rose-500 ring-offset-1' : 'hover:shadow-lg'
      }`}
      bodyStyle={{ padding: 10 }}
      onClick={() => onSelect(project.id)}
      onMouseEnter={() => onSelect(project.id)}
    >
      <div
        className={`relative mb-2 flex h-20 items-center justify-center rounded bg-gradient-to-br ${getGradientByProjectId(
          project.id,
        )} overflow-hidden`}
      >
        <FundProjectionScreenOutlined className="text-3xl text-rose-300" />
        <div className="absolute right-1.5 top-1.5">
          <Tag color="magenta" className="mr-0 text-[11px] leading-4">
            带货剧情
          </Tag>
        </div>
      </div>

      <div className="mb-1.5 min-w-0">
        <div className="text-[11px] text-gray-500">{project.style}</div>
        <div className="truncate text-sm font-semibold text-gray-900">{project.name}</div>
        {project.description ? (
          <div className="mt-0.5 line-clamp-1 text-[11px] text-gray-500">{project.description}</div>
        ) : null}
      </div>

      <div className="mb-2 flex flex-wrap gap-1">
        <Tag color="blue" className="mr-0 text-[11px] leading-4">
          {platformLabel}
        </Tag>
        <Tag color="cyan" className="mr-0 text-[11px] leading-4">
          {durationSec}s
        </Tag>
        <Tag color="purple" className="mr-0 text-[11px] leading-4">
          {formulaName}
        </Tag>
        <Tag color="default" className="mr-0 text-[11px] leading-4">
          {regionLabel}
        </Tag>
      </div>

      <div className="flex items-center justify-between border-t border-gray-100 pt-1.5">
        <span className="truncate text-[11px] text-gray-400">种子 {project.seed}</span>
        <Space size="small" onClick={(e) => e.stopPropagation()}>
          <Button
            type="primary"
            size="small"
            icon={<EnterOutlined />}
            className="text-[11px]"
            onClick={() => onEnter(project.id)}
          >
            进入工作台
          </Button>
        </Space>
      </div>
    </Card>
  )
}

export default StoryProjectCard
