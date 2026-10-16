<!-- Open-Box 二开：终端分流（按设备 IP/MAC 指定直连/代理/旁路；由旧版自研 UI 移植） -->
<template>
  <div>
    <div class="mb-3 flex items-center justify-between">
      <h2 class="text-lg font-bold">{{ $t('obx.terminals') }}</h2>
    </div>

    <div
      v-if="err"
      class="alert alert-error mb-3"
    >
      <span>{{ err }}</span>
    </div>

    <div
      v-if="candidates.length"
      class="mb-3 rounded-box border border-base-300/30 bg-base-100 p-3"
    >
      <div class="mb-2 text-sm font-medium opacity-70">{{ $t('obx.detectedTerminals') }}</div>
      <div class="flex flex-wrap gap-2">
        <button
          v-for="c in candidates"
          :key="c.ident"
          class="btn btn-ghost btn-xs"
          @click="pick(c)"
        >
          {{ c.name || c.ident }} <span class="opacity-60">{{ c.ident }}</span>
        </button>
      </div>
    </div>

    <div class="overflow-x-auto rounded-box border border-base-300/30 bg-base-100">
      <table class="table">
        <thead>
          <tr>
            <th>{{ $t('obx.ident') }}</th>
            <th>{{ $t('obx.name') }}</th>
            <th>{{ $t('obx.policy') }}</th>
            <th class="text-right">{{ $t('obx.actions') }}</th>
          </tr>
        </thead>
        <tbody>
          <tr
            v-for="tm in terminals"
            :key="tm.id"
          >
            <td class="font-mono">{{ tm.ident }}</td>
            <td>{{ tm.name || '—' }}</td>
            <td>
              <select
                class="select select-bordered select-sm"
                :value="tm.policy"
                @change="setPolicy(tm, ($event.target as HTMLSelectElement).value)"
              >
                <option value="proxy">{{ $t('obx.polProxy') }}</option>
                <option value="direct">{{ $t('obx.polDirect') }}</option>
                <option value="bypass">{{ $t('obx.polBypass') }}</option>
              </select>
            </td>
            <td class="text-right">
              <button
                class="btn btn-ghost btn-xs text-error"
                @click="remove(tm)"
              >{{ $t('obx.delete') }}</button>
            </td>
          </tr>
          <tr v-if="!terminals.length">
            <td
              colspan="4"
              class="text-center opacity-60"
            >{{ $t('obx.noTerminals') }}</td>
          </tr>
        </tbody>
      </table>
    </div>

    <div class="mt-3 flex flex-wrap items-center gap-2">
      <input
        v-model="f.ident"
        class="input input-bordered input-sm"
        :placeholder="$t('obx.identPh')"
      />
      <input
        v-model="f.name"
        class="input input-bordered input-sm"
        :placeholder="$t('obx.name')"
      />
      <select
        v-model="f.policy"
        class="select select-bordered select-sm"
      >
        <option value="proxy">{{ $t('obx.polProxy') }}</option>
        <option value="direct">{{ $t('obx.polDirect') }}</option>
        <option value="bypass">{{ $t('obx.polBypass') }}</option>
      </select>
      <button
        class="btn btn-primary btn-sm"
        @click="add"
      >{{ $t('obx.add') }}</button>
    </div>
  </div>
</template>

<script setup lang="ts">
import { ObxApiError, obxDel, obxGet, obxPost } from '@/openbox/api'
import { onMounted, ref } from 'vue'

type Terminal = { id: number; ident: string; name: string; policy: string }

const terminals = ref<Terminal[]>([])
const candidates = ref<{ ident: string; name: string }[]>([])
const f = ref({ ident: '', name: '', policy: 'proxy' })
const err = ref('')

async function load() {
  err.value = ''
  try {
    const d = await obxGet<{ terminals: Terminal[] }>('/api/terminals')
    terminals.value = d.terminals || []
    const c = await obxGet<{ candidates: { ident: string; name: string }[] }>('/api/terminal-candidates').catch(() => ({ candidates: [] }))
    candidates.value = (c.candidates || []).filter((x) => !terminals.value.some((t) => t.ident === x.ident))
  } catch (e) { err.value = e instanceof ObxApiError ? e.message : '加载失败' }
}
function pick(c: { ident: string; name: string }) {
  f.value.ident = c.ident
  f.value.name = c.name || ''
}
async function add() {
  if (!f.value.ident.trim()) return
  try {
    await obxPost('/api/terminals', { ident: f.value.ident.trim(), name: f.value.name.trim(), policy: f.value.policy })
    f.value = { ident: '', name: '', policy: 'proxy' }
    await load()
  } catch (e) { err.value = e instanceof ObxApiError ? e.message : '添加失败' }
}
async function setPolicy(tm: Terminal, policy: string) {
  try {
    await obxPost('/api/terminals', { ident: tm.ident, name: tm.name, policy })
    await load()
  } catch (e) { err.value = e instanceof ObxApiError ? e.message : '保存失败' }
}
async function remove(tm: Terminal) {
  try { await obxDel(`/api/terminals/${tm.id}`); await load() }
  catch (e) { err.value = e instanceof ObxApiError ? e.message : '删除失败' }
}

onMounted(load)
</script>
