// Open-Box 二开：VPS 本机 Chrome 的 WebSocket 连不上 sing-box，改用轮询面板 /api/openbox/clash-logs。
import type { Log } from '@/types'
import { obxGet } from '@/openbox/api'
import { onUnmounted } from 'vue'
import type { LogsSubscription } from './types'

export const subscribeLogs = (
  params: Record<string, string>,
  onBatch: (batch: Log[]) => void,
): LogsSubscription => {
  let timer: any = null
  let seen = new Set<string>()

  const poll = async () => {
    try {
      const level = params.level || 'info'
      const r = await obxGet<{ logs: Log[] }>(`/api/openbox/clash-logs?level=${encodeURIComponent(level)}`)
      const logs = r.logs || []
      // 只推送新日志
      const fresh = logs.filter((l: Log) => {
        const key = `${l.type}:${l.payload}`
        if (seen.has(key)) return false
        seen.add(key)
        return true
      })
      if (fresh.length) onBatch(fresh)
      // 限制 seen 大小
      if (seen.size > 1000) {
        const arr = Array.from(seen)
        seen = new Set(arr.slice(-500))
      }
    } catch {}
  }

  poll()
  timer = setInterval(poll, 3000)
  const close = () => { if (timer) clearInterval(timer) }
  onUnmounted(close)

  return { close }
}
