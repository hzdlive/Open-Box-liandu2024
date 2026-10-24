<template>
  <div class="flex flex-col gap-3 p-3">
    <div class="flex items-center gap-2 flex-wrap">
      <SegmentedControl v-model="activeTab" :options="tabOptions" />
      <div class="ml-auto flex items-center gap-2">
        <div class="relative">
          <input v-model="searchText" class="input input-bordered input-sm rounded-full w-70 pr-8" placeholder="搜索 | 多个关键词用空格分隔" />
          <span v-if="searchText" class="absolute right-3 top-1/2 -translate-y-1/2 cursor-pointer opacity-50 hover:opacity-100" @click="searchText = ''">×</span>
        </div>
        <button
          class="btn btn-ghost btn-sm btn-square"
          :title="$t('obx.proxySettings')"
          @click="settingsShow = true"
        >⚙</button>
      </div>
    </div>
    <ProxySettingsModal v-model:show="settingsShow" />
    <ObPolicyTab v-if="activeTab === 'policy'" :search-text="searchText" />
    <div v-if="activeTab === 'node'" class="flex flex-col gap-3">
      <div v-for="name in filteredGroups" :key="name">
        <FailoverGroupExt v-if="isFailoverGroup(name)" :name="name" />
        <ProxyGroup v-else :name="name" />
      </div>
      <div v-if="!filteredGroups.length" class="text-center opacity-50 py-8">无节点组</div>
    </div>
    <ObSubTab v-if="activeTab === 'sub'" :search-text="searchText" />
  </div>
</template>

<script setup lang="ts">
import { ref, computed, onMounted, onUnmounted } from 'vue'
import SegmentedControl from '@/components/common/SegmentedControl.vue'
import ProxyGroup from '@/components/proxies/ProxyGroup.vue'
import { fetchProxies } from '@/assembly/proxies'
import { isProxiesPageMounted } from '@/composables/proxies'
import { visibleProxyGroups } from '../composables/useProxyGroupFilter'
import { loadProxySettings } from '../composables/useProxySettings'
import { refreshAlive } from '../composables/useAliveCount'
import { obxGet } from '../api'
import FailoverGroupExt from '../components/FailoverGroupExt.vue'
import ObPolicyTab from '../components/ObPolicyTab.vue'
import ObSubTab from '../components/ObSubTab.vue'
import ProxySettingsModal from '../components/ProxySettingsModal.vue'

const activeTab = ref('node')
const searchText = ref('')
const settingsShow = ref(false)

// 策略/订阅计数（此前 tabOptions 只给节点加了计数，两处直接丢了）
const policyCount = ref<number | null>(null)
const subCount = ref<number | null>(null)
async function loadTabCounts() {
  try {
    const sitesData = await obxGet<any>('/api/sitesets')
    const list = Array.isArray(sitesData) ? sitesData : (sitesData.sitesets || [])
    // 策略卡 = 站点集 + 兜底其他卡（原版 13 张的构成）
    policyCount.value = list.length + 1
  } catch {}
  try {
    const subsData = await obxGet<any>('/api/subscriptions')
    const list = Array.isArray(subsData) ? subsData : (subsData.subscriptions || [])
    subCount.value = list.length
  } catch {}
}

const tabOptions = computed(() => [
  { value: 'policy', label: policyCount.value === null ? '策略' : `策略 (${policyCount.value})` },
  { value: 'node', label: `节点 (${filteredGroups.value.length})` },
  { value: 'sub', label: subCount.value === null ? '订阅' : `订阅 (${subCount.value})` },
])

const failoverNames = ref<Set<string>>(new Set())
async function loadFailoverNames() {
  try {
    const data = await obxGet<any[]>('/api/groups')
    const list = Array.isArray(data) ? data : []
    failoverNames.value = new Set(list.filter((g: any) => g.type === 'failover').map((g: any) => g.name))
  } catch {}
}
function isFailoverGroup(name: string): boolean {
  return failoverNames.value.has(name)
}

const filteredGroups = computed(() => {
  const q = searchText.value.trim().toLowerCase()
  if (!q) return visibleProxyGroups.value
  const keys = q.split(/\s+/).filter(Boolean)
  return visibleProxyGroups.value.filter((n) => keys.every((k) => n.toLowerCase().includes(k)))
})

let timer: any = null
onMounted(() => {
  // 原生 ProxiesPage 会在挂载后把 isProxiesPageMounted 置 true，
  // 解除首屏只取 16 条的限制；路由实际挂的是本组件，原生页从未挂载，
  // 该标志恒为 false，导致排序第 17 位的“所有-手动”被 slice 永久切掉
  // （前 16 位里有 10 个隐藏项：其他 + 6 个 sub-* + 3 个 lane）。
  isProxiesPageMounted.value = true
  fetchProxies()
  loadFailoverNames()
  loadProxySettings()
  loadTabCounts()
  refreshAlive()
  timer = setInterval(refreshAlive, 10000)
})
onUnmounted(() => {
  if (timer) clearInterval(timer)
})
</script>
