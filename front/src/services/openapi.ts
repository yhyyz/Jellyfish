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

/**
 * v0.7.2 (Manual QA Bug E 修复) — 防呆 strip VITE_API_BASE_URL 末尾 `/api`。
 *
 * 背景：
 *   - generated client 内每个 method 的 url 已含 `/api/v1/...` 前缀。
 *   - 历史 .env / .env.example 把 `VITE_API_BASE_URL` 配为 `http://host/api`，
 *     与 method url 拼接后会出现 `http://host/api/api/v1/...` 双 /api 404。
 *   - Manual QA 在本机 chrome 实测命中 admin login 走双 /api 404 链路。
 *
 * 策略：
 *   - 仅当显式提供 VITE_API_BASE_URL 时介入（dev 同源 proxy 场景空 BASE 不受影响）。
 *   - 末尾若是 `/api` 或 `/api/`，自动 strip，避免与 generated client 前缀重复。
 *   - 其它形态（含正常 root URL、含子路径如 `/api-prod` 等）保持原样。
 */
export function normalizeApiBase(rawBase: string): string {
  if (rawBase.endsWith('/api/')) {
    return rawBase.slice(0, -5)
  }
  if (rawBase.endsWith('/api')) {
    return rawBase.slice(0, -4)
  }
  return rawBase
}

const runtimeBackendUrl = window.__ENV?.BACKEND_URL
const buildtimeBackendUrl = import.meta.env.VITE_BACKEND_URL || undefined

initOpenAPI(runtimeBackendUrl ?? buildtimeBackendUrl ?? '')

// W32-followup-2 (Manual QA Bug D 修复)：
// 增加 VITE_API_BASE_URL 作为 prod 部署的最高优先级 absolute URL 覆盖入口，
// 让 prod 镜像 build 时能直接配死后端 URL，不依赖反向代理。
// 仅在显式提供时覆盖，避免污染 dev / 同源 proxy 场景的空 BASE 默认行为。
//
// v0.7.2 (Manual QA Bug E 修复)：
// 末尾 `/api` 自动 strip，避免与 generated client 已有的 /api 前缀拼成双 /api。
if (import.meta.env.VITE_API_BASE_URL) {
  OpenAPI.BASE = normalizeApiBase(import.meta.env.VITE_API_BASE_URL)
}
