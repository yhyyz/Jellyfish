/**
 * 登录页 (P5 W32-T9)。
 *
 * 表单：username + password + 记住我
 * 提交：调 AuthContext.login，成功后跳回 location.state.from 或 '/'
 * 失败：根据后端错误码（401 / 400）显示对应的本地化消息
 */

import { LockOutlined, UserOutlined } from '@ant-design/icons'
import { Alert, Button, Card, Checkbox, Form, Input, Space, Typography } from 'antd'
import { useCallback, useState } from 'react'
import { useTranslation } from 'react-i18next'
import { useLocation, useNavigate } from 'react-router-dom'
import { ApiError } from '../../services/generated'
import { useAuth } from '../../contexts/AuthContext'

interface LoginFormValues {
  username: string
  password: string
  remember?: boolean
}

interface LocationStateWithFrom {
  from?: string
}

export default function LoginPage(): React.ReactElement {
  const { t } = useTranslation('auth')
  const { login, isLoading } = useAuth()
  const navigate = useNavigate()
  const location = useLocation()
  const [errorMessage, setErrorMessage] = useState<string | null>(null)

  const handleSubmit = useCallback(
    async (values: LoginFormValues) => {
      setErrorMessage(null)
      try {
        await login(values.username, values.password)
        const state = location.state as LocationStateWithFrom | undefined
        const from = state?.from ?? '/'
        navigate(from, { replace: true })
      } catch (err) {
        if (err instanceof ApiError) {
          if (err.status === 401) {
            setErrorMessage(t('loginPage.errorIncorrect'))
            return
          }
          if (err.status === 400) {
            setErrorMessage(t('loginPage.errorInactive'))
            return
          }
        }
        setErrorMessage(t('loginPage.errorGeneric'))
      }
    },
    [login, navigate, location.state, t],
  )

  return (
    <div
      style={{
        minHeight: '100vh',
        display: 'flex',
        alignItems: 'center',
        justifyContent: 'center',
        background: '#f0f2f5',
        padding: 16,
      }}
    >
      <Card style={{ width: 420 }} bordered={false}>
        <Space direction="vertical" size="large" style={{ width: '100%' }}>
          <div style={{ textAlign: 'center' }}>
            <Typography.Title level={3} style={{ margin: 0 }}>
              {t('loginPage.title')}
            </Typography.Title>
            <Typography.Text type="secondary">
              {t('loginPage.subtitle')}
            </Typography.Text>
          </div>

          {errorMessage ? (
            <Alert type="error" showIcon message={errorMessage} role="alert" />
          ) : null}

          <Form<LoginFormValues>
            layout="vertical"
            onFinish={handleSubmit}
            initialValues={{ remember: true }}
            disabled={isLoading}
          >
            <Form.Item
              label={t('loginPage.username')}
              name="username"
              rules={[{ required: true, message: t('loginPage.username') }]}
            >
              <Input
                prefix={<UserOutlined />}
                placeholder={t('loginPage.usernamePlaceholder')}
                autoComplete="username"
              />
            </Form.Item>

            <Form.Item
              label={t('loginPage.password')}
              name="password"
              rules={[{ required: true, message: t('loginPage.password') }]}
            >
              <Input.Password
                prefix={<LockOutlined />}
                placeholder={t('loginPage.passwordPlaceholder')}
                autoComplete="current-password"
              />
            </Form.Item>

            <Form.Item name="remember" valuePropName="checked">
              <Checkbox>{t('loginPage.rememberMe')}</Checkbox>
            </Form.Item>

            <Form.Item>
              <Button
                type="primary"
                htmlType="submit"
                block
                loading={isLoading}
              >
                {isLoading ? t('loginPage.submitting') : t('loginPage.submit')}
              </Button>
            </Form.Item>
          </Form>
        </Space>
      </Card>
    </div>
  )
}
