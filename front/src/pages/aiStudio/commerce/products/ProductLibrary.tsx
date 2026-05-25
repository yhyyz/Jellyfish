/**
 * 商品库 (ProductLibrary) 页面。
 *
 * 范式锚点：
 * - 列表数据走 TanStack Query 的 `useProductList`，禁止裸 useState + load()
 *   的旧模式（参见 research.md F2 delta）；
 * - 新建 / 编辑共用 `ProductFormModal`（基于 `Form.useForm`），
 *   与 ProjectLobby 的弹窗范式保持一致（F3 delta）；
 * - 卡片复用 `DisplayImageCard`，禁止重复实现样式（F-table）。
 *
 * 页面定位：
 * - “准备”性质的资产管理面板：负责商品的录入、编辑、删除与 AI 抽取入队；
 * - 不承担生成态状态展示（P2 任务进度交给任务中心）。
 */
import React, { useState } from 'react'
import {
  Button,
  Card,
  Empty,
  Input,
  Pagination,
  Select,
  Space,
  Spin,
  message,
} from 'antd'
import { LinkOutlined, PlusOutlined, ReloadOutlined } from '@ant-design/icons'
import { useQueryClient } from '@tanstack/react-query'
import { ScrollablePage } from '../../components/ScrollablePage'
import { ProductCard } from './ProductCard'
import { ProductFormModal } from './ProductFormModal'
import { URLExtractModal } from './URLExtractModal'
import {
  productKeys,
  useDeleteProduct,
  useProductList,
  type ProductRead,
} from './queries'

/** 类目筛选下拉选项；与 backend `ProductCategory` 严格对齐 */
const CATEGORY_FILTER_OPTIONS = [
  { value: 'electronics', label: '电子' },
  { value: 'beauty', label: '美妆' },
  { value: 'food', label: '食品' },
  { value: 'apparel', label: '服饰' },
  { value: 'home', label: '家居' },
  { value: 'health', label: '健康' },
  { value: 'other', label: '其他' },
]

/**
 * 渲染商品库页面：搜索 + 类目过滤 + 卡片网格 + 分页 + 新建/提取/编辑弹窗。
 *
 * 核心状态：
 * - `search`：输入框文本，回车后才触发查询（避免 keystroke 抖动）；
 * - `searchActive`：真正下发到 API 的关键字，与输入框解耦；
 * - `category`：类目过滤；变更后回到首页；
 * - `page` / `pageSize`：分页参数；目前固定 12/页。
 */
const ProductLibrary: React.FC = () => {
  const qc = useQueryClient()

  const [search, setSearch] = useState('')
  const [searchActive, setSearchActive] = useState('')
  const [category, setCategory] = useState<string | undefined>(undefined)
  const [page, setPage] = useState(1)
  const pageSize = 12

  const { data, isLoading, isFetching } = useProductList({
    q: searchActive || undefined,
    category,
    page,
    pageSize,
  })
  const deleteMutation = useDeleteProduct()

  const [createOpen, setCreateOpen] = useState(false)
  const [editingProduct, setEditingProduct] = useState<ProductRead | null>(null)
  const [extractOpen, setExtractOpen] = useState(false)

  const handleRefresh = () => {
    void qc.invalidateQueries({ queryKey: productKeys.all })
  }

  const handleSearch = (value: string) => {
    setPage(1)
    setSearchActive(value.trim())
  }

  const handleCategoryChange = (value: string | undefined) => {
    setPage(1)
    setCategory(value)
  }

  const handleDelete = async (productId: string) => {
    try {
      await deleteMutation.mutateAsync(productId)
      message.success('已删除商品')
    } catch {
      message.error('删除失败')
    }
  }

  const items: ProductRead[] = data?.items ?? []
  const total = data?.total ?? 0
  const formModalOpen = createOpen || editingProduct !== null

  return (
    <ScrollablePage className="pr-1">
      <Card
        title="商品库"
        extra={
          <Space wrap>
            <Input.Search
              placeholder="搜索商品名称 / 描述"
              allowClear
              value={search}
              onChange={(e) => setSearch(e.target.value)}
              onSearch={handleSearch}
              style={{ width: 240 }}
            />
            <Button icon={<ReloadOutlined />} onClick={handleRefresh}>
              刷新
            </Button>
            <Button icon={<LinkOutlined />} onClick={() => setExtractOpen(true)}>
              从 URL 提取
            </Button>
            <Button type="primary" icon={<PlusOutlined />} onClick={() => setCreateOpen(true)}>
              新建商品
            </Button>
          </Space>
        }
      >
        <Space className="mb-3" wrap>
          <Select
            placeholder="按类目过滤"
            allowClear
            options={CATEGORY_FILTER_OPTIONS}
            value={category}
            onChange={handleCategoryChange}
            style={{ width: 180 }}
          />
        </Space>

        {isLoading ? (
          <div className="py-12 text-center">
            <Spin />
          </div>
        ) : items.length === 0 ? (
          <Empty description="暂无商品" image={Empty.PRESENTED_IMAGE_SIMPLE} />
        ) : (
          <div className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-4 gap-3">
            {items.map((p) => (
              <ProductCard
                key={p.id}
                product={p}
                onEdit={() => setEditingProduct(p)}
                onDelete={() => void handleDelete(p.id)}
              />
            ))}
          </div>
        )}

        {total > pageSize ? (
          <div className="mt-4 flex justify-end">
            <Pagination
              current={page}
              pageSize={pageSize}
              total={total}
              showSizeChanger={false}
              disabled={isFetching}
              onChange={(nextPage: number) => setPage(nextPage)}
            />
          </div>
        ) : null}
      </Card>

      <ProductFormModal
        mode={editingProduct ? 'edit' : 'create'}
        open={formModalOpen}
        initial={editingProduct}
        onCancel={() => {
          setCreateOpen(false)
          setEditingProduct(null)
        }}
        onSuccess={() => {
          setCreateOpen(false)
          setEditingProduct(null)
        }}
      />

      <URLExtractModal
        open={extractOpen}
        onCancel={() => setExtractOpen(false)}
      />
    </ScrollablePage>
  )
}

export default ProductLibrary
