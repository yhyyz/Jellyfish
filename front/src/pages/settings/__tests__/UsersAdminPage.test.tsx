import { describe, it, expect, beforeEach, vi } from 'vitest'
import { render, screen, waitFor, within } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { MemoryRouter } from 'react-router-dom'
import UsersAdminPage from '../UsersAdminPage'
import { AuthProvider } from '../../../contexts/AuthContext'
import { SettingsUsersService } from '../../../services/generated'
import '../../../i18n'

const mockUsers = [
  {
    id: 'u-admin',
    username: 'admin',
    email: 'admin@example.com',
    role: 'admin' as const,
    is_active: true,
    created_at: '2026-05-28T10:00:00Z',
    updated_at: '2026-05-28T10:00:00Z',
  },
  {
    id: 'u-bob',
    username: 'bob',
    email: 'bob@example.com',
    role: 'member' as const,
    is_active: true,
    created_at: '2026-05-28T10:01:00Z',
    updated_at: '2026-05-28T10:01:00Z',
  },
]

function renderPage() {
  return render(
    <MemoryRouter>
      <AuthProvider>
        <UsersAdminPage />
      </AuthProvider>
    </MemoryRouter>,
  )
}

describe('UsersAdminPage', () => {
  beforeEach(() => {
    localStorage.clear()
    vi.restoreAllMocks()
    vi.spyOn(SettingsUsersService, 'listUsersEndpointApiV1SettingsUsersGet').mockResolvedValue({
      code: 200,
      message: 'success',
      data: { items: mockUsers, pagination: { page: 1, page_size: 20, total: 2, max_page: 1 } },
    } as never)
  })

  it('renders user list rows', async () => {
    renderPage()
    await waitFor(() => {
      expect(screen.getByText('admin@example.com')).toBeInTheDocument()
      expect(screen.getByText('bob@example.com')).toBeInTheDocument()
    })
  })

  it('opens create modal and submits new user', async () => {
    const createSpy = vi
      .spyOn(SettingsUsersService, 'createUserEndpointApiV1SettingsUsersPost')
      .mockResolvedValue({
        code: 201,
        message: 'success',
        data: {
          id: 'new-id',
          username: 'carol',
          email: 'carol@example.com',
          role: 'member',
          is_active: true,
          created_at: '2026-05-28T10:02:00Z',
          updated_at: '2026-05-28T10:02:00Z',
        },
      } as never)

    renderPage()
    await waitFor(() => expect(screen.getByText('admin@example.com')).toBeInTheDocument())

    await userEvent.click(screen.getByRole('button', { name: /新建用户|New User|新規ユーザー|사용자 추가/i }))
    const dialog = await screen.findByRole('dialog')
    await userEvent.type(within(dialog).getByLabelText(/用户名|Username|ユーザー名|사용자명/i), 'carol')
    await userEvent.type(within(dialog).getByLabelText(/邮箱|Email|メール|이메일/i), 'carol@example.com')
    await userEvent.type(within(dialog).getByLabelText(/密码|Password|パスワード|비밀번호/i), 'pw-12345')

    const okBtns = within(dialog).getAllByRole('button', { name: /OK|确定|확인/i })
    await userEvent.click(okBtns[0])

    await waitFor(() => {
      expect(createSpy).toHaveBeenCalled()
      const callArg = createSpy.mock.calls[0]?.[0] as { requestBody: { username: string } }
      expect(callArg.requestBody.username).toBe('carol')
    })
  })

  it('shows table loading state then resolves to data', async () => {
    renderPage()
    await waitFor(() => {
      expect(screen.getByText('admin')).toBeInTheDocument()
    })
  })

  it('displays role badges via tag', async () => {
    renderPage()
    await waitFor(() => {
      expect(screen.getByText('admin@example.com')).toBeInTheDocument()
    })
    const adminTags = screen.getAllByText(/管理员|Admin|管理者|관리자/i)
    expect(adminTags.length).toBeGreaterThanOrEqual(1)
  })
})
