<!-- Open-Box 二开：出站节点组管理（1:1 对标原版 v0.1.331 出站节点页） -->
<template>
  <div>
    <div class="mb-3 flex items-center justify-between">
      <h2 class="text-lg font-bold">{{ $t('obx.groups') }}</h2>
      <div class="flex gap-2">
        <button
          class="btn btn-ghost btn-sm"
          :disabled="busy"
          @click="checkHealth"
        >
          {{ $t('obx.healthCheck') }}
        </button>
        <button
          class="btn btn-primary btn-sm btn-square"
          :title="$t('obx.addGroup')"
          @click="openAdd"
        >
          +
        </button>
      </div>
    </div>

    <div
      v-if="err"
      class="alert alert-error mb-3"
    >
      <span>{{ err }}</span>
    </div>

    <!-- 卡片列表（对标原版：拖拽手柄 / 图标 / 名称+徽标 / 描述 / 启用+编辑+删除） -->
    <div class="flex flex-col gap-2">
      <div
        v-for="(g, gi) in groups"
        :key="g.id"
        class="flex items-center gap-3 rounded-box border border-base-300/30 bg-base-100 px-4 py-3"
        :class="{ 'opacity-60': !g.enabled && !g.builtin, 'ring-2 ring-primary': dragOver === gi }"
        draggable="true"
        @dragstart="onDragStart(gi)"
        @dragover.prevent="onDragOver(gi)"
        @dragleave="dragOver = -1"
        @drop="onDrop(gi)"
        @dragend="dragOver = -1"
      >
        <span
          class="cursor-move opacity-40"
          title="拖拽排序"
        >≡</span>
        <span
          v-if="g.icon"
          class="text-xl"
          :style="g.icon_scale ? `transform: scale(${1 + g.icon_scale * 0.1})` : ''"
        >{{ iconEmoji(g.icon) }}</span>
        <div class="min-w-0 flex-1">
          <div class="flex items-center gap-2">
            <span class="font-medium">{{ g.name }}</span>
            <span
              v-if="g.builtin"
              class="badge badge-ghost badge-xs"
            >{{ $t('obx.builtin') }}</span>
            <span
              v-else
              class="badge badge-ghost badge-xs"
            >{{ typeBadge(g.type) }}</span>
          </div>
          <div class="truncate text-sm opacity-60">
            {{ g.detail || groupDetail(g) }}
          </div>
        </div>
        <div class="flex items-center gap-1">
          <button
            v-if="!g.builtin"
            class="btn btn-ghost btn-square btn-sm"
            :class="g.enabled ? 'text-success' : 'opacity-40'"
            :title="g.enabled ? $t('obx.disable') : $t('obx.enable')"
            @click="toggle(g)"
          >
            ⏻
          </button>
          <button
            class="btn btn-ghost btn-square btn-sm"
            :title="$t('obx.edit')"
            @click="openEdit(g)"
          >
            ✎
          </button>
          <button
            v-if="!g.builtin"
            class="btn btn-ghost btn-square btn-sm hover:text-error"
            :title="$t('obx.delete')"
            @click="remove(g)"
          >
            🗑
          </button>
        </div>
      </div>
    </div>

    <!-- 添加/编辑分组弹窗（1:1 对标原版） -->
    <div
      v-if="dlg"
      class="modal modal-open"
    >
      <div class="modal-box max-w-3xl">
        <div class="mb-4 flex items-center justify-between">
          <h3 class="text-lg font-bold">
            {{ dlg.id ? $t('obx.editGroup') : $t('obx.addGroup') }}
          </h3>
          <button
            class="btn btn-ghost btn-sm btn-square"
            @click="dlg = null"
          >
            ✕
          </button>
        </div>

        <!-- 内置组：只能改名和图标 -->
        <template v-if="dlg.builtin">
          <div class="grid grid-cols-3 items-end gap-3">
            <label class="form-control">
              <span class="label-text mb-1">{{ $t('obx.icon') }}</span>
              <select
                v-model="dlg.icon"
                class="select select-bordered w-full"
              >
                <option value="">{{ $t('obx.none') }}</option>
                <option
                  v-for="ic in ICONS"
                  :key="ic.value"
                  :value="ic.value"
                >
                  {{ ic.label }}
                </option>
              </select>
            </label>
            <div class="form-control">
              <span class="label-text mb-1">{{ $t('obx.iconScale') }}</span>
              <div class="join">
                <button
                  class="btn btn-bordered join-item"
                  @click="dlg.icon_scale = Math.max(-5, (dlg.icon_scale || 0) - 1)"
                >−</button>
                <span class="join-item flex w-10 items-center justify-center border border-base-300">{{ dlg.icon_scale || 0 }}</span>
                <button
                  class="btn btn-bordered join-item"
                  @click="dlg.icon_scale = Math.min(5, (dlg.icon_scale || 0) + 1)"
                >+</button>
                <button
                  class="btn btn-ghost join-item"
                  @click="dlg.icon_scale = 0"
                >{{ $t('obx.reset') }}</button>
              </div>
            </div>
            <label class="form-control">
              <span class="label-text mb-1">{{ $t('obx.groupName') }}</span>
              <input
                v-model="dlg.name"
                class="input input-bordered w-full"
              />
            </label>
          </div>
          <p class="mt-3 text-sm opacity-60">{{ $t('obx.builtinOnlyNameIcon') }}</p>
        </template>

        <!-- 普通组：完整表单 -->
        <template v-else>
          <div class="grid grid-cols-3 items-end gap-3">
            <label class="form-control">
              <span class="label-text mb-1">{{ $t('obx.icon') }}</span>
              <select
                v-model="dlg.icon"
                class="select select-bordered w-full"
              >
                <option value="">{{ $t('obx.none') }}</option>
                <option
                  v-for="ic in ICONS"
                  :key="ic.value"
                  :value="ic.value"
                >
                  {{ ic.label }}
                </option>
              </select>
            </label>
            <div class="form-control">
              <span class="label-text mb-1">{{ $t('obx.iconScale') }}</span>
              <div class="join">
                <button
                  class="btn btn-bordered join-item"
                  @click="dlg.icon_scale = Math.max(-5, (dlg.icon_scale || 0) - 1)"
                >−</button>
                <span class="join-item flex w-10 items-center justify-center border border-base-300">{{ dlg.icon_scale || 0 }}</span>
                <button
                  class="btn btn-bordered join-item"
                  @click="dlg.icon_scale = Math.min(5, (dlg.icon_scale || 0) + 1)"
                >+</button>
                <button
                  class="btn btn-ghost join-item"
                  @click="dlg.icon_scale = 0"
                >{{ $t('obx.reset') }}</button>
              </div>
            </div>
            <label class="form-control">
              <span class="label-text mb-1">{{ $t('obx.groupName') }}</span>
              <input
                v-model="dlg.name"
                class="input input-bordered w-full"
              />
            </label>
          </div>

          <div class="mt-3 grid grid-cols-4 items-end gap-3">
            <label class="form-control">
              <span class="label-text mb-1">{{ $t('obx.groupRule') }}</span>
              <select
                v-model="dlg.type"
                class="select select-bordered w-full"
                @change="onTypeChange"
              >
                <option value="urltest">{{ $t('obx.urltestLong') }}</option>
                <option value="selector">{{ $t('obx.selectorLong') }}</option>
                <option value="failover">{{ $t('obx.failoverLong') }}</option>
                <option value="smart">{{ $t('obx.smartLong') }}</option>
                <option value="loadbalance">{{ $t('obx.loadbalanceLong') }}</option>
              </select>
            </label>
            <label class="form-control">
              <span class="label-text mb-1">{{ $t('obx.intervalS') }}</span>
              <div class="flex items-center gap-1">
                <input
                  v-model.number="dlg.interval_s"
                  type="number"
                  min="30"
                  class="input input-bordered w-full"
                />
                <span class="text-sm opacity-60">{{ $t('obx.seconds') }}</span>
              </div>
            </label>
            <label class="form-control">
              <span class="label-text mb-1">{{ dlg.type === 'failover' ? $t('obx.toleranceMsLane') : $t('obx.toleranceMs') }}</span>
              <div class="flex items-center gap-1">
                <input
                  v-model.number="dlg.tolerance_ms"
                  type="number"
                  min="0"
                  class="input input-bordered w-full"
                />
                <span class="text-sm opacity-60">{{ $t('obx.millis') }}</span>
              </div>
            </label>
            <div />
            <label class="form-control col-span-3">
              <span class="label-text mb-1">{{ $t('obx.testUrl') }}</span>
              <input
                v-model="dlg.test_url"
                class="input input-bordered w-full"
                :placeholder="$t('obx.testUrlPh')"
              />
            </label>
            <label class="form-control">
              <span class="label-text mb-1">{{ $t('obx.expectedStatus') }}</span>
              <input
                v-model="dlg.expected_status"
                class="input input-bordered w-full"
                :placeholder="$t('obx.expectedStatusPh')"
              />
            </label>
          </div>

          <!-- 动态组 / 静态组 切换（故障转移不显示，直接用页签） -->
          <div
            v-if="dlg.type !== 'failover'"
            class="mt-4 flex gap-2"
          >
            <button
              type="button"
              class="btn btn-sm"
              :class="dlg.mode === 'dynamic' ? 'btn-success' : 'btn-ghost'"
              @click="dlg.mode = 'dynamic'"
            >
              {{ $t('obx.dynamicGroup') }}
            </button>
            <button
              type="button"
              class="btn btn-sm"
              :class="dlg.mode === 'static' ? 'btn-success' : 'btn-ghost'"
              @click="dlg.mode = 'static'"
            >
              {{ $t('obx.staticGroup') }}
            </button>
          </div>

          <!-- 动态组：关键词 -->
          <div
            v-if="dlg.type !== 'failover' && dlg.mode === 'dynamic'"
            class="mt-3"
          >
            <label class="form-control">
              <span class="label-text mb-1">{{ $t('obx.keywords') }}</span>
              <input
                v-model="dlg.keywords"
                class="input input-bordered w-full"
                :placeholder="$t('obx.groupKeywordsPh')"
                :disabled="dlg.type === 'failover'"
              />
            </label>
            <p class="mt-1 text-xs opacity-60">{{ $t('obx.groupKeywordsHint') }}</p>
            <div class="mt-2 rounded-box border border-base-300/30">
              <div class="border-b border-base-300/30 px-3 py-2 text-sm">
                {{ $t('obx.hitsNow', { n: hitCount }) }}
              </div>
              <div class="max-h-32 overflow-y-auto px-3 py-2 text-sm opacity-60">
                <template v-if="hitTags.length">
                  <div
                    v-for="t in hitTags"
                    :key="t"
                  >
                    {{ t }}
                  </div>
                </template>
                <div
                  v-else
                  class="py-2 text-center"
                >
                  {{ $t('obx.noHits') }}
                </div>
              </div>
            </div>
          </div>

          <!-- 静态组：双栏选择器 -->
          <div
            v-else
            class="mt-3"
          >
            <!-- 故障转移：主用/备用页签（1:1 对标原版） -->
            <div
              v-if="dlg.type === 'failover'"
              class="mb-3"
            >
              <p class="mb-2 text-xs opacity-60">{{ $t('obx.lanesHint2') }}</p>
              <div class="mb-2 flex items-center gap-2">
                <button
                  v-for="(ln, idx) in dlg.lanes"
                  :key="idx"
                  class="btn btn-sm"
                  :class="activeLane === idx ? 'btn-success' : 'btn-ghost'"
                  @click="activeLane = Number(idx)"
                >
                  {{ laneTabName(ln, Number(idx)) }} · {{ (ln.members || []).length }}
                </button>
                <button
                  class="btn btn-ghost btn-sm btn-square"
                  :title="$t('obx.addLane')"
                  @click="addLane"
                >
                  +
                </button>
              </div>
              <div
                v-if="dlg.lanes[activeLane]"
                class="flex items-end gap-2"
              >
                <label class="form-control">
                  <span class="label-text mb-1 text-xs">{{ $t('obx.icon') }}</span>
                  <select
                    v-model="dlg.lanes[activeLane].icon"
                    class="select select-bordered select-sm w-28"
                  >
                    <option value="">{{ $t('obx.none') }}</option>
                    <option
                      v-for="ic in ICONS"
                      :key="ic.value"
                      :value="ic.value"
                    >
                      {{ ic.label }}
                    </option>
                  </select>
                </label>
                <label class="form-control flex-1">
                  <span class="label-text mb-1 text-xs">{{ $t('obx.laneNameOpt') }}</span>
                  <input
                    v-model="dlg.lanes[activeLane].name"
                    class="input input-bordered input-sm w-full"
                    :placeholder="activeLane === 0 ? '主用' : `备用 ${activeLane}`"
                  />
                </label>
                <label class="form-control">
                  <span class="label-text mb-1 text-xs">{{ $t('obx.laneMode') }}</span>
                  <select
                    v-model="dlg.lanes[activeLane].mode"
                    class="select select-bordered select-sm"
                  >
                    <option value="auto">{{ $t('obx.laneModeAuto') }}</option>
                    <option value="manual">{{ $t('obx.laneModeManual') }}</option>
                  </select>
                </label>
                <button
                  v-if="dlg.lanes.length > 1"
                  class="btn btn-ghost btn-sm text-error"
                  :title="$t('obx.delete')"
                  @click="removeLane(activeLane)"
                >
                  🗑
                </button>
              </div>
            </div>
            <div class="grid grid-cols-[1fr_auto_1fr] gap-3">
              <div class="rounded-box border border-base-300/30">
                <div class="border-b border-base-300/30 p-2">
                  <div class="mb-2 flex items-center justify-between gap-2">
                    <span class="text-sm font-medium">{{ $t('obx.available', { n: availList.length }) }}</span>
                    <div class="flex items-center gap-1">
                      <select v-model="availSubFilter" class="select select-bordered select-xs w-28">
                        <option value="">全部</option>
                        <option v-for="o in subOptions" :key="o.id" :value="o.id">{{ o.name }}</option>
                      </select>
                      <input
                        v-model="availFilter"
                        class="input input-bordered input-xs w-28"
                        :placeholder="$t('obx.filterByName')"
                      />
                    </div>
                  </div>
                  <div class="flex items-center gap-1">
                    <button
                      class="btn btn-ghost btn-xs"
                      @click="selectAllAvail"
                    >
                      {{ $t('obx.selectAll') }}
                    </button>
                    <button
                      class="btn btn-ghost btn-xs"
                      @click="invertAvail"
                    >
                      {{ $t('obx.invert') }}
                    </button>
                    <button
                      class="btn btn-ghost btn-xs"
                      @click="clearAvail"
                    >
                      {{ $t('obx.clearSel') }}
                    </button>
                  </div>
                </div>
                <div class="max-h-48 overflow-y-auto p-1">
                  <label
                    v-for="t in availList"
                    :key="t.tag"
                    class="flex cursor-pointer items-center gap-2 rounded px-2 py-1 hover:bg-base-200"
                  >
                    <input
                      v-model="availChecked"
                      type="checkbox"
                      :value="t.tag"
                      class="checkbox checkbox-sm"
                    />
                    <span class="flex-1 truncate text-sm">{{ t.tag }}</span>
                    <span class="badge badge-ghost badge-xs">{{ t.kind }}</span>
                  </label>
                </div>
              </div>
              <div class="flex flex-col justify-center gap-2">
                <button
                  class="btn btn-circle btn-sm"
                  :disabled="!availChecked.length"
                  @click="moveToSelected"
                >
                  →
                </button>
                <button
                  class="btn btn-circle btn-sm"
                  :disabled="!selChecked.length"
                  @click="moveToAvail"
                >
                  ←
                </button>
              </div>
              <div class="rounded-box border border-base-300/30">
                <div class="border-b border-base-300/30 p-2">
                  <div class="mb-2 flex items-center justify-between">
                    <span class="text-sm font-medium">{{ $t('obx.selectedN', { n: curMembers.length }) }}</span>
                    <input
                      v-model="selFilter"
                      class="input input-bordered input-xs w-32"
                      :placeholder="$t('obx.filterByName')"
                    />
                  </div>
                  <div class="flex items-center gap-1">
                    <button
                      class="btn btn-ghost btn-xs"
                      @click="selectAllSel"
                    >
                      {{ $t('obx.selectAll') }}
                    </button>
                    <button
                      class="btn btn-ghost btn-xs"
                      @click="invertSel"
                    >
                      {{ $t('obx.invert') }}
                    </button>
                    <button
                      class="btn btn-ghost btn-xs"
                      @click="clearSel"
                    >
                      {{ $t('obx.clearSel') }}
                    </button>
                  </div>
                </div>
                <div class="max-h-48 overflow-y-auto p-1">
                  <div
                    v-if="!selList.length"
                    class="p-4 text-center text-sm opacity-60"
                  >
                    {{ $t('obx.pickHint') }}
                  </div>
                  <label
                    v-for="t in selList"
                    :key="t"
                    class="flex cursor-pointer items-center gap-2 rounded px-2 py-1 hover:bg-base-200"
                  >
                    <input
                      v-model="selChecked"
                      type="checkbox"
                      :value="t"
                      class="checkbox checkbox-sm"
                    />
                    <span class="flex-1 truncate text-sm">{{ t }}</span>
                  </label>
                </div>
              </div>
            </div>
          </div>
        </template>

        <p
          v-if="dlgErr"
          class="mt-3 text-sm text-error"
        >
          {{ dlgErr }}
        </p>
        <div class="modal-action">
          <button
            class="btn btn-ghost"
            @click="dlg = null"
          >
            {{ $t('obx.cancel') }}
          </button>
          <button
            class="btn btn-success"
            :disabled="dlgBusy"
            @click="save"
          >
            {{ $t('obx.save') }}
          </button>
        </div>
      </div>
    </div>
  </div>
