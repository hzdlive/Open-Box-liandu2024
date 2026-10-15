// Open-Box 二开：面板登录门禁（沿用 Flask /api/auth/*，与旧版 UI 同一套 session）
import { reactive } from 'vue'
import { obxGet, obxPost } from './api'

export const obxAuth = reactive({ checked: false, hasPassword: false, loggedIn: false })

export async function checkObxAuth() {
  try {
    const s = await obxGet<{ has_password: boolean; logged_in: boolean }>('/api/auth/status')
    obxAuth.hasPassword = s.has_password
    obxAuth.loggedIn = s.logged_in || !s.has_password
  } catch {
    // 面板不可达时不挡住仪表盘（纯 Clash API 使用场景）
    obxAuth.hasPassword = false
    obxAuth.loggedIn = true
  }
  obxAuth.checked = true
}

export async function obxLogin(password: string) {
  await obxPost('/api/auth/login', { password })
  obxAuth.loggedIn = true
}

export function needObxLogin() {
  return obxAuth.checked && obxAuth.hasPassword && !obxAuth.loggedIn
}
