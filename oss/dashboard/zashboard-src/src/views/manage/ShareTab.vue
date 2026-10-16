<!-- Open-Box 二开：共享网络（LAN Shadowsocks 入站服务器；1:1 对标原版 profile.servers[]） -->
<template>
  <div>
    <div class="mb-3 flex items-center justify-between">
      <h2 class="text-lg font-bold">{{ $t('obx.shareNetwork') }}</h2>
      <button
        class="btn btn-primary btn-sm"
        @click="openAdd"
      >
        {{ $t('obx.addServer') }}
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
            <th>{{ $t('obx.protocol') }}</th>
            <th>{{ $t('obx.address') }}</th>
            <th>{{ $t('obx.port') }}</th>
            <th>{{ $t('obx.enabled') }}</th>
            <th class="text-right">{{ $t('obx.actions') }}</th>
          </tr>
        </thead>
        <tbody>
          <tr
            v-for="s in servers"
            :key="s.id"
          >
            <td class="font-medium">{{ s.name || '—' }}</td>
            <td>Shadowsocks</td>
            <td class="font-mono">{{ s.address }}</td>
            <td class="font-mono">{{ s.port }}</td>
            <td>
              <input
                type="checkbox"
                class="toggle toggle-sm"
                :checked="s.enabled"
                @change="toggle(s)"
              />
            </td>
            <td class="text-right">
              <div class="join">
                <button
                  class="btn btn-ghost btn-xs join-item"
                  @click="showLink(s)"
                >{{ $t('obx.shareLink') }}</button>
                <button
                  class="btn btn-ghost btn-xs join-item"
                  @click="openEdit(s)"
                >{{ $t('obx.edit') }}</button>
                <button
                  class="btn btn-ghost btn-xs join-item text-error"
                  @click="remove(s)"
                >{{ $t('obx.delete') }}</button>
              </div>
            </td>
          </tr>
          <tr v-if="!servers.length">
            <td
              colspan="6"
              class="text-center opacity-60"
            >{{ $t('obx.noShareServers') }}</td>
          </tr>
        </tbody>
      </table>
    </div>

    <div
      v-if="dlg"
      class="modal modal-open"
    >
      <div class="modal-box">
        <h3 class="mb-4 text-lg font-bold">{{ dlg.id ? $t('obx.editServer') : $t('obx.addServer') }}</h3>
        <div class="grid grid-cols-2 gap-3">
          <label class="form-control">
            <span class="label-text mb-1">{{ $t('obx.remark') }}</span>
            <input
              v-model="dlg.name"
              class="input input-bordered w-full"
              placeholder="例如：家里"
            />
          </label>
          <label class="form-control">
            <span class="label-text mb-1">{{ $t('obx.protocol') }}</span>
            <select
              v-model="dlg.protocol"
              class="select select-bordered w-full"
            >
              <option value="shadowsocks">Shadowsocks</option>
            </select>
          </label>
          <label class="form-control">
            <span class="label-text mb-1">{{ $t('obx.address') }}</span>
            <input
              v-model="dlg.address"
              class="input input-bordered w-full"
              placeholder="127.0.0.1"
            />
          </label>
          <label class="form-control">
            <span class="label-text mb-1">{{ $t('obx.port') }}</span>
            <input
              v-model.number="dlg.port"
              type="number"
              min="1024"
              max="65535"
              class="input input-bordered w-full"
            />
          </label>
          <label class="form-control">
            <span class="label-text mb-1">{{ $t('obx.cipher') }}</span>
            <select
              v-model="dlg.method"
              class="select select-bordered w-full"
            >
              <option
                v-for="m in methods"
                :key="m"
                :value="m"
              >{{ m }}</option>
            </select>
          </label>
          <label class="form-control">
            <span class="label-text mb-1">{{ $t('obx.password') }}</span>
            <div class="join w-full">
              <input
                v-model="dlg.password"
                class="input input-bordered join-item w-full"
                :placeholder="$t('obx.autoGen')"
              />
              <button
                class="btn btn-ghost join-item"
                @click="dlg.password = ''"
                :title="$t('obx.regen')"
              >↻</button>
            </div>
          </label>
        </div>
        <p class="mt-3 text-xs opacity-60">{{ $t('obx.noTlsHint') }}</p>
        <div
          v-if="link"
          class="mt-3"
        >
          <div class="label-text mb-1">{{ $t('obx.shareLink') }}</div>
          <div class="flex items-center gap-2">
            <input
              :value="link"
              readonly
              class="input input-bordered input-sm w-full font-mono text-xs"
              @click="($event.target as HTMLInputElement).select()"
            />
            <button
              class="btn btn-ghost btn-sm"
              @click="copy(link)"
            >{{ $t('obx.copy') }}</button>
          </div>
        </div>
        <p
          v-if="dlgErr"
          class="mt-3 text-sm text-error"
        >{{ dlgErr }}</p>
        <div class="modal-action">
          <button
            class="btn btn-ghost"
            @click="dlg = null; link = ''"
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

