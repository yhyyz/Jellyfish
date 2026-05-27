/**
 * VoicePackLibrary — 商品音色库浏览页（W20-T5）。
 *
 * 页面定位：
 * - 系统级 / 用户级 VoicePack 的**只读浏览面板**，给商品视频生成提供候选音色目录。
 * - 编辑、删除、训练等管理能力 W20 不开放，定制能力以 stub 弹窗占位（敬请期待）。
 *
 * 数据 & 交互：
 * - 列表数据走 `useVoicePacks(languageCode)`，底层封装 OpenAPI 生成的
 *   `CommerceVoicePacksService`（AGENTS.md 规则 #2，禁止手写 service）。
 * - 顶部工具栏：language 下拉（zh-CN / en-US）+ 上传定制音色按钮。
 *   下拉切换会驱动 query key 变化、自动 refetch 对应语言的列表。
 * - 主体：3 列响应式 grid（Tailwind grid-cols-1 / md:grid-cols-2 / lg:grid-cols-3），
 *   每张卡片展示 provider tag + name + gender tag + 试听按钮。
 * - 试听沿用 W20-T2 VoicePackPicker 的「单 active player」语义：同一时刻最多 1 个
 *   audio 元素在播；切换或卸载时主动 pause 旧元素。
 *
 * 状态：
 * - loading → antd Skeleton；error → antd Alert + 重试按钮；空集合 → antd Empty。
 *
 * 路由：
 * - W20-T5 仅产出页面文件；路由注册（/commerce/voice-packs）由 W20-T7 统一接入。
 */
import React, { useMemo, useRef, useState } from 'react'
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
import { CaretRightOutlined, UploadOutlined } from '@ant-design/icons'
import { useTranslation } from 'react-i18next'

import type { VoicePackRead } from '../../../../services/generated'
import { ScrollablePage } from '../../components/ScrollablePage'
import { resolveAssetUrl } from '../../assets/utils'
import { useVoicePacks } from '../projects/workbench.queries'
import { VoicePackUploadModal } from './VoicePackUploadModal'

/**
 * language 过滤候选；保持与后端 seed VoicePack 的 language_code 对齐。
 */
const LANGUAGE_OPTIONS = [
  { value: 'zh-CN', label: 'zh-CN' },
  { value: 'en-US', label: 'en-US' },
]

/**
 * 单张音色卡片的渲染入参。
 *
 * 通过把 audio 元素 ref 透给上层 onPlay 回调，实现「单 active player」：
 * 上层在切换时主动 pause 旧元素，无需引入全局状态库。
 */
interface VoicePackCardProps {
  pack: VoicePackRead
  onPlay: (audio: HTMLAudioElement | null) => void
  playLabel: string
}

/**
 * 单张音色卡片：provider tag + name + gender tag + sample 试听按钮。
 *
 * 试听按钮 disabled 与否取决于 sample_file_id 是否能解析出可访问 URL；
 * 没有 sample 的音色保留卡片但禁用按钮，避免列表里出现「断行」。
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
        {/* sample 试听 audio：单元素隐藏，由按钮触发 play / pause */}
        <audio ref={audioRef} src={sampleUrl} preload="none" />
      </div>
    </Card>
  )
}

/**
 * 商品音色库主视图。
 *
 * 状态：
 * - `languageCode`：当前过滤语言，默认 zh-CN。
 * - `uploadOpen`：上传定制音色弹窗开关（W20 stub）。
 * - `activePlayerRef`：当前正在播放的 audio 元素引用，切换 / 卸载时主动 pause。
 */
export const VoicePackLibrary: React.FC = () => {
  const { t } = useTranslation('commerce')
  const [languageCode, setLanguageCode] = useState<string>('zh-CN')
  const [uploadOpen, setUploadOpen] = useState(false)

  const query = useVoicePacks(languageCode)

  // 防御式：后端已按 language_code 过滤，但客户端再过一遍以防缓存命中漂移。
  const filtered = useMemo<VoicePackRead[]>(
    () =>
      (query.data ?? []).filter(
        (pack: VoicePackRead) => pack.language_code === languageCode,
      ),
    [query.data, languageCode],
  )

  // 单 active player：保留正在播放的 audio 引用，切换时 pause 旧元素。
  const activePlayerRef = useRef<HTMLAudioElement | null>(null)

  /**
   * 试听播放控制（与 VoicePackPicker 保持一致）。
   *
   * play() 在某些浏览器返回 promise，这里 swallow 拒绝避免 unhandled rejection。
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
        // 用户尚未交互或音频不可用时浏览器会拒绝 play，UI 层无需感知。
      })
    }
  }

  const playLabel = t('voicePackPicker.play')

  /** 顶部工具栏：language 下拉 + 上传定制按钮。 */
  const toolbar = (
    <Space wrap>
      <Select
        aria-label="voice-pack-language"
        value={languageCode}
        onChange={(v) => setLanguageCode(v)}
        options={LANGUAGE_OPTIONS}
        style={{ width: 140 }}
      />
      <Button icon={<UploadOutlined />} onClick={() => setUploadOpen(true)}>
        {t('voicePackLibrary.uploadCustom')}
      </Button>
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
          <Skeleton
            key={i}
            active
            title={false}
            paragraph={{ rows: 2 }}
          />
        ))}
      </div>
    )
  } else if (query.isError) {
    body = (
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
    body = (
      <Empty
        image={Empty.PRESENTED_IMAGE_SIMPLE}
        description={t('voicePackLibrary.empty')}
      />
    )
  } else {
    body = (
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
        {body}
      </Card>

      <VoicePackUploadModal
        open={uploadOpen}
        onClose={() => setUploadOpen(false)}
      />
    </ScrollablePage>
  )
}

export default VoicePackLibrary
