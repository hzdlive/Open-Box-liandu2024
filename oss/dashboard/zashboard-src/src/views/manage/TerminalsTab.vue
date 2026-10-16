<!-- Open-Box 二开：终端分流（1:1 对标原版添加/编辑终端规则模态框） -->
<template>
  <div>
    <div class="mb-3 flex items-center justify-between">
      <h2 class="text-lg font-bold">{{ $t('obx.terminals') }}</h2>
      <button
        class="btn btn-primary btn-sm"
        @click="openAdd()"
      >
        + {{ $t('obx.addTerminalRule') }}
      </button>
    </div>

    <div
      v-if="err"
      class="alert alert-error mb-3"
    >
      <span>{{ err }}</span>
    </div>

    <!-- 规则列表 -->
    <div class="flex flex-col gap-2">
      <div
        v-for="r in rules"
        :key="r.id"
        class="flex items-center gap-3 rounded-box border border-base-300/30 bg-base-100 p-3"
        :class="{ 'opacity-60': !r.enabled }"
      >
        <div class="flex-1">
          <div class="font-medium">{{ r.name || $t('obx.unnamed') }}</div>
          <div class="text-xs opacity-60">
            {{ r.match_by === 'mac' ? $t('obx.byMac') : $t('obx.byIp') }} ·
            {{ r.targets.length }}{{ $t('obx.terminalsCount') }} ·
            {{ policyLabel(r.policy) }}
            <span v-if="r.policy === 'proxy' && r.outbound">→ {{ r.outbound }}</span>
          </div>
        </div>
        <button
          class="btn btn-ghost btn-sm btn-square"
          :title="r.enabled ? $t('obx.disable') : $t('obx.enable')"
          @click="toggleEnabled(r)"
        >
          <span v-if="r.enabled">⏸</span>
          <span v-else>▶</span>
        </button>
        <button
          class="btn btn-ghost btn-sm"
          @click="openEdit(r)"
        >
          {{ $t('obx.edit') }}
        </button>
        <button
          class="btn btn-ghost btn-sm text-error"
          @click="remove(r)"
        >
          {{ $t('obx.delete') }}
        </button>
      </div>
      <div
        v-if="!rules.length"
        class="rounded-box border border-base-300/30 bg-base-100 p-6 text-center opacity-60"
      >
        {{ $t('obx.noTerminalRules') }}
      </div>
    </div>

    <!-- 添加/编辑模态框 -->
    <div
      v-if="dlg"
      class="modal modal-open"
    >
      <div class="modal-box max-w-2xl">
        <div class="mb-4 flex items-center justify-between">
          <h3 class="text-lg font-bold">
            {{ dlg.id ? $t('obx.editTerminalRule') : $t('obx.addTerminalRule') }}
          </h3>
          <button
            class="btn btn-ghost btn-sm btn-square"
            @click="dlg = null"
          >
            ✕
          </button>
        </div>

        <!-- 名称 -->
        <div class="mb-4">
          <label class="mb-1 block text-sm font-medium">{{ $t('obx.name') }}</label>
          <input
            v-model="dlg.name"
            class="input input-bordered w-full"
            :placeholder="$t('obx.terminalNamePh')"
          />
        </div>

        <!-- 终端匹配方式 -->
        <div class="mb-4">
          <div class="mb-2 flex items-center justify-between">
            <label class="text-sm font-medium">{{ $t('obx.terminals') }}</label>
            <div class="flex gap-1 rounded-full bg-base-200 p-1">
              <button
                type="button"
                class="btn btn-xs rounded-full"
                :class="dlg.match_by === 'ip' ? 'btn-success' : 'btn-ghost'"
                @click="dlg.match_by = 'ip'"
              >
                {{ $t('obx.byIp') }}
              </button>
              <button
                type="button"
                class="btn btn-xs rounded-full"
                :class="dlg.match_by === 'mac' ? 'btn-success' : 'btn-ghost'"
                @click="dlg.match_by = 'mac'"
              >
                {{ $t('obx.byMac') }}
              </button>
            </div>
          </div>
          <textarea
            v-model="dlg.targetsText"
            class="textarea textarea-bordered w-full font-mono text-sm"
            rows="4"
            :placeholder="dlg.match_by === 'ip' ? $t('obx.terminalIpPh') : $t('obx.terminalMacPh')"
          ></textarea>
          <p class="mt-1 text-xs opacity-60">
            {{ dlg.match_by === 'ip' ? $t('obx.terminalIpDesc') : $t('obx.terminalMacDesc') }}
          </p>
          <!-- 从已知终端添加 -->
          <div class="mt-2 flex items-center gap-2">
            <span class="text-xs opacity-60">{{ $t('obx.addFromKnown') }}</span>
            <select
              class="select select-bordered select-sm flex-1"
              @change="addKnown($event)"
            >
              <option value="">{{ $t('obx.selectFromDhcp') }}</option>
              <option
                v-for="c in candidates"
                :key="c.ident"
                :value="c.ident"
              >
                {{ c.name || c.ident }} ({{ c.ident }})
              </option>
            </select>
          </div>
        </div>

        <!-- 这些终端 -->
        <div class="mb-4">
          <label class="mb-2 block text-sm font-medium">{{ $t('obx.theseTerminals') }}</label>
          <div class="flex flex-col gap-3">
            <label class="flex cursor-pointer items-start gap-3">
              <input
                v-model="dlg.policy"
                type="radio"
                value="proxy"
                class="radio radio-primary mt-1"
              />
              <span>
                <span class="font-medium">{{ $t('obx.polProxyFull') }}</span>
                <span class="block text-xs opacity-60">{{ $t('obx.polProxyDesc') }}</span>
              </span>
            </label>
            <label class="flex cursor-pointer items-start gap-3">
              <input
                v-model="dlg.policy"
                type="radio"
                value="direct"
                class="radio radio-primary mt-1"
              />
              <span>
                <span class="font-medium">{{ $t('obx.polDirectFull') }}</span>
                <span class="block text-xs opacity-60">{{ $t('obx.polDirectDesc') }}</span>
              </span>
            </label>
            <label class="flex cursor-pointer items-start gap-3">
              <input
                v-model="dlg.policy"
                type="radio"
                value="whitelist"
                class="radio radio-primary mt-1"
              />
              <span>
                <span class="font-medium">{{ $t('obx.polWhitelistFull') }}</span>
                <span class="block text-xs opacity-60">{{ $t('obx.polWhitelistDesc') }}</span>
              </span>
            </label>
          </div>
        </div>

        <!-- 出站（仅 proxy 时显示） -->
        <div
          v-if="dlg.policy === 'proxy'"
          class="mb-4"
        >
          <label class="mb-1 block text-sm font-medium">{{ $t('obx.outbound') }}</label>
          <button
            type="button"
            class="input input-bordered relative w-full pr-8 text-left"
            @click="openObSel()"
          >
            <span class="block truncate">{{ dlg.outbound || $t('obx.selectOutbound') }}</span>
            <span class="pointer-events-none absolute right-2 top-1/2 -translate-y-1/2 opacity-60">▾</span>
          </button>
          <p class="mt-1 text-xs opacity-60">{{ $t('obx.terminalOutboundDesc') }}</p>
        </div>

        <div
          v-if="dlgErr"
          class="alert alert-error mb-3"
        >
          <span>{{ dlgErr }}</span>
        </div>

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
            @click="save()"
          >
            {{ $t('obx.save') }}
          </button>
        </div>
      </div>
    </div>

    <!-- 出口选择器（复用节点/节点组双页签） -->
    <div
      v-if="obSel.show"
      class="modal modal-open"
    >
      <div class="modal-box max-w-lg">
        <div class="mb-3 flex items-center justify-between">
          <h3 class="text-lg font-bold">{{ $t('obx.selectOutbound') }}</h3>
          <button
            class="btn btn-ghost btn-sm btn-square"
            @click="obSel.show = false"
          >
            ✕
          </button>
        </div>
        <div class="mb-3 flex gap-2">
          <button
            type="button"
            class="btn btn-sm"
            :class="obSel.tab === 'nodes' ? 'btn-success' : 'btn-ghost'"
            @click="obSel.tab = 'nodes'; obSel.search = ''"
          >
            {{ $t('obx.nodes') }} ({{ obSel.nodes.length }})
          </button>
          <button
            type="button"
            class="btn btn-sm"
            :class="obSel.tab === 'groups' ? 'btn-success' : 'btn-ghost'"
            @click="obSel.tab = 'groups'; obSel.search = ''"
          >
            {{ $t('obx.nodeGroups') }} ({{ obSel.groups.length }})
          </button>
          <div class="relative flex-1">
            <input
              v-model="obSel.search"
              class="input input-bordered input-sm w-full pr-8"
              :placeholder="$t('obx.search')"
            />
            <button
              v-if="obSel.search"
              class="btn btn-ghost btn-xs absolute right-1 top-1/2 -translate-y-1/2"
              @click="obSel.search = ''"
            >
              ✕
            </button>
          </div>
        </div>
        <div
          v-if="obSel.tab === 'nodes'"
          class="max-h-96 overflow-y-auto"
        >
          <div class="mb-1 px-2 text-xs opacity-60">{{ $t('obx.builtin') }}</div>
          <button
            type="button"
            class="flex w-full items-center justify-between px-3 py-2 text-left hover:bg-base-200"
            @click="selectOb('direct')"
          >
            <span>{{ $t('obx.direct') }}</span>
          </button>
          <button
            type="button"
            class="flex w-full items-center justify-between px-3 py-2 text-left hover:bg-base-200"
            @click="selectOb('reject')"
          >
            <span>{{ $t('obx.reject') }}</span>
          </button>
          <div class="mb-1 mt-2 px-2 text-xs opacity-60">{{ $t('obx.nodes') }}</div>
          <button
            v-for="n in filteredObNodes"
            :key="n.id || n.tag"
            type="button"
            class="flex w-full items-center justify-between px-3 py-2 text-left hover:bg-base-200"
            @click="selectOb(n.tag || n.name)"
          >
            <span class="truncate">{{ n.name || n.tag }}</span>
            <span
              v-if="obLatency(n.tag || n.name)"
              class="text-sm"
              :class="Number(obLatency(n.tag || n.name)) < 300 ? 'text-success' : Number(obLatency(n.tag || n.name)) < 800 ? 'text-warning' : 'text-error'"
            >
              {{ obLatency(n.tag || n.name) }}
            </span>
          </button>
        </div>
        <div
          v-else
          class="max-h-96 overflow-y-auto"
        >
          <button
            v-for="g in filteredObGroups"
            :key="g.id"
            type="button"
            class="flex w-full items-center justify-between px-3 py-2 text-left hover:bg-base-200"
            @click="selectOb(g.name)"
          >
            <span class="truncate">{{ g.name }}</span>
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

