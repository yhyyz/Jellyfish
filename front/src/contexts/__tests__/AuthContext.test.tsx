import { describe, it, expect, beforeEach, vi } from 'vitest'
import { waitFor } from '@testing-library/react'
import { renderHook, act } from '@testing-library/react'
import { AuthProvider, useAuth } from '../AuthContext'
import { AuthService, OpenAPI, ApiError } from '../../services/generated'

const TOKEN_STORAGE_KEY = 'jellyfish_access_token'
const USER_STORAGE_KEY = 'jellyfish_current_user'

function wrapper({ children }: { children: React.ReactNode }) {
  return <AuthProvider>{children}</AuthProvider>
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
    vi.spyOn(AuthService, 'loginAccessTokenApiV1LoginAccessTokenPost').mockResolvedValue({
      code: 200,
      message: 'success',
      data: { access_token: 'jwt-test-token', token_type: 'bearer', expires_in: 3600 },
    } as unknown as Awaited<ReturnType<typeof AuthService.loginAccessTokenApiV1LoginAccessTokenPost>>)

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
    vi.spyOn(AuthService, 'loginAccessTokenApiV1LoginAccessTokenPost').mockResolvedValue({
      code: 200,
      message: 'success',
      data: { access_token: 'jwt-1', token_type: 'bearer', expires_in: 3600 },
    } as unknown as Awaited<ReturnType<typeof AuthService.loginAccessTokenApiV1LoginAccessTokenPost>>)

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
    vi.spyOn(AuthService, 'loginAccessTokenApiV1LoginAccessTokenPost').mockResolvedValue({
      code: 200,
      message: 'success',
      data: { access_token: 'jwt-2', token_type: 'bearer', expires_in: 3600 },
    } as unknown as Awaited<ReturnType<typeof AuthService.loginAccessTokenApiV1LoginAccessTokenPost>>)

    const { result } = renderHook(() => useAuth(), { wrapper })
    await act(async () => {
      await result.current.login('carol', 'pw')
    })
    expect(result.current.hasRole('admin')).toBe(true)
    expect(result.current.hasRole(['admin', 'member'])).toBe(true)
    expect(result.current.hasRole('viewer')).toBe(false)
  })

  it('reads persisted user from localStorage on mount', async () => {
    localStorage.setItem(TOKEN_STORAGE_KEY, 'persisted-jwt')
    localStorage.setItem(
      USER_STORAGE_KEY,
      JSON.stringify({ id: 'u1', username: 'persisted', role: 'admin' }),
    )

    const { result } = renderHook(() => useAuth(), { wrapper })
    await waitFor(() => {
      expect(result.current.user?.username).toBe('persisted')
      expect(result.current.token).toBe('persisted-jwt')
    })
  })
})
