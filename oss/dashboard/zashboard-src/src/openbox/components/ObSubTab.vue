<template>
  <!-- v0.1.368：组卡片按设备分列（与策略、节点页签统一） -->
  <div :class="['grid gap-3', proxyGroupColumnsClass]">
    <div
      v-for="sub in subs"
      :key="sub.id"
      class="rounded-box border border-base-300/30 bg-base-100 p-4"
    >
      <div class="flex items-center gap-3 cursor-pointer" @click="expanded = expanded === sub.id ? null : sub.id">
        <!-- v0.1.363：窄屏下名称容器缺 min-w-0 时 flex 子项按内容最小宽
             拒绝收缩，长订阅名会把右侧按钮推出屏外；名称截断 + 按钮
             区不收缩，保证按钮始终与订阅名同排靠右。 -->
        <div class="flex-1 flex items-center gap-2 min-w-0">
          <span class="text-base font-semibold truncate">{{ sub.name }} ({{ sub.alive }}/{{ sub.total }})</span>
          <span class="badge badge-ghost badge-sm shrink-0">{{ sub.mode === 'login' ? '登录' : sub.mode === 'subscription' ? '订阅' : '节点' }}</span>
        </div>
        <div class="flex gap-1 shrink-0">
          <button class="btn btn-ghost btn-sm text-lg" @click.stop="speedtest(sub)" title="测速">⚡</button>
          <button class="btn btn-ghost btn-sm text-lg" @click.stop="refresh(sub)" title="刷新">🔄</button>
        </div>
      </div>
      <div class="mt-1 text-xs opacity-50">更新于 {{ sub.updated }} · {{ sub.traffic }}</div>
      <div v-if="expanded === sub.id" class="mt-3 grid gap-2 sm:grid-cols-2 lg:grid-cols-3">
        <div
          v-for="m in sub.nodes"
          :key="m.name"
          class="rounded-box border border-base-300/50 bg-base-100 p-3"
        >
          <div class="text-sm font-medium">{{ m.name }}</div>
          <div class="text-xs opacity-60 mt-1">
            {{ m.protocol }} / udp
            <span class="badge badge-sm ml-1" :class="latencyClass(m.latency)">{{ m.latency }}</span>
          </div>
        </div>
      </div>
    </div>
  </div>
</template>

<script setup lang="ts">
import { ref, onMounted } from 'vue'
import { obxGet, obxPost } from '../api'
import { proxyGroupColumnsClass } from '@/store/settings'

const props = defineProps<{ searchText?: string }>()

function latencyClass(lat: any): string {
  const n = typeof lat === 'string' ? parseInt(lat) : (lat ?? NaN)
  if (isNaN(n) || n <= 0) return 'badge-ghost'
  if (n < 150) return 'badge-success'
  if (n < 300) return 'badge-warning'
  return 'badge-error'
}

const subs = ref<any[]>([])
const expanded = ref<number | null>(null)

async function load() {
  try {
    const data = await obxGet<any>('/api/subscriptions')
    const list = Array.isArray(data) ? data : (data.subscriptions || [])
    const q = (props.searchText || '').toLowerCase()
    subs.value = await Promise.all(
      list
        .filter((s: any) => !q || s.name.toLowerCase().includes(q))
        .map(async (s: any) => {
          let nodes: any[] = []
          try {
            const nd = await obxGet<any>(`/api/subscriptions/${s.id}/nodes`)
            nodes = Array.isArray(nd) ? nd : (nd.nodes || [])
          } catch {}
          return {
            id: s.id,
            name: s.name,
            mode: s.mode,
            alive: s.node_count || 0,
            total: s.node_total || s.node_count || 0,
            updated: s.updated_at ? new Date(s.updated_at).toLocaleString('zh-CN') : '',
            traffic: s.userinfo || '',
            nodes: nodes.map((n: any) => ({
              name: n.tag || n.name,
              protocol: n.protocol || n.type || '',
              latency: n.latency || '',
            })),
          }
        }),
    )
  } catch (e) {
    console.error('load subs failed', e)
  }
}

async function speedtest(sub: any) {
  try {
    await obxPost(`/api/subscriptions/${sub.id}/speedtest`, {})
  } catch (e) {
    console.error('speedtest failed', e)
  }
}

async function refresh(sub: any) {
  try {
    await obxPost(`/api/subscriptions/${sub.id}/refresh`, {})
    load()
  } catch (e) {
    console.error('refresh failed', e)
  }
}

onMounted(load)
defineExpose({ reload: load })
</script>