</template>

<script setup lang="ts">
import { ObxApiError, obxDel, obxGet, obxPost, obxPut } from '@/openbox/api'
import { computed, onMounted, ref } from 'vue'
import { useI18n } from 'vue-i18n'

const { t } = useI18n()

// 图标选项（对标原版图标选择器）
const ICONS = [
  { value: 'dart', label: '🎯 靶心' },
  { value: 'globe', label: '🌍 地球·彩色(亚洲)' },
  { value: 'globe-blue', label: '🌐 地球·蓝色' },
  { value: 'bolt', label: '⚡ 闪电' },
  { value: 'rocket', label: '🚀 火箭' },
  { value: 'shield', label: '🛡️ 盾牌' },
  { value: 'star', label: '⭐ 星星' },
  { value: 'fire', label: '🔥 火焰' },
  { value: 'game', label: '🎮 游戏' },
  { value: 'video', label: '🎬 视频' },
  { value: 'music', label: '🎵 音乐' },
  { value: 'cross', label: '❌ 拒绝' },
]
function iconEmoji(v: string) {
  return ICONS.find((i) => i.value === v)?.label.split(' ')[0] || '📦'
}

type Group = {
  id: number
  name: string
  type: string
  enabled: boolean
  member_count: number
  members: string[]
  dynamic_keywords: string[]
  interval_s: number
  tolerance_ms: number
  idle_timeout: string
  expected_status: string
  test_url: string
  icon: string
  icon_scale: number
  lanes: { name: string; icon: string; mode: string; members: string[] }[]
  builtin?: boolean
  detail?: string
}

