/**
 * AVPreviewPanel —— 分镜工作室「音视频预览」抽屉面板（W20-T4 / W31-T5 / W31-T8）。
 *
 * 这是 W20 Wave B 的入口面板：把 Wave A 已完工的 VoicePackPicker /
 * SubtitleStylePicker 嵌进来，同时把"成片预览 / 触发生成 / 跳任务中心"
 * 这条窄链路收口到一个右抽屉里。
 *
 * P5 W31 在原面板基础上加「音轨混合配置」分组：
 *   - AudioMixMode 4 段 Radio：``off`` / ``voice_only`` / ``voice_bgm`` / ``full``
 *   - mode ∈ {voice_bgm, full} 时显示 BGM 文件 Select（FileItem with type=audio）
 *   - mode = full 时再显示 SFX 文件 Select + bgm_ducking_db Slider (-30~0 dB)
 *   - 触发 chapter_av_export 时把 audio_mix_mode 直接拼进请求体
 *
 * P5 W31-T8：BGM/SFX 选择 + ducking 滑块通过新增的 PATCH 端点真持久化到
 * ``ChapterTimelineSegment``：
 *   - BGM/SFX Select onChange 立即 mutate（用户单击即写）
 *   - ducking Slider 用 antd v5 ``onChangeComplete``（松开手才 mutate），
 *     避免拖动时高频写库
 *   - audio_mix_mode 仍然是 ChapterAvExportRequest 入参，**不**触发 PATCH
 *     （它不属于 segment 持久化字段）
 *   - mutation 失败 message.error，UI 状态不回滚，让用户重试或修正
 *
 * 视图状态机（按 shot.dubbed_video_file_id 二选一）：
 *   - 已就位 → 主区域 <video controls> 直接播放最终成片
 *   - 未就位 → 主区域 antd Empty + 「立即生成成片」+「查看任务中心」
 *
 * 设计要点：
 * - 严守 AGENTS.md「工作室 = 生成」边界（前端页面职责小节）：本面板
 *   只承担"生成准备 / 触发 / 播放"，不掺资产或对白提取确认能力，
 *   提取留在分镜编辑页。
 * - 任务入队走 OpenAPI generated `CommerceTasksService.enqueue
 *   ChapterAvExportApiV1CommerceChapterAvExportPost`（AGENTS.md 规则
 *   #2，禁手写 service）。
 * - mutation.isPending 期间 disable + loading 触发按钮，避免双触发。
 * - 「查看任务中心」走 zustand `useTaskUiStore.setOpen(true)` 直接打开
 *   全局浮动任务中心面板（应用内 TaskCenter 是浮窗而非路由，
 *   见 layouts/MainLayout.tsx）。
 * - 下半部用 antd Collapse 嵌三个 picker：
 *     * 「音色」→ VoicePackPicker（默认 zh-CN）
 *     * 「字幕样式」→ SubtitleStylePicker
 *     * 「音轨混合」(W31) → AudioMixMode 4 段 + 条件 BGM/SFX 选择器 + ducking 滑块
 *   语音/字幕/AudioMixMode 仍是组件本地状态；BGM/SFX/ducking 通过 PATCH
 *   持久化到 segment（W31-T8）。
 */
import React, { useMemo, useState } from 'react'
import {
  Button,
  Collapse,
  Empty,
  Radio,
  Select,
  Slider,
  Space,
  Tooltip,
  message,
} from 'antd'
import { PlayCircleOutlined, UnorderedListOutlined } from '@ant-design/icons'
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { useTranslation } from 'react-i18next'

import {
  CommerceTasksService,
  StudioChaptersService,
  StudioFilesService,
  type ChapterTimelineSegmentAudioPatch,
  type ShotRead,
} from '../../../../../services/generated'
import { resolveAssetUrl } from '../../../assets/utils'
import { useTaskUiStore } from '../../../components/taskUiStore'
import { VoicePackPicker } from './VoicePackPicker'
import {
  SubtitleStylePicker,
  type SubtitleStyleValue,
} from './SubtitleStylePicker'

/**
 * AudioMixMode：与后端 ``app.models.types.AudioMixMode`` 枚举值严格对齐。
 *
 * 前端硬编码这一份枚举字符串而不是从 generated 类型反查，是因为生成的
 * OpenAPI 客户端把它作为 ChapterAvExportRequest.audio_mix_mode 的 string
 * 字段（默认 ``voice_only``），没有专属 enum 类型。这层薄包装 + Radio
 * 选项数组让 i18n 与 onChange 类型推断都更明确。
 */
export type AudioMixMode = 'off' | 'voice_only' | 'voice_bgm' | 'full'

