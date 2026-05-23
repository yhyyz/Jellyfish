// 开发环境通过 Vite proxy 同源代理，无需指定后端地址。
// 生产环境部署时由 Docker/Nginx 入口脚本覆盖此文件。
window.__ENV = window.__ENV || {
  BACKEND_URL: '',
}
