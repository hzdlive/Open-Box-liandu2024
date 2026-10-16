<!-- Open-Box 二开：共享网络（1:1 对标原版添加/编辑服务器模态框，5种协议） -->
<template>
  <div>
    <div class="mb-3 flex items-center justify-between">
      <h2 class="text-lg font-bold">{{ $t('obx.shareNetwork') }}</h2>
      <button
        class="btn btn-primary btn-sm"
        @click="openAdd()"
      >
        + {{ $t('obx.addServer') }}
      </button>
    </div>

    <div
      v-if="err"
      class="alert alert-error mb-3"
    >
      <span>{{ err }}</span>
    </div>

    <!-- 服务器列表 -->
    <div class="flex flex-col gap-2">
      <div
        v-for="s in servers"
        :key="s.id"
        class="flex items-center gap-3 rounded-box border border-base-300/30 bg-base-100 p-3"
        :class="{ 'opacity-60': !s.enabled }"
      >
        <span class="cursor-move opacity-40">≡</span>
        <div class="flex-1">
          <div class="font-medium">{{ s.name || $t('obx.unnamed') }}</div>
          <div class="text-xs opacity-60 font-mono">
            {{ protocolLabel(s.protocol) }} {{ $t('obx.port') }} {{ s.port }} {{ s.address }}
          </div>
        </div>
        <button
          class="btn btn-ghost btn-sm btn-square"
          :class="s.enabled ? 'text-success' : 'opacity-40'"
          :title="s.enabled ? $t('obx.disable') : $t('obx.enable')"
          @click="toggle(s)"
        >
          ⏻
        </button>
        <button
          class="btn btn-ghost btn-sm btn-square"
          :title="$t('obx.copyLink')"
          @click="copyLink(s)"
        >
          📋
        </button>
        <button
          class="btn btn-ghost btn-sm btn-square"
          :title="$t('obx.edit')"
          @click="openEdit(s)"
        >
          ✎
        </button>
        <button
          class="btn btn-ghost btn-sm btn-square text-error"
          :title="$t('obx.delete')"
          @click="remove(s)"
        >
          🗑
        </button>
      </div>
      <div
        v-if="!servers.length"
        class="rounded-box border border-base-300/30 bg-base-100 p-6 text-center opacity-60"
      >
        {{ $t('obx.noShareServers') }}
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
            {{ dlg.id ? $t('obx.editServer') : $t('obx.addServer') }}
          </h3>
          <button
            class="btn btn-ghost btn-sm btn-square"
            @click="dlg = null"
          >
            ✕
          </button>
        </div>

        <div class="grid grid-cols-2 gap-3">
          <!-- 备注 -->
          <label class="form-control">
            <span class="label-text mb-1">{{ $t('obx.remark') }}</span>
            <input
              v-model="dlg.name"
              class="input input-bordered w-full rounded-full"
              :placeholder="$t('obx.serverRemarkPh')"
            />
          </label>
          <!-- 协议 -->
          <label class="form-control">
            <span class="label-text mb-1">{{ $t('obx.protocol') }}</span>
            <select
              v-model="dlg.protocol"
              class="select select-bordered w-full rounded-full"
            >
              <option value="shadowsocks">Shadowsocks</option>
              <option value="vless">VLESS</option>
              <option value="tuic">TUIC</option>
              <option value="hysteria2">Hysteria2</option>
              <option value="socks5http">{{ $t('obx.socks5http') }}</option>
            </select>
          </label>
          <!-- 域名/IP -->
          <label class="form-control">
            <span class="label-text mb-1">{{ $t('obx.domainIp') }}</span>
            <input
              v-model="dlg.address"
              class="input input-bordered w-full rounded-full"
            />
          </label>
          <!-- 端口 -->
          <label class="form-control">
            <span class="label-text mb-1">{{ $t('obx.port') }}</span>
            <input
              v-model.number="dlg.port"
              type="number"
              min="1"
              max="65535"
              class="input input-bordered w-full rounded-full"
            />
          </label>

          <!-- Shadowsocks: 加密 + 密码 -->
          <template v-if="dlg.protocol === 'shadowsocks'">
            <label class="form-control">
              <span class="label-text mb-1">{{ $t('obx.cipher') }}</span>
              <select
                v-model="dlg.method"
                class="select select-bordered w-full rounded-full"
              >
                <option v-for="m in ssMethods" :key="m" :value="m">{{ m }}</option>
              </select>
            </label>
            <label class="form-control">
              <span class="label-text mb-1">{{ $t('obx.password') }}</span>
              <div class="join w-full">
                <input
                  v-model="dlg.password"
                  class="input input-bordered join-item w-full rounded-l-full"
                />
                <button class="btn btn-ghost join-item rounded-r-full" @click="dlg.password = genPassword()">↻</button>
              </div>
            </label>
            <p class="col-span-2 text-xs opacity-60">{{ $t('obx.ssNoTlsHint') }}</p>
          </template>

          <!-- VLESS: UUID + TLS -->
          <template v-if="dlg.protocol === 'vless'">
            <label class="form-control col-span-2">
              <span class="label-text mb-1">UUID</span>
              <div class="flex items-center gap-2">
                <div class="join flex-1">
                  <input
                    v-model="dlg.uuid"
                    class="input input-bordered join-item w-full rounded-l-full font-mono text-sm"
                  />
                  <button class="btn btn-ghost join-item rounded-r-full" @click="dlg.uuid = genUUID()">↻</button>
                </div>
                <label class="flex cursor-pointer items-center gap-2">
                  <input v-model="dlg.tls" type="checkbox" class="toggle toggle-success" />
                  <span class="text-sm">TLS（{{ $t('obx.selfCert') }}）</span>
                </label>
              </div>
            </label>
            <p class="col-span-2 text-xs opacity-60">{{ $t('obx.vlessTlsHint') }}</p>
          </template>

          <!-- TUIC: UUID + 密码 -->
          <template v-if="dlg.protocol === 'tuic'">
            <label class="form-control">
              <span class="label-text mb-1">UUID</span>
              <div class="join w-full">
                <input
                  v-model="dlg.uuid"
                  class="input input-bordered join-item w-full rounded-l-full font-mono text-sm"
                />
                <button class="btn btn-ghost join-item rounded-r-full" @click="dlg.uuid = genUUID()">↻</button>
              </div>
            </label>
            <label class="form-control">
              <span class="label-text mb-1">{{ $t('obx.password') }}</span>
              <div class="join w-full">
                <input
                  v-model="dlg.password"
                  class="input input-bordered join-item w-full rounded-l-full"
                />
                <button class="btn btn-ghost join-item rounded-r-full" @click="dlg.password = genPassword()">↻</button>
              </div>
            </label>
            <p class="col-span-2 text-xs opacity-60">{{ $t('obx.tuicTlsHint') }}</p>
          </template>

          <!-- Hysteria2: 密码 + 混淆密码 -->
          <template v-if="dlg.protocol === 'hysteria2'">
            <label class="form-control">
              <span class="label-text mb-1">{{ $t('obx.password') }}</span>
              <div class="join w-full">
                <input
                  v-model="dlg.password"
                  class="input input-bordered join-item w-full rounded-l-full"
                />
                <button class="btn btn-ghost join-item rounded-r-full" @click="dlg.password = genPassword()">↻</button>
              </div>
            </label>
            <label class="form-control">
              <span class="label-text mb-1">{{ $t('obx.obfsPassword') }}</span>
              <div class="join w-full">
                <input
                  v-model="dlg.obfs"
                  class="input input-bordered join-item w-full rounded-l-full"
                  :placeholder="$t('obx.obfsPh')"
                />
                <button class="btn btn-ghost join-item rounded-r-full" @click="dlg.obfs = genPassword()">↻</button>
              </div>
            </label>
            <p class="col-span-2 text-xs opacity-60">{{ $t('obx.hy2TlsHint') }}</p>
          </template>

          <!-- SOCKS5/HTTP: 用户名 + 密码 -->
          <template v-if="dlg.protocol === 'socks5http'">
            <label class="form-control">
              <span class="label-text mb-1">{{ $t('obx.username') }}</span>
              <input
                v-model="dlg.username"
                class="input input-bordered w-full rounded-full"
                :placeholder="$t('obx.optionalAuth')"
              />
            </label>
            <label class="form-control">
              <span class="label-text mb-1">{{ $t('obx.password') }}</span>
              <div class="join w-full">
                <input
                  v-model="dlg.password"
                  class="input input-bordered join-item w-full rounded-l-full"
                  :placeholder="$t('obx.optionalAuth')"
                />
                <button class="btn btn-ghost join-item rounded-r-full" @click="dlg.password = genPassword()">↻</button>
              </div>
            </label>
            <p class="col-span-2 text-xs opacity-60">{{ $t('obx.socksHttpHint') }}</p>
          </template>
        </div>

        <!-- 分享链接 -->
        <div class="mt-4">
          <div class="label-text mb-1">{{ $t('obx.shareLink') }}</div>
          <div class="flex items-center gap-2">
            <input
              :value="shareLink"
              readonly
              class="input input-bordered w-full rounded-full font-mono text-xs"
              @click="($event.target as HTMLInputElement).select()"
            />
            <button class="btn btn-ghost btn-square" @click="copy(shareLink)">📋</button>
          </div>
        </div>

        <!-- 二维码（本地生成，不依赖外部服务） -->
        <div v-if="shareLink" class="mt-4 flex justify-center">
          <img
            :src="`/api/share/qr?text=${encodeURIComponent(shareLink)}`"
            alt="QR"
            class="rounded-box border border-base-300 p-2"
          />
        </div>

        <p v-if="dlgErr" class="mt-3 text-sm text-error">{{ dlgErr }}</p>

        <div class="modal-action">
          <button class="btn btn-ghost" @click="dlg = null">{{ $t('obx.cancel') }}</button>
          <button class="btn btn-success" :disabled="dlgBusy" @click="save()">{{ $t('obx.save') }}</button>
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

