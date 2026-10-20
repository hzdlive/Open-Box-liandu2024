<!-- Open-Box: 共享出口选择器（节点/节点组/订阅 三页签）
  从 SitesTab/ChainsTab/TerminalsTab 的三份重复实现抽取。
  用法: <ObOutboundSelector v-model:show="selShow" @select="onSelect" />
-->
<template>
  <div v-if="show" class="modal modal-open">
    <div class="modal-box max-w-lg">
      <div class="mb-3 flex items-center justify-between">
        <h3 class="text-lg font-bold">{{ $t('obx.selectOutbound') }}</h3>
        <button class="btn btn-ghost btn-sm btn-square" @click="close">✕</button>
      </div>
      <!-- 页签 -->
      <div class="mb-3 flex gap-2">
        <button type="button" class="btn btn-sm" :class="tab === 'nodes' ? 'btn-success' : 'btn-ghost'" @click="tab = 'nodes'; search = ''">
          {{ $t('obx.nodes') }} ({{ nodes.length }})
        </button>
        <button type="button" class="btn btn-sm" :class="tab === 'groups' ? 'btn-success' : 'btn-ghost'" @click="tab = 'groups'; search = ''">
          {{ $t('obx.nodeGroups') }} ({{ groups.length }})
        </button>
        <button v-if="showSubs" type="button" class="btn btn-sm" :class="tab === 'subs' ? 'btn-success' : 'btn-ghost'" @click="tab = 'subs'; search = ''">
          {{ $t('obx.subscriptions') }} ({{ subs.length }})
        </button>
        <div class="relative flex-1">
          <input v-model="search" class="input input-bordered input-sm w-full pr-8" :placeholder="$t('obx.search')" />
          <button v-if="search" class="btn btn-ghost btn-xs absolute right-1 top-1/2 -translate-y-1/2" @click="search = ''">✕</button>
        </div>
      </div>
      <!-- 节点列表 -->
      <div v-if="tab === 'nodes'" class="max-h-96 overflow-y-auto">
        <div class="mb-1 px-2 text-xs opacity-60">{{ $t('obx.builtin') }}</div>
        <button type="button" class="flex w-full items-center justify-between px-3 py-2 text-left hover:bg-base-200" @click="pick('direct')">
          <span>{{ $t('obx.direct') }}</span>
        </button>
        <button type="button" class="flex w-full items-center justify-between px-3 py-2 text-left hover:bg-base-200" @click="pick('reject')">
          <span>{{ $t('obx.reject') }}</span>
        </button>
        <div class="mb-1 mt-2 px-2 text-xs opacity-60">{{ $t('obx.nodes') }}</div>
        <div v-if="loading" class="p-4 text-center opacity-60">{{ $t('obx.loading') }}</div>
        <button
          v-for="n in filteredNodes" :key="n.id || n.tag" type="button"
          class="flex w-full items-center justify-between px-3 py-2 text-left hover:bg-base-200"
          @click="pick(n.tag || n.name)"
        >
          <span class="truncate"><span v-if="n.sub_name" class="badge badge-ghost badge-xs mr-1">{{ n.sub_name }}</span>{{ n.name || n.tag }}</span>
          <span v-if="latency(n.tag || n.name)" class="text-sm" :class="latencyCls(n.tag || n.name)">{{ latency(n.tag || n.name) }}</span>
        </button>
        <template v-if="showChains">
          <div v-if="filteredChains.length" class="mb-1 mt-2 px-2 text-xs opacity-60">
            {{ $t('obx.chains') || '链式代理' }}
          </div>
          <button
            v-for="c in filteredChains" :key="c.id" type="button"
            class="flex w-full items-center justify-between px-3 py-2 text-left hover:bg-base-200"
            @click="pick(c.name)"
          >
            <span class="truncate">{{ c.name }}</span>
            <span v-if="latency(c.name)" class="text-sm" :class="latencyCls(c.name)">{{ latency(c.name) }}</span>
          </button>
        </template>
      </div>
      <!-- 节点组列表 -->
      <div v-else-if="tab === 'groups'" class="max-h-96 overflow-y-auto">
        <div v-if="loading" class="p-4 text-center opacity-60">{{ $t('obx.loading') }}</div>
        <button
          v-for="g in filteredGroups" :key="g.id" type="button"
          class="flex w-full items-center justify-between px-3 py-2 text-left hover:bg-base-200"
          @click="pick(g.name)"
        >
          <span class="truncate">{{ g.name }}</span>
        </button>
      </div>
      <!-- 订阅列表 -->
      <div v-else-if="tab === 'subs' && showSubs" class="max-h-96 overflow-y-auto">
        <div v-if="loading" class="p-4 text-center opacity-60">{{ $t('obx.loading') }}</div>
        <button
          v-for="s in filteredSubs" :key="s.id" type="button"
          class="flex w-full items-center justify-between px-3 py-2 text-left hover:bg-base-200"
          @click="pick('sub-' + s.id)"
        >
          <span class="truncate">{{ s.name }}</span>
          <span class="badge badge-ghost badge-xs">{{ s.node_count }}</span>
        </button>
      </div>
    </div>
  </div>
