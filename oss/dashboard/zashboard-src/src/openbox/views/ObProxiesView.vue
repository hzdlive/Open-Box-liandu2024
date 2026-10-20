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

const tabOptions = computed(() => [
  { value: 'policy', label: '策略' },
  { value: 'node', label: `节点 (${filteredGroups.value.length})` },
  { value: 'sub', label: '订阅' },
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
  fetchProxies()
  loadFailoverNames()
  loadProxySettings()
  refreshAlive()
  timer = setInterval(refreshAlive, 10000)
})
onUnmounted(() => {
  if (timer) clearInterval(timer)
})
</script>
