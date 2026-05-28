/**
 * SubtitleStyleEditor — 项目级字幕样式编辑器（P5 W30-T5）。
 *
 * 替换 W20-T6 SubtitleStyleLibrary 中的"项目级覆盖占位 Alert"：
 *
 * - 系统级行（`project_id=null`）以**只读**形态展示，所有字段 disabled，
 *   头部 `Tag color=blue` 显示 `subtitleStyleEditor.systemBadge`，底部
 *   仅保留 `subtitleStyleEditor.cloneBtn`（克隆为项目覆盖）。
 * - 项目级行（`project_id=projectId`）走完整编辑模式，底部 OK 触发
 *   `subtitleStyleEditor.saveBtn`（POST 新建 / PATCH 更新），并额外暴露
 *   `subtitleStyleEditor.resetBtn`（DELETE 项目级行，回退系统模板）。
 * - 新建模式（创建空白项目级行）：`mode='create'`，无 ID，OK 走 POST。
 *
 * 字段集与后端 `ProjectSubtitleStyleCreateInput` 严格对齐：
 *   name / description / language_code / format / font_family / font_size /
 *   primary_colour / secondary_colour / outline_colour / back_colour /
 *   bold / italic / border_style / outline / shadow / alignment /
 *   margin_l / margin_r / margin_v / play_res_x / play_res_y /
 *   font_fallback_chain。
 *
 * 颜色字段在 UI 上以 `#RRGGBB` 形式供 antd ColorPicker 编辑，提交前
 * 通过 W20-T3 已落地的 `colorCodec.toAss` 转 `&HAABBGGRR`；从后端读到的
 * `&HAABBGGRR` 通过 `colorCodec.fromAss` 还原到 UI。
 *
 * 实时预览：右侧展示 mock 字幕渲染块，颜色 / 字号 / 字体 / 对齐随用户输入
 * 即时更新；不追求 ASS 全保真，只给体感参考。
 *
 * 与 antd `Modal` jsdom close-animation quirk 的契合策略：
 * - 测试侧统一用 `findByRole('dialog')` / `waitFor`，不做同步断言；
 * - 内部 `destroyOnClose` 强制每次重开时重置 form 状态，避免 stale 缓存。
 */
import React, { useEffect, useMemo, useState } from 'react'
import {
  Alert,
  Button,
  ColorPicker,
  Divider,
  Form,
  Input,
  InputNumber,
  Modal,
  Popconfirm,
  Radio,
  Select,
  Space,
  Switch,
  Tag,
  message as antdMessage,
} from 'antd'
import type { Color } from 'antd/es/color-picker'
import { useTranslation } from 'react-i18next'

import { CommerceSubtitleStylesService } from '../../../../services/generated'
import type {
  ProjectSubtitleStyleCreateInput,
  ProjectSubtitleStyleUpdateInput,
  SubtitleStyleRead,
} from '../../../../services/generated'
import { fromAss, toAss } from '../projects/components/_subtitle/colorCodec'

/** 编辑器三种业务态：新建、项目级编辑、系统级只读。 */
export type EditorMode = 'create' | 'projectEdit' | 'systemReadonly'

export interface SubtitleStyleEditorProps {
  /** 是否打开 */
  open: boolean
  /** 关闭回调（成功 / 取消通用） */
  onClose: () => void
  /** 当前 project ID，所有项目级 CRUD 操作的归属 */
  projectId: string
  /** 当前编辑的样式行（系统级或项目级）；新建模式传 null */
  style: SubtitleStyleRead | null
  /** 提交（保存 / 克隆 / 重置）成功回调，上层负责刷新列表 */
  onMutated?: () => void
}

/** UI 表单内部使用的字段，颜色字段全部 web hex。 */
interface EditorFormValues {
  name: string
  description: string
  language_code: string
  format: 'ass' | 'srt' | 'vtt'
  font_family: string
  font_size: number
  primary_colour_hex: string
  secondary_colour_hex: string
  outline_colour_hex: string
  back_colour_hex: string
  bold: boolean
  italic: boolean
  border_style: 1 | 3
  outline: number
  shadow: number
  alignment: number
  margin_l: number
  margin_r: number
  margin_v: number
  play_res_x: number
  play_res_y: number
  font_fallback_chain: string[]
}

