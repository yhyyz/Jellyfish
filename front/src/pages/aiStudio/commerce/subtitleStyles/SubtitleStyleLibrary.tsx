/**
 * 字幕样式库（SubtitleStyleLibrary）页面 —— W20-T6。
 *
 * 页面定位：
 * - 给字幕样式提供独立的**只读**浏览入口，列出 W18 内置的 3 个系统模板
 *   （DOUYIN_DEFAULT / TIKTOK_VIRAL / REELS_LOWER_THIRD），每张卡片含
 *   平台 tag、说明与 mini ASS 预览。
 * - 项目级覆盖（per-project subtitle override）目前仅占位，URL 不带
 *   `?projectId` 时显示 info banner 告知用户该能力将在 W21 启用。
 *
 * 范式锚点（与 FormulaLibrary / VoicePackPicker 保持一致）：
 * - 数据走 `useSubtitleStyles({ isSystem: true })`（在 sibling
 *   `projects/workbench.queries.ts` 已封装），底层是 OpenAPI generated
 *   client `CommerceSubtitleStylesService`，遵循 AGENTS.md 第 2 条不允许
 *   再写手工 service。
 * - Loading / Error / Empty 三态使用 antd 标准组件（Skeleton / Alert /
 *   Empty），与 ProductLibrary、FormulaLibrary 风格一致。
 * - 当前页面仅做浏览，不引入选择回调；后续若要复用为带 selected 状态的
 *   弹窗内容，应抽到独立组件而非在这里改造。
 *
 * 路由注册：本任务（T20-6）不改 routes.ts，由 T20-7 统一处理。
 */
import React from 'react'
import { Alert, Card, Empty, Skeleton, Space, Tag } from 'antd'
import { useTranslation } from 'react-i18next'
import { useSearchParams } from 'react-router-dom'
import { ScrollablePage } from '../../components/ScrollablePage'
import { useSubtitleStyles } from '../projects/workbench.queries'
import { fromAss } from '../projects/components/_subtitle/colorCodec'
import type { SubtitleStyleRead } from '../../../../services/generated'

/**
 * 单张样式卡片中的迷你字幕预览块。
 *
 * 仅取主要视觉字段（font_family / font_size / primary_colour / outline）
 * 做浏览级体感呈现，不追求 ASS 全保真渲染——保真渲染在 W21 真正生成
 * 阶段由后端 / 渲染管线负责。
 *
 * 与 SubtitleStylePicker 中的 StylePreviewBlock 概念一致，但这里独立成
 * 文件级常量，避免跨文件 import 私有组件造成圈层耦合（AGENTS.md 第 3 条
 * 鼓励先行复制再考虑抽离）。
 */
const StylePreviewBlock: React.FC<{
  style: SubtitleStyleRead
  previewText: string
}> = ({ style, previewText }) => {
  // fromAss 容错：seed 数据格式异常不应让整张卡片崩溃
  let primary = '#FFFFFF'
  let outline = '#000000'
  try {
    primary = fromAss(style.primary_colour)
  } catch {
    /* keep default */
  }
  try {
    outline = fromAss(style.outline_colour)
  } catch {
    /* keep default */
  }

  return (
    <div
      className="flex h-20 items-center justify-center rounded bg-gray-900 px-2"
      style={{
        fontFamily: style.font_family,
        // font_size 基于 PlayResY=1920 脚本像素，按 1/3 缩放给个体感
        fontSize: Math.max(12, Math.round(style.font_size / 3)),
        color: primary,
        fontWeight: style.bold ? 700 : 400,
        fontStyle: style.italic ? 'italic' : 'normal',
        WebkitTextStroke:
          style.outline > 0 ? `${style.outline / 2}px ${outline}` : undefined,
      }}
    >
      {previewText}
    </div>
  )
}

/**
 * 字幕样式库主组件。
 *
 * 状态：
 * - `searchParams`：识别 URL 是否带 `projectId`，以决定显示 info banner 还
 *   是项目级覆盖占位区。W20 阶段两条分支都仅是占位，正式实装在 W21。
 * - `useSubtitleStyles({ isSystem: true })`：仅取系统模板。
 *
 * 渲染策略：
 * - 顶部 Card 包裹整页内容，与 FormulaLibrary 视觉一致。
 * - 系统模板区：3 列网格（响应式：移动端 1 列，md+ 3 列）。
 * - 项目级覆盖区：W20 仅显示提示性 Alert，未提供任何编辑入口。
 */
const SubtitleStyleLibrary: React.FC = () => {
  const { t } = useTranslation('commerce')
  const [searchParams] = useSearchParams()
  const projectId = searchParams.get('projectId')

  const { data: systemStyles, isLoading, isError } = useSubtitleStyles({
    isSystem: true,
  })

  return (
    <ScrollablePage className="pr-1">
      <Card
        title={
          <Space>
            <span>{t('subtitleStyleLibrary.pageTitle')}</span>
            {systemStyles && <Tag>{`${systemStyles.length} 个`}</Tag>}
          </Space>
        }
      >
        <div className="space-y-6">
          {/* 系统模板区 */}
          <section>
            <div className="mb-3 text-base font-medium">
              {t('subtitleStyleLibrary.systemSection')}
            </div>

            {isError && (
              <Alert
                type="error"
                showIcon
                message={t('subtitleStyleLibrary.loadFailed')}
              />
            )}

            {isLoading && !isError && (
              <Skeleton active paragraph={{ rows: 4 }} />
            )}

            {!isLoading && !isError && (
              <>
                {systemStyles && systemStyles.length > 0 ? (
                  <div className="grid grid-cols-1 gap-3 md:grid-cols-3">
                    {systemStyles.map((style: SubtitleStyleRead) => (
                      <Card
                        key={style.id}
                        size="small"
                        data-testid={`subtitle-style-card-${style.id}`}
                        className="border border-gray-200"
                      >
                        <div className="flex flex-col gap-2">
                          <div className="flex items-center justify-between">
                            <span className="font-medium">{style.name}</span>
                            <Tag color="blue">
                              {style.format.toUpperCase()}
                            </Tag>
                          </div>
                          <StylePreviewBlock
                            style={style}
                            previewText={t('subtitleStyleLibrary.preview')}
                          />
                          {style.description && (
                            <div className="text-xs text-gray-500">
                              {style.description}
                            </div>
                          )}
                          <div className="text-xs text-gray-400">
                            {style.language_code} · {style.font_family} ·{' '}
                            {style.font_size}px
                          </div>
                        </div>
                      </Card>
                    ))}
                  </div>
                ) : (
                  <Empty image={Empty.PRESENTED_IMAGE_SIMPLE} />
                )}
              </>
            )}
          </section>

          {/* 项目级覆盖区（W20 占位 / W21 启用） */}
          <section>
            {!projectId ? (
              <Alert
                type="info"
                showIcon
                message={t('subtitleStyleLibrary.projectOverridesNotice')}
              />
            ) : (
              <Alert
                type="info"
                showIcon
                message={t('subtitleStyleLibrary.projectOverridesNotice')}
                description={`projectId=${projectId}`}
              />
            )}
          </section>
        </div>
      </Card>
    </ScrollablePage>
  )
}

export default SubtitleStyleLibrary
