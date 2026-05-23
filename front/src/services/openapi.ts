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
