/**
 * VoicePackUploadModal — 自定义音色训练上传弹窗（P5 W29 引入）。
 *
 * 替换 W20-T5 的 43 行 stub：把"敬请期待"占位换成完整的 antd Form：
 *
 * - sample_file Upload drag/drop（accept=.wav,.mp3,.m4a）
 * - 客户端 5 项校验：format / size / duration / sample_rate / channels
 *   通过浏览器 AudioContext.decodeAudioData 拿到 duration / sample_rate / channels；
 *   失败立即 form-level 提示，不触达后端。
 * - 表单字段：
 *   prefix Input (regex ^[A-Za-z0-9_]{1,10}$, maxLength=10)
 *   display_name Input (maxLength=64)
 *   target_model Radio (cosyvoice-v3.5-plus / cosyvoice-v3-plus)
 *   region Radio (cn-beijing / ap-singapore)
 *   language_hints Select multiple (zh / en / fr / de / ja / ko / ru)
 *   description TextArea (maxLength=255 可选)
 *
 * 提交：调 generated client `CommerceVoicePacksCustomService.createCustomVoicePackEndpoint*`。
 * 成功 toast 后 onClose；失败显示后端错误，modal 不关。
 */
import React, { useState } from 'react'
import {
  Alert,
  Button,
  Form,
  Input,
  Modal,
  Radio,
  Select,
  Space,
  Upload,
  message as antdMessage,
} from 'antd'
import type { UploadFile, UploadProps } from 'antd/es/upload/interface'
import { InboxOutlined } from '@ant-design/icons'
import { useTranslation } from 'react-i18next'

import { CommerceVoicePacksCustomService } from '../../../../services/generated'

export interface VoicePackUploadModalProps {
  /** 是否打开 */
  open: boolean
  /** 关闭回调（成功 / 取消通用） */
  onClose: () => void
  /** 创建成功回调（携带新 voice_pack_id），上层用于刷新列表或定位轮询行 */
  onCreated?: (voicePackId: string) => void
}

/** DashScope CosyVoice voice clone 输入约束（与后端 contracts 同源）。 */
const MAX_FILE_BYTES = 10 * 1024 * 1024
const MIN_DURATION_SEC = 10
const MAX_DURATION_SEC = 60
const MIN_SAMPLE_RATE_HZ = 16000

/** 允许格式（小写后缀）。 */
const ALLOWED_FORMATS = ['wav', 'mp3', 'm4a'] as const
type AllowedFormat = (typeof ALLOWED_FORMATS)[number]

/** target_model 选项；与后端 ALLOWED_TARGET_MODELS 同步。 */
const TARGET_MODEL_OPTIONS = [
  { value: 'cosyvoice-v3.5-plus', labelKey: 'voicePackUpload.targetModel.v35plus' },
  { value: 'cosyvoice-v3-plus', labelKey: 'voicePackUpload.targetModel.v3plus' },
] as const

/** region 选项；与后端 VoiceRegion 同步。 */
const REGION_OPTIONS = [
  { value: 'cn-beijing', labelKey: 'voicePackUpload.region.beijing' },
  { value: 'ap-singapore', labelKey: 'voicePackUpload.region.singapore' },
] as const

/** language_hints 候选；覆盖 cosyvoice-v3 系列支持的全部语言。 */
const LANGUAGE_OPTIONS = [
  'zh', 'en', 'fr', 'de', 'ja', 'ko', 'ru',
] as const

/** 提取文件名后缀小写形态。 */
function getSuffix(name: string | undefined): string {
  if (!name || !name.includes('.')) return ''
  return name.slice(name.lastIndexOf('.') + 1).toLowerCase().trim()
}

interface AudioProbeResult {
  durationSec: number
  sampleRateHz: number
  channels: number
}

/**
 * 通过 AudioContext.decodeAudioData 探测音频元信息。
 *
 * 前端校验只是体验优化（即时反馈），后端会用 soundfile 二次校验；
 * 校验失败时返回 null，调用方决定是否阻断提交。
 */
async function probeAudio(file: File): Promise<AudioProbeResult | null> {
  try {
    const arrayBuf = await file.arrayBuffer()
    // 兼容 Safari webkitAudioContext。
    const Ctor: typeof AudioContext | undefined =
      typeof window !== 'undefined'
        ? // eslint-disable-next-line @typescript-eslint/no-explicit-any
          (window as any).AudioContext || (window as any).webkitAudioContext
        : undefined
    if (!Ctor) return null
    const ctx = new Ctor()
    const buf = await ctx.decodeAudioData(arrayBuf.slice(0))
    const result: AudioProbeResult = {
      durationSec: buf.duration,
      sampleRateHz: buf.sampleRate,
      channels: buf.numberOfChannels,
    }
    void ctx.close?.()
    return result
  } catch (_err) {
    return null
  }
}

