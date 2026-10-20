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
        <span>🌍 {{ site.currentGroup }}</span>
        <span v-if="site.currentNode"> ⊕ {{ site.currentNode }}</span>
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
        return {
          id: s.id,
          name: s.name,
          icon: s.icon,
          matched: all.length,
          total: all.length,
          latency: flipInfo.latency || '',
          currentGroup: s.group || '所有-自动',
          currentNode: flipInfo.now || '',
          selected: flipInfo.now || '',
          options: all.map((name: string) => {
            const p = proxies[name] || {}
            return { name, type: p.type || 'selector', latency: p.latency || '' }
          }),
        }
      })
  } catch (e) {
    console.error('load policies failed', e)
  }
}

async function selectOutbound(site: any, opt: any) {
  try {
    await obxPost(`/api/sitesets/${site.id}/select`, { outbound: opt.name })
    site.selected = opt.name
    site.currentNode = opt.name
  } catch (e) {
    console.error('select failed', e)
  }
}

onMounted(load)
defineExpose({ reload: load })
</script>
