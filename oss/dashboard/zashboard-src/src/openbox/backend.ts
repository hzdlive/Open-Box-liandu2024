// Open-Box 二开：首次打开自动接入本机 sing-box 的 Clash API，免去手动填写后端。
// 连接信息由面板 /api/openbox/clash-config 下发（端口/secret），host 取页面当前域名。
import { backendList, setActiveBackend } from '@/store/setup'
import type { Backend } from '@/types'
import { v4 as uuid } from 'uuid'
import { obxGet } from './api'

export async function ensureOpenBoxBackend() {
  if (backendList.value.length > 0) return
  try {
    const cfg = await obxGet<{ port: number; secret: string; listen: string }>('/api/openbox/clash-config')
    const b = {
      type: 'clash',
      protocol: window.location.protocol === 'https:' ? 'https' : 'http',
      host: window.location.hostname,
      port: String(cfg.port || 9090),
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
