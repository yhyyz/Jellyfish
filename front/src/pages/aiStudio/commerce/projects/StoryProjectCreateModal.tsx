/**
 * 剧情带货项目创建弹窗。
 *
 * 单弹窗一次性创建 Project（kind=commerce_story）+ CommerceStoryConfig，
 * 后端服务在单事务内完成两表 INSERT。表单基于 antd Form.useForm，提交
 * 后通过 useCreateStoryProject mutation 落库，成功后导航到对应工作台。
 *
 * 字段范围（P1）：
 * - 项目核心：name / description / style / visual_style / seed
 * - 带货配置：target_platform / target_duration_sec / formula_id /
 *   compliance_region
 * - P2 字段（archetype / tone_grid / audience_override / target_kpi）
 *   暂不暴露在表单中，留待 P2 再开放。
 */
import React, { useEffect, useMemo } from 'react'
import { useNavigate } from 'react-router-dom'
import { Modal, Form, Input, Select, InputNumber, Button, Space, message } from 'antd'
import { useCreateStoryProject, useStoryFormulaList } from './queries'
import type {
  ComplianceRegion,
  Platform,
  ProjectStyle,
  ProjectVisualStyle,
  StoryFormulaRead,
  StoryProjectCreate,
} from '../../../../services/generated'

export interface StoryProjectCreateModalProps {
  /** 是否展示弹窗（受控） */
  open: boolean
  /** 关闭弹窗回调（取消 / 完成均会触发） */
  onClose: () => void
  /** 创建成功后回调（外层可借此刷新数据，本组件已主动失效缓存） */
  onCreated?: (newProjectId: string) => void
}

/** 创建表单字段的内部类型，与 antd Form values 对齐 */
interface CreateFormValues {
  name: string
  description?: string
  style: ProjectStyle
  visual_style: ProjectVisualStyle
  target_platform: Platform
  target_duration_sec: number
  formula_id?: string
  compliance_region: ComplianceRegion
  seed: number
}

/** 题材选项：与 ProjectStyle 枚举保持一致 */
const STYLE_OPTIONS: { value: ProjectStyle; label: string }[] = [
  { value: '真人都市', label: '真人都市' },
  { value: '动漫3D', label: '动漫 3D' },
]

/**
 * 视觉风格选项。
 *
 * 注意：当前生成的 ProjectVisualStyle 类型仅含 `'现实'`，但运行时后端
 * 接受更多值（通过 ProjectLobby 中 `as any` 验证），此处暴露
 * `live_action / anime` 以贴合带货剧情的产品文案，提交时通过
 * `as ProjectVisualStyle` 抑制类型差异。
 */
const VISUAL_STYLE_OPTIONS: { value: string; label: string }[] = [
  { value: 'live_action', label: '真人' },
  { value: 'anime', label: '动漫' },
]

/** 平台选项：与 Platform 枚举严格对齐 */
const PLATFORM_OPTIONS: { value: Platform; label: string }[] = [
  { value: 'douyin', label: '抖音' },
  { value: 'kuaishou', label: '快手' },
  { value: 'xiaohongshu', label: '小红书' },
  { value: 'youtube', label: 'YouTube' },
  { value: 'tiktok', label: 'TikTok' },
]

/** 目标时长选项：覆盖 30s 短带货到 180s 长解说 */
const DURATION_OPTIONS: { value: number; label: string }[] = [
  { value: 30, label: '30 秒' },
  { value: 45, label: '45 秒' },
  { value: 60, label: '60 秒' },
  { value: 90, label: '90 秒' },
  { value: 120, label: '120 秒' },
  { value: 180, label: '180 秒' },
]

/** 合规地域选项：与 ComplianceRegion 枚举对齐 */
const COMPLIANCE_REGION_OPTIONS: { value: ComplianceRegion; label: string }[] = [
  { value: 'cn_mainland', label: '中国大陆' },
  { value: 'hk_tw', label: '港澳台' },
  { value: 'overseas', label: '海外' },
]

/**
 * 生成一个项目 ID（业务方传入）。
 *
 * 优先 `crypto.randomUUID`；老浏览器降级为时间戳 + 随机片段。
 * 与 ProjectLobby 中的 newProjectId 行为保持一致。
 */
function newProjectId(): string {
  if (typeof crypto !== 'undefined' && typeof crypto.randomUUID === 'function') {
    return crypto.randomUUID()
  }
  return `csp_${Date.now()}_${Math.random().toString(16).slice(2)}`
}

