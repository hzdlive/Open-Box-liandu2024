// Open-Box: 过滤代理页不显示的内部组
// flip-*: 站点集翻转选择器（策略 Tab 已展示）
// obflip-*: QUIC 阻断内联 rule_set 引用
// __fo:*: 故障转移内部出站
// sub-*: 订阅 urltest 组（订阅 Tab 已展示）
import { computed } from 'vue'
import { renderProxyGroups } from '@/composables/proxies'

const HIDDEN_PREFIXES = ['flip-', 'obflip-', '__fo:', 'sub-']

export function isHiddenGroup(name: string): boolean {
  // lane 子组（含 #）由 FailoverGroupExt 归集，顶层不单独显示
  if (name.includes('#')) return true
  return HIDDEN_PREFIXES.some((p) => name.startsWith(p))
}

export const visibleProxyGroups = computed(() =>
  renderProxyGroups.value.filter((name) => !isHiddenGroup(name)),
)
