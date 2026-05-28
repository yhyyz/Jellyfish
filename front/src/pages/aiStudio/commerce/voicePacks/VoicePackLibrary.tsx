/**
 * VoicePackLibrary — 商品音色库浏览页（W20-T5；W29 增加自定义音色 + clone_status + 轮询）。
 *
 * 页面定位：
 * - 系统级 + 用户级 VoicePack 的浏览面板，给商品视频生成提供候选音色目录。
 * - W20: 只读浏览（系统级），上传定制以 stub 占位。
 * - W29: 加上自定义音色管理：上传 → 训练 → 状态 badge → 自动轮询 → 删除。
 *
 * 数据 & 交互：
 * - 系统级 VoicePack 走 `useVoicePacks(languageCode)`（已有 W20-T2 实现）。
 * - 自定义 VoicePack 走 W29 新增的 `useCustomVoicePacks(null, { refetchInterval })`：
 *   - 任一行 clone_status=deploying 时本地 setInterval 10s 自动 refetch；
 *   - 全部进入终态后 clearInterval。
 * - 顶部工具栏：language 下拉 + 上传定制音色按钮（打开 W29 完整 Modal）。
 * - 每张自定义音色卡片右上角带 clone_status badge（deploying / ready / failed / deleted）。
 *   failed 行 hover tooltip 显示 failure_reason；deleted 行整行灰显。
 *
 * 状态：
 * - loading → antd Skeleton；error → antd Alert + 重试按钮；空集合 → antd Empty。
 */
import React, { useEffect, useMemo, useRef, useState } from 'react'
import {
  Alert,
  Badge,
  Button,
  Card,
  Empty,
  Popconfirm,
  Select,
  Skeleton,
  Space,
  Tag,
  Tooltip,
  message as antdMessage,
} from 'antd'
import {
  CaretRightOutlined,
  CheckCircleFilled,
  CloseCircleFilled,
  DeleteOutlined,
  LoadingOutlined,
  UploadOutlined,
} from '@ant-design/icons'
import { useTranslation } from 'react-i18next'

import type {
  CustomVoiceListItem,
  VoicePackRead,
} from '../../../../services/generated'
import { ScrollablePage } from '../../components/ScrollablePage'
import { resolveAssetUrl } from '../../assets/utils'
import {
  useCustomVoicePacks,
  useDeleteCustomVoicePack,
  useVoicePacks,
} from '../projects/workbench.queries'
import { VoicePackUploadModal } from './VoicePackUploadModal'

/**
 * language 过滤候选；保持与后端 seed VoicePack 的 language_code 对齐。
 * W29 起加入 ja-JP / ko-KR 海外档（W29-T10 海外 seed 后启用）。
 */
const LANGUAGE_OPTIONS = [
  { value: 'zh-CN', label: 'zh-CN' },
  { value: 'en-US', label: 'en-US' },
  { value: 'ja-JP', label: 'ja-JP' },
  { value: 'ko-KR', label: 'ko-KR' },
]

/** 单 active player 共享类型：把 ref 透给上层切换控制。 */
interface VoicePackCardProps {
  pack: VoicePackRead
  onPlay: (audio: HTMLAudioElement | null) => void
  playLabel: string
}

/**
 * 单张系统级音色卡片（W20-T5 原有渲染逻辑保留）。
 */
const VoicePackCard: React.FC<VoicePackCardProps> = ({
  pack,
  onPlay,
  playLabel,
}) => {
  const audioRef = useRef<HTMLAudioElement | null>(null)
  const sampleUrl = resolveAssetUrl(pack.sample_file_id ?? null)

  return (
    <Card
      role="listitem"
      aria-label={pack.name}
      size="small"
      className="h-full"
      title={
        <div className="flex items-center gap-2 min-w-0">
          <Tag color="geekblue" className="!m-0 shrink-0">
            {pack.provider}
          </Tag>
          <span className="font-medium text-slate-800 truncate">
            {pack.name}
          </span>
        </div>
      }
      extra={
        pack.is_system ? (
          <Tag color="default" className="!m-0">
            system
          </Tag>
        ) : null
      }
    >
      <div className="flex items-center justify-between gap-2">
        <Space size={4} wrap>
          {pack.gender ? <Tag className="!m-0">{pack.gender}</Tag> : null}
          {pack.archetype_hint ? (
            <Tag color="purple" className="!m-0">
              {pack.archetype_hint}
            </Tag>
          ) : null}
          <Tag className="!m-0">{pack.language_code}</Tag>
        </Space>
        <Button
          size="small"
          type="text"
          icon={<CaretRightOutlined />}
          aria-label={`play ${pack.name}`}
          disabled={!sampleUrl}
          onClick={() => onPlay(audioRef.current)}
        >
          {playLabel}
        </Button>
        <audio ref={audioRef} src={sampleUrl} preload="none" />
      </div>
    </Card>
  )
}

