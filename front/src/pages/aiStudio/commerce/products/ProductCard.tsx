/**
 * 商品卡片：商品库网格中每一个商品的展示单元。
 *
 * - 复用资产模块的 `DisplayImageCard`，避免重复造轮子。
 * - `imageUrl` 从 `product.images[0].file_id` 经 `resolveAssetUrl` 解析；
 *   列表接口默认 images 为空时降级为占位图。
 * - extra 区提供编辑/删除入口；删除使用 `Popconfirm` 二次确认，
 *   与 ProjectLobby 的删除交互保持一致。
 */
import React from 'react'
import { Button, Popconfirm, Space, Tag } from 'antd'
import { DeleteOutlined, EditOutlined } from '@ant-design/icons'
import { DisplayImageCard } from '../../assets/components/DisplayImageCard'
import { resolveAssetUrl } from '../../assets/utils'
import type { ProductRead } from './queries'

type Props = {
  product: ProductRead
  onEdit: () => void
  onDelete: () => void
  onSelect?: () => void
}

/**
 * 渲染单个商品的卡片。
 *
 * @param product 商品聚合数据；列表场景下 images 默认为空数组。
 * @param onEdit 点击“编辑”按钮的回调；由父级打开 `ProductFormModal`。
 * @param onDelete 用户确认“删除商品”后的回调；由父级触发 mutation。
 * @param onSelect 可选；目前预留给未来“在剧情项目中选择该商品”场景。
 */
export const ProductCard: React.FC<Props> = ({ product, onEdit, onDelete, onSelect }) => {
  const primaryImage = product.images?.[0]
  const imageUrl = primaryImage?.file_id ? resolveAssetUrl(primaryImage.file_id) : undefined

  return (
    <DisplayImageCard
      title={<div className="truncate" title={product.name}>{product.name}</div>}
      imageUrl={imageUrl}
      imageAlt={product.name}
      onImageClick={onSelect}
      extra={
        <Space>
          <Button size="small" icon={<EditOutlined />} onClick={onEdit}>
            编辑
          </Button>
          <Popconfirm
            title="确认删除商品？"
            description="删除后将级联清理图片与项目关联。"
            okText="删除"
            cancelText="取消"
            okButtonProps={{ danger: true }}
            onConfirm={onDelete}
          >
            <Button size="small" danger icon={<DeleteOutlined />} />
          </Popconfirm>
        </Space>
      }
      meta={
        <div className="space-y-1">
          <div className="text-xs text-gray-500">
            品牌：{product.brand || '—'}
            {product.category ? <span className="ml-2">类目：{product.category}</span> : null}
          </div>
          {product.description ? (
            <div className="text-xs text-gray-600 line-clamp-2" title={product.description}>
              {product.description}
            </div>
          ) : null}
          {product.selling_points && product.selling_points.length > 0 ? (
            <div className="flex flex-wrap gap-1">
              {product.selling_points.slice(0, 3).map((s) => (
                <Tag key={s} color="blue" className="m-0">
                  {s}
                </Tag>
              ))}
              {product.selling_points.length > 3 ? (
                <Tag className="m-0">+{product.selling_points.length - 3}</Tag>
              ) : null}
            </div>
          ) : null}
        </div>
      }
    />
  )
}

export default ProductCard
