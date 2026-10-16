<!-- Open-Box 二开：出站节点组管理（由旧版自研 UI 移植；实时切换用 zashboard 原生代理页） -->
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
          class="btn btn-primary btn-sm"
          @click="openAdd"
        >
          {{ $t('obx.addGroup') }}
        </button>
      </div>
    </div>

    <div
      v-if="err"
      class="alert alert-error mb-3"
    >
      <span>{{ err }}</span>
    </div>

    <div class="overflow-x-auto rounded-box border border-base-300/30 bg-base-100">
      <table class="table">
        <thead>
          <tr>
            <th>{{ $t('obx.name') }}</th>
            <th>{{ $t('obx.type') }}</th>
            <th>{{ $t('obx.nodes') }}</th>
            <th>{{ $t('obx.detail') }}</th>
            <th>{{ $t('obx.enabled') }}</th>
            <th class="text-right">{{ $t('obx.actions') }}</th>
          </tr>
        </thead>
        <tbody>
          <tr
            v-for="g in groups"
            :key="g.id"
          >
            <td class="font-medium">
              {{ g.name }}
              <span
                v-if="g.builtin"
                class="badge badge-ghost badge-xs ml-1"
              >{{ $t('obx.builtin') }}</span>
            </td>
            <td>{{ typeName(g.type) }}</td>
            <td>{{ g.member_count }}</td>
            <td class="max-w-xs truncate text-sm opacity-70">
              {{ g.detail || groupDetail(g) }}
            </td>
            <td>
              <input
                v-if="!g.builtin"
                type="checkbox"
                class="toggle toggle-sm"
                :checked="g.enabled"
                @change="toggle(g)"
              />
              <span
                v-else
                class="opacity-50"
              >—</span>
            </td>
            <td class="text-right">
              <div
                v-if="!g.builtin"
                class="join"
              >
                <button
                  class="btn btn-ghost btn-xs join-item"
                  :disabled="isFirst(g)"
                  @click="move(g, -1)"
                >
                  ↑
                </button>
                <button
                  class="btn btn-ghost btn-xs join-item"
                  :disabled="isLast(g)"
                  @click="move(g, 1)"
                >
                  ↓
                </button>
                <button
                  class="btn btn-ghost btn-xs join-item"
                  @click="openEdit(g)"
                >
                  {{ $t('obx.edit') }}
                </button>
                <button
                  class="btn btn-ghost btn-xs join-item text-error"
                  @click="remove(g)"
                >
                  {{ $t('obx.delete') }}
                </button>
              </div>
              <span
                v-else
                class="text-sm opacity-50"
              >{{ $t('obx.builtinNoEdit') }}</span>
            </td>
          </tr>
        </tbody>
      </table>
    </div>

    <div
      v-if="dlg"
      class="modal modal-open"
    >
      <div class="modal-box max-w-lg">
        <h3 class="mb-4 text-lg font-bold">
          {{ dlg.id ? $t('obx.editGroup') : $t('obx.addGroup') }}
        </h3>
        <div class="grid grid-cols-2 gap-3">
          <label class="form-control">
            <span class="label-text mb-1">{{ $t('obx.name') }}</span>
            <input
              v-model="dlg.name"
              class="input input-bordered w-full"
            />
          </label>
          <label class="form-control">
            <span class="label-text mb-1">{{ $t('obx.type') }}</span>
            <select
              v-model="dlg.type"
              class="select select-bordered w-full"
            >
              <option value="urltest">{{ $t('obx.urltest') }}</option>
              <option value="selector">{{ $t('obx.selector') }}</option>
              <option value="failover">{{ $t('obx.failover') }}</option>
            </select>
          </label>
          <label class="form-control col-span-2">
            <span class="label-text mb-1">{{ $t('obx.membersHint') }}</span>
            <input
              v-model="dlg.members"
              class="input input-bordered w-full"
              placeholder="tag1, tag2（逗号分隔）"
            />
          </label>
          <label class="form-control col-span-2">
            <span class="label-text mb-1">{{ $t('obx.keywordsHint') }}</span>
            <input
              v-model="dlg.keywords"
              class="input input-bordered w-full"
              placeholder="香港, 美国（动态匹配，逗号分隔）"
              :disabled="dlg.type === 'failover'"
            />
          </label>
          <div
            v-if="dlg.type === 'failover'"
            class="col-span-2 rounded-box border border-base-300/30 p-3"
          >
            <div class="mb-2 flex items-center justify-between">
              <span class="label-text font-medium">{{ $t('obx.lanes') }}</span>
              <button
                class="btn btn-ghost btn-xs"
                @click="dlg.lanes.push({ name: `lane${dlg.lanes.length + 1}`, members: '' })"
              >{{ $t('obx.addLane') }}</button>
            </div>
            <div
              v-for="(ln, i) in dlg.lanes"
              :key="i"
              class="mb-2 grid grid-cols-3 gap-2"
            >
              <input
                v-model="ln.name"
                class="input input-bordered input-sm"
                :placeholder="$t('obx.laneName')"
              />
              <input
                v-model="ln.members"
                class="input input-bordered input-sm col-span-2"
                :placeholder="$t('obx.laneMembersPh')"
              />
            </div>
            <p class="text-xs opacity-60">{{ $t('obx.lanesHint') }}</p>
          </div>
          <label class="form-control">
            <span class="label-text mb-1">{{ $t('obx.intervalS') }}</span>
            <input
              v-model.number="dlg.interval_s"
              type="number"
              min="30"
              class="input input-bordered w-full"
            />
          </label>
          <label class="form-control">
            <span class="label-text mb-1">{{ $t('obx.toleranceMs') }}</span>
            <input
              v-model.number="dlg.tolerance_ms"
              type="number"
              min="0"
              class="input input-bordered w-full"
            />
          </label>
          <label class="form-control">
            <span class="label-text mb-1">{{ $t('obx.idleTimeout') }}</span>
            <input
              v-model="dlg.idle_timeout"
              class="input input-bordered w-full"
              placeholder="12h"
            />
          </label>
          <label class="form-control">
            <span class="label-text mb-1">{{ $t('obx.testUrl') }}</span>
            <input
              v-model="dlg.test_url"
              class="input input-bordered w-full"
              placeholder="空=全局测速地址"
            />
          </label>
        </div>
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
            class="btn btn-primary"
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
import { onMounted, ref } from 'vue'
import { useI18n } from 'vue-i18n'

