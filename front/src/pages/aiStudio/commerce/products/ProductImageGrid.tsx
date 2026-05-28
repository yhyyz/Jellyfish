/**
 * ProductImageGrid 组件：商品图“7 角度 × 4 质量”栅格视图。
 *
 * 设计要点：
 * - 横向按 7 个 AssetViewAngle 顺序展开（FRONT / LEFT / RIGHT / BACK /
 *   THREE_QUARTER / TOP / DETAIL），每行一个角度。
 * - 每行内部纵向再展开 4 个 AssetQualityLevel 槽位（LOW / MEDIUM / HIGH /
 *   ULTRA），构成 7×4 = 28 个固定槽位。
 * - 每个槽位根据是否能在 `images` 中匹配到 `(view_angle, quality_level)`
 *   决定渲染：
 *     * 命中：复用资产模块 `DisplayImageCard` 展示文件预览，叠加金色/灰色
 *       星标用于切换主图。
 *     * 未命中：渲染可点击的占位卡片，点击触发 `onUpload(angle, quality)`
 *       由父级负责拉起上传弹窗或调用 OpenAPI 生成的上传接口。
 *
 * 与 AGENTS.md 协作约定的关系：
 * - 规则 #2：组件内部不实现任何手写 service，仅暴露事件回调由父级使用
 *   OpenAPI generated client（StudioFilesService / StudioProductsService）
 *   完成上传与挂载。
 * - 规则 #3：填充态优先复用 `DisplayImageCard`，避免重复实现图片预览。
 * - 规则 #5：所有函数与组件均补充中文注释，含参数/返回/关键逻辑说明。
 *
 * 国际化：使用 react-i18next 的 'commerce' 命名空间。该命名空间在 T20-7
 * 之前尚未在 `i18n.ts` 中注册，因此此处即便在生产环境也会回退为原始 key，
 * 但组件接入与测试可先行落地。
 */
import React from 'react'
import { Card } from 'antd'
import { PlusOutlined, StarFilled, StarOutlined } from '@ant-design/icons'
import { useTranslation } from 'react-i18next'

import type { AssetQualityLevel } from '../../../../services/generated/models/AssetQualityLevel'
import type { AssetViewAngle } from '../../../../services/generated/models/AssetViewAngle'
import { DisplayImageCard } from '../../assets/components/DisplayImageCard'
import { resolveAssetUrl } from '../../assets/utils'
import type { ProductImageRead } from './queries'

/**
 * 7 个角度的稳定顺序。该顺序同时作为 UI 渲染顺序与生产可视化顺序，
 * 不要随意调整，否则可能影响产品同事手工核对图片完成度的习惯。
 */
const VIEW_ANGLES: AssetViewAngle[] = [
  'FRONT',
  'LEFT',
  'RIGHT',
  'BACK',
  'THREE_QUARTER',
  'TOP',
  'DETAIL',
]

/**
 * 4 个质量等级的稳定顺序：与后端 `AssetQualityLevel` 枚举字段顺序一致，
 * 由低到高呈现，用户更容易理解“尚未补齐到 ULTRA 级别”这种语义。
 */
const QUALITY_LEVELS: AssetQualityLevel[] = ['LOW', 'MEDIUM', 'HIGH', 'ULTRA']

/**
 * ProductImageGrid props 契约。
 *
 * - `productId`：仅用于上层定位上下文，组件内部不直接调用与 productId 相关的
 *   API；保留该字段是为父级回调时透出便利，并与未来上传/调度接入对齐。
 * - `images`：当前商品已落库的图片列表；通常来源于 `useProductDetail` 返回。
 * - `onUpload`：点击空槽时触发，参数为 (角度, 质量)，由父级弹起上传交互。
 * - `onSelectPrimary`：点击非主图星标触发，参数为 image.id（number），
 *   由父级调用后端“切换主图”接口；类型与 ProductImageRead.id 直接对齐，
 *   避免无谓的 String() 转换。
 */
export interface ProductImageGridProps {
  productId: string
  images: ProductImageRead[]
  onUpload: (angle: AssetViewAngle, quality: AssetQualityLevel) => void
  onSelectPrimary: (imageId: number) => void
}

/**
 * 单个图片槽位的内部渲染单元。
 *
 * 抽出为子组件的原因（满足 AGENTS.md 规则 #3）：
 * - “填充态 + 星标按钮”与“空态 + 上传占位”各自重复出现 28 次；
 * - 抽离后保证两种状态共享统一的尺寸/边框风格，避免日后样式漂移；
 * - 测试时通过 data-testid 钩子精准定位到具体槽位。
 *
 * @param angle 当前槽位归属的角度；用于回调透传与 testid 拼装。
 * @param quality 当前槽位归属的质量等级；同上。
 * @param image 命中时传入的 ProductImageRead；未命中传 undefined。
 * @param onUpload 空槽点击回调。
 * @param onSelectPrimary 非主图星标点击回调（imageId 为 number，与后端 schema 一致）。
 */
