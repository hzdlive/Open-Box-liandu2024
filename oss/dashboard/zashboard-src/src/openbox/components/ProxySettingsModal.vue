<template>
  <div v-if="show" class="modal modal-open">
    <div class="modal-box max-w-2xl">
      <div class="mb-4 flex items-center justify-between">
        <h3 class="text-lg font-bold">{{ $t('obx.proxySettings') }}</h3>
        <button class="btn btn-ghost btn-sm btn-square" @click="close">✕</button>
      </div>

      <!-- 基础项 -->
      <div class="flex flex-col gap-3">
        <label class="flex items-center justify-between gap-3">
          <span class="text-sm">{{ $t('obx.nodeSort') }}</span>
          <select v-model="sort" class="select select-bordered select-sm" @change="onSortChange">
            <option value="defaultsort">{{ $t('obx.sortDefault') }}</option>
            <option value="latencyasc">{{ $t('obx.sortLatencyAsc') }}</option>
            <option value="latencydesc">{{ $t('obx.sortLatencyDesc') }}</option>
            <option value="nameasc">{{ $t('obx.sortNameAsc') }}</option>
            <option value="namedesc">{{ $t('obx.sortNameDesc') }}</option>
          </select>
        </label>
        <label class="flex items-center justify-between gap-3">
          <span class="text-sm">{{ $t('obx.groupByProvider') }}</span>
          <input
            type="checkbox" class="toggle toggle-primary toggle-sm"
            :checked="groupBy"
            @change="onGroupChange"
          />
        </label>
        <label class="flex items-center justify-between gap-3">
          <span class="text-sm">{{ $t('obx.cardMinWidth') }}</span>
          <span class="flex items-center gap-2">
            <input
              v-model.number="cardWidth" type="number" min="80" max="400"
              class="input input-bordered input-sm w-24"
              @change="onWidthChange"
            />
            <button class="btn btn-ghost btn-sm" @click="onWidthReset">{{ $t('obx.reset') }}</button>
          </span>
        </label>
      </div>

      <div class="divider" />

      <!-- 显示顺序 + 命中顺序（左右对照原版布局） -->
      <div class="grid grid-cols-1 gap-4 sm:grid-cols-2">
        <div>
          <div class="mb-2 text-sm font-semibold">{{ $t('obx.displayOrder') }}</div>
          <div class="flex flex-col gap-1">
            <div
              v-for="(s, i) in orderList" :key="s.name"
              class="flex items-center gap-2 rounded bg-base-200/60 px-2 py-1.5 text-sm"
              :class="{ 'ring-2 ring-primary': dragOver === i }"
              draggable="true"
              @dragstart="dragFrom = i"
              @dragover.prevent="dragOver = i"
              @dragleave="dragOver = -1"
              @drop="onOrderDrop(i)"
              @dragend="dragOver = -1"
            >
              <span class="cursor-move opacity-40">≡</span>
              <span class="text-base leading-none">{{ siteIcon(s.icon, s.name) }}</span>
              <span class="truncate">{{ s.name }}</span>
            </div>
            <div v-if="!orderList.length" class="text-sm opacity-50">{{ $t('obx.noData') }}</div>
          </div>
          <p class="mt-2 text-xs opacity-60">{{ $t('obx.displayOrderHint') }}</p>
        </div>
        <div>
          <div class="mb-2 text-sm font-semibold">{{ $t('obx.hitOrder') }}</div>
          <div class="flex flex-col gap-1">
            <div
              v-if="hasFrontRules"
              class="flex items-center gap-2 rounded bg-base-200/60 px-2 py-1.5 text-sm"
            >
              <span>🚩</span>
              <span class="truncate">{{ $t('obx.frontCustomShunt') }}</span>
            </div>
            <div
              v-for="(s, i) in hitList" :key="s.name"
              class="flex items-center gap-2 rounded bg-base-200/60 px-2 py-1.5 text-sm"
            >
              <span class="w-5 text-right opacity-50">{{ i + 1 }}</span>
              <span class="text-base leading-none">{{ siteIcon(s.icon, s.name) }}</span>
              <span class="truncate">{{ s.name }}</span>
            </div>
            <div v-if="!hitList.length && !hasFrontRules" class="text-sm opacity-50">{{ $t('obx.noData') }}</div>
          </div>
          <p class="mt-2 text-xs opacity-60">{{ $t('obx.hitOrderHint') }}</p>
        </div>
      </div>
    </div>
    <div class="modal-backdrop" @click="close" />
  </div>