type ShareServer = { id: number; name: string; protocol: string; address: string; port: number; method: string; password: string; enabled: boolean }

const servers = ref<ShareServer[]>([])
const err = ref('')
const dlg = ref<any>(null)
const dlgErr = ref('')
const dlgBusy = ref(false)
const link = ref('')
const methods = ['aes-256-gcm', 'aes-128-gcm', 'chacha20-ietf-poly1305', '2022-blake3-aes-128-gcm', '2022-blake3-aes-256-gcm']

async function load() {
  err.value = ''
  try { servers.value = await obxGet<ShareServer[]>('/api/share-servers') }
  catch (e) { err.value = e instanceof ObxApiError ? e.message : '加载失败' }
}
function openAdd() {
  dlgErr.value = ''; link.value = ''
  dlg.value = { id: null, name: '', protocol: 'shadowsocks', address: '127.0.0.1', port: 8388, method: 'aes-256-gcm', password: '' }
}
function openEdit(s: ShareServer) {
  dlgErr.value = ''; link.value = ''
  dlg.value = { id: s.id, name: s.name, protocol: s.protocol, address: s.address, port: s.port, method: s.method, password: s.password }
  showLink(s)
}
function ssLink(s: { method: string; password: string; address: string; port: number }) {
  const userinfo = btoa(`${s.method}:${s.password}`).replace(/=+$/, '')
  return `ss://${userinfo}@${s.address}:${s.port}`
}
function showLink(s: ShareServer) {
  link.value = ssLink(s)
}
async function copy(t: string) {
  try { await navigator.clipboard.writeText(t) } catch { /* noop */ }
}
async function save() {
  if (!dlg.value) return
  dlgBusy.value = true; dlgErr.value = ''
  try {
    const body = { name: dlg.value.name.trim(), protocol: dlg.value.protocol, address: dlg.value.address.trim() || '127.0.0.1', port: dlg.value.port, method: dlg.value.method, password: dlg.value.password.trim() }
    let saved: ShareServer
    if (dlg.value.id) saved = await obxPut(`/api/share-servers/${dlg.value.id}`, body)
    else saved = await obxPost('/api/share-servers', body)
    link.value = ssLink(saved)
    await load()
  } catch (e) { dlgErr.value = e instanceof ObxApiError ? e.message : '保存失败' }
  finally { dlgBusy.value = false }
}
async function toggle(s: ShareServer) {
  try { await obxPut(`/api/share-servers/${s.id}`, { enabled: !s.enabled }); await load() }
  catch (e) { err.value = e instanceof ObxApiError ? e.message : '操作失败' }
}
async function remove(s: ShareServer) {
  if (!confirm(`确定删除服务器「${s.name || s.port}」吗？`)) return
  try { await obxDel(`/api/share-servers/${s.id}`); await load() }
  catch (e) { err.value = e instanceof ObxApiError ? e.message : '删除失败' }
}

onMounted(load)
</script>
