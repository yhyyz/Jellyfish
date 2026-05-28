import { Card, Form, Input, Select, Switch, Button, message, Divider, Space, Typography } from 'antd'
import { KeyOutlined, RightOutlined } from '@ant-design/icons'
import { Link } from 'react-router-dom'
import { useAppStore } from '../store/useAppStore'
import { useTranslation } from 'react-i18next'

const { Title, Text } = Typography

const Settings: React.FC = () => {
  const { t } = useTranslation(['settings', 'common'])
  const user = useAppStore((state) => state.user)
  const setUser = useAppStore((state) => state.setUser)

  const [form] = Form.useForm()

  const handleFinish = (values: { name: string; role: string; darkMode: boolean }) => {
    setUser({ name: values.name, role: values.role })
    message.success(t('settings.updated'))
  }

  return (
    <Space direction="vertical" size="large" className="w-full">
      <Card title={t('settings.title')}>
        <Form
          form={form}
          layout="vertical"
          initialValues={{
            name: user.name,
            role: user.role,
            darkMode: false,
          }}
          onFinish={handleFinish}
        >
          <Form.Item
            label={t('settings.nickname')}
            name="name"
            rules={[{ required: true, message: t('settings.validation.nicknameRequired') }]}
          >
            <Input placeholder={t('settings.nickname')} />
          </Form.Item>

          <Form.Item
            label={t('settings.role')}
            name="role"
            rules={[{ required: true, message: t('settings.validation.roleRequired') }]}
          >
            <Select
              options={[
                { label: t('settings.roleOptions.admin'), value: t('settings.roleOptions.admin') },
                {
                  label: t('settings.roleOptions.operator'),
                  value: t('settings.roleOptions.operator'),
                },
                { label: t('settings.roleOptions.guest'), value: t('settings.roleOptions.guest') },
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
          TODO(P5)：接 RBAC 后用 user.role / permissions 控制 API Keys 入口可见性。
        </Text>
      </Card>
    </Space>
  )
}

export default Settings