type ShareServer = {
  id: number; name: string; protocol: string; address: string; port: number
  method: string; password: string; enabled: boolean; params: any
}

const servers = ref<ShareServer[]>([])
const err = ref('')
const dlg = ref<any>(null)
const dlgErr = ref('')
const dlgBusy = ref(false)
const ssMethods = ['aes-256-gcm', 'aes-128-gcm', 'chacha20-ietf-poly1305', '2022-blake3-aes-128-gcm', '2022-blake3-aes-256-gcm']

function protocolLabel(p: string) {
  return { shadowsocks: 'Shadowsocks', vless: 'VLESS', tuic: 'TUIC', hysteria2: 'Hysteria2', socks5http: 'SOCKS5 / HTTP' }[p] || p
}

function genPassword(len = 16) {
  const chars = 'ABCDEFGHJKLMNPQRSTUVWXYZabcdefghjkmnpqrstuvwxyz23456789'
  let s = ''
  const arr = new Uint32Array(len)
  crypto.getRandomValues(arr)
  for (let i = 0; i < len; i++) s += chars[arr[i] % chars.length]
  return s
}
function genUUID() {
  return 'xxxxxxxx-xxxx-4xxx-yxxx-xxxxxxxxxxxx'.replace(/[xy]/g, (c) => {
    const r = (crypto.getRandomValues(new Uint8Array(1))[0] & 15)
    const v = c === 'x' ? r : (r & 0x3 | 0x8)
    return v.toString(16)
  })
}

