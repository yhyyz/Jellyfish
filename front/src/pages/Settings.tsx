import { Card, Form, Input, Select, Switch, Button, message, Divider, Space, Typography } from 'antd'
import { KeyOutlined, RightOutlined } from '@ant-design/icons'
import { Link } from 'react-router-dom'
import { useTranslation } from 'react-i18next'
import { useAuth } from '../contexts/AuthContext'

const { Title, Text } = Typography

/**
 * Settings 页面 — 个人偏好与系统设置入口（v0.7.2 收口到 AuthContext）。
 *
 * 历史背景（v0.7.2 之前）：
 *   - 该页同时读写 ``useAppStore.user.name`` / ``useAppStore.user.role``
 *     （hardcode 'Admin' / '系统管理员' 占位），save 时 ``useAppStore.setUser``
 *     仅本地 zustand state，不触达后端。
 *   - W32-followup-2 起 user state 已迁到 ``AuthContext``，nickname/role
 *     由后端 ``GET /me`` 真实返回，``useAppStore.user`` 失去消费者。
 *
 * v0.7.2 行为：
 *   - nickname / role 来自 ``useAuth().user``，read-only 展示（编辑入口
 *     仍需后端 user 管理 API，本期不做）；
 *   - darkMode 暂时保留前端表单占位（无后端支持，仅本地 message 提示）。
 *
 * 该改动同步删除 ``useAppStore.user`` / ``useAppStore.setUser`` 字段，
 * 让前端 user state 单一源收口到 AuthContext。
 */
const Settings: React.FC = () => {
  const { t } = useTranslation(['settings', 'common'])
  const { user } = useAuth()

  const [form] = Form.useForm()

  const handleFinish = (_values: { name: string; role: string; darkMode: boolean }) => {
    // nickname / role 编辑能力暂未对接后端 user 管理 API；
    // 这里保留 message.success 视觉反馈，避免 form submit 静默无响应。
    message.success(t('settings.updated'))
  }

  return (
    <Space direction="vertical" size="large" className="w-full">
      <Card title={t('settings.title')}>
        <Form
          form={form}
          layout="vertical"
          initialValues={{
            name: user?.username ?? '',
            role: user?.role ?? '',
            darkMode: false,
          }}
          onFinish={handleFinish}
        >
          <Form.Item
            label={t('settings.nickname')}
            name="name"
            rules={[{ required: true, message: t('settings.validation.nicknameRequired') }]}
          >
            <Input placeholder={t('settings.nickname')} disabled />
          </Form.Item>

          <Form.Item
            label={t('settings.role')}
            name="role"
            rules={[{ required: true, message: t('settings.validation.roleRequired') }]}
          >
            <Select
              disabled
              options={[
                { label: t('settings.roleOptions.admin'), value: 'admin' },
                { label: t('settings.roleOptions.operator'), value: 'member' },
                { label: t('settings.roleOptions.guest'), value: 'viewer' },
              ]}
            />
          </Form.Item>

          <Form.Item
            label={t('settings.darkMode')}
            name="darkMode"
            valuePropName="checked"
            tooltip={t('settings.darkModeTooltip')}
          >
            <Switch />
          </Form.Item>

          <Form.Item>
            <Button type="primary" htmlType="submit">
              {t('common:save')}
            </Button>
          </Form.Item>
        </Form>
      </Card>

      <Card title="高级">
        <Link
          to="/settings/api-keys"
          data-testid="settings-api-keys-link"
          className="block"
        >
          <div className="flex items-center justify-between rounded border border-slate-200 bg-white p-4 transition hover:border-blue-400 hover:shadow-sm">
            <Space>
              <KeyOutlined style={{ fontSize: 20 }} />
              <div>
                <Title level={5} className="!m-0">
                  API Keys
                </Title>
                <Text type="secondary">
                  管理 SaaS 调用方密钥、配额与使用情况（仅 admin）
                </Text>
              </div>
            </Space>
            <RightOutlined />
          </div>
        </Link>
        <Divider className="!my-3" />
        <Text type="secondary" style={{ fontSize: 12 }}>
          TODO(P5)：接 RBAC 后用 useAuth().user.role / permissions 控制 API Keys 入口可见性。
        </Text>
      </Card>
    </Space>
  )
}

export default Settings