const AUDIO_MIX_MODE_OPTIONS: AudioMixMode[] = [
  'off',
  'voice_only',
  'voice_bgm',
  'full',
]

/**
 * BGM 滑块边界：与后端 ``ChapterTimelineSegmentWrite.bgm_ducking_db``
 * Pydantic 校验范围（``ge=-30.0, le=0.0``）保持完全一致；变更需要同步
 * 后端 schema 与本常量。
 */
const DUCKING_DB_MIN = -30
const DUCKING_DB_MAX = 0
const DUCKING_DB_DEFAULT = -12

/** 组件入参契约。 */
export interface AVPreviewPanelProps {
  /** 当前章节 ID（chapter_av_export 的落点章节） */
  chapterId: string
  /** 当前项目 ID（用于按项目过滤 BGM/SFX 候选 FileItem） */
  projectId: string
  /** 当前选中镜头；可能为 null（未选 / 加载中均可） */
  shot?: ShotRead | null
  /**
   * 当前镜头对应的 ChapterTimelineSegment 主键。
   *
   * P5 W31-T8：BGM/SFX/ducking 通过 ``PATCH /api/v1/studio/chapters/{cid}
   * /timeline/segments/{sid}/audio`` 持久化，需要 segment_id；为空则
   * BGM/SFX/ducking 选择器仍可视化但不会发起 mutate（用户先要 PUT 一次
   * timeline 让 segment 落库）。
   */
  segmentId?: string | null
  /** 任务入队成功 callback（可选） */
  onTriggerExport?: () => void
}

/**
 * 「音视频预览」抽屉主面板。
 *
 * 内部维护多段本地状态：voicePackId / subtitleStyle / audioMixMode /
 * bgmFileId / sfxFileId / bgmDuckingDb。前两段与 audio_mix_mode 仍然只在
 * 组件内存中（语音 + 字幕 follow-up 持久化、audio_mix_mode 是 export
 * 入参）；BGM/SFX/ducking 通过 W31-T8 新增的 PATCH 端点真写回 segment。
 */
