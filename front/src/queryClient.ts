/**
 * TanStack Query 全局配置。
 *
 * 提供统一的缓存策略、重试策略和 refetch 行为，
 * 供所有页面的 useQuery / useMutation 共享。
 */
import { QueryClient } from '@tanstack/react-query'

export const queryClient = new QueryClient({
  defaultOptions: {
    queries: {
      staleTime: 30 * 1000, // 30s 内视为新鲜，不重复请求
      refetchOnWindowFocus: false, // 聚焦窗口不自动刷新
      retry: 1, // 失败后重试 1 次
    },
  },
})
