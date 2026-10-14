<template>
  <div class="topbar"><h2>链式代理</h2><span class="sub">出口再套一层代理</span></div>

  <div class="card">
    <table>
      <tr><th>名称</th><th>出口协议</th><th>服务器</th><th>前置</th><th></th></tr>
      <tr v-for="c in chains" :key="c.id">
        <td>{{ c.name }}</td><td>{{ c.exit_protocol }}</td>
        <td class="muted">{{ c.server }}:{{ c.port }}</td>
        <td class="muted">{{ (c.front || []).join(' → ') || '—' }}</td>
        <td>
          <button class="small ghost" @click="edit(c)">编辑</button>
          <button class="small danger" @click="del(c)">删除</button>
        </td>
      </tr>
    </table>
  </div>

  <div class="card">
    <h3>{{ editing ? '编辑' : '新建' }}链式代理</h3>
    <form @submit.prevent="save">
      <div class="form-row">
        <div><label>名称</label><input v-model="f.name" required></div>
        <div><label>出口协议</label><select v-model="f.exit_protocol">
          <option value="socks">socks</option><option value="http">http</option>
        </select></div>
      </div>
      <div class="form-row">
        <div><label>服务器</label><input v-model="f.server" required></div>
        <div><label>端口</label><input v-model.number="f.port" type="number" required></div>
      </div>
      <label>前置（逗号分隔的节点组/节点标签，按顺序经过）</label>
      <input v-model="f.front" placeholder="auto, 香港节点">
      <div style="margin-top:8px">
        <button>{{ editing ? '保存' : '创建' }}</button>
        <button v-if="editing" type="button" class="ghost" @click="reset">取消</button>
      </div>
    </form>
  </div>
</template>

<script setup>
import { ref, onMounted, inject } from 'vue'
import { get, post, put, delReq } from '../api.js'

const toast = inject('toast')
const chains = ref([])
const editing = ref(null)
const f = ref({ name: '', exit_protocol: 'socks', server: '', port: 1080, front: '' })

async function load() { chains.value = await get('/api/chains') }
function reset() {
  editing.value = null
  f.value = { name: '', exit_protocol: 'socks', server: '', port: 1080, front: '' }
}
function edit(c) {
  editing.value = c.id
  f.value = { name: c.name, exit_protocol: c.exit_protocol, server: c.server,
              port: c.port, front: (c.front || []).join(', ') }
}
async function save() {
  const body = { name: f.value.name, exit_protocol: f.value.exit_protocol,
    server: f.value.server, port: f.value.port,
    front: f.value.front.split(',').map(x => x.trim()).filter(Boolean) }
  try {
    if (editing.value) await put('/api/chains/' + editing.value, body)
    else await post('/api/chains', body)
    toast('已保存'); reset(); load()
  } catch (e) { toast(e.message) }
}
async function del(c) {
  if (!confirm(`删除 ${c.name}？`)) return
  try { await delReq('/api/chains/' + c.id); toast('已删除'); load() }
  catch (e) { toast(e.message) }
}

onMounted(load)
</script>
