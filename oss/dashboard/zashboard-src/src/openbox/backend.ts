// Open-Box 二开：首次打开自动接入本机 sing-box 的 Clash API，免去手动填写后端。
// 连接信息由面板 /api/openbox/clash-config 下发（端口/secret），host 取页面当前域名。
import { backendList, setActiveBackend } from '@/store/setup'
import type { Backend } from '@/types'
import { v4 as uuid } from 'uuid'
import { obxGet } from './api'

export async function ensureOpenBoxBackend() {
  try {
    const cfg = await obxGet<{ port: number; secret: string; listen: string }>('/api/openbox/clash-config')
    const port = String(cfg.port || 9090)
    const host = window.location.hostname || '127.0.0.1'
    const protocol = window.location.protocol === 'https:' ? 'https' : 'http'
    // 清除 localStorage 旧数据，避免 useStorage 合并导致字段丢失
    try { localStorage.removeItem('setup/api-list') } catch {}
    try { localStorage.removeItem('setup/active-uuid') } catch {}
    const b = {
      type: 'clash',
      protocol,
      host,
      port,
      secondaryPath: '',
      password: cfg.secret || '',
      uuid: uuid(),
      label: 'Open-Box',
    } as Backend
    backendList.value = [b]
    setActiveBackend(b.uuid)
  } catch {
    /* 面板不可达时保留手动配置入口（Setup 页） */
  }
}