const groups = ref<Group[]>([])
const err = ref('')
const busy = ref(false)
const dlg = ref<any>(null)
const dlgErr = ref('')
const dlgBusy = ref(false)

// 双栏选择器状态
const allTags = ref<{ tag: string; kind: string; sub?: string }[]>([])
const availFilter = ref('')
const availSubFilter = ref('')  // 订阅下拉筛选（1:1 原版）
const subOptions = ref<{ id: string; name: string }[]>([])
const selFilter = ref('')
const availChecked = ref<string[]>([])
const selChecked = ref<string[]>([])
const activeLane = ref(0)

// 当前编辑的成员列表：failover 时为当前页签的 members，否则为 dlg.members
const curMembers = computed<string[]>({
  get() {
    if (!dlg.value) return []
    if (dlg.value.type === 'failover') {
      const ln = dlg.value.lanes?.[activeLane.value]
      return (ln?.members || []) as string[]
    }
    return (dlg.value.members || []) as string[]
  },
  set(v: string[]) {
    if (!dlg.value) return
    if (dlg.value.type === 'failover') {
      const ln = dlg.value.lanes?.[activeLane.value]
      if (ln) ln.members = v
    } else {
      dlg.value.members = v
    }
  },
})
function laneTabName(ln: any, i: number) {
  return (ln?.name || '').trim() || (i === 0 ? '主用' : `备用 ${i}`)
}
function addLane() {
  dlg.value.lanes.push({ name: '', icon: '', mode: 'auto', members: [] })
  activeLane.value = dlg.value.lanes.length - 1
}
function removeLane(i: number) {
  dlg.value.lanes.splice(i, 1)
  if (activeLane.value >= dlg.value.lanes.length)
    activeLane.value = Math.max(0, dlg.value.lanes.length - 1)
}

