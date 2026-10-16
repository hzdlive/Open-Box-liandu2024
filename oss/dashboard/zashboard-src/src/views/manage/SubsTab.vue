<!-- Open-Box 二开：订阅管理（由旧版自研 UI 移植核心功能） -->
<template>
  <div>
    <div class="mb-3 flex items-center justify-between">
      <h2 class="text-lg font-bold">{{ $t('obx.subscriptions') }}</h2>
      <button
        class="btn btn-primary btn-sm"
        @click="openAdd"
      >
        {{ $t('obx.addSubscription') }}
      </button>
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
            <th>{{ $t('obx.nodes') }}</th>
            <th>{{ $t('obx.autoUpdate') }}</th>
            <th>{{ $t('obx.updatedAt') }}</th>
            <th>{{ $t('obx.enabled') }}</th>
            <th class="text-right">{{ $t('obx.actions') }}</th>
          </tr>
        </thead>
        <tbody>
          <tr
            v-for="s in subs"
            :key="s.id"
          >
            <td class="font-medium">{{ s.name }}</td>
            <td>{{ s.node_count }}/{{ s.node_total }}</td>
            <td>{{ s.auto_update?.enabled ? `每${s.auto_update.days}天 ${s.auto_update.hour}点` : '—' }}</td>
            <td class="text-sm opacity-70">{{ fmtTime(s.updated_at) }}</td>
            <td>
              <input
                type="checkbox"
                class="toggle toggle-sm"
                :checked="s.enabled"
                @change="toggleEnabled(s)"
              />
            </td>
            <td class="text-right">
              <div class="join">
                <button
                  class="btn btn-ghost btn-xs join-item"
                  :disabled="busyId === s.id"
                  @click="refresh(s)"
                >
                  {{ $t('obx.refresh') }}
                </button>
                <button
                  class="btn btn-ghost btn-xs join-item"
                  @click="openEdit(s)"
                >
                  {{ $t('obx.edit') }}
                </button>
                <button
                  class="btn btn-ghost btn-xs join-item text-error"
                  @click="remove(s)"
                >
                  {{ $t('obx.delete') }}
                </button>
              </div>
            </td>
          </tr>
          <tr v-if="!subs.length && !loading">
            <td
              colspan="6"
              class="text-center opacity-60"
            >
              {{ $t('obx.noSubscriptions') }}
            </td>
          </tr>
        </tbody>
      </table>
    </div>

    <!-- 订阅分享 -->
    <div class="mb-3 mt-6 flex items-center justify-between">
      <h3 class="font-bold">{{ $t('obx.subShare') }}</h3>
      <button
        class="btn btn-ghost btn-sm"
        @click="openShareAdd"
      >
        {{ $t('obx.add') }}
      </button>
    </div>
    <p class="mb-2 text-sm opacity-60">{{ $t('obx.subShareHint') }}</p>
    <div class="overflow-x-auto rounded-box border border-base-300/30 bg-base-100">
      <table class="table">
        <thead>
          <tr>
            <th>{{ $t('obx.name') }}</th>
            <th>{{ $t('obx.shareLink') }}</th>
            <th class="text-right">{{ $t('obx.actions') }}</th>
          </tr>
        </thead>
        <tbody>
          <tr
            v-for="sh in shares"
            :key="sh.id"
          >
            <td class="font-medium">{{ sh.name }}</td>
            <td class="max-w-md truncate font-mono text-xs">{{ shareUrl(sh.token) }}</td>
            <td class="text-right">
              <div class="join">
                <button
                  class="btn btn-ghost btn-xs join-item"
                  @click="copyLink(sh)"
                >{{ $t('obx.copy') }}</button>
                <button
                  class="btn btn-ghost btn-xs join-item text-error"
                  @click="delShare(sh)"
                >{{ $t('obx.delete') }}</button>
              </div>
            </td>
          </tr>
          <tr v-if="!shares.length">
            <td
              colspan="3"
              class="text-center opacity-60"
            >{{ $t('obx.noSubShare') }}</td>
          </tr>
        </tbody>
      </table>
    </div>

    <!-- 新增 / 编辑弹窗 -->
    <div
      v-if="dlg"
      class="modal modal-open"
    >
      <div class="modal-box">
        <h3 class="mb-4 text-lg font-bold">
          {{ dlg.id ? $t('obx.editSubscription') : $t('obx.addSubscription') }}
        </h3>
        <label class="form-control mb-3">
          <span class="label-text mb-1">{{ $t('obx.name') }}</span>
          <input
            v-model="dlg.name"
            class="input input-bordered w-full"
          />
        </label>
        <label class="form-control mb-3">
          <span class="label-text mb-1">{{ $t('obx.urls') }}</span>
          <textarea
            v-model="dlg.urlsText"
            class="textarea textarea-bordered w-full"
            rows="3"
            placeholder="https://…（每行一个）"
          />
        </label>
        <div class="mb-4 rounded-box border border-base-300/30 p-3">
          <label class="flex cursor-pointer items-center gap-2">
            <input
              v-model="dlg.auEnabled"
              type="checkbox"
              class="toggle toggle-sm"
            />
            <span class="label-text">{{ $t('obx.autoUpdate') }}</span>
          </label>
          <div
            v-if="dlg.auEnabled"
            class="mt-2 grid grid-cols-2 gap-2"
          >
            <label class="form-control">
              <span class="label-text mb-1">{{ $t('obx.everyDays') }}</span>
              <input
                v-model.number="dlg.auDays"
                type="number"
                min="1"
                class="input input-bordered w-full"
              />
            </label>
            <label class="form-control">
              <span class="label-text mb-1">{{ $t('obx.atHour') }}</span>
              <input
                v-model.number="dlg.auHour"
                type="number"
                min="0"
                max="23"
                class="input input-bordered w-full"
              />
            </label>
          </div>
        </div>
        <p
          v-if="dlgErr"
          class="mb-3 text-sm text-error"
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

