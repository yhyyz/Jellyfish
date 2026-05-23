import React, { useCallback, useEffect, useMemo, useRef, useState } from 'react'
import {
  Button,
  Image,
  Input,
  Modal,
  Radio,
  Select,
  Slider,
  Space,
  Spin,
  Switch,
  Tabs,
  Tag,
  Tooltip,
  message,
} from 'antd'
import {
  AppstoreOutlined,
  CameraOutlined,
  CustomerServiceOutlined,
  DeleteOutlined,
  DoubleRightOutlined,
  DownloadOutlined,
  EditOutlined,
  LinkOutlined,
  PictureOutlined,
  PlusOutlined,
  SettingOutlined,
  SoundOutlined,
  TagOutlined,
  ThunderboltOutlined,
  ToolOutlined,
  UploadOutlined,
  UserOutlined,
  VideoCameraOutlined,
} from '@ant-design/icons'
import {
  FilmService,
  StudioEntitiesService,
  StudioImageTasksService,
  StudioShotFrameImagesService,
  StudioShotLinksService,
  StudioShotsService,
} from '../../../services/generated'
import { StudioEntitiesApi } from '../../../services/studioEntities'
import type {
  EntityNameExistenceItem,
  ImageGenerationOptionsRead,
  ProjectCostumeLinkRead,
  ProjectPropLinkRead,
  ProjectSceneLinkRead,
  ShotAssetsOverviewRead,
  ShotCharacterLinkRead,
  ShotDetailRead,
  ShotDialogLineRead,
  ShotExtractedCandidateRead,
  ShotExtractedDialogueCandidateRead,
  ShotFrameImageRead,
  ShotFramePromptMappingRead,
  ShotVideoReadinessRead,
} from '../../../services/generated'
import { listTaskLinksNormalized } from '../../../services/filmTaskLinks'
import { buildFileDownloadUrl, resolveAssetUrl } from '../assets/utils'
import {
  defaultTaskActionErrorMessage,
  executeTaskCancel,
  extractTaskIdFromApiEnvelope,
} from '../components/taskActionHelpers'
import { useRelationTaskNotification } from '../components/taskNotificationHelpers'
import { TASK_COPY } from '../components/taskCopy'
import { useGenerationDraft } from '../hooks/useGenerationDraft'
import type { RelationTaskState } from '../project/ProjectWorkbench/chapterDivisionTasks'
import { toRelationTaskStateFromStatusRead } from '../project/ProjectWorkbench/chapterDivisionTasks'
import { ChapterStudioMaintenancePanel } from './components/ChapterStudioMaintenancePanel'
import { ChapterStudioReadinessDiagnosisPanel } from './components/ChapterStudioReadinessDiagnosisPanel'
import { ChapterStudioVideoReadinessPanel } from './components/ChapterStudioVideoReadinessPanel'
import {
  CAMERA_SHOT_OPTIONS,
  CAMERA_ANGLE_OPTIONS,
  CAMERA_MOVEMENT_OPTIONS,
} from './constants'
import type {
  FramePromptDerived,
  InspectorTabKey,
  KeyframeCardState,
  KeyframeResolutionProfile,
  PromptFrameType,
  ShotFramePromptDebugContext,
  ShotFramePromptQualityChecks,
  StudioShot,
  VideoPromptDerived,
  VideoReferenceMode,
} from './types'
import {
  applyTaskCancelState,
  buildActionBeatPhaseTags,
  buildGuidanceLevelSummary,
  buildKeyframeGuidanceSummary,
  getKeyframeRenderStatusMeta,
  getResolutionProfileLabel,
  mapGenerationDraftStateToRenderState,
  normalizeAssetName,
  parseDirectorCommandSummary,
  readDebugContextText,
  reorder,
  resolveKeyframePixelSize,
  sleep,
  uniqueNames,
} from './utils'

const { TextArea } = Input

