/**
 * @deprecated 此模块为遗留桩代码，仅为尚未迁移到 OpenAPI generated client 的页面提供编译兼容。
 * 所有新代码应使用 `./generated/` 中的 OpenAPI client。
 * TODO: 迁移 aiStudio/agents 页面后删除此文件与 aiStudioApi.ts。
 */

const backendBaseUrl = import.meta.env.VITE_BACKEND_URL ?? 'http://localhost:8000'
const baseURL = import.meta.env.VITE_API_BASE_URL ?? `${backendBaseUrl}/api`

/** 简易 fetch 封装，替代已移除的 axios 依赖 */
async function request<T>(method: string, url: string, data?: unknown): Promise<T> {
  const res = await fetch(`${baseURL}${url}`, {
    method,
    headers: data ? { 'Content-Type': 'application/json' } : undefined,
    body: data ? JSON.stringify(data) : undefined,
  })
  if (!res.ok) throw new Error(`HTTP ${res.status}`)
  return res.json() as Promise<T>
}

export const get = <T = unknown>(url: string): Promise<T> => request<T>('GET', url)

export const post = <T = unknown>(url: string, data?: unknown): Promise<T> =>
  request<T>('POST', url, data)

export const put = <T = unknown>(url: string, data?: unknown): Promise<T> =>
  request<T>('PUT', url, data)

export const del = <T = unknown>(url: string): Promise<T> => request<T>('DELETE', url)

export default { get, post, put, del }
