/**
 * 鉴权上下文 (P5 W32-T9)。
 *
 * 职责：
 * - 持久化 access token 到 localStorage (key: jellyfish_access_token)
 * - 启动期把 token 注入 OpenAPI generated client 的 TOKEN 配置
 * - 提供 login / logout / hasRole 工具方法
 * - 暴露当前 user / role / isLoading 给消费者
 *
 * 设计要点：
 * - 不在 token 里读 role —— 后端 JWT 不放 role（防降权失效），
 *   role 由 /api/v1/login/access-token 响应不携带，需要后续接口暴露 me 端点
 *   再拉取；本 stage-1 简化处理：登录后保存 username 与 role（来自 username
 *   推断为 admin/未来从 /me 拉），暂用 token 持久化 + 用户填写时记下。
 * - W32-T10 commit 落 /api/v1/users/me 端点后再增强（恢复 user 详情）。
 */

import { createContext, useCallback, useContext, useEffect, useMemo, useState } from 'react'
import type { ReactNode } from 'react'
import { AuthService, OpenAPI } from '../services/generated'

const TOKEN_STORAGE_KEY = 'jellyfish_access_token'
const USER_STORAGE_KEY = 'jellyfish_current_user'

export type UserRole = 'admin' | 'member' | 'viewer'

export interface AuthUser {
  id: string
  username: string
  role: UserRole
}

export interface AuthContextValue {
  user: AuthUser | null
  token: string | null
  isLoading: boolean
  login: (username: string, password: string) => Promise<void>
  logout: () => void
  hasRole: (required: UserRole | UserRole[]) => boolean
}

const AuthContext = createContext<AuthContextValue | null>(null)

function readPersistedUser(): AuthUser | null {
  try {
    const raw = localStorage.getItem(USER_STORAGE_KEY)
    if (!raw) return null
    return JSON.parse(raw) as AuthUser
  } catch {
    return null
  }
}

function persistUser(user: AuthUser | null): void {
  if (user) {
    localStorage.setItem(USER_STORAGE_KEY, JSON.stringify(user))
  } else {
    localStorage.removeItem(USER_STORAGE_KEY)
  }
}

function setOpenApiToken(token: string | null): void {
  OpenAPI.TOKEN = token ?? undefined
}

export interface AuthProviderProps {
  children: ReactNode
}

export function AuthProvider({ children }: AuthProviderProps): React.ReactElement {
  const [token, setToken] = useState<string | null>(() =>
    typeof window !== 'undefined' ? localStorage.getItem(TOKEN_STORAGE_KEY) : null,
  )
  const [user, setUser] = useState<AuthUser | null>(() => readPersistedUser())
  const [isLoading, setIsLoading] = useState<boolean>(false)

  useEffect(() => {
    setOpenApiToken(token)
  }, [token])

  const login = useCallback(
    async (username: string, password: string): Promise<void> => {
      setIsLoading(true)
      try {
        const resp = await AuthService.loginAccessTokenApiV1LoginAccessTokenPost({
          formData: { username, password },
        })
        const access = resp?.data?.access_token
        if (!access) {
          throw new Error('Empty access_token in response')
        }
        localStorage.setItem(TOKEN_STORAGE_KEY, access)
        setToken(access)
        const fallbackUser: AuthUser = {
          id: '__pending_me__',
          username,
          role: 'admin',
        }
        persistUser(fallbackUser)
        setUser(fallbackUser)
      } finally {
        setIsLoading(false)
      }
    },
    [],
  )

  const logout = useCallback((): void => {
    localStorage.removeItem(TOKEN_STORAGE_KEY)
    persistUser(null)
    setToken(null)
    setUser(null)
  }, [])

  const hasRole = useCallback(
    (required: UserRole | UserRole[]): boolean => {
      if (!user) return false
      const allowed = Array.isArray(required) ? required : [required]
      return allowed.includes(user.role)
    },
    [user],
  )

  const value = useMemo<AuthContextValue>(
    () => ({ user, token, isLoading, login, logout, hasRole }),
    [user, token, isLoading, login, logout, hasRole],
  )

  return <AuthContext.Provider value={value}>{children}</AuthContext.Provider>
}

export function useAuth(): AuthContextValue {
  const ctx = useContext(AuthContext)
  if (!ctx) {
    throw new Error('useAuth must be used inside <AuthProvider>')
  }
  return ctx
}
