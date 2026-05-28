/**
 * 字幕样式库（SubtitleStyleLibrary）页面 —— W20-T6 + W30-T5。
 *
 * 页面定位：
 * - 不带 `?projectId` 时显示**只读**系统模板浏览（保留 W20 行为）。
 * - 带 `?projectId=xxx` 时升级为完整的"系统级 + 项目级覆盖"管理面板：
 *   - 表格列：名称 / 来源 (system/project Tag) / 字体 / 字号 / 操作
 *   - 顶部 `subtitleStyleEditor.createBtn` 按钮 → 打开空白
 *     `SubtitleStyleEditor`（mode='create'）。
 *   - 行点击：项目级行进入编辑模式（mode='projectEdit'）；系统级行进入
 *     只读 + 克隆模式（mode='systemReadonly'）。
 *
 * 数据：使用 OpenAPI generated client：
 * - 无 projectId：`useSubtitleStyles({ isSystem: true })`（W20 路径）。
 * - 带 projectId：直接调
 *   `CommerceSubtitleStylesService.listProjectSubtitleStylesEndpointApiV1Commerce
 *   ProjectsProjectIdSubtitleStylesGet`（merged 视图）。
 *
 * 状态管理：保持与 VoicePackLibrary 一致的 useEffect + useState 范式。
 */
import React, { useCallback, useEffect, useMemo, useState } from 'react'
import {
  Alert,
  Button,
  Card,
  Skeleton,
  Space,
  Table,
  Tag,
  message as antdMessage,
} from 'antd'
import type { ColumnsType } from 'antd/es/table'
import { useTranslation } from 'react-i18next'
import { useSearchParams } from 'react-router-dom'

import { ScrollablePage } from '../../components/ScrollablePage'
import { useSubtitleStyles } from '../projects/workbench.queries'
import { fromAss } from '../projects/components/_subtitle/colorCodec'
import {
  CommerceSubtitleStylesService,
  type SubtitleStyleRead,
} from '../../../../services/generated'
import SubtitleStyleEditor from './SubtitleStyleEditor'

interface StylePreviewBlockProps {
  style: SubtitleStyleRead
  previewText: string
}

/**
 * 单张样式卡片中的迷你字幕预览块。
 * 仅取主要视觉字段做浏览级体感；保真渲染交给后端管线。
 */
const StylePreviewBlock: React.FC<StylePreviewBlockProps> = ({
  style,
  previewText,
}) => {
  let primary = '#FFFFFF'
  let outline = '#000000'
  try {
    primary = fromAss(style.primary_colour)
  } catch {
    /* keep default */
  }
  try {
    if (style.outline_colour) outline = fromAss(style.outline_colour)
  } catch {
    /* keep default */
  }

  return (
    <div
      className="flex h-16 items-center justify-center rounded bg-gray-900 px-2"
      style={{
        fontFamily: style.font_family,
        fontSize: Math.max(11, Math.round(style.font_size / 4)),
        color: primary,
        fontWeight: style.bold ? 700 : 400,
        fontStyle: style.italic ? 'italic' : 'normal',
        WebkitTextStroke:
          style.outline > 0 ? `${style.outline / 3}px ${outline}` : undefined,
      }}
    >
      {previewText}
    </div>
  )
}