/** 系统级 seed 默认 fallback 链，新建模式时给个合理初值。 */
const DEFAULT_FALLBACK_CHAIN = [
  'Source Han Sans CN Heavy',
  'PingFang SC',
  'Arial',
] as const

/** ASS Alignment numpad 1-9 → 选项 i18n key 映射。 */
const ALIGNMENT_OPTIONS = [
  { value: 1, key: 'subtitleStyleEditor.alignment.bottomLeft' },
  { value: 2, key: 'subtitleStyleEditor.alignment.bottomCenter' },
  { value: 3, key: 'subtitleStyleEditor.alignment.bottomRight' },
  { value: 5, key: 'subtitleStyleEditor.alignment.middleCenter' },
  { value: 8, key: 'subtitleStyleEditor.alignment.topCenter' },
] as const

/** 容错 fromAss：ColorPicker 不能让单条非法 seed 把整页打死。 */
function safeFromAss(literal: string | undefined | null, fallback: string): string {
  if (!literal) return fallback
  try {
    return fromAss(literal)
  } catch {
    return fallback
  }
}

/** 把 ORM 行转成 form 默认值。 */
function styleToFormValues(
  style: SubtitleStyleRead | null,
): EditorFormValues {
  return {
    name: style?.name ?? '',
    description: style?.description ?? '',
    language_code: style?.language_code ?? 'zh-CN',
    format: ((style?.format as EditorFormValues['format']) ?? 'ass'),
    font_family: style?.font_family ?? 'Source Han Sans CN Heavy',
    font_size: style?.font_size ?? 60,
    primary_colour_hex: safeFromAss(style?.primary_colour, '#FFFFFF'),
    secondary_colour_hex: safeFromAss(style?.secondary_colour, '#FFFFFF'),
    outline_colour_hex: safeFromAss(style?.outline_colour, '#000000'),
    back_colour_hex: safeFromAss(style?.back_colour, '#000000'),
    bold: style?.bold ?? true,
    italic: style?.italic ?? false,
    border_style: ((style?.border_style as 1 | 3) ?? 1),
    outline: style?.outline ?? 3,
    shadow: style?.shadow ?? 1,
    alignment: style?.alignment ?? 2,
    margin_l: style?.margin_l ?? 60,
    margin_r: style?.margin_r ?? 60,
    margin_v: style?.margin_v ?? 200,
    play_res_x: style?.play_res_x ?? 1080,
    play_res_y: style?.play_res_y ?? 1920,
    font_fallback_chain: style?.font_fallback_chain ?? [...DEFAULT_FALLBACK_CHAIN],
  }
}

/** 把 form 值转成 ProjectSubtitleStyleCreateInput / UpdateInput。 */
function formToPayload(
  values: EditorFormValues,
): ProjectSubtitleStyleCreateInput {
  return {
    name: values.name.trim(),
    description: values.description?.trim() || null,
    language_code: values.language_code,
    format: values.format,
    font_family: values.font_family,
    font_size: values.font_size,
    primary_colour: toAss(values.primary_colour_hex),
    secondary_colour: toAss(values.secondary_colour_hex),
    outline_colour: toAss(values.outline_colour_hex),
    back_colour: toAss(values.back_colour_hex),
    bold: values.bold,
    italic: values.italic,
    border_style: values.border_style,
    outline: values.outline,
    shadow: values.shadow,
    alignment: values.alignment,
    margin_l: values.margin_l,
    margin_r: values.margin_r,
    margin_v: values.margin_v,
    play_res_x: values.play_res_x,
    play_res_y: values.play_res_y,
    font_fallback_chain: values.font_fallback_chain,
  }
}

/** 提取 antd ColorPicker 的 hex 值；统一返回 6 位 #RRGGBB（去 alpha）。 */
function pickHex(value: Color | string | undefined, fallback: string): string {
  if (!value) return fallback
  if (typeof value === 'string') return value.startsWith('#') ? value : `#${value}`
  const hex = value.toHexString()
  return hex.length >= 7 ? hex.slice(0, 7) : hex
}

interface PreviewBlockProps {
  values: EditorFormValues
  text: string
}

