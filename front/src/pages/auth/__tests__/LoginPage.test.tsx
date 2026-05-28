import { describe, it, expect, beforeEach, vi } from 'vitest'
import { render, screen, waitFor } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { MemoryRouter } from 'react-router-dom'
import LoginPage from '../LoginPage'
import { AuthProvider } from '../../../contexts/AuthContext'
import { AuthService, ApiError } from '../../../services/generated'
import '../../../i18n'

function renderWithProviders() {
  return render(
    <MemoryRouter initialEntries={['/login']}>
      <AuthProvider>
        <LoginPage />
      </AuthProvider>
    </MemoryRouter>,
  )
}

describe('LoginPage', () => {
  beforeEach(() => {
    localStorage.clear()
    vi.restoreAllMocks()
  })

  it('renders username + password + remember + submit', () => {
    renderWithProviders()
    expect(screen.getByLabelText(/用户名|Username|ユーザー名|사용자명/i)).toBeInTheDocument()
    expect(screen.getByLabelText(/密码|Password|パスワード|비밀번호/i)).toBeInTheDocument()
    expect(screen.getByRole('button', { name: /登录|Sign in|サインイン|로그인/i })).toBeInTheDocument()
  })

  it('shows 401 inline error message on incorrect credentials', async () => {
    vi.spyOn(AuthService, 'loginAccessTokenApiV1LoginAccessTokenPost').mockRejectedValue(
      new ApiError(
        { method: 'POST', url: '/api/v1/login/access-token' } as never,
        { status: 401, statusText: 'Unauthorized', body: { code: 401, message: 'Incorrect' }, ok: false, url: '/api/v1/login/access-token' } as never,
        'Unauthorized',
      ),
    )

    renderWithProviders()
    await userEvent.type(screen.getByLabelText(/用户名|Username|ユーザー名|사용자명/i), 'alice')
    await userEvent.type(screen.getByLabelText(/密码|Password|パスワード|비밀번호/i), 'wrong')
    await userEvent.click(screen.getByRole('button', { name: /登录|Sign in|サインイン|로그인/i }))

    const alert = await screen.findByRole('alert')
    expect(alert.textContent).toMatch(/错误|Incorrect|正しく|올바르지/i)
  })

  it('shows 400 inactive error message', async () => {
    vi.spyOn(AuthService, 'loginAccessTokenApiV1LoginAccessTokenPost').mockRejectedValue(
      new ApiError(
        { method: 'POST', url: '/api/v1/login/access-token' } as never,
        { status: 400, statusText: 'Bad', body: { code: 400, message: 'Inactive user' }, ok: false, url: '/api/v1/login/access-token' } as never,
        'Bad',
      ),
    )

    renderWithProviders()
    await userEvent.type(screen.getByLabelText(/用户名|Username|ユーザー名|사용자명/i), 'inactive')
    await userEvent.type(screen.getByLabelText(/密码|Password|パスワード|비밀번호/i), 'pw')
    await userEvent.click(screen.getByRole('button', { name: /登录|Sign in|サインイン|로그인/i }))

    const alert = await screen.findByRole('alert')
    expect(alert.textContent).toMatch(/禁用|inactive|無効|비활성/i)
  })

  it('persists token to localStorage after successful login', async () => {
    vi.spyOn(AuthService, 'loginAccessTokenApiV1LoginAccessTokenPost').mockResolvedValue({
      code: 200,
      message: 'success',
      data: { access_token: 'good-jwt', token_type: 'bearer', expires_in: 3600 },
    } as unknown as Awaited<ReturnType<typeof AuthService.loginAccessTokenApiV1LoginAccessTokenPost>>)

    renderWithProviders()
    await userEvent.type(screen.getByLabelText(/用户名|Username|ユーザー名|사용자명/i), 'admin')
    await userEvent.type(screen.getByLabelText(/密码|Password|パスワード|비밀번호/i), 'changeme')
    await userEvent.click(screen.getByRole('button', { name: /登录|Sign in|サインイン|로그인/i }))

    await waitFor(() => {
      expect(localStorage.getItem('jellyfish_access_token')).toBe('good-jwt')
    })
  })
})