const SubtitleStyleLibrary: React.FC = () => {
  const { t } = useTranslation('commerce')
  const [searchParams] = useSearchParams()
  const projectId = searchParams.get('projectId')

  // 不带 projectId 走 W20 旧路径（仅系统模板）
  const { data: systemStyles, isLoading: legacyLoading, isError: legacyError } =
    useSubtitleStyles({ isSystem: true })

  // 带 projectId 走 merged 视图（系统 + 项目级覆盖）
  const [mergedStyles, setMergedStyles] = useState<SubtitleStyleRead[]>([])
  const [mergedLoading, setMergedLoading] = useState(false)
  const [mergedError, setMergedError] = useState<string | null>(null)
  const [editorOpen, setEditorOpen] = useState(false)
  const [editingStyle, setEditingStyle] = useState<SubtitleStyleRead | null>(null)
  const [refreshTick, setRefreshTick] = useState(0)

  const refreshMerged = useCallback(() => {
    setRefreshTick((v) => v + 1)
  }, [])

  useEffect(() => {
    if (!projectId) return
    let cancelled = false
    setMergedLoading(true)
    setMergedError(null)
    CommerceSubtitleStylesService.listProjectSubtitleStylesEndpointApiV1CommerceProjectsProjectIdSubtitleStylesGet(
      { projectId },
    )
      .then((res) => {
        if (cancelled) return
        setMergedStyles(res.data ?? [])
      })
      .catch((err: unknown) => {
        if (cancelled) return
        setMergedError(
          err instanceof Error ? err.message : 'failed to load styles',
        )
      })
      .finally(() => {
        if (cancelled) return
        setMergedLoading(false)
      })
    return () => {
      cancelled = true
    }
  }, [projectId, refreshTick])

  const openEditor = useCallback((style: SubtitleStyleRead | null) => {
    setEditingStyle(style)
    setEditorOpen(true)
  }, [])

  const handleEditorClose = useCallback(() => {
    setEditorOpen(false)
    setEditingStyle(null)
  }, [])

  const handleMutated = useCallback(() => {
    refreshMerged()
    antdMessage.success(t('subtitleStyleEditor.saveSuccess'))
  }, [refreshMerged, t])

  const tableColumns: ColumnsType<SubtitleStyleRead> = useMemo(
    () => [
      {
        title: t('subtitleStyleLibrary.col.name'),
        dataIndex: 'name',
        key: 'name',
        render: (_: unknown, row: SubtitleStyleRead) => (
          <span data-testid={`subtitle-style-row-name-${row.id}`}>{row.name}</span>
        ),
      },
      {
        title: t('subtitleStyleLibrary.col.scope'),
        dataIndex: 'project_id',
        key: 'scope',
        width: 120,
        render: (_: unknown, row: SubtitleStyleRead) =>
          row.project_id == null ? (
            <Tag color="blue">{t('subtitleStyleLibrary.scope.system')}</Tag>
          ) : (
            <Tag color="green">{t('subtitleStyleLibrary.scope.project')}</Tag>
          ),
      },
      {
        title: t('subtitleStyleLibrary.col.fontFamily'),
        dataIndex: 'font_family',
        key: 'font_family',
        ellipsis: true,
      },
      {
        title: t('subtitleStyleLibrary.col.fontSize'),
        dataIndex: 'font_size',
        key: 'font_size',
        width: 100,
      },
      {
        title: t('subtitleStyleLibrary.col.actions'),
        key: 'actions',
        width: 220,
        render: (_: unknown, row: SubtitleStyleRead) => (
          <Space>
            {row.project_id == null ? (
              <Button
                size="small"
                type="link"
                onClick={() => openEditor(row)}
                data-testid={`subtitle-style-clone-${row.id}`}
              >
                {t('subtitleStyleEditor.cloneBtn')}
              </Button>
            ) : (
              <Button
                size="small"
                type="link"
                onClick={() => openEditor(row)}
                data-testid={`subtitle-style-edit-${row.id}`}
              >
                {t('subtitleStyleLibrary.editBtn')}
              </Button>
            )}
          </Space>
        ),
      },
    ],
    [openEditor, t],
  )

  return (
    <ScrollablePage className="pr-1">
      <Card
        title={
          <Space>
            <span>{t('subtitleStyleLibrary.pageTitle')}</span>
            {projectId ? (
              <Tag color="green">{t('subtitleStyleLibrary.projectMode')}</Tag>
            ) : null}
          </Space>
        }
        extra={
          projectId ? (
            <Button
              type="primary"
              onClick={() => openEditor(null)}
              data-testid="subtitle-style-create-btn"
            >
              {t('subtitleStyleEditor.createBtn')}
            </Button>
          ) : null
        }
      >
        {!projectId ? (
          <div className="space-y-6">
            <section>
              <div className="mb-3 text-base font-medium">
                {t('subtitleStyleLibrary.systemSection')}
              </div>

              {legacyError && (
                <Alert
                  type="error"
                  showIcon
                  message={t('subtitleStyleLibrary.loadFailed')}
                />
              )}
              {legacyLoading && !legacyError && (
                <Skeleton active paragraph={{ rows: 4 }} />
              )}
              {!legacyLoading && !legacyError && systemStyles && (
                <div className="grid grid-cols-1 gap-3 md:grid-cols-3">
                  {systemStyles.map((s: SubtitleStyleRead) => (
                    <Card
                      key={s.id}
                      size="small"
                      data-testid={`subtitle-style-card-${s.id}`}
                      className="border border-gray-200"
                    >
                      <div className="flex flex-col gap-2">
                        <div className="flex items-center justify-between">
                          <span className="font-medium">{s.name}</span>
                          <Tag color="blue">{s.format.toUpperCase()}</Tag>
                        </div>
                        <StylePreviewBlock
                          style={s}
                          previewText={t('subtitleStyleLibrary.preview')}
                        />
                        {s.description && (
                          <div className="text-xs text-gray-500">
                            {s.description}
                          </div>
                        )}
                        <div className="text-xs text-gray-400">
                          {s.language_code} · {s.font_family} · {s.font_size}px
                        </div>
                      </div>
                    </Card>
                  ))}
                </div>
              )}
            </section>

            <section>
              <Alert
                type="info"
                showIcon
                message={t('subtitleStyleLibrary.projectOverridesHint')}
              />
            </section>
          </div>
        ) : (
          <div className="space-y-3">
            {mergedError && (
              <Alert
                type="error"
                showIcon
                message={t('subtitleStyleLibrary.loadFailed')}
                description={mergedError}
              />
            )}
            <Table<SubtitleStyleRead>
              rowKey="id"
              columns={tableColumns}
              dataSource={mergedStyles}
              loading={mergedLoading}
              pagination={false}
              data-testid="subtitle-style-merged-table"
            />
          </div>
        )}
      </Card>

      {projectId && (
        <SubtitleStyleEditor
          open={editorOpen}
          onClose={handleEditorClose}
          projectId={projectId}
          style={editingStyle}
          onMutated={handleMutated}
        />
      )}
    </ScrollablePage>
  )
}

export default SubtitleStyleLibrary
