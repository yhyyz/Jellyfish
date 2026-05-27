/**
 * ProductImageGrid 组件 TDD 测试套件。
 *
 * 覆盖 W20 Wave A 第一个组件（多角度商品图栅格）的 5 条核心契约：
 *   1. 渲染 7 个角度分组（FRONT/LEFT/RIGHT/BACK/THREE_QUARTER/TOP/DETAIL），每组带本地化标题。
 *   2. 每个角度组内固定渲染 4 个 quality 槽位（LOW/MEDIUM/HIGH/ULTRA），无论是否被填充。
 *   3. 点击空槽位调用 onUpload(angle, quality) 回调，参数透传无误。
 *   4. is_primary=true 的图片显示金色星标识（class 中含 text-yellow-400）。
 *   5. 点击非主图星标触发 onSelectPrimary(imageId) 回调。
 *
 * 测试约定：
 * - 不挂 I18nextProvider，直接断言原始翻译键路径（commerce 命名空间尚未在 i18n.ts 注册，
 *   T20-7 才会接入）。
 * - 使用 data-testid 钩子定位 slot 与 star，避免依赖 antd Card 的内部 DOM 细节。
 */
import { beforeEach, describe, expect, it, vi } from 'vitest'
import { render, screen } from '@testing-library/react'
import userEvent from '@testing-library/user-event'

import { ProductImageGrid } from '../ProductImageGrid'
import type { ProductImageRead } from '../queries'

/**
 * 构造一条最小可用的 ProductImageRead 测试夹具，便于各用例局部覆写。
 *
 * @param overrides 覆写字段（angle/quality/is_primary 等）。
 * @returns 完整的 ProductImageRead 对象。
 */
function buildImage(overrides: Partial<ProductImageRead> = {}): ProductImageRead {
  return {
    id: 1,
    product_id: 'p1',
    file_id: 'file-1',
    quality_level: 'HIGH',
    view_angle: 'FRONT',
    is_primary: false,
    width: null,
    height: null,
    fmt: null,
    created_at: '2024-01-01T00:00:00Z',
    ...overrides,
  }
}

describe('ProductImageGrid', () => {
  const onUpload = vi.fn()
  const onSelectPrimary = vi.fn()

  beforeEach(() => {
    vi.clearAllMocks()
  })

  it('渲染 7 个角度分组并展示本地化标题键', () => {
    render(
      <ProductImageGrid
        productId="p1"
        images={[]}
        onUpload={onUpload}
        onSelectPrimary={onSelectPrimary}
      />,
    )

    // 7 个角度的本地化键应全部出现（i18n 未注册时 t() 会回退为原始 key）。
    expect(screen.getByText('productImageGrid.angle.FRONT')).toBeInTheDocument()
    expect(screen.getByText('productImageGrid.angle.LEFT')).toBeInTheDocument()
    expect(screen.getByText('productImageGrid.angle.RIGHT')).toBeInTheDocument()
    expect(screen.getByText('productImageGrid.angle.BACK')).toBeInTheDocument()
    expect(screen.getByText('productImageGrid.angle.THREE_QUARTER')).toBeInTheDocument()
    expect(screen.getByText('productImageGrid.angle.TOP')).toBeInTheDocument()
    expect(screen.getByText('productImageGrid.angle.DETAIL')).toBeInTheDocument()
  })

  it('每个角度组渲染 4 个 quality 槽位（共 28 个空槽）', () => {
    render(
      <ProductImageGrid
        productId="p1"
        images={[]}
        onUpload={onUpload}
        onSelectPrimary={onSelectPrimary}
      />,
    )

    // 没有任何图片时，全部 7×4=28 个槽位应均为 empty-slot。
    const emptySlots = screen.getAllByTestId(/^empty-slot-/)
    expect(emptySlots).toHaveLength(28)
  })

  it('点击空槽位触发 onUpload(angle, quality)，参数原样传递', async () => {
    const user = userEvent.setup()
    render(
      <ProductImageGrid
        productId="p1"
        images={[]}
        onUpload={onUpload}
        onSelectPrimary={onSelectPrimary}
      />,
    )

    // 点击 FRONT × HIGH 空槽
    await user.click(screen.getByTestId('empty-slot-FRONT-HIGH'))

    expect(onUpload).toHaveBeenCalledTimes(1)
    expect(onUpload).toHaveBeenCalledWith('FRONT', 'HIGH')
  })

  it('is_primary=true 的图片在槽位上显示金色星标（含 text-yellow-400 类）', () => {
    const images: ProductImageRead[] = [
      buildImage({
        id: 1,
        view_angle: 'FRONT',
        quality_level: 'HIGH',
        is_primary: true,
      }),
    ]
    render(
      <ProductImageGrid
        productId="p1"
        images={images}
        onUpload={onUpload}
        onSelectPrimary={onSelectPrimary}
      />,
    )

    const star = screen.getByTestId('primary-star-1')
    expect(star).toHaveClass('text-yellow-400')
  })

  it('点击非主图星标触发 onSelectPrimary(imageId)', async () => {
    const user = userEvent.setup()
    const images: ProductImageRead[] = [
      buildImage({
        id: 7,
        view_angle: 'LEFT',
        quality_level: 'MEDIUM',
        is_primary: false,
      }),
    ]
    render(
      <ProductImageGrid
        productId="p1"
        images={images}
        onUpload={onUpload}
        onSelectPrimary={onSelectPrimary}
      />,
    )

    await user.click(screen.getByTestId('primary-star-7'))

    expect(onSelectPrimary).toHaveBeenCalledTimes(1)
    expect(onSelectPrimary).toHaveBeenCalledWith('7')
  })
})
