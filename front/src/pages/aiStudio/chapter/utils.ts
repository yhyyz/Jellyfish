import type { ChapterRead, ImageGenerationOptionsRead } from '../../../services/generated'
import type { Chapter } from '../../../mocks/data'
import type { GenerationDraftState } from '../hooks/useGenerationDraft'
import type { RelationTaskState } from '../project/ProjectWorkbench/chapterDivisionTasks'
import type { KeyframeResolutionProfile, ShotFramePromptDebugContext } from './types'

const FRAME_FILE_TAG_ADOPT = '采用'
const FRAME_FILE_TAG_ABANDON = '废弃'

export function normalizeFrameExclusiveTags(tags: string[]): string[] {
  const cleaned = (tags || []).map((x) => String(x ?? '').trim()).filter(Boolean)
  const hasAdopt = cleaned.includes(FRAME_FILE_TAG_ADOPT)
  const hasAbandon = cleaned.includes(FRAME_FILE_TAG_ABANDON)
  const rest = cleaned.filter((t) => t !== FRAME_FILE_TAG_ADOPT && t !== FRAME_FILE_TAG_ABANDON)
  if (hasAdopt && !hasAbandon) return [FRAME_FILE_TAG_ADOPT, ...rest]
  if (!hasAdopt && hasAbandon) return [FRAME_FILE_TAG_ABANDON, ...rest]
  // 两者都没有或同时存在：同时存在时默认保留"采用"
  if (hasAdopt && hasAbandon) return [FRAME_FILE_TAG_ADOPT, ...rest]
  return rest
}

export function readDebugContextText(
  context: ShotFramePromptDebugContext | null,
  key: string,
): string {
  if (!context) return ''
  const value = context[key]
  return typeof value === 'string' ? value.trim() : ''
}

export function buildKeyframeGuidanceSummary(items: string[]): string[] {
  const result: string[] = []
  const seen = new Set<string>()
  items
    .flatMap((item) => item.split('；'))
    .map((item) => item.trim())
    .filter(Boolean)
    .forEach((item) => {
      if (seen.has(item)) return
      seen.add(item)
      result.push(item)
    })
  return result
}

export function stripDirectiveLevelPrefix(item: string): string {
  const text = String(item || '').trim()
  if (text.startsWith('必须：')) return text.slice(3).trim()
  if (text.startsWith('优先：')) return text.slice(3).trim()
  return text
}

export function parseDirectorCommandSummary(summary: string): Array<{
  level: 'must' | 'prefer'
  text: string
}> {
  return String(summary || '')
    .split('；')
    .map((item) => item.trim())
    .filter(Boolean)
    .map((item) => {
      if (item.startsWith('必须：')) {
        return { level: 'must' as const, text: item.slice(3).trim() }
      }
      if (item.startsWith('优先：')) {
        return { level: 'prefer' as const, text: item.slice(3).trim() }
      }
      return { level: 'prefer' as const, text: item }
    })
}

export function buildGuidanceLevelSummary(
  parsedDirectorCommands: Array<{ level: 'must' | 'prefer'; text: string }>,
  guidanceSummary: string[],
): { must: number; prefer: number; normal: number } {
  const must = parsedDirectorCommands.filter((item) => item.level === 'must').length
  const prefer = parsedDirectorCommands.filter((item) => item.level === 'prefer').length
  const parsedTexts = new Set(parsedDirectorCommands.map((item) => item.text.trim()).filter(Boolean))
  const normal = guidanceSummary
    .map((item) => stripDirectiveLevelPrefix(item))
    .filter((item) => item && !parsedTexts.has(item)).length
  return { must, prefer, normal }
}

export function buildActionBeatPhaseTags(summary: string): Array<{ text: string; phaseLabel: string }> {
  return String(summary || '')
    .split('；')
    .map((item) => item.trim())
    .filter(Boolean)
    .map((item) => {
      const matched = item.match(/^\d+\.\s*(触发|峰值|收束)\s*·\s*(.+)$/)
      if (!matched) {
        return { phaseLabel: '阶段', text: item }
      }
      return {
        phaseLabel: matched[1],
        text: matched[2].trim(),
      }
    })
}

