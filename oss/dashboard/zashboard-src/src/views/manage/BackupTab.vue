<!-- Open-Box 二开：备份管理。选择性导出/导入（对标原版 behavior-spec §5.8）。 -->
<template>
  <div class="flex flex-col gap-3">
    <div class="rounded-box border border-base-300/30 bg-base-100 p-4">
      <div>
        <h3 class="text-base font-bold">{{ t('obx.backupExport') || '备份导出' }}</h3>
        <p class="text-sm opacity-70">{{ t('obx.backupExportDesc') || '必选分组总是包含，可选分组按需勾选。导出文件不含面板密码。' }}</p>
        <div v-if="loading" class="text-sm opacity-60">加载中…</div>
        <div v-else class="grid grid-cols-2 md:grid-cols-4 gap-2 mt-2">
          <label
            v-for="g in groups"
            :key="g.id"
            class="flex items-center gap-2 p-2 border rounded cursor-pointer"
            :class="{ 'opacity-60': g.required }"
          >
            <input
              type="checkbox"
              class="checkbox checkbox-sm"
              :checked="g.required || selected.includes(g.id)"
              :disabled="g.required"
              @change="toggle(g.id)"
            />
            <span class="text-sm">
              {{ g.description }}
              <span v-if="g.required" class="badge badge-xs badge-ghost ml-1">必选</span>
            </span>
          </label>
        </div>
        <div class="mt-3 flex justify-end gap-2">
          <button class="btn btn-primary btn-sm" :disabled="exporting" @click="doExport">
            {{ exporting ? '导出中…' : (t('obx.backupDownload') || '下载备份') }}
          </button>
        </div>
        <div v-if="err" class="text-error text-sm mt-2">{{ err }}</div>
      </div>
    </div>

    <div class="rounded-box border border-base-300/30 bg-base-100 p-4">
      <div>
        <h3 class="text-base font-bold">{{ t('obx.backupImport') || '备份导入' }}</h3>
        <p class="text-sm opacity-70">{{ t('obx.backupImportDesc') || '选择备份文件恢复。导入后建议重启内核。' }}</p>
        <input
          ref="fileInput"
          type="file"
          accept=".json,application/json"
          class="file-input file-input-sm file-input-bordered w-full max-w-md mt-2"
          @change="onFile"
        />
        <div class="mt-3 flex justify-end gap-2">
          <button class="btn btn-warning btn-sm" :disabled="!file || importing" @click="doImport">
            {{ importing ? '导入中…' : (t('obx.backupRestore') || '恢复备份') }}
          </button>
        </div>
        <div v-if="importResult" class="text-sm mt-2">
          <span class="text-success">恢复成功：</span>
          <span v-for="(c, k) in importResult.counts" :key="k" class="badge badge-ghost badge-sm mr-1">{{ k }}: {{ c }}</span>
        </div>
        <div v-if="importErr" class="text-error text-sm mt-2">{{ importErr }}</div>
      </div>
    </div>
  </div>
</template>

<script setup lang="ts">
import { ref, onMounted } from 'vue'
import { useI18n } from 'vue-i18n'
import { obxGet, obxPost } from '@/openbox/api'

const { t } = useI18n()

interface BackupGroup {
  id: string
  required: boolean
  description: string
  tables: string[]
}

const groups = ref<BackupGroup[]>([])
const selected = ref<string[]>([])
const loading = ref(true)
const exporting = ref(false)
const err = ref('')
const file = ref<File | null>(null)
const fileInput = ref<HTMLInputElement | null>(null)
const importing = ref(false)
const importResult = ref<any>(null)
const importErr = ref('')

async function loadGroups() {
  loading.value = true
  try {
    const r = await obxGet<{ groups: BackupGroup[] }>('/api/backup/groups')
    groups.value = r.groups || []
    // 默认选中所有可选分组
    selected.value = groups.value.filter(g => !g.required).map(g => g.id)
  } catch (e: any) {
    err.value = e.message || '加载失败'
  } finally {
    loading.value = false
  }
}

function toggle(id: string) {
  const i = selected.value.indexOf(id)
  if (i >= 0) selected.value.splice(i, 1)
  else selected.value.push(id)
}

async function doExport() {
  exporting.value = true
  err.value = ''
  try {
    // 必选分组后端自动包含，这里只传可选的选中项
    const optional = groups.value.filter(g => !g.required).map(g => g.id)
    const qs = selected.value.filter(id => optional.includes(id)).join(',')
    const url = qs ? `/api/backup?groups=${encodeURIComponent(qs)}` : '/api/backup'
    const res = await fetch(url, { credentials: 'include' })
    if (!res.ok) throw new Error(`导出失败: ${res.status}`)
    const blob = await res.blob()
    const a = document.createElement('a')
    a.href = URL.createObjectURL(blob)
    a.download = `openbox-backup-${new Date().toISOString().slice(0, 10)}.json`
    a.click()
    URL.revokeObjectURL(a.href)
  } catch (e: any) {
    err.value = e.message || '导出失败'
  } finally {
    exporting.value = false
  }
}

function onFile(e: Event) {
  const input = e.target as HTMLInputElement
  file.value = input.files?.[0] || null
  importResult.value = null
  importErr.value = ''
}

async function doImport() {
  if (!file.value) return
  importing.value = true
  importErr.value = ''
  importResult.value = null
  try {
    const text = await file.value.text()
    const data = JSON.parse(text)
    const r = await obxPost<any>('/api/backup', data)
    importResult.value = r
  } catch (e: any) {
    importErr.value = e.message || '导入失败'
  } finally {
    importing.value = false
  }
}

onMounted(loadGroups)
</script>