</template>

<script setup lang="ts">
import { ref, computed, watch } from 'vue'
import { obxGet } from '../api'

const props = defineProps<{
  show: boolean
  showSubs?: boolean   // 订阅页签（默认显示；链式/终端用不到可关）
  showChains?: boolean // 节点页签内的链式代理分组（默认显示）
}>()
const emit = defineEmits<{
  (e: 'update:show', v: boolean): void
  (e: 'select', value: string): void
}>()

const showSubs = computed(() => props.showSubs !== false)
const showChains = computed(() => props.showChains !== false)

const tab = ref<'nodes' | 'groups' | 'subs'>('nodes')
const search = ref('')
const loading = ref(false)
const nodes = ref<any[]>([])
const groups = ref<any[]>([])
const chains = ref<any[]>([])
const subs = ref<any[]>([])
const health = ref<Record<string, number>>({})

async function load() {
  loading.value = true
  try {
    const [n, g, c, h, s] = await Promise.all([
      obxGet<any[]>('/api/nodes'),
      obxGet<any[]>('/api/groups'),
      obxGet<any[]>('/api/chains').catch(() => []),
      obxGet<any[]>('/api/health').catch(() => []),
      obxGet<any[]>('/api/subscriptions').catch(() => []),
    ])
    nodes.value = n || []
    chains.value = c || []
    subs.value = (s || []).map((x: any) => ({
      ...x,
      node_count: (n || []).filter((node: any) => node.sub_id === x.id).length,
    }))
    // 节点组页签只显示真实分组（直连/拒绝在节点页签内置区）
    groups.value = (g || []).filter(
      (x: any) => x.name !== 'direct' && x.name !== 'block' && x.tag !== 'direct' && x.tag !== 'block',
    )
    const hm: Record<string, number> = {}
    for (const item of h || []) if (item.latency_ms != null) hm[item.tag] = item.latency_ms
    health.value = hm
  } catch {
    // 加载失败保留空列表
  } finally {
    loading.value = false
  }
}

watch(() => props.show, (v) => {
  if (v) {
    tab.value = 'nodes'
    search.value = ''
    load()
  }
})

const q = computed(() => search.value.trim().toLowerCase())
const filteredNodes = computed(() =>
  !q.value ? nodes.value : nodes.value.filter((n: any) => (n.name || n.tag || '').toLowerCase().includes(q.value)))
const filteredChains = computed(() =>
  !q.value ? chains.value : chains.value.filter((c: any) => (c.name || '').toLowerCase().includes(q.value)))
const filteredGroups = computed(() =>
  !q.value ? groups.value : groups.value.filter((g: any) => (g.name || '').toLowerCase().includes(q.value)))
const filteredSubs = computed(() =>
  !q.value ? subs.value : subs.value.filter((s: any) => (s.name || '').toLowerCase().includes(q.value)))

function latency(tag: string): number | '' {
  const v = health.value[tag]
  return v != null && v > 0 ? v : ''
}
function latencyCls(tag: string): string {
  const v = Number(health.value[tag] ?? Infinity)
  return v < 300 ? 'text-success' : v < 800 ? 'text-warning' : 'text-error'
}
function pick(value: string) {
  emit('select', value)
  emit('update:show', false)
}
function close() {
  emit('update:show', false)
}
</script>
