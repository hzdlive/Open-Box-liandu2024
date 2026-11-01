<template>
  <div class="relative flex size-full flex-col overflow-hidden">
    <!-- v0.1.365：连接、日志、运行规则合并为“连接”页，以页签切换。
         桌面端标题 + 页签合并为一行；移动端页签独占一行。 -->
    <div class="flex shrink-0 flex-col gap-2 px-3 pt-3 pb-2 md:flex-row md:items-center">
      <h1 class="shrink-0 text-base font-bold">{{ $t('connections') }}</h1>
      <SegmentedControl v-model="tab" :options="tabOptions" />
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
import { isConnectionCard } from '@/store/settings'
import LogsPage from '@/views/LogsPage.vue'
import RulesPage from '@/views/RulesPage.vue'
import { ref, watch } from 'vue'
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