const { t } = useI18n()

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
  lanes: { name: string; members: string[] }[]
  builtin?: boolean
  detail?: string
}

const groups = ref<Group[]>([])
const err = ref('')
const busy = ref(false)
const dlg = ref<any>(null)
const dlgErr = ref('')
const dlgBusy = ref(false)

function typeName(ty: string) {
  return { urltest: t('obx.urltest'), selector: t('obx.selector'), failover: t('obx.failover'), builtin: t('obx.builtin') }[ty] || ty
}
function groupDetail(g: Group) {
  if (g.type === 'urltest' || g.type === 'failover')
    return `${g.member_count} 个成员 · 检测间隔 ${g.interval_s || 300}s · 容差 ${g.tolerance_ms || 100}ms`
  return `${g.member_count} 个成员`
}
const editable = () => groups.value.filter((g) => !g.builtin)
const isFirst = (g: Group) => editable()[0]?.id === g.id
const isLast = (g: Group) => editable().slice(-1)[0]?.id === g.id

async function load() {
  err.value = ''
  try {
    groups.value = await obxGet<Group[]>('/api/groups')
  } catch (e) {
    err.value = e instanceof ObxApiError ? e.message : '加载失败'
  }
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

function openAdd() {
  dlgErr.value = ''
  dlg.value = { id: null, name: '', type: 'urltest', members: '', keywords: '', interval_s: 300, tolerance_ms: 100, idle_timeout: '12h', expected_status: '', test_url: '', lanes: [] }
}
function openEdit(g: Group) {
  dlgErr.value = ''
  dlg.value = { id: g.id, name: g.name, type: g.type, members: (g.members || []).join(', '), keywords: (g.dynamic_keywords || []).join(', '), interval_s: g.interval_s || 300, tolerance_ms: g.tolerance_ms || 100, idle_timeout: g.idle_timeout || '12h', expected_status: g.expected_status || '', test_url: g.test_url || '', lanes: (g.lanes || []).map((ln: any) => ({ name: ln.name, members: (ln.members || []).join(', ') })) }
}
const split = (s: string) => s.split(',').map((x) => x.trim()).filter(Boolean)

async function save() {
  if (!dlg.value?.name.trim()) { dlgErr.value = '名称不能为空'; return }
  const lanes = (dlg.value.lanes || []).map((ln: any) => ({ name: (ln.name || '').trim(), members: split(ln.members || '') })).filter((ln: any) => ln.name || ln.members.length)
  const body = { name: dlg.value.name.trim(), type: dlg.value.type, members: split(dlg.value.members), dynamic_keywords: split(dlg.value.keywords), interval_s: dlg.value.interval_s, tolerance_ms: dlg.value.tolerance_ms, idle_timeout: dlg.value.idle_timeout, expected_status: dlg.value.expected_status, test_url: dlg.value.test_url, lanes }
  dlgBusy.value = true
  dlgErr.value = ''
  try {
    if (dlg.value.id) await obxPut(`/api/groups/${dlg.value.id}`, body)
    else await obxPost('/api/groups', body)
    dlg.value = null
    await load()
  } catch (e) {
    dlgErr.value = e instanceof ObxApiError ? e.message : '保存失败'
  } finally {
    dlgBusy.value = false
  }
}

async function toggle(g: Group) {
  try { await obxPut(`/api/groups/${g.id}`, { enabled: !g.enabled }); await load() }
  catch (e) { err.value = e instanceof ObxApiError ? e.message : '操作失败' }
}
async function remove(g: Group) {
  if (!confirm(`确定删除组「${g.name}」吗？`)) return
  try { await obxDel(`/api/groups/${g.id}`); await load() }
  catch (e) { err.value = e instanceof ObxApiError ? e.message : '删除失败' }
}
async function move(g: Group, dir: number) {
  const list = editable()
  const i = list.findIndex((x) => x.id === g.id)
  const j = i + dir
  if (j < 0 || j >= list.length) return
  ;[list[i], list[j]] = [list[j], list[i]]
  try { await obxPost('/api/groups/reorder', { ids: list.map((x) => x.id) }); await load() }
  catch (e) { err.value = e instanceof ObxApiError ? e.message : '排序失败' }
}

onMounted(load)
</script>