/**
 * 单条自定义音色卡片（W29 新增）。
 *
 * - clone_status=deploying：蓝色 spinner badge + 卡片半透明
 * - clone_status=ready：绿色 ✓ badge
 * - clone_status=failed：红色 ✗ badge + tooltip 显示 description 末尾的 failure_reason
 * - clone_status=deleted：灰色 badge + 整张卡片灰显（默认列表会过滤，仅 audit 模式可见）
 */
interface CustomVoicePackCardProps {
  item: CustomVoiceListItem
  onDelete: (voicePackId: string) => void
  deletingId: string | null
}

const CustomVoicePackCard: React.FC<CustomVoicePackCardProps> = ({
  item,
  onDelete,
  deletingId,
}) => {
  const { t } = useTranslation('commerce')
  const status = item.clone_status as
    | 'deploying'
    | 'ready'
    | 'failed'
    | 'deleted'
    | null

  let badgeNode: React.ReactNode = null
  if (status === 'deploying') {
    badgeNode = (
      <Tag
        icon={<LoadingOutlined spin />}
        color="processing"
        className="!m-0"
        aria-label="clone-status-deploying"
      >
        {t('voicePackLibrary.cloneStatus.deploying')}
      </Tag>
    )
  } else if (status === 'ready') {
    badgeNode = (
      <Tag
        icon={<CheckCircleFilled />}
        color="success"
        className="!m-0"
        aria-label="clone-status-ready"
      >
        {t('voicePackLibrary.cloneStatus.ready')}
      </Tag>
    )
  } else if (status === 'failed') {
    const reason = (item.description || '')
      .split('[clone_failed]')
      .slice(1)
      .join('[clone_failed]')
      .trim()
    const badge = (
      <Tag
        icon={<CloseCircleFilled />}
        color="error"
        className="!m-0"
        aria-label="clone-status-failed"
      >
        {t('voicePackLibrary.cloneStatus.failed')}
      </Tag>
    )
    badgeNode = reason ? (
      <Tooltip title={reason}>{badge}</Tooltip>
    ) : (
      badge
    )
  } else if (status === 'deleted') {
    badgeNode = (
      <Tag color="default" className="!m-0" aria-label="clone-status-deleted">
        {t('voicePackLibrary.cloneStatus.deleted')}
      </Tag>
    )
  }

  const isDeploying = status === 'deploying'
  const isDeleted = status === 'deleted'

  return (
    <Card
      role="listitem"
      aria-label={item.name}
      size="small"
      className={`h-full ${isDeleted ? 'opacity-50' : ''}`}
      title={
        <div className="flex items-center gap-2 min-w-0">
          <Tag color="geekblue" className="!m-0 shrink-0">
            {item.provider}
          </Tag>
          <span className="font-medium text-slate-800 truncate">
            {item.name}
          </span>
        </div>
      }
      extra={
        <Space size={4}>
          {badgeNode}
          {!isDeleted ? (
            <Popconfirm
              title={t('voicePackLibrary.deleteConfirm')}
              onConfirm={() => onDelete(item.id)}
              okButtonProps={{ loading: deletingId === item.id }}
              okText={t('voicePackLibrary.deleteOk')}
              cancelText={t('voicePackLibrary.deleteCancel')}
            >
              <Button
                size="small"
                type="text"
                danger
                icon={<DeleteOutlined />}
                aria-label={`delete ${item.name}`}
              />
            </Popconfirm>
          ) : null}
        </Space>
      }
    >
      <Space size={4} wrap>
        {item.gender ? <Tag className="!m-0">{item.gender}</Tag> : null}
        <Tag className="!m-0">{item.language_code}</Tag>
        {item.target_model ? (
          <Tag className="!m-0">{item.target_model}</Tag>
        ) : null}
        {item.region ? <Tag className="!m-0">{item.region}</Tag> : null}
        {isDeploying ? (
          <span className="text-xs text-slate-500">
            {t('voicePackLibrary.cloneStatus.deployingHint')}
          </span>
        ) : null}
      </Space>
    </Card>
  )
}

/**
 * 商品音色库主视图。
 */