</template>

<script setup lang="ts">
// 代理页「策略设置」弹窗（对标原版）：基础三项 + 显示顺序拖拽 + 命中顺序只读。
// 基础三项走 zashboard 原生 store（排序/卡宽/分组开关），本组件只做服务端
// 持久化与 UI；命中顺序为派生展示：前置规则置顶 + 站点集顺序。
import { ref, watch } from 'vue'
import { obxGet } from '../api'
import {
  loadProxySettings,
  saveProxySettings,
  displayOrder,
  PROXY_CARD_MIN_WIDTH_DEFAULT,
} from '../composables/useProxySettings'
import { siteIcon } from '../composables/useSiteIcon'
import { proxySortType, minProxyCardWidth, groupProxiesByProvider } from '@/store/settings'

// "其他"：兜底策略，非站点集表的真实行，原版左右列表都展示（命中排序固定末位）
const FALLBACK_SITE = { name: '其他', icon: 'globe:earth-americas' }

const props = defineProps<{ show: boolean }>()
const emit = defineEmits<{ 'update:show': [boolean] }>()

const sort = ref('latencyasc')
const groupBy = ref(true)
const cardWidth = ref(PROXY_CARD_MIN_WIDTH_DEFAULT)
const orderList = ref<{ name: string; icon: string }[]>([])
const hitList = ref<{ name: string; icon: string }[]>([])
const hasFrontRules = ref(false)
const dragFrom = ref(-1)
const dragOver = ref(-1)

function withFallback(sites: any[]): { name: string; icon: string }[] {
  const list = (sites || [])
    .map((s: any) => ({ name: s.name, icon: s.icon || '' }))
    .filter((s: any) => s.name)
  if (!list.some((s: any) => s.name === FALLBACK_SITE.name)) list.push({ ...FALLBACK_SITE })
  return list
}
// 显示顺序：服务端保存顺序优先，未在保存名单的（新增）按站点集原相对顺序追加
function sortByDisplayOrder(list: { name: string; icon: string }[]): { name: string; icon: string }[] {
  const order = displayOrder.value
  if (!order.length) return list
  const idx = new Map(order.map((n, i) => [n, i]))
  return [...list].sort((a, b) => {
    const ia = idx.get(a.name) ?? Number.MAX_SAFE_INTEGER
    const ib = idx.get(b.name) ?? Number.MAX_SAFE_INTEGER
    if (ia !== ib) return ia - ib
    return list.indexOf(a) - list.indexOf(b)
  })
}

watch(
  () => props.show,
  async (v) => {
    if (!v) return
    await loadProxySettings()
    sort.value = String(proxySortType.value)
    groupBy.value = !!groupProxiesByProvider.value
    cardWidth.value = minProxyCardWidth.value || PROXY_CARD_MIN_WIDTH_DEFAULT
    try {
      const [sites, front] = await Promise.all([
        obxGet<any[]>('/api/sitesets').catch(() => []),
        obxGet<any[]>('/api/front-rules').catch(() => []),
      ])
      const all = withFallback(sites)
      hitList.value = all
      orderList.value = sortByDisplayOrder(all)
      hasFrontRules.value = (front || []).length > 0
    } catch {
      hitList.value = []
      orderList.value = []
      hasFrontRules.value = false
    }
  },
)

async function onSortChange() {
  await saveProxySettings({ sort: sort.value })
}
async function onGroupChange(e: Event) {
  groupBy.value = (e.target as HTMLInputElement).checked
  await saveProxySettings({ group_by_provider: groupBy.value })
}
async function onWidthChange() {
  await saveProxySettings({ card_min_width: cardWidth.value })
  cardWidth.value = minProxyCardWidth.value
}
async function onWidthReset() {
  cardWidth.value = PROXY_CARD_MIN_WIDTH_DEFAULT
  await saveProxySettings({ card_min_width: PROXY_CARD_MIN_WIDTH_DEFAULT })
}
async function onOrderDrop(to: number) {
  const from = dragFrom.value
  dragOver.value = -1
  if (from < 0 || from === to) return
  const list = [...orderList.value]
  const [moved] = list.splice(from, 1)
  list.splice(to, 0, moved)
  orderList.value = list
  await saveProxySettings({ display_order: list.map((s) => s.name) })
  orderList.value = sortByDisplayOrder(orderList.value)
}
function close() {
  emit('update:show', false)
}
</script>
