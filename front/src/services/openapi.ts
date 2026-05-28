import { OpenAPI } from './generated'

declare global {
  interface Window {
    __ENV?: {
      BACKEND_URL?: string
    }
  }
}

/**
 * 初始化由 OpenAPI 生成的请求客户端。
 *
 * 开发环境通过 Vite proxy 同源代理后端 API，BASE 设为空串即可。
 * 生产环境通过 window.__ENV.BACKEND_URL 或构建时 VITE_BACKEND_URL 指定。
 */
export function initOpenAPI(base: string = '') {
  OpenAPI.BASE = base
}

const runtimeBackendUrl = window.__ENV?.BACKEND_URL
const buildtimeBackendUrl = import.meta.env.VITE_BACKEND_URL || undefined

initOpenAPI(runtimeBackendUrl ?? buildtimeBackendUrl ?? '')

// W32-followup-2 (Manual QA Bug D 修复)：
// 增加 VITE_API_BASE_URL 作为 prod 部署的最高优先级 absolute URL 覆盖入口，
// 让 prod 镜像 build 时能直接配死后端 URL，不依赖反向代理。
// 仅在显式提供时覆盖，避免污染 dev / 同源 proxy 场景的空 BASE 默认行为。
if (import.meta.env.VITE_API_BASE_URL) {
  OpenAPI.BASE = import.meta.env.VITE_API_BASE_URL
}
