import { describe, it, expect, beforeEach, vi } from 'vitest'
import { waitFor } from '@testing-library/react'
import { renderHook, act } from '@testing-library/react'
import { AuthProvider, useAuth } from '../AuthContext'
import { AuthService, OpenAPI, UsersService, ApiError } from '../../services/generated'

const TOKEN_STORAGE_KEY = 'jellyfish_access_token'
const USER_STORAGE_KEY = 'jellyfish_current_user'

function wrapper({ children }: { children: React.ReactNode }) {
  return <AuthProvider>{children}</AuthProvider>
}

/**
 * 构造 AuthService.loginAccessToken 的 resolved 响应壳。
 * 复用以避免每个 test 都拼一遍长 cast。
 */
function mockLoginResolves(token: string): void {
  vi.spyOn(AuthService, 'loginAccessTokenApiV1LoginAccessTokenPost').mockResolvedValue({
    code: 200,
    message: 'success',
    data: { access_token: token, token_type: 'bearer', expires_in: 3600 },
  } as unknown as Awaited<ReturnType<typeof AuthService.loginAccessTokenApiV1LoginAccessTokenPost>>)
}

/**
 * 构造 UsersService.readUsersMe 的 resolved 响应壳。
 * role 来自参数，模拟后端 /me 真实返回。
 */
function mockMeResolves(opts: {
  id?: string
  username?: string
  role: 'admin' | 'member'
  isActive?: boolean
}): void {
  vi.spyOn(UsersService, 'readUsersMeApiV1UsersMeGet').mockResolvedValue({
    code: 200,
    message: 'success',
    data: {
      id: opts.id ?? 'user-id-1',
      username: opts.username ?? 'someone',
      email: `${opts.username ?? 'someone'}@example.com`,
      role: opts.role,
      is_active: opts.isActive ?? true,
      created_at: '2026-05-28T00:00:00Z',
      updated_at: '2026-05-28T00:00:00Z',
    },
  } as unknown as Awaited<ReturnType<typeof UsersService.readUsersMeApiV1UsersMeGet>>)
}

