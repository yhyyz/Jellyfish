/**
 * 用户管理页 (P5 W32-T10)。
 *
 * admin-only 页面（路由层包 ProtectedRoute requiredRole=admin）：
 * - antd Table 显示 users (id / username / email / role / is_active / created_at / actions)
 * - 顶部 "新建用户" 按钮 → 弹 Modal 表单
 * - 行级 actions: 编辑 (改 role/email/is_active) / 重置密码 / 禁用
 * - 4 locale i18n
 */

import { DeleteOutlined, EditOutlined, KeyOutlined, PlusOutlined } from '@ant-design/icons'
import {
  Badge,
  Button,
  Form,
  Input,
  Modal,
  Popconfirm,
  Select,
  Space,
  Switch,
  Table,
  Tag,
  Typography,
  message,
} from 'antd'
import type { TableProps } from 'antd'
import { useCallback, useEffect, useMemo, useState } from 'react'
import { useTranslation } from 'react-i18next'
import {
  ApiError,
  SettingsUsersService,
  type UserCreate,
  type UserRead,
  type UserUpdate,
} from '../../services/generated'
import { useAuth } from '../../contexts/AuthContext'

type RoleKey = 'admin' | 'member' | 'viewer'

interface CreateFormValues extends UserCreate {}

interface EditFormValues {
  email?: string
  role?: RoleKey
  is_active?: boolean
}

interface ResetPasswordValues {
  password: string
}

