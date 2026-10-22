<template>
  <div class="flex flex-col gap-3">
    <div
      v-for="site in orderedSites"
      :key="site.id"
      class="rounded-box border border-base-300/30 bg-base-100 p-4"
    >
      <div class="flex items-center gap-3 cursor-pointer" @click="expanded = expanded === site.id ? null : site.id">
        <div class="text-3xl leading-none">{{ mapIcon(site.icon, site.name) }}</div>
        <div class="flex-1 flex items-center gap-2 flex-wrap">
          <span class="text-base font-semibold">{{ site.name }}</span>
          <span class="badge badge-success badge-sm">域名穿透</span>
          <span class="text-sm opacity-60">Selector ({{ site.matched }}/{{ site.total }})</span>
        </div>
        <div class="badge" :class="latencyClass(site.latency)">{{ site.latency }}</div>
      </div>
      <div class="mt-2 text-sm opacity-70">
        <span v-if="site.isOther">🎯 {{ site.selected }}</span>
        <span v-else>
          <span>🌍 {{ site.currentGroup }}</span>
          <span v-if="site.currentNode"> ⊕ {{ site.currentNode }}</span>
        </span>
      </div>
      <!-- 成员存活圆点（对标原生 ProxyPreview：延迟>0 为存活，按延迟着色，选中带圈） -->
      <div v-if="site.options.length" class="mt-2 flex gap-1.5">
        <span
          v-for="opt in site.options"
          :key="opt.name"
          class="inline-block h-2.5 w-2.5 rounded-full"
          :class="dotClass(opt, site.selected)"
          :title="`${opt.name}: ${opt.delay > 0 ? opt.delay + 'ms' : '未连通'}`"
        />
      </div>
      <div v-if="expanded === site.id" class="mt-3 grid gap-2 sm:grid-cols-2 lg:grid-cols-3">
        <div
          v-for="opt in site.options"
          :key="opt.name"
          class="rounded-box border p-3 cursor-pointer transition-colors hover:border-success"
          :class="opt.name === site.selected
            ? 'bg-success text-success-content border-success'
            : 'border-base-300/50 bg-base-100'"
          @click="selectOutbound(site, opt)"
        >
          <div class="text-sm font-medium">{{ opt.name }}</div>
          <div class="text-xs opacity-60 mt-1">
            {{ opt.type }} / udp
            <span class="badge badge-sm ml-1" :class="opt.name === site.selected ? 'badge-ghost' : latencyClass(opt.latency)">{{ opt.latency }}</span>
          </div>
        </div>
      </div>
    </div>
  </div>
</template>

<script setup lang="ts">
import { ref, onMounted, computed } from 'vue'
import { obxGet, obxPost } from '../api'
import { siteIcon } from '../composables/useSiteIcon'
import { displayOrder } from '../composables/useProxySettings'

const props = defineProps<{ searchText?: string }>()

function mapIcon(iconId: string | undefined, name: string): string {
  return siteIcon(iconId, name)
}

function latencyClass(lat: string | number | undefined): string {
  const n = typeof lat === 'string' ? parseInt(lat) : (lat ?? NaN)
  if (isNaN(n) || n <= 0) return 'badge-ghost'
  if (n < 150) return 'badge-success'
  if (n < 300) return 'badge-warning'
  return 'badge-error'
}

// 原生语义：存活 = 延迟不为 NOT_CONNECTED（0）。Clash API 不返 latency 字段，
// 延迟取 history 最后一条的 delay；无 history 即未连通。
function lastDelay(p: any): number {
  const h = p?.history
  if (!Array.isArray(h) || !h.length) return 0
  const d = h[h.length - 1]?.delay
  return typeof d === 'number' && d > 0 ? d : 0
}

function dotClass(opt: any, selected: string): string {
  const ring = opt.name === selected ? 'ring-2 ring-offset-1 ring-success' : ''
  if (!opt.delay || opt.delay <= 0) return `bg-base-300 ${ring}`
  if (opt.delay < 150) return `bg-success ${ring}`
  if (opt.delay < 300) return `bg-warning ${ring}`
  return `bg-error ${ring}`
}