/** 实时预览面板（mock 渲染，不追求 ASS 保真）。 */
const PreviewBlock: React.FC<PreviewBlockProps> = ({ values, text }) => {
  const justifyMap: Record<number, React.CSSProperties['justifyContent']> = {
    1: 'flex-start',
    2: 'center',
    3: 'flex-end',
    5: 'center',
    8: 'center',
  }
  const alignItemsMap: Record<number, React.CSSProperties['alignItems']> = {
    1: 'flex-end',
    2: 'flex-end',
    3: 'flex-end',
    5: 'center',
    8: 'flex-start',
  }
  return (
    <div
      data-testid="subtitle-style-editor-preview"
      className="relative rounded bg-gray-900"
      style={{
        width: '100%',
        height: 240,
        display: 'flex',
        justifyContent: justifyMap[values.alignment] ?? 'center',
        alignItems: alignItemsMap[values.alignment] ?? 'flex-end',
        padding: 16,
        overflow: 'hidden',
      }}
    >
      <span
        style={{
          fontFamily: values.font_family,
          fontSize: Math.max(12, Math.round(values.font_size / 3)),
          color: values.primary_colour_hex,
          fontWeight: values.bold ? 700 : 400,
          fontStyle: values.italic ? 'italic' : 'normal',
          WebkitTextStroke:
            values.outline > 0
              ? `${values.outline / 2}px ${values.outline_colour_hex}`
              : undefined,
          textShadow:
            values.shadow > 0
              ? `${values.shadow}px ${values.shadow}px 0 ${values.back_colour_hex}`
              : undefined,
        }}
      >
        {text}
      </span>
    </div>
  )
}

/**
 * 主组件：根据 props.style.project_id 自动判断 mode 并切换 UI 行为。
 */