type Sub = {
  id: number
  name: string
  urls: string[]
  node_count: number
  node_total: number
  enabled: boolean
  auto_update_hours: number
  auto_update: { enabled: boolean; days: number; hour: number }
  updated_at: string
}

const subs = ref<Sub[]>([])
const loading = ref(false)
const err = ref('')
const busyId = ref<number | null>(null)
const dlg = ref<{ id: number | null; name: string; urlsText: string; auEnabled: boolean; auDays: number; auHour: number } | null>(null)
const dlgErr = ref('')
const dlgBusy = ref(false)

function fmtTime(t: string) {
  if (!t) return '—'
  return t.replace('T', ' ').slice(0, 19)
}

async function load() {
  loading.value = true
  err.value = ''
  try {
    subs.value = await obxGet<Sub[]>('/api/subscriptions')
  } catch (e) {
    err.value = e instanceof ObxApiError ? e.message : '加载失败'
  } finally {
    loading.value = false
  }
}

function openAdd() {
  dlgErr.value = ''
  dlg.value = { id: null, name: '', urlsText: '', auEnabled: false, auDays: 1, auHour: 4 }
}

function openEdit(s: Sub) {
  dlgErr.value = ''
  const au = s.auto_update || { enabled: false, days: 1, hour: 4 }
  dlg.value = { id: s.id, name: s.name, urlsText: (s.urls || []).join('\n'), auEnabled: !!au.enabled, auDays: au.days || 1, auHour: au.hour ?? 4 }
}

async function save() {
  if (!dlg.value) return
  const urls = dlg.value.urlsText.split('\n').map((u) => u.trim()).filter(Boolean)
  if (!dlg.value.name.trim() || !urls.length) {
    dlgErr.value = '名称和订阅链接不能为空'
    return
  }
  dlgBusy.value = true
  dlgErr.value = ''
  try {
    const au = { enabled: dlg.value.auEnabled, days: dlg.value.auDays, hour: dlg.value.auHour }
    if (dlg.value.id) {
      await obxPut(`/api/subscriptions/${dlg.value.id}`, {
        name: dlg.value.name.trim(),
        urls,
        auto_update: au,
      })
    } else {
      await obxPost('/api/subscriptions', {
        name: dlg.value.name.trim(),
        urls,
        auto_update: au,
      })
    }
    dlg.value = null
    await load()
  } catch (e) {
    dlgErr.value = e instanceof ObxApiError ? e.message : '保存失败'
  } finally {
    dlgBusy.value = false
  }
}

async function toggleEnabled(s: Sub) {
  try {
    await obxPut(`/api/subscriptions/${s.id}`, { enabled: !s.enabled })
    s.enabled = !s.enabled
  } catch (e) {
    err.value = e instanceof ObxApiError ? e.message : '操作失败'
  }
}

async function refresh(s: Sub) {
  busyId.value = s.id
  err.value = ''
  try {
    await obxPost(`/api/subscriptions/${s.id}/refresh`, {})
    await load()
  } catch (e) {
    err.value = e instanceof ObxApiError ? e.message : '刷新失败'
  } finally {
    busyId.value = null
  }
}

async function remove(s: Sub) {
  if (!confirm(`确定删除订阅「${s.name}」吗？其下节点将一并删除。`)) return
  try {
    await obxDel(`/api/subscriptions/${s.id}`)
    await load()
  } catch (e) {
    err.value = e instanceof ObxApiError ? e.message : '删除失败'
  }
}

// ---- 订阅分享 ----
type Share = { id: number; name: string; token: string; node_filter: string; created_at: string }
const shares = ref<Share[]>([])

function shareUrl(token: string) {
  return `${location.origin}/sub/${token}`
}
async function loadShares() {
  try { shares.value = await obxGet<Share[]>('/api/subscription-shares') }
  catch { shares.value = [] }
}
async function openShareAdd() {
  const name = prompt('分享名称：')
  if (!name?.trim()) return
  try {
    await obxPost('/api/subscription-shares', { name: name.trim() })
    await loadShares()
  } catch (e) { err.value = e instanceof ObxApiError ? e.message : '创建失败' }
}
async function copyLink(sh: Share) {
  try { await navigator.clipboard.writeText(shareUrl(sh.token)) }
  catch { /* clipboard unavailable */ }
}
async function delShare(sh: Share) {
  if (!confirm(`确定删除分享「${sh.name}」吗？`)) return
  try { await obxDel(`/api/subscription-shares/${sh.id}`); await loadShares() }
  catch (e) { err.value = e instanceof ObxApiError ? e.message : '删除失败' }
}

onMounted(() => { load(); loadShares() })
</script>