export const AVPreviewPanel: React.FC<AVPreviewPanelProps> = ({
  chapterId,
  projectId,
  shot,
  segmentId,
  onTriggerExport,
}) => {
  const { t } = useTranslation('commerce')

  const [voicePackId, setVoicePackId] = useState<string | undefined>(undefined)
  const [subtitleStyle, setSubtitleStyle] = useState<
    SubtitleStyleValue | undefined
  >(undefined)
  // P5 W31 新增本地状态：mode + BGM/SFX file_id + ducking_db
  const [audioMixMode, setAudioMixMode] = useState<AudioMixMode>('voice_only')
  const [bgmFileId, setBgmFileId] = useState<string | undefined>(undefined)
  const [sfxFileId, setSfxFileId] = useState<string | undefined>(undefined)
  const [bgmDuckingDb, setBgmDuckingDb] = useState<number>(DUCKING_DB_DEFAULT)

  /**
   * 拉项目下的音频候选 FileItem（type=audio）。
   *
   * 仅当 mode ∈ {voice_bgm, full} 时启用，避免在 voice_only/off 模式下
   * 浪费一次 list 请求。后端 listFilesApi 现暂不支持 ``usage_kind=
   * bgm_track`` 过滤（与 task spec 期望的精确过滤不一致），W31 V1 用
   * "项目下所有 audio 文件 + 前端展示 type 标签"妥协，等后端补 usage_kind
   * 查询参数后再切（W31 follow-up）。
   */
  const audioFilesQuery = useQuery({
    queryKey: ['av-preview', 'audio-files', projectId],
    enabled:
      Boolean(projectId) &&
      (audioMixMode === 'voice_bgm' || audioMixMode === 'full'),
    queryFn: async () => {
      const res = await StudioFilesService.listFilesApiApiV1StudioFilesGet({
        projectId,
        page: 1,
        pageSize: 50,
      })
      return res.data?.items ?? []
    },
  })

  const audioOptions = useMemo(() => {
    const items = audioFilesQuery.data ?? []
    return items
      .filter((f: { type?: string }) => f.type === 'audio')
      .map((f: { id: string; name?: string }) => ({
        value: f.id,
        label: f.name || f.id,
      }))
  }, [audioFilesQuery.data])

  /**
   * chapter_av_export 触发 mutation。
   *
   * 调用 OpenAPI generated client，把当前 ``audioMixMode`` 拼进请求体；
   * 成功 / 失败均通过 antd ``message`` 给用户即时反馈。
   * onSuccess 转发给父组件的可选 callback，让父级可按需做缓存失效（如刷新
   * chapter / shot 列表）。
   */
  const trigger = useMutation({
    mutationFn: async () => {
      const res =
        await CommerceTasksService.enqueueChapterAvExportApiV1CommerceChapterAvExportPost(
          {
            requestBody: {
              chapter_id: chapterId,
              // P5 W31：把当前选中的 mode 透传给 worker；voice_only 与 W19
              // 默认行为完全等价，新增 voice_bgm / full / off 在 worker
              // _build_filter_specs 内分流。
              audio_mix_mode: audioMixMode,
            },
          },
        )
      return res.data
    },
    onSuccess: (data) => {
      const taskTip = data?.task_id ? `（task_id: ${data.task_id}）` : ''
      message.success(`${t('avPreview.exportEnqueued')}${taskTip}`)
      onTriggerExport?.()
    },
    onError: (err) => {
      const errMsg = err instanceof Error ? err.message : '未知错误'
      message.error(`${t('avPreview.exportFailed')}：${errMsg}`)
    },
  })

  /**
   * P5 W31-T8：PATCH segment audio mutation。
   *
   * 把 BGM/SFX/ducking 偏量更新写回 ``ChapterTimelineSegment``。前端缺少
   * ``segmentId``（父级未提供，例如 segment 尚未通过 PUT timeline 落库）
   * 时直接 ``message.warning`` 不发请求，避免 404 噪声。
   *
   * onSuccess 失效 ``chapterTimelineKeys.detail(chapterId)``，让任何同级
   * useQuery (如 useChapterTimeline，未来引入) 自动 refetch；onError 显示
   * antd ``message.error`` 但不回滚 UI 状态——让用户看到自己刚选的值仍在
   * 屏幕上，便于纠正后重试。
   */
  const queryClient = useQueryClient()
  const patchSegmentAudio = useMutation({
    mutationFn: async (patch: ChapterTimelineSegmentAudioPatch) => {
      if (!segmentId) {
        throw new Error('segmentId is required for patch')
      }
      const res =
        await StudioChaptersService.patchChapterTimelineSegmentAudioApiV1StudioChaptersChapterIdTimelineSegmentsSegmentIdAudioPatch(
          {
            chapterId,
            segmentId,
            requestBody: patch,
          },
        )
      return res.data
    },
    onSuccess: () => {
      void queryClient.invalidateQueries({
        queryKey: ['commerce', 'chapter-timeline', 'detail', chapterId],
      })
    },
    onError: (err) => {
      const errMsg = err instanceof Error ? err.message : '未知错误'
      message.error(`${t('avPreview.audioPatchFailed')}：${errMsg}`)
    },
  })

  /**
   * BGM/SFX 选择器变更 → 立即 mutate（无 debounce：选择器是离散事件，
   * 不像滑块那样产生连续 tick）。``segmentId`` 缺失时仅更新本地 UI，不
   * 发请求（用户改 mode 后挑文件，segment 还没在 DB 里也很正常）。
   */
  const handleBgmChange = (next: string | undefined): void => {
    setBgmFileId(next)
    if (segmentId) {
      patchSegmentAudio.mutate({ bgm_file_id: next ?? null })
    }
  }
  const handleSfxChange = (next: string | undefined): void => {
    setSfxFileId(next)
    if (segmentId) {
      patchSegmentAudio.mutate({ sfx_file_id: next ?? null })
    }
  }

  /**
   * ducking 滑块：``onChange`` 仅更新本地 UI（拖动期间高频，不写库），
   * ``onAfterChange`` 在用户松开手时触发一次 mutate（antd 5.10 API；
   * v5.12+ 改名 onChangeComplete，本仓库 5.10 仍用 onAfterChange）。
   */
  const handleDuckingChange = (next: number): void => {
    setBgmDuckingDb(next)
  }
  const handleDuckingChangeComplete = (next: number): void => {
    setBgmDuckingDb(next)
    if (segmentId) {
      patchSegmentAudio.mutate({ bgm_ducking_db: next })
    }
  }

  // TaskCenter 在 layouts/MainLayout 中是常驻浮窗（非路由）；
  // 通过 zustand store 拿到 setOpen 直接打开浮窗即可。
  const setTaskCenterOpen = useTaskUiStore((state) => state.setOpen)

  const dubbedFileId = shot?.dubbed_video_file_id ?? null
  const videoUrl = dubbedFileId ? resolveAssetUrl(dubbedFileId) : undefined

  const showBgmPicker = audioMixMode === 'voice_bgm' || audioMixMode === 'full'
  const showSfxAndDucking = audioMixMode === 'full'

  return (
    <div className="flex h-full flex-col gap-3" data-testid="av-preview-panel">
      {/* 主区域：成片 video / Empty 占位 */}
      <div className="min-h-[260px]">
        {videoUrl ? (
          <video
            src={videoUrl}
            controls
            className="w-full rounded bg-black"
            data-testid="av-preview-video"
          >
            {t('avPreview.videoFallback')}
          </video>
        ) : (
          <div
            className="flex h-[260px] flex-col items-center justify-center gap-3 rounded border border-dashed border-gray-200 bg-gray-50 px-4"
            data-testid="av-preview-empty"
          >
            <Empty description={t('avPreview.emptyHint')} />
            <Space>
              <Button
                type="primary"
                icon={<PlayCircleOutlined />}
                disabled={trigger.isPending}
                loading={trigger.isPending}
                onClick={() => trigger.mutate()}
                aria-label={t('avPreview.triggerExport')}
              >
                {t('avPreview.triggerExport')}
              </Button>
              <Button
                icon={<UnorderedListOutlined />}
                onClick={() => setTaskCenterOpen(true)}
                aria-label={t('avPreview.viewTaskCenter')}
              >
                {t('avPreview.viewTaskCenter')}
              </Button>
            </Space>
          </div>
        )}
      </div>

      {/* 下半部：嵌套 picker */}
      <Collapse
        defaultActiveKey={['voice', 'audioMix']}
        items={[
          {
            key: 'voice',
            label: t('avPreview.voicePanel'),
            children: (
              <VoicePackPicker
                languageCode="zh-CN"
                value={voicePackId}
                onChange={setVoicePackId}
              />
            ),
          },
          {
            key: 'subtitle',
            label: t('avPreview.subtitlePanel'),
            children: (
              <SubtitleStylePicker
                value={subtitleStyle}
                onChange={setSubtitleStyle}
              />
            ),
          },
          {
            key: 'audioMix',
            label: t('avPreview.audioMixModePanel'),
            children: (
              <div
                className="flex flex-col gap-3"
                data-testid="av-preview-audio-mix"
              >
                <Radio.Group
                  value={audioMixMode}
                  onChange={(e) => setAudioMixMode(e.target.value as AudioMixMode)}
                  optionType="button"
                  buttonStyle="solid"
                  aria-label={t('avPreview.audioMixModeLabel')}
                >
                  {AUDIO_MIX_MODE_OPTIONS.map((mode) => (
                    <Tooltip
                      key={mode}
                      title={t(`avPreview.audioMixMode.${mode}.hint`)}
                    >
                      <Radio.Button value={mode}>
                        {t(`avPreview.audioMixMode.${mode}.label`)}
                      </Radio.Button>
                    </Tooltip>
                  ))}
                </Radio.Group>

                {showBgmPicker && (
                  <div data-testid="av-preview-bgm-row">
                    <div className="text-sm text-gray-600">
                      {t('avPreview.bgmLabel')}
                    </div>
                    <Select
                      allowClear
                      style={{ width: '100%' }}
                      placeholder={t('avPreview.bgmPlaceholder')}
                      value={bgmFileId}
                      onChange={(v) => handleBgmChange(v ?? undefined)}
                      options={audioOptions}
                      loading={audioFilesQuery.isLoading}
                      aria-label={t('avPreview.bgmLabel')}
                    />
                  </div>
                )}

                {showSfxAndDucking && (
                  <>
                    <div data-testid="av-preview-sfx-row">
                      <div className="text-sm text-gray-600">
                        {t('avPreview.sfxLabel')}
                      </div>
                      <Select
                        allowClear
                        style={{ width: '100%' }}
                        placeholder={t('avPreview.sfxPlaceholder')}
                        value={sfxFileId}
                        onChange={(v) => handleSfxChange(v ?? undefined)}
                        options={audioOptions}
                        loading={audioFilesQuery.isLoading}
                        aria-label={t('avPreview.sfxLabel')}
                      />
                    </div>
                    <div data-testid="av-preview-ducking-row">
                      <div className="flex items-center justify-between text-sm text-gray-600">
                        <span>{t('avPreview.duckingLabel')}</span>
                        <span>{`${bgmDuckingDb} dB`}</span>
                      </div>
                      <Slider
                        min={DUCKING_DB_MIN}
                        max={DUCKING_DB_MAX}
                        step={1}
                        value={bgmDuckingDb}
                        onChange={(v) => handleDuckingChange(v as number)}
                        onAfterChange={(v) =>
                          handleDuckingChangeComplete(v as number)
                        }
                        aria-label={t('avPreview.duckingLabel')}
                      />
                    </div>
                  </>
                )}
              </div>
            ),
          },
        ]}
      />
    </div>
  )
}

export default AVPreviewPanel
