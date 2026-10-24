// Open-Box: 过滤代理页不显示的内部组
// flip-*: 站点集翻转选择器（策略 Tab 已展示）
// obflip-*: QUIC 阻断内联 rule_set 引用
// __fo:*: 故障转移内部出站
// sub-*: 订阅 urltest 组（订阅 Tab 已展示）
import { computed } from 'vue'
import { renderProxyGroups } from '@/composables/proxies'

const HIDDEN_PREFIXES = ['flip-', 'obflip-', '__fo:', 'sub-']

// 原版节点 Tab 不列兜底组：其他只在策略 Tab 里当第 13 张卡。
// 这里只做视图层过滤 -- 内核里的其他 selector、策略卡、
// /api/openbox/final-select 热切换都不受影响。
// GLOBAL 同理：displayGlobalByMode=false 时它会被追加进节点列表，
// 原版节点 Tab 不列这个伪组；mounted 修复后它会冒出来，一并在视图层过滤。
const HIDDEN_EXACT = new Set(['其他', 'GLOBAL'])

export function isHiddenGroup(name: string): boolean {
  // lane 子组（含 #）由 FailoverGroupExt 归集，顶层不单独显示
  if (name.includes('#')) return true
  if (HIDDEN_EXACT.has(name)) return true
  return HIDDEN_PREFIXES.some((p) => name.startsWith(p))
}

export const visibleProxyGroups = computed(() =>
  renderProxyGroups.value.filter((name) => !isHiddenGroup(name)),
)
