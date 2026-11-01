<template>
  <div class="relative flex size-full flex-col overflow-hidden">
    <!-- v0.1.365：连接、日志、运行规则合并为“连接”页，以页签切换。
         v0.1.366：移动端改用文字页签，顶栏收为一行——页签在左，
         连接状态（连接页签）/日志暂停（日志页签）在右上角；
         桌面端标题 + 滑块页签仍为一行。 -->
    <div class="flex shrink-0 flex-col gap-2 px-3 pt-3 pb-2 md:flex-row md:items-center">
      <h1 class="hidden shrink-0 text-base font-bold md:block">{{ $t('connections') }}</h1>
      <SegmentedControl v-model="tab" :options="tabOptions" class="hidden md:inline-flex" />
      <div class="flex items-center gap-4 md:hidden" role="tablist">
        <button
          v-for="t in tabOptions"
          :key="t.value"
          type="button"
          role="tab"
          :aria-selected="tab === t.value"
          class="border-b-2 pb-1 text-sm whitespace-nowrap"
          :class="tab === t.value ? 'border-primary text-primary font-medium' : 'border-transparent opacity-60'"
          @click="setTab(t.value)"
        >
          {{ t.label }}
        </button>
        <div class="ml-auto flex items-center gap-2">
          <span v-if="tab === 'connections'" class="text-xs whitespace-nowrap opacity-70">
            {{ connCount }}
          </span>
          <button
            v-if="tab === 'logs'"
            type="button"
            class="btn btn-ghost btn-sm btn-square"
            :title="isPaused ? '继续' : '暂停'"
            @click="isPaused = !isPaused"
          >
            <PlayIcon v-if="isPaused" class="h-4 w-4" />
            <PauseIcon v-else class="h-4 w-4" />
          </button>
        </div>
      </div>
    </div>
    <div class="min-h-0 flex-1">
      <template v-if="tab === 'connections'">
        <div
          class="relative flex size-full flex-col overflow-hidden"
          :style="!isConnectionCard && padding"
        >
          <template v-if="isConnectionCard">
            <ConnectionCardList />
          </template>
          <template v-else>
            <ConnectionCtrl />
            <ConnectionTable />
          </template>
          <ConnectionDetails />
        </div>
      </template>
      <RulesPage v-else-if="tab === 'rules'" />
      <LogsPage v-else-if="tab === 'logs'" />
    </div>
  </div>
</template>

<script setup lang="ts">
import { can } from '@/assembly/backend'
import SegmentedControl from '@/components/common/SegmentedControl.vue'
import ConnectionCardList from '@/components/connections/ConnectionCardList.vue'
import ConnectionDetails from '@/components/connections/ConnectionDetails.vue'
import ConnectionTable from '@/components/connections/ConnectionTable.vue'
import ConnectionCtrl from '@/components/controls/ConnectionCtrl.tsx'
import { usePaddingForViews } from '@/composables/paddingViews'
import { connections, renderConnections } from '@/store/connections'
import { isPaused } from '@/store/logs'
import { isConnectionCard } from '@/store/settings'
import LogsPage from '@/views/LogsPage.vue'
import RulesPage from '@/views/RulesPage.vue'
import { PauseIcon, PlayIcon } from '@heroicons/vue/24/outline'
import { computed, ref, watch } from 'vue'
import { useRoute, useRouter } from 'vue-router'

const { padding } = usePaddingForViews({
  offsetTop: 0,
  offsetBottom: 0,
})

// 页签顺序按 365 日志：路由／连接／日志
type ConnTab = 'rules' | 'connections' | 'logs'
const tabOptions = [
  { value: 'rules', label: '路由' },
  { value: 'connections', label: '连接' },
  { value: 'logs', label: '日志' },
]

// 记住当前页签：?tab= 优先（旧链接 /#/logs、/#/rules 经路由重定向
// 到此，见 router/index.ts），其次 localStorage，最后默认连接。
// 无规则查看能力时规则页签不可用，回落到连接。
const TAB_KEY = 'config/connections-tab'
const route = useRoute()
const router = useRouter()
function isTab(v: unknown): v is ConnTab {
  return v === 'rules' || v === 'connections' || v === 'logs'
}
function setTab(v: string) {
  if (isTab(v)) tab.value = v
}
// v0.1.366 移动端右上角：连接状态（过滤后/总数，同 ConnectionTabs 口径），
// 日志暂停与 LogsCtrl 共用同一 isPaused 状态，两处同步。
const connCount = computed(() => {
  if (renderConnections.value.length !== connections.value.length) {
    return `${renderConnections.value.length} / ${connections.value.length}`
  }
  return `${connections.value.length}`
})
function resolveTab(): ConnTab {
  const q = route.query.tab
  if (isTab(q)) return q === 'rules' && !can('rules') ? 'connections' : q
  try {
    const saved = localStorage.getItem(TAB_KEY)
    if (isTab(saved)) return saved === 'rules' && !can('rules') ? 'connections' : saved
  } catch {}
  return 'connections'
}
const tab = ref<ConnTab>(resolveTab())
watch(tab, (v) => {
  try {
    localStorage.setItem(TAB_KEY, v)
  } catch {}
  if (route.query.tab !== v) {
    router.replace({ query: { ...route.query, tab: v } }).catch(() => {})
  }
})
watch(
  () => route.query.tab,
  () => {
    const t = resolveTab()
    if (t !== tab.value) tab.value = t
  },
)
</script>

<style>
.vjs-tree {
  font-family:
    NotoEmoji,
    Monaco,
    Menlo,
    Consolas,
    Bitstream Vera Sans Mono,
    monospace;
}
.vjs-tree-node.is-highlight,
.vjs-tree-node:hover {
  background-color: var(--color-base-200);
}
</style>
