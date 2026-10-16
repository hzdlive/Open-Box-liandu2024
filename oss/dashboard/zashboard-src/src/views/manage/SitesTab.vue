<!-- Open-Box 二开：目标分流（站点集，自上而下首命中；由旧版自研 UI 移植） -->
<template>
  <div>
    <div class="mb-3 flex items-center justify-between">
      <h2 class="text-lg font-bold">{{ $t('obx.siteSets') }}</h2>
      <button
        class="btn btn-primary btn-sm"
        @click="openAdd"
      >
        {{ $t('obx.addSiteSet') }}
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
            <th>{{ $t('obx.action') }}</th>
            <th>{{ $t('obx.group') }}</th>
            <th>{{ $t('obx.rules') }}</th>
            <th>{{ $t('obx.hotSwitch') }}</th>
            <th class="text-right">{{ $t('obx.actions') }}</th>
          </tr>
        </thead>
        <tbody>
          <tr
            v-for="s in sites"
            :key="s.id"
          >
            <td class="font-medium">{{ s.name }}</td>
            <td>
              <span
                class="badge badge-sm"
                :class="actionCls(s.action)"
              >{{ actionName(s.action) }}</span>
            </td>
            <td>{{ s.action === 'proxy' ? s.group : '—' }}</td>
            <td class="max-w-xs truncate text-sm opacity-70">{{ ruleSummary(s) }}</td>
            <td>
              <div class="join">
                <button
                  class="btn btn-xs join-item"
                  :class="s.flip === 'proxy' ? 'btn-primary' : 'btn-ghost'"
                  @click="flip(s, 'proxy')"
                >{{ $t('obx.flipProxy') }}</button>
                <button
                  class="btn btn-xs join-item"
                  :class="s.flip === 'direct' ? 'btn-primary' : 'btn-ghost'"
                  @click="flip(s, 'direct')"
                >{{ $t('obx.flipDirect') }}</button>
                <button
                  v-if="s.flip"
                  class="btn btn-xs join-item btn-ghost"
                  @click="flip(s, '')"
                >✕</button>
              </div>
            </td>
            <td class="text-right">
              <div class="join">
                <button
                  class="btn btn-ghost btn-xs join-item"
                  @click="move(s, -1)"
                >↑</button>
                <button
                  class="btn btn-ghost btn-xs join-item"
                  @click="move(s, 1)"
                >↓</button>
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
        </tbody>
      </table>
    </div>

    <div
      v-if="dlg"
      class="modal modal-open"
    >
      <div class="modal-box max-w-2xl">
        <h3 class="mb-4 text-lg font-bold">{{ dlg.id ? $t('obx.editSiteSet') : $t('obx.addSiteSet') }}</h3>
        <div class="grid grid-cols-3 gap-3">
          <label class="form-control">
            <span class="label-text mb-1">{{ $t('obx.name') }}</span>
            <input
              v-model="dlg.name"
              class="input input-bordered w-full"
            />
          </label>
          <label class="form-control">
            <span class="label-text mb-1">{{ $t('obx.action') }}</span>
            <select
              v-model="dlg.action"
              class="select select-bordered w-full"
            >
              <option value="proxy">{{ $t('obx.actProxy') }}</option>
              <option value="direct">{{ $t('obx.actDirect') }}</option>
              <option value="reject">{{ $t('obx.actReject') }}</option>
            </select>
          </label>
          <label class="form-control">
            <span class="label-text mb-1">{{ $t('obx.group') }}</span>
            <input
              v-model="dlg.group"
              class="input input-bordered w-full"
              :disabled="dlg.action !== 'proxy'"
            />
          </label>
          <label class="form-control col-span-3">
            <span class="label-text mb-1">{{ $t('obx.domainSuffix') }}</span>
            <textarea
              v-model="dlg.domain_suffix"
              class="textarea textarea-bordered w-full"
              rows="2"
              placeholder="google.com（一行一个）"
            />
          </label>
          <label class="form-control">
            <span class="label-text mb-1">{{ $t('obx.domainExact') }}</span>
            <textarea
              v-model="dlg.domains"
              class="textarea textarea-bordered w-full"
              rows="2"
            />
          </label>
          <label class="form-control">
            <span class="label-text mb-1">{{ $t('obx.domainKeyword') }}</span>
            <textarea
              v-model="dlg.domain_keyword"
              class="textarea textarea-bordered w-full"
              rows="2"
            />
          </label>
          <label class="form-control">
            <span class="label-text mb-1">{{ $t('obx.ipCidr') }}</span>
            <textarea
              v-model="dlg.ip_cidr"
              class="textarea textarea-bordered w-full"
              rows="2"
              placeholder="1.1.1.0/24（一行一个）"
            />
          </label>
          <label class="form-control col-span-3">
            <span class="label-text mb-1">{{ $t('obx.ruleSets') }}</span>
            <input
              v-model="dlg.rule_sets"
              class="input input-bordered w-full"
              placeholder="geosite-youtube, geosite-netflix（逗号分隔）"
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
import { useI18n } from 'vue-i18n'