export default function UsersAdminPage(): React.ReactElement {
  const { t } = useTranslation('settings')
  const { user: currentUser } = useAuth()
  const [items, setItems] = useState<UserRead[]>([])
  const [loading, setLoading] = useState<boolean>(false)
  const [createOpen, setCreateOpen] = useState<boolean>(false)
  const [editTarget, setEditTarget] = useState<UserRead | null>(null)
  const [resetTarget, setResetTarget] = useState<UserRead | null>(null)
  const [createForm] = Form.useForm<CreateFormValues>()
  const [editForm] = Form.useForm<EditFormValues>()
  const [resetForm] = Form.useForm<ResetPasswordValues>()

  const reload = useCallback(async () => {
    setLoading(true)
    try {
      const resp = await SettingsUsersService.listUsersEndpointApiV1SettingsUsersGet({})
      setItems(resp?.data?.items ?? [])
    } finally {
      setLoading(false)
    }
  }, [])

  useEffect(() => {
    void reload()
  }, [reload])

  const handleCreate = useCallback(async () => {
    const values = await createForm.validateFields()
    try {
      await SettingsUsersService.createUserEndpointApiV1SettingsUsersPost({
        requestBody: values,
      })
      message.success(t('users.messages.created'))
      setCreateOpen(false)
      createForm.resetFields()
      await reload()
    } catch (err) {
      if (err instanceof ApiError && err.status === 409) {
        message.error(t('users.messages.conflict'))
        return
      }
      throw err
    }
  }, [createForm, reload, t])

  const handleEdit = useCallback(async () => {
    if (!editTarget) return
    const values = await editForm.validateFields()
    const payload: UserUpdate = {}
    if (values.email !== undefined && values.email !== editTarget.email) payload.email = values.email
    if (values.role !== undefined) payload.role = values.role
    if (values.is_active !== undefined) payload.is_active = values.is_active

    await SettingsUsersService.updateUserEndpointApiV1SettingsUsersUserIdPatch({
      userId: editTarget.id,
      requestBody: payload,
    })
    message.success(t('users.messages.updated'))
    setEditTarget(null)
    editForm.resetFields()
    await reload()
  }, [editTarget, editForm, reload, t])

  const handleResetPassword = useCallback(async () => {
    if (!resetTarget) return
    const values = await resetForm.validateFields()
    await SettingsUsersService.updateUserEndpointApiV1SettingsUsersUserIdPatch({
      userId: resetTarget.id,
      requestBody: { password: values.password },
    })
    message.success(t('users.messages.updated'))
    setResetTarget(null)
    resetForm.resetFields()
  }, [resetTarget, resetForm, t])

  const handleDelete = useCallback(
    async (record: UserRead) => {
      if (currentUser && record.username === currentUser.username) {
        message.error(t('users.deleteSelfNotAllowed'))
        return
      }
      try {
        await SettingsUsersService.softDeleteUserEndpointApiV1SettingsUsersUserIdDelete(
          { userId: record.id },
        )
        message.success(t('users.messages.deleted'))
        await reload()
      } catch (err) {
        if (err instanceof ApiError && err.status === 400) {
          message.error(t('users.deleteSelfNotAllowed'))
          return
        }
        throw err
      }
    },
    [currentUser, reload, t],
  )

  const columns: TableProps<UserRead>['columns'] = useMemo(
    () => [
      { title: t('users.fields.username'), dataIndex: 'username', key: 'username' },
      { title: t('users.fields.email'), dataIndex: 'email', key: 'email' },
      {
        title: t('users.fields.role'),
        dataIndex: 'role',
        key: 'role',
        render: (role: RoleKey) => {
          const colorMap: Record<RoleKey, string> = {
            admin: 'red',
            member: 'blue',
            viewer: 'default',
          }
          return <Tag color={colorMap[role]}>{t(`users.roles.${role}`)}</Tag>
        },
      },
      {
        title: t('users.fields.isActive'),
        dataIndex: 'is_active',
        key: 'is_active',
        render: (active: boolean) => (
          <Badge status={active ? 'success' : 'default'} text={active ? 'ON' : 'OFF'} />
        ),
      },
      {
        title: t('users.fields.createdAt'),
        dataIndex: 'created_at',
        key: 'created_at',
        render: (v: string) => (v ? new Date(v).toLocaleString() : '-'),
      },
      {
        title: '',
        key: 'actions',
        render: (_: unknown, record: UserRead) => (
          <Space size="small">
            <Button
              type="link"
              icon={<EditOutlined />}
              onClick={() => {
                setEditTarget(record)
                editForm.setFieldsValue({
                  email: record.email,
                  role: record.role as RoleKey,
                  is_active: record.is_active,
                })
              }}
            >
              {t('users.actions.edit')}
            </Button>
            <Button
              type="link"
              icon={<KeyOutlined />}
              onClick={() => {
                setResetTarget(record)
                resetForm.resetFields()
              }}
            >
              {t('users.actions.resetPassword')}
            </Button>
            <Popconfirm
              title={t('users.deleteConfirm')}
              onConfirm={() => handleDelete(record)}
            >
              <Button type="link" danger icon={<DeleteOutlined />}>
                {record.is_active
                  ? t('users.actions.delete')
                  : t('users.actions.enable')}
              </Button>
            </Popconfirm>
          </Space>
        ),
      },
    ],
    [t, editForm, resetForm, handleDelete],
  )

  return (
    <div style={{ padding: 24 }}>
      <Space direction="vertical" size="middle" style={{ width: '100%' }}>
        <Space style={{ justifyContent: 'space-between', width: '100%' }}>
          <Typography.Title level={3} style={{ margin: 0 }}>
            {t('users.title')}
          </Typography.Title>
          <Button
            type="primary"
            icon={<PlusOutlined />}
            onClick={() => {
              setCreateOpen(true)
              createForm.resetFields()
            }}
          >
            {t('users.create')}
          </Button>
        </Space>

        <Table<UserRead>
          rowKey="id"
          loading={loading}
          columns={columns}
          dataSource={items}
          pagination={false}
        />
      </Space>

      <Modal
        title={t('users.create')}
        open={createOpen}
        onOk={handleCreate}
        onCancel={() => setCreateOpen(false)}
        destroyOnClose
      >
        <Form<CreateFormValues> form={createForm} layout="vertical">
          <Form.Item
            label={t('users.fields.username')}
            name="username"
            rules={[{ required: true }]}
          >
            <Input />
          </Form.Item>
          <Form.Item
            label={t('users.fields.email')}
            name="email"
            rules={[{ required: true, type: 'email' }]}
          >
            <Input />
          </Form.Item>
          <Form.Item
            label={t('users.fields.password')}
            name="password"
            rules={[{ required: true, min: 6 }]}
          >
            <Input.Password placeholder={t('users.fields.passwordPlaceholder')} />
          </Form.Item>
          <Form.Item
            label={t('users.fields.role')}
            name="role"
            initialValue="member"
            rules={[{ required: true }]}
          >
            <Select
              options={[
                { value: 'admin', label: t('users.roles.admin') },
                { value: 'member', label: t('users.roles.member') },
                { value: 'viewer', label: t('users.roles.viewer') },
              ]}
            />
          </Form.Item>
        </Form>
      </Modal>

      <Modal
        title={t('users.edit')}
        open={editTarget !== null}
        onOk={handleEdit}
        onCancel={() => setEditTarget(null)}
        destroyOnClose
      >
        <Form<EditFormValues> form={editForm} layout="vertical">
          <Form.Item label={t('users.fields.email')} name="email" rules={[{ type: 'email' }]}>
            <Input />
          </Form.Item>
          <Form.Item label={t('users.fields.role')} name="role">
            <Select
              options={[
                { value: 'admin', label: t('users.roles.admin') },
                { value: 'member', label: t('users.roles.member') },
                { value: 'viewer', label: t('users.roles.viewer') },
              ]}
            />
          </Form.Item>
          <Form.Item
            label={t('users.fields.isActive')}
            name="is_active"
            valuePropName="checked"
          >
            <Switch />
          </Form.Item>
        </Form>
      </Modal>

      <Modal
        title={t('users.actions.resetPassword')}
        open={resetTarget !== null}
        onOk={handleResetPassword}
        onCancel={() => setResetTarget(null)}
        destroyOnClose
      >
        <Form<ResetPasswordValues> form={resetForm} layout="vertical">
          <Form.Item
            label={t('users.fields.password')}
            name="password"
            rules={[{ required: true, min: 6 }]}
          >
            <Input.Password placeholder={t('users.fields.passwordPlaceholder')} />
          </Form.Item>
        </Form>
      </Modal>
    </div>
  )
}
