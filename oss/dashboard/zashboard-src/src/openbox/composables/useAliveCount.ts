// Open-Box: 节点存活统计（弥补 sing-box Clash API 不返回 alive 字段的缺口）
// 经后端 /api/health（面板侧探测历史）计算 tag -> 是否存活 + 延迟。
import { ref } from 'vue'
import { obxGet } from '../api'

const aliveMap = ref<Map<string, number>>(new Map()) // tag -> latency_ms (>0 表示存活)
let lastFetch = 0

export async function refreshAlive() {
  const now = Date.now()
  if (now - lastFetch < 5000) return // 5s 节流
  lastFetch = now
  try {
    const data = await obxGet<any[]>('/api/health')
    const m = new Map<string, number>()
    for (const h of data || []) {
      if (h.tag && h.latency_ms != null) m.set(h.tag, Number(h.latency_ms))
    }
    aliveMap.value = m
  } catch {
    // 健康数据不可达时保留旧值，不阻塞页面
  }
}

export function isAlive(tag: string): boolean {
  const v = aliveMap.value.get(tag)
  return v != null && v > 0
}

export function aliveCount(tags: string[]): number {
  return tags.filter((t) => isAlive(t)).length
}
