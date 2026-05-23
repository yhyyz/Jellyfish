import type {
  ShotFramePromptMappingRead,
  ShotRead,
  ShotVideoPromptPackRead,
} from '../../../services/generated'

export type ShotFramePromptDebugContext = Record<string, unknown>
export type ShotFramePromptQualityChecks = {
  passed: boolean
  issues: string[]
} | null
export type FramePromptDerived = {
  basePrompt: string
  renderedPrompt: string
  selectedGuidance: string[]
  droppedGuidance: string[]
  selectedGuidanceDetails: Array<{ text: string; category: string; reasonTag: string; reason: string }>
  droppedGuidanceDetails: Array<{ text: string; category: string; reasonTag: string; reason: string }>
  images: string[]
  mappings: ShotFramePromptMappingRead[]
}
export type VideoReferenceMode = 'first' | 'last' | 'key' | 'first_last' | 'first_last_key' | 'text_only'
export type VideoPromptDerived = {
  prompt: string
  images: string[]
  pack: ShotVideoPromptPackRead | null
}

export type InspectorMode = 'push' | 'overlay'
export type ShotFilter = 'all' | 'pendingConfirm' | 'generating' | 'ready' | 'hidden' | 'problem'

export type StudioShot = ShotRead & {
  hidden?: boolean
  hasProblem?: boolean
  hasSpeech?: boolean
  hasMusic?: boolean
}

export type ShotRuntimeState = {
  has_active_tasks: boolean
  has_active_video_tasks: boolean
  has_active_prompt_tasks: boolean
  has_active_frame_tasks: boolean
  active_task_count: number
}

export type LayoutPrefs = {
  leftWidth: number
  rightWidth: number
  inspectorOpen: boolean
  inspectorMode: InspectorMode
  autoOpenInspector: boolean
  timelineCollapsed: boolean
}

export type KeyframeCardState = {
  loading: boolean
  taskStatus: string | null
  taskId: string | null
  thumbs: Array<{ linkId: number; fileId: string; thumbUrl: string }>
  modalOpen: boolean
  applyingFileId: string | null
}

export type KeyframeResolutionProfile = 'standard' | 'high'

export type InspectorTabKey = 'ops' | 'camera' | 'prompt_image' | 'dialogue' | 'keyframe_gen' | 'gen_ref'

export type PromptFrameType = 'first' | 'key' | 'last'
