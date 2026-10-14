<template>
  <div class="topbar"><h2>内核</h2><span class="sub">sing-box 内核管理</span></div>

  <div class="grid c2">
    <div class="card">
      <h3>服务状态 <span :class="['pill', svc.running ? 'ok' : '']">{{ svc.running ? '运行中' : '已停止' }}</span></h3>
      <dl class="kv">
        <dt>版本</dt><dd>{{ svc.version || '—' }}</dd>
        <dt>PID</dt><dd>{{ svc.pid || '—' }}</dd>
        <dt>平台</dt><dd>{{ svc.platform || '—' }} / {{ svc.arch || '—' }}</dd>
        <dt>系统</dt><dd>{{ svc.os_version || '—' }}</dd>
        <dt>运行</dt><dd>{{ svc.uptime_s != null ? Math.round(svc.uptime_s) + 's' : '—' }}</dd>
        <dt>二进制</dt><dd class="muted">{{ svc.bin_path }}</dd>
        <dt>开机自启</dt><dd>{{ svc.autostart ? '已启用' : '未启用' }}</dd>
        <dt>配置修订</dt><dd>{{ svc.state_rev }} / 已应用 {{ svc.applied_rev || '—' }}
          <span v-if="svc.config_stale" class="pill warn">有未应用更改</span></dd>
      </dl>
      <div style="margin-top:8px">
        <button class="small" @click="svcAct('/api/service/start', '启动')">启动</button>
        <button class="small ghost" @click="svcAct('/api/service/stop', '停止')">停止</button>
        <button class="small ghost" @click="svcAct('/api/service/restart', '重启')">重启</button>
      </div>
    </div>

    <div class="card">
      <h3>配置应用</h3>
      <p class="muted">仅出站变化时尝试热应用（内核原生 PUT /openbox/outbounds），否则完整重启。</p>
      <div class="form-row">
        <div><select v-model="applyMode">
          <option value="auto">自动</option><option value="hot">仅热应用</option><option value="full">完整重启</option>
        </select></div>
        <div style="flex:0"><button @click="applyCfg" :disabled="applying">{{ applying ? '应用中…' : '应用配置' }}</button></div>
      </div>
      <p v-if="applyResult" :class="applyResult.ok ? 'ok-text' : 'danger-text'">{{ applyResult.msg }}</p>
    </div>
  </div>

  <div class="grid c2">
    <div class="card">
      <h3>部署状态</h3>
      <dl class="kv">
        <dt>部署版本</dt><dd>{{ deploy.version || '—' }}</dd>
        <dt>上次部署</dt><dd>{{ deploy.deployed_at || '—' }}</dd>
        <dt>上次回滚</dt><dd>{{ deploy.rolled_back_at || '—' }}</dd>
      </dl>
      <div style="margin-top:8px">
        <button class="small ghost" @click="rollback" :disabled="rolling">
          {{ rolling ? '回滚中…' : '回滚到直连' }}</button>
        <button class="small danger" @click="factoryReset">恢复出厂</button>
      </div>
    </div>

    <div class="card">
      <h3>共享网络 <span class="muted">局域网共享代理入口</span></h3>
      <label><input type="checkbox" v-model="share.enabled" style="width:auto"> 启用（0.0.0.0 监听）</label>
      <div class="form-row" style="margin-top:8px">
        <div><input v-model.number="share.port" type="number" min="1024" max="65535"></div>
        <div style="flex:0"><button class="small" @click="saveShare">保存</button></div>
        <div style="flex:0"><button class="small ghost" @click="checkPort">端口检测</button></div>
      </div>
      <p v-if="portResult" :class="portResult.ok ? 'ok-text' : 'danger-text'">
        {{ portResult.ok ? '端口可用' : portResult.conflicts.join('；') }}</p>
    </div>
  </div>
</template>

<script setup>
import { ref, onMounted, inject } from 'vue'
import { get, post, put } from '../api.js'

const toast = inject('toast')
const svc = ref({}), deploy = ref({})
const applyMode = ref('auto'), applying = ref(false), applyResult = ref(null)
const rolling = ref(false)
const share = ref({ enabled: false, port: 8088 }), portResult = ref(null)

async function load() {
  svc.value = await get('/api/service')
  deploy.value = await get('/api/deploy/state').catch(() => ({}))
  share.value = await get('/api/share-network')
}
async function svcAct(path, label) {
  try { await post(path, {}); toast(label + '已执行'); load() }
  catch (e) { toast(e.message) }
}
async function applyCfg() {
  applying.value = true; applyResult.value = null
  try {
    const r = await post('/api/config/apply?mode=' + applyMode.value, {})
    applyResult.value = { ok: true,
      msg: `已应用（${r.mode === 'hot' ? '热应用' : '完整重启'}）：${r.outbounds} 出站 / ${r.route_rules} 路由规则` }
    load()
  } catch (e) { applyResult.value = { ok: false, msg: e.message } }
  applying.value = false
}
async function rollback() {
  if (!confirm('回滚到直连配置并重启内核？')) return
  rolling.value = true
  try { await post('/api/deploy/rollback', {}); toast('已回滚'); load() }
  catch (e) { toast(e.message) }
  rolling.value = false
}
async function factoryReset() {
  if (!confirm('恢复出厂将清空全部配置！确定？')) return
  if (!confirm('再次确认：所有订阅、节点、站点集都将被删除。')) return
  try { await post('/api/factory-reset', {}); toast('已恢复出厂'); load() }
  catch (e) { toast(e.message) }
}
async function saveShare() {
  try { await put('/api/share-network', share.value); toast('已保存，下次应用生效') }
  catch (e) { toast(e.message) }
}
async function checkPort() {
  try { portResult.value = await get('/api/share-network/port-check?port=' + share.value.port) }
  catch (e) { toast(e.message) }
}

onMounted(load)
</script>