export const VoicePackLibrary: React.FC = () => {
  const { t } = useTranslation('commerce')
  const [languageCode, setLanguageCode] = useState<string>('zh-CN')
  const [uploadOpen, setUploadOpen] = useState(false)

  const query = useVoicePacks(languageCode)

  const filtered = useMemo<VoicePackRead[]>(
    () =>
      (query.data ?? []).filter(
        (pack: VoicePackRead) => pack.language_code === languageCode,
      ),
    [query.data, languageCode],
  )

  const activePlayerRef = useRef<HTMLAudioElement | null>(null)
  const handlePlay = (audio: HTMLAudioElement | null) => {
    if (!audio) return
    if (activePlayerRef.current && activePlayerRef.current !== audio) {
      activePlayerRef.current.pause()
    }
    activePlayerRef.current = audio
    const result = audio.play()
    if (result && typeof (result as Promise<void>).then === 'function') {
      ;(result as Promise<void>).catch(() => {
        /* noop */
      })
    }
  }

  // ------ W29 自定义音色 + 自动轮询 ------
  const [customRefetchInterval, setCustomRefetchInterval] = useState<
    number | false
  >(false)
  const customQuery = useCustomVoicePacks(null, {
    refetchInterval: customRefetchInterval,
  })

  /**
   * 列表里只要还有一行 clone_status=deploying，就把 refetchInterval 调到 10s；
   * 全部进入终态后清零，避免静默轮询。
   */
  useEffect(() => {
    const hasDeploying = (customQuery.data ?? []).some(
      (item: CustomVoiceListItem) => item.clone_status === 'deploying',
    )
    setCustomRefetchInterval(hasDeploying ? 10000 : false)
  }, [customQuery.data])

  const deleteMutation = useDeleteCustomVoicePack()
  const onDelete = (voicePackId: string) => {
    deleteMutation.mutate(voicePackId, {
      onSuccess: () => {
        antdMessage.success(t('voicePackLibrary.deleteSuccess'))
      },
      onError: () => {
        antdMessage.error(t('voicePackLibrary.deleteFailed'))
      },
    })
  }

  const playLabel = t('voicePackPicker.play')

  const toolbar = (
    <Space wrap>
      <Select
        aria-label="voice-pack-language"
        value={languageCode}
        onChange={(v) => setLanguageCode(v)}
        options={LANGUAGE_OPTIONS}
        style={{ width: 140 }}
      />
      <Button
        type="primary"
        icon={<UploadOutlined />}
        onClick={() => setUploadOpen(true)}
      >
        {t('voicePackLibrary.uploadCustom')}
      </Button>
    </Space>
  )

  /** 系统级音色 grid 渲染。 */
  let systemBody: React.ReactNode
  if (query.isLoading) {
    systemBody = (
      <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-3 gap-3">
        {[0, 1, 2].map((i) => (
          <Skeleton key={i} active title={false} paragraph={{ rows: 2 }} />
        ))}
      </div>
    )
  } else if (query.isError) {
    systemBody = (
      <Alert
        type="error"
        showIcon
        message={t('voicePackLibrary.loadFailed')}
        action={
          <Button size="small" onClick={() => void query.refetch()}>
            {t('voicePackLibrary.retry')}
          </Button>
        }
      />
    )
  } else if (filtered.length === 0) {
    systemBody = (
      <Empty
        image={Empty.PRESENTED_IMAGE_SIMPLE}
        description={t('voicePackLibrary.empty')}
      />
    )
  } else {
    systemBody = (
      <div
        role="list"
        aria-label="voice-packs"
        className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-3 gap-3"
      >
        {filtered.map((pack) => (
          <VoicePackCard
            key={pack.id}
            pack={pack}
            onPlay={handlePlay}
            playLabel={playLabel}
          />
        ))}
      </div>
    )
  }

  /** 自定义音色 grid 渲染。 */
  const customItems = customQuery.data ?? []
  let customBody: React.ReactNode
  if (customQuery.isLoading) {
    customBody = (
      <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-3 gap-3">
        {[0, 1].map((i) => (
          <Skeleton
            key={`custom-skel-${i}`}
            active
            title={false}
            paragraph={{ rows: 2 }}
          />
        ))}
      </div>
    )
  } else if (customQuery.isError) {
    customBody = (
      <Alert
        type="error"
        showIcon
        message={t('voicePackLibrary.customLoadFailed')}
      />
    )
  } else if (customItems.length === 0) {
    customBody = (
      <Empty
        image={Empty.PRESENTED_IMAGE_SIMPLE}
        description={t('voicePackLibrary.customEmpty')}
      />
    )
  } else {
    customBody = (
      <div
        role="list"
        aria-label="custom-voice-packs"
        className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-3 gap-3"
      >
        {customItems.map((item: CustomVoiceListItem) => (
          <CustomVoicePackCard
            key={item.id}
            item={item}
            onDelete={onDelete}
            deletingId={
              deleteMutation.isPending
                ? (deleteMutation.variables as string | null)
                : null
            }
          />
        ))}
      </div>
    )
  }

  return (
    <ScrollablePage className="pr-1">
      <Card
        title={
          <Space>
            <span>{t('voicePackLibrary.pageTitle')}</span>
            <Tag>{`${filtered.length}`}</Tag>
          </Space>
        }
        extra={toolbar}
      >
        {systemBody}
      </Card>

      <Card
        className="mt-3"
        title={
          <Space>
            <span>{t('voicePackLibrary.customSectionTitle')}</span>
            <Badge count={customItems.length} showZero color="#1677ff" />
          </Space>
        }
      >
        {customBody}
      </Card>

      <VoicePackUploadModal
        open={uploadOpen}
        onClose={() => setUploadOpen(false)}
        onCreated={() => {
          // 创建后立即拉一次最新列表，让新行带 deploying 状态出现
          void customQuery.refetch()
        }}
      />
    </ScrollablePage>
  )
}

export default VoicePackLibrary
