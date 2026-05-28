/**
 * ConsistencyReviewDrawer（W27-T3）。
 *
 * 横向展开的视觉一致性审阅抽屉：
 *
 * - 头部：得分数值 + 色档徽章 + retry_count 标签（如 > 0）
 * - 中部：``Image.PreviewGroup`` 横向排列抽样帧 + 1 张参考图，支持点击放大
 * - 底部：参考图视角（front / three_quarter / ...）与"未评估"语义提示
 *
 * 数据来源：
 * ``CommerceShotConsistencyService.getShotConsistencyEvidenceApiV1Commerce
 *  ShotsShotIdConsistencyEvidenceGet``（OpenAPI generated client，唯一调
 * 用入口）。本组件不重新计算 score，只透传后端字段，与 W27-T1 sidecar
 * 写入路径解耦。
 *
 * 设计要点：
 * - 抽屉只在 ``open=true && shotId`` 同时满足时发起请求；
 * - 关闭后不保留 react-query 缓存（``gcTime=0``），避免下次打开看到旧数据；
 * - 加载/错误/空态分别走 ``Spin`` / ``Alert`` / ``Empty``；
 * - ``destroyOnClose=true`` 让每次打开都重新挂载，避免抽屉内 Image
 *   PreviewGroup 状态串台。
 */
import React from 'react'
import { Alert, Drawer, Empty, Image, Space, Spin, Tag, Typography } from 'antd'
import { useQuery } from '@tanstack/react-query'

import {
  CommerceShotConsistencyService,
  type ConsistencyEvidenceRead,
} from '../../../../../services/generated'
import { ConsistencyBadge } from './ConsistencyBadge'

const { Text, Paragraph } = Typography

export interface ConsistencyReviewDrawerProps {
  /** 抽屉打开状态 */
  open: boolean
  /** 关闭回调（默认：``onOpenChange(false)``） */
  onClose: () => void
  /** 必填的 shotId；为空时直接渲染 Empty */
  shotId: string | null
  /** 抽屉宽度，默认 720 */
  width?: number
}

/**
 * 把视角枚举字符串显示成中文标签；缺失时返回 ``—``。
 */
function formatViewAngle(angle: string | null | undefined): string {
  if (!angle) return '—'
  const dict: Record<string, string> = {
    FRONT: '正面',
    THREE_QUARTER: '3/4 侧面',
    LEFT: '左侧',
    RIGHT: '右侧',
    BACK: '背面',
    TOP: '俯视',
    DETAIL: '细节',
  }
  return dict[angle.toUpperCase()] ?? angle
}

/**
 * 视觉一致性审阅抽屉主组件。
 */
export const ConsistencyReviewDrawer: React.FC<ConsistencyReviewDrawerProps> = ({
  open,
  onClose,
  shotId,
  width = 720,
}) => {
  const enabled = open && Boolean(shotId)
  const { data, isLoading, isError, error } = useQuery({
    queryKey: ['consistency-evidence', shotId ?? ''],
    enabled,
    gcTime: 0,
    queryFn: async (): Promise<ConsistencyEvidenceRead> => {
      const resp =
        await CommerceShotConsistencyService.getShotConsistencyEvidenceApiV1CommerceShotsShotIdConsistencyEvidenceGet(
          { shotId: shotId as string },
        )
      const payload = resp.data
      if (!payload) {
        throw new Error('empty consistency evidence response')
      }
      return payload
    },
  })

  return (
    <Drawer
      title="视觉一致性审阅"
      placement="right"
      width={width}
      open={open}
      onClose={onClose}
      destroyOnClose
    >
      {!shotId ? (
        <Empty description="未提供镜头 ID" />
      ) : isLoading ? (
        <div className="flex h-40 items-center justify-center">
          <Spin />
        </div>
      ) : isError ? (
        <Alert
          type="error"
          message="无法加载一致性证据"
          description={error instanceof Error ? error.message : '未知错误'}
          showIcon
        />
      ) : data ? (
        <DrawerContent data={data} />
      ) : (
        <Empty description="暂无一致性证据" />
      )}
    </Drawer>
  )
}

/**
 * 抽屉主体内容。提取为独立子组件，避免在主体里堆叠太多分支。
 */
const DrawerContent: React.FC<{ data: ConsistencyEvidenceRead }> = ({ data }) => {
  const samples = data.sampled_frame_urls ?? []
  const reference = data.reference_image_url ?? null
  const retryCount = data.retry_count ?? null

  return (
    <Space direction="vertical" size={16} className="w-full">
      {/* 顶部：得分 + 色档 + retry */}
      <div className="flex flex-wrap items-center gap-3" data-testid="consistency-summary">
        <ConsistencyBadge score={data.score ?? null} shotId={data.shot_id} />
        <Text type="secondary">
          得分：
          <Text strong>
            {data.score === null || data.score === undefined
              ? '未评估'
              : data.score.toFixed(4)}
          </Text>
        </Text>
        {retryCount !== null && retryCount > 0 ? (
          <Tag color="orange" data-testid="retry-count-tag">
            已重试 {retryCount} 次
          </Tag>
        ) : null}
      </div>

      {/* 中部：抽样帧 + 参考图 */}
      <div>
        <Text className="mb-2 block font-medium">抽样帧 / 参考图</Text>
        {samples.length === 0 && !reference ? (
          <Empty description="暂无可用图片" />
        ) : (
          <div className="flex gap-3 overflow-x-auto pb-2" data-testid="consistency-preview-strip">
            <Image.PreviewGroup>
              {samples.map((url, idx) => (
                <div key={`sample-${idx}-${url}`} className="w-[120px] shrink-0">
                  <Image
                    width={120}
                    height={120}
                    style={{
                      objectFit: 'cover',
                      borderRadius: 8,
                      border: '1px solid #e2e8f0',
                    }}
                    src={url}
                    alt={`抽样帧 ${idx + 1}`}
                  />
                  <div className="mt-1 text-center">
                    <Tag color="blue">{`帧 ${idx + 1}`}</Tag>
                  </div>
                </div>
              ))}
              {reference ? (
                <div key="reference" className="w-[120px] shrink-0">
                  <Image
                    width={120}
                    height={120}
                    style={{
                      objectFit: 'cover',
                      borderRadius: 8,
                      border: '2px solid #1677ff',
                    }}
                    src={reference}
                    alt="参考图"
                  />
                  <div className="mt-1 text-center">
                    <Tag color="purple">参考图</Tag>
                  </div>
                </div>
              ) : null}
            </Image.PreviewGroup>
          </div>
        )}
      </div>

      {/* 底部：视角 + 说明 */}
      <Paragraph type="secondary" className="text-xs">
        参考图视角：<Text code>{formatViewAngle(data.reference_view_angle)}</Text>
        ；当前抽样帧来自关联商品图集，未来 wave 接入持久化抽帧后会切换为
        视频实抽帧。一致性得分由 DINOv2 ViT-B/14 计算，区间 [-1, 1]，常落 [0, 1]。
      </Paragraph>
    </Space>
  )
}

export default ConsistencyReviewDrawer