// 生成分享链接
const shareLink = computed(() => {
  if (!dlg.value) return ''
  const d = dlg.value
  const host = d.address || '127.0.0.1'
  const port = d.port || 0
  const remark = d.name ? `#${encodeURIComponent(d.name)}` : ''
  if (d.protocol === 'shadowsocks') {
    const ui = btoa(`${d.method}:${d.password}`).replace(/=+$/, '')
    return `ss://${ui}@${host}:${port}${remark}`
  }
  if (d.protocol === 'vless') {
    const tls = d.tls ? '?security=tls&allowInsecure=1' : ''
    return `vless://${d.uuid}@${host}:${port}${tls}${remark}`
  }
  if (d.protocol === 'tuic') {
    return `tuic://${d.uuid}:${d.password}@${host}:${port}?allow_insecure=1${remark}`
  }
  if (d.protocol === 'hysteria2') {
    const obfs = d.obfs ? `&obfs=salamander&obfs-password=${encodeURIComponent(d.obfs)}` : ''
    return `hysteria2://${encodeURIComponent(d.password)}@${host}:${port}/?insecure=1${obfs}${remark}`
  }
  if (d.protocol === 'socks5http') {
    let auth = ''
    if (d.username) auth = `${encodeURIComponent(d.username)}:${encodeURIComponent(d.password)}@`
    else if (d.password) auth = `:${encodeURIComponent(d.password)}@`
    return `socks5://${auth}${host}:${port}${remark}`
  }
  return ''
})