function typeBadge(ty: string) {
  return {
    urltest: t('obx.urltestLong'),
    selector: t('obx.selectorLong'),
    failover: t('obx.failoverLong'),
  }[ty] || ty
}
function groupDetail(g: Group) {
  if (g.type === 'urltest')
    return `${t('obx.dynamicGroup')} · ${t('obx.memberCount', { n: g.member_count })} · ${t('obx.intervalS')}${g.interval_s || 300}s · ${t('obx.toleranceMs')}${g.tolerance_ms || 100}ms`
  if (g.type === 'failover')
    return `${t('obx.failoverLong')} · ${t('obx.memberCount', { n: g.member_count })}`
  return `${t('obx.dynamicGroup')} · ${t('obx.memberCount', { n: g.member_count })}`
}

// 动态关键词命中预览
const hitTags = computed(() => {
  if (!dlg.value || dlg.value.mode !== 'dynamic') return []
  const kws = (dlg.value.keywords || '').split(',').map((s: string) => s.trim().toLowerCase()).filter(Boolean)
  if (!kws.length) return allTags.value.map((x) => x.tag)
  return allTags.value.filter((x) => kws.some((k: string) => x.tag.toLowerCase().includes(k))).map((x) => x.tag)
})
const hitCount = computed(() => hitTags.value.length)

