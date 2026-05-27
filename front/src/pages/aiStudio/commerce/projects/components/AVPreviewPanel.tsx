/**
 * AVPreviewPanel —— 分镜工作室「音视频预览」抽屉面板（W20-T4）。
 *
 * 这是 W20 Wave B 的入口面板：把 Wave A 已完工的 VoicePackPicker /
 * SubtitleStylePicker 嵌进来，同时把"成片预览 / 触发生成 / 跳任务中心"
 * 这条窄链路收口到一个右抽屉里。
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
 * - 下半部用 antd Collapse 嵌两个 picker：
 *     * 「音色」→ VoicePackPicker（默认 zh-CN）
 *     * 「字幕样式」→ SubtitleStylePicker
 *   暂用本地 useState 承接选中态；TODO(W20-T5): 等项目级 mutation hook
 *   就绪后改为对 StoryProject.voice_pack_id /
 *   StoryProject.subtitle_style_id 回写。
 */
import React, { useState } from 'react'
import { Button, Collapse, Empty, Space, message } from 'antd'
import { PlayCircleOutlined, UnorderedListOutlined } from '@ant-design/icons'
import { useMutation } from '@tanstack/react-query'

import {
  CommerceTasksService,
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
 * 组件入参契约。
 *
 * - chapterId / projectId 必传，因为 chapter_av_export 任务的目标章节是
 *   定位级关键参数；projectId 暂作为 picker 选择回写的预留 hook。
 * - shot 可选：父级在镜头未选定 / 加载中时传 null 即可，面板会落到
 *   Empty 分支。
 * - onTriggerExport 可选：任务入队成功后 callback，供父级自定义
 *   message / 缓存失效之外的副作用。
 */
export interface AVPreviewPanelProps {
  /** 当前章节 ID（chapter_av_export 的落点章节） */
  chapterId: string
  /** 当前项目 ID（暂为 picker 项目级回写预留） */
  projectId: string
  /** 当前选中镜头；可能为 null（未选 / 加载中均可） */
  shot?: ShotRead | null
  /** 任务入队成功 callback（可选） */
  onTriggerExport?: () => void
}

/**
 * 「音视频预览」抽屉主面板。
 *
 * 内部维护两段本地状态：voicePackId / subtitleStyle。当前阶段（W20
 * Wave B 第一件）只做组件级展示与触发动作，不把选择回写到项目；
 * 留 TODO 给 W20-T5 接 project mutation hook。
 */
export const AVPreviewPanel: React.FC<AVPreviewPanelProps> = ({
  chapterId,
  // projectId 暂作为预留参数，避免 ESLint 未使用告警显式 _ 标记。
  projectId: _projectId,
  shot,
  onTriggerExport,
}) => {
  // TODO(W20-T5): 改成读 project.voice_pack_id / 写 useUpdateStoryProject。
  const [voicePackId, setVoicePackId] = useState<string | undefined>(undefined)
  // TODO(W20-T5): 改成读 project.subtitle_style_id / 写 useUpdateStoryProject。
  const [subtitleStyle, setSubtitleStyle] = useState<
    SubtitleStyleValue | undefined
  >(undefined)

  /**
   * chapter_av_export 触发 mutation。
   *
   * 仅做最薄封装：调用 OpenAPI generated client，成功 / 失败均通过 antd
   * `message` 给用户即时反馈；onSuccess 转发给父组件的可选 callback，
   * 让父级可按需做缓存失效（如刷新 chapter / shot 列表）。
   */
  const trigger = useMutation({
    mutationFn: async () => {
      const res =
        await CommerceTasksService.enqueueChapterAvExportApiV1CommerceChapterAvExportPost(
          { requestBody: { chapter_id: chapterId } },
        )
      return res.data
    },
    onSuccess: (data) => {
      const taskTip = data?.task_id ? `（task_id: ${data.task_id}）` : ''
      message.success(`已加入生成队列${taskTip}`)
      onTriggerExport?.()
    },
    onError: (err) => {
      const errMsg = err instanceof Error ? err.message : '未知错误'
      message.error(`触发失败：${errMsg}`)
    },
  })

  // TaskCenter 在 layouts/MainLayout 中是常驻浮窗（非路由）；
  // 通过 zustand store 拿到 setOpen 直接打开浮窗即可。
  const setTaskCenterOpen = useTaskUiStore((state) => state.setOpen)

  const dubbedFileId = shot?.dubbed_video_file_id ?? null
  const videoUrl = dubbedFileId ? resolveAssetUrl(dubbedFileId) : undefined

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
            您的浏览器不支持 video 标签
          </video>
        ) : (
          <div
            className="flex h-[260px] flex-col items-center justify-center gap-3 rounded border border-dashed border-gray-200 bg-gray-50 px-4"
            data-testid="av-preview-empty"
          >
            <Empty description="等待 chapter_av_export 完成" />
            <Space>
              <Button
                type="primary"
                icon={<PlayCircleOutlined />}
                disabled={trigger.isPending}
                loading={trigger.isPending}
                onClick={() => trigger.mutate()}
                aria-label="立即生成"
              >
                立即生成成片
              </Button>
              <Button
                icon={<UnorderedListOutlined />}
                onClick={() => setTaskCenterOpen(true)}
                aria-label="查看任务中心"
              >
                查看任务中心
              </Button>
            </Space>
          </div>
        )}
      </div>

      {/* 下半部：嵌套 picker */}
      <Collapse
        defaultActiveKey={['voice']}
        items={[
          {
            key: 'voice',
            label: '音色',
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
            label: '字幕样式',
            children: (
              <SubtitleStylePicker
                value={subtitleStyle}
                onChange={setSubtitleStyle}
              />
            ),
          },
        ]}
      />
    </div>
  )
}

export default AVPreviewPanel