const StoryProjectCreateModal: React.FC<StoryProjectCreateModalProps> = ({
  open,
  onClose,
  onCreated,
}) => {
  const navigate = useNavigate()
  const [form] = Form.useForm<CreateFormValues>()
  const createMutation = useCreateStoryProject()
  // 表单需要 formula 列表；不区分 region，列表 ≤10 条无性能压力。
  const { data: formulas, isLoading: formulasLoading } = useStoryFormulaList()

  /**
   * 初始默认值：
   * - 视觉风格 / 平台 / 时长 / 合规地域均按产品默认设置。
   * - 种子默认随机，复用 ProjectLobby 的策略保持视觉调性可重现。
   */
  const initialValues = useMemo<Partial<CreateFormValues>>(
    () => ({
      style: '真人都市' as ProjectStyle,
      visual_style: 'live_action' as unknown as ProjectVisualStyle,
      target_platform: 'douyin',
      target_duration_sec: 60,
      compliance_region: 'cn_mainland',
      seed: Math.floor(Math.random() * 99999),
    }),
    [],
  )

  // 弹窗每次打开重新生成默认种子，避免缓存导致每次都一样。
  useEffect(() => {
    if (open) {
      form.resetFields()
      form.setFieldsValue({
        ...initialValues,
        seed: Math.floor(Math.random() * 99999),
      })
    }
  }, [open, form, initialValues])

  /**
   * 提交处理：构造 StoryProjectCreate 请求体，调用统一创建端点。
   *
   * 成功后：
   * 1. 弹出成功提示
   * 2. 触发外部 onCreated 回调（如刷新外层）
   * 3. 关闭弹窗
   * 4. 跳转到 /commerce/projects/:id（StoryWorkbench，由 W8-T3 提供）
   */
  const handleFinish = async (values: CreateFormValues) => {
    try {
      const id = newProjectId()
      const body: StoryProjectCreate = {
        id,
        name: values.name,
        description: values.description ?? '',
        style: values.style,
        visual_style: values.visual_style,
        seed: values.seed,
        progress: 0,
        config: {
          target_platform: values.target_platform,
          target_duration_sec: values.target_duration_sec,
          formula_id: values.formula_id ?? null,
          compliance_region: values.compliance_region,
        },
      }
      const created = await createMutation.mutateAsync(body)
      message.success('剧情带货项目创建成功')
      onCreated?.(created.id)
      onClose()
      navigate(`/commerce/projects/${created.id}`)
    } catch {
      message.error('创建失败，请稍后重试')
    }
  }

  return (
    <Modal
      title="新建剧情带货项目"
      open={open}
      onCancel={onClose}
      footer={null}
      width={560}
      destroyOnClose
    >
      <Form<CreateFormValues>
        form={form}
        layout="vertical"
        initialValues={initialValues}
        onFinish={handleFinish}
      >
        <Form.Item
          name="name"
          label="项目名称"
          rules={[{ required: true, message: '请输入项目名称' }]}
        >
          <Input placeholder="例如：某面膜小红书 60 秒带货" maxLength={64} />
        </Form.Item>
        <Form.Item name="description" label="项目描述（选填）">
          <Input.TextArea rows={3} placeholder="一句话说明商品定位与目标人群" />
        </Form.Item>

        <Space.Compact block>
          <Form.Item
            name="style"
            label="题材"
            rules={[{ required: true, message: '请选择题材' }]}
            className="flex-1"
          >
            <Select options={STYLE_OPTIONS} />
          </Form.Item>
          <Form.Item
            name="visual_style"
            label="视觉风格"
            rules={[{ required: true, message: '请选择视觉风格' }]}
            className="ml-2 flex-1"
          >
            <Select options={VISUAL_STYLE_OPTIONS} />
          </Form.Item>
        </Space.Compact>

        <Space.Compact block>
          <Form.Item
            name="target_platform"
            label="目标平台"
            rules={[{ required: true, message: '请选择目标平台' }]}
            className="flex-1"
          >
            <Select options={PLATFORM_OPTIONS} />
          </Form.Item>
          <Form.Item
            name="target_duration_sec"
            label="目标时长"
            rules={[{ required: true, message: '请选择目标时长' }]}
            className="ml-2 flex-1"
          >
            <Select options={DURATION_OPTIONS} />
          </Form.Item>
        </Space.Compact>

        <Form.Item
          name="formula_id"
          label="剧情公式"
          tooltip="选择一个预置剧情公式将用于脚本生成；可留空，由 Agent 自动选用"
        >
          <Select
            allowClear
            placeholder={formulasLoading ? '加载中…' : '请选择剧情公式'}
            options={(formulas ?? []).map((f: StoryFormulaRead) => ({
              value: f.id,
              label: `${f.name}（${f.typical_duration_sec}s · ${f.typical_shot_count} 镜）`,
            }))}
          />
        </Form.Item>

        <Space.Compact block>
          <Form.Item
            name="compliance_region"
            label="合规地域"
            rules={[{ required: true, message: '请选择合规地域' }]}
            className="flex-1"
          >
            <Select options={COMPLIANCE_REGION_OPTIONS} />
          </Form.Item>
          <Form.Item
            name="seed"
            label="全局种子"
            tooltip="固定种子可保证视觉调性可复现"
            className="ml-2 flex-1"
            rules={[{ required: true, message: '请输入种子' }]}
          >
            <InputNumber min={0} className="w-full" />
          </Form.Item>
        </Space.Compact>

        <Form.Item className="mb-0">
          <Space>
            <Button onClick={onClose}>取消</Button>
            <Button type="primary" htmlType="submit" loading={createMutation.isPending}>
              创建并进入
            </Button>
          </Space>
        </Form.Item>
      </Form>
    </Modal>
  )
}

export default StoryProjectCreateModal