// 可选列表 = 全部标签 - 已选（支持按订阅筛选，1:1 原版）
const availList = computed(() => {
  const sel = new Set(curMembers.value)
  const f = availFilter.value.trim().toLowerCase()
  const sub = availSubFilter.value
  return allTags.value.filter((x) => {
    if (sel.has(x.tag)) return false
    if (f && !x.tag.toLowerCase().includes(f)) return false
    if (sub) {
      // 链式代理归为一类；否则按订阅名匹配
      if (sub === '__chain__') return x.kind === 'chain'
      if (x.kind === 'chain') return false
      return (x.sub || '') === sub
    }
    return true
  })
})
const selList = computed<string[]>(() => {
  const f = selFilter.value.trim().toLowerCase()
  return curMembers.value.filter((m: string) => !f || m.toLowerCase().includes(f))
})

function selectAllAvail() { availChecked.value = availList.value.map((x) => x.tag) }
function invertAvail() {
  const all = new Set(availList.value.map((x) => x.tag))
  availChecked.value = [...all].filter((x) => !availChecked.value.includes(x))
}
function clearAvail() { availChecked.value = [] }
function selectAllSel() { selChecked.value = [...selList.value] }
function invertSel() {
  const all = new Set(selList.value)
  selChecked.value = [...all].filter((x) => !selChecked.value.includes(x))
}
function clearSel() { selChecked.value = [] }
function moveToSelected() {
  const sel = new Set(curMembers.value)
  availChecked.value.forEach((x) => sel.add(x))
  curMembers.value = [...sel]
  availChecked.value = []
}
function moveToAvail() {
  const rm = new Set(selChecked.value)
  curMembers.value = curMembers.value.filter((x: string) => !rm.has(x))
  selChecked.value = []
}

