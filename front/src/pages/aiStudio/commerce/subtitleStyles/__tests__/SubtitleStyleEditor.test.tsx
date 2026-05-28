/**
 * SubtitleStyleEditor 单元测试（W30-T5）。
 *
 * 覆盖：
 * 1. systemReadonly 模式：所有字段渲染 + form disabled + 仅"克隆"按钮可见。
 * 2. projectEdit 模式：保存按钮 + 重置按钮可见，保存调 PATCH client。
 * 3. create 模式（style=null）：保存按钮调 POST client。
 * 4. 系统级行点克隆 → 调 POST client。
 * 5. 项目级行点重置 + 弹窗确认 → 调 DELETE client。
 *
 * 注意：vitest 环境下 react-i18next 未初始化，t() 直接返回 key 字符串，
 * 因此断言用 i18n key（如 `subtitleStyleEditor.saveBtn`）做 regex 匹配。
 * antd Modal jsdom close-animation quirk 通过 `findByRole` / `waitFor` 处理。
 */
import { describe, it, expect, vi, beforeEach, afterEach } from 'vitest'
import { render, screen, fireEvent, waitFor, within } from '@testing-library/react'

import { CommerceSubtitleStylesService } from '../../../../../services/generated'
import type { SubtitleStyleRead } from '../../../../../services/generated'
import SubtitleStyleEditor from '../SubtitleStyleEditor'

const buildSystemStyle = (): SubtitleStyleRead => ({
  id: 'douyin_default',
  name: '抖音默认',
  description: '系统级抖音模板',
  language_code: 'zh-CN',
  format: 'ass',
  font_family: 'Source Han Sans CN Heavy',
  font_size: 60,
  primary_colour: '&H00FFFFFF',
  secondary_colour: '&H00FFFFFF',
  outline_colour: '&H00000000',
  back_colour: '&H80000000',
  bold: true,
  italic: false,
  border_style: 1,
  outline: 3,
  shadow: 1,
  alignment: 2,
  margin_l: 60,
  margin_r: 60,
  margin_v: 200,
  play_res_x: 1080,
  play_res_y: 1920,
  font_fallback_chain: ['Source Han Sans CN Heavy', 'PingFang SC'],
  is_system: true,
  sort_order: 0,
  project_id: null,
  created_at: '2026-05-28T00:00:00Z',
  updated_at: '2026-05-28T00:00:00Z',
})

const buildProjectStyle = (): SubtitleStyleRead => ({
  ...buildSystemStyle(),
  id: 'substyle_proj1',
  name: '项目大字幕',
  is_system: false,
  project_id: 'proj-1',
  font_size: 80,
})