describe('AuthContext', () => {
  beforeEach(() => {
    localStorage.clear()
    OpenAPI.TOKEN = undefined
    vi.restoreAllMocks()
  })

  it('starts unauthenticated when no token in storage', () => {
    const { result } = renderHook(() => useAuth(), { wrapper })
    expect(result.current.user).toBeNull()
    expect(result.current.token).toBeNull()
  })

  it('login persists token to localStorage and OpenAPI client', async () => {
    mockLoginResolves('jwt-test-token')
    mockMeResolves({ id: 'u-alice', username: 'alice', role: 'admin' })

    const { result } = renderHook(() => useAuth(), { wrapper })
    await act(async () => {
      await result.current.login('alice', 'pw-12345')
    })

    expect(localStorage.getItem(TOKEN_STORAGE_KEY)).toBe('jwt-test-token')
    expect(result.current.token).toBe('jwt-test-token')
    expect(result.current.user?.username).toBe('alice')
    expect(OpenAPI.TOKEN).toBe('jwt-test-token')
  })

  it('login throws ApiError 401 when backend rejects', async () => {
    vi.spyOn(AuthService, 'loginAccessTokenApiV1LoginAccessTokenPost').mockRejectedValue(
      new ApiError(
        { method: 'POST', url: '/api/v1/login/access-token' } as never,
        { status: 401, statusText: 'Unauthorized', body: { code: 401, message: 'Incorrect' }, ok: false, url: '/api/v1/login/access-token' } as never,
        'Unauthorized',
      ),
    )

    const { result } = renderHook(() => useAuth(), { wrapper })
    await expect(
      act(async () => {
        await result.current.login('alice', 'wrong')
      }),
    ).rejects.toThrow()
    expect(localStorage.getItem(TOKEN_STORAGE_KEY)).toBeNull()
    expect(result.current.user).toBeNull()
  })

  it('logout clears token + user state + localStorage', async () => {
    mockLoginResolves('jwt-1')
    mockMeResolves({ id: 'u-bob', username: 'bob', role: 'admin' })

    const { result } = renderHook(() => useAuth(), { wrapper })
    await act(async () => {
      await result.current.login('bob', 'pw')
    })
    expect(result.current.token).toBe('jwt-1')

    act(() => {
      result.current.logout()
    })
    expect(result.current.token).toBeNull()
    expect(result.current.user).toBeNull()
    expect(localStorage.getItem(TOKEN_STORAGE_KEY)).toBeNull()
    expect(localStorage.getItem(USER_STORAGE_KEY)).toBeNull()
    expect(OpenAPI.TOKEN).toBeUndefined()
  })

  it('hasRole returns false when not logged in', () => {
    const { result } = renderHook(() => useAuth(), { wrapper })
    expect(result.current.hasRole('admin')).toBe(false)
    expect(result.current.hasRole(['admin', 'member'])).toBe(false)
  })

  it('hasRole accepts both single and array forms', async () => {
    mockLoginResolves('jwt-2')
    mockMeResolves({ id: 'u-carol', username: 'carol', role: 'admin' })

    const { result } = renderHook(() => useAuth(), { wrapper })
    await act(async () => {
      await result.current.login('carol', 'pw')
    })
    expect(result.current.hasRole('admin')).toBe(true)
    expect(result.current.hasRole(['admin', 'member'])).toBe(true)
    expect(result.current.hasRole('viewer')).toBe(false)
  })

  it('reads persisted user from localStorage on mount and refreshes via /me', async () => {
    localStorage.setItem(TOKEN_STORAGE_KEY, 'persisted-jwt')
    localStorage.setItem(
      USER_STORAGE_KEY,
      JSON.stringify({ id: 'u1', username: 'persisted', role: 'admin' }),
    )
    mockMeResolves({ id: 'u1', username: 'persisted', role: 'admin' })

    const { result } = renderHook(() => useAuth(), { wrapper })
    await waitFor(() => {
      expect(result.current.user?.username).toBe('persisted')
      expect(result.current.token).toBe('persisted-jwt')
    })
  })

  // === W32-followup new cases ===

  it('login as admin fetches /me and stores real role=admin', async () => {
    mockLoginResolves('jwt-admin')
    mockMeResolves({ id: 'admin-uuid', username: 'admin', role: 'admin' })

    const meSpy = vi.spyOn(UsersService, 'readUsersMeApiV1UsersMeGet')
    const { result } = renderHook(() => useAuth(), { wrapper })
    await act(async () => {
      await result.current.login('admin', 'pw')
    })

    expect(meSpy).toHaveBeenCalled()
    expect(result.current.user?.id).toBe('admin-uuid')
    expect(result.current.user?.role).toBe('admin')
    expect(result.current.hasRole('admin')).toBe(true)
  })

  it('login as member fetches /me; role=member and hasRole(admin) is false (W32-followup bug fix)', async () => {
    mockLoginResolves('jwt-member')
    mockMeResolves({ id: 'member-uuid', username: 'bob', role: 'member' })

    const { result } = renderHook(() => useAuth(), { wrapper })
    await act(async () => {
      await result.current.login('bob', 'pw')
    })

    expect(result.current.user?.role).toBe('member')
    expect(result.current.hasRole('admin')).toBe(false)
    expect(result.current.hasRole('member')).toBe(true)
    expect(result.current.hasRole(['admin', 'member'])).toBe(true)
  })

  it('initial mount with stale token: /me 401 → clears token + user', async () => {
    localStorage.setItem(TOKEN_STORAGE_KEY, 'stale-jwt')
    localStorage.setItem(
      USER_STORAGE_KEY,
      JSON.stringify({ id: 'u-old', username: 'oldcache', role: 'admin' }),
    )
    vi.spyOn(UsersService, 'readUsersMeApiV1UsersMeGet').mockRejectedValue(
      new ApiError(
        { method: 'GET', url: '/api/v1/users/me' } as never,
        {
          status: 401,
          statusText: 'Unauthorized',
          body: { code: 401, message: 'Invalid token' },
          ok: false,
          url: '/api/v1/users/me',
        } as never,
        'Unauthorized',
      ),
    )

    const { result } = renderHook(() => useAuth(), { wrapper })
    await waitFor(() => {
      expect(result.current.user).toBeNull()
      expect(result.current.token).toBeNull()
      expect(result.current.isLoading).toBe(false)
    })
    expect(localStorage.getItem(TOKEN_STORAGE_KEY)).toBeNull()
    expect(localStorage.getItem(USER_STORAGE_KEY)).toBeNull()
  })
})
