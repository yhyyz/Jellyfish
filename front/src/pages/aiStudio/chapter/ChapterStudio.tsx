import React, { useCallback, useEffect, useMemo, useRef, useState } from 'react'
import {
  Badge,
  Button,
  Card,
  Divider,
  Dropdown,
  Input,
  Layout,
  Modal,
  Radio,
  Segmented,
  Select,
  Slider,
  Spin,
  Space,
  Switch,
  Tag,
  Tooltip,
  message,
} from 'antd'
import {
  AppstoreOutlined,
  ArrowLeftOutlined,
  CaretLeftOutlined,
  CaretRightOutlined,
  CheckCircleOutlined,
  ClockCircleOutlined,
  DeleteOutlined,
  DoubleLeftOutlined,
  DoubleRightOutlined,
  DownloadOutlined,
  EyeInvisibleOutlined,
  EyeOutlined,
  FileTextOutlined,
  LinkOutlined,
  MergeCellsOutlined,
  PauseCircleOutlined,
  PlayCircleOutlined,
  ScissorOutlined,
  SettingOutlined,
  SoundOutlined,
  StopOutlined,
  ThunderboltOutlined,
  UndoOutlined,
  VideoCameraAddOutlined,
  VideoCameraOutlined,
} from '@ant-design/icons'
import { useLocation, useParams, Link } from 'react-router-dom'
import {
  LlmService,
  StudioChaptersService,
  StudioFilesService,
  StudioImageTasksService,
  StudioProjectsService,
  StudioShotCharacterLinksService,
  StudioShotDetailsService,
  StudioShotDialogLinesService,
  StudioShotFrameImagesService,
  StudioShotLinksService,
  StudioShotsService,
} from '../../../services/generated'
import type {
  ImageGenerationOptionsRead,
  ProjectActorLinkRead,
  ProjectCostumeLinkRead,
  ShotDetailRead,
  ShotDialogLineRead,
  ShotExtractedCandidateRead,
  ShotExtractedDialogueCandidateRead,
  ShotFrameImageRead,
  ShotCharacterLinkRead,
  ProjectPropLinkRead,
  ProjectSceneLinkRead,
  ShotStatus,
  ShotRuntimeSummaryRead,
  ShotVideoReadinessRead,
} from '../../../services/generated'
import { buildFileDownloadUrl } from '../assets/utils'
import type { Chapter } from '../../../mocks/data'
import { useTaskPageContext } from '../components/taskPageContext'
import { ChapterStudioBatchToolbar } from './components/ChapterStudioBatchToolbar'
import { useProjectStyleOptions } from '../project/useProjectStyleOptions'
import { Inspector } from './Inspector'
import {
  LAYOUT_STORAGE_KEY,
  FRAME_FILE_TAG_ADOPT,
  FRAME_FILE_TAG_ABANDON,
  CAMERA_MOVEMENT_OPTIONS,
} from './constants'
import type {
  KeyframeResolutionProfile,
  LayoutPrefs,
  ShotFilter,
  ShotRuntimeState,
  StudioShot,
} from './types'
import {
  clamp,
  isTypingTarget,
  normalizeFrameExclusiveTags,
  reorder,
  toUIChapter,
} from './utils'
import './chapterStudio.separation.css'

const { Sider, Content } = Layout

function useLocalStoragePrefs() {
  const [prefs, setPrefs] = useState<LayoutPrefs>(() => {
    try {
      const raw = window.localStorage.getItem(LAYOUT_STORAGE_KEY)
      if (!raw) {
        return {
          leftWidth: 280,
          rightWidth: 420,
          inspectorOpen: false,
          inspectorMode: 'push',
          autoOpenInspector: true,
          timelineCollapsed: false,
        }
      }
      const parsed = JSON.parse(raw) as Partial<LayoutPrefs>
      return {
        leftWidth: typeof parsed.leftWidth === 'number' ? parsed.leftWidth : 280,
        rightWidth: typeof parsed.rightWidth === 'number' ? parsed.rightWidth : 420,
        inspectorOpen: typeof parsed.inspectorOpen === 'boolean' ? parsed.inspectorOpen : false,
        inspectorMode: parsed.inspectorMode === 'overlay' ? 'overlay' : 'push',
        autoOpenInspector: typeof parsed.autoOpenInspector === 'boolean' ? parsed.autoOpenInspector : true,
        timelineCollapsed: typeof parsed.timelineCollapsed === 'boolean' ? parsed.timelineCollapsed : false,
      }
    } catch {
      return {
        leftWidth: 280,
        rightWidth: 420,
        inspectorOpen: false,
        inspectorMode: 'push',
        autoOpenInspector: true,
        timelineCollapsed: false,
      }
    }
  })

  useEffect(() => {
    window.localStorage.setItem(LAYOUT_STORAGE_KEY, JSON.stringify(prefs))
  }, [prefs])

  return [prefs, setPrefs] as const
}

