<!-- Open-Box 二开：链式代理（由旧版自研 UI 移植） -->
<template>
  <div>
    <div class="mb-3 flex items-center justify-between">
      <h2 class="text-lg font-bold">{{ $t('obx.chains') }}</h2>
      <button
        class="btn btn-primary btn-sm"
        @click="openAdd"
      >
        {{ $t('obx.addChain') }}
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
            <th>{{ $t('obx.exitProtocol') }}</th>
            <th>{{ $t('obx.server') }}</th>
            <th>{{ $t('obx.front') }}</th>
            <th class="text-right">{{ $t('obx.actions') }}</th>
          </tr>
        </thead>
        <tbody>
          <tr
            v-for="c in chains"
            :key="c.id"
          >
            <td class="font-medium">{{ c.name }}</td>
            <td>{{ c.exit_protocol }}</td>
            <td class="font-mono">{{ c.server }}:{{ c.port }}</td>
            <td>{{ Array.isArray(c.front) ? c.front.join(', ') : c.front }}</td>
            <td class="text-right">
              <div class="join">
                <button
                  class="btn btn-ghost btn-xs join-item"
                  @click="openEdit(c)"
                >{{ $t('obx.edit') }}</button>
                <button
                  class="btn btn-ghost btn-xs join-item text-error"
                  @click="remove(c)"
                >{{ $t('obx.delete') }}</button>
              </div>
            </td>
          </tr>
          <tr v-if="!chains.length">
            <td
              colspan="5"
              class="text-center opacity-60"
            >{{ $t('obx.noChains') }}</td>
          </tr>
        </tbody>
      </table>
    </div>

    <div
      v-if="dlg"
      class="modal modal-open"
    >
      <div class="modal-box">
        <h3 class="mb-4 text-lg font-bold">{{ dlg.id ? $t('obx.editChain') : $t('obx.addChain') }}</h3>
        <div class="grid grid-cols-2 gap-3">
          <label class="form-control">
            <span class="label-text mb-1">{{ $t('obx.name') }}</span>
            <input
              v-model="dlg.name"
              class="input input-bordered w-full"
            />
          </label>
          <label class="form-control">
            <span class="label-text mb-1">{{ $t('obx.exitProtocol') }}</span>
            <select
              v-model="dlg.exit_protocol"
              class="select select-bordered w-full"
            >
              <option value="socks">socks</option>
              <option value="http">http</option>
            </select>
          </label>
          <label class="form-control">
            <span class="label-text mb-1">{{ $t('obx.server') }}</span>
            <input
              v-model="dlg.server"
              class="input input-bordered w-full"
            />
          </label>
          <label class="form-control">
            <span class="label-text mb-1">{{ $t('obx.port') }}</span>
            <input
              v-model.number="dlg.port"
              type="number"
              min="1"
              max="65535"
              class="input input-bordered w-full"
            />
          </label>
          <label class="form-control col-span-2">
            <span class="label-text mb-1">{{ $t('obx.front') }}</span>
            <input
              v-model="dlg.front"
              class="input input-bordered w-full"
              placeholder="所有-自动"
            />
          </label>
        </div>
        <p
          v-if="dlgErr"
          class="mt-3 text-sm text-error"
        >{{ dlgErr }}</p>
        <div class="modal-action">
          <button
            class="btn btn-ghost"
            @click="dlg = null"
          >{{ $t('obx.cancel') }}</button>
          <button
            class="btn btn-primary"
            :disabled="dlgBusy"
            @click="save"
          >{{ $t('obx.save') }}</button>
        </div>
      </div>
    </div>
  </div>
</template>

<script setup lang="ts">
import { ObxApiError, obxDel, obxGet, obxPost, obxPut } from '@/openbox/api'
import { onMounted, ref } from 'vue'

type Chain = { id: number; name: string; exit_protocol: string; server: string; port: number; front: string | string[] }

const chains = ref<Chain[]>([])
const err = ref('')
const dlg = ref<any>(null)
const dlgErr = ref('')
const dlgBusy = ref(false)

async function load() {
  err.value = ''
  try { chains.value = await obxGet<Chain[]>('/api/chains') }
  catch (e) { err.value = e instanceof ObxApiError ? e.message : '加载失败' }
}
function openAdd() {
  dlgErr.value = ''
  dlg.value = { id: null, name: '', exit_protocol: 'socks', server: '', port: 1080, front: '所有-自动' }
}
function openEdit(c: Chain) {
  dlgErr.value = ''
  dlg.value = { id: c.id, name: c.name, exit_protocol: c.exit_protocol, server: c.server, port: c.port, front: Array.isArray(c.front) ? c.front.join(', ') : c.front }
}
async function save() {
  if (!dlg.value?.name.trim()) { dlgErr.value = '名称不能为空'; return }
  const body = { name: dlg.value.name.trim(), exit_protocol: dlg.value.exit_protocol, server: dlg.value.server.trim(), port: dlg.value.port, front: dlg.value.front }
  dlgBusy.value = true; dlgErr.value = ''
  try {
    if (dlg.value.id) await obxPut(`/api/chains/${dlg.value.id}`, body)
    else await obxPost('/api/chains', body)
    dlg.value = null; await load()
  } catch (e) { dlgErr.value = e instanceof ObxApiError ? e.message : '保存失败' }
  finally { dlgBusy.value = false }
}
async function remove(c: Chain) {
  if (!confirm(`确定删除链式代理「${c.name}」吗？`)) return
  try { await obxDel(`/api/chains/${c.id}`); await load() }
  catch (e) { err.value = e instanceof ObxApiError ? e.message : '删除失败' }
}

onMounted(load)
</script>
