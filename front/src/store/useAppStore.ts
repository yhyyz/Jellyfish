import { create } from 'zustand'
import type { SupportedLanguage } from '../i18n'

/**
 * useAppStore — 应用级轻量偏好 store（zustand）。
 *
 * v0.7.2 收口：user 字段（nickname / role）已迁到 ``AuthContext``，
 * 此处仅保留与登录态无关的 UI 偏好（侧边栏折叠、语言切换）。
 * 历史 ``user`` / ``setUser`` 字段连同 hardcode 'Admin / 系统管理员'
 * 占位一并删除，避免双源真相。
 */
interface AppState {
  siderCollapsed: boolean
  language: SupportedLanguage
  setLanguage: (lang: SupportedLanguage) => void
  toggleSider: () => void
}

export const useAppStore = create<AppState>((set) => ({
  siderCollapsed: false,
  language: 'zh-CN',
  setLanguage: (lang) => set(() => ({ language: lang })),
  toggleSider: () =>
    set((state) => ({
      siderCollapsed: !state.siderCollapsed,
    })),
}))