export function clamp(n: number, min: number, max: number) {
  return Math.max(min, Math.min(max, n))
}

export function sleep(ms: number) {
  return new Promise((resolve) => window.setTimeout(resolve, ms))
}

export function getResolutionProfileLabel(profile: KeyframeResolutionProfile): string {
  return profile === 'high' ? '高清（3K）' : '标准（2K）'
}

export function resolveKeyframePixelSize(
  options: ImageGenerationOptionsRead | null,
  ratio: string,
  profile: KeyframeResolutionProfile,
): string {
  const normalizedRatio = String(ratio ?? '').trim()
  if (!options || !normalizedRatio) return ''
  const profiles = options.ratio_size_profiles?.[normalizedRatio] ?? null
  if (!profiles) return ''
  return profiles[profile] ?? profiles.standard ?? ''
}

export function mapGenerationDraftStateToRenderState(
  state: GenerationDraftState,
): 'idle' | 'stale' | 'syncing' | 'clean' | 'error' {
  if (state === 'derived' || state === 'submitted') return 'clean'
  if (state === 'deriving' || state === 'submitting') return 'syncing'
  if (state === 'draft_changed' || state === 'context_changed') return 'stale'
  if (state === 'error') return 'error'
  return 'idle'
}

export function getKeyframeRenderStatusMeta(state: GenerationDraftState) {
  const renderState = mapGenerationDraftStateToRenderState(state)
  if (renderState === 'clean') {
    return {
      color: 'green' as const,
      label: '已同步',
      description: '当前最终提示词已与基础提示词和参考图顺序保持一致。',
    }
  }
  if (renderState === 'syncing') {
    return {
      color: 'blue' as const,
      label: '同步中',
      description: '正在根据当前基础提示词和参考图顺序更新最终提示词…',
    }
  }
  if (renderState === 'error') {
    return {
      color: 'red' as const,
      label: '同步失败',
      description: '自动更新失败，请重试。若问题持续存在，请检查基础提示词和参考图。',
    }
  }
  if (renderState === 'idle') {
    return {
      color: 'default' as const,
      label: '待生成',
      description: '请先输入基础提示词，系统会自动生成最终提示词。',
    }
  }
  return {
    color: 'gold' as const,
    label: '待同步',
    description: '基础提示词或参考图顺序已变化，最终提示词正在等待更新。',
  }
}

export function applyTaskCancelState(
  currentTask: RelationTaskState | null,
  data?: { task_id?: string | null; status?: string | null; cancel_requested?: boolean | null } | null,
): RelationTaskState | null {
  if (!currentTask) return null
  return {
    ...currentTask,
    taskId: data?.task_id || currentTask.taskId,
    status: (data?.status ?? currentTask.status) as RelationTaskState['status'],
    cancelRequested: data?.cancel_requested ?? true,
  }
}

export function reorder<T>(list: T[], startIndex: number, endIndex: number) {
  const result = [...list]
  const [removed] = result.splice(startIndex, 1)
  result.splice(endIndex, 0, removed)
  return result
}

export function normalizeAssetName(value?: string | null) {
  return String(value ?? '').trim().toLowerCase()
}

export function uniqueNames(values: Array<string | null | undefined>) {
  const seen = new Set<string>()
  const result: string[] = []
  values.forEach((value) => {
    const raw = String(value ?? '').trim()
    if (!raw) return
    const key = normalizeAssetName(raw)
    if (!key || seen.has(key)) return
    seen.add(key)
    result.push(raw)
  })
  return result
}

export function isTypingTarget(target: EventTarget | null) {
  if (!(target instanceof HTMLElement)) return false
  const tag = target.tagName.toLowerCase()
  if (tag === 'input' || tag === 'textarea' || tag === 'select') return true
  if (target.isContentEditable) return true
  return Boolean(target.closest('[contenteditable="true"]'))
}

export function toUIChapter(c: ChapterRead): Chapter {
  return {
    id: c.id,
    projectId: c.project_id,
    index: c.index,
    title: c.title,
    summary: c.summary ?? '',
    storyboardCount: c.shot_count ?? c.storyboard_count ?? 0,
    status: c.status ?? 'draft',
    updatedAt: new Date().toISOString(),
  }
}