async function load() {
  err.value = ''
  try {
    groups.value = await obxGet<Group[]>('/api/groups')
  } catch (e) {
    err.value = e instanceof ObxApiError ? e.message : '加载失败'
  }
}

async function loadTags() {
  try {
    const [nodes, chains, subs] = await Promise.all([
      obxGet<any[]>('/api/nodes'),
      obxGet<any[]>('/api/chains').catch(() => []),
      obxGet<any[]>('/api/subscriptions').catch(() => []),
    ])
    // sub_id -> 订阅名映射
    const subMap = new Map<number, string>()
    const opts: { id: string; name: string }[] = []
    if (Array.isArray(subs)) {
      for (const s of subs) {
        if (s.id != null) {
          subMap.set(s.id, s.name || s.url || `#${s.id}`)
          opts.push({ id: String(s.name || s.url || `#${s.id}`), name: s.name || s.url || `#${s.id}` })
        }
      }
    }
    // 去重并排序
    const seen = new Set<string>()
    subOptions.value = opts.filter((o) => {
      if (seen.has(o.id)) return false
      seen.add(o.id)
      return true
    }).sort((a, b) => a.name.localeCompare(b.name, 'zh-CN'))
    // 链式代理单独一类（对标原版下拉中的"链式代理"）
    if (Array.isArray(chains) && chains.length) {
      subOptions.value.push({ id: '__chain__', name: '链式代理' })
    }
    allTags.value = [
      ...nodes.map((n: any) => ({
        tag: n.tag || n.name,
        kind: t('obx.node'),
        sub: n.sub_id != null ? (subMap.get(n.sub_id) || '') : '',
      })),
      ...(Array.isArray(chains) ? chains.map((c: any) => ({ tag: c.name, kind: t('obx.chain') })) : []),
      { tag: '直连', kind: t('obx.group') },
      { tag: '拒绝', kind: t('obx.group') },
    ]
  } catch { allTags.value = [] }
}

