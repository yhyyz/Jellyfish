/**
 * MainLayout 头部用户区 TDD 测试套件 (W32-followup-2, Manual QA Bug B 修复)。
 *
 * 验证的核心契约：
 *  1. 显示 AuthContext.user.username（不再是 useAppStore hardcode 'Admin'）
 *  2. role 经 auth.json roles.{admin,member,viewer} ns 翻译为本地化 label
 *  3. 顶部 Dropdown 触发 user.logout 菜单点击：
 *     - 调用 useAuth().logout() 1 次（清 token + state）
 *     - navigate('/login', { replace: true }) 1 次
 *
 * 设计取舍：
 *  - 通过 vi.mock 直接桩 ../contexts/AuthContext，避免依赖真实 OpenAPI / /me；
 *  - 桩 TaskRuntimeProvider / TaskCenter 为透传/空，避免拉起 FilmService 与
 *    定时器，让 layout 渲染保持纯 UI；
 *  - 桩 react-router-dom.useNavigate，断言 logout 后跳 /login。
 *  - 用真实 i18n 实例（zh-CN）→ 验证 roles.admin → '系统管理员' 等真翻译。
 */

import React from 'react'
import { describe, it, expect, beforeEach, vi } from 'vitest'
import { render, screen, fireEvent, waitFor } from '@testing-library/react'
import { MemoryRouter } from 'react-router-dom'
import '../../i18n'
import i18n from '../../i18n'

void React

const logoutMock = vi.fn()
const navigateMock = vi.fn()

vi.mock('../../contexts/AuthContext', () => ({
  useAuth: () => ({
    user: { id: 'u-1', username: 'alice', role: 'admin' },
    token: 'tok-xxx',
    isLoading: false,
    login: vi.fn(),
    logout: logoutMock,
    hasRole: () => true,
  }),
  AuthProvider: ({ children }: { children: React.ReactNode }) => <>{children}</>,
}))

vi.mock('../../pages/aiStudio/components/TaskRuntimeProvider', () => ({
  TaskRuntimeProvider: ({ children }: { children: React.ReactNode }) => <>{children}</>,
}))

vi.mock('../../pages/aiStudio/components/TaskCenter', () => ({
  TaskCenter: () => null,
}))

vi.mock('react-router-dom', async () => {
  const actual = await vi.importActual<typeof import('react-router-dom')>('react-router-dom')
  return {
    ...actual,
    useNavigate: () => navigateMock,
  }
})

import MainLayout from '../MainLayout'
import { useAppStore } from '../../store/useAppStore'

function renderLayout() {
  return render(
    <MemoryRouter initialEntries={['/projects']}>
      <MainLayout />
    </MemoryRouter>,
  )
}

describe('MainLayout 头部用户区（AuthContext 接通 + role i18n + logout）', () => {
  beforeEach(() => {
    logoutMock.mockReset()
    navigateMock.mockReset()
    useAppStore.setState({ siderCollapsed: false, language: 'zh-CN' })
    void i18n.changeLanguage('zh-CN')
  })

  it('显示 AuthContext.user.username（而非 useAppStore.user.name = "Admin"）', () => {
    renderLayout()
    expect(screen.getByText('alice')).toBeInTheDocument()
    expect(screen.queryByText('Admin')).not.toBeInTheDocument()
  })

  it('role=admin 渲染为 zh-CN 翻译"系统管理员"', () => {
    renderLayout()
    expect(screen.getByText('系统管理员')).toBeInTheDocument()
  })

  it('点击 Dropdown「退出登录」调用 logout + navigate /login', async () => {
    renderLayout()
    const trigger = screen.getByText('alice').closest('div')
    expect(trigger).toBeTruthy()
    fireEvent.mouseEnter(trigger!.parentElement!)

    await waitFor(() => {
      expect(screen.getByText('退出登录')).toBeInTheDocument()
    })

    fireEvent.click(screen.getByText('退出登录'))

    await waitFor(() => {
      expect(logoutMock).toHaveBeenCalledTimes(1)
    })
    expect(navigateMock).toHaveBeenCalledWith('/login', { replace: true })
  })
})

describe('MainLayout 头部 role i18n 各 locale 完整性', () => {
  beforeEach(() => {
    logoutMock.mockReset()
    navigateMock.mockReset()
  })

  it('en-US: roles.admin 翻译为 "Administrator"', async () => {
    await i18n.changeLanguage('en-US')
    useAppStore.setState({ language: 'en-US' })
    renderLayout()
    expect(screen.getByText('Administrator')).toBeInTheDocument()
  })

  it('ja-JP: roles.admin 翻译为 "管理者"', async () => {
    await i18n.changeLanguage('ja-JP')
    useAppStore.setState({ language: 'ja-JP' })
    renderLayout()
    expect(screen.getByText('管理者')).toBeInTheDocument()
  })

  it('ko-KR: roles.admin 翻译为 "관리자"', async () => {
    await i18n.changeLanguage('ko-KR')
    useAppStore.setState({ language: 'ko-KR' })
    renderLayout()
    expect(screen.getByText('관리자')).toBeInTheDocument()
  })
})