export function Inspector(props: {
  projectId?: string
  chapterId?: string
  projectVisualStyle: '现实' | '动漫'
  projectStyle: string
  projectDefaultVideoRatio: string
  capabilityDefaultVideoRatio: string
  videoRatioOptions: Array<{ value: string; label: React.ReactNode }>
  imageGenerationOptions: ImageGenerationOptionsRead | null
  keyframeResolutionProfile: KeyframeResolutionProfile
  onChangeKeyframeResolutionProfile: (value: KeyframeResolutionProfile) => void
  loadingDetail: boolean
  shotDetail: ShotDetailRead | null
  dialogLines: ShotDialogLineRead[]
  frameImages: ShotFrameImageRead[]
  sceneLinks: ProjectSceneLinkRead[]
  propLinks: ProjectPropLinkRead[]
  costumeLinks: ProjectCostumeLinkRead[]
  shotCharacterLinks: ShotCharacterLinkRead[]
  shotCandidateItems: ShotExtractedCandidateRead[]
  shotDialogueCandidateItems: ShotExtractedDialogueCandidateRead[]
  cameraUpdating: boolean
  promptAssetsUpdating: boolean
  onDeleteDialogLine: (lineId: number) => Promise<void>
  onUpdatePromptScene: (sceneId?: string) => Promise<void>
  onUpdatePromptActors: (actorIds: string[]) => Promise<void>
  onUpdatePromptProps: (propIds: string[]) => Promise<void>
  onUpdatePromptCostumes: (costumeIds: string[]) => Promise<void>
  selectedShot: StudioShot | null
  onUpdateShotTitle: (shotId: string, title: string) => Promise<void>
  onUpdateShotScriptExcerpt: (shotId: string, script_excerpt: string) => Promise<void>
  onDeleteShotOps: (shotId: string) => Promise<void>
  onClose: () => void
  onPatchShotDetail: (patch: Partial<ShotDetailRead>) => void
  onPatchShotDetailImmediate: (patch: Partial<ShotDetailRead>) => Promise<void>
  onSelectPreviewVideo: (fileId: string) => void
  /** 下拉展开时拉取最新分镜帧图，用于「参考」关键帧类型选项动态更新 */
  onRefreshShotFrameImages?: () => Promise<void>
}) {
  const {
    projectId,
    chapterId,
    projectVisualStyle,
    projectStyle,
    projectDefaultVideoRatio,
    capabilityDefaultVideoRatio,
    videoRatioOptions,
    imageGenerationOptions,
    keyframeResolutionProfile,
    onChangeKeyframeResolutionProfile,
    loadingDetail,
    shotDetail,
    dialogLines,
    frameImages,
    sceneLinks,
    propLinks,
    costumeLinks,
    shotCharacterLinks,
    shotCandidateItems,
    shotDialogueCandidateItems,
    cameraUpdating,
    promptAssetsUpdating,
    onDeleteDialogLine,
    onUpdatePromptScene,
    onUpdatePromptActors,
    onUpdatePromptProps,
    onUpdatePromptCostumes,
    selectedShot,
    onUpdateShotTitle,
    onUpdateShotScriptExcerpt,
    onDeleteShotOps,
    onClose,
    onPatchShotDetail,
    onPatchShotDetailImmediate,
    onSelectPreviewVideo,
    onRefreshShotFrameImages,
  } = props
  const currentChapterId = chapterId ?? null
  const [imageVersion, setImageVersion] = useState('v1')
  const [refImageType, setRefImageType] = useState<string | undefined>(undefined)
  const [refFrameTypeSelectLoading, setRefFrameTypeSelectLoading] = useState(false)
  const [useBoneDepth, setUseBoneDepth] = useState(false)
  const [audioMode, setAudioMode] = useState<'none' | 'prompt' | 'upload'>('none')
  const [hideShot, setHideShot] = useState(false)
  const [inspectorTabKey, setInspectorTabKey] = useState<InspectorTabKey>('camera')
  const [sceneNameMap, setSceneNameMap] = useState<Record<string, string>>({})
  const [characterNameMap, setCharacterNameMap] = useState<Record<string, string>>({})
  const [linkRoleOpen, setLinkRoleOpen] = useState(false)
  const [linkRoleLoading, setLinkRoleLoading] = useState(false)
  const [linkRoleSelectedIds, setLinkRoleSelectedIds] = useState<string[]>([])
  const [projectRoleOptions, setProjectRoleOptions] = useState<
    Array<{ value: string; label: React.ReactNode; searchLabel: string; disabled?: boolean }>
  >([])
  const [shotLinkedAssets, setShotLinkedAssets] = useState<
    Array<{ type: string; id: string; name?: string; thumbnail?: string; image_id?: number | null }>
  >([])
  const [shotAssetsOverview, setShotAssetsOverview] = useState<ShotAssetsOverviewRead | null>(null)
  const shotAssetsOverviewRequestSeqRef = useRef(0)
  const [shotRenderPromptLoading, setShotRenderPromptLoading] = useState(false)
  const [shotExtractStatus, setShotExtractStatus] = useState<{
    source: 'idle'
    updatedAt: number | null
    message: string
  }>({
    source: 'idle',
    updatedAt: null,
    message: '',
  })
  const [readinessExistenceMap, setReadinessExistenceMap] = useState<Record<string, EntityNameExistenceItem>>({})
  const [readinessExistenceLoading, setReadinessExistenceLoading] = useState(false)
  const [linkSceneOpen, setLinkSceneOpen] = useState(false)
  const [linkSceneLoading, setLinkSceneLoading] = useState(false)
  const [projectSceneOptions, setProjectSceneOptions] = useState<Array<{ value: string; label: React.ReactNode; searchLabel: string }>>([])

  const [linkPropOpen, setLinkPropOpen] = useState(false)
  const [linkPropLoading, setLinkPropLoading] = useState(false)
  const [linkPropSelectedIds, setLinkPropSelectedIds] = useState<string[]>([])
  const [projectPropOptions, setProjectPropOptions] = useState<Array<{ value: string; label: React.ReactNode; searchLabel: string; disabled?: boolean }>>([])

  const [linkCostumeOpen, setLinkCostumeOpen] = useState(false)
  const [linkCostumeLoading, setLinkCostumeLoading] = useState(false)
  const [linkCostumeSelectedIds, setLinkCostumeSelectedIds] = useState<string[]>([])
  const [projectCostumeOptions, setProjectCostumeOptions] = useState<Array<{ value: string; label: React.ReactNode; searchLabel: string; disabled?: boolean }>>([])
  const [opsTitleDraft, setOpsTitleDraft] = useState('')
  const [opsNoteDraft, setOpsNoteDraft] = useState('')
  const opsTitleSaveTimerRef = useRef<number | null>(null)
  const opsNoteSaveTimerRef = useRef<number | null>(null)
  const [keyframePromptPreviewOpen, setKeyframePromptPreviewOpen] = useState(false)
  const [keyframePromptPreviewLoading, setKeyframePromptPreviewLoading] = useState(false)
  const [keyframePromptActionLoading, setKeyframePromptActionLoading] = useState(false)
  const [keyframePromptPreviewFrameType, setKeyframePromptPreviewFrameType] = useState<PromptFrameType>('key')
  const [keyframePromptRefManualTouched, setKeyframePromptRefManualTouched] = useState(false)
  const [keyframePromptDebugContext, setKeyframePromptDebugContext] = useState<ShotFramePromptDebugContext | null>(null)
  const [keyframePromptDebugCollapsed, setKeyframePromptDebugCollapsed] = useState(true)
  const [keyframeDirectiveCollapsed, setKeyframeDirectiveCollapsed] = useState(true)
  const [keyframePromptDecisionCollapsed, setKeyframePromptDecisionCollapsed] = useState(true)
  const [keyframePromptQualityChecks, setKeyframePromptQualityChecks] = useState<ShotFramePromptQualityChecks>(null)
  const [videoPromptPreviewOpen, setVideoPromptPreviewOpen] = useState(false)
  const [videoPromptPreviewLoading, setVideoPromptPreviewLoading] = useState(false)
  const [videoPromptPreviewSubmitting, setVideoPromptPreviewSubmitting] = useState(false)
  const [videoPromptContextCollapsed, setVideoPromptContextCollapsed] = useState(true)
  const resolveVideoRatioForRequest = useCallback(() => {
    const shotRatio = String(shotDetail?.override_video_ratio ?? '').trim()
    const projectRatio = String(projectDefaultVideoRatio ?? '').trim()
    const fallbackRatio = String(capabilityDefaultVideoRatio ?? '').trim()
    return shotRatio || projectRatio || fallbackRatio
  }, [capabilityDefaultVideoRatio, projectDefaultVideoRatio, shotDetail?.override_video_ratio])
  const resolvedKeyframeRatio = resolveVideoRatioForRequest()
  const resolvedKeyframePixelSize = resolveKeyframePixelSize(
    imageGenerationOptions,
    resolvedKeyframeRatio,
    keyframeResolutionProfile,
  )
  const videoPromptDraft = useGenerationDraft<
    { prompt: string },
    { referenceMode: VideoReferenceMode; images: string[] },
    VideoPromptDerived,
    { taskId: string | null }
  >({
    initialBase: { prompt: '' },
    initialContext: { referenceMode: 'text_only', images: [] },
    derive: async ({ base, context }) => {
      if (!selectedShot?.id) {
        throw new Error('shot is required')
      }
      const ratio = resolveVideoRatioForRequest()
      if (!ratio) {
        throw new Error('video ratio is required')
      }
      const res = await FilmService.previewVideoGenerationPromptApiV1FilmTasksVideoPreviewPromptPost({
        requestBody: {
          shot_id: selectedShot.id,
          reference_mode: context.referenceMode,
          prompt: (base.prompt || '').trim() || null,
          images: context.images,
          ratio,
        } as any,
      })
      const data = (res as any)?.data ?? null
      return {
        prompt: typeof data?.prompt === 'string' ? data.prompt : '',
        images: Array.isArray(data?.images) ? (data.images as string[]).filter(Boolean) : [],
        pack: data?.pack ?? null,
      }
    },
    submit: async ({ derived, context }) => {
      if (!selectedShot?.id) {
        throw new Error('shot is required')
      }
      const ratio = resolveVideoRatioForRequest()
      if (!ratio) {
        throw new Error('video ratio is required')
      }
      const created = await FilmService.createVideoGenerationTaskApiV1FilmTasksVideoPost({
        requestBody: {
          shot_id: selectedShot.id,
          reference_mode: context.referenceMode,
          prompt: (derived.prompt || '').trim(),
          images: derived.images,
          ratio,
        } as any,
      })
      return {
        taskId: created.data?.task_id ?? null,
      }
    },
  })
  const videoPromptPreviewDraft = videoPromptDraft.base.prompt
  const videoPromptPreviewImages = videoPromptDraft.context.images
  const videoReferenceMode = videoPromptDraft.context.referenceMode
  const videoPromptPreviewPack = videoPromptDraft.derived?.pack ?? null
  const videoActionBeatPhases = videoPromptPreviewPack?.action_beat_phases ?? []
  const videoActionBeats = videoActionBeatPhases.length > 0
    ? videoActionBeatPhases.map((item) => ({
        text: item.text,
        phase: item.phase,
      }))
    : (videoPromptPreviewPack?.action_beats ?? []).map((text) => ({
        text,
        phase: null,
      }))
  const videoVisibleActionBeats = videoPromptContextCollapsed
    ? videoActionBeats.slice(0, 2)
    : videoActionBeats
  const hiddenVideoActionBeatCount = Math.max(0, videoActionBeats.length - videoVisibleActionBeats.length)
  const [videoTaskPolling, setVideoTaskPolling] = useState(false)
  const [videoTaskStatus, setVideoTaskStatus] = useState<string | null>(null)
  const [videoTaskId, setVideoTaskId] = useState<string | null>(null)
  const [videoTask, setVideoTask] = useState<RelationTaskState | null>(null)
  const [videoSettledTask, setVideoSettledTask] = useState<RelationTaskState | null>(null)
  const [promptTask, setPromptTask] = useState<RelationTaskState | null>(null)
  const [promptSettledTask, setPromptSettledTask] = useState<RelationTaskState | null>(null)
  const [frameImageTask, setFrameImageTask] = useState<RelationTaskState | null>(null)
  const [frameImageSettledTask, setFrameImageSettledTask] = useState<RelationTaskState | null>(null)
  const [generatedVideos, setGeneratedVideos] = useState<Array<{ linkId: number; fileId: string; url: string }>>([])
  const [videoReadiness, setVideoReadiness] = useState<ShotVideoReadinessRead | null>(null)
  const [videoReadinessLoading, setVideoReadinessLoading] = useState(false)
  const [keyframeCards, setKeyframeCards] = useState<Record<PromptFrameType, KeyframeCardState>>({
    first: { loading: false, taskStatus: null, taskId: null, thumbs: [], modalOpen: false, applyingFileId: null },
    key: { loading: false, taskStatus: null, taskId: null, thumbs: [], modalOpen: false, applyingFileId: null },
    last: { loading: false, taskStatus: null, taskId: null, thumbs: [], modalOpen: false, applyingFileId: null },
  })
  const selectedShotSourceLabel = useMemo(() => {
    if (!selectedShot) return '分镜工作室'
    const shotTitle = selectedShot.title?.trim()
    return shotTitle ? `镜头：${shotTitle}` : `镜头：第 ${selectedShot.index} 镜`
  }, [selectedShot])
  useRelationTaskNotification({
    task: videoTask,
    settledTask: videoSettledTask,
    title: TASK_COPY.videoGeneration.title,
    sourceLabel: selectedShotSourceLabel,
    runningDescription: TASK_COPY.videoGeneration.runningDescription,
    cancellingDescription: TASK_COPY.videoGeneration.cancellingDescription,
    successDescription: TASK_COPY.videoGeneration.successDescription,
    cancelledDescription: TASK_COPY.videoGeneration.cancelledDescription,
    failedDescription: TASK_COPY.videoGeneration.failedDescription,
    onCancel:
      videoTask?.taskId
        ? () =>
            void executeTaskCancel({
              taskId: videoTask.taskId,
              reason: '用户在分镜工作室取消视频生成任务',
              applyCancelData: (data) => {
                setVideoTask((current) => applyTaskCancelState(current, data))
                return null
              },
              cancelledImmediatelyMessage: TASK_COPY.videoGeneration.cancelledImmediatelyMessage,
              cancelRequestedMessage: TASK_COPY.videoGeneration.cancelRequestedMessage,
              fallbackErrorMessage: '取消视频生成任务失败',
            })
        : null,
    onNavigate: () => undefined,
  })
  useRelationTaskNotification({
    task: promptTask,
    settledTask: promptSettledTask,
    title: TASK_COPY.shotFramePrompt.title,
    sourceLabel: selectedShotSourceLabel,
    runningDescription: TASK_COPY.shotFramePrompt.runningDescription,
    cancellingDescription: TASK_COPY.shotFramePrompt.cancellingDescription,
    successDescription: TASK_COPY.shotFramePrompt.successDescription,
    cancelledDescription: TASK_COPY.shotFramePrompt.cancelledDescription,
    failedDescription: TASK_COPY.shotFramePrompt.failedDescription,
    onCancel:
      promptTask?.taskId
        ? () =>
            void executeTaskCancel({
              taskId: promptTask.taskId,
              reason: '用户在分镜工作室取消分镜提示词生成任务',
              applyCancelData: (data) => {
                setPromptTask((current) => applyTaskCancelState(current, data))
                return null
              },
              cancelledImmediatelyMessage: TASK_COPY.shotFramePrompt.cancelledImmediatelyMessage,
              cancelRequestedMessage: TASK_COPY.shotFramePrompt.cancelRequestedMessage,
              fallbackErrorMessage: '取消分镜提示词生成任务失败',
            })
        : null,
    onNavigate: () => undefined,
  })
  useRelationTaskNotification({
    task: frameImageTask,
    settledTask: frameImageSettledTask,
    title: TASK_COPY.shotFrameImage.title,
    sourceLabel: selectedShotSourceLabel,
    runningDescription: TASK_COPY.shotFrameImage.runningDescription,
    cancellingDescription: TASK_COPY.shotFrameImage.cancellingDescription,
    successDescription: TASK_COPY.shotFrameImage.successDescription,
    cancelledDescription: TASK_COPY.shotFrameImage.cancelledDescription,
    failedDescription: TASK_COPY.shotFrameImage.failedDescription,
    onCancel:
      frameImageTask?.taskId
        ? () =>
            void executeTaskCancel({
              taskId: frameImageTask.taskId,
              reason: '用户在分镜工作室取消关键帧图片生成任务',
              applyCancelData: (data) => {
                setFrameImageTask((current) => applyTaskCancelState(current, data))
                return null
              },
              cancelledImmediatelyMessage: TASK_COPY.shotFrameImage.cancelledImmediatelyMessage,
              cancelRequestedMessage: TASK_COPY.shotFrameImage.cancelRequestedMessage,
              fallbackErrorMessage: '取消关键帧图片生成任务失败',
            })
        : null,
    onNavigate: () => undefined,
  })
  const showAvTab = false
  const showGenRefParams = false
  const showGenRefVersions = false

  const getInspectorTabForSelectedShot = useCallback(
    (shot: StudioShot | null): InspectorTabKey => {
      if (!shot) return 'camera'
      if (shot.hasProblem) return 'ops'
      if (!(shot.script_excerpt ?? '').trim() || shot.status !== 'ready') return 'prompt_image'
      if (shot.status === 'ready') return 'gen_ref'
      if (!shot.hasSpeech) return 'dialogue'
      return 'camera'
    },
    [],
  )

  useEffect(() => {
    setInspectorTabKey(getInspectorTabForSelectedShot(selectedShot))
  }, [getInspectorTabForSelectedShot, selectedShot?.id])

  useEffect(() => {
    setHideShot(Boolean(selectedShot?.hidden))
  }, [selectedShot?.hidden])

  useEffect(() => {
    if (!selectedShot?.id) {
      setVideoReadiness(null)
      return
    }
    let canceled = false
    setVideoReadinessLoading(true)
    void (async () => {
      try {
        const res = await StudioShotsService.getShotVideoReadinessApiApiV1StudioShotsShotIdVideoReadinessGet({
          shotId: selectedShot.id,
          referenceMode: videoReferenceMode,
        })
        if (canceled) return
        setVideoReadiness((res.data ?? null) as ShotVideoReadinessRead | null)
      } catch {
        if (canceled) return
        setVideoReadiness(null)
      } finally {
        if (!canceled) setVideoReadinessLoading(false)
      }
    })()
    return () => {
      canceled = true
    }
  }, [
    selectedShot?.id,
    selectedShot?.status,
    videoReferenceMode,
    shotDetail?.duration,
    shotDetail?.first_frame_prompt,
    shotDetail?.key_frame_prompt,
    shotDetail?.last_frame_prompt,
    frameImages.map((x) => `${x.id}:${x.file_id ?? ''}`).join('|'),
  ])

  useEffect(() => {
    if (!selectedShot?.id) {
      setGeneratedVideos([])
      return
    }
    let canceled = false
    void (async () => {
      try {
        const links = await listTaskLinksNormalized({
          resourceType: 'video',
          relationType: 'video',
          relationEntityId: selectedShot.id,
          order: 'updated_at',
          isDesc: true,
          page: 1,
          pageSize: 100,
        })
        if (canceled) return
        const seen = new Set<string>()
        const list = links
          .filter((l) => Boolean(l.file_id))
          .map((l) => ({
            linkId: l.id,
            fileId: String(l.file_id),
            url: buildFileDownloadUrl(String(l.file_id)) ?? '',
          }))
          .filter((v) => Boolean(v.url))
          .filter((v) => {
            if (seen.has(v.fileId)) return false
            seen.add(v.fileId)
            return true
          })
        const currentId = selectedShot.generated_video_file_id?.trim() || ''
        if (currentId && !list.some((x) => x.fileId === currentId)) {
          const currentUrl = buildFileDownloadUrl(currentId) ?? ''
          if (currentUrl) list.unshift({ linkId: -1, fileId: currentId, url: currentUrl })
        }
        setGeneratedVideos(list)
      } catch {
        if (!canceled) setGeneratedVideos([])
      }
    })()
    return () => {
      canceled = true
    }
  }, [selectedShot?.id, selectedShot?.generated_video_file_id, videoTaskStatus, videoTaskPolling])

  useEffect(() => {
    setOpsTitleDraft(selectedShot?.title ?? '')
    setOpsNoteDraft(selectedShot?.script_excerpt ?? '')
    if (opsTitleSaveTimerRef.current) window.clearTimeout(opsTitleSaveTimerRef.current)
    if (opsNoteSaveTimerRef.current) window.clearTimeout(opsNoteSaveTimerRef.current)
    opsTitleSaveTimerRef.current = null
    opsNoteSaveTimerRef.current = null
  }, [selectedShot?.id])

  useEffect(() => {
    if (!selectedShot?.id) return
    if (opsTitleDraft === (selectedShot.title ?? '')) return

    if (opsTitleSaveTimerRef.current) window.clearTimeout(opsTitleSaveTimerRef.current)
    opsTitleSaveTimerRef.current = window.setTimeout(() => {
      void onUpdateShotTitle(selectedShot.id, opsTitleDraft)
      opsTitleSaveTimerRef.current = null
    }, 500)

    return () => {
      if (opsTitleSaveTimerRef.current) window.clearTimeout(opsTitleSaveTimerRef.current)
      opsTitleSaveTimerRef.current = null
    }
  }, [opsTitleDraft, selectedShot?.id, selectedShot?.title, onUpdateShotTitle])

  useEffect(() => {
    if (!selectedShot?.id) return
    if (opsNoteDraft === (selectedShot.script_excerpt ?? '')) return

    if (opsNoteSaveTimerRef.current) window.clearTimeout(opsNoteSaveTimerRef.current)
    opsNoteSaveTimerRef.current = window.setTimeout(() => {
      void onUpdateShotScriptExcerpt(selectedShot.id, opsNoteDraft)
      opsNoteSaveTimerRef.current = null
    }, 500)

    return () => {
      if (opsNoteSaveTimerRef.current) window.clearTimeout(opsNoteSaveTimerRef.current)
      opsNoteSaveTimerRef.current = null
    }
  }, [opsNoteDraft, selectedShot?.id, selectedShot?.script_excerpt, onUpdateShotScriptExcerpt])

  const flushOpsTitle = async () => {
    if (!selectedShot?.id) return
    if (opsTitleSaveTimerRef.current) window.clearTimeout(opsTitleSaveTimerRef.current)
    opsTitleSaveTimerRef.current = null
    if (opsTitleDraft === (selectedShot.title ?? '')) return
    await onUpdateShotTitle(selectedShot.id, opsTitleDraft)
  }

  const flushOpsNote = async () => {
    if (!selectedShot?.id) return
    if (opsNoteSaveTimerRef.current) window.clearTimeout(opsNoteSaveTimerRef.current)
    opsNoteSaveTimerRef.current = null
    if (opsNoteDraft === (selectedShot.script_excerpt ?? '')) return
    await onUpdateShotScriptExcerpt(selectedShot.id, opsNoteDraft)
  }

  const sceneIds = useMemo(() => Array.from(new Set(sceneLinks.map((x) => x.scene_id).filter(Boolean))), [sceneLinks])
  const characterIds = useMemo(() => Array.from(new Set(shotCharacterLinks.map((x) => x.character_id).filter(Boolean))), [shotCharacterLinks])

  const linkedCharacterIds = useMemo(() => characterIds, [characterIds])
  const linkedSceneId = useMemo(() => {
    if (!selectedShot?.id) return null
    return sceneLinks.find((l) => (l.shot_id ?? null) === selectedShot.id)?.scene_id ?? shotDetail?.scene_id ?? null
  }, [sceneLinks, selectedShot?.id, shotDetail?.scene_id])
  const linkedPropIds = useMemo(() => {
    if (!selectedShot?.id) return []
    return Array.from(new Set(propLinks.filter((l) => (l.shot_id ?? null) === selectedShot.id).map((l) => l.prop_id).filter(Boolean))) as string[]
  }, [propLinks, selectedShot?.id])
  const linkedCostumeIds = useMemo(() => {
    if (!selectedShot?.id) return []
    return Array.from(new Set(costumeLinks.filter((l) => (l.shot_id ?? null) === selectedShot.id).map((l) => l.costume_id).filter(Boolean))) as string[]
  }, [costumeLinks, selectedShot?.id])

  useEffect(() => {
    if (!selectedShot?.id) {
      setShotLinkedAssets([])
      return
    }
    let canceled = false
    void (async () => {
      try {
        const res = await StudioShotsService.listShotLinkedAssetsApiV1StudioShotsShotIdLinkedAssetsGet({
          shotId: selectedShot.id,
          page: 1,
          pageSize: 100,
        })
        if (canceled) return
        const items = (res.data?.items ?? []) as any[]
        setShotLinkedAssets(
          items
            .filter((x) => x && typeof x.type === 'string' && typeof x.id === 'string')
            .map((x) => ({
              type: String(x.type),
              id: String(x.id),
              name: typeof x.name === 'string' ? x.name : undefined,
              image_id: typeof x.image_id === 'number' ? x.image_id : x.image_id === null ? null : undefined,
              thumbnail: typeof x.thumbnail === 'string' && x.thumbnail.trim() ? x.thumbnail.trim() : undefined,
            })),
        )
      } catch {
        if (!canceled) setShotLinkedAssets([])
      }
    })()
    return () => {
      canceled = true
    }
  }, [selectedShot?.id])

  const loadShotAssetsOverview = useCallback(
    async (shotId: string) => {
      const reqSeq = ++shotAssetsOverviewRequestSeqRef.current
      try {
        const res = await StudioShotsService.getShotAssetsOverviewApiApiV1StudioShotsShotIdAssetsOverviewGet({
          shotId,
        })
        if (reqSeq !== shotAssetsOverviewRequestSeqRef.current) return
        setShotAssetsOverview(res.data ?? null)
      } catch {
        if (reqSeq !== shotAssetsOverviewRequestSeqRef.current) return
        setShotAssetsOverview(null)
      }
    },
    [],
  )

  useEffect(() => {
    if (!selectedShot?.id) {
      shotAssetsOverviewRequestSeqRef.current += 1
      setShotAssetsOverview(null)
      return
    }
    void loadShotAssetsOverview(selectedShot.id)
  }, [loadShotAssetsOverview, selectedShot?.id, shotCandidateItems])

  useEffect(() => {
    if (!selectedShot?.id) {
      setShotExtractStatus({ source: 'idle', updatedAt: null, message: '' })
      return
    }
    setShotExtractStatus({
      source: 'idle',
      updatedAt: null,
      message: '待确认候选请前往分镜编辑页提取或刷新。',
    })
  }, [
    selectedShot?.id,
  ])

  const linkedAssetThumbByKey = useMemo(() => {
    const map = new Map<string, string>()
    shotLinkedAssets.forEach((it) => {
      if (!it.thumbnail) return
      map.set(`${it.type}:${it.id}`, it.thumbnail)
    })
    return map
  }, [shotLinkedAssets])

  const promptAssetReadiness = useMemo(() => {
    if (selectedShot?.skip_extraction) {
      return {
        checks: [] as Array<{
          key: 'characters' | 'scene' | 'props' | 'costumes'
          label: string
          importance: string
          entries: Array<{ id: number; name: string; status: ShotExtractedCandidateRead['candidate_status'] }>
          missing: string[]
          expectedCount: number
          actualCount: number
          ignoredCount: number
          resolvedCount: number
          ready: boolean
        }>,
        expectedChecks: [] as Array<{
          key: 'characters' | 'scene' | 'props' | 'costumes'
          label: string
          importance: string
          entries: Array<{ id: number; name: string; status: ShotExtractedCandidateRead['candidate_status'] }>
          missing: string[]
          expectedCount: number
          actualCount: number
          ignoredCount: number
          resolvedCount: number
          ready: boolean
        }>,
        readyCount: 1,
        totalCount: 1,
        percent: 100,
        hasMissing: false,
      }
    }
    const overviewItems = shotAssetsOverview?.items ?? []
    const bucket = (type: 'character' | 'scene' | 'prop' | 'costume') =>
      overviewItems.filter((item) => item.type === type)

    const checks = [
      {
        key: 'characters' as const,
        label: '角色',
        importance: '影响人物一致性、关键帧参考图和画面主体描述。',
        candidates: bucket('character'),
      },
      {
        key: 'scene' as const,
        label: '场景',
        importance: '影响镜头环境描述、视频提示词和整体空间连续性。',
        candidates: bucket('scene'),
      },
      {
        key: 'props' as const,
        label: '道具',
        importance: '影响关键动作细节，缺失时容易让画面叙事元素不完整。',
        candidates: bucket('prop'),
      },
      {
        key: 'costumes' as const,
        label: '服装',
        importance: '影响角色外观连续性，尤其在多镜头或生成多版本时更明显。',
        candidates: bucket('costume'),
      },
    ].map((item) => {
      const entries = item.candidates.map((candidate) => ({
        id: candidate.candidate_id ?? -1,
        name: candidate.name,
        status: candidate.candidate_status ?? (candidate.is_linked ? 'linked' : 'pending'),
      }))
      const pending = entries.filter((entry) => entry.status === 'pending')
      const linked = entries.filter((entry) => entry.status === 'linked')
      const ignored = entries.filter((entry) => entry.status === 'ignored')
      return {
        ...item,
        entries,
        missing: pending.map((entry) => entry.name),
        expectedCount: entries.length,
        actualCount: linked.length,
        ignoredCount: ignored.length,
        resolvedCount: linked.length + ignored.length,
        ready: entries.length === 0 || pending.length === 0,
      }
    })

    const expectedChecks = checks.filter((item) => item.expectedCount > 0)
    const readyCount = expectedChecks.filter((item) => item.ready).length
    return {
      checks,
      expectedChecks,
      readyCount,
      totalCount: expectedChecks.length,
      percent: expectedChecks.length === 0 ? 100 : Math.round((readyCount / expectedChecks.length) * 100),
      hasMissing: expectedChecks.some((item) => item.missing.length > 0),
    }
  }, [selectedShot?.skip_extraction, shotAssetsOverview?.items])

  useEffect(() => {
    if (!projectId || !selectedShot?.id) {
      setReadinessExistenceMap({})
      return
    }

    const overviewItems = shotAssetsOverview?.items ?? []
    const characterNames = uniqueNames(
      overviewItems.filter((item) => item.type === 'character' && item.candidate_status === 'pending').map((item) => item.name),
    )
    const sceneNames = uniqueNames(
      overviewItems.filter((item) => item.type === 'scene' && item.candidate_status === 'pending').map((item) => item.name),
    )
    const propNames = uniqueNames(
      overviewItems.filter((item) => item.type === 'prop' && item.candidate_status === 'pending').map((item) => item.name),
    )
    const costumeNames = uniqueNames(
      overviewItems.filter((item) => item.type === 'costume' && item.candidate_status === 'pending').map((item) => item.name),
    )

    if (characterNames.length === 0 && sceneNames.length === 0 && propNames.length === 0 && costumeNames.length === 0) {
      setReadinessExistenceMap({})
      return
    }

    let cancelled = false
    setReadinessExistenceLoading(true)
    void (async () => {
      try {
        const res = await StudioEntitiesService.checkEntityNamesExistenceApiV1StudioEntitiesExistenceCheckPost({
          requestBody: {
            project_id: projectId,
            shot_id: selectedShot.id,
            character_names: characterNames,
            scene_names: sceneNames,
            prop_names: propNames,
            costume_names: costumeNames,
          },
        })
        if (cancelled) return
        const data = res.data
        const next: Record<string, EntityNameExistenceItem> = {}
        ;(data?.characters ?? []).forEach((item) => {
          next[`characters:${normalizeAssetName(item.name)}`] = item
        })
        ;(data?.scenes ?? []).forEach((item) => {
          next[`scene:${normalizeAssetName(item.name)}`] = item
        })
        ;(data?.props ?? []).forEach((item) => {
          next[`props:${normalizeAssetName(item.name)}`] = item
        })
        ;(data?.costumes ?? []).forEach((item) => {
          next[`costumes:${normalizeAssetName(item.name)}`] = item
        })
        setReadinessExistenceMap(next)
      } catch {
        if (!cancelled) setReadinessExistenceMap({})
      } finally {
        if (!cancelled) setReadinessExistenceLoading(false)
      }
    })()

    return () => {
      cancelled = true
    }
  }, [
    projectId,
    selectedShot?.id,
    shotAssetsOverview?.items,
  ])

  const getReadinessExistenceLabel = useCallback((checkKey: 'characters' | 'scene' | 'props' | 'costumes', name: string) => {
    const item = readinessExistenceMap[`${checkKey}:${normalizeAssetName(name)}`]
    if (!item) {
      return readinessExistenceLoading ? '检测中' : null
    }
    if (!item.exists) return '需新建'
    if (item.linked_to_project && !item.linked_to_shot) return '项目内可关联'
    if (!item.linked_to_project) return '资产库已有'
    if (item.linked_to_shot) return '已关联'
    return null
  }, [readinessExistenceLoading, readinessExistenceMap])


  const promptAssetReadinessNote = useMemo(() => {
    if (!selectedShot) return '请先选择一个分镜。'
    if (selectedShot.skip_extraction) return '当前分镜已明确标记为无需提取，系统会直接按“提取确认已完成”处理。'
    if (!shotAssetsOverview) return '当前还没有拿到这条分镜的资产总览，暂时无法展示候选确认状态。'
    return '这里作为生成前的诊断面板，优先依据后端 assets-overview 展示当前镜头的信息确认状态；提取、刷新与精细确认统一在分镜编辑页处理。'
  }, [selectedShot, shotAssetsOverview])

  const shotExtractStatusText = useMemo(() => {
    if (!shotExtractStatus.message) return ''
    if (!shotExtractStatus.updatedAt) return shotExtractStatus.message
    const time = new Date(shotExtractStatus.updatedAt).toLocaleTimeString('zh-CN', {
      hour: '2-digit',
      minute: '2-digit',
      second: '2-digit',
    })
    return `${shotExtractStatus.message} · ${time}`
  }, [shotExtractStatus])

  const goToShotEditForAssets = useCallback(() => {
    if (!projectId || !currentChapterId || !selectedShot?.id) return
    window.location.assign(`/projects/${projectId}/chapters/${currentChapterId}/shots/${selectedShot.id}/edit`)
  }, [currentChapterId, projectId, selectedShot?.id])

  const extractFileIdFromThumbnail = useCallback((thumbnail?: string | null): string | null => {
    const v = (thumbnail || '').trim()
    if (!v) return null
    // 纯 file_id：不包含路径或协议
    if (!v.includes('/') && !v.includes(':')) return v
    try {
      const url = new URL(v, typeof window !== 'undefined' ? window.location.origin : 'http://localhost')
      const m = url.pathname.match(/\/api\/v1\/studio\/files\/([^/]+)\/download\/?$/)
      if (m?.[1]) return decodeURIComponent(m[1])
    } catch {
      // ignore
    }
    return null
  }, [])

  const shotLinkedAssetNameByFileId = useMemo(() => {
    const map = new Map<string, string>()
    shotLinkedAssets.forEach((it: any) => {
      const fid =
        (typeof it?.file_id === 'string' && it.file_id.trim() ? it.file_id.trim() : null) ??
        extractFileIdFromThumbnail(it?.thumbnail ?? null)
      if (!fid) return
      const name = typeof it?.name === 'string' && it.name.trim() ? it.name.trim() : String(it?.id ?? '')
      if (!name) return
      map.set(fid, name)
    })
    return map
  }, [extractFileIdFromThumbnail, shotLinkedAssets])

  const deriveKeyframePromptPreview = useCallback(
    async ({
      base,
      context,
    }: {
      base: { frameType: PromptFrameType; prompt: string }
      context: { refFileIds: string[] }
    }): Promise<FramePromptDerived> => {
      if (!selectedShot?.id) {
        throw new Error('shot is required')
      }
      const basePrompt = (base.prompt || '').trim()
      const refFileIds = (context.refFileIds || []).filter(Boolean)
      if (!basePrompt) {
        return {
          basePrompt: '',
          renderedPrompt: '',
          selectedGuidance: [],
          droppedGuidance: [],
          selectedGuidanceDetails: [],
          droppedGuidanceDetails: [],
          images: [],
          mappings: [],
        }
      }

      const imagesPayload = refFileIds
        .map((fid) => {
          const match =
            shotLinkedAssets.find((x) => extractFileIdFromThumbnail(x.thumbnail ?? null) === fid) ??
            shotLinkedAssets.find((x) => (x as any)?.file_id === fid)
          return match
            ? {
                type: match.type as any,
                id: match.id,
                name: match.name ?? match.id,
                file_id: fid,
              }
            : null
        })
        .filter(Boolean)

      const rendered = await StudioImageTasksService.renderShotFramePromptApiV1StudioImageTasksShotShotIdFrameRenderPromptPost({
        shotId: selectedShot.id,
        requestBody: {
          frame_type: base.frameType,
          prompt: basePrompt,
          images: imagesPayload as any,
        } as any,
      })
      const d = rendered.data as any
      return {
        basePrompt: typeof d?.base_prompt === 'string' ? d.base_prompt : basePrompt,
        renderedPrompt: typeof d?.rendered_prompt === 'string' ? d.rendered_prompt : '',
        selectedGuidance: Array.isArray(d?.selected_guidance)
          ? d.selected_guidance.map((item: unknown) => String(item ?? '').trim()).filter(Boolean)
          : [],
        droppedGuidance: Array.isArray(d?.dropped_guidance)
          ? d.dropped_guidance.map((item: unknown) => String(item ?? '').trim()).filter(Boolean)
          : [],
        selectedGuidanceDetails: Array.isArray(d?.selected_guidance_details)
          ? d.selected_guidance_details
            .map((item: any) => ({
              text: String(item?.text ?? '').trim(),
              category: String(item?.category ?? '').trim(),
              reasonTag: String(item?.reason_tag ?? '').trim(),
              reason: String(item?.reason ?? '').trim(),
            }))
            .filter((item: { text: string }) => item.text)
          : [],
        droppedGuidanceDetails: Array.isArray(d?.dropped_guidance_details)
          ? d.dropped_guidance_details
            .map((item: any) => ({
              text: String(item?.text ?? '').trim(),
              category: String(item?.category ?? '').trim(),
              reasonTag: String(item?.reason_tag ?? '').trim(),
              reason: String(item?.reason ?? '').trim(),
            }))
            .filter((item: { text: string }) => item.text)
          : [],
        images: Array.isArray(d?.images) ? (d.images as string[]).filter(Boolean) : [],
        mappings: Array.isArray(d?.mappings) ? (d.mappings as ShotFramePromptMappingRead[]) : [],
      }
    },
    [extractFileIdFromThumbnail, selectedShot?.id, shotLinkedAssets],
  )

  const keyframePromptDraft = useGenerationDraft<
    { frameType: PromptFrameType; prompt: string },
    { refFileIds: string[] },
    FramePromptDerived,
    { taskId: string | null }
  >({
    initialBase: { frameType: 'key', prompt: '' },
    initialContext: { refFileIds: [] },
    derive: deriveKeyframePromptPreview,
    submit: async ({ base, context, derived }) => {
      if (!selectedShot?.id) {
        throw new Error('shot is required')
      }
      const resolvedItems =
        derived.mappings.length > 0
          ? derived.mappings.map((mapping) => ({
              type: mapping.type,
              id: mapping.id,
              name: mapping.name,
              file_id: mapping.file_id,
            }))
          : (context.refFileIds || []).map((fid) => {
              const match =
                shotLinkedAssets.find((x) => extractFileIdFromThumbnail(x.thumbnail ?? null) === fid) ??
                shotLinkedAssets.find((x) => (x as any)?.file_id === fid)
              return {
                type: (match?.type as any) ?? 'character',
                id: match?.id ?? fid,
                name: match?.name ?? match?.id ?? fid,
                file_id: fid,
              }
            })

      const ratio = resolveVideoRatioForRequest()
      if (!ratio) {
        throw new Error('video ratio is required')
      }
      const created = await StudioImageTasksService.createShotFrameImageGenerationTaskApiV1StudioImageTasksShotShotIdFrameImageTasksPost({
        shotId: selectedShot.id,
        requestBody: {
          frame_type: base.frameType,
          model_id: null,
          prompt: (base.prompt || '').trim(),
          images: resolvedItems as any,
          target_ratio: ratio,
          resolution_profile: keyframeResolutionProfile,
        } as any,
      })
      return {
        taskId: created.data?.task_id ?? null,
      }
    },
  })
  const keyframePromptPreviewDraft = keyframePromptDraft.base.prompt
  const keyframePromptRenderedDraft = keyframePromptDraft.derived?.renderedPrompt ?? ''
  const keyframePromptSelectedGuidance = keyframePromptDraft.derived?.selectedGuidance ?? []
  const keyframePromptDroppedGuidance = keyframePromptDraft.derived?.droppedGuidance ?? []
  const keyframePromptSelectedGuidanceDetails = keyframePromptDraft.derived?.selectedGuidanceDetails ?? []
  const keyframePromptDroppedGuidanceDetails = keyframePromptDraft.derived?.droppedGuidanceDetails ?? []
  const keyframePromptVisibleSelectedGuidanceDetails = keyframePromptDecisionCollapsed
    ? keyframePromptSelectedGuidanceDetails.slice(0, 2)
    : keyframePromptSelectedGuidanceDetails
  const keyframePromptVisibleDroppedGuidanceDetails = keyframePromptDecisionCollapsed
    ? keyframePromptDroppedGuidanceDetails.slice(0, 1)
    : keyframePromptDroppedGuidanceDetails
  const keyframePromptRenderMappings = keyframePromptDraft.derived?.mappings ?? []
  const keyframePromptPreviewRefFileIds = keyframePromptDraft.context.refFileIds
  const keyframePromptRenderState = keyframePromptDraft.state
  const renderShotPromptToTextarea = useCallback(
    async (opts?: { frameType?: PromptFrameType; prompt?: string; refFileIds?: string[]; showPreviewLoading?: boolean }) => {
      if (!selectedShot?.id) return
      const frameType = opts?.frameType ?? keyframePromptPreviewFrameType
      const basePrompt = (typeof opts?.prompt === 'string' ? opts.prompt : keyframePromptPreviewDraft || '').trim()
      const refFileIds = (opts?.refFileIds ?? keyframePromptPreviewRefFileIds ?? []).filter(Boolean)
      const nextBase = { frameType, prompt: basePrompt }
      const nextContext = { refFileIds }
      keyframePromptDraft.hydrate({
        base: nextBase,
        context: nextContext,
        state: basePrompt ? 'draft_changed' : 'idle',
      })
      if (!basePrompt) {
        return
      }
      setShotRenderPromptLoading(true)
      if (opts?.showPreviewLoading) {
        setKeyframePromptPreviewLoading(true)
      }
      try {
        const derived = await keyframePromptDraft.deriveNow({ base: nextBase, context: nextContext })
        if (derived?.images?.length) {
          keyframePromptDraft.hydrate({
            base: nextBase,
            context: { refFileIds: derived.images },
            derived: {
              ...derived,
              images: derived.images,
            },
          })
        }
      } catch {
        keyframePromptDraft.setState('error')
      } finally {
        if (opts?.showPreviewLoading) {
          setKeyframePromptPreviewLoading(false)
        }
        setShotRenderPromptLoading(false)
      }
    },
    [
      keyframePromptDraft,
      keyframeResolutionProfile,
      keyframePromptPreviewDraft,
      keyframePromptPreviewFrameType,
      keyframePromptPreviewRefFileIds,
      selectedShot?.id,
    ],
  )

  const orderedLinkedCharacterIds = useMemo(() => {
    return shotCharacterLinks
      .slice()
      .sort((a, b) => (a.index ?? 0) - (b.index ?? 0))
      .map((x) => x.character_id)
      .filter(Boolean)
      .map((x) => String(x))
  }, [shotCharacterLinks])

  const autoKeyframeRefFileIds = useMemo(() => {
    const out: string[] = []
    const push = (fid: string | null) => {
      if (!fid) return
      if (out.includes(fid)) return
      out.push(fid)
    }
    // 角色（按 index 顺序）
    orderedLinkedCharacterIds.forEach((cid) =>
      push(extractFileIdFromThumbnail(linkedAssetThumbByKey.get(`character:${cid}`) ?? null)),
    )
    // 场景（单个）
    if (linkedSceneId) push(extractFileIdFromThumbnail(linkedAssetThumbByKey.get(`scene:${linkedSceneId}`) ?? null))
    // 道具
    linkedPropIds.forEach((pid) => push(extractFileIdFromThumbnail(linkedAssetThumbByKey.get(`prop:${pid}`) ?? null)))
    // 服装
    linkedCostumeIds.forEach((cid) =>
      push(extractFileIdFromThumbnail(linkedAssetThumbByKey.get(`costume:${cid}`) ?? null)),
    )
    return out
  }, [
    extractFileIdFromThumbnail,
    linkedCostumeIds,
    linkedPropIds,
    linkedSceneId,
    linkedAssetThumbByKey,
    orderedLinkedCharacterIds,
  ])

  const moveKeyframePromptRefFile = useCallback((fromIndex: number, toIndex: number) => {
    const current = keyframePromptPreviewRefFileIds
    if (fromIndex < 0 || toIndex < 0 || fromIndex >= current.length || toIndex >= current.length) return
    const next = reorder(current, fromIndex, toIndex)
    setKeyframePromptRefManualTouched(true)
    keyframePromptDraft.setContext({ refFileIds: next })
  }, [keyframePromptDraft, keyframePromptPreviewRefFileIds])

  const allSelectableKeyframeRefFileIds = useMemo(() => {
    const out: string[] = []
    const seen = new Set<string>()
    const push = (fid: string) => {
      const normalized = String(fid || '').trim()
      if (!normalized || seen.has(normalized)) return
      seen.add(normalized)
      out.push(normalized)
    }
    autoKeyframeRefFileIds.forEach(push)
    keyframePromptPreviewRefFileIds.forEach(push)
    return out
  }, [autoKeyframeRefFileIds, keyframePromptPreviewRefFileIds])

  const addKeyframePromptRefFile = useCallback((fid: string) => {
    const normalized = String(fid || '').trim()
    if (!normalized) return
    if (keyframePromptPreviewRefFileIds.includes(normalized)) return
    setKeyframePromptRefManualTouched(true)
    keyframePromptDraft.replaceContext({ refFileIds: [...keyframePromptPreviewRefFileIds, normalized] })
  }, [keyframePromptDraft, keyframePromptPreviewRefFileIds])

  const removeKeyframePromptRefFile = useCallback((fid: string) => {
    const normalized = String(fid || '').trim()
    if (!normalized) return
    setKeyframePromptRefManualTouched(true)
    keyframePromptDraft.replaceContext({
      refFileIds: keyframePromptPreviewRefFileIds.filter((item) => item !== normalized),
    })
  }, [keyframePromptDraft, keyframePromptPreviewRefFileIds])

  const resetKeyframePromptRefFiles = useCallback(() => {
    setKeyframePromptRefManualTouched(false)
    keyframePromptDraft.replaceContext({ refFileIds: autoKeyframeRefFileIds })
  }, [autoKeyframeRefFileIds, keyframePromptDraft])

  const clearKeyframePromptRefFiles = useCallback(() => {
    setKeyframePromptRefManualTouched(true)
    keyframePromptDraft.replaceContext({ refFileIds: [] })
  }, [keyframePromptDraft])

  const loadProjectRoleOptions = async () => {
    if (!projectId) {
      setProjectRoleOptions([])
      return
    }
    setLinkRoleLoading(true)
    try {
      const res = await StudioEntitiesApi.list('character', { page: 1, pageSize: 20, q: null })
      const items = (res.data?.items ?? []).filter((x: any) => x?.project_id === projectId)
      const opts = items.map((c: any) => {
        const id = String(c?.id ?? '')
        const name = String(c?.name ?? id)
        const thumb = typeof c?.thumbnail === 'string' ? c.thumbnail : ''
        const disabled = linkedCharacterIds.includes(id)
        return {
          value: id,
          searchLabel: name,
          disabled,
          label: (
            <div className="flex items-center gap-2 min-w-0">
              {thumb ? (
                <img src={resolveAssetUrl(thumb)} alt="" className="w-6 h-6 rounded object-cover shrink-0" />
              ) : (
                <div className="w-6 h-6 rounded bg-gray-100 flex items-center justify-center text-gray-400 shrink-0">
                  <UserOutlined />
                </div>
              )}
              <div className="min-w-0 truncate">{name}</div>
            </div>
          ),
        }
      })
      setProjectRoleOptions(opts)
    } catch {
      setProjectRoleOptions([])
    } finally {
      setLinkRoleLoading(false)
    }
  }

  const loadProjectAssetOptions = async (kind: 'scene' | 'prop' | 'costume') => {
    if (!projectId) return
    if (kind === 'scene') setLinkSceneLoading(true)
    if (kind === 'prop') setLinkPropLoading(true)
    if (kind === 'costume') setLinkCostumeLoading(true)
    try {
      const res = await StudioShotLinksService.listProjectEntityLinksApiV1StudioShotLinksEntityTypeGet({
        entityType: kind,
        projectId,
        chapterId: null,
        shotId: null,
        assetId: null,
        order: null,
        isDesc: false,
        page: 1,
        pageSize: 20,
      })
      const items = (res.data?.items ?? []) as any[]
      const ids = Array.from(
        new Set(
          items
            .map((it) => (kind === 'scene' ? it.scene_id : kind === 'prop' ? it.prop_id : it.costume_id))
            .filter(Boolean)
            .map((x) => String(x)),
        ),
      )
      const details = await Promise.all(
        ids.map(async (id) => {
          try {
            const r = await StudioEntitiesApi.get(kind as any, id)
            const d = (r.data ?? null) as any
            return { id, name: String(d?.name ?? id), thumb: typeof d?.thumbnail === 'string' ? d.thumbnail : '' }
          } catch {
            return { id, name: id, thumb: '' }
          }
        }),
      )
      const nextThumbMap: Record<string, string> = {}
      details.forEach((d) => {
        if (d.thumb) nextThumbMap[d.id] = d.thumb
      })

      const makeLabel = (d: { id: string; name: string; thumb: string }) => (
        <div className="flex items-center gap-2 min-w-0">
          {d.thumb ? (
            <img src={resolveAssetUrl(d.thumb)} alt="" className="w-6 h-6 rounded object-cover shrink-0" />
          ) : (
            <div className="w-6 h-6 rounded bg-gray-100 flex items-center justify-center text-gray-400 shrink-0">
              <UserOutlined />
            </div>
          )}
          <div className="min-w-0 truncate">{d.name}</div>
        </div>
      )

      if (kind === 'scene') {
        setProjectSceneOptions(details.map((d) => ({ value: d.id, searchLabel: d.name, label: makeLabel(d) })))
      } else if (kind === 'prop') {
        setProjectPropOptions(
          details.map((d) => ({ value: d.id, searchLabel: d.name, label: makeLabel(d), disabled: linkedPropIds.includes(d.id) })),
        )
      } else {
        setProjectCostumeOptions(
          details.map((d) => ({ value: d.id, searchLabel: d.name, label: makeLabel(d), disabled: linkedCostumeIds.includes(d.id) })),
        )
      }
    } finally {
      if (kind === 'scene') setLinkSceneLoading(false)
      if (kind === 'prop') setLinkPropLoading(false)
      if (kind === 'costume') setLinkCostumeLoading(false)
    }
  }

  const openReadinessLinker = useCallback(
    async (kind: 'characters' | 'scene' | 'props' | 'costumes') => {
      if (!selectedShot?.id) return
      if (kind === 'characters') {
        setInspectorTabKey('keyframe_gen')
        setLinkRoleSelectedIds([])
        setLinkRoleOpen(true)
        await loadProjectRoleOptions()
        return
      }
      if (kind === 'scene') {
        setInspectorTabKey('keyframe_gen')
        setLinkSceneOpen(true)
        await loadProjectAssetOptions('scene')
        return
      }
      if (kind === 'props') {
        setInspectorTabKey('keyframe_gen')
        setLinkPropSelectedIds([])
        setLinkPropOpen(true)
        await loadProjectAssetOptions('prop')
        return
      }
      setInspectorTabKey('keyframe_gen')
      setLinkCostumeSelectedIds([])
      setLinkCostumeOpen(true)
      await loadProjectAssetOptions('costume')
    },
    [loadProjectAssetOptions, loadProjectRoleOptions, selectedShot?.id],
  )

  const openReadinessCreate = useCallback((kind: 'characters' | 'scene' | 'props' | 'costumes', name: string) => {
    if (!projectId || !selectedShot?.id) return
    const currentShotId = selectedShot.id
    const styleQ =
      `&visualStyle=${encodeURIComponent(projectVisualStyle)}` +
      `&style=${encodeURIComponent(projectStyle)}`
    const ctxQ =
      `&projectId=${encodeURIComponent(projectId)}` +
      `&chapterId=${encodeURIComponent(currentChapterId ?? '')}` +
      `&shotId=${encodeURIComponent(currentShotId)}` +
      styleQ
    const open = (url: string) => window.open(url, '_blank', 'noopener,noreferrer')
    if (kind === 'characters') {
      open(`/projects/${encodeURIComponent(projectId)}?tab=roles&create=1&name=${encodeURIComponent(name)}${ctxQ}`)
      return
    }
    const tab = kind === 'scene' ? 'scene' : kind === 'props' ? 'prop' : 'costume'
    open(`/assets?tab=${tab}&create=1&name=${encodeURIComponent(name)}${ctxQ}`)
  }, [currentChapterId, projectId, projectStyle, projectVisualStyle, selectedShot?.id])

  const handleReadinessMissingAction = useCallback(async (kind: 'characters' | 'scene' | 'props' | 'costumes', name: string) => {
    const item = readinessExistenceMap[`${kind}:${normalizeAssetName(name)}`]
    if (item && !item.exists) {
      openReadinessCreate(kind, name)
      return
    }
    await openReadinessLinker(kind)
  }, [openReadinessCreate, openReadinessLinker, readinessExistenceMap])

  useEffect(() => {
    if (sceneIds.length === 0) {
      setSceneNameMap({})
      return
    }
    void (async () => {
      const entries = await Promise.all(
        sceneIds.map(async (id) => {
          try {
            const r = await StudioEntitiesApi.get('scene', id)
            const d = r.data as { name?: string } | null | undefined
            return [id, d?.name?.trim() || id] as const
          } catch {
            return [id, id] as const
          }
        }),
      )
      setSceneNameMap(Object.fromEntries(entries))
    })()
  }, [sceneIds])

  useEffect(() => {
    if (characterIds.length === 0) {
      setCharacterNameMap({})
      return
    }
    void (async () => {
      const entries = await Promise.all(
        characterIds.map(async (id) => {
          try {
            const r = await StudioEntitiesApi.get('character', id)
            const d = r.data as { name?: string; thumbnail?: string | null } | null | undefined
            const name = d?.name?.trim() || id
            const thumb = typeof d?.thumbnail === 'string' && d.thumbnail.trim() ? d.thumbnail.trim() : ''
            return { id, name, thumb }
          } catch {
            return { id, name: id, thumb: '' }
          }
        }),
      )
      const nextNameMap: Record<string, string> = {}
      entries.forEach((e) => {
        nextNameMap[e.id] = e.name
      })
      setCharacterNameMap(nextNameMap)
    })()
  }, [characterIds])

  const getPromptFromDetailByType = (frameType: PromptFrameType): string => {
    if (!shotDetail) return ''
    if (frameType === 'first') return shotDetail.first_frame_prompt ?? ''
    if (frameType === 'last') return shotDetail.last_frame_prompt ?? ''
    return shotDetail.key_frame_prompt ?? ''
  }

  const frameLabel: Record<PromptFrameType, string> = { first: '首帧', key: '关键帧', last: '尾帧' }

  const handleRefFrameTypeDropdownVisibleChange = useCallback(
    async (open: boolean) => {
      if (!open || !onRefreshShotFrameImages) return
      setRefFrameTypeSelectLoading(true)
      try {
        await onRefreshShotFrameImages()
      } finally {
        setRefFrameTypeSelectLoading(false)
      }
    },
    [onRefreshShotFrameImages],
  )

  const refFrameTypeOptions = useMemo(() => {
    const kinds = new Set((frameImages ?? []).map((x) => x.frame_type))
    const opts: Array<{ value: string; label: string }> = []
    if (kinds.has('first')) opts.push({ value: 'first', label: '首帧' })
    if (kinds.has('last')) opts.push({ value: 'last', label: '尾帧' })
    if (kinds.has('first') && kinds.has('last')) opts.push({ value: 'first_last', label: '首尾帧' })
    if (kinds.has('key')) opts.push({ value: 'key', label: '关键帧' })
    return opts
  }, [frameImages])

  useEffect(() => {
    const allowed = new Set(refFrameTypeOptions.map((x) => x.value))
    setRefImageType((prev) => (prev && allowed.has(prev) ? prev : undefined))
  }, [refFrameTypeOptions])

  const buildVideoRefSelection = () => {
    const first = frameImages.find((x) => x.frame_type === 'first')?.file_id ?? null
    const last = frameImages.find((x) => x.frame_type === 'last')?.file_id ?? null
    const key = frameImages.find((x) => x.frame_type === 'key')?.file_id ?? null

    const s = refImageType
    if (s === 'first_last') {
      return {
        referenceMode: 'first_last' as const,
        images: [first, last].filter((x): x is string => Boolean(x)),
      }
    }
    if (s === 'key') return { referenceMode: 'key' as const, images: key ? [key] : [] }
    if (s === 'first') return { referenceMode: 'first' as const, images: first ? [first] : [] }
    if (s === 'last') return { referenceMode: 'last' as const, images: last ? [last] : [] }
    return { referenceMode: 'text_only' as const, images: [] }
  }

  const openVideoPromptPreview = async () => {
    if (!selectedShot?.id) {
      message.warning('请先选择一个分镜')
      return
    }
    const { referenceMode, images } = buildVideoRefSelection()
    const nextContext = { referenceMode, images }
    videoPromptDraft.hydrate({
      base: { prompt: '' },
      context: nextContext,
    })
    setVideoPromptContextCollapsed(true)
    setVideoPromptPreviewOpen(true)
    setVideoPromptPreviewLoading(true)
    try {
      const derived = await videoPromptDraft.deriveNow({
        base: { prompt: '' },
        context: nextContext,
      })
      if (derived) {
        videoPromptDraft.hydrate({
          base: { prompt: derived.prompt },
          context: {
            referenceMode,
            images: derived.images,
          },
          derived,
        })
      }
    } catch {
      message.error('获取视频提示词预览失败')
    } finally {
      setVideoPromptPreviewLoading(false)
    }
  }

  const submitVideoGeneration = async () => {
    if (!selectedShot?.id) {
      message.warning('请先选择一个分镜')
      return
    }
    if (!resolveVideoRatioForRequest()) {
      message.warning('当前镜头缺少视频比例，请先设置项目默认比例或镜头覆盖比例')
      return
    }
    const prompt = (videoPromptPreviewDraft || '').trim()
    if (!prompt) {
      message.warning('请输入视频提示词')
      return
    }
    setVideoPromptPreviewSubmitting(true)
    try {
      const submitted = await videoPromptDraft.submitNow()
      const taskId = submitted?.taskId
      if (!taskId) {
        message.error('视频生成任务创建失败：服务端未返回任务 ID')
        return
      }
      setVideoTaskId(taskId)
      setVideoTaskStatus('pending')
      setVideoTaskPolling(true)
      setVideoTask({
        taskId,
        status: 'pending',
        progress: 0,
        cancelRequested: false,
      })
      setVideoSettledTask(null)
      setVideoPromptPreviewOpen(false)
    } catch (e) {
      message.error(defaultTaskActionErrorMessage(e, '发起视频生成失败'))
    } finally {
      setVideoPromptPreviewSubmitting(false)
    }
  }

  useEffect(() => {
    if (!videoTaskPolling || !videoTaskId) return
    let cancelled = false
    void (async () => {
      try {
        let finalTaskState: RelationTaskState | null = null
        for (let i = 0; i < 60; i += 1) {
          await sleep(2000)
          if (cancelled) return
          const statusRes = await FilmService.getTaskStatusApiV1FilmTasksTaskIdStatusGet({ taskId: videoTaskId })
          const status = statusRes.data?.status ?? null
          if (!status) continue
          if (statusRes.data) {
            finalTaskState = toRelationTaskStateFromStatusRead(statusRes.data)
            setVideoTask(finalTaskState)
          }
          setVideoTaskStatus(status)
          if (status === 'succeeded' || status === 'failed' || status === 'cancelled') break
        }
        if (
          !cancelled &&
          finalTaskState &&
          (finalTaskState.status === 'succeeded' ||
            finalTaskState.status === 'failed' ||
            finalTaskState.status === 'cancelled')
        ) {
          setVideoTask(null)
          setVideoSettledTask(finalTaskState)
        }
      } catch {
        if (!cancelled) {
          message.error('获取视频任务状态失败')
        }
      } finally {
        if (!cancelled) setVideoTaskPolling(false)
      }
    })()
    return () => {
      cancelled = true
    }
  }, [videoTaskPolling, videoTaskId])
  const updateCardState = (frameType: PromptFrameType, patch: Partial<KeyframeCardState>) => {
    setKeyframeCards((prev) => ({ ...prev, [frameType]: { ...prev[frameType], ...patch } }))
  }

  const getLatestFrameSlotId = async (frameType: PromptFrameType): Promise<number | null> => {
    if (!selectedShot?.id) return null
    const res = await StudioShotFrameImagesService.listShotFrameImagesApiV1StudioShotFrameImagesGet({
      shotDetailId: selectedShot.id,
      order: null,
      isDesc: false,
      page: 1,
      pageSize: 100,
    })
    const items = (res.data?.items ?? []) as ShotFrameImageRead[]
    const slot = items.find((x) => x.frame_type === frameType)
    return slot?.id ?? null
  }

  const loadCardThumbs = async (frameType: PromptFrameType, slotIdOverride?: number | null, retryCount = 1) => {
    const localSlotId = frameImages.find((x) => x.frame_type === frameType)?.id ?? null
    const slotId = slotIdOverride ?? localSlotId ?? (await getLatestFrameSlotId(frameType))
    if (!slotId) {
      updateCardState(frameType, { thumbs: [] })
      return
    }
    let thumbs: Array<{ linkId: number; fileId: string; thumbUrl: string }> = []
    for (let i = 0; i < retryCount; i += 1) {
      const links = await listTaskLinksNormalized({
        resourceType: 'image',
        relationType: 'shot_frame_image',
        relationEntityId: String(slotId),
        order: 'updated_at',
        isDesc: true,
        page: 1,
        pageSize: 100,
      })
      const seen = new Set<string>()
      thumbs = links
        .filter((l) => Boolean(l.file_id))
        .filter((l) => {
          const fid = String(l.file_id)
          if (seen.has(fid)) return false
          seen.add(fid)
          return true
        })
        .map((l) => ({
          linkId: l.id,
          fileId: String(l.file_id),
          thumbUrl: buildFileDownloadUrl(String(l.file_id)) ?? '',
        }))
      if (thumbs.length > 0 || i === retryCount - 1) break
      await sleep(800)
    }
    updateCardState(frameType, { thumbs })
  }

  const generateKeyframeCard = async (frameType: PromptFrameType) => {
    if (!selectedShot?.id) {
      message.warning('请先选择一个分镜')
      return
    }
    try {
      setKeyframePromptPreviewLoading(true)
      setKeyframePromptPreviewOpen(true)
      setKeyframePromptPreviewFrameType(frameType)
      setKeyframePromptRefManualTouched(false)
      setKeyframePromptDebugCollapsed(true)
      setKeyframeDirectiveCollapsed(true)
      setKeyframePromptDecisionCollapsed(true)
      const basePrompt = getPromptFromDetailByType(frameType)
      keyframePromptDraft.hydrate({
        base: { frameType, prompt: basePrompt },
        context: { refFileIds: autoKeyframeRefFileIds },
        state: basePrompt.trim() ? 'draft_changed' : 'idle',
      })
      setKeyframePromptDebugContext(null)
      setKeyframePromptQualityChecks(null)
      // 文本区域内容：统一由 frame-render-prompt 获取
      if (basePrompt.trim()) {
        void renderShotPromptToTextarea({
          frameType,
          prompt: basePrompt,
          refFileIds: autoKeyframeRefFileIds,
          showPreviewLoading: true,
        })
      } else {
        setKeyframePromptPreviewLoading(false)
      }
    } catch {
      message.error('获取提示词失败')
      setKeyframePromptPreviewLoading(false)
    } finally {
      // loading 由 renderShotPromptToTextarea 结束后关闭
    }
  }

  const regenerateKeyframePrompt = async () => {
    if (!selectedShot?.id) {
      message.warning('请先选择一个分镜')
      return
    }
    const frameType = keyframePromptPreviewFrameType
    setKeyframePromptActionLoading(true)
    try {
      const created = await FilmService.createShotFramePromptTaskApiV1FilmTasksShotFramePromptsPost({
        requestBody: {
          shot_id: selectedShot.id,
          frame_type: frameType,
        },
      })
      const taskId = extractTaskIdFromApiEnvelope(created)
      if (!taskId) {
        message.error('生成任务创建失败：服务端未返回任务 ID')
        return
      }
      setPromptTask({
        taskId,
        status: 'pending',
        progress: 0,
        cancelRequested: false,
      })
      setPromptSettledTask(null)

      let finalStatus = 'pending'
      let finalTaskState: RelationTaskState | null = null
      for (let i = 0; i < 30; i += 1) {
        await sleep(2000)
        const statusRes = await FilmService.getTaskStatusApiV1FilmTasksTaskIdStatusGet({ taskId })
        const status = statusRes.data?.status
        if (!status) continue
        finalStatus = status
        if (statusRes.data) {
          finalTaskState = toRelationTaskStateFromStatusRead(statusRes.data)
          setPromptTask(finalTaskState)
        }
        if (status === 'succeeded' || status === 'failed' || status === 'cancelled') break
      }
      if (
        finalTaskState &&
        (finalTaskState.status === 'succeeded' ||
          finalTaskState.status === 'failed' ||
          finalTaskState.status === 'cancelled')
      ) {
        setPromptTask(null)
        setPromptSettledTask(finalTaskState)
      }

      if (finalStatus !== 'succeeded') {
        if (finalStatus !== 'failed' && finalStatus !== 'cancelled') {
          message.warning('生成任务仍在执行，请稍后重试')
        }
        return
      }

      const resultRes = await FilmService.getTaskResultApiV1FilmTasksTaskIdResultGet({ taskId })
      const result = (resultRes.data?.result ?? null) as Record<string, unknown> | null
      const generatedPrompt = typeof result?.prompt === 'string' ? result.prompt : ''
      const debugContext =
        result && typeof result.debug_context === 'object' && result.debug_context !== null
          ? (result.debug_context as ShotFramePromptDebugContext)
          : null
      const qualityChecks =
        result &&
        typeof result.quality_checks === 'object' &&
        result.quality_checks !== null &&
        typeof (result.quality_checks as Record<string, unknown>).passed === 'boolean'
          ? {
              passed: Boolean((result.quality_checks as Record<string, unknown>).passed),
              issues: Array.isArray((result.quality_checks as Record<string, unknown>).issues)
                ? ((result.quality_checks as Record<string, unknown>).issues as unknown[])
                    .map((item) => (typeof item === 'string' ? item.trim() : ''))
                    .filter(Boolean)
                : [],
            }
          : null
      if (!generatedPrompt.trim()) {
        message.warning('生成完成，但未返回提示词')
        return
      }
      if (frameType === 'first') {
        onPatchShotDetail({ first_frame_prompt: generatedPrompt })
      } else if (frameType === 'last') {
        onPatchShotDetail({ last_frame_prompt: generatedPrompt })
      } else {
        onPatchShotDetail({ key_frame_prompt: generatedPrompt })
      }
      setKeyframePromptDebugContext(debugContext)
      setKeyframePromptQualityChecks(qualityChecks)
      keyframePromptDraft.replaceBase({ frameType, prompt: generatedPrompt })
      keyframePromptDraft.setState('draft_changed')
      await renderShotPromptToTextarea({
        frameType,
        prompt: generatedPrompt,
        refFileIds: keyframePromptPreviewRefFileIds.length > 0 ? keyframePromptPreviewRefFileIds : autoKeyframeRefFileIds,
      })
      message.success('提示词已生成')
    } catch (e) {
      message.error(defaultTaskActionErrorMessage(e, '生成提示词失败'))
    } finally {
      setKeyframePromptActionLoading(false)
    }
  }

  useEffect(() => {
    // 弹窗打开时，若当前没有参考图，则自动填充为分镜关联实体的参考图
    if (!keyframePromptPreviewOpen) return
    if (keyframePromptRefManualTouched) return
    if (keyframePromptPreviewRefFileIds.length > 0) return
    if (autoKeyframeRefFileIds.length === 0) return
    keyframePromptDraft.setContext({ refFileIds: autoKeyframeRefFileIds })
  }, [autoKeyframeRefFileIds, keyframePromptPreviewOpen, keyframePromptPreviewRefFileIds.length, keyframePromptRefManualTouched])

  useEffect(() => {
    if (!keyframePromptPreviewOpen) return
    if (mapGenerationDraftStateToRenderState(keyframePromptRenderState) !== 'stale') return
    const basePrompt = (keyframePromptPreviewDraft || '').trim()
    if (!basePrompt) return
    const refFileIds =
      keyframePromptPreviewRefFileIds.length > 0 ? keyframePromptPreviewRefFileIds : autoKeyframeRefFileIds
    const timer = window.setTimeout(() => {
      void renderShotPromptToTextarea({
        frameType: keyframePromptPreviewFrameType,
        prompt: basePrompt,
        refFileIds,
      })
    }, 400)
    return () => {
      window.clearTimeout(timer)
    }
  }, [
    autoKeyframeRefFileIds,
    keyframePromptPreviewDraft,
    keyframePromptPreviewFrameType,
    keyframePromptPreviewOpen,
    keyframePromptPreviewRefFileIds,
    keyframePromptRenderState,
    renderShotPromptToTextarea,
  ])

  const confirmGenerateKeyframeWithPrompt = async () => {
    if (!selectedShot?.id) {
      message.warning('请先选择一个分镜')
      return
    }
    const frameType = keyframePromptPreviewFrameType
    const basePrompt = (keyframePromptPreviewDraft || '').trim()
    if (!basePrompt) {
      message.warning('请输入提示词')
      return
    }

    setKeyframePromptActionLoading(true)
    updateCardState(frameType, { loading: true, taskStatus: 'pending', taskId: null })
    try {
      const refFileIds = keyframePromptPreviewRefFileIds.length > 0 ? keyframePromptPreviewRefFileIds : autoKeyframeRefFileIds
      keyframePromptDraft.replaceContext({ refFileIds })
      const submitted = await keyframePromptDraft.submitNow()
      const taskId = submitted?.taskId
      if (!taskId) {
        message.error('生成任务创建失败：服务端未返回任务 ID')
        updateCardState(frameType, { loading: false, taskStatus: 'failed' })
        return
      }
      updateCardState(frameType, { taskId })
      setFrameImageTask({
        taskId,
        status: 'pending',
        progress: 0,
        cancelRequested: false,
      })
      setFrameImageSettledTask(null)

      let finalStatus = 'pending'
      let finalTaskState: RelationTaskState | null = null
      for (let i = 0; i < 30; i += 1) {
        await sleep(2000)
        const statusRes = await FilmService.getTaskStatusApiV1FilmTasksTaskIdStatusGet({ taskId })
        const status = statusRes.data?.status
        if (!status) continue
        finalStatus = status
        if (statusRes.data) {
          finalTaskState = toRelationTaskStateFromStatusRead(statusRes.data)
          setFrameImageTask(finalTaskState)
        }
        updateCardState(frameType, { taskStatus: status })
        if (status === 'succeeded' || status === 'failed' || status === 'cancelled') break
      }
      if (
        finalTaskState &&
        (finalTaskState.status === 'succeeded' ||
          finalTaskState.status === 'failed' ||
          finalTaskState.status === 'cancelled')
      ) {
        setFrameImageTask(null)
        setFrameImageSettledTask(finalTaskState)
      }
      if (finalStatus === 'succeeded') {
        const latestSlotId = await getLatestFrameSlotId(frameType)
        await loadCardThumbs(frameType, latestSlotId, 5)
        setKeyframePromptPreviewOpen(false)
      } else if (finalStatus === 'failed') {
        const err = finalTaskState?.error?.trim()
        message.error(
          err ? `${frameLabel[frameType]}生成失败：${err}` : `${frameLabel[frameType]}生成失败，请查看任务中心或稍后重试`,
        )
      } else if (finalStatus === 'cancelled') {
        message.warning(`${frameLabel[frameType]}生成已取消`)
      } else {
        message.warning('生成任务仍在执行，请稍后刷新')
      }
    } catch (e) {
      updateCardState(frameType, { taskStatus: 'failed' })
      message.error(defaultTaskActionErrorMessage(e, `${frameLabel[frameType]}生成失败`))
    } finally {
      updateCardState(frameType, { loading: false })
      setKeyframePromptActionLoading(false)
    }
  }

  const applyCardImage = async (frameType: PromptFrameType, fileId: string) => {
    const slot = frameImages.find((x) => x.frame_type === frameType)
    if (!slot) return
    updateCardState(frameType, { applyingFileId: fileId })
    try {
      await StudioShotFrameImagesService.updateShotFrameImageApiV1StudioShotFrameImagesImageIdPatch({
        imageId: slot.id,
        requestBody: { file_id: fileId } as any,
      })
      await loadCardThumbs(frameType)
      message.success('已切换使用图片')
    } catch {
      message.error('切换失败')
    } finally {
      updateCardState(frameType, { applyingFileId: null })
    }
  }

  useEffect(() => {
    if (!selectedShot?.id) return
    void Promise.all([loadCardThumbs('first'), loadCardThumbs('key'), loadCardThumbs('last')])
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [selectedShot?.id, frameImages.map((x) => `${x.id}:${x.file_id ?? ''}`).join('|')])

  const pendingDialogueCandidates = shotDialogueCandidateItems.filter((item) => item.candidate_status === 'pending')

  return (
    <div className="w-full h-full flex flex-col min-h-0">
      <div className="cs-inspector-header flex items-center justify-between">
        <div className="min-w-0">
          <div className="font-medium truncate">分镜生成面板</div>
          <div className="text-xs text-gray-500 truncate">
            {selectedShot ? `${String(selectedShot.index).padStart(2, '0')} · ${selectedShot.title}` : '未选择分镜'}
          </div>
        </div>
        <Space size="small">
          <Tooltip title="收起">
            <Button size="small" type="text" icon={<DoubleRightOutlined />} onClick={onClose} />
          </Tooltip>
        </Space>
      </div>

      <div className="cs-inspector flex-1 min-h-0 overflow-auto">
        <Tabs
          tabPosition="left"
          activeKey={inspectorTabKey}
          onChange={(activeKey) => setInspectorTabKey(activeKey as InspectorTabKey)}
          items={(() => {
            const items = [
              {
              key: 'ops',
              label: '维护设置',
              children: (
                <ChapterStudioMaintenancePanel
                  opsTitleDraft={opsTitleDraft}
                  opsNoteDraft={opsNoteDraft}
                  hideShot={hideShot}
                  onChangeTitle={setOpsTitleDraft}
                  onBlurTitle={() => {
                    void flushOpsTitle()
                  }}
                  onChangeNote={setOpsNoteDraft}
                  onBlurNote={() => {
                    void flushOpsNote()
                  }}
                  onToggleHidden={setHideShot}
                  onRequestDelete={() => {
                    if (!selectedShot?.id) return
                    Modal.confirm({
                      title: '删除分镜？',
                      content: '此操作不可撤销。',
                      okText: '删除',
                      okButtonProps: { danger: true },
                      cancelText: '取消',
                      onOk: () => onDeleteShotOps(selectedShot.id),
                    })
                  }}
                />
              ),
            },
              {
              key: 'camera',
              label: '生成参数',
              children: (
                <div>
                  {loadingDetail ? (
                    <div className="text-gray-500">加载中…</div>
                  ) : shotDetail ? (
                    <>
                      <div className="cs-group">
                        <div className="cs-group-title">
                          <CameraOutlined /> 镜头语言
                        </div>
                        <div className="space-y-4">
                          <div>
                            <div className="text-gray-500 text-xs mb-1">景别</div>
                            <Radio.Group
                              value={shotDetail.camera_shot}
                              optionType="button"
                              buttonStyle="solid"
                              size="small"
                              options={CAMERA_SHOT_OPTIONS}
                              onChange={(e) => void onPatchShotDetailImmediate({ camera_shot: e.target.value })}
                              disabled={cameraUpdating}
                            />
                          </div>
                          <div>
                            <div className="text-gray-500 text-xs mb-1">角度</div>
                            <Radio.Group
                              value={shotDetail.angle}
                              optionType="button"
                              size="small"
                              options={CAMERA_ANGLE_OPTIONS}
                              onChange={(e) => void onPatchShotDetailImmediate({ angle: e.target.value })}
                              disabled={cameraUpdating}
                            />
                          </div>
                          <div>
                            <div className="text-gray-500 text-xs mb-1">运镜</div>
                            <Radio.Group
                              value={shotDetail.movement}
                              size="small"
                              options={CAMERA_MOVEMENT_OPTIONS}
                              onChange={(e) => void onPatchShotDetailImmediate({ movement: e.target.value })}
                              disabled={cameraUpdating}
                            />
                          </div>
                          <div>
                            <div className="text-gray-500 text-xs mb-1">时长（1–30s，整数）</div>
                            <div className="flex items-center gap-2">
                              <Slider
                                min={1}
                                max={30}
                                step={1}
                                value={Math.max(1, Math.min(30, Math.round(shotDetail.duration ?? 1)))}
                                style={{ flex: 1 }}
                                onChange={(v) => void onPatchShotDetailImmediate({ duration: Math.round(Number(v)) })}
                                disabled={cameraUpdating}
                              />
                              <Input
                                size="small"
                                value={`${Math.max(1, Math.min(30, Math.round(shotDetail.duration ?? 1)))}`}
                                style={{ width: 72 }}
                                onChange={(e) => {
                                  const raw = Number(e.target.value)
                                  if (!Number.isFinite(raw)) return
                                  const n = Math.max(1, Math.min(30, Math.round(raw)))
                                  void onPatchShotDetailImmediate({ duration: n })
                                }}
                                disabled={cameraUpdating}
                              />
                            </div>
                          </div>
                          <div>
                            <div className="text-gray-500 text-xs mb-1">视频比例</div>
                            <Select
                              size="small"
                              allowClear
                              value={shotDetail.override_video_ratio ?? undefined}
                              placeholder={projectDefaultVideoRatio || capabilityDefaultVideoRatio || '请选择视频比例'}
                              options={videoRatioOptions}
                              onChange={(value) => {
                                onPatchShotDetail({ override_video_ratio: value ?? null })
                              }}
                              disabled={cameraUpdating}
                            />
                            <div className="mt-1 text-[11px] text-gray-400">
                              当前生效：{resolveVideoRatioForRequest() || '未设置'}
                            </div>
                          </div>
                        </div>
                      </div>

                      <div className="cs-group">
                        <div className="cs-group-title">
                          <TagOutlined /> 情绪标签
                        </div>
                        <div className="cs-hint">用标签快速标记镜头情绪，便于生成风格统一。</div>
                        <div className="mt-3">
                          <Space wrap>
                            {['愤怒', '反转', '紧张', '温馨', '压抑'].map((t) => (
                              <Tag key={t} className="cursor-pointer">
                                {t}
                              </Tag>
                            ))}
                            <Button size="small" type="dashed">
                              + 自定义
                            </Button>
                          </Space>
                        </div>
                      </div>
                    </>
                  ) : (
                    <div className="text-gray-500">请选择分镜</div>
                  )}
                </div>
              ),
            },
              {
              key: 'prompt_image',
              label: '确认诊断',
              children: (
                <div>
                  <ChapterStudioReadinessDiagnosisPanel
                    selectedShot={selectedShot}
                    shotAssetsOverview={shotAssetsOverview}
                    promptAssetReadiness={promptAssetReadiness}
                    promptAssetReadinessNote={promptAssetReadinessNote}
                    shotExtractStatusSource={shotExtractStatus.source}
                    shotExtractStatusText={shotExtractStatusText}
                    onGoToShotEdit={goToShotEditForAssets}
                    onHandleMissingAction={(kind, name) => {
                      void handleReadinessMissingAction(kind, name)
                    }}
                    getReadinessExistenceLabel={getReadinessExistenceLabel}
                  />

                  <div className="cs-group">
                    <div className="cs-group-title">
                      <PictureOutlined /> 氛围描述
                    </div>
                    <div>
                        <div className="flex items-center justify-between">
                          <div className="text-gray-500 text-xs">氛围描述</div>
                          <Switch
                            size="small"
                            checked={shotDetail?.follow_atmosphere ?? false}
                            onChange={(v) => onPatchShotDetail({ follow_atmosphere: v })}
                          />
                        </div>
                        <TextArea
                          rows={3}
                          placeholder="氛围描述…（可选跟随画面）"
                          value={shotDetail?.atmosphere ?? ''}
                          onChange={(e) => onPatchShotDetail({ atmosphere: e.target.value })}
                        />
                    </div>
                  </div>

                </div>
              ),
            },
              {
              key: 'dialogue',
              label: '对白状态',
              children: (
                <div>
                  <div className="cs-group">
                    <div className="cs-group-title">
                      <SoundOutlined /> 对白状态
                    </div>
                    <div className="cs-hint">这里主要查看当前镜头对白与待确认状态。对白候选的主确认入口在分镜编辑页，工作室侧重继续准备关键帧、图片和视频生成。</div>
                    <div className="space-y-4 mt-3">
                      <div>
                        <Button icon={<EditOutlined />} onClick={goToShotEditForAssets}>
                          去分镜编辑确认对白
                        </Button>
                      </div>
                      <div className="rounded-lg border border-dashed border-slate-200 bg-slate-50 px-3 py-3 text-xs text-slate-500">
                        如需新增对白、接受候选或忽略候选，请前往分镜编辑页处理。工作室这里主要用于查看当前对白状态，并继续后续生成准备。
                      </div>

                      {pendingDialogueCandidates.length > 0 ? (
                        <div>
                          <div className="text-gray-500 text-xs mb-2">待确认对白候选</div>
                          <div className="space-y-2">
                            {pendingDialogueCandidates.map((candidate) => (
                              <div key={candidate.id} className="rounded-lg border border-amber-200 bg-amber-50 px-3 py-2">
                                <div className="flex items-start justify-between gap-2">
                                  <div className="min-w-0">
                                    <div className="text-xs text-amber-700 mb-1">
                                      {candidate.speaker_name?.trim() || '未知'} → {candidate.target_name?.trim() || '未知'}
                                    </div>
                                    <div className="text-xs text-gray-700 break-words">{candidate.text}</div>
                                  </div>
                                  <Button size="small" icon={<EditOutlined />} onClick={goToShotEditForAssets}>
                                    去编辑页处理
                                  </Button>
                                </div>
                              </div>
                            ))}
                          </div>
                        </div>
                      ) : null}

                      <div>
                        <div className="text-gray-500 text-xs mb-2">当前对白</div>
                        {dialogLines.length > 0 ? (
                          <div className="space-y-1">
                            {dialogLines.slice().sort((a, b) => (a.index ?? 0) - (b.index ?? 0)).map((l) => (
                              <div key={l.id} className="flex items-center gap-2">
                                <div className="text-xs text-gray-600 truncate flex-1 min-w-0">{l.text}</div>
                                <Button
                                  size="small"
                                  type="text"
                                  danger
                                  icon={<DeleteOutlined />}
                                  onClick={() => {
                                    Modal.confirm({
                                      title: '删除该对白？',
                                      okText: '删除',
                                      cancelText: '取消',
                                      okButtonProps: { danger: true },
                                      onOk: async () => {
                                        try {
                                          await onDeleteDialogLine(l.id)
                                          message.success('已删除')
                                        } catch {
                                          message.error('删除失败')
                                        }
                                      },
                                    })
                                  }}
                                />
                              </div>
                            ))}
                          </div>
                        ) : (
                          <div className="text-xs text-gray-400">当前镜头还没有对白。</div>
                        )}
                      </div>
                    </div>
                  </div>
                </div>
              ),
            },
              {
              key: 'keyframe_gen',
              label: '关键帧与参考图',
              children: (
                <div className="space-y-3">
                  <div className="cs-group">
                    <div className="cs-group-title">
                      <SettingOutlined /> 关键帧规格
                    </div>
                    <div className="text-xs text-gray-500 mb-2">
                      关键帧会跟随当前视频比例生成；这里控制参考帧分辨率档位。
                    </div>
                    <div className="flex items-center gap-3">
                      <div className="min-w-[96px] text-xs text-gray-500">分辨率档位</div>
                      <Select
                        size="small"
                        value={keyframeResolutionProfile}
                        style={{ width: 160 }}
                        options={[
                          { value: 'standard', label: '标准（2K）' },
                          { value: 'high', label: '高清（3K）' },
                        ]}
                        onChange={(value) => onChangeKeyframeResolutionProfile(value as KeyframeResolutionProfile)}
                      />
                    </div>
                    <div className="mt-2 rounded bg-gray-50 px-3 py-2 text-xs text-gray-600">
                      <div>
                        当前规格：{resolvedKeyframeRatio || '未设置比例'} ·{' '}
                        {getResolutionProfileLabel(keyframeResolutionProfile)}
                        {resolvedKeyframePixelSize ? ` → ${resolvedKeyframePixelSize}` : ''}
                      </div>
                      <div className="mt-1 text-gray-500">
                        当前模型：{imageGenerationOptions?.provider || '未识别供应商'}
                        {imageGenerationOptions?.model_name ? ` / ${imageGenerationOptions.model_name}` : ''}
                      </div>
                    </div>
                  </div>
                  {(['first', 'key', 'last'] as PromptFrameType[]).map((ft) => {
                    const st = keyframeCards[ft]
                    const slot = frameImages.find((x) => x.frame_type === ft)
                    const inUseFileId = slot?.file_id ? String(slot.file_id) : ''
                    const statusText =
                      st.taskStatus === 'pending'
                        ? '排队中'
                        : st.taskStatus === 'running'
                          ? '生成中'
                          : st.taskStatus === 'succeeded'
                            ? '已完成'
                            : st.taskStatus === 'failed'
                              ? '失败'
                              : st.taskStatus === 'cancelled'
                                ? '已取消'
                                : ''
                    return (
                      <div key={ft} className="cs-group">
                        <div className="cs-group-title flex items-center justify-between gap-2">
                          <span>{frameLabel[ft]}图片</span>
                          <Space size={8}>
                            <Button size="small" type="link" onClick={() => updateCardState(ft, { modalOpen: true })}>
                              更多
                            </Button>
                            <Button size="small" type="primary" loading={st.loading} onClick={() => void generateKeyframeCard(ft)}>
                              生成
                            </Button>
                          </Space>
                        </div>
                        <div className="text-xs text-gray-500 min-h-5">{statusText}</div>
                        {st.thumbs.length === 0 ? (
                          <div className="mt-2 h-24 border border-dashed rounded flex items-center justify-center text-xs text-gray-400">暂无图片</div>
                        ) : (
                          <div className="mt-2 flex items-center gap-2 overflow-x-auto whitespace-nowrap pb-1">
                            {st.thumbs.slice(0, 4).map((it) => (
                              <img key={it.linkId} src={it.thumbUrl} alt="" className="w-16 h-16 rounded object-cover border border-gray-200 shrink-0" />
                            ))}
                          </div>
                        )}
                        <Modal title={`${frameLabel[ft]}图片`} open={st.modalOpen} onCancel={() => updateCardState(ft, { modalOpen: false })} footer={null} width={720}>
                          {ft === 'first' ? (
                            <div className="mb-3">
                              <div className="text-sm text-gray-600 mb-2">关联角色</div>
                              <div className="flex items-center gap-2 overflow-x-auto pb-1">
                                <button
                                  type="button"
                                  className="w-12 h-12 rounded border border-dashed border-gray-300 flex items-center justify-center text-gray-500 shrink-0 hover:border-gray-400 hover:text-gray-700"
                                  disabled={promptAssetsUpdating || linkRoleLoading}
                                  onClick={() => {
                                    setLinkRoleSelectedIds([])
                                    setLinkRoleOpen(true)
                                    void loadProjectRoleOptions()
                                  }}
                                  title="添加关联角色"
                                >
                                  <PlusOutlined />
                                </button>
                                {linkedCharacterIds.length === 0 ? (
                                  <div className="text-xs text-gray-400">暂无关联角色</div>
                                ) : (
                                  linkedCharacterIds.map((cid) => {
                                    const thumb = linkedAssetThumbByKey.get(`character:${cid}`)
                                    const name = characterNameMap[cid] ?? cid
                                    return thumb ? (
                                    <Image
                                        key={cid}
                                        width={48}
                                        height={48}
                                        style={{ objectFit: 'cover', borderRadius: 8 }}
                                        src={resolveAssetUrl(thumb)}
                                        preview={{ src: resolveAssetUrl(thumb) }}
                                      />
                                    ) : (
                                      <div
                                        key={cid}
                                        title={name}
                                        className="w-12 h-12 rounded bg-gray-100 flex items-center justify-center text-gray-400 shrink-0"
                                      >
                                        <UserOutlined />
                                      </div>
                                    )
                                  })
                                )}
                              </div>

                              <div className="mt-3 text-sm text-gray-600 mb-2">关联场景</div>
                              <div className="flex items-center gap-2 overflow-x-auto pb-1">
                                <button
                                  type="button"
                                  className="w-12 h-12 rounded border border-dashed border-gray-300 flex items-center justify-center text-gray-500 shrink-0 hover:border-gray-400 hover:text-gray-700"
                                  disabled={promptAssetsUpdating || linkSceneLoading}
                                  onClick={() => {
                                    setLinkSceneOpen(true)
                                    void loadProjectAssetOptions('scene')
                                  }}
                                  title="添加/更换关联场景"
                                >
                                  <PlusOutlined />
                                </button>
                                {linkedSceneId ? (
                                  linkedAssetThumbByKey.get(`scene:${linkedSceneId}`) ? (
                                    <Image
                                      key={linkedSceneId}
                                      width={48}
                                      height={48}
                                      style={{ objectFit: 'cover', borderRadius: 8 }}
                                      src={resolveAssetUrl(linkedAssetThumbByKey.get(`scene:${linkedSceneId}`) ?? '')}
                                      preview={{ src: resolveAssetUrl(linkedAssetThumbByKey.get(`scene:${linkedSceneId}`) ?? '') }}
                                    />
                                  ) : (
                                    <div className="text-xs text-gray-400">已关联场景：{sceneNameMap[linkedSceneId] ?? linkedSceneId}</div>
                                  )
                                ) : (
                                  <div className="text-xs text-gray-400">暂无关联场景</div>
                                )}
                              </div>

                              <div className="mt-3 text-sm text-gray-600 mb-2">关联道具</div>
                              <div className="flex items-center gap-2 overflow-x-auto pb-1">
                                <button
                                  type="button"
                                  className="w-12 h-12 rounded border border-dashed border-gray-300 flex items-center justify-center text-gray-500 shrink-0 hover:border-gray-400 hover:text-gray-700"
                                  disabled={promptAssetsUpdating || linkPropLoading}
                                  onClick={() => {
                                    setLinkPropSelectedIds([])
                                    setLinkPropOpen(true)
                                    void loadProjectAssetOptions('prop')
                                  }}
                                  title="添加关联道具"
                                >
                                  <PlusOutlined />
                                </button>
                                {linkedPropIds.length === 0 ? (
                                  <div className="text-xs text-gray-400">暂无关联道具</div>
                                ) : (
                                  linkedPropIds.map((pid) =>
                                    linkedAssetThumbByKey.get(`prop:${pid}`) ? (
                                      <Image
                                        key={pid}
                                        width={48}
                                        height={48}
                                        style={{ objectFit: 'cover', borderRadius: 8 }}
                                        src={resolveAssetUrl(linkedAssetThumbByKey.get(`prop:${pid}`) ?? '')}
                                        preview={{ src: resolveAssetUrl(linkedAssetThumbByKey.get(`prop:${pid}`) ?? '') }}
                                      />
                                    ) : (
                                      <div key={pid} className="w-12 h-12 rounded bg-gray-100 flex items-center justify-center text-gray-400 shrink-0">
                                        <UserOutlined />
                                      </div>
                                    ),
                                  )
                                )}
                              </div>

                              <div className="mt-3 text-sm text-gray-600 mb-2">关联服装</div>
                              <div className="flex items-center gap-2 overflow-x-auto pb-1">
                                <button
                                  type="button"
                                  className="w-12 h-12 rounded border border-dashed border-gray-300 flex items-center justify-center text-gray-500 shrink-0 hover:border-gray-400 hover:text-gray-700"
                                  disabled={promptAssetsUpdating || linkCostumeLoading}
                                  onClick={() => {
                                    setLinkCostumeSelectedIds([])
                                    setLinkCostumeOpen(true)
                                    void loadProjectAssetOptions('costume')
                                  }}
                                  title="添加关联服装"
                                >
                                  <PlusOutlined />
                                </button>
                                {linkedCostumeIds.length === 0 ? (
                                  <div className="text-xs text-gray-400">暂无关联服装</div>
                                ) : (
                                  linkedCostumeIds.map((cid) =>
                                    linkedAssetThumbByKey.get(`costume:${cid}`) ? (
                                      <Image
                                        key={cid}
                                        width={48}
                                        height={48}
                                        style={{ objectFit: 'cover', borderRadius: 8 }}
                                        src={resolveAssetUrl(linkedAssetThumbByKey.get(`costume:${cid}`) ?? '')}
                                        preview={{ src: resolveAssetUrl(linkedAssetThumbByKey.get(`costume:${cid}`) ?? '') }}
                                      />
                                    ) : (
                                      <div key={cid} className="w-12 h-12 rounded bg-gray-100 flex items-center justify-center text-gray-400 shrink-0">
                                        <UserOutlined />
                                      </div>
                                    ),
                                  )
                                )}
                              </div>
                            </div>
                          ) : null}

                          <div className="grid grid-cols-2 md:grid-cols-3 gap-3">
                            {st.thumbs.map((it) => {
                              const inUse = inUseFileId && inUseFileId === it.fileId
                              return (
                                <div key={it.linkId} className="border rounded p-2">
                                  <img src={it.thumbUrl} alt="" className="w-full h-36 object-cover rounded" />
                                  <div className="mt-2 flex items-center justify-between">
                                    {inUse ? (
                                      <Tag color="green">使用中</Tag>
                                    ) : (
                                      <Button size="small" loading={st.applyingFileId === it.fileId} onClick={() => void applyCardImage(ft, it.fileId)}>
                                        使用
                                      </Button>
                                    )}
                                  </div>
                                </div>
                              )
                            })}
                          </div>

                          <Modal
                            title="关联角色"
                            open={linkRoleOpen}
                            onCancel={() => setLinkRoleOpen(false)}
                            footer={null}
                            destroyOnClose
                            width={560}
                          >
                            <div className="space-y-2">
                              <div className="text-xs text-gray-500">来源：当前项目全部角色（选择后立即保存；已关联的角色不可重复选择）</div>
                              <Select
                                mode="multiple"
                                className="w-full"
                                placeholder="选择要关联到当前分镜的角色"
                                value={linkRoleSelectedIds}
                                loading={linkRoleLoading}
                                disabled={promptAssetsUpdating}
                                options={projectRoleOptions}
                                optionFilterProp="searchLabel"
                                showSearch
                                filterOption={(input: string, option?: any) =>
                                  String(option?.searchLabel ?? '').toLowerCase().includes(input.toLowerCase())
                                }
                                onChange={(vals: Array<string | number>) => {
                                  const nextNew = (vals ?? []).map((v) => String(v)).filter(Boolean)
                                  setLinkRoleSelectedIds(nextNew)
                                  const merged = Array.from(new Set([...linkedCharacterIds, ...nextNew]))
                                  void (async () => {
                                    await onUpdatePromptActors(merged)
                                    setLinkRoleOpen(false)
                                    setLinkRoleSelectedIds([])
                                  })()
                                }}
                              />
                            </div>
                          </Modal>

                          <Modal
                            title="关联场景"
                            open={linkSceneOpen}
                            onCancel={() => setLinkSceneOpen(false)}
                            footer={null}
                            destroyOnClose
                            width={560}
                          >
                            <div className="space-y-2">
                              <div className="text-xs text-gray-500">来源：当前项目场景（选择后立即保存）</div>
                              <Select
                                className="w-full"
                                placeholder="选择要关联到当前分镜的场景"
                                value={linkedSceneId ?? undefined}
                                loading={linkSceneLoading}
                                disabled={promptAssetsUpdating}
                                options={projectSceneOptions}
                                optionFilterProp="searchLabel"
                                showSearch
                                filterOption={(input: string, option?: any) =>
                                  String(option?.searchLabel ?? '').toLowerCase().includes(input.toLowerCase())
                                }
                                onChange={(v: string) => {
                                  void (async () => {
                                    await onUpdatePromptScene(v)
                                    setLinkSceneOpen(false)
                                  })()
                                }}
                              />
                            </div>
                          </Modal>

                          <Modal
                            title="关联道具"
                            open={linkPropOpen}
                            onCancel={() => setLinkPropOpen(false)}
                            footer={null}
                            destroyOnClose
                            width={560}
                          >
                            <div className="space-y-2">
                              <div className="text-xs text-gray-500">来源：当前项目道具（选择后立即保存；已关联的不可重复选择）</div>
                              <Select
                                mode="multiple"
                                className="w-full"
                                placeholder="选择要关联到当前分镜的道具"
                                value={linkPropSelectedIds}
                                loading={linkPropLoading}
                                disabled={promptAssetsUpdating}
                                options={projectPropOptions}
                                optionFilterProp="searchLabel"
                                showSearch
                                filterOption={(input: string, option?: any) =>
                                  String(option?.searchLabel ?? '').toLowerCase().includes(input.toLowerCase())
                                }
                                onChange={(vals: Array<string | number>) => {
                                  const nextNew = (vals ?? []).map((v) => String(v)).filter(Boolean)
                                  setLinkPropSelectedIds(nextNew)
                                  const merged = Array.from(new Set([...linkedPropIds, ...nextNew]))
                                  void (async () => {
                                    await onUpdatePromptProps(merged)
                                    setLinkPropOpen(false)
                                    setLinkPropSelectedIds([])
                                  })()
                                }}
                              />
                            </div>
                          </Modal>

                          <Modal
                            title="关联服装"
                            open={linkCostumeOpen}
                            onCancel={() => setLinkCostumeOpen(false)}
                            footer={null}
                            destroyOnClose
                            width={560}
                          >
                            <div className="space-y-2">
                              <div className="text-xs text-gray-500">来源：当前项目服装（选择后立即保存；已关联的不可重复选择）</div>
                              <Select
                                mode="multiple"
                                className="w-full"
                                placeholder="选择要关联到当前分镜的服装"
                                value={linkCostumeSelectedIds}
                                loading={linkCostumeLoading}
                                disabled={promptAssetsUpdating}
                                options={projectCostumeOptions}
                                optionFilterProp="searchLabel"
                                showSearch
                                filterOption={(input: string, option?: any) =>
                                  String(option?.searchLabel ?? '').toLowerCase().includes(input.toLowerCase())
                                }
                                onChange={(vals: Array<string | number>) => {
                                  const nextNew = (vals ?? []).map((v) => String(v)).filter(Boolean)
                                  setLinkCostumeSelectedIds(nextNew)
                                  const merged = Array.from(new Set([...linkedCostumeIds, ...nextNew]))
                                  void (async () => {
                                    await onUpdatePromptCostumes(merged)
                                    setLinkCostumeOpen(false)
                                    setLinkCostumeSelectedIds([])
                                  })()
                                }}
                              />
                            </div>
                          </Modal>
                        </Modal>
                      </div>
                    )
                  })}
                </div>
              ),
            },
              ...(showAvTab ? [{
                key: 'av',
                label: '音视频控制',
                children: (
                  <div>
                    <div className="cs-group">
                      <div className="cs-group-title">
                        <CustomerServiceOutlined /> 配乐
                      </div>
                      <div className="space-y-3">
                        <Radio.Group
                          value={audioMode}
                          onChange={(e) => setAudioMode(e.target.value)}
                          options={[
                            { value: 'none', label: '无' },
                            { value: 'prompt', label: '提示词' },
                            { value: 'upload', label: '上传音频' },
                          ]}
                        />
                        {audioMode === 'prompt' && <TextArea rows={3} placeholder="配乐提示词（支持多版本）…" />}
                        {audioMode === 'upload' && (
                          <Button block icon={<UploadOutlined />}>
                            上传音频
                          </Button>
                        )}
                      </div>
                    </div>

                    <div className="cs-group">
                      <div className="cs-group-title">
                        <SoundOutlined /> 音效
                      </div>
                      <div className="space-y-3">
                        <Button block icon={<UploadOutlined />}>
                          添加一条音效（Mock）
                        </Button>
                      </div>
                    </div>

                    <div className="cs-group">
                      <div className="cs-group-title">
                        <SettingOutlined /> 开关
                      </div>
                      <div className="space-y-3">
                        <div className="flex items-center justify-between">
                          <span className="text-sm">关闭配乐</span>
                          <Switch />
                        </div>
                        <div className="flex items-center justify-between">
                          <span className="text-sm">关闭对白</span>
                          <Switch />
                        </div>
                        <div className="flex items-center justify-between">
                          <span className="text-sm">智能对口型</span>
                          <Switch />
                        </div>
                      </div>
                    </div>
                  </div>
                ),
              }] : []),
              {
              key: 'gen_ref',
              label: '视频生成',
              children: (
                <div>
                  <ChapterStudioVideoReadinessPanel
                    selectedShot={selectedShot}
                    videoReadinessLoading={videoReadinessLoading}
                    videoReadiness={videoReadiness}
                    videoReferenceMode={videoReferenceMode}
                  />

                  <div className="cs-group">
                    <div className="cs-group-title">
                      <LinkOutlined /> 参考
                    </div>
                    <Select
                      allowClear
                      placeholder="按已有关键帧类型选择"
                      className="w-full"
                      value={refImageType}
                      onChange={(v) => setRefImageType(v === undefined || v === null ? undefined : String(v))}
                      options={refFrameTypeOptions}
                      loading={refFrameTypeSelectLoading}
                      onDropdownVisibleChange={handleRefFrameTypeDropdownVisibleChange}
                    />
                  </div>

                  {showGenRefParams && (
                    <div className="cs-group">
                      <div className="cs-group-title">
                        <ToolOutlined /> 参数
                      </div>
                      <Space direction="vertical" className="w-full" size="small">
                        <Select
                          size="small"
                          placeholder="模型选择"
                          options={[
                            { value: 'model_a', label: '模型 A（写实）' },
                            { value: 'model_b', label: '模型 B（风格化）' },
                          ]}
                        />
                        <div className="flex items-center justify-between">
                          <span className="text-sm">ControlNet（深度/骨骼）</span>
                          <Switch checked={useBoneDepth} onChange={setUseBoneDepth} />
                        </div>
                        <Slider min={3} max={12} defaultValue={5} />
                      </Space>
                    </div>
                  )}

                  <div className="cs-group">
                    <div className="cs-group-title">
                      <ThunderboltOutlined /> 生成
                    </div>
                    <Space wrap>
                      <Button type="primary" icon={<VideoCameraOutlined />} loading={videoPromptPreviewSubmitting || videoTaskPolling} onClick={() => void openVideoPromptPreview()}>
                        生成视频
                      </Button>
                      {videoTaskStatus ? <span className="text-xs text-gray-500">任务状态：{videoTaskStatus}</span> : null}
                    </Space>
                  </div>

                  <div className="cs-group">
                    <div className="cs-group-title">
                      <VideoCameraOutlined /> 已生成视频
                    </div>
                    {generatedVideos.length === 0 ? (
                      <div className="text-xs text-gray-400">当前分镜暂无已生成视频</div>
                    ) : (
                      <div className="flex flex-col gap-3">
                        {generatedVideos.map((item, idx) => (
                          <div
                            key={`${item.linkId}-${item.fileId}`}
                            className="rounded-lg border border-gray-200 p-2 sm:p-3"
                          >
                            <div className="relative w-full overflow-hidden rounded-md bg-black aspect-video">
                              <video
                                src={item.url}
                                className="absolute inset-0 h-full w-full object-cover"
                                preload="metadata"
                                muted
                                onClick={() => onSelectPreviewVideo(item.fileId)}
                                style={{ cursor: 'pointer' }}
                              />
                            </div>
                            <div className="mt-2 flex min-w-0 items-center justify-between gap-3">
                              <span className="text-xs text-gray-600 whitespace-nowrap shrink-0">
                                视频 {idx + 1}
                              </span>
                              <Tooltip title="下载视频">
                                <Button
                                  size="small"
                                  type="default"
                                  icon={<DownloadOutlined />}
                                  className="shrink-0"
                                  onClick={() => {
                                    if (!item.url) return
                                    window.open(item.url, '_blank', 'noopener,noreferrer')
                                  }}
                                />
                              </Tooltip>
                            </div>
                          </div>
                        ))}
                      </div>
                    )}
                  </div>

                  {showGenRefVersions && (
                    <div className="cs-group">
                      <div className="cs-group-title">
                        <AppstoreOutlined /> 版本
                      </div>
                      <Tabs
                        type="card"
                        size="small"
                        activeKey={imageVersion}
                        onChange={setImageVersion}
                        items={[
                          { key: 'v1', label: 'v1' },
                          { key: 'v2', label: 'v2' },
                          { key: 'v3', label: 'v3' },
                        ]}
                      />
                    </div>
                  )}
                </div>
              ),
              },
            ]

            const order: Record<string, number> = {
              gen_ref: 0,
              keyframe_gen: 1,
              camera: 2,
              prompt_image: 3,
              dialogue: 4,
              ops: 5,
              av: 6,
            }

            return items.sort((a, b) => (order[String(a.key)] ?? 999) - (order[String(b.key)] ?? 999))
          })()}
        />

        <Modal
          title={`${frameLabel[keyframePromptPreviewFrameType]}图片生成提示词预览`}
          open={keyframePromptPreviewOpen}
          onCancel={() => {
            if (keyframePromptActionLoading) return
            setKeyframePromptPreviewOpen(false)
          }}
          footer={(
            <div className="flex items-center justify-between">
              <div />
              <Space>
                <Button
                  loading={keyframePromptActionLoading}
                  onClick={() => {
                    if (keyframePromptActionLoading) return
                    setKeyframePromptPreviewOpen(false)
                  }}
                >
                  取消
                </Button>
                <Button type="primary" loading={keyframePromptActionLoading} onClick={() => void confirmGenerateKeyframeWithPrompt()}>
                  生成
                </Button>
              </Space>
            </div>
          )}
          destroyOnClose
          width={900}
        >
          {(() => {
            const hasBasePrompt = keyframePromptPreviewDraft.trim().length > 0
            const renderStatusMeta = getKeyframeRenderStatusMeta(keyframePromptRenderState)
            const debugVisualStyle = readDebugContextText(keyframePromptDebugContext, 'visual_style')
            const debugStyle = readDebugContextText(keyframePromptDebugContext, 'style')
            const debugCharacterContext = readDebugContextText(keyframePromptDebugContext, 'character_context')
            const debugSceneContext = readDebugContextText(keyframePromptDebugContext, 'scene_context')
            const debugPropContext = readDebugContextText(keyframePromptDebugContext, 'prop_context')
            const debugCostumeContext = readDebugContextText(keyframePromptDebugContext, 'costume_context')
            const debugShotDescription = readDebugContextText(keyframePromptDebugContext, 'shot_description')
            const debugDialogSummary = readDebugContextText(keyframePromptDebugContext, 'dialog_summary')
            const debugPreviousShotTitle = readDebugContextText(keyframePromptDebugContext, 'previous_shot_title')
            const debugPreviousShotScriptExcerpt = readDebugContextText(keyframePromptDebugContext, 'previous_shot_script_excerpt')
            const debugPreviousShotEndState = readDebugContextText(keyframePromptDebugContext, 'previous_shot_end_state')
            const debugNextShotTitle = readDebugContextText(keyframePromptDebugContext, 'next_shot_title')
            const debugNextShotScriptExcerpt = readDebugContextText(keyframePromptDebugContext, 'next_shot_script_excerpt')
            const debugNextShotStartGoal = readDebugContextText(keyframePromptDebugContext, 'next_shot_start_goal')
            const debugContinuityGuidance = readDebugContextText(keyframePromptDebugContext, 'continuity_guidance')
            const debugCompositionAnchor = readDebugContextText(keyframePromptDebugContext, 'composition_anchor')
            const debugScreenDirectionGuidance = readDebugContextText(keyframePromptDebugContext, 'screen_direction_guidance')
            const debugFrameSpecificGuidance = readDebugContextText(keyframePromptDebugContext, 'frame_specific_guidance')
            const debugDirectorCommandSummary = readDebugContextText(keyframePromptDebugContext, 'director_command_summary')
            const debugActionBeatPhases = readDebugContextText(keyframePromptDebugContext, 'action_beat_phases')
            const debugSelectedActionBeatPhase = readDebugContextText(keyframePromptDebugContext, 'selected_action_beat_phase')
            const debugSelectedActionBeatText = readDebugContextText(keyframePromptDebugContext, 'selected_action_beat_text')
            const actionBeatPhaseTags = buildActionBeatPhaseTags(debugActionBeatPhases)
            const parsedDirectorCommandSummary = parseDirectorCommandSummary(debugDirectorCommandSummary)
            const keyframeGuidanceSummary = buildKeyframeGuidanceSummary([
              debugDirectorCommandSummary,
              debugFrameSpecificGuidance,
              debugContinuityGuidance,
              debugCompositionAnchor,
              debugScreenDirectionGuidance,
            ])
            const guidanceLevelSummary = buildGuidanceLevelSummary(parsedDirectorCommandSummary, keyframeGuidanceSummary)
            const debugUnifyStyle =
              typeof keyframePromptDebugContext?.unify_style === 'boolean'
                ? (keyframePromptDebugContext.unify_style ? '是' : '否')
                : readDebugContextText(keyframePromptDebugContext, 'unify_style')
            const hasPromptDebugContext = Boolean(
              debugVisualStyle ||
                debugStyle ||
                debugCharacterContext ||
                debugSceneContext ||
                debugPropContext ||
                debugCostumeContext ||
                debugShotDescription ||
                debugDialogSummary ||
                debugPreviousShotTitle ||
                debugPreviousShotScriptExcerpt ||
                debugPreviousShotEndState ||
                debugNextShotTitle ||
                debugNextShotScriptExcerpt ||
                debugNextShotStartGoal ||
                debugContinuityGuidance ||
                debugCompositionAnchor ||
                debugScreenDirectionGuidance ||
                debugFrameSpecificGuidance ||
                debugDirectorCommandSummary ||
                debugActionBeatPhases ||
                debugSelectedActionBeatText ||
                debugUnifyStyle,
            )
            const hasPromptQualityChecks = keyframePromptQualityChecks !== null
            return keyframePromptPreviewLoading ? (
              <div className="py-8 text-center">
                <Spin />
              </div>
            ) : (
              <div className="space-y-4">
                <div className="rounded-xl border border-slate-200 bg-white p-4">
                  <div className="mb-2 flex items-center justify-between">
                    <div>
                      <div className="text-sm font-medium text-slate-900">参考图映射</div>
                      <div className="mt-1 text-xs text-slate-500">
                        图片顺序会直接决定最终提示词中的图1、图2映射关系，并影响模型生成结果。
                      </div>
                    </div>
                    <Space size="small">
                      <Tag color="gold">顺序影响图1/图2</Tag>
                      <Button
                        size="small"
                        disabled={keyframePromptActionLoading || shotRenderPromptLoading || autoKeyframeRefFileIds.length === 0}
                        onClick={resetKeyframePromptRefFiles}
                      >
                        自动填充
                      </Button>
                      <Button
                        size="small"
                        danger
                        disabled={keyframePromptActionLoading || shotRenderPromptLoading || keyframePromptPreviewRefFileIds.length === 0}
                        onClick={clearKeyframePromptRefFiles}
                      >
                        清空
                      </Button>
                    </Space>
                  </div>
                  {keyframePromptPreviewRefFileIds.length === 0 ? (
                    <div className="text-xs text-gray-400">暂无关联图片</div>
                  ) : (
                    <div className="flex gap-3 overflow-x-auto pb-1">
                      <Image.PreviewGroup>
                        {keyframePromptPreviewRefFileIds.map((fid, index) => (
                          <div key={fid} className="w-[92px] shrink-0">
                            <Tooltip title={shotLinkedAssetNameByFileId.get(fid) ?? fid}>
                              <Image
                                width={72}
                                height={72}
                                style={{ objectFit: 'cover', borderRadius: 8, border: '1px solid #e2e8f0' }}
                                src={buildFileDownloadUrl(fid)}
                              />
                            </Tooltip>
                            <div className="mt-1">
                              <Tag color="blue">{`图${index + 1}`}</Tag>
                            </div>
                            <div className="truncate text-[11px] text-gray-700">
                              {shotLinkedAssetNameByFileId.get(fid) ?? fid}
                            </div>
                            <div className="mt-1 flex gap-1">
                              <Button
                                size="small"
                                disabled={index === 0 || keyframePromptActionLoading || shotRenderPromptLoading}
                                onClick={() => moveKeyframePromptRefFile(index, index - 1)}
                              >
                                左移
                              </Button>
                              <Button
                                size="small"
                                disabled={
                                  index === keyframePromptPreviewRefFileIds.length - 1 ||
                                  keyframePromptActionLoading ||
                                  shotRenderPromptLoading
                                }
                                onClick={() => moveKeyframePromptRefFile(index, index + 1)}
                              >
                                右移
                              </Button>
                              <Button
                                size="small"
                                danger
                                disabled={keyframePromptActionLoading || shotRenderPromptLoading}
                                onClick={() => removeKeyframePromptRefFile(fid)}
                              >
                                移除
                              </Button>
                            </div>
                          </div>
                        ))}
                      </Image.PreviewGroup>
                    </div>
                  )}
                  {allSelectableKeyframeRefFileIds.filter((fid) => !keyframePromptPreviewRefFileIds.includes(fid)).length > 0 ? (
                    <div className="mt-3 border-t border-slate-100 pt-3">
                      <div className="mb-2 text-xs text-slate-500">可选参考图（点击添加）</div>
                      <div className="flex gap-3 overflow-x-auto pb-1">
                        {allSelectableKeyframeRefFileIds
                          .filter((fid) => !keyframePromptPreviewRefFileIds.includes(fid))
                          .map((fid) => (
                            <div key={`candidate_${fid}`} className="w-[92px] shrink-0">
                              <Tooltip title={shotLinkedAssetNameByFileId.get(fid) ?? fid}>
                                <Image
                                  width={72}
                                  height={72}
                                  style={{ objectFit: 'cover', borderRadius: 8, border: '1px solid #e2e8f0' }}
                                  src={buildFileDownloadUrl(fid)}
                                />
                              </Tooltip>
                              <div className="mt-1 truncate text-[11px] text-gray-700">
                                {shotLinkedAssetNameByFileId.get(fid) ?? fid}
                              </div>
                              <Button
                                className="mt-1"
                                block
                                size="small"
                                disabled={keyframePromptActionLoading || shotRenderPromptLoading}
                                onClick={() => addKeyframePromptRefFile(fid)}
                              >
                                添加
                              </Button>
                            </div>
                          ))}
                      </div>
                    </div>
                  ) : null}
                </div>

              <div className="rounded-xl border border-slate-200 bg-white p-4">
                <div className="mb-2 flex items-center justify-between">
                  <div>
                    <div className="text-sm font-medium text-slate-900">基础提示词</div>
                    <div className="mt-1 text-xs text-slate-500">
                      描述画面内容本身，不包含图片映射说明。
                    </div>
                    <div className="mt-1 text-xs text-slate-500">
                      AI生成会继承当前项目风格，并优先参考已确认的角色、场景、道具和服装设定。
                    </div>
                  </div>
                  <Space size="small">
                    <Tag color={hasBasePrompt ? 'blue' : 'default'}>{hasBasePrompt ? '可编辑' : '未生成'}</Tag>
                    <Button
                      size="small"
                      type={hasBasePrompt ? 'default' : 'primary'}
                      loading={keyframePromptActionLoading}
                      onClick={() => void regenerateKeyframePrompt()}
                    >
                      AI生成
                    </Button>
                  </Space>
                </div>
                {!hasBasePrompt ? (
                  <div className="mb-3 rounded-lg border border-amber-200 bg-amber-50 px-3 py-2 text-sm text-amber-700">
                    当前还没有基础提示词。你可以先让 AI 生成一版，再按需修改；也可以直接手动输入。
                  </div>
                  ) : null}
                  {hasPromptQualityChecks ? (
                    <div
                      className={`mb-3 rounded-lg border px-3 py-2 text-xs ${
                        keyframePromptQualityChecks?.passed
                          ? 'border-emerald-200 bg-emerald-50 text-emerald-700'
                          : 'border-amber-200 bg-amber-50 text-amber-700'
                      }`}
                    >
                      <div className="flex items-center gap-2">
                        <Tag color={keyframePromptQualityChecks?.passed ? 'green' : 'gold'}>
                          {keyframePromptQualityChecks?.passed ? '质量校验通过' : '已触发自动修正'}
                        </Tag>
                        <span>
                          {keyframePromptQualityChecks?.passed
                            ? '本次 AI 生成已通过基础质量校验。'
                            : '本次 AI 生成触发过自动修正，系统已尽量清理不符合基础提示词要求的内容。'}
                        </span>
                      </div>
                    </div>
                  ) : null}
                  <Input.TextArea
                    rows={6}
                    value={keyframePromptPreviewDraft}
                    onChange={(e) => {
                      keyframePromptDraft.setBase((prev) => ({ ...prev, prompt: e.target.value }))
                      if (!e.target.value.trim()) {
                        keyframePromptDraft.resetDerived()
                      }
                    }}
                    placeholder="请输入基础提示词，例如人物动作、场景氛围、镜头视角等…"
                    disabled={keyframePromptActionLoading || shotRenderPromptLoading}
                  />
                  {keyframeGuidanceSummary.length > 0 || debugDirectorCommandSummary ? (
                    <div className="mt-3 rounded-lg border border-sky-200 bg-sky-50 px-3 py-3 text-xs text-sky-800">
                      <div className="flex items-start justify-between gap-3">
                        <div className="min-w-0">
                          <div className="font-medium">基础提示词生成依据</div>
                          <div className="mt-1 text-sky-700">
                            这些导演约束主要用于生成上游基础提示词，默认先看摘要；只有少量高优先级规则会再进入最终图片提示词。
                          </div>
                        </div>
                        <Button size="small" type="text" onClick={() => setKeyframeDirectiveCollapsed((prev) => !prev)}>
                          {keyframeDirectiveCollapsed ? '展开细节' : '收起细节'}
                        </Button>
                      </div>
                      <div className="mt-2 flex flex-wrap gap-2">
                        <Tag color="red">{`必须 ${guidanceLevelSummary.must}`}</Tag>
                        <Tag color="blue">{`优先 ${guidanceLevelSummary.prefer}`}</Tag>
                        <Tag>{`普通 ${guidanceLevelSummary.normal}`}</Tag>
                        {actionBeatPhaseTags.length > 0 ? (
                          <Tag color="purple">{`动作阶段 ${actionBeatPhaseTags.length}`}</Tag>
                        ) : null}
                      </div>
                      <div className="mt-2 flex flex-wrap gap-2">
                        {(keyframeDirectiveCollapsed
                          ? (
                            parsedDirectorCommandSummary.length > 0
                              ? parsedDirectorCommandSummary
                                  .slice(0, 2)
                                  .map((item) => `${item.level === 'must' ? '必须' : '优先'} · ${item.text}`)
                              : keyframeGuidanceSummary.slice(0, 2)
                          )
                          : keyframeGuidanceSummary
                        ).map((item) => (
                          <Tooltip key={item} title={item}>
                            <Tag color="blue" className="max-w-[240px] overflow-hidden">
                              <span className="inline-block max-w-[200px] truncate align-bottom">{item}</span>
                            </Tag>
                          </Tooltip>
                        ))}
                      </div>
                      {actionBeatPhaseTags.length > 0 ? (
                        <div className="mt-3 rounded-lg border border-slate-200 bg-white px-3 py-3 text-xs text-slate-700">
                          <div className="flex items-center justify-between gap-2">
                            <div className="font-medium text-slate-800">当前帧消费的动作阶段</div>
                            {debugSelectedActionBeatPhase && debugSelectedActionBeatText ? (
                              <Tag color="purple">
                                {`${debugSelectedActionBeatPhase} · ${debugSelectedActionBeatText}`}
                              </Tag>
                            ) : null}
                          </div>
                          <div className="mt-2 flex flex-wrap gap-2">
                            {actionBeatPhaseTags.map((item, index) => (
                              <Tooltip key={`${item.phaseLabel}:${index}:${item.text}`} title={`${item.phaseLabel} · ${item.text}`}>
                                <Tag
                                  color={
                                    item.phaseLabel === '触发'
                                      ? 'gold'
                                      : item.phaseLabel === '峰值'
                                        ? 'blue'
                                        : 'green'
                                  }
                                  className="max-w-[240px] overflow-hidden"
                                >
                                  <span className="inline-block max-w-[200px] truncate align-bottom">
                                    {item.phaseLabel} · {item.text}
                                  </span>
                                </Tag>
                              </Tooltip>
                            ))}
                          </div>
                        </div>
                      ) : null}
                      {!keyframeDirectiveCollapsed ? (
                        <div className="mt-3 grid gap-3 md:grid-cols-2">
                          {debugDirectorCommandSummary ? (
                            <div className="rounded-lg border border-indigo-200 bg-indigo-50 px-3 py-3 text-xs text-indigo-800">
                              <div className="font-medium">高优先级导演指令</div>
                              <div className="mt-2 flex flex-wrap gap-2">
                                {parsedDirectorCommandSummary.map((item, index) => (
                                  <Tooltip key={`${item.level}:${index}:${item.text}`} title={`${item.level === 'must' ? '必须' : '优先'} · ${item.text}`}>
                                    <Tag
                                      color={item.level === 'must' ? 'red' : 'blue'}
                                      className="max-w-[240px] overflow-hidden"
                                    >
                                      <span className="inline-block max-w-[200px] truncate align-bottom">
                                        {item.level === 'must' ? '必须' : '优先'} · {item.text}
                                      </span>
                                    </Tag>
                                  </Tooltip>
                                ))}
                              </div>
                            </div>
                          ) : null}
                          {keyframeGuidanceSummary.length > 0 ? (
                            <div className="rounded-lg border border-blue-200 bg-blue-50 px-3 py-3 text-xs text-blue-800">
                              <div className="font-medium">补充 Guidance</div>
                              <div className="mt-2 flex flex-wrap gap-2">
                                {keyframeGuidanceSummary.map((item) => (
                                  <Tooltip key={item} title={item}>
                                    <Tag color="blue" className="max-w-[220px] overflow-hidden">
                                      <span className="inline-block max-w-[180px] truncate align-bottom">{item}</span>
                                    </Tag>
                                  </Tooltip>
                                ))}
                              </div>
                            </div>
                          ) : null}
                        </div>
                      ) : null}
                    </div>
                  ) : null}
                  {hasPromptDebugContext ? (
                    <div className="mt-3 rounded-lg border border-slate-200 bg-slate-50 px-3 py-3 text-xs text-slate-600">
                      <div className="flex items-center justify-between gap-3">
                        <div className="font-medium text-slate-700">最近一次 AI 生成上下文</div>
                        <Space size="small">
                          <Tag color="default">调试信息</Tag>
                          <Button
                            size="small"
                            type="text"
                            onClick={() => setKeyframePromptDebugCollapsed((prev) => !prev)}
                          >
                            {keyframePromptDebugCollapsed ? '展开细节' : '收起细节'}
                          </Button>
                        </Space>
                      </div>
                      {keyframePromptDebugCollapsed ? (
                        <div className="mt-2 text-slate-500">
                          调试信息默认收起，展开后可查看最近一次 AI 生成使用的项目风格、镜头描述、连续性约束与实体上下文。
                        </div>
                      ) : (
                        <div className="mt-2 grid gap-2 md:grid-cols-2">
                          <div>
                            <div className="text-slate-500">项目风格</div>
                            <div className="mt-1 text-slate-700">
                              {[debugVisualStyle, debugStyle].filter(Boolean).join(' / ') || '无'}
                            </div>
                          </div>
                          <div>
                            <div className="text-slate-500">统一风格</div>
                            <div className="mt-1 text-slate-700">{debugUnifyStyle || '无'}</div>
                          </div>
                          {debugShotDescription ? (
                            <div className="md:col-span-2">
                              <div className="text-slate-500">镜头补充描述</div>
                              <div className="mt-1 whitespace-pre-wrap text-slate-700">{debugShotDescription}</div>
                            </div>
                          ) : null}
                          {debugDialogSummary ? (
                            <div className="md:col-span-2">
                              <div className="text-slate-500">对白摘要</div>
                              <div className="mt-1 whitespace-pre-wrap text-slate-700">{debugDialogSummary}</div>
                            </div>
                          ) : null}
                          {debugActionBeatPhases ? (
                            <div className="md:col-span-2">
                              <div className="text-slate-500">动作拍点阶段</div>
                              <div className="mt-1 flex flex-wrap gap-2">
                                {actionBeatPhaseTags.map((item, index) => (
                                  <Tag
                                    key={`debug-action-phase:${index}:${item.text}`}
                                    color={
                                      item.phaseLabel === '触发'
                                        ? 'gold'
                                        : item.phaseLabel === '峰值'
                                          ? 'blue'
                                          : 'green'
                                    }
                                  >
                                    {`${item.phaseLabel} · ${item.text}`}
                                  </Tag>
                                ))}
                              </div>
                              {debugSelectedActionBeatPhase || debugSelectedActionBeatText ? (
                                <div className="mt-2 text-slate-700">
                                  {`当前帧优先消费：${[debugSelectedActionBeatPhase, debugSelectedActionBeatText].filter(Boolean).join(' · ')}`}
                                </div>
                              ) : null}
                            </div>
                          ) : null}
                          {debugPreviousShotTitle || debugPreviousShotScriptExcerpt || debugPreviousShotEndState ? (
                            <div className="md:col-span-2 rounded-lg border border-slate-200 bg-white px-3 py-3">
                              <div className="text-slate-500">上一镜头承接</div>
                              <div className="mt-1 space-y-1 text-slate-700">
                                {debugPreviousShotTitle ? <div>标题：{debugPreviousShotTitle}</div> : null}
                                {debugPreviousShotScriptExcerpt ? (
                                  <div className="whitespace-pre-wrap">摘录：{debugPreviousShotScriptExcerpt}</div>
                                ) : null}
                                {debugPreviousShotEndState ? (
                                  <div className="whitespace-pre-wrap">结尾状态：{debugPreviousShotEndState}</div>
                                ) : null}
                              </div>
                            </div>
                          ) : null}
                          {debugNextShotTitle || debugNextShotScriptExcerpt || debugNextShotStartGoal ? (
                            <div className="md:col-span-2 rounded-lg border border-slate-200 bg-white px-3 py-3">
                              <div className="text-slate-500">下一镜头衔接</div>
                              <div className="mt-1 space-y-1 text-slate-700">
                                {debugNextShotTitle ? <div>标题：{debugNextShotTitle}</div> : null}
                                {debugNextShotScriptExcerpt ? (
                                  <div className="whitespace-pre-wrap">摘录：{debugNextShotScriptExcerpt}</div>
                                ) : null}
                                {debugNextShotStartGoal ? (
                                  <div className="whitespace-pre-wrap">起始目标：{debugNextShotStartGoal}</div>
                                ) : null}
                              </div>
                            </div>
                          ) : null}
                          {debugContinuityGuidance ? (
                            <div className="md:col-span-2">
                              <div className="text-slate-500">连续性建议</div>
                              <div className="mt-1 whitespace-pre-wrap text-slate-700">{debugContinuityGuidance}</div>
                            </div>
                          ) : null}
                          {debugCompositionAnchor ? (
                            <div className="md:col-span-2">
                              <div className="text-slate-500">构图与空间锚点</div>
                              <div className="mt-1 whitespace-pre-wrap text-slate-700">{debugCompositionAnchor}</div>
                            </div>
                          ) : null}
                          {debugScreenDirectionGuidance ? (
                            <div className="md:col-span-2">
                              <div className="text-slate-500">朝向与视线建议</div>
                              <div className="mt-1 whitespace-pre-wrap text-slate-700">{debugScreenDirectionGuidance}</div>
                            </div>
                          ) : null}
                          {debugFrameSpecificGuidance ? (
                            <div className="md:col-span-2">
                              <div className="text-slate-500">当前帧专项建议</div>
                              <div className="mt-1 whitespace-pre-wrap text-slate-700">{debugFrameSpecificGuidance}</div>
                            </div>
                          ) : null}
                          {debugCharacterContext ? (
                            <div className="md:col-span-2">
                              <div className="text-slate-500">角色上下文</div>
                              <div className="mt-1 whitespace-pre-wrap text-slate-700">{debugCharacterContext}</div>
                            </div>
                          ) : null}
                          {debugSceneContext ? (
                            <div className="md:col-span-2">
                              <div className="text-slate-500">场景上下文</div>
                              <div className="mt-1 whitespace-pre-wrap text-slate-700">{debugSceneContext}</div>
                            </div>
                          ) : null}
                          {debugPropContext ? (
                            <div className="md:col-span-2">
                              <div className="text-slate-500">道具上下文</div>
                              <div className="mt-1 whitespace-pre-wrap text-slate-700">{debugPropContext}</div>
                            </div>
                          ) : null}
                          {debugCostumeContext ? (
                            <div className="md:col-span-2">
                              <div className="text-slate-500">服装上下文</div>
                              <div className="mt-1 whitespace-pre-wrap text-slate-700">{debugCostumeContext}</div>
                            </div>
                          ) : null}
                        </div>
                      )}
                    </div>
                  ) : null}
                </div>

                <div className="rounded-xl border border-slate-200 bg-slate-50 p-4">
                  <div className="mb-3 flex items-center justify-between">
                    <div>
                      <div className="text-sm font-medium text-slate-900">最终生成提示词</div>
                      <div className="mt-1 text-xs text-slate-500">
                        系统会根据当前基础提示词和参考图顺序自动生成这一版内容，提交给模型时将使用这里的结果。
                      </div>
                    </div>
                    <Space size="small">
                      <Tag color="geekblue">系统生成</Tag>
                      <Tag>只读</Tag>
                      <Button
                        size="small"
                        onClick={() =>
                          void renderShotPromptToTextarea({
                            frameType: keyframePromptPreviewFrameType,
                            prompt: keyframePromptPreviewDraft,
                            refFileIds:
                              keyframePromptPreviewRefFileIds.length > 0
                                ? keyframePromptPreviewRefFileIds
                                : autoKeyframeRefFileIds,
                          })
                        }
                        disabled={!hasBasePrompt}
                        loading={shotRenderPromptLoading}
                      >
                        重新同步
                      </Button>
                      <Button
                        size="small"
                        onClick={async () => {
                          try {
                            await navigator.clipboard.writeText(keyframePromptRenderedDraft || '')
                            message.success('最终提示词已复制')
                          } catch {
                            message.error('复制失败')
                          }
                        }}
                        disabled={!keyframePromptRenderedDraft.trim()}
                      >
                        复制
                      </Button>
                    </Space>
                  </div>
                  <div
                    className={`mb-3 rounded-lg border px-3 py-2 text-sm ${
                      renderStatusMeta.color === 'green'
                        ? 'border-green-200 bg-green-50 text-green-700'
                        : renderStatusMeta.color === 'blue'
                          ? 'border-blue-200 bg-blue-50 text-blue-700'
                          : renderStatusMeta.color === 'red'
                            ? 'border-red-200 bg-red-50 text-red-700'
                            : renderStatusMeta.color === 'gold'
                              ? 'border-amber-200 bg-amber-50 text-amber-700'
                              : 'border-slate-200 bg-white text-slate-600'
                    }`}
                  >
                    <div className="flex items-center gap-2">
                      <Tag color={renderStatusMeta.color}>{renderStatusMeta.label}</Tag>
                      <span>{renderStatusMeta.description}</span>
                    </div>
                  </div>
                  {keyframePromptRenderMappings.length > 0 ? (
                    <div className="mb-2 flex flex-wrap gap-2">
                      {keyframePromptRenderMappings.map((mapping) => (
                        <Tag key={`${mapping.token}:${mapping.file_id}`}>{`${mapping.token} = ${mapping.name}`}</Tag>
                      ))}
                    </div>
                  ) : null}
                  {keyframePromptSelectedGuidance.length > 0 || keyframePromptDroppedGuidance.length > 0 ? (
                    <div className="mb-3 rounded-lg border border-slate-200 bg-white px-3 py-3 text-xs text-slate-700">
                      <div className="flex items-start justify-between gap-3">
                        <div>
                          <div className="font-medium text-slate-900">最终图片提示词收敛结果</div>
                          <div className="mt-1 text-slate-500">
                            系统会从上游导演约束里挑出最关键的少量规则，补进最终图片提示词。
                          </div>
                        </div>
                        <Space size="small" wrap>
                          <Tag color="green">{`保留 ${keyframePromptSelectedGuidance.length}`}</Tag>
                          <Tag color="gold">{`压缩 ${keyframePromptDroppedGuidance.length}`}</Tag>
                          {(keyframePromptSelectedGuidance.length > 2 || keyframePromptDroppedGuidance.length > 0) ? (
                            <Button
                              size="small"
                              type="text"
                              onClick={() => setKeyframePromptDecisionCollapsed((prev) => !prev)}
                            >
                              {keyframePromptDecisionCollapsed ? '查看取舍' : '收起取舍'}
                            </Button>
                          ) : null}
                        </Space>
                      </div>
                      <div className="mt-3 grid gap-3 md:grid-cols-2">
                        <div className="rounded-lg border border-emerald-200 bg-emerald-50 px-3 py-3 text-xs text-emerald-800">
                          <div className="font-medium">实际保留的 Guidance</div>
                          {keyframePromptSelectedGuidance.length > 0 ? (
                            <div className="mt-2 flex flex-wrap gap-2">
                              {keyframePromptVisibleSelectedGuidanceDetails.map((item) => (
                                <Tooltip
                                  key={`selected:${item.text}`}
                                  title={(
                                    <div className="max-w-[320px] text-xs leading-5">
                                      {item.reasonTag ? (
                                        <Tag color="green" className="mb-1">
                                          {item.reasonTag}
                                        </Tag>
                                      ) : null}
                                      <div>{item.text}</div>
                                      {item.reason ? <div className="mt-1 text-slate-500">{item.reason}</div> : null}
                                    </div>
                                  )}
                                >
                                  <Tag color="green" className="max-w-[240px] overflow-hidden">
                                    <span className="inline-block max-w-[200px] truncate align-bottom">{item.text}</span>
                                  </Tag>
                                </Tooltip>
                              ))}
                              {keyframePromptDecisionCollapsed && keyframePromptSelectedGuidanceDetails.length > 2 ? (
                                <Tag>{`+${keyframePromptSelectedGuidanceDetails.length - 2} 条`}</Tag>
                              ) : null}
                            </div>
                          ) : (
                            <div className="mt-2 text-emerald-700">当前没有额外 guidance 被保留。</div>
                          )}
                        </div>
                        <div className="rounded-lg border border-amber-200 bg-amber-50 px-3 py-3 text-xs text-amber-800">
                          <div className="font-medium">已压缩的 Guidance</div>
                          {keyframePromptDroppedGuidance.length > 0 ? (
                            keyframePromptDecisionCollapsed ? (
                              <div className="mt-2 text-amber-700">
                                当前有 {keyframePromptDroppedGuidance.length} 条 guidance 被压缩，展开后可查看具体取舍原因。
                              </div>
                            ) : (
                              <div className="mt-2 flex flex-wrap gap-2">
                                {keyframePromptVisibleDroppedGuidanceDetails.map((item) => (
                                  <Tooltip
                                    key={`dropped:${item.text}`}
                                    title={(
                                      <div className="max-w-[320px] text-xs leading-5">
                                        {item.reasonTag ? (
                                          <Tag color="gold" className="mb-1">
                                            {item.reasonTag}
                                          </Tag>
                                        ) : null}
                                        <div>{item.text}</div>
                                        {item.reason ? <div className="mt-1 text-slate-500">{item.reason}</div> : null}
                                      </div>
                                    )}
                                  >
                                    <Tag color="gold" className="max-w-[240px] overflow-hidden">
                                      <span className="inline-block max-w-[200px] truncate align-bottom">{item.text}</span>
                                    </Tag>
                                  </Tooltip>
                                ))}
                              </div>
                            )
                          ) : (
                            <div className="mt-2 text-amber-700">当前没有 guidance 被压缩。</div>
                          )}
                        </div>
                      </div>
                    </div>
                  ) : null}
                  {hasBasePrompt ? (
                    <div className="rounded-lg border border-slate-200 bg-white px-3 py-3 text-sm leading-6 text-slate-800 whitespace-pre-wrap min-h-[220px]">
                      {keyframePromptRenderedDraft || '系统正在根据当前内容准备最终提示词…'}
                    </div>
                  ) : (
                    <div className="rounded-lg border border-dashed border-slate-300 bg-white px-4 py-6 text-sm text-slate-500">
                      <div className="font-medium text-slate-700">等待基础提示词</div>
                      <div className="mt-2">
                        基础提示词准备完成后，系统会自动：
                      </div>
                      <div className="mt-2 space-y-1 text-slate-500">
                        <div>1. 根据当前参考图顺序生成图1 / 图2映射</div>
                        <div>2. 补充“## 图片内容说明”</div>
                        <div>3. 生成最终提交给模型的提示词</div>
                      </div>
                    </div>
                  )}
                </div>
              </div>
            )
          })()}
        </Modal>

        <Modal
          title="视频生成提示词预览"
          open={videoPromptPreviewOpen}
          onCancel={() => {
            if (videoPromptPreviewSubmitting) return
            setVideoPromptPreviewOpen(false)
          }}
          okText="生成"
          cancelText="取消"
          onOk={() => void submitVideoGeneration()}
          confirmLoading={videoPromptPreviewSubmitting}
          width={900}
          destroyOnClose
        >
          {videoPromptPreviewLoading ? (
            <div className="py-8 text-center">
              <Spin />
            </div>
          ) : (
            <div className="space-y-3">
              <div className="rounded-lg border border-slate-200 bg-slate-50 px-3 py-3 text-xs text-slate-600">
                <div className="flex items-start justify-between gap-3">
                  <div className="min-w-0">
                    <div className="font-medium text-slate-700">镜头连续性上下文</div>
                    <div className="mt-1 text-[11px] leading-5 text-slate-500">
                      这些上下文会参与视频模板渲染和最终提示词补强，默认先展示摘要，需要时再展开细节。
                    </div>
                  </div>
                  <Button
                    type="link"
                    size="small"
                    className="px-0"
                    onClick={() => setVideoPromptContextCollapsed((prev) => !prev)}
                  >
                    {videoPromptContextCollapsed ? '展开细节' : '收起细节'}
                  </Button>
                </div>
                <div className="mt-2 flex flex-wrap gap-2">
                  <Tag color="blue">{`动作节拍 ${videoActionBeats.length}`}</Tag>
                  {videoPromptPreviewPack?.previous_shot_summary ? (
                    <Tag color="purple">上一镜头</Tag>
                  ) : null}
                  {videoPromptPreviewPack?.next_shot_goal ? (
                    <Tag color="cyan">下一镜头</Tag>
                  ) : null}
                  {videoPromptPreviewPack?.continuity_guidance ? (
                    <Tag color="gold">连续性</Tag>
                  ) : null}
                </div>
                <div className="mt-3 space-y-3">
                  <div>
                    <div className="text-slate-500">动作节拍</div>
                    {videoVisibleActionBeats.length > 0 ? (
                      <div className="mt-1 flex flex-wrap gap-2">
                        {videoVisibleActionBeats.map((item, index) => (
                          <Tag
                            key={`${index}:${item.phase ?? 'raw'}:${item.text}`}
                            color={
                              item.phase === 'trigger'
                                ? 'gold'
                                : item.phase === 'peak'
                                  ? 'blue'
                                  : item.phase === 'aftermath'
                                    ? 'green'
                                    : 'default'
                            }
                          >
                            {item.phase
                              ? `${item.phase === 'trigger' ? '触发' : item.phase === 'peak' ? '峰值' : '收束'} · ${item.text}`
                              : item.text}
                          </Tag>
                        ))}
                        {videoPromptContextCollapsed && hiddenVideoActionBeatCount > 0 ? (
                          <Tag>{`+${hiddenVideoActionBeatCount}`}</Tag>
                        ) : null}
                      </div>
                    ) : (
                      <div className="mt-1 text-gray-400">暂无动作节拍</div>
                    )}
                  </div>
                  {!videoPromptContextCollapsed ? (
                    <>
                      <div>
                        <div className="text-slate-500">上一镜头摘要</div>
                        <div className="mt-1 whitespace-pre-wrap text-slate-700">
                          {videoPromptPreviewPack?.previous_shot_summary || '无'}
                        </div>
                      </div>
                      <div>
                        <div className="text-slate-500">下一镜头目标</div>
                        <div className="mt-1 whitespace-pre-wrap text-slate-700">
                          {videoPromptPreviewPack?.next_shot_goal || '无'}
                        </div>
                      </div>
                      <div>
                        <div className="text-slate-500">连续性建议</div>
                        <div className="mt-1 whitespace-pre-wrap text-slate-700">
                          {videoPromptPreviewPack?.continuity_guidance || '无'}
                        </div>
                      </div>
                      <div>
                        <div className="text-slate-500">构图与空间锚点</div>
                        <div className="mt-1 whitespace-pre-wrap text-slate-700">
                          {videoPromptPreviewPack?.composition_anchor || '无'}
                        </div>
                      </div>
                      <div>
                        <div className="text-slate-500">朝向与视线建议</div>
                        <div className="mt-1 whitespace-pre-wrap text-slate-700">
                          {videoPromptPreviewPack?.screen_direction_guidance || '无'}
                        </div>
                      </div>
                    </>
                  ) : null}
                </div>
              </div>
              <div>
                <div className="text-xs text-gray-500 mb-2">关联图片（参考图）</div>
                {videoPromptPreviewImages.length === 0 ? (
                  <div className="text-xs text-gray-400">暂无关联图片</div>
                ) : (
                  <div className="flex gap-2 overflow-x-auto pb-1">
                    <Image.PreviewGroup>
                      {videoPromptPreviewImages.map((fid) => (
                        <Image
                          key={fid}
                          width={72}
                          height={72}
                          style={{ objectFit: 'cover', borderRadius: 8 }}
                          src={buildFileDownloadUrl(fid)}
                        />
                      ))}
                    </Image.PreviewGroup>
                  </div>
                )}
              </div>
              <div>
                <div className="text-xs text-gray-500 mb-2">提示词（可编辑）</div>
                <Input.TextArea
                  rows={10}
                  value={videoPromptPreviewDraft}
                  onChange={(e) => videoPromptDraft.setBase({ prompt: e.target.value })}
                  placeholder="请输入视频提示词…"
                  disabled={videoPromptPreviewSubmitting}
                />
              </div>
            </div>
          )}
        </Modal>
      </div>
    </div>
  )
}
