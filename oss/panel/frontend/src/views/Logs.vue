<template>
  <div class="topbar"><h2>日志</h2></div>
  <div class="tabs">
    <button :class="{ active: source === 'kernel' }" @click="setSource('kernel')">内核</button>
    <button :class="{ active: source === 'panel' }" @click="setSource('panel')">面板</button>
  </div>
  <div class="card">
    <div style="margin-bottom:8px">
      <button class="small ghost" @click="load">刷新</button>
      <input v-model="filter" placeholder="过滤关键字" style="max-width:240px;margin-left:8px">
      <select v-model.number="n" style="max-width:120px;margin-left:8px" @change="load">
        <option :value="200">200 行</option><option :value="500">500 行</option><option :value="2000">2000 行</option>
      </select>
    </div>
    <p v-if="note" class="muted">{{ note }}</p>
    <pre class="code">{{ filtered.join('\n') || '(空)' }}</pre>
  </div>
</template>

<script setup>
import { ref, computed, onMounted, inject } from 'vue'
import { get } from '../api.js'

const toast = inject('toast')
const source = ref('kernel')
const lines = ref([]), note = ref('')
const filter = ref(''), n = ref(200)

const filtered = computed(() => {
  const f = filter.value.trim()
  if (!f) return lines.value
  return lines.value.filter(l => l.includes(f))
})

function setSource(s) { source.value = s; load() }
async function load() {
  try {
    const r = await get(`/api/service/log?n=${n.value}&source=${source.value}`)
    lines.value = r.log || []
    note.value = r.note || ''
  } catch (e) { toast(e.message) }
}

onMounted(load)
</script>