const sites = ref<any[]>([])

// 显示顺序（策略设置里拖拽保存）：已保存名单优先，未保存的按站点集原序追加
const orderedSites = computed(() => {
  const order = displayOrder.value
  if (!order.length) return sites.value
  const idx = new Map(order.map((n, i) => [n, i]))
  return [...sites.value].sort((a, b) => {
    const ia = idx.get(a.name) ?? Number.MAX_SAFE_INTEGER
    const ib = idx.get(b.name) ?? Number.MAX_SAFE_INTEGER
    if (ia !== ib) return ia - ib
    return sites.value.indexOf(a) - sites.value.indexOf(b)
  })
})
const expanded = ref<string | null>(null)

async function load() {
  try {
    const [sitesData, clashData] = await Promise.all([
      obxGet<any>('/api/sitesets'),
      obxGet<any>('/api/openbox/clash-proxies').catch(() => ({ proxies: {} })),
    ])
    const list = Array.isArray(sitesData) ? sitesData : (sitesData.sitesets || [])
    const proxies = clashData.proxies || {}
    const q = (props.searchText || '').toLowerCase()
    sites.value = list
      .filter((s: any) => !q || s.name.toLowerCase().includes(q))
      .map((s: any) => {
        const flipTag = `flip-${s.id}`
        const flipInfo = proxies[flipTag] || {}
        const all = flipInfo.all || []
        const options = all.map((name: string) => {
          const p = proxies[name] || {}
          const delay = lastDelay(p)
          return { name, type: p.type || 'selector', latency: delay > 0 ? delay : '', delay }
        })
        return {
          id: s.id,
          name: s.name,
          icon: s.icon,
          // 原生语义：matched = 存活数（延迟>0），total = 成员数；此前两者都写 all.length，恒为 (N/N)
          matched: options.filter((o: any) => o.delay > 0).length,
          total: all.length,
          latency: lastDelay(flipInfo) || '',
          currentGroup: s.group || '所有-自动',
          currentNode: flipInfo.now || '',
          selected: flipInfo.now || '',
          options,
        }
      })
    // 兜底策略卡（其他，1:1 对标原版第 13 张卡）：无规则命中时走 route.final，
    // 后端把 final 做成含全部组的选择器（tag 其他），卡片与站点集卡同源渲染；
    // 内核未重建前无此选择器时不渲染，避免 (0/0) 空卡。
    const otherInfo = proxies['其他']
    if (otherInfo && (!q || '其他'.includes(q))) {
      const all = otherInfo.all || []
      const options = all.map((name: string) => {
        const p = proxies[name] || {}
        const delay = lastDelay(p)
        return { name, type: p.type || 'selector', latency: delay > 0 ? delay : '', delay }
      })
      sites.value.push({
        id: 'other',
        name: '其他',
        icon: 'globe:earth-americas',
        isOther: true,
        matched: options.filter((o: any) => o.delay > 0).length,
        total: all.length,
        latency: lastDelay(otherInfo) || '',
        currentGroup: '',
        currentNode: otherInfo.now || '',
        selected: otherInfo.now || '',
        options,
      })
    }
  } catch (e) {
    console.error('load policies failed', e)
  }
}

async function selectOutbound(site: any, opt: any) {
  try {
    if (site.isOther) {
      await obxPost<any>('/api/openbox/final-select', { outbound: opt.name })
      site.selected = opt.name
      site.currentNode = opt.name
      return
    }
    const res = await obxPost<any>(`/api/sitesets/${site.id}/select`, { outbound: opt.name })
    site.selected = opt.name
    site.currentNode = opt.name
    // 后端把选择落盘为 group/action，卡片首行（group ⊕ now）随之同步
    if (res?.site_set?.group) site.currentGroup = res.site_set.group
  } catch (e) {
    console.error('select failed', e)
  }
}

onMounted(load)
defineExpose({ reload: load })
</script>