async function checkHealth() {
  busy.value = true
  try {
    await obxPost('/api/health/check', {})
    await load()
  } catch (e) {
    err.value = e instanceof ObxApiError ? e.message : '检查失败'
  } finally {
    busy.value = false
  }
}

function baseDlg() {
  return {
    id: null, builtin: false, name: '', type: 'urltest',
    icon: '', icon_scale: 0,
    interval_s: 300, tolerance_ms: 100, idle_timeout: '12h',
    expected_status: '', test_url: '',
    mode: 'dynamic', keywords: '', members: [] as string[],
    lanes: [] as { name: string; icon: string; mode: string; members: string[] }[],
  }
}
function openAdd() {
  dlgErr.value = ''
  availFilter.value = ''; selFilter.value = ''
  availChecked.value = []; selChecked.value = []
  activeLane.value = 0
  dlg.value = baseDlg()
  loadTags()
}
// 切换到故障转移时自动创建主用页签
function onTypeChange() {
  if (dlg.value?.type === 'failover' && !dlg.value.lanes.length) {
    dlg.value.lanes.push({ name: '', icon: '', mode: 'auto', members: [] })
    activeLane.value = 0
  }
}
function openEdit(g: Group) {
  dlgErr.value = ''
  availFilter.value = ''; selFilter.value = ''
  availChecked.value = []; selChecked.value = []
  activeLane.value = 0
  const isDynamic = !!(g.dynamic_keywords?.length) || (g.members || []).some((m) => m === '*nodes*' || m === '*all*')
  dlg.value = {
    ...baseDlg(),
    id: g.id, builtin: !!g.builtin, name: g.name, type: g.type,
    icon: g.icon || '', icon_scale: g.icon_scale || 0,
    interval_s: g.interval_s || 300, tolerance_ms: g.tolerance_ms || 100,
    idle_timeout: g.idle_timeout || '12h',
    expected_status: g.expected_status || '', test_url: g.test_url || '',
    mode: isDynamic ? 'dynamic' : 'static',
    keywords: (g.dynamic_keywords || []).join(', '),
    members: (g.members || []).filter((m) => m !== '*nodes*' && m !== '*all*'),
    lanes: (g.lanes || []).map((ln: any) => ({
      name: ln.name || '', icon: ln.icon || '',
      mode: ln.mode || 'auto', members: [...(ln.members || [])],
    })),
  }
  loadTags()
}

