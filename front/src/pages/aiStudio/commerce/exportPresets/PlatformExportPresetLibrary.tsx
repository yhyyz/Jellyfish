/**
 * PlatformExportPresetLibrary — 平台导出预设库浏览页（W23-T1，P4 Wave A）。
 *
 * 页面定位：
 * - 系统级（5 套：抖音 / 快手 / 小红书 / YouTube Shorts / TikTok）+ 用户级
 *   PlatformExportPreset 的**只读浏览面板**，给后续多平台导出能力提供参数模板目录。
 * - 编辑、克隆、删除等管理能力延后到 W23-T2 + 渲染管线落地后再开放，UI 仅做查询。
 *
 * 数据 & 交互：
 * - 列表数据走 `usePlatformExportPresets({ platform })`，底层调 OpenAPI generated
 *   `StudioPlatformExportPresetsService.listPlatformExportPresetsEndpoint*`
 *   （AGENTS.md 规则 #2，禁止手写 service）。
 * - 顶部工具栏：platform 下拉，缺省 `null` 为"全部"；切换会驱动 query key 变化、
 *   自动 refetch 对应平台的列表。
 * - 主体：3 列响应式 grid，每张卡片展示 platform tag + name + 画幅 / 时长 /
 *   编码 / 响度 4 项关键参数与说明描述。
 *
 * 状态：
 * - loading → antd Skeleton；error → antd Alert + 重试按钮；空集合 → antd Empty。
 *
 * 路由：
 * - `/commerce/export-presets`，由 `App.tsx` 统一懒加载注册。
 */
import React, { useMemo, useState } from 'react'
import {
  Alert,
  Button,
  Card,
  Empty,
  Select,
  Skeleton,
  Space,
  Tag,
} from 'antd'
import { useTranslation } from 'react-i18next'
import { useQuery } from '@tanstack/react-query'

import {
  StudioPlatformExportPresetsService,
  type PlatformExportPresetRead,
} from '../../../../services/generated'
import { ScrollablePage } from '../../components/ScrollablePage'

/**
 * 平台过滤候选；保持与后端 :class:`Platform` 枚举的字符串值对齐。
 *
 * 用 `null` 表示"全部"以避免与字符串值冲突。
 */
const PLATFORM_OPTIONS: { value: string | null; label: string }[] = [
  { value: null, label: '全部' },
  { value: 'douyin', label: '抖音' },
  { value: 'kuaishou', label: '快手' },
  { value: 'xiaohongshu', label: '小红书' },
  { value: 'youtube', label: 'YouTube Shorts' },
  { value: 'tiktok', label: 'TikTok' },
]

/**
 * react-query key factory；platform 维度独立缓存槽。
 */
const platformExportPresetKeys = {
  all: ['studio', 'platform-export-presets'] as const,
  list: (platform: string | null) =>
    [...platformExportPresetKeys.all, 'list', platform] as const,
}

/**
 * 拉取平台导出预设列表（按 platform 过滤）。
 *
 * 仅做最薄封装：调用 OpenAPI generated client，把响应里的 `data` 兜底成空数组返回。
 */
function usePlatformExportPresets(platform: string | null) {
  return useQuery({
    queryKey: platformExportPresetKeys.list(platform),
    queryFn: async (): Promise<PlatformExportPresetRead[]> => {
      const res =
        await StudioPlatformExportPresetsService.listPlatformExportPresetsEndpointApiV1StudioPlatformExportPresetsGet(
          { platform },
        )
      return res.data ?? []
    },
  })
}

/**
 * 单张预设卡片的渲染入参。
 */
interface PresetCardProps {
  preset: PlatformExportPresetRead
}

/**
 * 单张预设卡片：platform tag + name + 4 项核心参数 + 描述。
 *
 * 设计原则：
 *  - 视觉密度参考 VoicePackLibrary，保持平台小卡 + 标签矩阵的样式一致。
 *  - 卡片本身不带交互（不打开抽屉、不路由跳转），W23-T1 仅承担"看清楚有什么参数"。
 */