type TRule = {
  id: number; name: string; match_by: string; targets: string[]
  policy: string; outbound: string; enabled: boolean; position: number
}

const rules = ref<TRule[]>([])
const candidates = ref<{ ident: string; name: string }[]>([])
const err = ref('')

const dlg = ref<null | {
  id: number | null; name: string; match_by: string; targetsText: string
  policy: string; outbound: string
}>(null)
const dlgErr = ref('')
const dlgBusy = ref(false)

// 出口选择器
const obSel = ref({
  show: false,
  tab: 'nodes' as 'nodes' | 'groups',
  search: '',
  nodes: [] as any[],
  groups: [] as any[],
  health: {} as Record<string, number>,
  loading: false,
})

function policyLabel(p: string) {
  return { proxy: t('obx.polProxyFull'), direct: t('obx.polDirectFull'), whitelist: t('obx.polWhitelistFull') }[p] || p
}

async function load() {
  err.value = ''
  try {
    rules.value = await obxGet<TRule[]>('/api/terminal-rules')
    const c = await obxGet<{ candidates: { ident: string; name: string }[] }>('/api/terminal-candidates').catch(() => ({ candidates: [] }))
    candidates.value = c.candidates || []
  } catch (e) { err.value = e instanceof ObxApiError ? e.message : '加载失败' }
}