async function save() {
  if (!dlg.value) return
  const d = dlg.value
  if (!d.name.trim()) { dlgErr.value = t('obx.nameRequired'); return }
  dlgBusy.value = true
  dlgErr.value = ''
  try {
    if (d.builtin) {
      // 内置组只能改名和图标
      await obxPut(`/api/groups/${d.id}`, { name: d.name.trim(), icon: d.icon, icon_scale: d.icon_scale })
    } else {
      const lanes = (d.lanes || []).map((ln: any) => ({
        name: (ln.name || '').trim(), icon: ln.icon || '',
        mode: ln.mode || 'auto', members: ln.members || [],
      }))
      const body: any = {
        name: d.name.trim(), type: d.type,
        icon: d.icon, icon_scale: d.icon_scale,
        interval_s: d.interval_s, tolerance_ms: d.tolerance_ms,
        idle_timeout: d.idle_timeout,
        expected_status: d.expected_status, test_url: d.test_url,
        lanes,
      }
      if (d.type === 'failover') {
        // 故障转移：成员全在页签里，顶层 members/dynamic_keywords 为空
        body.members = []
        body.dynamic_keywords = []
      } else if (d.mode === 'dynamic') {
        const kws = d.keywords.split(',').map((s: string) => s.trim()).filter(Boolean)
        body.dynamic_keywords = kws
        // 动态组无关键词时用 *all* 标记，避免回显时被误判为静态组
        body.members = kws.length ? [] : ['*all*']
      } else {
        body.members = d.members
        body.dynamic_keywords = []
      }
      if (d.id) await obxPut(`/api/groups/${d.id}`, body)
      else await obxPost('/api/groups', body)
    }
    dlg.value = null
    await load()
  } catch (e) {
    dlgErr.value = e instanceof ObxApiError ? e.message : t('obx.saveFailed')
  } finally {
    dlgBusy.value = false
  }
}

async function toggle(g: Group) {
  try { await obxPut(`/api/groups/${g.id}`, { enabled: !g.enabled }); await load() }
  catch (e) { err.value = e instanceof ObxApiError ? e.message : '操作失败' }
}

// 拖拽排序（1:1 对标原版；内置组也可拖动）
const dragFrom = ref(-1)
const dragOver = ref(-1)
function onDragStart(i: number) {
  dragFrom.value = i
}
function onDragOver(i: number) {
  dragOver.value = i
}
async function onDrop(i: number) {
  const from = dragFrom.value
  dragFrom.value = -1
  dragOver.value = -1
  if (from < 0 || from === i) return
  const list = [...groups.value]
  const [moved] = list.splice(from, 1)
  list.splice(i, 0, moved)
  groups.value = list
  // 完整顺序（含内置组 id）发给后端
  const ids = list.map((g) => g.id)
  try {
    await obxPost('/api/groups/reorder', { ids })
  } catch (e) {
    err.value = e instanceof ObxApiError ? e.message : '排序失败'
    await load()
  }
}
async function remove(g: Group) {
  if (!confirm(t('obx.delGroupConfirm', { name: g.name }))) return
  try { await obxDel(`/api/groups/${g.id}`); await load() }
  catch (e) { err.value = e instanceof ObxApiError ? e.message : '删除失败' }
}

onMounted(load)
</script>