const ImageSlot: React.FC<{
  angle: AssetViewAngle
  quality: AssetQualityLevel
  image?: ProductImageRead
  onUpload: ProductImageGridProps['onUpload']
  onSelectPrimary: ProductImageGridProps['onSelectPrimary']
}> = ({ angle, quality, image, onUpload, onSelectPrimary }) => {
  const { t } = useTranslation('commerce')

  // 空槽：渲染可点击的虚线占位卡，触发 onUpload。
  if (!image) {
    return (
      <button
        type="button"
        data-testid={`empty-slot-${angle}-${quality}`}
        onClick={() => onUpload(angle, quality)}
        className="h-32 w-full rounded-md border-2 border-dashed border-gray-300 bg-gray-50 text-gray-400 hover:border-blue-400 hover:text-blue-500 transition flex flex-col items-center justify-center cursor-pointer"
      >
        <PlusOutlined className="text-lg" />
        <span className="text-xs mt-1">{t('productImageGrid.uploadHint')}</span>
        <span className="text-[10px] mt-1 text-gray-400">
          {t(`productImageGrid.quality.${quality}`)}
        </span>
      </button>
    )
  }

  // 已填充：复用 DisplayImageCard，并叠加星标按钮做主图切换。
  const imageUrl = image.file_id ? resolveAssetUrl(image.file_id) : undefined
  const imageId = image.id
  // 主图态使用金色 StarFilled，非主图使用灰色 StarOutlined；
  // 主图自身无需再次切换，因此 onClick 仅在非主图时回调。
  const starClassName = image.is_primary
    ? 'text-yellow-400 cursor-default'
    : 'text-gray-400 cursor-pointer hover:text-yellow-400'

  return (
    <div data-testid={`filled-slot-${angle}-${quality}`} className="relative">
      <DisplayImageCard
        title={
          <div className="flex items-center justify-between gap-2">
            <span className="truncate text-xs">
              {t(`productImageGrid.quality.${quality}`)}
            </span>
            <button
              type="button"
              data-testid={`primary-star-${imageId}`}
              aria-label={t('productImageGrid.primaryBadge')}
              className={`bg-transparent border-0 p-0 leading-none ${starClassName}`}
              onClick={() => {
                if (!image.is_primary) {
                  onSelectPrimary(imageId)
                }
              }}
            >
              {image.is_primary ? <StarFilled /> : <StarOutlined />}
            </button>
          </div>
        }
        imageUrl={imageUrl}
        imageAlt={`${angle}-${quality}`}
        imageHeightClassName="h-24"
        size="small"
        hoverable={false}
      />
    </div>
  )
}

/**
 * ProductImageGrid 主组件：渲染 7 角度 × 4 质量的栅格。
 *
 * 关键内部逻辑：
 *   1. 按 VIEW_ANGLES 顺序构建 7 行；
 *   2. 每行内对 4 个 quality 槽位通过 `find` 精确匹配 `(view_angle,
 *      quality_level)`；后端唯一约束保证 0/1 命中。
 *   3. 命中渲染填充态、未命中渲染空态。
 *
 * @param productId 上下文商品 id。组件本身不读取，回调时由父级使用。
 * @param images 当前商品图片列表（可能为空）。
 * @param onUpload 空槽位上传回调。
 * @param onSelectPrimary 非主图星标点击回调。
 */
export const ProductImageGrid: React.FC<ProductImageGridProps> = ({
  productId: _productId,
  images,
  onUpload,
  onSelectPrimary,
}) => {
  const { t } = useTranslation('commerce')

  return (
    <div className="space-y-4" data-testid="product-image-grid">
      {VIEW_ANGLES.map((angle) => {
        // 按角度过滤一次，减少每个 quality slot 的二次扫描成本。
        const angleImages = images.filter((img) => img.view_angle === angle)
        return (
          <Card
            key={angle}
            size="small"
            title={
              <span className="text-sm font-medium">
                {t(`productImageGrid.angle.${angle}`)}
              </span>
            }
          >
            <div className="grid grid-cols-4 gap-3">
              {QUALITY_LEVELS.map((quality) => {
                const matched = angleImages.find(
                  (img) => img.quality_level === quality,
                )
                return (
                  <ImageSlot
                    key={`${angle}-${quality}`}
                    angle={angle}
                    quality={quality}
                    image={matched}
                    onUpload={onUpload}
                    onSelectPrimary={onSelectPrimary}
                  />
                )
              })}
            </div>
          </Card>
        )
      })}
    </div>
  )
}

export default ProductImageGrid
