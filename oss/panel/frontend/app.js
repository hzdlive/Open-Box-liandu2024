'use strict';
/* OpenBox-OSS panel frontend. No build step, no dependencies. */

const $ = (s, el = document) => el.querySelector(s);
const esc = s => String(s ?? '').replace(/[&<>"']/g, c =>
  ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' }[c]));
const lines = s => String(s || '').split('\n').map(x => x.trim()).filter(Boolean);

async function api(method, path, body) {
  const r = await fetch('/api' + path, {
    method, headers: { 'Content-Type': 'application/json' },
    body: body ? JSON.stringify(body) : undefined,
  });
  const data = await r.json().catch(() => ({}));
  if (!r.ok) throw new Error(data.error || ('HTTP ' + r.status));
  return data;
}
const get = p => api('GET', p);
const post = (p, b) => api('POST', p, b);
const put = (p, b) => api('PUT', p, b);
const delReq = p => api('DELETE', p);

let toastTimer = null;
function toast(msg, ok = true) {
  const t = $('#toast');
  t.textContent = msg;
  t.style.borderColor = ok ? 'var(--line)' : 'var(--red)';
  t.hidden = false;
  clearTimeout(toastTimer);
  toastTimer = setTimeout(() => { t.hidden = true; }, 2600);
}

const NAV = [
  ['', '概览'], ['proxy', '代理'], ['subs', '订阅'], ['sites', '站点集'],
  ['rulesets', '规则集'], ['chains', '链式代理'], ['debug', '规则调试'],
  ['settings', '设置'], ['config', '配置'],
];

function renderNav(active) {
  $('#nav').innerHTML = NAV.map(([h, label]) =>
    `<a href="#/${h}" class="${h === active ? 'active' : ''}">${label}</a>`).join('');
}

function healthPill(h) {
  if (h.ok === true) return `<span class="pill ok">${esc(h.latency_ms)} ms</span>`;
  if (h.ok === false) return `<span class="pill bad">不通</span>`;
  return `<span class="pill skip">跳过</span>`;
}
function actionPill(a) {
  const m = { proxy: '代理', direct: '直连', reject: '拒绝' };
  return `<span class="pill ${a}">${m[a] || esc(a)}</span>`;
}

/* ---------- 概览 ---------- */
async function vOverview() {
  const [st, health] = await Promise.all([get('/status'), get('/health')]);
  const okCount = health.filter(h => h.ok === true).length;
  const card = (n, l) => `<div class="card"><div class="num">${n}</div><div class="lbl">${l}</div></div>`;
  $('#view').innerHTML = `
    <h2>概览</h2>
    <div class="cards">
      ${card(st.nodes, '节点')}${card(st.subscriptions, '订阅')}
      ${card(st.site_sets, '站点集')}${card(st.groups, '节点组')}
      ${card(okCount + ' / ' + health.length, '健康检查通过')}
    </div>
    <h3>节点健康</h3>
    ${health.length ? `<table><tr><th>节点</th><th>状态</th><th>检查时间</th></tr>
      ${health.map(h => `<tr><td>${esc(h.tag)}</td><td>${healthPill(h)}</td><td class="muted">${esc(h.checked_at)}</td></tr>`).join('')}
      </table>` : '<p class="muted">暂无数据，去「代理」页执行健康检查。</p>'}
    <p class="muted">版本 ${esc(st.version)} · sing-box 内核：${esc(st.singbox)}</p>`;
}

/* ---------- 代理 ---------- */
async function vProxy() {
  const [nodes, health, groups] = await Promise.all(
    [get('/nodes'), get('/health'), get('/groups')]);
  const hm = Object.fromEntries(health.map(h => [h.tag, h]));
  $('#view').innerHTML = `
    <h2>代理</h2>
    <div><button id="btn-health">检查健康</button>
      <span class="muted">TCP 连通 + TLS 握手延迟；UDP 协议会标记为跳过</span></div>
    <h3>节点（${nodes.length}）</h3>
    <table><tr><th>标签</th><th>协议</th><th>服务器</th><th>健康</th></tr>
    ${nodes.map(n => `<tr><td>${esc(n.tag)}</td><td>${esc(n.protocol)}</td>
      <td class="muted">${esc(n.server)}:${n.port}</td>
      <td>${hm[n.tag] ? healthPill(hm[n.tag]) : '<span class="muted">—</span>'}</td></tr>`).join('')}
    </table>
    <h3>节点组</h3>
    <div class="grid2">${groups.map(g => `<div class="card">
      <div><b>${esc(g.name)}</b> <span class="muted">${esc(g.type)}</span></div>
      <div class="muted">成员: ${g.members.length ? esc(g.members.join(', ')) : '—'}</div>
      <div class="muted">关键词: ${g.dynamic_keywords.length ? esc(g.dynamic_keywords.join(', ')) : '—'}</div>
      <div><button class="small danger" data-del-group="${g.id}">删除</button></div>
    </div>`).join('')}</div>
    <form class="panel" id="f-group"><h3>新建节点组</h3>
      <div class="row">
        <div><label>名称</label><input type="text" name="name" required></div>
        <div><label>类型</label><select name="type"><option value="urltest">自动择优 (urltest)</option><option value="selector">手动选择 (selector)</option></select></div>
      </div>
      <label>成员标签（逗号分隔；*nodes* = 全部节点，*all* = 节点+链式代理）</label>
      <input type="text" name="members" placeholder="*nodes*">
      <label>动态关键词（逗号分隔，标签含关键词自动收编）</label>
      <input type="text" name="dynamic_keywords" placeholder="香港, HK">
      <div><button>创建</button></div>
    </form>`;
  $('#btn-health').onclick = async () => {
    toast('检查中…');
    try { await post('/health/check', {}); toast('检查完成'); vProxy(); }
    catch (e) { toast(e.message, false); }
  };
  $('#f-group').onsubmit = async e => {
    e.preventDefault();
    const f = new FormData(e.target);
    try {
      await post('/groups', {
        name: f.get('name').trim(), type: f.get('type'),
        members: String(f.get('members')).split(',').map(s => s.trim()).filter(Boolean),
        dynamic_keywords: String(f.get('dynamic_keywords')).split(',').map(s => s.trim()).filter(Boolean),
      });
      toast('已创建'); vProxy();
    } catch (err) { toast(err.message, false); }
  };
  $('#view').querySelectorAll('[data-del-group]').forEach(b => b.onclick = async () => {
    if (!confirm('删除该节点组？')) return;
    try { await delReq('/groups/' + b.dataset.delGroup); toast('已删除'); vProxy(); }
    catch (e) { toast(e.message, false); }
  });
}

/* ---------- 订阅 ---------- */
async function vSubs() {
  const subs = await get('/subscriptions');
  $('#view').innerHTML = `
    <h2>订阅</h2>
    <table><tr><th>名称</th><th>节点数</th><th>创建时间</th><th></th></tr>
    ${subs.map(s => `<tr><td>${esc(s.name)}</td><td>${s.node_count}</td>
      <td class="muted">${esc(s.created_at)}</td>
      <td><button class="small danger" data-del="${s.id}">删除</button></td></tr>`).join('')}
    </table>
    <form class="panel" id="f-sub"><h3>添加订阅</h3>
      <div class="row">
        <div><label>名称</label><input type="text" name="name" required></div>
        <div><label>格式</label><select name="format">
          <option value="auto">自动识别</option><option value="links">分享链接</option><option value="clash">Clash YAML</option>
        </select></div>
      </div>
      <label>订阅内容（粘贴 base64 订阅 / 链接列表 / Clash YAML）</label>
      <textarea name="content" rows="8" required></textarea>
      <div><button>解析并导入</button></div>
    </form>`;
  $('#f-sub').onsubmit = async e => {
    e.preventDefault();
    const f = new FormData(e.target);
    try {
      const r = await post('/subscriptions', {
        name: f.get('name').trim(), content: f.get('content'), format: f.get('format') });
      toast(`已导入 ${r.node_count} 个节点`); vSubs();
    } catch (err) { toast(err.message, false); }
  };
  $('#view').querySelectorAll('[data-del]').forEach(b => b.onclick = async () => {
    if (!confirm('删除该订阅及其节点？')) return;
    try { await delReq('/subscriptions/' + b.dataset.del); toast('已删除'); vSubs(); }
    catch (e) { toast(e.message, false); }
  });
}

/* ---------- 站点集 ---------- */
function rulesSummary(r) {
  const parts = [];
  if (r.domains?.length) parts.push(`域名×${r.domains.length}`);
  if (r.domain_suffix?.length) parts.push(`后缀×${r.domain_suffix.length}`);
  if (r.domain_keyword?.length) parts.push(`关键词×${r.domain_keyword.length}`);
  if (r.ip_cidr?.length) parts.push(`IP段×${r.ip_cidr.length}`);
  if (r.rule_sets?.length) parts.push(`规则集: ${r.rule_sets.join(',')}`);
  return parts.join(' · ') || '<span class="muted">空</span>';
}
async function vSites() {
  const [sets, groups] = await Promise.all([get('/sitesets'), get('/groups')]);
  const groupOpts = groups.map(g => `<option>${esc(g.name)}</option>`).join('');
  $('#view').innerHTML = `
    <h2>站点集 <span class="muted">自上而下匹配，先命中先生效</span></h2>
    <table><tr><th>名称</th><th>动作</th><th>出口组</th><th>规则</th><th></th></tr>
    ${sets.map(s => `<tr><td>${esc(s.name)}</td><td>${actionPill(s.action)}</td>
      <td>${esc(s.group)}</td><td class="muted">${rulesSummary(s.rules)}</td>
      <td><button class="small ghost" data-edit="${s.id}">编辑</button>
          <button class="small danger" data-del="${s.id}">删除</button></td></tr>`).join('')}
    </table>
    <form class="panel" id="f-site"><h3 id="f-site-title">新建站点集</h3>
      <input type="hidden" name="id">
      <div class="row">
        <div><label>名称</label><input type="text" name="name" required></div>
        <div><label>动作</label><select name="action">
          <option value="proxy">代理</option><option value="direct">直连</option><option value="reject">拒绝</option>
        </select></div>
      </div>
      <label>出口组（动作为代理时）</label><select name="group">${groupOpts}</select>
      <div class="row">
        <div><label>精确域名（每行一个）</label><textarea name="domains" rows="4"></textarea></div>
        <div><label>域名后缀（每行一个）</label><textarea name="domain_suffix" rows="4"></textarea></div>
      </div>
      <div class="row">
        <div><label>关键词（每行一个）</label><textarea name="domain_keyword" rows="4"></textarea></div>
        <div><label>IP 段 CIDR（每行一个）</label><textarea name="ip_cidr" rows="4"></textarea></div>
      </div>
      <label>引用规则集（逗号分隔名称）</label><input type="text" name="rule_sets">
      <div><button>保存</button> <button type="button" class="ghost" id="f-reset">重置</button></div>
    </form>`;
  const fill = s => {
    const f = $('#f-site');
    const set = (n, v) => { const el = f.querySelector(`[name="${n}"]`); if (el) el.value = v; };
    set('id', s.id); set('name', s.name); set('action', s.action); set('group', s.group);
    set('domains', (s.rules.domains || []).join('\n'));
    set('domain_suffix', (s.rules.domain_suffix || []).join('\n'));
    set('domain_keyword', (s.rules.domain_keyword || []).join('\n'));
    set('ip_cidr', (s.rules.ip_cidr || []).join('\n'));
    set('rule_sets', (s.rules.rule_sets || []).join(','));
    $('#f-site-title').textContent = '编辑站点集';
    f.scrollIntoView();
  };
  $('#view').querySelectorAll('[data-edit]').forEach(b => b.onclick = async () => {
    const s = sets.find(x => String(x.id) === b.dataset.edit);
    if (s) fill(s);
  });
  $('#f-reset').onclick = () => { const f = $('#f-site'); f.reset(); f.querySelector('[name="id"]').value = ''; $('#f-site-title').textContent = '新建站点集'; };
  $('#f-site').onsubmit = async e => {
    e.preventDefault();
    const f = new FormData(e.target);
    const body = {
      name: f.get('name').trim(), action: f.get('action'), group: f.get('group'),
      rules: {
        domains: lines(f.get('domains')), domain_suffix: lines(f.get('domain_suffix')),
        domain_keyword: lines(f.get('domain_keyword')), ip_cidr: lines(f.get('ip_cidr')),
        rule_sets: String(f.get('rule_sets')).split(',').map(s => s.trim()).filter(Boolean),
      },
    };
    try {
      if (f.get('id')) await put('/sitesets/' + f.get('id'), body);
      else await post('/sitesets', body);
      toast('已保存'); vSites();
    } catch (err) { toast(err.message, false); }
  };
  $('#view').querySelectorAll('[data-del]').forEach(b => b.onclick = async () => {
    if (!confirm('删除该站点集？')) return;
    try { await delReq('/sitesets/' + b.dataset.del); toast('已删除'); vSites(); }
    catch (e) { toast(e.message, false); }
  });
}

/* ---------- 规则集 ---------- */
async function vRulesets() {
  const list = await get('/rulesets');
  $('#view').innerHTML = `
    <h2>规则集</h2>
    <table><tr><th>名称</th><th>URL</th><th>格式</th><th>更新时间</th><th></th></tr>
    ${list.map(r => `<tr><td>${esc(r.name)}</td><td class="muted">${esc(r.url) || '—'}</td>
      <td>${esc(r.format)}</td><td class="muted">${esc(r.updated_at) || '—'}</td>
      <td><button class="small ghost" data-refresh="${r.id}">刷新</button>
          <button class="small danger" data-del="${r.id}">删除</button></td></tr>`).join('')}
    </table>
    <form class="panel" id="f-rs"><h3>添加规则集</h3>
      <div class="row">
        <div><label>名称</label><input type="text" name="name" required></div>
        <div><label>格式</label><select name="format">
          <option value="auto">自动识别</option><option value="clash-classical">Clash classical</option><option value="domain-list">纯域名列表</option>
        </select></div>
      </div>
      <label>URL（留空则仅本地占位）</label><input type="text" name="url" placeholder="https://…">
      <div><button>添加</button></div>
    </form>`;
  $('#f-rs').onsubmit = async e => {
    e.preventDefault();
    const f = new FormData(e.target);
    try {
      await post('/rulesets', { name: f.get('name').trim(), url: f.get('url').trim(), format: f.get('format') });
      toast('已添加'); vRulesets();
    } catch (err) { toast(err.message, false); }
  };
  $('#view').querySelectorAll('[data-refresh]').forEach(b => b.onclick = async () => {
    toast('抓取中…');
    try { await post(`/rulesets/${b.dataset.refresh}/refresh`, {}); toast('已刷新'); vRulesets(); }
    catch (e) { toast(e.message, false); }
  });
  $('#view').querySelectorAll('[data-del]').forEach(b => b.onclick = async () => {
    if (!confirm('删除该规则集？')) return;
    try { await delReq('/rulesets/' + b.dataset.del); toast('已删除'); vRulesets(); }
    catch (e) { toast(e.message, false); }
  });
}

/* ---------- 链式代理 ---------- */
async function vChains() {
  const [chains, groups, nodes] = await Promise.all(
    [get('/chains'), get('/groups'), get('/nodes')]);
  const frontOpts = [...groups.map(g => g.name), ...nodes.map(n => n.tag)]
    .map(t => `<option>${esc(t)}</option>`).join('');
  $('#view').innerHTML = `
    <h2>链式代理 <span class="muted">出口经前置节点/组中转</span></h2>
    <table><tr><th>名称</th><th>出口</th><th>前置</th><th></th></tr>
    ${chains.map(c => `<tr><td>${esc(c.name)}</td>
      <td class="muted">${esc(c.exit_protocol)}://${esc(c.server)}:${c.port}</td>
      <td>${esc(c.front)}</td>
      <td><button class="small danger" data-del="${c.id}">删除</button></td></tr>`).join('')}
    </table>
    <form class="panel" id="f-chain"><h3>新建链式代理</h3>
      <div class="row">
        <div><label>名称</label><input type="text" name="name" required></div>
        <div><label>出口协议</label><select name="exit_protocol">
          <option value="socks">socks5</option><option value="http">http/https</option></select></div>
      </div>
      <div class="row">
        <div><label>出口服务器</label><input type="text" name="server" required></div>
        <div><label>端口</label><input type="number" name="port" required></div>
      </div>
      <div class="row">
        <div><label>用户名（可选）</label><input type="text" name="username"></div>
        <div><label>密码（可选）</label><input type="password" name="password"></div>
      </div>
      <label>前置节点/组</label><select name="front">${frontOpts}</select>
      <div><button>创建</button></div>
    </form>`;
  $('#f-chain').onsubmit = async e => {
    e.preventDefault();
    const f = new FormData(e.target);
    try {
      await post('/chains', {
        name: f.get('name').trim(), exit_protocol: f.get('exit_protocol'),
        server: f.get('server').trim(), port: Number(f.get('port')),
        params: { username: f.get('username').trim(), password: f.get('password') },
        front: f.get('front'),
      });
      toast('已创建'); vChains();
    } catch (err) { toast(err.message, false); }
  };
  $('#view').querySelectorAll('[data-del]').forEach(b => b.onclick = async () => {
    if (!confirm('删除该链式代理？')) return;
    try { await delReq('/chains/' + b.dataset.del); toast('已删除'); vChains(); }
    catch (e) { toast(e.message, false); }
  });
}

/* ---------- 规则调试 ---------- */
async function vDebug() {
  $('#view').innerHTML = `
    <h2>规则调试 <span class="muted">输入域名或 IP，预览按哪条规则走</span></h2>
    <form class="panel" id="f-debug">
      <label>目标</label>
      <input type="text" name="target" placeholder="www.youtube.com 或 8.8.8.8" required>
      <div><button>预览路由</button></div>
    </form>
    <div id="dbg-result"></div>`;
  $('#f-debug').onsubmit = async e => {
    e.preventDefault();
    const target = new FormData(e.target).get('target').trim();
    try {
      const r = await post('/route/preview', { target });
      $('#dbg-result').innerHTML = `<div class="result">
        <div class="big">${esc(target)}</div>
        <p>命中站点集：<b>${r.site_set ? esc(r.site_set) : '（无，按兜底）'}</b></p>
        <p>动作：${actionPill(r.action)}　出口：<span class="pill proxy">${esc(r.outbound)}</span></p>
      </div>`;
    } catch (err) { toast(err.message, false); }
  };
}

/* ---------- 设置 ---------- */
async function vSettings() {
  const s = await get('/settings');
  $('#view').innerHTML = `
    <h2>设置</h2>
    <form class="panel" id="f-settings">
      <div class="row">
        <div><label>直连 DNS</label><input type="text" name="dns_direct" value="${esc(s.dns_direct)}"></div>
        <div><label>代理 DNS</label><input type="text" name="dns_proxy" value="${esc(s.dns_proxy)}"></div>
      </div>
      <div class="row">
        <div><label>兜底出口</label><input type="text" name="final_outbound" value="${esc(s.final_outbound)}"></div>
        <div><label>TUN 协议栈</label><select name="tun_stack">
          ${['mixed', 'gvisor', 'system'].map(v =>
            `<option value="${v}"${s.tun_stack === v ? ' selected' : ''}>${v}</option>`).join('')}
        </select></div>
      </div>
      <div><button>保存</button></div>
    </form>`;
  $('#f-settings').onsubmit = async e => {
    e.preventDefault();
    const f = new FormData(e.target);
    try {
      await put('/settings', {
        dns_direct: f.get('dns_direct').trim(), dns_proxy: f.get('dns_proxy').trim(),
        final_outbound: f.get('final_outbound').trim(), tun_stack: f.get('tun_stack'),
      });
      toast('已保存');
    } catch (err) { toast(err.message, false); }
  };
}

/* ---------- 配置 ---------- */
async function vConfig() {
  const conf = await get('/config');
  const text = JSON.stringify(conf, null, 2);
  $('#view').innerHTML = `
    <h2>生成的 sing-box 配置</h2>
    <div><button id="btn-copy">复制</button><button id="btn-dl" class="ghost">下载 config.json</button></div>
    <pre class="cfg" id="cfg-pre"></pre>`;
  $('#cfg-pre').textContent = text;
  $('#btn-copy').onclick = async () => {
    try { await navigator.clipboard.writeText(text); toast('已复制'); }
    catch (e) { toast('复制失败', false); }
  };
  $('#btn-dl').onclick = () => {
    const a = document.createElement('a');
    a.href = URL.createObjectURL(new Blob([text], { type: 'application/json' }));
    a.download = 'config.json';
    a.click();
  };
}

/* ---------- 路由 ---------- */
const ROUTES = {
  '': vOverview, 'proxy': vProxy, 'subs': vSubs, 'sites': vSites,
  'rulesets': vRulesets, 'chains': vChains, 'debug': vDebug,
  'settings': vSettings, 'config': vConfig,
};
async function navigate() {
  const h = location.hash.replace(/^#\/?/, '').split('?')[0] || '';
  renderNav(h);
  $('#view').innerHTML = '<p class="muted">加载中…</p>';
  try {
    await (ROUTES[h] || vOverview)();
  } catch (e) {
    $('#view').innerHTML = `<p class="muted">加载失败：${esc(e.message)}</p>`;
  }
  window.scrollTo(0, 0);
}
window.addEventListener('hashchange', navigate);
navigate();