const { t } = useI18n()

type SiteSet = {
  id: number; name: string; action: string; group: string; flip: string
  rules: { domains: string[]; domain_suffix: string[]; domain_keyword: string[]; ip_cidr: string[] }
  rule_sets: string[]
}

const sites = ref<SiteSet[]>([])
const err = ref('')
const dlg = ref<any>(null)
const dlgErr = ref('')
const dlgBusy = ref(false)

const actionName = (a: string) => ({ proxy: t('obx.actProxy'), direct: t('obx.actDirect'), reject: t('obx.actReject') }[a] || a)
const actionCls = (a: string) => ({ proxy: 'badge-primary', direct: 'badge-success', reject: 'badge-error' }[a] || 'badge-ghost')
function ruleSummary(s: SiteSet) {
  const r = s.rules || {}
  const parts: string[] = []
  const n = (arr?: string[]) => (arr || []).length
  if (n(r.domain_suffix)) parts.push(`${n(r.domain_suffix)} 后缀`)
  if (n(r.domains)) parts.push(`${n(r.domains)} 精确`)
  if (n(r.domain_keyword)) parts.push(`${n(r.domain_keyword)} 关键词`)
  if (n(r.ip_cidr)) parts.push(`${n(r.ip_cidr)} IP段`)
  if ((s.rule_sets || []).length) parts.push(`${s.rule_sets.length} 规则集`)
  return parts.join(' · ') || '—'
}
const lines = (s: string) => s.split('\n').map((x) => x.trim()).filter(Boolean)

async function load() {
  err.value = ''
  try { sites.value = await obxGet<SiteSet[]>('/api/sitesets') }
  catch (e) { err.value = e instanceof ObxApiError ? e.message : '加载失败' }
}
function openAdd() {
  dlgErr.value = ''
  dlg.value = { id: null, name: '', action: 'proxy', group: '所有-自动', domains: '', domain_suffix: '', domain_keyword: '', ip_cidr: '', rule_sets: '' }
}
function openEdit(s: SiteSet) {
  const r = s.rules || {}
  dlgErr.value = ''
  dlg.value = { id: s.id, name: s.name, action: s.action, group: s.group, domains: (r.domains || []).join('\n'), domain_suffix: (r.domain_suffix || []).join('\n'), domain_keyword: (r.domain_keyword || []).join('\n'), ip_cidr: (r.ip_cidr || []).join('\n'), rule_sets: (s.rule_sets || []).join(', ') }
}
async function save() {
  if (!dlg.value?.name.trim()) { dlgErr.value = '名称不能为空'; return }
  const body = { name: dlg.value.name.trim(), action: dlg.value.action, group: dlg.value.group, rules: { domains: lines(dlg.value.domains), domain_suffix: lines(dlg.value.domain_suffix), domain_keyword: lines(dlg.value.domain_keyword), ip_cidr: lines(dlg.value.ip_cidr) }, rule_sets: dlg.value.rule_sets.split(',').map((x: string) => x.trim()).filter(Boolean) }
  dlgBusy.value = true; dlgErr.value = ''
  try {
    if (dlg.value.id) await obxPut(`/api/sitesets/${dlg.value.id}`, body)
    else await obxPost('/api/sitesets', body)
    dlg.value = null; await load()
  } catch (e) { dlgErr.value = e instanceof ObxApiError ? e.message : '保存失败' }
  finally { dlgBusy.value = false }
}
async function remove(s: SiteSet) {
  if (!confirm(`确定删除站点集「${s.name}」吗？`)) return
  try { await obxDel(`/api/sitesets/${s.id}`); await load() }
  catch (e) { err.value = e instanceof ObxApiError ? e.message : '删除失败' }
}
async function move(s: SiteSet, dir: number) {
  const ids = sites.value.map((x) => x.id)
  const i = ids.indexOf(s.id); const j = i + dir
  if (j < 0 || j >= ids.length) return
  ;[ids[i], ids[j]] = [ids[j], ids[i]]
  try { await obxPut('/api/sitesets/order', { order: ids }); await load() }
  catch (e) { err.value = e instanceof ObxApiError ? e.message : '排序失败' }
}
async function flip(s: SiteSet, to: string) {
  try { await obxPost(`/api/sitesets/${s.id}/flip`, { flip: to }); await load() }
  catch (e) { err.value = e instanceof ObxApiError ? e.message : '切换失败' }
}

onMounted(load)
</script>
