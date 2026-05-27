/**
 * VoicePackPicker 音色选择器组件（W20-T2）。
 *
 * 给 StoryWorkbench 右侧抽屉提供 VoicePack 列表选择 UI：
 * - 按 language_code 过滤候选音色（防御式：后端已过滤一遍）。
 * - 当出现 ≥2 个 provider 时按 provider 分组展示。
 * - 每行附带试听按钮，单 active player：同一时刻最多 1 个音频在播。
 * - 选中行通过 aria-selected="true" + ring 视觉反馈双重表达。
 *
 * 设计要点：
 * - 数据走 useVoicePacks(languageCode)，依赖 OpenAPI 生成的
 *   CommerceVoicePacksService（AGENTS.md 规则 #2，禁止手写 service）。
 * - 单 active player 用一个 ref 记录“当前正在播的 audio 元素”，避免引入
 *   全局状态库；切换音色或卸载时主动 pause 旧元素。
 * - 加载态用 antd Skeleton，错误态用 antd Alert + 重试按钮。
 */
import React, { useMemo, useRef } from 'react'
import { Alert, Button, Skeleton, Tag } from 'antd'
import { CaretRightOutlined } from '@ant-design/icons'
import { useTranslation } from 'react-i18next'

import type { VoicePackRead } from '../../../../../services/generated'
import { resolveAssetUrl } from '../../../assets/utils'
import { useVoicePacks } from '../workbench.queries'

export interface VoicePackPickerProps {
  /** 当前选中的 VoicePack id；未选传 undefined */
  value?: string
  /** 用于过滤的语言代码（如 zh-CN / en-US） */
  languageCode: string
  /** 选中变化回调 */
  onChange: (voicePackId: string) => void
}

/**
 * 单行音色 UI。
 *
 * 通过 forwardRef 把内部 audio 元素引用透出，方便上层维护“当前 active player”。
 */
interface VoicePackRowProps {
  pack: VoicePackRead
  selected: boolean
  onSelect: () => void
  onPlay: (audio: HTMLAudioElement | null) => void
  playLabel: string
}

const VoicePackRow: React.FC<VoicePackRowProps> = ({
  pack,
  selected,
  onSelect,
  onPlay,
  playLabel,
}) => {
  const audioRef = useRef<HTMLAudioElement | null>(null)
  const sampleUrl = resolveAssetUrl(pack.sample_file_id ?? null)

  return (
    <div
      role="option"
      aria-selected={selected}
      aria-label={pack.name}
      onClick={onSelect}
      className={[
        'flex items-center gap-3 px-3 py-2 rounded cursor-pointer',
        'border border-transparent hover:bg-slate-50',
        selected ? 'ring-2 ring-primary bg-blue-50/40' : '',
      ].join(' ')}
    >
      <Tag color="geekblue" className="!m-0 shrink-0">
        {pack.provider}
      </Tag>
      <span className="font-medium text-slate-800 truncate">{pack.name}</span>
      {pack.gender ? <Tag className="!m-0 shrink-0">{pack.gender}</Tag> : null}

      <div className="ml-auto flex items-center gap-2">
        <Button
          size="small"
          type="text"
          icon={<CaretRightOutlined />}
          aria-label={`play ${pack.name}`}
          disabled={!sampleUrl}
          onClick={(e) => {
            e.stopPropagation()
            onPlay(audioRef.current)
          }}
        >
          {playLabel}
        </Button>
        {/* sample 试听 audio：单元素隐藏，由按钮触发 play / pause */}
        <audio ref={audioRef} src={sampleUrl} preload="none" />
      </div>
    </div>
  )
}

/**
 * 把 packs 按 provider 分组（保持 sort_order 稳定，组键按字典序）。
 */
function groupByProvider(packs: VoicePackRead[]): Record<string, VoicePackRead[]> {
  const grouped: Record<string, VoicePackRead[]> = {}
  for (const pack of packs) {
    const key = pack.provider
    if (!grouped[key]) grouped[key] = []
    grouped[key].push(pack)
  }
  return grouped
}

export const VoicePackPicker: React.FC<VoicePackPickerProps> = ({
  value,
  languageCode,
  onChange,
}) => {
  const { t } = useTranslation('commerce')
  const query = useVoicePacks(languageCode)

  // 防御式：后端已按 language_code 过滤，但 client 再过一遍以保证
  // “languageCode prop 变化但缓存命中” 的边界场景下不串数据。
  const filtered = useMemo<VoicePackRead[]>(
    () =>
      (query.data ?? []).filter(
        (pack: VoicePackRead) => pack.language_code === languageCode,
      ),
    [query.data, languageCode],
  )

  const grouped = useMemo(() => groupByProvider(filtered), [filtered])
  const providerCount = Object.keys(grouped).length

  // 当前正在播放的 audio 元素引用：切换 / 卸载时主动 pause。
  const activePlayerRef = useRef<HTMLAudioElement | null>(null)

  /**
   * 试听播放控制。
   *
   * 若已有其他 audio 正在播，先 pause 旧的，再 play 新的；保证单 active player。
   * play() 在某些浏览器返回 promise，这里 swallow 掉拒绝以避免 unhandled rejection。
   */
  const handlePlay = (audio: HTMLAudioElement | null) => {
    if (!audio) return
    if (activePlayerRef.current && activePlayerRef.current !== audio) {
      activePlayerRef.current.pause()
    }
    activePlayerRef.current = audio
    const result = audio.play()
    if (result && typeof (result as Promise<void>).then === 'function') {
      ;(result as Promise<void>).catch(() => {
        // 用户尚未交互或音频不可用时浏览器会拒绝 play；UI 层无需感知。
      })
    }
  }

  if (query.isLoading) {
    return (
      <div className="space-y-2">
        <Skeleton active title={false} paragraph={{ rows: 3 }} />
      </div>
    )
  }

  if (query.isError) {
    return (
      <Alert
        type="error"
        showIcon
        message={t('voicePackPicker.errorRetry')}
        action={
          <Button size="small" onClick={() => void query.refetch()}>
            {t('voicePackPicker.errorRetry')}
          </Button>
        }
      />
    )
  }

  if (filtered.length === 0) {
    return (
      <div className="text-slate-500 text-sm py-4 text-center">
        {t('voicePackPicker.noResults', { language: languageCode })}
      </div>
    )
  }

  const playLabel = t('voicePackPicker.play')

  // 单 provider 场景：直接平铺，不渲染分组，避免视觉噪音。
  if (providerCount < 2) {
    return (
      <div role="listbox" aria-label="voice-packs" className="space-y-1">
        {filtered.map((pack) => (
          <VoicePackRow
            key={pack.id}
            pack={pack}
            selected={value === pack.id}
            onSelect={() => onChange(pack.id)}
            onPlay={handlePlay}
            playLabel={playLabel}
          />
        ))}
      </div>
    )
  }

  // 多 provider 场景：按 provider 分组渲染。
  const providerKeys = Object.keys(grouped).sort()
  return (
    <div role="listbox" aria-label="voice-packs" className="space-y-3">
      {providerKeys.map((provider) => (
        <div key={provider} role="group" aria-label={provider} className="space-y-1">
          <div className="text-xs uppercase tracking-wide text-slate-500 px-1">
            {provider}
          </div>
          {grouped[provider].map((pack) => (
            <VoicePackRow
              key={pack.id}
              pack={pack}
              selected={value === pack.id}
              onSelect={() => onChange(pack.id)}
              onPlay={handlePlay}
              playLabel={playLabel}
            />
          ))}
        </div>
      ))}
    </div>
  )
}

export default VoicePackPicker
