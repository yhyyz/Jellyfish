import { Spin } from 'antd'

/**
 * 路由级懒加载的统一 fallback 骨架屏。
 * 在页面 chunk 下载 & 解析期间，向用户展示居中 loading 指示器。
 */
export function PageSkeleton() {
  return (
    <div style={{ display: 'flex', justifyContent: 'center', alignItems: 'center', minHeight: '60vh' }}>
      <Spin size="large" />
    </div>
  )
}