function openAdd() {
  dlgErr.value = ''
  dlg.value = { id: null, name: '', match_by: 'ip', targetsText: '', policy: 'proxy', outbound: '' }
}

function openEdit(r: TRule) {
  dlgErr.value = ''
  dlg.value = {
    id: r.id, name: r.name, match_by: r.match_by,
    targetsText: (r.targets || []).join('\n'),
    policy: r.policy, outbound: r.outbound,
  }
}

function addKnown(ev: Event) {
  const sel = ev.target as HTMLSelectElement
  const v = sel.value
  if (!v || !dlg.value) return
  const cur = dlg.value.targetsText.trim()
  dlg.value.targetsText = cur ? `${cur}\n${v}` : v
  sel.value = ''
}

async function save() {
  if (!dlg.value) return
  dlgErr.value = ''
  const d = dlg.value
  const targets = d.targetsText.split('\n').map((s) => s.trim()).filter(Boolean)
  if (!targets.length) {
    dlgErr.value = t('obx.terminalTargetsRequired')
    return
  }
  if (d.policy === 'proxy' && !d.outbound) {
    dlgErr.value = t('obx.terminalOutboundRequired')
    return
  }
  dlgBusy.value = true
  try {
    const body = {
      name: d.name.trim(), match_by: d.match_by, targets,
      policy: d.policy, outbound: d.policy === 'proxy' ? d.outbound : '',
    }
    if (d.id) await obxPut(`/api/terminal-rules/${d.id}`, body)
    else await obxPost('/api/terminal-rules', body)
    dlg.value = null
    await load()
  } catch (e) {
    dlgErr.value = e instanceof ObxApiError ? e.message : t('obx.saveFailed')
  } finally {
    dlgBusy.value = false
  }
}

