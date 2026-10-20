<template>
  <div class="flex flex-col gap-2">
    <div v-for="sec in sections" :key="sec.sub || '__none__'">
      <p v-if="sec.sub" class="my-2 text-sm font-semibold">{{ sec.sub }}</p>
      <ProxyNodeGrid>
        <ProxyNodeCard
          v-for="node in sec.proxies"
          :key="node"
          :name="node"
          :group-name="name"
          :active="node === now"
          @click.stop="handlerProxySelect(name, node)"
        />
      </ProxyNodeGrid>
    </div>
  </div>
</template>

<script setup lang="ts">
// Open-Box 自研：按订阅（提供商）分段渲染组内节点。
// zashboard 原生 ProxiesByProvider 按 Clash API 的 provider-name 分组，
// 我们的 sing-box 出站无此字段，故按面板 /api/nodes 的 sub_name 分组。
import { computed, onMounted, ref } from 'vue'
import { handlerProxySelect } from '@/assembly/proxies'
import ProxyNodeCard from '@/components/proxies/ProxyNodeCard.vue'
import ProxyNodeGrid from '@/components/proxies/ProxyNodeGrid.vue'
import { obxGet } from '../api'

const props = defineProps<{
  name: string
  now?: string
  renderProxies: string[]
}>()

const subMap = ref<Record<string, string>>({})

onMounted(async () => {
  try {
    const nodes = await obxGet<any[]>('/api/nodes')
    const m: Record<string, string> = {}
    for (const n of nodes || []) {
      if (n.tag) m[n.tag] = n.sub_name || ''
      if (n.name) m[n.name] = n.sub_name || ''
    }
    subMap.value = m
  } catch {}
})

const sections = computed(() => {
  const bySub = new Map<string, string[]>()
  for (const p of props.renderProxies) {
    const sub = subMap.value[p] || ''
    if (!bySub.has(sub)) bySub.set(sub, [])
    bySub.get(sub)!.push(p)
  }
  // 有订阅名的段在前（按名称排），无订阅（手动节点/直连等）排最后
  return [...bySub.entries()]
    .sort(([a], [b]) => {
      if (a === b) return 0
      if (a === '') return 1
      if (b === '') return -1
      return a.localeCompare(b)
    })
    .map(([sub, proxies]) => ({ sub, proxies }))
})
</script>