interface FormValues {
  prefix: string
  display_name: string
  target_model: string
  region: string
  language_hints?: string[]
  description?: string
}

export const VoicePackUploadModal: React.FC<VoicePackUploadModalProps> = ({
  open,
  onClose,
  onCreated,
}) => {
  const { t } = useTranslation('commerce')
  const [form] = Form.useForm<FormValues>()
  const [fileList, setFileList] = useState<UploadFile[]>([])
  const [audioError, setAudioError] = useState<string | null>(null)
  const [submitError, setSubmitError] = useState<string | null>(null)
  const [submitting, setSubmitting] = useState(false)

  /**
   * 重置内部状态，弹窗关闭时调用，避免下次打开仍残留旧值。
   */
  const reset = () => {
    form.resetFields()
    setFileList([])
    setAudioError(null)
    setSubmitError(null)
    setSubmitting(false)
  }

  /**
   * 处理 antd Upload 的 beforeUpload：拦截真实上传（我们自己提交），
   * 并在选中文件后立即跑客户端校验。
   */
  const beforeUpload: UploadProps['beforeUpload'] = async (file) => {
    setAudioError(null)
    setSubmitError(null)

    const suffix = getSuffix(file.name) as AllowedFormat
    if (!ALLOWED_FORMATS.includes(suffix)) {
      setAudioError(t('voicePackUpload.errors.format', { suffix }))
      return Upload.LIST_IGNORE
    }
    if (file.size > MAX_FILE_BYTES) {
      setAudioError(
        t('voicePackUpload.errors.size', {
          max: `${MAX_FILE_BYTES / (1024 * 1024)} MB`,
        }),
      )
      return Upload.LIST_IGNORE
    }

    const probe = await probeAudio(file)
    if (!probe) {
      setAudioError(t('voicePackUpload.errors.unparseable'))
      return Upload.LIST_IGNORE
    }
    if (
      probe.durationSec < MIN_DURATION_SEC ||
      probe.durationSec > MAX_DURATION_SEC
    ) {
      setAudioError(
        t('voicePackUpload.errors.duration', {
          actual: probe.durationSec.toFixed(1),
          min: MIN_DURATION_SEC,
          max: MAX_DURATION_SEC,
        }),
      )
      return Upload.LIST_IGNORE
    }
    if (probe.sampleRateHz < MIN_SAMPLE_RATE_HZ) {
      setAudioError(
        t('voicePackUpload.errors.sampleRate', {
          actual: probe.sampleRateHz,
          min: MIN_SAMPLE_RATE_HZ,
        }),
      )
      return Upload.LIST_IGNORE
    }
    if (probe.channels < 1 || probe.channels > 2) {
      setAudioError(
        t('voicePackUpload.errors.channels', { actual: probe.channels }),
      )
      return Upload.LIST_IGNORE
    }

    setFileList([
      {
        uid: file.uid,
        name: file.name,
        status: 'done',
        size: file.size,
        // antd Upload 需要 originFileObj 才能在 onChange/onSubmit 取到原 File。
        originFileObj: file as unknown as UploadFile['originFileObj'],
      },
    ])
    return false
  }

  /**
   * 移除已选文件（重置 audio 校验态）。
   */
  const onRemoveFile = () => {
    setFileList([])
    setAudioError(null)
  }

  /**
   * 提交表单：调用 generated client，成功后 toast + onCreated + 关闭。
   */
  const onSubmit = async () => {
    setSubmitError(null)
    if (audioError) {
      return
    }
    if (fileList.length === 0) {
      setAudioError(t('voicePackUpload.errors.fileMissing'))
      return
    }
    let values: FormValues
    try {
      values = await form.validateFields()
    } catch (_err) {
      return
    }
    const fileObj = fileList[0].originFileObj as unknown as File
    if (!fileObj) {
      setAudioError(t('voicePackUpload.errors.fileMissing'))
      return
    }

    setSubmitting(true)
    try {
      const res =
        await CommerceVoicePacksCustomService.createCustomVoicePackEndpointApiV1CommerceVoicePacksCustomPost(
          {
            formData: {
              sample_file: fileObj as unknown as string,
              prefix: values.prefix,
              target_model: values.target_model,
              region: values.region,
              display_name: values.display_name,
              language_hints:
                values.language_hints && values.language_hints.length > 0
                  ? values.language_hints.join(',')
                  : null,
              description: values.description ?? null,
            },
          },
        )
      const voicePackId = res.data?.voice_pack_id
      antdMessage.success(t('voicePackUpload.successToast'))
      if (voicePackId) {
        onCreated?.(voicePackId)
      }
      reset()
      onClose()
    } catch (err) {
      // antd / fetch ApiError 可能在 .body / .message 处携带错误信息；
      // 这里尽力解析常见路径，回退到 err.message。
      // eslint-disable-next-line @typescript-eslint/no-explicit-any
      const anyErr = err as any
      const detail =
        anyErr?.body?.detail?.message ||
        anyErr?.body?.detail ||
        anyErr?.body?.message ||
        anyErr?.message ||
        t('voicePackUpload.errors.submitGeneric')
      setSubmitError(typeof detail === 'string' ? detail : JSON.stringify(detail))
    } finally {
      setSubmitting(false)
    }
  }

  return (
    <Modal
      open={open}
      title={t('voicePackUpload.title')}
      onCancel={() => {
        if (!submitting) {
          reset()
          onClose()
        }
      }}
      okText={t('voicePackUpload.submit')}
      cancelText={t('voicePackUpload.cancel')}
      confirmLoading={submitting}
      onOk={onSubmit}
      destroyOnClose
      width={640}
    >
      <Form
        form={form}
        layout="vertical"
        initialValues={{
          target_model: 'cosyvoice-v3.5-plus',
          region: 'cn-beijing',
          language_hints: ['zh'],
        }}
      >
        <Form.Item
          label={t('voicePackUpload.fields.sampleFile')}
          required
          extra={t('voicePackUpload.fields.sampleFileHint')}
        >
          <Upload.Dragger
            accept=".wav,.mp3,.m4a"
            maxCount={1}
            multiple={false}
            fileList={fileList}
            beforeUpload={beforeUpload}
            onRemove={onRemoveFile}
          >
            <p className="ant-upload-drag-icon">
              <InboxOutlined />
            </p>
            <p className="ant-upload-text">
              {t('voicePackUpload.fields.dragDrop')}
            </p>
          </Upload.Dragger>
          {audioError ? (
            <Alert
              type="error"
              showIcon
              message={audioError}
              className="!mt-2"
            />
          ) : null}
        </Form.Item>

        <Form.Item
          name="prefix"
          label={t('voicePackUpload.fields.prefix')}
          rules={[
            {
              required: true,
              message: t('voicePackUpload.fields.prefixRequired'),
            },
            {
              pattern: /^[A-Za-z0-9_]{1,10}$/,
              message: t('voicePackUpload.fields.prefixPattern'),
            },
          ]}
        >
          <Input
            placeholder="myvoice"
            maxLength={10}
            aria-label="voice-pack-prefix"
          />
        </Form.Item>

        <Form.Item
          name="display_name"
          label={t('voicePackUpload.fields.displayName')}
          rules={[
            {
              required: true,
              message: t('voicePackUpload.fields.displayNameRequired'),
            },
            { max: 64 },
          ]}
        >
          <Input
            placeholder={t('voicePackUpload.fields.displayNamePlaceholder')}
            maxLength={64}
            aria-label="voice-pack-display-name"
          />
        </Form.Item>

        <Form.Item
          name="target_model"
          label={t('voicePackUpload.fields.targetModel')}
          rules={[{ required: true }]}
        >
          <Radio.Group aria-label="voice-pack-target-model">
            <Space direction="vertical">
              {TARGET_MODEL_OPTIONS.map((opt) => (
                <Radio key={opt.value} value={opt.value}>
                  {t(opt.labelKey)}
                </Radio>
              ))}
            </Space>
          </Radio.Group>
        </Form.Item>

        <Form.Item
          name="region"
          label={t('voicePackUpload.fields.region')}
          rules={[{ required: true }]}
        >
          <Radio.Group aria-label="voice-pack-region">
            <Space direction="vertical">
              {REGION_OPTIONS.map((opt) => (
                <Radio key={opt.value} value={opt.value}>
                  {t(opt.labelKey)}
                </Radio>
              ))}
            </Space>
          </Radio.Group>
        </Form.Item>

        <Form.Item
          name="language_hints"
          label={t('voicePackUpload.fields.languageHints')}
        >
          <Select
            mode="multiple"
            allowClear
            aria-label="voice-pack-language-hints"
            placeholder={t('voicePackUpload.fields.languageHintsPlaceholder')}
            options={LANGUAGE_OPTIONS.map((code) => ({
              label: code,
              value: code,
            }))}
          />
        </Form.Item>

        <Form.Item
          name="description"
          label={t('voicePackUpload.fields.description')}
          rules={[{ max: 255 }]}
        >
          <Input.TextArea
            rows={3}
            maxLength={255}
            showCount
            aria-label="voice-pack-description"
            placeholder={t('voicePackUpload.fields.descriptionPlaceholder')}
          />
        </Form.Item>

        {submitError ? (
          <Alert type="error" showIcon message={submitError} className="mb-2" />
        ) : null}

        <Button type="link" disabled={submitting} onClick={reset} size="small">
          {t('voicePackUpload.reset')}
        </Button>
      </Form>
    </Modal>
  )
}

export default VoicePackUploadModal
