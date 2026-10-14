<template>
  <div class="uplist">
    <div v-for="(u, i) in model" :key="i" class="uprow">
      <span class="pill" :class="i === 0 ? 'ok' : ''">{{ i === 0 ? '主' : '备' + i }}</span>
      <input :value="u" placeholder="IP / tcp:// / tls:// / https:// / quic://，一行一条"
        @input="set(i, $event.target.value)">
      <span v-if="latency[u] != null" class="muted" style="font-size:12px;white-space:nowrap">{{ latency[u] }} ms</span>
      <button type="button" class="small ghost" @click="$emit('test', u)" :disabled="!String(u || '').trim()">⚡</button>
      <button type="button" class="small danger" @click="remove(i)">删除</button>
    </div>
    <button type="button" class="small ghost" @click="add">+ 添加上游</button>
  </div>
</template>

<script setup>
import { computed } from 'vue'
const props = defineProps({ modelValue: Array, latency: Object })
const emit = defineEmits(['update:modelValue', 'test'])
const model = computed({
  get: () => props.modelValue || [],
  set: v => emit('update:modelValue', v),
})
function set(i, v) {
  const a = [...model.value]; a[i] = v; model.value = a
}
function add() { model.value = [...model.value, ''] }
function remove(i) { model.value = model.value.filter((_, j) => j !== i) }
</script>

<style scoped>
.uplist { display: flex; flex-direction: column; gap: 6px; margin: 4px 0 8px; }
.uprow { display: flex; gap: 8px; align-items: center; }
.uprow input { flex: 1; }
</style>
