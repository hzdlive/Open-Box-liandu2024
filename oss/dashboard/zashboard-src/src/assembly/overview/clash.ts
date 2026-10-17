// Open-Box 二开：VPS 本机 Chrome 的 WebSocket 连不上 sing-box，改用轮询面板 /api/traffic/now。
// 面板接口返回 {download, up}，此处映射为前端期望的 {down, up}。
import { shallowRef, onUnmounted } from 'vue'
import { obxGet } from '@/openbox/api'

export const fetchMemoryAPI = <T>() => {
  // memory 暂不需要，返回空
  const data = shallowRef<T>()
  return { data, close: () => {} }
}

export const fetchTrafficAPI = <T>() => {
  const data = shallowRef<T>()
  let timer: any = null
  let prevDown: number | null = null
  let prevUp: number | null = null
  let prevTime = 0

  const poll = async () => {
    try {
      const r = await obxGet<any>('/api/traffic/now')
      const now = Date.now()
      if (prevDown !== null && prevTime > 0) {
        const dt = (now - prevTime) / 1000
        if (dt > 0) {
          const down = Math.max(0, Math.round(((r.download || 0) - prevDown) / dt))
          const up = Math.max(0, Math.round(((r.up || 0) - prevUp) / dt))
          data.value = { down, up, downTotal: r.download, upTotal: r.up } as T
        }
      }
      prevDown = r.download || 0
      prevUp = r.up || 0
      prevTime = now
    } catch {}
  }

  poll()
  timer = setInterval(poll, 2000)
  const close = () => { if (timer) clearInterval(timer) }
  onUnmounted(close)
  return { data, close }
}