describe('SubtitleStyleEditor', () => {
  // eslint-disable-next-line @typescript-eslint/no-explicit-any
  let createSpy: any
  // eslint-disable-next-line @typescript-eslint/no-explicit-any
  let updateSpy: any
  // eslint-disable-next-line @typescript-eslint/no-explicit-any
  let deleteSpy: any

  beforeEach(() => {
    createSpy = vi.spyOn(
      CommerceSubtitleStylesService,
      'createProjectSubtitleStyleEndpointApiV1CommerceProjectsProjectIdSubtitleStylesPost',
    )
    updateSpy = vi.spyOn(
      CommerceSubtitleStylesService,
      'updateProjectSubtitleStyleEndpointApiV1CommerceProjectsProjectIdSubtitleStylesStyleIdPatch',
    )
    deleteSpy = vi.spyOn(
      CommerceSubtitleStylesService,
      'deleteProjectSubtitleStyleEndpointApiV1CommerceProjectsProjectIdSubtitleStylesStyleIdDelete',
    )
  })

  afterEach(() => {
    createSpy.mockRestore()
    updateSpy.mockRestore()
    deleteSpy.mockRestore()
  })

  it('renders system style readonly with cloneBtn but no saveBtn', async () => {
    render(
      <SubtitleStyleEditor
        open
        onClose={() => undefined}
        projectId="proj-1"
        style={buildSystemStyle()}
      />,
    )
    const dialog = await screen.findByRole('dialog')
    expect(within(dialog).getByText(/subtitleStyleEditor\.systemBadge/i)).toBeInTheDocument()
    expect(within(dialog).getByText(/subtitleStyleEditor\.immutableHint/i)).toBeInTheDocument()
    expect(within(dialog).getByRole('button', { name: /subtitleStyleEditor\.cloneBtn/i })).toBeInTheDocument()
    expect(within(dialog).queryByRole('button', { name: /subtitleStyleEditor\.saveBtn/i })).toBeNull()
    expect(within(dialog).queryByRole('button', { name: /subtitleStyleEditor\.resetBtn/i })).toBeNull()
  })

  it('renders project style with saveBtn + resetBtn visible', async () => {
    render(
      <SubtitleStyleEditor
        open
        onClose={() => undefined}
        projectId="proj-1"
        style={buildProjectStyle()}
      />,
    )
    const dialog = await screen.findByRole('dialog')
    expect(within(dialog).getByText(/subtitleStyleEditor\.projectBadge/i)).toBeInTheDocument()
    expect(within(dialog).getByRole('button', { name: /subtitleStyleEditor\.saveBtn/i })).toBeInTheDocument()
    expect(within(dialog).getByRole('button', { name: /subtitleStyleEditor\.resetBtn/i })).toBeInTheDocument()
  })

  it('renders create mode (style=null) with saveBtn only', async () => {
    render(
      <SubtitleStyleEditor
        open
        onClose={() => undefined}
        projectId="proj-1"
        style={null}
      />,
    )
    const dialog = await screen.findByRole('dialog')
    expect(within(dialog).getByText(/subtitleStyleEditor\.createTitle/i)).toBeInTheDocument()
    expect(within(dialog).getByRole('button', { name: /subtitleStyleEditor\.saveBtn/i })).toBeInTheDocument()
    expect(within(dialog).queryByRole('button', { name: /subtitleStyleEditor\.resetBtn/i })).toBeNull()
  })

  it('clicking cloneBtn on system style calls POST client', async () => {
    createSpy.mockResolvedValue({
      code: 201,
      message: 'success',
      data: {
        ...buildProjectStyle(),
        id: 'substyle_clone1',
      },
      meta: null,
    } as never)
    const onMutated = vi.fn()
    const onClose = vi.fn()
    render(
      <SubtitleStyleEditor
        open
        onClose={onClose}
        projectId="proj-1"
        style={buildSystemStyle()}
        onMutated={onMutated}
      />,
    )
    const dialog = await screen.findByRole('dialog')
    fireEvent.click(
      within(dialog).getByRole('button', {
        name: /subtitleStyleEditor\.cloneBtn/i,
      }),
    )
    await waitFor(() => {
      expect(createSpy).toHaveBeenCalledTimes(1)
    })
    const callArgs = createSpy.mock.calls[0][0] as {
      projectId: string
      requestBody: { name: string }
    }
    expect(callArgs.projectId).toBe('proj-1')
    expect(callArgs.requestBody.name).toBe('抖音默认')
    await waitFor(() => {
      expect(onMutated).toHaveBeenCalled()
      expect(onClose).toHaveBeenCalled()
    })
  })

  it('clicking saveBtn on project style calls PATCH client', async () => {
    updateSpy.mockResolvedValue({
      code: 200,
      message: 'success',
      data: { ...buildProjectStyle(), font_size: 80 },
      meta: null,
    } as never)
    const onMutated = vi.fn()
    render(
      <SubtitleStyleEditor
        open
        onClose={() => undefined}
        projectId="proj-1"
        style={buildProjectStyle()}
        onMutated={onMutated}
      />,
    )
    const dialog = await screen.findByRole('dialog')
    fireEvent.click(
      within(dialog).getByRole('button', {
        name: /subtitleStyleEditor\.saveBtn/i,
      }),
    )
    await waitFor(() => {
      expect(updateSpy).toHaveBeenCalledTimes(1)
    })
    const callArgs = updateSpy.mock.calls[0][0] as {
      projectId: string
      styleId: string
    }
    expect(callArgs.projectId).toBe('proj-1')
    expect(callArgs.styleId).toBe('substyle_proj1')
  })

  it('clicking resetBtn opens popconfirm and calling DELETE on confirm', async () => {
    deleteSpy.mockResolvedValue({
      code: 200,
      message: 'success',
      data: null,
      meta: null,
    } as never)
    render(
      <SubtitleStyleEditor
        open
        onClose={() => undefined}
        projectId="proj-1"
        style={buildProjectStyle()}
      />,
    )
    const dialog = await screen.findByRole('dialog')
    const resetBtn = within(dialog).getByRole('button', {
      name: /subtitleStyleEditor\.resetBtn/i,
    })
    fireEvent.click(resetBtn)
    // Popconfirm 渲染到 portal，整个 document 范围查找 ok 按钮
    const okBtn = await screen.findByRole('button', {
      name: /subtitleStyleEditor\.resetOk/i,
    })
    fireEvent.click(okBtn)
    await waitFor(() => {
      expect(deleteSpy).toHaveBeenCalledTimes(1)
    })
    const callArgs = deleteSpy.mock.calls[0][0] as {
      projectId: string
      styleId: string
    }
    expect(callArgs.projectId).toBe('proj-1')
    expect(callArgs.styleId).toBe('substyle_proj1')
  })

  it('renders core form fields (name / fontSize / primaryColour)', async () => {
    render(
      <SubtitleStyleEditor
        open
        onClose={() => undefined}
        projectId="proj-1"
        style={buildProjectStyle()}
      />,
    )
    const dialog = await screen.findByRole('dialog')
    expect(within(dialog).getByText(/subtitleStyleEditor\.fields\.name/i)).toBeInTheDocument()
    expect(within(dialog).getByText(/subtitleStyleEditor\.fields\.fontSize/i)).toBeInTheDocument()
    expect(within(dialog).getByText(/subtitleStyleEditor\.fields\.primaryColour/i)).toBeInTheDocument()
    expect(within(dialog).getByTestId('subtitle-style-editor-preview')).toBeInTheDocument()
  })
})