async function load() {
  err.value = ''
  try { servers.value = await obxGet<ShareServer[]>('/api/share-servers') }
  catch (e) { err.value = e instanceof ObxApiError ? e.message : '加载失败' }
}

function openAdd() {
  dlgErr.value = ''
  dlg.value = {
    id: null, name: '', protocol: 'shadowsocks',
    address: '192.168.2.250', port: 8388,
    method: 'aes-256-gcm', password: genPassword(),
    uuid: genUUID(), tls: true, obfs: '',
    username: '',
  }
}

function openEdit(s: ShareServer) {
  dlgErr.value = ''
  const p = s.params || {}
  dlg.value = {
    id: s.id, name: s.name, protocol: s.protocol,
    address: s.address, port: s.port,
    method: s.method, password: s.password,
    uuid: p.uuid || genUUID(), tls: p.tls !== false, obfs: p.obfs || '',
    username: p.username || '',
  }
}

async function copy(text: string) {
  try { await navigator.clipboard.writeText(text) } catch { /* noop */ }
}

function copyLink(s: ShareServer) {
  // 构造该服务器的分享链接并复制
  const d = {
    name: s.name, protocol: s.protocol, address: s.address, port: s.port,
    method: s.method, password: s.password,
    uuid: s.params?.uuid || '', tls: s.params?.tls !== false,
    obfs: s.params?.obfs || '', username: s.params?.username || '',
  }
  const save = dlg.value
  dlg.value = d
  const link = shareLink.value
  dlg.value = save
  copy(link)
}

async function save() {
  if (!dlg.value) return
  dlgBusy.value = true; dlgErr.value = ''
  try {
    const d = dlg.value
    const body: any = {
      name: d.name.trim(), protocol: d.protocol,
      address: d.address.trim() || '127.0.0.1', port: d.port,
      method: d.method, password: d.password,
      params: {},
    }
    if (d.protocol === 'vless') body.params = { uuid: d.uuid, tls: d.tls }
    else if (d.protocol === 'tuic') body.params = { uuid: d.uuid }
    else if (d.protocol === 'hysteria2') body.params = { obfs: d.obfs }
    else if (d.protocol === 'socks5http') body.params = { username: d.username }
    // vless/tuic 的 uuid 存到 password 字段之外的 params；密码字段按协议复用
    if (d.protocol === 'vless' || d.protocol === 'tuic') {
      body.password = d.uuid // 兼容旧字段，实际用 params.uuid
    }
    if (d.id) await obxPut(`/api/share-servers/${d.id}`, body)
    else await obxPost('/api/share-servers', body)
    dlg.value = null
    await load()
  } catch (e) { dlgErr.value = e instanceof ObxApiError ? e.message : '保存失败' }
  finally { dlgBusy.value = false }
}

async function toggle(s: ShareServer) {
  try { await obxPut(`/api/share-servers/${s.id}`, { enabled: !s.enabled }); await load() }
  catch (e) { err.value = e instanceof ObxApiError ? e.message : '操作失败' }
}

async function remove(s: ShareServer) {
  if (!confirm(t('obx.deleteConfirm'))) return
  try { await obxDel(`/api/share-servers/${s.id}`); await load() }
  catch (e) { err.value = e instanceof ObxApiError ? e.message : '删除失败' }
}

onMounted(load)
</script>
