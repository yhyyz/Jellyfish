/**
 * 鉴权上下文 (P5 W32-T9 + W32-followup)。
 *
 * 职责：
 * - 持久化 access token 到 localStorage (key: jellyfish_access_token)
 * - 启动期把 token 注入 OpenAPI generated client 的 TOKEN 配置
 * - 登录成功后 / 启动期检测到 token 时，调用 GET /api/v1/users/me 拉真实
 *   user profile（id / username / role / is_active），写入 state
 * - 提供 login / logout / hasRole 工具方法
 * - 暴露当前 user / role / isLoading 给消费者
 *
 * W32-followup 修复要点（之前 W32-T9 的 hardcode bug）：
 * - 旧实装：登录后 user.role 硬编码为 'admin'，member 用户登录虽被
 *   backend require_admin 拦 403，但前端导航不隐藏 admin 入口，体验差。
 * - 新实装：登录响应仅含 access_token；立刻调 /me 拿真实 user，
 *   role 永远来自后端而不是前端推断。
 * - 启动期 localStorage 有 token 时同样调 /me 校验；失败（401 / 网络
 *   等）即清掉 token + 退出登录态，避免持久化无效 session。
 */

import { createContext, useCallback, useContext, useEffect, useMemo, useState } from 'react'
import type { ReactNode } from 'react'
import { AuthService, OpenAPI, UsersService } from '../services/generated'
import type { UserRead } from '../services/generated'

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

/**
 * 把后端 UserRead 投影成前端 AuthUser。
 *
 * 后端 role 是 enum literal（'admin' / 'member'），与前端 UserRole 完全
 * 兼容。这里仍显式 cast 是为防御未来后端引入新角色（如 'viewer'）但前
 * 端尚未同步类型时编译能立刻失败。
 */
function projectUser(api: UserRead): AuthUser {
  return {
    id: api.id,
    username: api.username,
    role: api.role as UserRole,
  }
}

export interface AuthProviderProps {
  children: ReactNode
}

export function AuthProvider({ children }: AuthProviderProps): React.ReactElement {
  const [token, setToken] = useState<string | null>(() =>
    typeof window !== 'undefined' ? localStorage.getItem(TOKEN_STORAGE_KEY) : null,
  )
  const [user, setUser] = useState<AuthUser | null>(() => readPersistedUser())
  const [isLoading, setIsLoading] = useState<boolean>(() => {
    // 启动期若 localStorage 已有 token，需要等 /me 校验完成才能进入 ready 态。
    if (typeof window === 'undefined') return false
    return Boolean(localStorage.getItem(TOKEN_STORAGE_KEY))
  })

  useEffect(() => {
    setOpenApiToken(token)
  }, [token])

  // 启动期若有持久化 token，立刻向后端 /me 校验一次：
  // - 成功 → 用真实 role 覆写 state（即使持久化里有过期的 hardcode role）
  // - 失败 → 清掉 token + user（避免无效 session 误导路由守卫）
  useEffect(() => {
    if (typeof window === 'undefined') return
    const persistedToken = localStorage.getItem(TOKEN_STORAGE_KEY)
    if (!persistedToken) {
      setIsLoading(false)
      return
    }
    setOpenApiToken(persistedToken)
    let cancelled = false
    UsersService.readUsersMeApiV1UsersMeGet({})
      .then((resp) => {
        if (cancelled) return
        const me = resp?.data
        if (!me) {
          throw new Error('Empty /me response')
        }
        const real = projectUser(me)
        persistUser(real)
        setUser(real)
      })
      .catch(() => {
        if (cancelled) return
        localStorage.removeItem(TOKEN_STORAGE_KEY)
        persistUser(null)
        setToken(null)
        setUser(null)
      })
      .finally(() => {
        if (!cancelled) setIsLoading(false)
      })
    return () => {
      cancelled = true
    }
  }, [])

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
        // 必须立刻同步注入 OpenAPI.TOKEN，否则后续 /me 调用还会用旧值。
        setOpenApiToken(access)
        // 拿真实 user，role 来自后端 DB（解决 W32-T9 hardcode 'admin' bug）。
        const meResp = await UsersService.readUsersMeApiV1UsersMeGet({})
        const me = meResp?.data
        if (!me) {
          throw new Error('Empty /me response after login')
        }
        const real = projectUser(me)
        persistUser(real)
        setUser(real)
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