const PresetCard: React.FC<PresetCardProps> = ({ preset }) => {
  const { t } = useTranslation('commerce')

  return (
    <Card
      role="listitem"
      aria-label={preset.name}
      size="small"
      className="h-full"
      title={
        <div className="flex items-center gap-2 min-w-0">
          <Tag color="geekblue" className="!m-0 shrink-0">
            {preset.platform}
          </Tag>
          <span className="font-medium text-slate-800 truncate">
            {preset.name}
          </span>
        </div>
      }
      extra={
        preset.is_system ? (
          <Tag color="default" className="!m-0">
            system
          </Tag>
        ) : null
      }
    >
      <div className="flex flex-col gap-1 text-xs text-slate-600">
        <Space size={4} wrap>
          <Tag className="!m-0">
            {t('platformExportPresetLibrary.aspectRatio')}: {preset.aspect_ratio}
          </Tag>
          <Tag className="!m-0">
            {t('platformExportPresetLibrary.maxDuration')}:{' '}
            {preset.max_duration_sec}s
          </Tag>
          <Tag className="!m-0">
            {t('platformExportPresetLibrary.codec')}: {preset.codec_preset}
          </Tag>
          <Tag className="!m-0">
            {t('platformExportPresetLibrary.loudness')}:{' '}
            {preset.loudness_lufs.toFixed(1)} LUFS
          </Tag>
        </Space>
        {preset.description ? (
          <div className="mt-1 text-slate-500 break-words whitespace-pre-wrap">
            {preset.description}
          </div>
        ) : null}
      </div>
    </Card>
  )
}

/**
 * 平台导出预设库主视图。
 *
 * 状态：
 * - `platform`：当前过滤平台，缺省 `null`（全部）。
 */
export const PlatformExportPresetLibrary: React.FC = () => {
  const { t } = useTranslation('commerce')
  const [platform, setPlatform] = useState<string | null>(null)

  const query = usePlatformExportPresets(platform)

  // 防御式：后端已按 platform 过滤；客户端再过一遍以防缓存命中漂移。
  const filtered = useMemo<PlatformExportPresetRead[]>(
    () =>
      (query.data ?? []).filter((preset: PlatformExportPresetRead) =>
        platform == null ? true : preset.platform === platform,
      ),
    [query.data, platform],
  )

  /** 顶部工具栏：platform 下拉。 */
  const toolbar = (
    <Space wrap>
      <Select
        aria-label="platform-export-preset-platform"
        value={platform}
        onChange={(v) => setPlatform(v ?? null)}
        options={PLATFORM_OPTIONS}
        style={{ width: 180 }}
        placeholder={t('platformExportPresetLibrary.filterPlatform')}
      />
    </Space>
  )

  /**
   * 主体内容渲染：根据 query 状态分支为 loading / error / empty / grid。
   */
  let body: React.ReactNode
  if (query.isLoading) {
    body = (
      <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-3 gap-3">
        {[0, 1, 2].map((i) => (
          <Skeleton key={i} active title={false} paragraph={{ rows: 3 }} />
        ))}
      </div>
    )
  } else if (query.isError) {
    body = (
      <Alert
        type="error"
        showIcon
        message={t('platformExportPresetLibrary.loadFailed')}
        action={
          <Button size="small" onClick={() => void query.refetch()}>
            {t('platformExportPresetLibrary.retry')}
          </Button>
        }
      />
    )
  } else if (filtered.length === 0) {
    body = (
      <Empty
        image={Empty.PRESENTED_IMAGE_SIMPLE}
        description={t('platformExportPresetLibrary.empty')}
      />
    )
  } else {
    body = (
      <div
        role="list"
        aria-label="platform-export-presets"
        className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-3 gap-3"
      >
        {filtered.map((preset) => (
          <PresetCard key={preset.id} preset={preset} />
        ))}
      </div>
    )
  }

  return (
    <ScrollablePage className="pr-1">
      <Card
        title={
          <Space>
            <span>{t('platformExportPresetLibrary.pageTitle')}</span>
            <Tag>{`${filtered.length}`}</Tag>
          </Space>
        }
        extra={toolbar}
      >
        {body}
      </Card>
    </ScrollablePage>
  )
}

export default PlatformExportPresetLibrary