const ChapterStudio: React.FC = () => {
  const { projectId, chapterId } = useParams<{
    projectId?: string
    chapterId?: string
  }>()
  const location = useLocation()
  const [chapter, setChapter] = useState<Chapter | null>(null)
  const [projectVisualStyle, setProjectVisualStyle] = useState<'现实' | '动漫'>('现实')
  const [projectStyle, setProjectStyle] = useState<string>('真人都市')
  const [projectDefaultVideoRatio, setProjectDefaultVideoRatio] = useState<string>('')
  const { videoRatioOptions, defaultVideoRatio: capabilityDefaultVideoRatio } = useProjectStyleOptions()
  const [imageGenerationOptions, setImageGenerationOptions] = useState<ImageGenerationOptionsRead | null>(null)
  const [shots, setShots] = useState<StudioShot[]>([])
  const [shotRuntimeMap, setShotRuntimeMap] = useState<Record<string, ShotRuntimeState>>({})
  const [selectedShotId, setSelectedShotId] = useState<string | null>(null)
  const [selectedShotIds, setSelectedShotIds] = useState<string[]>([])
  const locationSelectionAppliedRef = useRef(false)
  const lastSelectedIndexRef = useRef<number>(-1)
  const [shotDetail, setShotDetail] = useState<ShotDetailRead | null>(null)
  const [dialogLines, setDialogLines] = useState<ShotDialogLineRead[]>([])
  const [frameImages, setFrameImages] = useState<ShotFrameImageRead[]>([])
  const [sceneLinks, setSceneLinks] = useState<ProjectSceneLinkRead[]>([])
  const [actorImageLinks, setActorImageLinks] = useState<ProjectActorLinkRead[]>([])
  const [propLinks, setPropLinks] = useState<ProjectPropLinkRead[]>([])
  const [costumeLinks, setCostumeLinks] = useState<ProjectCostumeLinkRead[]>([])
  const [shotCharacterLinks, setShotCharacterLinks] = useState<ShotCharacterLinkRead[]>([])
  const [shotCandidateItems, setShotCandidateItems] = useState<ShotExtractedCandidateRead[]>([])
  const [shotDialogueCandidateItems, setShotDialogueCandidateItems] = useState<ShotExtractedDialogueCandidateRead[]>([])
  const shotCandidatesRequestSeqRef = useRef(0)
  const [shotDurations, setShotDurations] = useState<Record<string, number>>({})
  const [loadingShots, setLoadingShots] = useState(true)
  const [loadingDetail, setLoadingDetail] = useState(false)
  const [prefs, setPrefs] = useLocalStoragePrefs()
  const [generating, setGenerating] = useState(false)
  const [batchSkipExtractionUpdating, setBatchSkipExtractionUpdating] = useState(false)
  const [batchVideoReadinessOpen, setBatchVideoReadinessOpen] = useState(false)
  const [batchVideoReadinessLoading, setBatchVideoReadinessLoading] = useState(false)
  const [batchVideoReadinessItems, setBatchVideoReadinessItems] = useState<
    Array<{ shot: StudioShot; readiness: ShotVideoReadinessRead | null; error?: string }>
  >([])
  const [saving, setSaving] = useState(false)
  const saveTimerRef = useRef<number | null>(null)
  const cameraPatchSeqRef = useRef(0)
  const [cameraUpdating, setCameraUpdating] = useState(false)
  const [promptAssetsUpdating, setPromptAssetsUpdating] = useState(false)

  const [frameTab, setFrameTab] = useState<'head' | 'keyframes' | 'tail' | 'compare'>('keyframes')
  const [keyframeResolutionProfile, setKeyframeResolutionProfile] = useState<KeyframeResolutionProfile>('standard')
  const [frameFileTagsMap, setFrameFileTagsMap] = useState<Record<string, string[]>>({})
  const [frameFileTagsLoading, setFrameFileTagsLoading] = useState(false)
  const [playbackRate, setPlaybackRate] = useState(1)
  const [loopCurrent, setLoopCurrent] = useState(false)
  const videoRef = useRef<HTMLVideoElement | null>(null)
  const [previewVideoFileId, setPreviewVideoFileId] = useState<string | null>(null)
  const [isPlaying, setIsPlaying] = useState(false)
  const [videoDuration, setVideoDuration] = useState(0)
  const [videoTime, setVideoTime] = useState(0)

  const [filter, setFilter] = useState<ShotFilter>('all')
  const [editingTitleId, setEditingTitleId] = useState<string | null>(null)
  const [editingTitleValue, setEditingTitleValue] = useState('')
  const [draggingShotId, setDraggingShotId] = useState<string | null>(null)
  const [dragOverShotId, setDragOverShotId] = useState<string | null>(null)
  const [isResizing, setIsResizing] = useState(false)

  useEffect(() => {
    let active = true
    void (async () => {
      try {
        const res = await LlmService.getImageGenerationOptionsApiV1LlmImageGenerationOptionsGet()
        if (!active) return
        setImageGenerationOptions(res.data ?? null)
      } catch {
        if (!active) return
        setImageGenerationOptions(null)
      }
    })()
    return () => {
      active = false
    }
  }, [])

  const containerRef = useRef<HTMLDivElement | null>(null)
  const dragStateRef = useRef<null | { type: 'left' | 'right'; startX: number; startLeft: number; startRight: number }>(null)
  const resizeRafRef = useRef<number | null>(null)
  const pendingResizeRef = useRef<null | { leftWidth?: number; rightWidth?: number }>(null)
  const showPreviewMinimizeButton = false
  const showPreviewFrameSegmented = false
  const showChapterTimeline = false
  const resolveShotVideoRatio = useCallback(
    (detail?: ShotDetailRead | null) => {
      const shotRatio = String(detail?.override_video_ratio ?? '').trim()
      const projectRatio = String(projectDefaultVideoRatio ?? '').trim()
      const fallbackRatio = String(capabilityDefaultVideoRatio ?? '').trim()
      return shotRatio || projectRatio || fallbackRatio
    },
    [capabilityDefaultVideoRatio, projectDefaultVideoRatio],
  )

  const hiddenKey = useMemo(() => (chapterId ? `jellyfish_hidden_shots_${chapterId}` : null), [chapterId])
  const hiddenIds = useMemo(() => {
    if (!hiddenKey) return new Set<string>()
    try {
      const raw = window.localStorage.getItem(hiddenKey)
      const arr = raw ? (JSON.parse(raw) as unknown) : []
      return new Set(Array.isArray(arr) ? (arr.filter((x) => typeof x === 'string') as string[]) : [])
    } catch {
      return new Set<string>()
    }
  }, [hiddenKey])

  const saveHiddenIds = (next: Set<string>) => {
    if (!hiddenKey) return
    try {
      window.localStorage.setItem(hiddenKey, JSON.stringify(Array.from(next)))
    } catch {
      // ignore
    }
  }

  const toggleHiddenShots = (ids: string[]) => {
    if (!hiddenKey) return
    const next = new Set(hiddenIds)
    ids.forEach((id) => {
      if (next.has(id)) next.delete(id)
      else next.add(id)
    })
    saveHiddenIds(next)
    setShots((prev) => prev.map((s) => (ids.includes(s.id) ? { ...s, hidden: next.has(s.id) } : s)))
  }

  const loadShots = async () => {
    if (!chapterId) return
    setLoadingShots(true)
    try {
      const [res, runtimeRes] = await Promise.all([
        StudioShotsService.listShotsApiV1StudioShotsGet({
          chapterId,
          page: 1,
          pageSize: 100,
          order: 'index',
          isDesc: false,
        }),
        StudioShotsService.listShotRuntimeSummaryApiV1StudioShotsRuntimeSummaryGet({
          chapterId,
        }),
      ])
      const arr = res.data?.items ?? []
      const runtimeItems: ShotRuntimeSummaryRead[] = runtimeRes.data ?? []
      setShotRuntimeMap(
        Object.fromEntries(
          runtimeItems.map((item) => [
            item.shot_id,
            {
              has_active_tasks: item.has_active_tasks,
              has_active_video_tasks: item.has_active_video_tasks,
              has_active_prompt_tasks: item.has_active_prompt_tasks,
              has_active_frame_tasks: item.has_active_frame_tasks,
              active_task_count: item.active_task_count,
            },
          ]),
        ),
      )
      // 给分镜补充一些“工作台态”的展示字段（后续可由后端返回）
      const enriched: StudioShot[] = arr
        .slice()
        .sort((a, b) => a.index - b.index)
        .map((s, idx) => ({
          ...s,
          hidden: hiddenIds.has(s.id),
          hasProblem: idx === 4,
          hasSpeech: false,
          hasMusic: idx % 3 !== 0,
        }))

      setShots(enriched)

      const locationState = location.state as { focusShotId?: string; selectedShotIds?: string[] } | null
      if (!locationSelectionAppliedRef.current && locationState) {
        const nextSelectedIds = (locationState.selectedShotIds ?? []).filter((id) =>
          enriched.some((shot) => shot.id === id),
        )
        const focusShotId =
          locationState.focusShotId && enriched.some((shot) => shot.id === locationState.focusShotId)
            ? locationState.focusShotId
            : nextSelectedIds[0] ?? null

        if (nextSelectedIds.length > 0) {
          setSelectedShotIds(nextSelectedIds)
        }
        if (focusShotId) {
          setSelectedShotId(focusShotId)
        }
        locationSelectionAppliedRef.current = true
        return
      }

      const selectedExists = selectedShotId ? enriched.some((s) => s.id === selectedShotId) : false
      if (!selectedShotId || !selectedExists) {
        const firstUnfinished = enriched.find((s) => !s.hidden && s.status !== 'ready')
        const firstVisible = enriched.find((s) => !s.hidden)
        setSelectedShotId((firstUnfinished ?? firstVisible ?? enriched[0])?.id ?? null)
      }
    } catch {
      message.error('加载分镜失败')
    } finally {
      setLoadingShots(false)
    }
  }

  const patchShotInList = (shotId: string, patch: Partial<StudioShot>) => {
    setShots((prev) => prev.map((s) => (s.id === shotId ? { ...s, ...patch } : s)))
  }

  const updateShotTitleInOps = async (shotId: string, title: string) => {
    try {
      const res = await StudioShotsService.updateShotApiV1StudioShotsShotIdPatch({
        shotId,
        requestBody: { title },
      } as any)
      if (res.data) patchShotInList(shotId, res.data as any)
      message.success('标题已保存')
    } catch {
      message.error('保存标题失败')
    }
  }

  const updateShotScriptExcerptInOps = async (shotId: string, script_excerpt: string) => {
    try {
      const res = await StudioShotsService.updateShotApiV1StudioShotsShotIdPatch({
        shotId,
        requestBody: { script_excerpt },
      } as any)
      if (res.data) patchShotInList(shotId, res.data as any)
      message.success('备注已保存')
    } catch {
      message.error('保存备注失败')
    }
  }

  const deleteShotFromOps = async (shotId: string) => {
    try {
      await StudioShotsService.deleteShotApiV1StudioShotsShotIdDelete({ shotId })
      await loadShots()
      message.success('已删除')
    } catch {
      message.error('删除失败')
    }
  }

  const loadChapter = async () => {
    if (!chapterId) return
    try {
      const [chapterRes, projectRes] = await Promise.all([
        StudioChaptersService.getChapterApiV1StudioChaptersChapterIdGet({ chapterId }),
        projectId ? StudioProjectsService.getProjectApiV1StudioProjectsProjectIdGet({ projectId }) : Promise.resolve(null),
      ])
      const data = chapterRes.data
      if (!data) {
        setChapter(null)
        return
      }
      setChapter(toUIChapter(data))
      const nextVisualStyle = projectRes?.data?.visual_style
      const nextStyle = projectRes?.data?.style
      const nextDefaultRatio = typeof projectRes?.data?.default_video_ratio === 'string' ? projectRes.data.default_video_ratio : ''
      if (nextVisualStyle === '现实' || nextVisualStyle === '动漫') {
        setProjectVisualStyle(nextVisualStyle)
      }
      if (typeof nextStyle === 'string' && nextStyle.trim()) {
        setProjectStyle(nextStyle)
      }
      setProjectDefaultVideoRatio(nextDefaultRatio)
    } catch {
      // 章节信息仅用于标题展示，失败不阻断工作台
      setChapter(null)
      setProjectDefaultVideoRatio('')
    }
  }

  useEffect(() => {
    void loadShots()
    void loadChapter()
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [chapterId, location.state, projectId])

  useEffect(() => {
    if (!selectedShotId) {
      shotCandidatesRequestSeqRef.current += 1
      setShotDetail(null)
      setDialogLines([])
      setFrameImages([])
      setSceneLinks([])
      setActorImageLinks([])
      setPropLinks([])
      setCostumeLinks([])
      setShotCharacterLinks([])
      setShotCandidateItems([])
      setShotDialogueCandidateItems([])
      return
    }
    setLoadingDetail(true)
    const reqSeq = ++shotCandidatesRequestSeqRef.current
    setShotCandidateItems([])
    setShotDialogueCandidateItems([])
    Promise.all([
      StudioShotDetailsService.getShotDetailApiV1StudioShotDetailsShotIdGet({ shotId: selectedShotId }).then((r: any) => r.data ?? null),
      StudioShotDialogLinesService.listShotDialogLinesApiV1StudioShotDialogLinesGet({
        shotDetailId: selectedShotId,
        q: null,
        order: 'index',
        isDesc: false,
        page: 1,
        pageSize: 100,
      }).then((r: any) => r.data?.items ?? []),
      StudioShotFrameImagesService.listShotFrameImagesApiV1StudioShotFrameImagesGet({
        shotDetailId: selectedShotId,
        order: null,
        isDesc: false,
        page: 1,
        pageSize: 100,
      }).then((r: any) => r.data?.items ?? []),
      StudioShotLinksService.listProjectEntityLinksApiV1StudioShotLinksEntityTypeGet({
        entityType: 'scene',
        projectId: projectId ?? null,
        chapterId: chapterId ?? null,
        shotId: selectedShotId,
        assetId: null,
        order: null,
        isDesc: false,
        page: 1,
        pageSize: 100,
      }).then((r: any) => r.data?.items ?? []),
      StudioShotLinksService.listProjectEntityLinksApiV1StudioShotLinksEntityTypeGet({
        entityType: 'actor',
        projectId: projectId ?? null,
        chapterId: chapterId ?? null,
        shotId: selectedShotId,
        assetId: null,
        order: null,
        isDesc: false,
        page: 1,
        pageSize: 100,
      }).then((r: any) => r.data?.items ?? []),
      StudioShotLinksService.listProjectEntityLinksApiV1StudioShotLinksEntityTypeGet({
        entityType: 'prop',
        projectId: projectId ?? null,
        chapterId: chapterId ?? null,
        shotId: selectedShotId,
        assetId: null,
        order: null,
        isDesc: false,
        page: 1,
        pageSize: 100,
      }).then((r: any) => r.data?.items ?? []),
      StudioShotLinksService.listProjectEntityLinksApiV1StudioShotLinksEntityTypeGet({
        entityType: 'costume',
        projectId: projectId ?? null,
        chapterId: chapterId ?? null,
        shotId: selectedShotId,
        assetId: null,
        order: null,
        isDesc: false,
        page: 1,
        pageSize: 100,
      }).then((r: any) => r.data?.items ?? []),
      StudioShotCharacterLinksService.listShotCharacterLinksApiV1StudioShotCharacterLinksGet({
        shotId: selectedShotId,
      }).then((r: any) => (r.data ?? []) as ShotCharacterLinkRead[]),
      StudioShotsService.getShotExtractedCandidatesApiV1StudioShotsShotIdExtractedCandidatesGet({
        shotId: selectedShotId,
      }).then((r) => r.data ?? []),
      StudioShotsService.getShotExtractedDialogueCandidatesApiV1StudioShotsShotIdExtractedDialogueCandidatesGet({
        shotId: selectedShotId,
      }).then((r) => r.data ?? []),
    ])
      .then(([detail, dialogs, frames, scenes, actors, props, costumes, shotCharacters, candidates, dialogueCandidates]) => {
        if (reqSeq !== shotCandidatesRequestSeqRef.current) return
        setShotDetail(detail)
        lastSavedDetailRef.current = detail
        setDialogLines(dialogs)
        setFrameImages(frames)
        setSceneLinks(scenes)
        setActorImageLinks(actors)
        setPropLinks(props)
        setCostumeLinks(costumes)
        setShotCharacterLinks(shotCharacters)
        setShotCandidateItems(candidates as ShotExtractedCandidateRead[])
        setShotDialogueCandidateItems(dialogueCandidates as ShotExtractedDialogueCandidateRead[])
        if (detail?.duration != null) {
          setShotDurations((prev) => ({ ...prev, [selectedShotId]: detail.duration ?? 0 }))
        }
      })
      .catch(() => {
        if (reqSeq !== shotCandidatesRequestSeqRef.current) return
        message.error('加载分镜详情失败')
      })
      .finally(() => {
        if (reqSeq !== shotCandidatesRequestSeqRef.current) return
        setLoadingDetail(false)
      })
  }, [selectedShotId])

  useEffect(() => {
    // 选中分镜时同步多选的“主选中项”
    if (!selectedShotId) return
    if (selectedShotIds.includes(selectedShotId)) return
    setSelectedShotIds([selectedShotId])
  }, [selectedShotId, selectedShotIds])

  const selectedShot = useMemo(() => shots.find((s) => s.id === selectedShotId) ?? null, [shots, selectedShotId])
  useTaskPageContext(
    selectedShotId
      ? [
          {
            relationType: 'shot',
            relationEntityId: selectedShotId,
          },
        ]
      : [],
  )
  const selectedShots = useMemo(
    () => shots.filter((shot) => selectedShotIds.includes(shot.id)),
    [selectedShotIds, shots],
  )
  const currentPreviewVideoFileId = previewVideoFileId || selectedShot?.generated_video_file_id || null
  const currentPreviewVideoUrl = currentPreviewVideoFileId ? buildFileDownloadUrl(currentPreviewVideoFileId) ?? '' : ''

  useEffect(() => {
    // 切换分镜时：主预览区视频跟随分镜（清空手动选择的预览视频）
    setPreviewVideoFileId(null)
  }, [selectedShotId])

  const refreshDialogLines = async (shotId: string) => {
    const res = await StudioShotDialogLinesService.listShotDialogLinesApiV1StudioShotDialogLinesGet({
      shotDetailId: shotId,
      q: null,
      order: 'index',
      isDesc: false,
      page: 1,
      pageSize: 100,
    })
    setDialogLines(res.data?.items ?? [])
  }

  const refreshShotFrameImages = useCallback(async () => {
    if (!selectedShotId) return
    try {
      const res = await StudioShotFrameImagesService.listShotFrameImagesApiV1StudioShotFrameImagesGet({
        shotDetailId: selectedShotId,
        order: null,
        isDesc: false,
        page: 1,
        pageSize: 100,
      })
      setFrameImages((res.data?.items ?? []) as ShotFrameImageRead[])
    } catch {
      message.error('刷新关键帧类型失败')
    }
  }, [selectedShotId])

  const deleteDialogLine = async (lineId: number) => {
    if (!selectedShotId) return
    await StudioShotDialogLinesService.deleteShotDialogLineApiV1StudioShotDialogLinesLineIdDelete({ lineId })
    await refreshDialogLines(selectedShotId)
  }

  const refreshPromptAssetLinks = async (shotId: string) => {
    const [scenes, actors, props, costumes] = await Promise.all([
      StudioShotLinksService.listProjectEntityLinksApiV1StudioShotLinksEntityTypeGet({
        entityType: 'scene',
        projectId: projectId ?? null,
        chapterId: chapterId ?? null,
        shotId,
        assetId: null,
        order: null,
        isDesc: false,
        page: 1,
        pageSize: 100,
      }).then((r: any) => (r.data?.items ?? []) as ProjectSceneLinkRead[]),
      StudioShotLinksService.listProjectEntityLinksApiV1StudioShotLinksEntityTypeGet({
        entityType: 'actor',
        projectId: projectId ?? null,
        chapterId: chapterId ?? null,
        shotId,
        assetId: null,
        order: null,
        isDesc: false,
        page: 1,
        pageSize: 100,
      }).then((r: any) => (r.data?.items ?? []) as ProjectActorLinkRead[]),
      StudioShotLinksService.listProjectEntityLinksApiV1StudioShotLinksEntityTypeGet({
        entityType: 'prop',
        projectId: projectId ?? null,
        chapterId: chapterId ?? null,
        shotId,
        assetId: null,
        order: null,
        isDesc: false,
        page: 1,
        pageSize: 100,
      }).then((r: any) => (r.data?.items ?? []) as ProjectPropLinkRead[]),
      StudioShotLinksService.listProjectEntityLinksApiV1StudioShotLinksEntityTypeGet({
        entityType: 'costume',
        projectId: projectId ?? null,
        chapterId: chapterId ?? null,
        shotId,
        assetId: null,
        order: null,
        isDesc: false,
        page: 1,
        pageSize: 100,
      }).then((r: any) => (r.data?.items ?? []) as ProjectCostumeLinkRead[]),
    ])
    setSceneLinks(scenes)
    setActorImageLinks(actors)
    setPropLinks(props)
    setCostumeLinks(costumes)
  }

  const loadShotCandidateItems = useCallback(async (shotId: string) => {
    try {
      const res = await StudioShotsService.getShotExtractedCandidatesApiV1StudioShotsShotIdExtractedCandidatesGet({
        shotId,
      })
      setShotCandidateItems(res.data ?? [])
    } catch {
      setShotCandidateItems([])
    }
  }, [])

  const loadShotDialogueCandidateItems = useCallback(async (shotId: string) => {
    try {
      const res = await StudioShotsService.getShotExtractedDialogueCandidatesApiV1StudioShotsShotIdExtractedDialogueCandidatesGet({
        shotId,
      })
      setShotDialogueCandidateItems(res.data ?? [])
    } catch {
      setShotDialogueCandidateItems([])
    }
  }, [])

  const batchUpdateSkipExtraction = useCallback(
    async (skip: boolean) => {
      const targetShots = selectedShots.filter((shot) => Boolean(shot.skip_extraction) !== skip)
      if (targetShots.length === 0) {
        message.info(skip ? '所选分镜已全部标记为无需提取' : '所选分镜已全部恢复提取')
        return
      }
      setBatchSkipExtractionUpdating(true)
      try {
        const results = await Promise.all(
          targetShots.map(async (shot) => {
            const res = await StudioShotsService.updateShotSkipExtractionApiV1StudioShotsShotIdSkipExtractionPatch({
              shotId: shot.id,
              requestBody: { skip },
            })
            return { shotId: shot.id, data: res.data?.state.shot ?? null }
          }),
        )
        results.forEach(({ shotId, data }) => {
          if (data) {
            patchShotInList(shotId, data as Partial<StudioShot>)
          } else {
            patchShotInList(shotId, { skip_extraction: skip })
          }
        })
        if (selectedShotId && targetShots.some((shot) => shot.id === selectedShotId)) {
          await Promise.all([
            loadShotCandidateItems(selectedShotId),
            loadShotDialogueCandidateItems(selectedShotId),
          ])
        }
        message.success(
          skip
            ? `已批量标记 ${targetShots.length} 条分镜为无需提取`
            : `已批量恢复 ${targetShots.length} 条分镜的提取确认流程`,
        )
      } catch {
        message.error(skip ? '批量标记无需提取失败' : '批量恢复提取失败')
      } finally {
        setBatchSkipExtractionUpdating(false)
      }
    },
    [loadShotCandidateItems, loadShotDialogueCandidateItems, patchShotInList, selectedShotId, selectedShots],
  )

  const fetchBatchVideoReadiness = useCallback(async () => {
    if (selectedShots.length === 0) {
      message.info('请先选择要检查的视频分镜')
      return [] as Array<{ shot: StudioShot; readiness: ShotVideoReadinessRead | null; error?: string }>
    }
    return Promise.all(
      selectedShots
        .slice()
        .sort((a, b) => a.index - b.index)
        .map(async (shot) => {
          try {
            const res = await StudioShotsService.getShotVideoReadinessApiApiV1StudioShotsShotIdVideoReadinessGet({
              shotId: shot.id,
              referenceMode: 'text_only',
            })
            return {
              shot,
              readiness: (res.data ?? null) as ShotVideoReadinessRead | null,
            }
          } catch {
            return {
              shot,
              readiness: null,
              error: '视频准备度检查失败，请稍后重试',
            }
          }
        }),
    )
  }, [selectedShots])

  const batchInspectVideoReadiness = useCallback(async () => {
    setBatchVideoReadinessOpen(true)
    setBatchVideoReadinessLoading(true)
    try {
      const results = await fetchBatchVideoReadiness()
      setBatchVideoReadinessItems(results)
    } finally {
      setBatchVideoReadinessLoading(false)
    }
  }, [fetchBatchVideoReadiness])

  const runBatchGenerate = useCallback(
    async (targetShotIds: string[]) => {
      for (const id of targetShotIds) {
        const framesRes = await StudioShotFrameImagesService.listShotFrameImagesApiV1StudioShotFrameImagesGet({
          shotDetailId: id,
          order: null,
          isDesc: false,
          page: 1,
          pageSize: 100,
        })
        const frames = framesRes.data?.items ?? []
        const target = frames.find((x) => x.frame_type === 'key') ?? frames[0]
        if (!target) continue

        const detailRes: any = await StudioShotDetailsService.getShotDetailApiV1StudioShotDetailsShotIdGet({ shotId: id })
        const d = detailRes?.data as any
        const prompt =
          (target.frame_type === 'first'
            ? d?.first_frame_prompt
            : target.frame_type === 'last'
              ? d?.last_frame_prompt
              : d?.key_frame_prompt) ?? ''
        if (!String(prompt || '').trim()) continue

        const linked = await StudioShotsService.listShotLinkedAssetsApiV1StudioShotsShotIdLinkedAssetsGet({
          shotId: id,
          page: 1,
          pageSize: 100,
        })
        const items = (linked.data?.items ?? []) as any[]
        const extractFileId = (thumbnail?: string | null): string | null => {
          const v = (thumbnail || '').trim()
          if (!v) return null
          if (!v.includes('/') && !v.includes(':')) return v
          try {
            const url = new URL(v, typeof window !== 'undefined' ? window.location.origin : 'http://localhost')
            const m = url.pathname.match(/\/api\/v1\/studio\/files\/([^/]+)\/download\/?$/)
            if (m?.[1]) return decodeURIComponent(m[1])
          } catch {
            // ignore
          }
          return null
        }
        const imagesPayload = items
          .map((x) => {
            const fileId = typeof x?.file_id === 'string' && x.file_id.trim() ? x.file_id.trim() : extractFileId(x?.thumbnail)
            return fileId
              ? {
                  type: x?.type as any,
                  id: String(x?.id ?? ''),
                  name: String(x?.name ?? x?.id ?? ''),
                  file_id: fileId,
                }
              : null
          })
          .filter(Boolean)
        const targetRatio = resolveShotVideoRatio(d)
        if (!targetRatio) continue
        await StudioImageTasksService.createShotFrameImageGenerationTaskApiV1StudioImageTasksShotShotIdFrameImageTasksPost({
          shotId: id,
          requestBody: {
            frame_type: target.frame_type as any,
            model_id: null,
            prompt,
            images: imagesPayload,
            target_ratio: targetRatio,
            resolution_profile: keyframeResolutionProfile,
          } as any,
        })
      }
    },
    [keyframeResolutionProfile, resolveShotVideoRatio],
  )

  const updatePromptProps = async (propIds: string[]) => {
    if (!selectedShotId || !projectId) return
    const next = Array.from(new Set(propIds.map((x) => x.trim()).filter(Boolean)))
    setPromptAssetsUpdating(true)
    try {
      const currentLinks = propLinks.filter((l) => (l.shot_id ?? null) === selectedShotId)
      await Promise.all(currentLinks.map((l) => StudioShotLinksService.deleteProjectPropLinkApiV1StudioShotLinksPropLinkIdDelete({ linkId: l.id })))
      await Promise.all(
        next.map((pid) =>
          StudioShotLinksService.createProjectPropLinkApiV1StudioShotLinksPropPost({
            requestBody: { project_id: projectId, chapter_id: chapterId ?? null, shot_id: selectedShotId, asset_id: pid },
          }),
        ),
      )
      await refreshPromptAssetLinks(selectedShotId)
      await loadShotCandidateItems(selectedShotId)
    } catch {
      message.error('更新道具失败')
    } finally {
      setPromptAssetsUpdating(false)
    }
  }

  const updatePromptCostumes = async (costumeIds: string[]) => {
    if (!selectedShotId || !projectId) return
    const next = Array.from(new Set(costumeIds.map((x) => x.trim()).filter(Boolean)))
    setPromptAssetsUpdating(true)
    try {
      const currentLinks = costumeLinks.filter((l) => (l.shot_id ?? null) === selectedShotId)
      await Promise.all(currentLinks.map((l) => StudioShotLinksService.deleteProjectCostumeLinkApiV1StudioShotLinksCostumeLinkIdDelete({ linkId: l.id })))
      await Promise.all(
        next.map((cid) =>
          StudioShotLinksService.createProjectCostumeLinkApiV1StudioShotLinksCostumePost({
            requestBody: { project_id: projectId, chapter_id: chapterId ?? null, shot_id: selectedShotId, asset_id: cid },
          }),
        ),
      )
      await refreshPromptAssetLinks(selectedShotId)
      await loadShotCandidateItems(selectedShotId)
    } catch {
      message.error('更新服装失败')
    } finally {
      setPromptAssetsUpdating(false)
    }
  }

  const updatePromptScene = async (sceneId?: string) => {
    if (!selectedShotId || !projectId) return
    setPromptAssetsUpdating(true)
    try {
      const currentLinks = sceneLinks.filter((l) => (l.shot_id ?? null) === selectedShotId)
      await Promise.all(currentLinks.map((l) => StudioShotLinksService.deleteProjectSceneLinkApiV1StudioShotLinksSceneLinkIdDelete({ linkId: l.id })))
      const nextSceneId = (sceneId ?? '').trim()
      if (nextSceneId) {
        await StudioShotLinksService.createProjectSceneLinkApiV1StudioShotLinksScenePost({
          requestBody: {
            project_id: projectId,
            chapter_id: chapterId ?? null,
            shot_id: selectedShotId,
            asset_id: nextSceneId,
          },
        })
      }
      await refreshPromptAssetLinks(selectedShotId)
      await loadShotCandidateItems(selectedShotId)
      patchShotDetailLocal({ scene_id: nextSceneId || null })
    } catch {
      message.error('更新场景失败')
    } finally {
      setPromptAssetsUpdating(false)
    }
  }

  const updatePromptActors = async (actorIds: string[]) => {
    if (!selectedShotId) return
    const next = Array.from(new Set(actorIds.map((x) => x.trim()).filter(Boolean)))
    const current = shotCharacterLinks
      .slice()
      .sort((a, b) => (a.index ?? 0) - (b.index ?? 0))
      .map((x) => x.character_id)
    const removed = current.filter((id) => !next.includes(id))
    if (removed.length > 0) {
      message.warning('当前接口暂不支持移除已关联角色，仅会新增或重排')
    }
    if (next.length === 0) return
    setPromptAssetsUpdating(true)
    try {
      await Promise.all(
        next.map((characterId, index) =>
          StudioShotCharacterLinksService.upsertShotCharacterLinkApiV1StudioShotCharacterLinksPost({
            requestBody: { shot_id: selectedShotId, character_id: characterId, index, note: '' },
          }),
        ),
      )
      const refreshed = await StudioShotCharacterLinksService.listShotCharacterLinksApiV1StudioShotCharacterLinksGet({ shotId: selectedShotId })
      setShotCharacterLinks((refreshed.data ?? []) as ShotCharacterLinkRead[])
      await loadShotCandidateItems(selectedShotId)
    } catch {
      message.error('更新角色失败')
    } finally {
      setPromptAssetsUpdating(false)
    }
  }

  const generateFrameImageTask = async () => {
    if (!selectedShotId) return
    const target =
      (frameTab === 'head' && frameImages.find((x) => x.frame_type === 'first')) ||
      (frameTab === 'tail' && frameImages.find((x) => x.frame_type === 'last')) ||
      frameImages.find((x) => x.frame_type === 'key') ||
      frameImages[0]
    if (!target) {
      message.warning('请先添加一张分镜帧图（frame image）')
      return
    }
    const prompt =
      (target.frame_type === 'first'
        ? shotDetail?.first_frame_prompt
        : target.frame_type === 'last'
          ? shotDetail?.last_frame_prompt
          : shotDetail?.key_frame_prompt) ?? ''
    if (!prompt.trim()) {
      message.warning('请先生成或填写提示词')
      return
    }
    setGenerating(true)
    try {
      const linked = await StudioShotsService.listShotLinkedAssetsApiV1StudioShotsShotIdLinkedAssetsGet({
        shotId: selectedShotId,
        page: 1,
        pageSize: 100,
      })
      const items = (linked.data?.items ?? []) as any[]
      const extractFileId = (thumbnail?: string | null): string | null => {
        const v = (thumbnail || '').trim()
        if (!v) return null
        if (!v.includes('/') && !v.includes(':')) return v
        try {
          const url = new URL(v, typeof window !== 'undefined' ? window.location.origin : 'http://localhost')
          const m = url.pathname.match(/\/api\/v1\/studio\/files\/([^/]+)\/download\/?$/)
          if (m?.[1]) return decodeURIComponent(m[1])
        } catch {
          // ignore
        }
        return null
      }
      const imagesPayload = items
        .map((x) => {
          const fileId = typeof x?.file_id === 'string' && x.file_id.trim() ? x.file_id.trim() : extractFileId(x?.thumbnail)
          return fileId
            ? {
                type: x?.type as any,
                id: String(x?.id ?? ''),
                name: String(x?.name ?? x?.id ?? ''),
                file_id: fileId,
              }
            : null
        })
        .filter(Boolean)
      const targetRatio = resolveShotVideoRatio(shotDetail)
      if (!targetRatio) {
        message.warning('请先设置视频比例')
        return
      }
      await StudioImageTasksService.createShotFrameImageGenerationTaskApiV1StudioImageTasksShotShotIdFrameImageTasksPost({
        shotId: selectedShotId,
        requestBody: {
          frame_type: target.frame_type as any,
          model_id: null,
          prompt,
          images: imagesPayload,
          target_ratio: targetRatio,
          resolution_profile: keyframeResolutionProfile,
        } as any,
      })
      message.success('已创建生成任务')
    } catch {
      message.error('创建生成任务失败')
    } finally {
      setGenerating(false)
    }
  }

  const currentFrameSlot = useMemo(() => {
    if (frameTab === 'head') return frameImages.find((x) => x.frame_type === 'first') ?? null
    if (frameTab === 'tail') return frameImages.find((x) => x.frame_type === 'last') ?? null
    return frameImages.find((x) => x.frame_type === 'key') ?? frameImages[0] ?? null
  }, [frameImages, frameTab])

  const currentFrameFileId = useMemo(() => {
    const fid = currentFrameSlot?.file_id ?? null
    return fid ? String(fid) : null
  }, [currentFrameSlot?.file_id])

  const currentFrameFileTags = useMemo(() => {
    if (!currentFrameFileId) return []
    return frameFileTagsMap[currentFrameFileId] ?? []
  }, [currentFrameFileId, frameFileTagsMap])

  useEffect(() => {
    if (!currentFrameFileId) return
    if (frameFileTagsMap[currentFrameFileId]) return
    let canceled = false
    setFrameFileTagsLoading(true)
    void (async () => {
      try {
        const res = await StudioFilesService.getFileDetailApiV1StudioFilesFileIdGet({ fileId: currentFrameFileId })
        if (canceled) return
        const tagsRaw = Array.isArray((res.data as any)?.tags) ? ((res.data as any).tags as string[]).filter(Boolean) : []
        setFrameFileTagsMap((prev) => ({ ...prev, [currentFrameFileId]: normalizeFrameExclusiveTags(tagsRaw) }))
      } catch {
        if (!canceled) setFrameFileTagsMap((prev) => ({ ...prev, [currentFrameFileId]: [] }))
      } finally {
        if (!canceled) setFrameFileTagsLoading(false)
      }
    })()
    return () => {
      canceled = true
    }
  }, [currentFrameFileId, frameFileTagsMap])

  const updateCurrentFrameFileTags = useCallback(
    async (nextTags: string[]) => {
      if (!currentFrameFileId) return
      const cleaned = Array.from(
        new Set(
          (nextTags || [])
            .map((x) => String(x ?? '').trim())
            .filter((x) => x.length > 0),
        ),
      )
      const normalized = normalizeFrameExclusiveTags(cleaned)
      setFrameFileTagsLoading(true)
      setFrameFileTagsMap((prev) => ({ ...prev, [currentFrameFileId]: normalized }))
      try {
        await StudioFilesService.updateFileMetaApiV1StudioFilesFileIdPatch({
          fileId: currentFrameFileId,
          requestBody: { tags: normalized } as any,
        })
      } catch {
        message.error('更新标签失败')
      } finally {
        setFrameFileTagsLoading(false)
      }
    },
    [currentFrameFileId],
  )

  // 选中分镜后若开启自动展开属性面板：默认展开（尤其是未就绪分镜）
  useEffect(() => {
    if (!selectedShot) return
    if (!prefs.autoOpenInspector) return
    if (prefs.inspectorOpen) return
    // “若无视频则自动展开”：这里用 status !== ready 作为近似判定
    if (selectedShot.status !== 'ready') {
      setPrefs((p) => ({ ...p, inspectorOpen: true }))
    }
  }, [prefs.autoOpenInspector, prefs.inspectorOpen, selectedShot, setPrefs])

  const lastSavedDetailRef = useRef<ShotDetailRead | null>(null)

  const patchShotDetailLocal = (patch: Partial<ShotDetailRead>) => {
    setShotDetail((prev) => (prev ? { ...prev, ...patch } : prev))
  }

  const patchShotDetailImmediate = async (patch: Partial<ShotDetailRead>) => {
    if (!selectedShotId) return
    patchShotDetailLocal(patch)
    setCameraUpdating(true)
    const seq = ++cameraPatchSeqRef.current
    try {
      const r: any = await StudioShotDetailsService.updateShotDetailApiV1StudioShotDetailsShotIdPatch({
        shotId: selectedShotId,
        requestBody: patch as any,
      })
      if (seq !== cameraPatchSeqRef.current) return
      if (r.data) {
        setShotDetail(r.data)
        lastSavedDetailRef.current = r.data
        if (r.data.duration != null) {
          setShotDurations((m) => ({ ...m, [selectedShotId]: r.data?.duration ?? 0 }))
        }
      }
    } catch {
      if (seq !== cameraPatchSeqRef.current) return
      message.error('镜头语言更新失败')
    } finally {
      if (seq === cameraPatchSeqRef.current) setCameraUpdating(false)
    }
  }

  // 自动保存（防抖）：shotDetail 变更后 PATCH 到后端
  useEffect(() => {
    if (!selectedShotId || !shotDetail) return
    if (saveTimerRef.current) window.clearTimeout(saveTimerRef.current)
    setSaving(true)
    saveTimerRef.current = window.setTimeout(() => {
      const prev = lastSavedDetailRef.current
      const next = shotDetail
      const patch: Record<string, unknown> = {}
      const assignIfChanged = <K extends keyof ShotDetailRead>(key: K) => {
        if (prev?.[key] !== next[key]) patch[key] = next[key] ?? null
      }
      assignIfChanged('scene_id')
      // 镜头语言字段（camera_shot/angle/movement/duration）走即时更新，不在此处防抖提交
      // array / object fields
      if (JSON.stringify(prev?.mood_tags ?? null) !== JSON.stringify(next.mood_tags ?? null)) patch.mood_tags = next.mood_tags ?? null
      assignIfChanged('atmosphere')
      assignIfChanged('follow_atmosphere')
      assignIfChanged('has_bgm')
      assignIfChanged('override_video_ratio')
      assignIfChanged('vfx_type')
      assignIfChanged('vfx_note')
      assignIfChanged('first_frame_prompt')
      assignIfChanged('key_frame_prompt')
      assignIfChanged('last_frame_prompt')

      const keys = Object.keys(patch)
      if (keys.length === 0) {
        setSaving(false)
        saveTimerRef.current = null
        return
      }

      void StudioShotDetailsService.updateShotDetailApiV1StudioShotDetailsShotIdPatch({
        shotId: selectedShotId,
        requestBody: patch as any,
      })
        .then((r: any) => {
          if (r.data) {
            setShotDetail(r.data)
            lastSavedDetailRef.current = r.data
            if (r.data.duration != null) {
              setShotDurations((m) => ({ ...m, [selectedShotId]: r.data?.duration ?? 0 }))
            }
          }
        })
        .catch(() => {
          message.error('自动保存失败')
        })
        .finally(() => {
          setSaving(false)
          saveTimerRef.current = null
        })
    }, 1000)
    return () => {
      if (saveTimerRef.current) window.clearTimeout(saveTimerRef.current)
      saveTimerRef.current = null
    }
  }, [selectedShotId, shotDetail])

  // 播放器：同步时间与状态
  useEffect(() => {
    const v = videoRef.current
    if (!v) return
    const onPlay = () => setIsPlaying(true)
    const onPause = () => setIsPlaying(false)
    const onTimeUpdate = () => setVideoTime(v.currentTime || 0)
    const onLoaded = () => setVideoDuration(v.duration || 0)
    v.addEventListener('play', onPlay)
    v.addEventListener('pause', onPause)
    v.addEventListener('timeupdate', onTimeUpdate)
    v.addEventListener('loadedmetadata', onLoaded)
    return () => {
      v.removeEventListener('play', onPlay)
      v.removeEventListener('pause', onPause)
      v.removeEventListener('timeupdate', onTimeUpdate)
      v.removeEventListener('loadedmetadata', onLoaded)
    }
  }, [selectedShotId])

  useEffect(() => {
    const v = videoRef.current
    if (!v) return
    v.playbackRate = playbackRate
  }, [playbackRate])

  useEffect(() => {
    const v = videoRef.current
    if (!v) return
    v.loop = loopCurrent
  }, [loopCurrent])

  useEffect(() => {
    const v = videoRef.current
    if (!v || !currentPreviewVideoUrl) return
    v.load()
    void v.play().catch(() => {
      // 浏览器策略可能阻止自动播放，保留静默失败
    })
  }, [currentPreviewVideoUrl])

  // 快捷键：←/→ 切换分镜，Space 播放暂停，P/Ctrl+I 面板，H 隐藏，M 合并，Ctrl/Cmd+Enter 保存并生成
  useEffect(() => {
    const onKeyDown = (e: KeyboardEvent) => {
      if (isTypingTarget(e.target)) return
      const key = e.key.toLowerCase()

      if (key === 'p' || (key === 'i' && (e.ctrlKey || e.metaKey))) {
        e.preventDefault()
        setPrefs((p) => ({ ...p, inspectorOpen: !p.inspectorOpen }))
        return
      }

      if (key === ' ') {
        e.preventDefault()
        const v = videoRef.current
        if (!v) return
        if (v.paused) void v.play()
        else v.pause()
        return
      }

      if (key === 'arrowleft' || key === 'arrowright') {
        e.preventDefault()
        const visible = shots.filter((s) => !s.hidden)
        const idx = visible.findIndex((s) => s.id === selectedShotId)
        if (idx === -1) return
        const next = key === 'arrowleft' ? visible[idx - 1] : visible[idx + 1]
        if (next) setSelectedShotId(next.id)
        return
      }

      if ((e.ctrlKey || e.metaKey) && key === 'enter') {
        e.preventDefault()
        void generateFrameImageTask()
        return
      }

      if (key === 'h') {
        e.preventDefault()
        if (!selectedShotId) return
        toggleHiddenShots([selectedShotId])
        return
      }

      if (key === 'm') {
        e.preventDefault()
        if (selectedShotIds.length < 2) {
          message.info('请先多选至少 2 个分镜再合并')
          return
        }
        Modal.confirm({
          title: `合并 ${selectedShotIds.length} 个分镜？`,
          content: '将它们合并为一个新的分镜（Mock 行为）。',
          okText: '合并',
          cancelText: '取消',
          onOk: () => {
            message.success('已合并（Mock）')
          },
        })
      }
    }
    window.addEventListener('keydown', onKeyDown)
    return () => window.removeEventListener('keydown', onKeyDown)
  }, [selectedShotId, selectedShotIds.length, shots, setPrefs])

  const statusTag = (status: ShotStatus | undefined) => {
    const s = status ?? 'pending'
    const map = { pending: 'default', generating: 'processing', ready: 'success' } as const
    const text = { pending: '待确认', generating: '生成中', ready: '已就绪' } as const
    return <Tag color={map[s]}>{text[s]}</Tag>
  }

  const statusDotClass = (status: ShotStatus | undefined) => {
    if (status === 'generating') return 'cs-generating'
    if (status === 'ready') return 'cs-ready'
    return 'cs-pending'
  }

  const getShotReadinessFlags = useCallback((shot: StudioShot) => {
    const runtime = shotRuntimeMap[shot.id]
    const isReady = !shot.hidden && shot.status === 'ready'
    const isGenerating = !shot.hidden && Boolean(runtime?.has_active_tasks)
    const isPendingConfirm = !shot.hidden && shot.status === 'pending'
    const hasProblem = Boolean(shot.hasProblem)
    const missing: string[] = []
    if (isPendingConfirm) missing.push('待确认')
    if (isGenerating) missing.push('生成中')
    return {
      isReady,
      isGenerating,
      isPendingConfirm,
      hasProblem,
      missing,
    }
  }, [shotRuntimeMap])

  const getShotProgressCount = useCallback(
    (shot: StudioShot) => {
      return [shot.status !== 'pending', shot.status === 'ready'].filter(Boolean).length
    },
    [getShotReadinessFlags],
  )

  const getShotPrimaryHint = useCallback(
    (shot: StudioShot) => {
      const flags = getShotReadinessFlags(shot)
      if (flags.hasProblem) return '存在待处理问题'
      if (flags.isGenerating) {
        const runtime = shotRuntimeMap[shot.id]
        return `镜头相关任务进行中（${runtime?.active_task_count ?? 1}）`
      }
      if (flags.isPendingConfirm) {
        return shot.skip_extraction
          ? '已标记无需提取，等待系统完成流程状态同步'
          : '请先完成信息提取确认'
      }
      return '镜头已具备视频生成前置条件'
    },
    [getShotReadinessFlags, shotRuntimeMap],
  )

  const chapterTitle = useMemo(() => {
    if (!chapter) return '章节生成工作台'
    return `第${chapter.index}章 · ${chapter.title.replace(/^第\d+[集章：:\s]*/g, '').trim() || chapter.title}`
  }, [chapter])

  const filteredShots = useMemo(() => {
    const list = shots.slice().sort((a, b) => a.index - b.index)
    switch (filter) {
      case 'pendingConfirm':
        return list.filter((s) => getShotReadinessFlags(s).isPendingConfirm)
      case 'generating':
        return list.filter((s) => getShotReadinessFlags(s).isGenerating)
      case 'ready':
        return list.filter((s) => getShotReadinessFlags(s).isReady)
      case 'hidden':
        return list.filter((s) => Boolean(s.hidden))
      case 'problem':
        return list.filter((s) => !s.hidden && Boolean(s.hasProblem))
      default:
        return list
    }
  }, [filter, getShotReadinessFlags, shots])

  const shotFilterCounts = useMemo(() => {
    const list = shots.slice()
    return {
      all: list.length,
      pendingConfirm: list.filter((s) => getShotReadinessFlags(s).isPendingConfirm).length,
      generating: list.filter((s) => getShotReadinessFlags(s).isGenerating).length,
      ready: list.filter((s) => getShotReadinessFlags(s).isReady).length,
      hidden: list.filter((s) => Boolean(s.hidden)).length,
      problem: list.filter((s) => !s.hidden && Boolean(s.hasProblem)).length,
    } satisfies Record<ShotFilter, number>
  }, [getShotReadinessFlags, shots])

  const multiToolbarVisible = selectedShotIds.length > 1

  const handleSelectShot = (shotId: string, indexInFiltered: number, e: React.MouseEvent) => {
    setSelectedShotId(shotId)
    const isRange = e.shiftKey && lastSelectedIndexRef.current >= 0
    const isToggle = e.ctrlKey || e.metaKey

    if (isRange) {
      const start = Math.min(lastSelectedIndexRef.current, indexInFiltered)
      const end = Math.max(lastSelectedIndexRef.current, indexInFiltered)
      const rangeIds = filteredShots.slice(start, end + 1).map((s) => s.id)
      setSelectedShotIds(Array.from(new Set([...selectedShotIds, ...rangeIds])))
      return
    }

    if (isToggle) {
      setSelectedShotIds((prev) => (prev.includes(shotId) ? prev.filter((id) => id !== shotId) : [...prev, shotId]))
      lastSelectedIndexRef.current = indexInFiltered
      return
    }

    setSelectedShotIds([shotId])
    lastSelectedIndexRef.current = indexInFiltered
  }

  const matchesFilter = (s: StudioShot, f: ShotFilter) => {
    const flags = getShotReadinessFlags(s)
    switch (f) {
      case 'pendingConfirm':
        return flags.isPendingConfirm
      case 'generating':
        return flags.isGenerating
      case 'ready':
        return flags.isReady
      case 'hidden':
        return Boolean(s.hidden)
      case 'problem':
        return !s.hidden && flags.hasProblem
      default:
        return true
    }
  }

  const reorderWithinFilter = (sourceId: string, destId: string) => {
    if (sourceId === destId) return
    setShots((prev) => {
      const ordered = prev.slice().sort((a, b) => a.index - b.index)
      const subset = ordered.filter((s) => matchesFilter(s, filter))
      const sourceIndex = subset.findIndex((s) => s.id === sourceId)
      const destIndex = subset.findIndex((s) => s.id === destId)
      if (sourceIndex === -1 || destIndex === -1) return prev
      const movedSubset = reorder(subset, sourceIndex, destIndex)
      const movedQueue = [...movedSubset]
      const replaced = ordered.map((s) => (matchesFilter(s, filter) ? (movedQueue.shift() as StudioShot) : s))
      const next = replaced.map((s, idx) => ({ ...s, index: idx + 1 }))

      // 后台同步排序（不阻塞 UI）
      const beforeMap = new Map(prev.map((s) => [s.id, s.index]))
      void (async () => {
        try {
          const changed = next.filter((s) => beforeMap.get(s.id) !== s.index)
          await Promise.all(
            changed.map((s) =>
              StudioShotsService.updateShotApiV1StudioShotsShotIdPatch({
                shotId: s.id,
                requestBody: { index: s.index },
              }),
            ),
          )
        } catch {
          message.error('同步排序失败')
        }
      })()

      return next
    })
  }

  const beginResize = (type: 'left' | 'right', e: React.PointerEvent) => {
    if (!containerRef.current) return
    const startX = e.clientX
    dragStateRef.current = {
      type,
      startX,
      startLeft: prefs.leftWidth,
      startRight: prefs.rightWidth,
    }
    ;(e.currentTarget as HTMLElement).setPointerCapture(e.pointerId)
    setIsResizing(true)
  }

  const onResizeMove = (e: React.PointerEvent) => {
    const st = dragStateRef.current
    if (!st) return
    const dx = e.clientX - st.startX
    const minLeft = 240
    const maxLeft = 360
    const minRight = 360
    const maxRight = 720
    if (st.type === 'left') {
      pendingResizeRef.current = { leftWidth: clamp(st.startLeft + dx, minLeft, maxLeft) }
    } else {
      // right：推挤/覆盖都复用 width 偏好
      pendingResizeRef.current = { rightWidth: clamp(st.startRight - dx, minRight, maxRight) }
    }

    if (resizeRafRef.current) return
    resizeRafRef.current = window.requestAnimationFrame(() => {
      const pending = pendingResizeRef.current
      pendingResizeRef.current = null
      resizeRafRef.current = null
      if (!pending) return
      setPrefs((p) => ({
        ...p,
        ...(typeof pending.leftWidth === 'number' ? { leftWidth: pending.leftWidth } : null),
        ...(typeof pending.rightWidth === 'number' ? { rightWidth: pending.rightWidth } : null),
      }))
    })
  }

  const endResize = () => {
    dragStateRef.current = null
    pendingResizeRef.current = null
    if (resizeRafRef.current) {
      window.cancelAnimationFrame(resizeRafRef.current)
      resizeRafRef.current = null
    }
    setIsResizing(false)
  }

  const shotContextMenu = (shot: StudioShot) => ([
    {
      key: 'copy',
      icon: <LinkOutlined />,
      label: '复制分镜',
      onClick: () => message.success('已复制（Mock）'),
    },
    {
      key: 'insert_after',
      icon: <VideoCameraAddOutlined />,
      label: '在后插入新分镜',
      onClick: () => message.success('已插入（Mock）'),
    },
    {
      key: 'transition',
      icon: <ScissorOutlined />,
      label: '设为转场点',
      onClick: () => message.success('已设置（Mock）'),
    },
    { type: 'divider' as const },
    {
      key: 'toggle_hide',
      icon: shot.hidden ? <EyeOutlined /> : <EyeInvisibleOutlined />,
      label: shot.hidden ? '取消隐藏' : '隐藏',
      onClick: () => toggleHiddenShots([shot.id]),
    },
    {
      key: 'delete',
      icon: <DeleteOutlined />,
      danger: true,
      label: '删除',
      onClick: () =>
        Modal.confirm({
          title: '删除分镜？',
          content: '此操作不可撤销。',
          okText: '删除',
          okButtonProps: { danger: true },
          cancelText: '取消',
          onOk: async () => {
            try {
              await StudioShotsService.deleteShotApiV1StudioShotsShotIdDelete({ shotId: shot.id })
              await loadShots()
              message.success('已删除')
            } catch {
              message.error('删除失败')
            }
          },
        }),
    },
  ])

  const batchMenuItems = [
    {
      key: 'merge',
      icon: <MergeCellsOutlined />,
      label: '合并',
      disabled: selectedShotIds.length < 2,
      onClick: () => {
        if (selectedShotIds.length < 2) return
        Modal.confirm({
          title: `合并 ${selectedShotIds.length} 个分镜？`,
          okText: '合并',
          cancelText: '取消',
          onOk: () => message.success('已合并（Mock）'),
        })
      },
    },
    {
      key: 'hide',
      icon: <EyeInvisibleOutlined />,
      label: '隐藏',
      onClick: () => toggleHiddenShots(selectedShotIds),
    },
    {
      key: 'delete',
      icon: <DeleteOutlined />,
      danger: true,
      label: '删除',
      onClick: () =>
        Modal.confirm({
          title: `删除 ${selectedShotIds.length} 个分镜？`,
          okText: '删除',
          okButtonProps: { danger: true },
          cancelText: '取消',
          onOk: async () => {
            try {
              await Promise.all(selectedShotIds.map((id) => StudioShotsService.deleteShotApiV1StudioShotsShotIdDelete({ shotId: id })))
              await loadShots()
              message.success('已删除')
            } catch {
              message.error('删除失败')
            }
          },
        }),
    },
    { type: 'divider' as const },
    {
      key: 'skip-extraction',
      icon: <StopOutlined />,
      danger: true,
      label: '维护：标记无需提取',
      onClick: () =>
        Modal.confirm({
          title: `确认以维护方式将 ${selectedShotIds.length} 个分镜标记为无需提取？`,
          content: '这属于准备阶段的维护性调整。标记后这些分镜会直接按“提取确认已完成”处理。',
          okText: '确认',
          okButtonProps: { danger: true, loading: batchSkipExtractionUpdating },
          cancelText: '取消',
          cancelButtonProps: { disabled: batchSkipExtractionUpdating },
          onOk: () => batchUpdateSkipExtraction(true),
        }),
    },
    {
      key: 'restore-extraction',
      icon: <UndoOutlined />,
      label: '维护：恢复提取',
      disabled: batchSkipExtractionUpdating,
      onClick: () => batchUpdateSkipExtraction(false),
    },
    { type: 'divider' as const },
    {
      key: 'generate',
      icon: <ThunderboltOutlined />,
      label: '批量生成',
      onClick: () => {
        if (selectedShotIds.length === 0) return
        Modal.confirm({
          title: `批量生成 ${selectedShotIds.length} 个分镜？`,
          okText: '开始',
          cancelText: '取消',
          onOk: async () => {
            setGenerating(true)
            try {
              const readinessResults = await fetchBatchVideoReadiness()
              const readyShots = readinessResults.filter((item) => item.readiness?.ready)
              const blockedShots = readinessResults.filter((item) => !item.readiness?.ready)

              if (blockedShots.length > 0) {
                setBatchVideoReadinessItems(readinessResults)
                setBatchVideoReadinessOpen(true)
              }

              if (readyShots.length === 0) {
                message.warning('当前选中的分镜都未通过视频准备度检查，已为你展开检查结果')
                return
              }

              if (blockedShots.length > 0) {
                message.warning(`其中 ${blockedShots.length} 条未通过检查，已自动跳过，仅继续生成 ${readyShots.length} 条`)
              }

              await runBatchGenerate(readyShots.map((item) => item.shot.id))
              message.success('已创建批量生成任务')
            } catch {
              message.error('批量生成失败')
            } finally {
              setGenerating(false)
            }
          },
        })
      },
    },
  ]

  const batchMaintenanceMenuItems = batchMenuItems.filter((item) => item.key !== 'generate')

  const toolbarSettingsItems = [
    {
      key: 'mode',
      icon: <AppstoreOutlined />,
      label: (
        <div className="flex items-center justify-between gap-3">
          <span>属性面板模式</span>
          <Select
            size="small"
            value={prefs.inspectorMode}
            style={{ width: 120 }}
            onChange={(v) => setPrefs((p) => ({ ...p, inspectorMode: v }))}
            options={[
              { value: 'push', label: '推挤模式' },
              { value: 'overlay', label: '覆盖模式' },
            ]}
          />
        </div>
      ),
    },
    {
      key: 'autoOpen',
      icon: <SettingOutlined />,
      label: (
        <div className="flex items-center justify-between gap-3">
          <span>选中分镜自动展开</span>
          <Switch
            size="small"
            checked={prefs.autoOpenInspector}
            onChange={(v) => setPrefs((p) => ({ ...p, autoOpenInspector: v }))}
          />
        </div>
      ),
    },
  ]

  const subtitleLines = useMemo(() => {
    if (!selectedShot || dialogLines.length === 0) return []
    const dur = Math.max(1, shotDetail?.duration ?? shotDurations[selectedShot.id] ?? 1)
    const per = dur / dialogLines.length
    return dialogLines.map((d, i) => ({
      key: `${selectedShot.id}-${d.id}`,
      role: d.speaker_character_id ?? '—',
      text: d.text,
      start: i * per,
      end: (i + 1) * per,
    }))
  }, [dialogLines, selectedShot, shotDetail?.duration, shotDurations])

  const activeSubtitleIndex = useMemo(() => {
    if (!selectedShot || subtitleLines.length === 0) return -1
    const t = videoTime
    return subtitleLines.findIndex((l) => t >= l.start && t < l.end)
  }, [selectedShot, subtitleLines, videoTime])

  return (
    <div className={['cs-studio w-full h-full min-h-0 flex flex-col', isResizing ? 'cs-resizing' : ''].join(' ')} ref={containerRef}>
      {/* 顶部工具栏（常驻） */}
      <div
        className="cs-topbar flex items-center gap-4 px-4 py-3"
        style={{
          flexShrink: 0,
        }}
      >
        <div className="flex items-center gap-2 min-w-0">
          {projectId && (
            <Link
              to={`/projects/${projectId}?tab=chapters`}
              className="text-sm text-gray-600 hover:text-blue-600 flex items-center gap-1 shrink-0"
            >
              <ArrowLeftOutlined /> 返回
            </Link>
          )}
          <Divider type="vertical" />
          <div className="min-w-0">
            <div className="font-medium text-gray-900 truncate">{chapterTitle}</div>
            <div className="text-xs text-gray-500">
              {saving ? (
                <span className="inline-flex items-center gap-1">
                  <ClockCircleOutlined /> 自动保存中…
                </span>
              ) : (
                <span className="inline-flex items-center gap-1">
                  <CheckCircleOutlined /> 已保存
                </span>
              )}
            </div>
          </div>
        </div>

        <div className="flex-1 min-w-0" />

        <div className="flex items-center gap-2 shrink-0">
          <Dropdown menu={{ items: toolbarSettingsItems }} trigger={['click']}>
            <Tooltip title="工作台设置">
              <Button size="small" icon={<SettingOutlined />} />
            </Tooltip>
          </Dropdown>
          <Tooltip title={prefs.inspectorOpen ? '收起属性面板（P / Ctrl/Cmd+I）' : '展开属性面板（P / Ctrl/Cmd+I）'}>
            <Button
              size="small"
              icon={prefs.inspectorOpen ? <DoubleRightOutlined /> : <DoubleLeftOutlined />}
              onClick={() => setPrefs((p) => ({ ...p, inspectorOpen: !p.inspectorOpen }))}
            />
          </Tooltip>
        </div>
      </div>

      {/* 三栏动态布局 */}
      <Layout
        className="flex-1 min-h-0"
        style={{
          background: 'transparent',
          position: 'relative',
          overflow: 'hidden',
        }}
        onPointerMove={onResizeMove}
        onPointerUp={endResize}
        onPointerCancel={endResize}
      >
        {/* 左侧：分镜列表 */}
        <Sider
          width={prefs.leftWidth}
          collapsedWidth={0}
          className="cs-left flex flex-col"
          style={{
            overflow: 'hidden',
          }}
        >
          <div className="cs-group m-3 mb-2 flex flex-col gap-2 min-w-0">
            <div className="cs-group-title mb-0 flex items-center gap-2 shrink-0">
              <FileTextOutlined /> 分镜列表
            </div>
            <div className="overflow-x-auto min-w-0 -mx-1 px-1">
              <Segmented
                size="small"
                value={filter}
                onChange={(v) => setFilter(v as ShotFilter)}
                options={[
                  { label: `全部 ${shotFilterCounts.all}`, value: 'all' },
                  { label: `待确认 ${shotFilterCounts.pendingConfirm}`, value: 'pendingConfirm' },
                  { label: `生成中 ${shotFilterCounts.generating}`, value: 'generating' },
                  { label: `已就绪 ${shotFilterCounts.ready}`, value: 'ready' },
                  { label: `隐藏 ${shotFilterCounts.hidden}`, value: 'hidden' },
                  { label: `有问题 ${shotFilterCounts.problem}`, value: 'problem' },
                ]}
              />
            </div>
          </div>

          {multiToolbarVisible && (
            <ChapterStudioBatchToolbar
              selectedCount={selectedShotIds.length}
              batchVideoReadinessLoading={batchVideoReadinessLoading}
              generating={generating}
              maintenanceMenuItems={batchMaintenanceMenuItems}
              onBatchInspectVideoReadiness={() => void batchInspectVideoReadiness()}
              onBatchGenerate={() => batchMenuItems.find((item) => item.key === 'generate')?.onClick?.()}
            />
          )}

          {!multiToolbarVisible && selectedShotIds.length === 1 && (
            <div className="cs-group m-3 mt-0 mb-2">
              <div className="rounded-lg border border-solid border-gray-200 bg-white/80 px-3 py-2 text-xs text-gray-600">
                已选 1 项，继续按 <span className="font-medium text-gray-700">Command/Ctrl + 点击</span> 可加入多选
              </div>
            </div>
          )}

          <div className="cs-left-scroll px-3 pb-3">
            {loadingShots ? (
              <div className="text-gray-500 text-center py-4">加载中...</div>
            ) : (
              <div>
                {filteredShots.map((s, i) => {
                  const isActive = selectedShotId === s.id
                  const isSelected = selectedShotIds.includes(s.id)
                  const isDragging = draggingShotId === s.id
                  const isDragOver = dragOverShotId === s.id && draggingShotId && draggingShotId !== s.id
                  const readiness = getShotReadinessFlags(s)
                  const progressCount = getShotProgressCount(s)
                  const primaryHint = getShotPrimaryHint(s)
                  return (
                    <div
                      key={s.id}
                      draggable
                      onDragStart={(e) => {
                        setDraggingShotId(s.id)
                        setDragOverShotId(null)
                        e.dataTransfer.effectAllowed = 'move'
                        e.dataTransfer.setData('text/plain', s.id)
                      }}
                      onDragEnter={() => {
                        if (!draggingShotId || draggingShotId === s.id) return
                        setDragOverShotId(s.id)
                      }}
                      onDragOver={(e) => {
                        e.preventDefault()
                        e.dataTransfer.dropEffect = 'move'
                      }}
                      onDrop={(e) => {
                        e.preventDefault()
                        const sourceId = e.dataTransfer.getData('text/plain') || draggingShotId
                        if (!sourceId) return
                        reorderWithinFilter(sourceId, s.id)
                        setDraggingShotId(null)
                        setDragOverShotId(null)
                      }}
                      onDragEnd={() => {
                        setDraggingShotId(null)
                        setDragOverShotId(null)
                      }}
                      style={{
                        opacity: isDragging ? 0.92 : 1,
                        outline: isDragOver ? '2px dashed var(--ant-color-primary)' : 'none',
                        borderRadius: 8,
                      }}
                    >
                      <Tooltip
                        title={
                          selectedShotIds.length === 0
                            ? 'Command/Ctrl + 点击可多选'
                            : selectedShotIds.length === 1 && !isSelected
                              ? '继续按 Command/Ctrl 点击可加入多选'
                              : undefined
                        }
                        placement="right"
                      >
                        <Dropdown menu={{ items: shotContextMenu(s) }} trigger={['contextMenu']}>
                          <Card
                            size="small"
                            className={[
                              'cs-shot-item mb-2 cursor-pointer transition-colors',
                              isSelected ? 'cs-shot-selected' : '',
                              isActive ? 'cs-shot-active' : '',
                            ].filter(Boolean).join(' ')}
                            style={{
                              opacity: s.hidden ? 0.55 : 1,
                            }}
                            onClick={(e) => handleSelectShot(s.id, i, e)}
                            onDoubleClick={() => {
                              setEditingTitleId(s.id)
                              setEditingTitleValue(s.title)
                            }}
                          >
                            <div className="flex gap-2">
                            <div className="w-16 h-10 rounded bg-gray-200 flex-shrink-0 flex items-center justify-center text-gray-400 text-xs overflow-hidden">
                              <span>16:9</span>
                            </div>
                            <div className="flex-1 min-w-0">
                              <div className="flex items-center gap-2">
                                <span className={`cs-dot ${statusDotClass(s.status)}`} />
                                <span className="text-xs text-gray-500 shrink-0">
                                  {String(s.index).padStart(2, '0')}
                                </span>
                                {editingTitleId === s.id ? (
                                  <Input
                                    size="small"
                                    value={editingTitleValue}
                                    autoFocus
                                    onChange={(ev) => setEditingTitleValue(ev.target.value)}
                                    onBlur={() => {
                                      const nextTitle = editingTitleValue.trim()
                                      setShots((prev) => prev.map((x) => (x.id === s.id ? { ...x, title: nextTitle || x.title } : x)))
                                      if (nextTitle && nextTitle !== s.title) {
                                        void StudioShotsService.updateShotApiV1StudioShotsShotIdPatch({
                                          shotId: s.id,
                                          requestBody: { title: nextTitle },
                                        }).catch(() => message.error('保存标题失败'))
                                      }
                                      setEditingTitleId(null)
                                    }}
                                    onKeyDown={(ev) => {
                                      if (ev.key === 'Enter') {
                                        (ev.currentTarget as HTMLInputElement).blur()
                                      }
                                      if (ev.key === 'Escape') {
                                        setEditingTitleId(null)
                                      }
                                    }}
                                  />
                                ) : (
                                  <div className="font-medium text-sm truncate" title="双击编辑标题">
                                    {s.title}
                                  </div>
                                )}
                              </div>
                              <div className="text-xs text-gray-500 mt-1 truncate">
                                {shotDetail?.movement ? `${CAMERA_MOVEMENT_OPTIONS.find((x) => x.value === shotDetail.movement)?.label ?? shotDetail.movement} · ` : ''}
                                {((shotDurations[s.id] ?? shotDetail?.duration ?? 0) || 0).toFixed(1)}s
                              </div>
                              <div className="cs-shot-progress mt-1">
                                <div className="cs-shot-progress__dots" aria-hidden="true">
                                  {[0, 1].map((idx) => (
                                    <span
                                      key={idx}
                                      className={[
                                        'cs-shot-progress__dot',
                                        idx < progressCount ? 'is-on' : '',
                                      ].join(' ')}
                                    />
                                  ))}
                                </div>
                                <span className="cs-shot-progress__text">{progressCount}/2</span>
                              </div>
                              <div className="cs-shot-hint mt-1">
                                {primaryHint}
                              </div>
                              <div className="mt-1 flex flex-wrap gap-1 items-center">
                                {readiness.isReady ? (
                                  <Tag className="m-0" color="success">已就绪</Tag>
                                ) : readiness.isGenerating ? (
                                  <Tag className="m-0" color="processing">生成中</Tag>
                                ) : (
                                  <Tag className="m-0" color="gold">待确认</Tag>
                                )}
                                {s.skip_extraction && (
                                  <Tag className="m-0" color="cyan">
                                    无需提取
                                  </Tag>
                                )}
                                {s.hasMusic && <Tag icon={<SoundOutlined />} className="m-0" color="default">音乐</Tag>}
                                {statusTag(s.status)}
                                {s.hidden && <Tag icon={<EyeInvisibleOutlined />} className="m-0">隐藏</Tag>}
                                {s.hasProblem && <Tag color="error" className="m-0">有问题</Tag>}
                              </div>
                            </div>
                            </div>
                          </Card>
                        </Dropdown>
                      </Tooltip>
                    </div>
                  )
                })}
              </div>
            )}
          </div>
        </Sider>

        {/* 左侧拖拽条 */}
        <div
          role="separator"
          className="cs-sep h-full"
          style={{
            width: 10,
            cursor: 'col-resize',
            background: 'transparent',
            flexShrink: 0,
          }}
          onPointerDown={(e) => beginResize('left', e)}
          title="拖拽调整左侧宽度"
        />

        {/* 中央：主预览区 */}
        <Content className="cs-main min-w-0 min-h-0 flex flex-col" style={{ padding: 16, position: 'relative', overflow: 'hidden' }}>
          <Card
            title={
              <div className="flex items-center gap-3 min-w-0">
                <span className="font-medium">主预览区</span>
                {selectedShot && (
                  <span className="text-xs text-gray-500 truncate">
                    当前分镜：{String(selectedShot.index).padStart(2, '0')} · {selectedShot.title}
                  </span>
                )}
              </div>
            }
            extra={
              <Space size="small">
                {showPreviewMinimizeButton && (
                  <Tooltip title="最小化预览（占位）">
                    <Button size="small" icon={<DoubleRightOutlined />} onClick={() => message.info('最小化预览（Mock）')} />
                  </Tooltip>
                )}
                <Tooltip title="截取当前帧（Mock）">
                  <Button size="small" icon={<ScissorOutlined />} onClick={() => message.success('已截取当前帧（Mock）')} />
                </Tooltip>
                <Tooltip title={currentPreviewVideoFileId ? '下载当前预览视频' : '暂无可下载视频'}>
                  <Button
                    size="small"
                    icon={<DownloadOutlined />}
                    disabled={!currentPreviewVideoFileId || !currentPreviewVideoUrl}
                    onClick={() => {
                      if (!currentPreviewVideoUrl) return
                      window.open(currentPreviewVideoUrl, '_blank', 'noopener,noreferrer')
                    }}
                  />
                </Tooltip>
              </Space>
            }
            className="cs-preview-card flex-1 min-h-0"
            bodyStyle={{ height: '100%', minHeight: 0, overflow: 'hidden', display: 'flex', flexDirection: 'column', gap: 12 }}
          >
            <div className="flex items-center justify-between gap-2">
              {showPreviewFrameSegmented ? (
                <Segmented
                  size="small"
                  value={frameTab}
                  onChange={(v) => setFrameTab(v as typeof frameTab)}
                  options={[
                    { label: '首帧', value: 'head' },
                    { label: '关键帧列表', value: 'keyframes' },
                    { label: '尾帧', value: 'tail' },
                    { label: '参考对比', value: 'compare' },
                  ]}
                />
              ) : (
                <div />
              )}
              <Space size="small">
                <Select
                  size="small"
                  value={playbackRate}
                  style={{ width: 86 }}
                  onChange={(v) => setPlaybackRate(v)}
                  options={[0.5, 1, 1.25, 1.5, 2].map((v) => ({ label: `${v}x`, value: v }))}
                />
                <Tooltip title="循环当前分镜">
                  <Switch size="small" checked={loopCurrent} onChange={setLoopCurrent} />
                </Tooltip>
                <Space size={4} className="max-w-[320px]">
                  <Radio.Group
                    size="small"
                    buttonStyle="solid"
                    disabled={!currentFrameFileId || frameFileTagsLoading}
                    value={currentFrameFileTags.includes(FRAME_FILE_TAG_ADOPT) ? FRAME_FILE_TAG_ADOPT : currentFrameFileTags.includes(FRAME_FILE_TAG_ABANDON) ? FRAME_FILE_TAG_ABANDON : ''}
                    onChange={(e) => {
                      const v = String(e?.target?.value ?? '')
                      const base = currentFrameFileTags.filter((t) => t !== FRAME_FILE_TAG_ADOPT && t !== FRAME_FILE_TAG_ABANDON)
                      if (!v) void updateCurrentFrameFileTags(base)
                      else void updateCurrentFrameFileTags([v, ...base])
                    }}
                  >
                    <Radio.Button value={FRAME_FILE_TAG_ADOPT}>采用</Radio.Button>
                    <Radio.Button value={FRAME_FILE_TAG_ABANDON}>废弃</Radio.Button>
                  </Radio.Group>
                  <Select
                    mode="tags"
                    size="small"
                    style={{ minWidth: 160, maxWidth: 220 }}
                    placeholder="自定义标签"
                    disabled={!currentFrameFileId || frameFileTagsLoading}
                    loading={frameFileTagsLoading}
                    value={currentFrameFileTags.filter((t) => t !== FRAME_FILE_TAG_ADOPT && t !== FRAME_FILE_TAG_ABANDON)}
                    onChange={(vals) => {
                      const base = Array.isArray(vals) ? (vals as any[]).map((v) => String(v)) : []
                      const keep =
                        currentFrameFileTags.find((t) => t === FRAME_FILE_TAG_ADOPT || t === FRAME_FILE_TAG_ABANDON) ?? null
                      void updateCurrentFrameFileTags(keep ? [keep, ...base] : base)
                    }}
                  />
                </Space>
                <Tooltip title="当前镜头数据">
                  <Tag className="m-0">
                    帧图 {frameImages.length} · 关联 {sceneLinks.length + actorImageLinks.length + propLinks.length + costumeLinks.length}
                  </Tag>
                </Tooltip>
              </Space>
            </div>

            <div className="flex-1 min-h-0 overflow-auto flex flex-col gap-8 pr-1">
              <div className="relative">
                <div className="cs-player-shell">
                  <div className="aspect-video bg-black rounded overflow-hidden flex items-center justify-center">
                  {/* Mock：没有真实视频源时仍可展示播放器结构 */}
                  <video
                    ref={videoRef}
                    className="w-full h-full object-contain"
                    controls={false}
                    muted
                    playsInline
                    preload="metadata"
                    src={currentPreviewVideoUrl || undefined}
                  />
                  {!selectedShot && (
                    <div className="absolute inset-0 flex items-center justify-center text-gray-400">
                      请选择分镜
                    </div>
                  )}
                  {selectedShot && !currentPreviewVideoUrl && selectedShot.status !== 'ready' && (
                    <div className="absolute inset-0 flex items-center justify-center">
                      <Badge
                        status={shotRuntimeMap[selectedShot.id]?.has_active_tasks ? 'processing' : 'default'}
                        text={shotRuntimeMap[selectedShot.id]?.has_active_tasks ? '生成中…' : '未生成'}
                      />
                    </div>
                  )}
                  </div>
                </div>

                {/* 播放控制条 */}
                <div className="mt-2 flex items-center gap-2">
                  <Button
                    size="small"
                    icon={<CaretLeftOutlined />}
                    onClick={() => message.info('帧退（Mock）')}
                  />
                  <Button
                    size="small"
                    type="primary"
                    icon={isPlaying ? <PauseCircleOutlined /> : <PlayCircleOutlined />}
                    onClick={() => {
                      const v = videoRef.current
                      if (!v) return
                      if (v.paused) void v.play()
                      else v.pause()
                    }}
                  >
                    {isPlaying ? '暂停' : '播放'}
                  </Button>
                  <Button
                    size="small"
                    icon={<CaretRightOutlined />}
                    onClick={() => message.info('帧进（Mock）')}
                  />
                  <div className="flex-1 min-w-0">
                    <Slider
                      tooltip={{ formatter: null }}
                      min={0}
                      max={Math.max(1, videoDuration || shotDetail?.duration || (selectedShotId ? shotDurations[selectedShotId] : 0) || 1)}
                      value={videoTime}
                      onChange={(v) => {
                        const vv = videoRef.current
                        if (!vv) return
                        vv.currentTime = Number(v)
                        setVideoTime(Number(v))
                      }}
                    />
                  </div>
                  <div className="text-xs text-gray-400 w-[110px] text-right">
                    {videoTime.toFixed(1)} / {Math.max(videoDuration || 0, shotDetail?.duration || (selectedShotId ? shotDurations[selectedShotId] : 0) || 0).toFixed(1)}s
                  </div>
                </div>

                {/* 对白字幕条 */}
                <div className="cs-subtitle mt-2 px-3 py-2">
                  {subtitleLines.length === 0 ? (
                    <div className="text-sm opacity-80">暂无对白字幕</div>
                  ) : (
                    <div className="flex flex-col gap-1">
                      {subtitleLines.map((l, idx) => {
                        const active = idx === activeSubtitleIndex
                        return (
                          <div
                            key={l.key}
                            className="cs-sub-line text-sm cursor-pointer"
                            style={{ opacity: active ? 1 : 0.6, fontWeight: active ? 600 : 400 }}
                            onClick={() => {
                              const v = videoRef.current
                              if (!v) return
                              v.currentTime = l.start
                              setVideoTime(l.start)
                            }}
                          >
                            <span style={{ opacity: 0.9 }}>{l.role}：</span>
                            <span>{l.text}</span>
                          </div>
                        )
                      })}
                    </div>
                  )}
                </div>
              </div>
            </div>

            {/* 章节级时间轴（可折叠，固定在底部不参与滚动） */}
            {showChapterTimeline && (
              <div
                className="rounded border border-solid border-gray-200 flex-shrink-0 min-h-0 flex flex-col"
                style={{ background: 'var(--ant-color-bg-container)' }}
              >
                <div className="px-3 py-2 flex items-center justify-between flex-shrink-0">
                  <div className="text-sm font-medium">章节时间轴</div>
                  <Button
                    size="small"
                    type="text"
                    onClick={() => setPrefs((p) => ({ ...p, timelineCollapsed: !p.timelineCollapsed }))}
                  >
                    {prefs.timelineCollapsed ? '展开' : '折叠'}
                  </Button>
                </div>
                {!prefs.timelineCollapsed && (
                  <div className="px-3 pb-3 flex-shrink-0 overflow-hidden">
                    <div className="flex items-center gap-2 overflow-x-auto py-1 min-h-[32px]">
                      {shots
                        .slice()
                        .sort((a, b) => a.index - b.index)
                        .filter((s) => !s.hidden)
                        .map((s) => {
                          const active = s.id === selectedShotId
                          return (
                            <div
                              key={s.id}
                              className="shrink-0 cursor-pointer rounded"
                              style={{
                                width: clamp(18 + ((shotDurations[s.id] ?? 1) || 1) * 6, 24, 96),
                                height: 14,
                                background:
                                  shotRuntimeMap[s.id]?.has_active_tasks
                                    ? 'rgba(59,130,246,0.45)'
                                    : s.status === 'ready'
                                    ? 'rgba(34,197,94,0.45)'
                                    : 'rgba(156,163,175,0.45)',
                                outline: active ? '2px solid var(--ant-color-primary)' : '1px solid rgba(0,0,0,0.06)',
                              }}
                              title={`${String(s.index).padStart(2, '0')} · ${s.title}`}
                              onClick={() => setSelectedShotId(s.id)}
                            />
                          )
                        })}
                    </div>
                    <div className="text-xs text-gray-500 mt-1">
                      点击条块跳转分镜；隐藏分镜不参与预览
                    </div>
                  </div>
                )}
              </div>
            )}
          </Card>
        </Content>

        {/* 右侧：属性面板（推挤 / 覆盖） */}
        {prefs.inspectorMode === 'push' ? (
          <>
            {/* 右侧拖拽条（推挤模式） */}
            {prefs.inspectorOpen && (
              <div
                role="separator"
                className="cs-sep cs-sep-strong h-full"
                style={{
                  width: 10,
                  cursor: 'col-resize',
                  background: 'transparent',
                  flexShrink: 0,
                }}
                onPointerDown={(e) => beginResize('right', e)}
                title="拖拽调整属性面板宽度"
              />
            )}
            <Sider
              width={prefs.inspectorOpen ? prefs.rightWidth : 0}
              collapsedWidth={0}
              collapsed={!prefs.inspectorOpen}
              className="cs-right"
              style={{
                overflow: 'hidden',
              }}
            >
              <Inspector
                projectId={projectId}
                chapterId={chapterId}
                projectVisualStyle={projectVisualStyle}
                projectStyle={projectStyle}
                projectDefaultVideoRatio={projectDefaultVideoRatio}
                capabilityDefaultVideoRatio={capabilityDefaultVideoRatio}
                videoRatioOptions={videoRatioOptions}
                imageGenerationOptions={imageGenerationOptions}
                keyframeResolutionProfile={keyframeResolutionProfile}
                onChangeKeyframeResolutionProfile={setKeyframeResolutionProfile}
                loadingDetail={loadingDetail}
                shotDetail={shotDetail}
                dialogLines={dialogLines}
                frameImages={frameImages}
                sceneLinks={sceneLinks}
                propLinks={propLinks}
                costumeLinks={costumeLinks}
                shotCharacterLinks={shotCharacterLinks}
                shotCandidateItems={shotCandidateItems}
                shotDialogueCandidateItems={shotDialogueCandidateItems}
                cameraUpdating={cameraUpdating}
                promptAssetsUpdating={promptAssetsUpdating}
                onDeleteDialogLine={deleteDialogLine}
                onUpdatePromptScene={updatePromptScene}
                onUpdatePromptActors={updatePromptActors}
                onUpdatePromptProps={updatePromptProps}
                onUpdatePromptCostumes={updatePromptCostumes}
                selectedShot={selectedShot}
                onUpdateShotTitle={updateShotTitleInOps}
                onUpdateShotScriptExcerpt={updateShotScriptExcerptInOps}
                onDeleteShotOps={deleteShotFromOps}
                onPatchShotDetail={patchShotDetailLocal}
                onPatchShotDetailImmediate={patchShotDetailImmediate}
                onSelectPreviewVideo={setPreviewVideoFileId}
                onRefreshShotFrameImages={refreshShotFrameImages}
                onClose={() => setPrefs((p) => ({ ...p, inspectorOpen: false }))}
              />
            </Sider>

            {!prefs.inspectorOpen && (
              <div
                className="cs-right-strip"
                onClick={() => setPrefs((p) => ({ ...p, inspectorOpen: true }))}
                title="展开属性面板（P / Ctrl/Cmd+I）"
              >
                <span>属性</span>
              </div>
            )}
          </>
        ) : (
          <>
            {/* 覆盖模式：右侧抽屉覆盖中央 */}
            {prefs.inspectorOpen && (
              <div
                className="absolute top-0 right-0 h-full"
                style={{
                  width: prefs.rightWidth,
                  background: '#f9fafc',
                  borderLeft: '2px solid #cbd5e1',
                  zIndex: 20,
                  boxShadow: '-4px 0 12px rgba(0,0,0,0.06)',
                  display: 'flex',
                  flexDirection: 'row',
                }}
              >
                <div
                  role="separator"
                  className="cs-sep cs-sep-strong"
                  style={{ width: 10, flexShrink: 0 }}
                  onPointerDown={(e) => beginResize('right', e)}
                  title="拖拽调整覆盖宽度"
                />
                <div className="flex-1 min-w-0 overflow-hidden">
                  <Inspector
                    projectId={projectId}
                    chapterId={chapterId}
                    projectVisualStyle={projectVisualStyle}
                    projectStyle={projectStyle}
                    projectDefaultVideoRatio={projectDefaultVideoRatio}
                    capabilityDefaultVideoRatio={capabilityDefaultVideoRatio}
                    videoRatioOptions={videoRatioOptions}
                    imageGenerationOptions={imageGenerationOptions}
                    keyframeResolutionProfile={keyframeResolutionProfile}
                    onChangeKeyframeResolutionProfile={setKeyframeResolutionProfile}
                    loadingDetail={loadingDetail}
                    shotDetail={shotDetail}
                    dialogLines={dialogLines}
                    frameImages={frameImages}
                    sceneLinks={sceneLinks}
                    propLinks={propLinks}
                    costumeLinks={costumeLinks}
                    shotCharacterLinks={shotCharacterLinks}
                    shotCandidateItems={shotCandidateItems}
                    shotDialogueCandidateItems={shotDialogueCandidateItems}
                    cameraUpdating={cameraUpdating}
                    promptAssetsUpdating={promptAssetsUpdating}
                    onDeleteDialogLine={deleteDialogLine}
                    onUpdatePromptScene={updatePromptScene}
                    onUpdatePromptActors={updatePromptActors}
                    onUpdatePromptProps={updatePromptProps}
                    onUpdatePromptCostumes={updatePromptCostumes}
                    selectedShot={selectedShot}
                    onUpdateShotTitle={updateShotTitleInOps}
                    onUpdateShotScriptExcerpt={updateShotScriptExcerptInOps}
                    onDeleteShotOps={deleteShotFromOps}
                    onPatchShotDetail={patchShotDetailLocal}
                    onPatchShotDetailImmediate={patchShotDetailImmediate}
                    onSelectPreviewVideo={setPreviewVideoFileId}
                    onRefreshShotFrameImages={refreshShotFrameImages}
                    onClose={() => setPrefs((p) => ({ ...p, inspectorOpen: false }))}
                  />
                </div>
              </div>
            )}

            {/* 覆盖模式下，右侧边缘常驻开关 */}
            <Tooltip title={prefs.inspectorOpen ? '收起属性面板' : '展开属性面板'}>
              <Button
                size="small"
                className="absolute top-1/2 -translate-y-1/2"
                style={{ right: 4, zIndex: 30 }}
                icon={prefs.inspectorOpen ? <DoubleRightOutlined /> : <DoubleLeftOutlined />}
                onClick={() => setPrefs((p) => ({ ...p, inspectorOpen: !p.inspectorOpen }))}
              />
            </Tooltip>
          </>
        )}

        <Modal
          title={`批量视频准备度（${selectedShots.length} 条）`}
          open={batchVideoReadinessOpen}
          onCancel={() => {
            if (batchVideoReadinessLoading) return
            setBatchVideoReadinessOpen(false)
          }}
          footer={[
            <Button key="close" onClick={() => setBatchVideoReadinessOpen(false)} disabled={batchVideoReadinessLoading}>
              关闭
            </Button>,
            <Button
              key="refresh"
              type="primary"
              icon={<VideoCameraOutlined />}
              loading={batchVideoReadinessLoading}
              onClick={() => void batchInspectVideoReadiness()}
            >
              重新检查
            </Button>,
          ]}
          width={880}
          destroyOnClose={false}
        >
          {batchVideoReadinessLoading ? (
            <div className="py-10 text-center">
              <Spin />
            </div>
          ) : batchVideoReadinessItems.length === 0 ? (
            <div className="text-sm text-gray-500">暂无批量视频准备度结果</div>
          ) : (
            <div className="space-y-3 max-h-[65vh] overflow-y-auto pr-1">
              <div className="text-xs text-gray-500">
                当前按 <Tag className="!mx-1">text_only</Tag> 参考模式检查这批分镜是否具备视频生成条件。
              </div>
              {batchVideoReadinessItems.map(({ shot, readiness, error }) => {
                const failedChecks = (readiness?.checks ?? []).filter((item) => !item.ok)
                return (
                  <div key={shot.id} className="rounded-lg border border-solid border-gray-200 bg-white px-4 py-3">
                    <div className="flex items-start justify-between gap-3">
                      <div className="min-w-0">
                        <div className="text-sm font-medium truncate">
                          {String(shot.index).padStart(2, '0')} · {shot.title}
                        </div>
                        <div className="text-xs text-gray-500 mt-1">
                          {error
                            ? error
                            : readiness?.ready
                              ? '当前镜头已满足视频生成条件。'
                              : `当前镜头还有 ${failedChecks.length} 项待补齐。`}
                        </div>
                      </div>
                      <Tag color={error ? 'red' : readiness?.ready ? 'green' : 'gold'}>
                        {error ? '检查失败' : readiness?.ready ? '可生成' : '待补齐'}
                      </Tag>
                    </div>
                    {!error ? (
                      <div className="mt-3 flex flex-wrap gap-2">
                        {(readiness?.checks ?? []).map((check) => (
                          <Tooltip key={check.key} title={check.message}>
                            <Tag color={check.ok ? 'green' : 'default'}>
                              {check.ok ? '通过' : '未通过'} · {check.key}
                            </Tag>
                          </Tooltip>
                        ))}
                      </div>
                    ) : null}
                    {!error && failedChecks.length > 0 ? (
                      <div className="mt-3 space-y-1">
                        {failedChecks.map((check) => (
                          <div key={check.key} className="text-xs text-gray-600">
                            • {check.message}
                          </div>
                        ))}
                      </div>
                    ) : null}
                  </div>
                )
              })}
            </div>
          )}
        </Modal>
      </Layout>
    </div>
  )
}

export default ChapterStudio

