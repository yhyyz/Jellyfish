/**
 * 路由守卫组件 (P5 W32-T9)。
 *
 * 用法：
 *   <ProtectedRoute><DashboardPage /></ProtectedRoute>
 *   <ProtectedRoute requiredRole="admin"><ApiKeysPage /></ProtectedRoute>
 *
 * 行为：
 * - 未登录 → 跳 /login 并保留来源路径（state.from）以便登录后回跳
 * - role 不足 → 跳 /403
 * - isLoading → 渲染居中 Spin
 */

import { Spin } from 'antd'
import type { ReactNode } from 'react'
import { useTranslation } from 'react-i18next'
import { Navigate, useLocation } from 'react-router-dom'
import type { UserRole } from '../contexts/AuthContext'
import { useAuth } from '../contexts/AuthContext'

export interface ProtectedRouteProps {
  requiredRole?: UserRole | UserRole[]
  children: ReactNode
}

export function ProtectedRoute({
  requiredRole,
  children,
}: ProtectedRouteProps): React.ReactElement {
  const { user, isLoading, hasRole } = useAuth()
  const { t } = useTranslation('auth')
  const location = useLocation()

  if (isLoading) {
    return (
      <div
        style={{
          display: 'flex',
          height: '60vh',
          alignItems: 'center',
          justifyContent: 'center',
        }}
      >
        <Spin tip={t('protected.loading')} />
      </div>
    )
  }

  if (!user) {
    return <Navigate to="/login" replace state={{ from: location.pathname }} />
  }

  if (requiredRole && !hasRole(requiredRole)) {
    return <Navigate to="/403" replace />
  }

  return <>{children}</>
}
