/**
 * VoicePackUploadModal — 上传定制音色 stub 弹窗（W20-T5）。
 *
 * 设计意图：
 * - 商品音色库当前只对外暴露**只读浏览**能力；自定义音色训练（用户上传 sample
 *   并产出私人 VoicePack）规划在 W21 推进。
 * - 在 W20 阶段先把按钮入口与弹窗骨架做出来，避免后续接入时再调整工具栏布局，
 *   也让用户提前感知该能力即将开放。
 * - 弹窗体只承担「告知敬请期待」职责，不做任何业务上传，footer 关闭。
 */
import React from 'react'
import { Empty, Modal } from 'antd'
import { useTranslation } from 'react-i18next'

export interface VoicePackUploadModalProps {
  /** 是否打开 */
  open: boolean
  /** 关闭回调 */
  onClose: () => void
}

export const VoicePackUploadModal: React.FC<VoicePackUploadModalProps> = ({
  open,
  onClose,
}) => {
  const { t } = useTranslation('commerce')
  return (
    <Modal
      open={open}
      title={t('voicePackLibrary.uploadCustom')}
      footer={null}
      onCancel={onClose}
      destroyOnClose
    >
      <Empty
        image={Empty.PRESENTED_IMAGE_SIMPLE}
        description={t('voicePackLibrary.uploadComingSoon')}
      />
    </Modal>
  )
}

export default VoicePackUploadModal