const SubtitleStyleEditor: React.FC<SubtitleStyleEditorProps> = ({
  open,
  onClose,
  projectId,
  style,
  onMutated,
}) => {
  const { t } = useTranslation('commerce')
  const [form] = Form.useForm<EditorFormValues>()
  const [submitting, setSubmitting] = useState(false)
  const [previewValues, setPreviewValues] = useState<EditorFormValues>(() =>
    styleToFormValues(style),
  )

  const mode: EditorMode = useMemo(() => {
    if (!style) return 'create'
    if (style.project_id == null) return 'systemReadonly'
    return 'projectEdit'
  }, [style])

  const isReadonly = mode === 'systemReadonly'

  useEffect(() => {
    if (open) {
      const next = styleToFormValues(style)
      form.setFieldsValue(next)
      setPreviewValues(next)
    }
  }, [open, style, form])

  const onValuesChange = (
    _changed: Partial<EditorFormValues>,
    all: EditorFormValues,
  ) => {
    setPreviewValues(all)
  }

  const handleSave = async () => {
    if (isReadonly) return
    let values: EditorFormValues
    try {
      values = await form.validateFields()
    } catch {
      return
    }
    const payload = formToPayload(values)
    setSubmitting(true)
    try {
      if (mode === 'create') {
        await CommerceSubtitleStylesService.createProjectSubtitleStyleEndpointApiV1CommerceProjectsProjectIdSubtitleStylesPost(
          { projectId, requestBody: payload },
        )
        antdMessage.success(t('subtitleStyleEditor.saveSuccess'))
      } else if (mode === 'projectEdit' && style) {
        await CommerceSubtitleStylesService.updateProjectSubtitleStyleEndpointApiV1CommerceProjectsProjectIdSubtitleStylesStyleIdPatch(
          {
            projectId,
            styleId: style.id,
            requestBody: payload as unknown as ProjectSubtitleStyleUpdateInput,
          },
        )
        antdMessage.success(t('subtitleStyleEditor.saveSuccess'))
      }
      onMutated?.()
      onClose()
    } catch (err) {
      const detail =
        err instanceof Error ? err.message : t('subtitleStyleEditor.saveFailed')
      antdMessage.error(detail)
    } finally {
      setSubmitting(false)
    }
  }

  /** 系统级 → 克隆为项目覆盖：拷贝当前 form 字段 → POST 项目级。 */
  const handleCloneToProject = async () => {
    let values: EditorFormValues
    try {
      values = await form.validateFields()
    } catch {
      return
    }
    setSubmitting(true)
    try {
      await CommerceSubtitleStylesService.createProjectSubtitleStyleEndpointApiV1CommerceProjectsProjectIdSubtitleStylesPost(
        { projectId, requestBody: formToPayload(values) },
      )
      antdMessage.success(t('subtitleStyleEditor.cloneSuccess'))
      onMutated?.()
      onClose()
    } catch (err) {
      const detail =
        err instanceof Error ? err.message : t('subtitleStyleEditor.cloneFailed')
      antdMessage.error(detail)
    } finally {
      setSubmitting(false)
    }
  }

  /** 项目级 → 重置为系统模板：DELETE 项目级行。 */
  const handleResetToSystem = async () => {
    if (!style || style.project_id == null) return
    setSubmitting(true)
    try {
      await CommerceSubtitleStylesService.deleteProjectSubtitleStyleEndpointApiV1CommerceProjectsProjectIdSubtitleStylesStyleIdDelete(
        { projectId, styleId: style.id },
      )
      antdMessage.success(t('subtitleStyleEditor.resetSuccess'))
      onMutated?.()
      onClose()
    } catch (err) {
      const detail =
        err instanceof Error ? err.message : t('subtitleStyleEditor.resetFailed')
      antdMessage.error(detail)
    } finally {
      setSubmitting(false)
    }
  }

  const titleNode = (
    <Space>
      <span>
        {mode === 'create'
          ? t('subtitleStyleEditor.createTitle')
          : t('subtitleStyleEditor.editTitle')}
      </span>
      {mode === 'systemReadonly' && (
        <Tag color="blue">{t('subtitleStyleEditor.systemBadge')}</Tag>
      )}
      {mode === 'projectEdit' && (
        <Tag color="green">{t('subtitleStyleEditor.projectBadge')}</Tag>
      )}
    </Space>
  )

  const footerNode = (
    <Space>
      <Button onClick={onClose} disabled={submitting}>
        {t('subtitleStyleEditor.cancelBtn')}
      </Button>
      {mode === 'systemReadonly' && (
        <Button type="primary" onClick={handleCloneToProject} loading={submitting}>
          {t('subtitleStyleEditor.cloneBtn')}
        </Button>
      )}
      {mode === 'projectEdit' && (
        <>
          <Popconfirm
            title={t('subtitleStyleEditor.resetConfirm')}
            okText={t('subtitleStyleEditor.resetOk')}
            cancelText={t('subtitleStyleEditor.cancelBtn')}
            onConfirm={handleResetToSystem}
          >
            <Button danger disabled={submitting}>
              {t('subtitleStyleEditor.resetBtn')}
            </Button>
          </Popconfirm>
          <Button type="primary" onClick={handleSave} loading={submitting}>
            {t('subtitleStyleEditor.saveBtn')}
          </Button>
        </>
      )}
      {mode === 'create' && (
        <Button type="primary" onClick={handleSave} loading={submitting}>
          {t('subtitleStyleEditor.saveBtn')}
        </Button>
      )}
    </Space>
  )

  return (
    <Modal
      open={open}
      onCancel={onClose}
      title={titleNode}
      footer={footerNode}
      destroyOnClose
      width={920}
      maskClosable={false}
    >
      {isReadonly && (
        <Alert
          type="info"
          showIcon
          message={t('subtitleStyleEditor.immutableHint')}
          className="mb-3"
        />
      )}

      <div className="grid grid-cols-1 gap-4 md:grid-cols-2">
        <Form
          form={form}
          layout="vertical"
          disabled={isReadonly}
          initialValues={styleToFormValues(style)}
          onValuesChange={onValuesChange}
          data-testid="subtitle-style-editor-form"
        >
          <Form.Item
            label={t('subtitleStyleEditor.fields.name')}
            name="name"
            rules={[{ required: true, max: 255 }]}
          >
            <Input maxLength={255} />
          </Form.Item>
          <Form.Item
            label={t('subtitleStyleEditor.fields.description')}
            name="description"
          >
            <Input.TextArea rows={2} maxLength={2048} />
          </Form.Item>
          <Form.Item
            label={t('subtitleStyleEditor.fields.fontFamily')}
            name="font_family"
            rules={[{ required: true, max: 128 }]}
          >
            <Input />
          </Form.Item>
          <Form.Item
            label={t('subtitleStyleEditor.fields.fontSize')}
            name="font_size"
            rules={[{ required: true, type: 'number', min: 16, max: 200 }]}
          >
            <InputNumber min={16} max={200} className="w-full" />
          </Form.Item>

          <Divider className="my-2" />

          <Form.Item
            label={t('subtitleStyleEditor.fields.primaryColour')}
            name="primary_colour_hex"
            getValueFromEvent={(value: Color | string) =>
              pickHex(value, '#FFFFFF')
            }
          >
            <ColorPicker disabledAlpha />
          </Form.Item>
          <Form.Item
            label={t('subtitleStyleEditor.fields.outlineColour')}
            name="outline_colour_hex"
            getValueFromEvent={(value: Color | string) =>
              pickHex(value, '#000000')
            }
          >
            <ColorPicker disabledAlpha />
          </Form.Item>
          <Form.Item
            label={t('subtitleStyleEditor.fields.secondaryColour')}
            name="secondary_colour_hex"
            getValueFromEvent={(value: Color | string) =>
              pickHex(value, '#FFFFFF')
            }
          >
            <ColorPicker disabledAlpha />
          </Form.Item>
          <Form.Item
            label={t('subtitleStyleEditor.fields.backColour')}
            name="back_colour_hex"
            getValueFromEvent={(value: Color | string) =>
              pickHex(value, '#000000')
            }
          >
            <ColorPicker disabledAlpha />
          </Form.Item>

          <Divider className="my-2" />

          <Space size="large" className="mb-2">
            <Form.Item
              label={t('subtitleStyleEditor.fields.bold')}
              name="bold"
              valuePropName="checked"
            >
              <Switch />
            </Form.Item>
            <Form.Item
              label={t('subtitleStyleEditor.fields.italic')}
              name="italic"
              valuePropName="checked"
            >
              <Switch />
            </Form.Item>
          </Space>

          <Form.Item
            label={t('subtitleStyleEditor.fields.alignment')}
            name="alignment"
          >
            <Radio.Group>
              {ALIGNMENT_OPTIONS.map((opt) => (
                <Radio.Button key={opt.value} value={opt.value}>
                  {t(opt.key)}
                </Radio.Button>
              ))}
            </Radio.Group>
          </Form.Item>
          <Form.Item
            label={t('subtitleStyleEditor.fields.outline')}
            name="outline"
          >
            <InputNumber min={0} max={20} step={0.5} className="w-full" />
          </Form.Item>
          <Form.Item
            label={t('subtitleStyleEditor.fields.shadow')}
            name="shadow"
          >
            <InputNumber min={0} max={20} step={0.5} className="w-full" />
          </Form.Item>
          <Form.Item
            label={t('subtitleStyleEditor.fields.borderStyle')}
            name="border_style"
          >
            <Radio.Group>
              <Radio value={1}>
                {t('subtitleStyleEditor.borderStyle.outlineShadow')}
              </Radio>
              <Radio value={3}>
                {t('subtitleStyleEditor.borderStyle.opaqueBox')}
              </Radio>
            </Radio.Group>
          </Form.Item>

          <Divider className="my-2" />

          <Space size="large" wrap>
            <Form.Item
              label={t('subtitleStyleEditor.fields.marginL')}
              name="margin_l"
            >
              <InputNumber min={0} max={2000} className="w-full" />
            </Form.Item>
            <Form.Item
              label={t('subtitleStyleEditor.fields.marginR')}
              name="margin_r"
            >
              <InputNumber min={0} max={2000} className="w-full" />
            </Form.Item>
            <Form.Item
              label={t('subtitleStyleEditor.fields.marginV')}
              name="margin_v"
            >
              <InputNumber min={0} max={2000} className="w-full" />
            </Form.Item>
          </Space>

          <Form.Item
            label={t('subtitleStyleEditor.fields.fontFallbackChain')}
            name="font_fallback_chain"
          >
            <Select mode="tags" tokenSeparators={[',']} />
          </Form.Item>
        </Form>

        <div>
          <div className="mb-2 text-sm text-gray-500">
            {t('subtitleStyleEditor.previewTitle')}
          </div>
          <PreviewBlock
            values={previewValues}
            text={t('subtitleStyleEditor.previewText')}
          />
          <div className="mt-3 text-xs text-gray-400">
            {t('subtitleStyleEditor.previewHint')}
          </div>
        </div>
      </div>
    </Modal>
  )
}

export default SubtitleStyleEditor
