// Open-Box: 代理页策略设置（服务端持久化）
// 服务端存 settings 表；加载后同步写入 zashboard 原生 store，机制走原生。
import { ref } from 'vue'
import { obxGet, obxPut } from '../api'
import {
  proxySortType,
  minProxyCardWidth,
  groupProxiesByProvider,
} from '@/store/settings'
import { PROXY_SORT_TYPE } from '@/constant'

export const PROXY_CARD_MIN_WIDTH_DEFAULT = 155

// 显示顺序：策略组名数组（服务端 JSON）
export const displayOrder = ref<string[]>([])
export const proxySettingsLoaded = ref(false)

export async function loadProxySettings(): Promise<void> {
  try {
    const s = await obxGet<any>('/api/openbox/proxy-settings')
    if (s) {
      if (s.sort) proxySortType.value = s.sort as PROXY_SORT_TYPE
      groupProxiesByProvider.value = !!s.group_by_provider
      minProxyCardWidth.value = s.card_min_width || PROXY_CARD_MIN_WIDTH_DEFAULT
      displayOrder.value = Array.isArray(s.display_order) ? s.display_order : []
    }
  } catch {
    // 未登录/接口异常时保留本地默认值
  } finally {
    proxySettingsLoaded.value = true
  }
}

export async function saveProxySettings(patch: Record<string, unknown>): Promise<any> {
  const s = await obxPut<any>('/api/openbox/proxy-settings', patch)
  if (s) {
    if (s.sort) proxySortType.value = s.sort as PROXY_SORT_TYPE
    groupProxiesByProvider.value = !!s.group_by_provider
    minProxyCardWidth.value = s.card_min_width || PROXY_CARD_MIN_WIDTH_DEFAULT
    displayOrder.value = Array.isArray(s.display_order) ? s.display_order : []
  }
  return s
}