async function toggleEnabled(r: TRule) {
  try {
    await obxPut(`/api/terminal-rules/${r.id}`, { enabled: !r.enabled })
    await load()
  } catch (e) { err.value = e instanceof ObxApiError ? e.message : '保存失败' }
}

async function remove(r: TRule) {
  if (!confirm(t('obx.deleteConfirm'))) return
  try {
    await obxDel(`/api/terminal-rules/${r.id}`)
    await load()
  } catch (e) { err.value = e instanceof ObxApiError ? e.message : '删除失败' }
}

// 出口选择器
async function openObSel() {
  obSel.value.show = true
  obSel.value.search = ''
  obSel.value.tab = 'nodes'
  obSel.value.loading = true
  try {
    const [nodes, groups, health] = await Promise.all([
      obxGet<any[]>('/api/nodes'),
      obxGet<any[]>('/api/groups'),
      obxGet<any[]>('/api/health').catch(() => []),
    ])
    obSel.value.nodes = nodes || []
    obSel.value.groups = (groups || []).filter(
      (g: any) => g.name !== 'direct' && g.name !== 'block' && g.tag !== 'direct' && g.tag !== 'block',
    )
    const hm: Record<string, number> = {}
    for (const h of (health || [])) {
      if (h.latency_ms != null) hm[h.tag] = h.latency_ms
    }
    obSel.value.health = hm
  } catch (e) { /* 忽略 */ } finally {
    obSel.value.loading = false
  }
}

function selectOb(v: string) {
  if (dlg.value) dlg.value.outbound = v
  obSel.value.show = false
}

const filteredObNodes = computed(() => {
  const q = obSel.value.search.trim().toLowerCase()
  let list = obSel.value.nodes
  if (q) list = list.filter((n: any) => (n.name || n.tag || '').toLowerCase().includes(q))
  return list
})
const filteredObGroups = computed(() => {
  const q = obSel.value.search.trim().toLowerCase()
  let list = obSel.value.groups
  if (q) list = list.filter((g: any) => (g.name || '').toLowerCase().includes(q))
  return list
})
function obLatency(tag: string): string {
  const v = obSel.value.health[tag]
  return v != null ? String(v) : ''
}

onMounted(load)
</script>
