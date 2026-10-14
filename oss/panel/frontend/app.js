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
  ['dns', 'DNS'], ['conns', '连接'], ['terminals', '终端'],
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
  const [st, health, svc] = await Promise.all(
    [get('/status'), get('/health'), get('/service')]);
  const okCount = health.filter(h => h.ok === true).length;
  const card = (n, l) => `<div class="card"><div class="num">${n}</div><div class="lbl">${l}</div></div>`;
  const svcPill = svc.running ? '<span class="pill ok">运行中</span>'
    : svc.installed ? '<span class="pill skip">已安装·未运行</span>'
    : '<span class="pill bad">未安装</span>';
  $('#view').innerHTML = `
    <h2>概览</h2>
    <div class="cards">
      ${card(st.nodes, '节点')}${card(st.subscriptions, '订阅')}
      ${card(st.site_sets, '站点集')}${card(st.groups, '节点组')}
      ${card(okCount + ' / ' + health.length, '健康检查通过')}
    </div>
    <h3>内核服务 ${svcPill}</h3>
    <div class="card">
      <div class="muted">版本 ${esc(svc.version || '—')} · PID ${svc.pid || '—'} ·
        运行 ${svc.uptime_s != null ? Math.round(svc.uptime_s) + 's' : '—'} ·
        二进制 ${esc(svc.bin_path)}</div>
      <div>
        <button class="small" id="svc-start">启动</button>
        <button class="small ghost" id="svc-stop">停止</button>
        <button class="small ghost" id="svc-restart">重启</button>
        <button class="small" id="svc-apply">应用配置</button>
        <button class="small ghost" id="svc-log">查看日志</button>
      </div>
      <pre class="cfg" id="svc-log-pre" hidden style="max-height:30vh"></pre>
    </div>
    <h3>节点健康</h3>
    ${health.length ? `<table><tr><th>节点</th><th>状态</th><th>检查时间</th></tr>
      ${health.map(h => `<tr><td>${esc(h.tag)}</td><td>${healthPill(h)}</td><td class="muted">${esc(h.checked_at)}</td></tr>`).join('')}
      </table>` : '<p class="muted">暂无数据，去「代理」页执行健康检查。</p>'}
    <p class="muted">版本 ${esc(st.version)} · sing-box 内核：${esc(st.singbox)}</p>`;
  const svcAct = async (path, label) => {
    try { await post(path, {}); toast(label + '已执行'); vOverview(); }
    catch (e) { toast(e.message, false); }
  };
  $('#svc-start').onclick = () => svcAct('/service/start', '启动');
  $('#svc-stop').onclick = () => svcAct('/service/stop', '停止');
  $('#svc-restart').onclick = () => svcAct('/service/restart', '重启');
  $('#svc-apply').onclick = async () => {
    try {
      const r = await post('/config/apply', {});
      toast(`已应用：${r.outbounds} 出站 / ${r.route_rules} 路由规则`);
      vOverview();
    } catch (e) { toast(e.message, false); }
  };
  $('#svc-log').onclick = async () => {
    const pre = $('#svc-log-pre');
    try {
      const r = await get('/service/log?n=100');
      pre.textContent = r.log || '(空)';
      pre.hidden = !pre.hidden;
    } catch (e) { toast(e.message, false); }
  };
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
    <table><tr><th></th><th>标签</th><th>协议</th><th>服务器</th><th>健康</th></tr>
    ${nodes.map(n => `<tr><td><input type="checkbox" data-share-tag="${esc(n.tag)}"></td>
      <td>${esc(n.tag)}</td><td>${esc(n.protocol)}</td>
      <td class="muted">${esc(n.server)}:${n.port}</td>
      <td>${hm[n.tag] ? healthPill(hm[n.tag]) : '<span class="muted">—</span>'}</td></tr>`).join('')}
    </table>
    <div><button id="btn-share">生成分享链接</button>
      <span class="muted">勾选节点后生成 vmess/vless/trojan/ss 链接 + 二维码</span></div>
    <div id="share-result"></div>
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
        <div><label>类型</label><select name="type"><option value="urltest">自动择优 (urltest)</option><option value="selector">手动选择 (selector)</option><option value="failover">故障转移 (failover)</option></select></div>
      </div>
      <label>成员标签（逗号分隔；*nodes* = 全部节点，*all* = 节点+链式代理）</label>
      <input type="text" name="members" placeholder="*nodes*">
      <label>动态关键词（逗号分隔，标签含关键词自动收编）</label>
      <input type="text" name="dynamic_keywords" placeholder="香港, HK">
      <div><button>创建</button></div>
    </form>`;
  $('#btn-share').onclick = async () => {
    const tags = [...$('#view').querySelectorAll('[data-share-tag]:checked')]
      .map(el => el.dataset.shareTag);
    if (!tags.length) { toast('请先勾选节点', false); return; }
    try {
      const items = await post('/share', { node_tags: tags });
      $('#share-result').innerHTML = items.map(it => it.link ? `
        <div class="result">
          <div><b>${esc(it.tag)}</b></div>
          <div class="grid2">
            <div><textarea rows="4" readonly>${esc(it.link)}</textarea>
              <div><button class="small" data-copy="${esc(it.link)}">复制链接</button></div></div>
            <div><img src="/api/share/qr?text=${encodeURIComponent(it.link)}"
                 alt="QR" style="width:160px;height:160px;background:#fff;padding:8px;border-radius:8px"></div>
          </div>
        </div>` : `
        <div class="result"><b>${esc(it.tag)}</b>
          <span class="pill bad">${esc(it.error)}</span></div>`).join('');
      $('#share-result').querySelectorAll('[data-copy]').forEach(b => b.onclick = async () => {
        try { await navigator.clipboard.writeText(b.dataset.copy); toast('已复制'); }
        catch (e) { toast('复制失败', false); }
      });
    } catch (e) { toast(e.message, false); }
  };
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
    <table><tr><th>名称</th><th>动作</th><th>当前出口</th><th>出口组</th><th>规则</th><th></th></tr>
    ${sets.map(s => {
      const eff = s.flip || s.action;
      const flipBtn = s.action === 'reject' ? '<span class="muted">—</span>'
        : `<button class="small ghost" data-flip="${s.id}" data-to="${eff === 'direct' ? 'proxy' : 'direct'}"
            title="不重启内核切换">切${eff === 'direct' ? '代理' : '直连'}</button>`;
      return `<tr><td>${esc(s.name)}</td><td>${actionPill(s.action)}</td>
      <td>${actionPill(eff)}${s.flip ? ' <span class="muted" title="热切换状态">(热切)</span>' : ''}</td>
      <td>${esc(s.group)}</td><td class="muted">${rulesSummary(s.rules)}</td>
      <td>${flipBtn} <button class="small ghost" data-edit="${s.id}">编辑</button>
          <button class="small danger" data-del="${s.id}">删除</button></td></tr>`;
    }).join('')}
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
  $('#view').querySelectorAll('[data-flip]').forEach(b => b.onclick = async () => {
    try {
      const r = await post('/sitesets/' + b.dataset.flip + '/flip', { to: b.dataset.to });
      toast(r.hot ? '已热切换（内核未重启）' : '已保存，下次应用配置生效'); vSites();
    } catch (e) { toast(e.message, false); }
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
      <div><button>预览路由</button>
        <button type="button" id="btn-penetrate" class="ghost">域名穿透</button></div>
    </form>
    <div id="dbg-result"></div>
    <h3>实际请求测试 <span class="muted">经本机混合入站真实发起请求，看状态、耗时与命中规则</span></h3>
    <form class="panel" id="f-rtest">
      <label>URL</label>
      <input type="text" name="url" placeholder="https://www.youtube.com/generate_204" required>
      <div><button>发起测试</button></div>
    </form>
    <div id="rtest-result"></div>`;
  const showPreview = r => `<div class="result">
      <p>命中站点集：<b>${r.site_set ? esc(r.site_set) : '（无，按兜底）'}</b></p>
      <p>动作：${actionPill(r.action)}　出口：<span class="pill proxy">${esc(r.outbound)}</span>
      ${r.flip ? `<span class="muted">（热切换：${esc(r.flip)}）</span>` : ''}</p>
    </div>`;
  $('#f-debug').onsubmit = async e => {
    e.preventDefault();
    const target = new FormData(e.target).get('target').trim();
    try {
      const r = await post('/route/preview', { target });
      $('#dbg-result').innerHTML = showPreview(r);
    } catch (err) { toast(err.message, false); }
  };
  $('#btn-penetrate').onclick = async () => {
    const target = new FormData($('#f-debug')).get('target').trim();
    if (!target) return toast('先输入目标', false);
    try {
      const r = await post('/route/penetrate', { target });
      $('#dbg-result').innerHTML = `<div class="result">
        <div class="big">${esc(target)}</div>
        <p>${r.chain.map(c => {
          const lbl = { site_set: '站点集', outbound: '出口', node: '节点' }[c.level] || c.level;
          return `<span class="pill">${lbl}</span> <b>${esc(c.name || '—')}</b>`;
        }).join(' <span class="muted">→</span> ')}</p>
        ${r.node ? `<p class="muted">${esc(r.node.protocol)}://${esc(r.node.server)}:${r.node.port}</p>` : ''}
        ${r.kernel ? '' : '<p class="muted">内核未运行，节点级解析不可用</p>'}
      </div>`;
    } catch (err) { toast(err.message, false); }
  };
  $('#f-rtest').onsubmit = async e => {
    e.preventDefault();
    const url = new FormData(e.target).get('url').trim();
    $('#rtest-result').innerHTML = '<p class="muted">请求中…</p>';
    try {
      const r = await post('/route/test', { url });
      $('#rtest-result').innerHTML = `<div class="result">
        <p>状态：<b>${r.status}</b>　耗时：<b>${r.elapsed_ms} ms</b></p>
        <p class="muted">最终 URL：${esc(r.final_url || '')}</p>
        ${showPreview(r.preview)}
      </div>`;
    } catch (err) {
      const d = err.data || {};
      $('#rtest-result').innerHTML = `<div class="result">
        <p>请求失败：${esc(err.message)}${d.elapsed_ms ? `（${d.elapsed_ms} ms）` : ''}</p>
        ${d.preview ? showPreview(d.preview) : ''}</div>`;
    }
  };
}

/* ---------- DNS ---------- */
async function vDns() {
  const d = await get('/dns');
  const modeName = { dnsmasq: '接管 dnsmasq 转发', firewall: '防火墙劫持', off: '禁用' };
  $('#view').innerHTML = `
    <h2>DNS</h2>
    <form class="panel" id="f-dns">
      <div class="row">
        <div><label>接管模式</label><select name="mode">
          ${['dnsmasq', 'firewall', 'off'].map(v =>
            `<option value="${v}"${d.mode === v ? ' selected' : ''}>${modeName[v]}</option>`).join('')}
        </select></div>
        <div><label>区域</label><select name="region">
          ${[['auto', '自动'], ['cn', '中国大陆'], ['outside', '中国大陆之外']].map(([v, l]) =>
            `<option value="${v}"${d.region === v ? ' selected' : ''}>${l}</option>`).join('')}
        </select>
        <div class="muted">当前判定：${esc(d.region_detected || '未检测')}
          <button type="button" id="btn-detect" class="small ghost">按出口 IP 检测</button></div></div>
      </div>
      <div class="row">
        <div><label>直连 DNS</label><input type="text" name="direct_dns" value="${esc(d.direct_dns)}"></div>
        <div><label>代理 DNS</label><input type="text" name="proxy_dns" value="${esc(d.proxy_dns)}">
          <div class="muted">中国大陆默认 TCP 1.1.1.1；大陆之外默认上游 DNS</div></div>
      </div>
      <div><button>保存</button> <span class="muted">保存后需「应用配置」重启内核生效</span></div>
    </form>
    <h3>DNS 重写 <span class="muted">域名 → 固定 IP 或另一个域名（dnsmasq address=）</span></h3>
    <table><tr><th>域名</th><th>目标</th><th></th></tr>
    ${d.rewrites.map(r => `<tr><td>${esc(r.domain)}</td><td>${esc(r.target)}</td>
      <td><button class="small danger" data-del-rw="${r.id}">删除</button></td></tr>`).join('')}
    </table>
    <form class="panel" id="f-rw"><h3>新增重写</h3>
      <div class="row">
        <div><label>域名</label><input type="text" name="domain" required></div>
        <div><label>目标</label><input type="text" name="target" placeholder="1.2.3.4 或 other.example.com" required></div>
      </div>
      <div><button>添加</button></div>
    </form>`;
  $('#f-dns').onsubmit = async e => {
    e.preventDefault();
    const f = new FormData(e.target);
    try {
      await put('/dns', { mode: f.get('mode'), region: f.get('region'),
        direct_dns: f.get('direct_dns').trim(), proxy_dns: f.get('proxy_dns').trim() });
      toast('已保存'); vDns();
    } catch (err) { toast(err.message, false); }
  };
  $('#btn-detect').onclick = async () => {
    try { const r = await post('/dns/detect-region', {}); toast(`检测到：${r.country} → ${r.region}`); vDns(); }
    catch (e) { toast(e.message, false); }
  };
  $('#f-rw').onsubmit = async e => {
    e.preventDefault();
    const f = new FormData(e.target);
    try { await post('/dns/rewrite', { domain: f.get('domain'), target: f.get('target') }); toast('已添加'); vDns(); }
    catch (err) { toast(err.message, false); }
  };
  $('#view').querySelectorAll('[data-del-rw]').forEach(b => b.onclick = async () => {
    try { await delReq('/dns/rewrite/' + b.dataset.delRw); toast('已删除'); vDns(); }
    catch (e) { toast(e.message, false); }
  });
}

/* ---------- 连接 ---------- */
let connsTimer = null;
async function vConns() {
  clearInterval(connsTimer);
  const fmt = n => n > 1e9 ? (n / 1e9).toFixed(2) + ' GB' : n > 1e6 ? (n / 1e6).toFixed(1) + ' MB' : Math.round(n / 1e3) + ' KB';
  const load = async () => {
    try {
      const [t, c] = await Promise.all([get('/traffic/now'), get('/connections').catch(() => null)]);
      $('#traf-now').innerHTML =
        `<div class="card"><div class="num">${fmt(t.download)}</div><div class="lbl">下载</div></div>
         <div class="card"><div class="num">${fmt(t.up)}</div><div class="lbl">上传</div></div>
         <div class="card"><div class="num">${t.connections}</div><div class="lbl">活动连接</div></div>
         ${t.kernel ? '' : '<div class="card"><div class="lbl">内核未运行</div></div>'}`;
      if (!c) { $('#conns-tbl').innerHTML = '<p class="muted">内核未运行，无实时连接</p>'; return; }
      $('#conns-tbl').innerHTML = `<table><tr><th>源</th><th>目标</th><th>出口链</th><th>规则</th><th>上/下行</th><th></th></tr>
        ${c.connections.map(x => `<tr><td class="muted">${esc(x.src)}</td>
          <td>${esc(x.dst)}${x.dport ? ':' + x.dport : ''}</td>
          <td class="muted">${esc((x.chains || []).join(' → '))}</td>
          <td class="muted">${esc(x.rule || '')}</td>
          <td class="muted">${fmt(x.upload)} / ${fmt(x.download)}</td>
          <td><button class="small danger" data-close="${esc(x.id)}">关闭</button></td></tr>`).join('')}
        </table>`;
      $('#conns-tbl').querySelectorAll('[data-close]').forEach(b => b.onclick = async () => {
        try { await delReq('/connections/' + encodeURIComponent(b.dataset.close)); load(); }
        catch (e) { toast(e.message, false); }
      });
    } catch (e) { /* keep old content on transient errors */ }
  };
  $('#view').innerHTML = `
    <h2>连接 <span class="muted">实时（5 秒刷新）</span></h2>
    <div class="grid2" id="traf-now"></div>
    <div id="conns-tbl"><p class="muted">加载中…</p></div>
    <h3>每日流量 <span class="muted">按终端 / 出口 / 目标聚合</span></h3>
    <div id="traf-daily"><p class="muted">加载中…</p></div>`;
  load();
  connsTimer = setInterval(load, 5000);
  try {
    const r = await get('/traffic/daily?days=7');
    $('#traf-daily').innerHTML = r.rows.length ? `<table>
      <tr><th>日期</th><th>终端</th><th>出口</th><th>目标</th><th>上传</th><th>下载</th></tr>
      ${r.rows.map(x => `<tr><td>${esc(x.day)}</td><td class="muted">${esc(x.client || '—')}</td>
        <td>${esc(x.proxy || '—')}</td><td class="muted">${esc(x.host || '—')}</td>
        <td>${fmt(x.up)}</td><td>${fmt(x.down)}</td></tr>`).join('')}</table>`
      : '<p class="muted">暂无记录（需要内核运行且流量采集开启）</p>';
  } catch (e) { $('#traf-daily').innerHTML = `<p class="muted">${esc(e.message)}</p>`; }
}

/* ---------- 终端 ---------- */
async function vTerminals() {
  const { terminals } = await get('/terminals');
  const polName = { direct: '直连', proxy: '代理', bypass: '不进内核' };
  $('#view').innerHTML = `
    <h2>终端分流 <span class="muted">按设备 IP / 网段指定策略</span></h2>
    <table><tr><th>标识（IP/网段）</th><th>名称</th><th>策略</th><th></th></tr>
    ${terminals.map(t => `<tr><td>${esc(t.ident)}</td><td>${esc(t.name || '—')}</td>
      <td><span class="pill">${polName[t.policy] || esc(t.policy)}</span></td>
      <td><button class="small danger" data-del-term="${t.id}">删除</button></td></tr>`).join('')}
    </table>
    <form class="panel" id="f-term"><h3>新增 / 修改终端策略</h3>
      <div class="row">
        <div><label>标识（IP 或 CIDR）</label><input type="text" name="ident" placeholder="192.168.1.50 或 192.168.1.0/24" required></div>
        <div><label>名称</label><input type="text" name="name" placeholder="客厅电视"></div>
        <div><label>策略</label><select name="policy">
          <option value="proxy">代理（默认）</option>
          <option value="direct">直连</option>
          <option value="bypass">不进内核</option>
        </select></div>
      </div>
      <div><button>保存</button> <span class="muted">保存后需「应用配置」生效；「不进内核」还需应用 nftables</span></div>
    </form>`;
  $('#f-term').onsubmit = async e => {
    e.preventDefault();
    const f = new FormData(e.target);
    try {
      await post('/terminals', { ident: f.get('ident'), name: f.get('name'), policy: f.get('policy') });
      toast('已保存'); vTerminals();
    } catch (err) { toast(err.message, false); }
  };
  $('#view').querySelectorAll('[data-del-term]').forEach(b => b.onclick = async () => {
    try { await delReq('/terminals/' + b.dataset.delTerm); toast('已删除'); vTerminals(); }
    catch (e) { toast(e.message, false); }
  });
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
      <div class="row">
        <div><label>TUN MTU</label><input type="number" name="tun_mtu" value="${esc(s.tun_mtu)}"></div>
        <div><label>屏蔽 QUIC（UDP 443 走代理时拒绝，浏览器自动退回 TCP）</label><select name="quic_block">
          <option value="1"${s.quic_block === '1' ? ' selected' : ''}>开（默认）</option>
          <option value="0"${s.quic_block !== '1' ? ' selected' : ''}>关</option>
        </select></div>
      </div>
      <div><button>保存</button> <span class="muted">DNS 详细设置已移至「DNS」页</span></div>
    </form>
    <h3>组件升级</h3>
    <div class="panel" id="upgrade-box"><p class="muted">加载中…</p></div>
    <h3>透明代理（生成预览 · 需 root 手动应用）</h3>
    <form class="panel" id="f-tproxy">
      <div class="row">
        <div><label>TPROXY 端口</label><input type="number" name="tproxy_port" value="7893"></div>
        <div><label>下行网卡</label><input type="text" name="lan_iface" value="br-lan"></div>
      </div>
      <div><button>生成预览</button></div>
    </form>
    <div id="tproxy-result"></div>`;
  $('#f-settings').onsubmit = async e => {
    e.preventDefault();
    const f = new FormData(e.target);
    try {
      await put('/settings', {
        dns_direct: f.get('dns_direct').trim(), dns_proxy: f.get('dns_proxy').trim(),
        final_outbound: f.get('final_outbound').trim(), tun_stack: f.get('tun_stack'),
        tun_mtu: f.get('tun_mtu').trim(), quic_block: f.get('quic_block'),
      });
      toast('已保存');
    } catch (err) { toast(err.message, false); }
  };

  // component upgrade
  const ubox = $('#upgrade-box');
  const renderUpgrade = async () => {
    try {
      const st = await get('/upgrade/status');
      ubox.innerHTML = `
        <div class="row">
          <div><label>面板</label><div><b>${esc(st.panel)}</b></div></div>
          <div><label>sing-box</label><div><b>${esc(st.singbox || '未安装')}</b>
            ${st.singbox_running ? '<span class="pill ok">运行中</span>' : ''}</div></div>
          <div><label>Geo 数据</label><div class="muted">${st.geo_files.length ? esc(st.geo_files.join(', ')) : '无'}</div></div>
        </div>
        <div><button id="btn-ucheck">检查更新</button>
          <button id="btn-urun" class="danger">执行升级</button>
          <span class="muted">调用 scripts/upgrade.sh，日志见下</span></div>
        <div id="ucheck-result"></div>
        <pre class="cfg" id="ulog" style="max-height:200px;overflow:auto"></pre>`;
      $('#btn-ucheck').onclick = async () => {
        $('#ucheck-result').innerHTML = '<span class="muted">检查中…</span>';
        try {
          const r = await get('/upgrade/check');
          $('#ucheck-result').innerHTML =
            `<p>sing-box 最新版：<b>${esc(r.latest)}</b> <span class="muted">${esc(r.published_at || '')}</span></p>`;
        } catch (e) { $('#ucheck-result').innerHTML = `<p class="muted">${esc(e.message)}</p>`; }
      };
      $('#btn-urun').onclick = async () => {
        if (!confirm('执行升级脚本？请确保了解其内容（oss/scripts/upgrade.sh）。')) return;
        try { await post('/upgrade/run', {}); toast('升级已启动，稍后刷新看日志'); pollUlog(); }
        catch (e) { toast(e.message, false); }
      };
      const pollUlog = async () => {
        try { $('#ulog').textContent = (await get('/upgrade/log')).log || '（暂无日志）'; }
        catch (e) { /* ignore */ }
      };
      pollUlog();
    } catch (e) { ubox.innerHTML = `<p class="muted">${esc(e.message)}</p>`; }
  };
  renderUpgrade();
  $('#f-tproxy').onsubmit = async e => {
    e.preventDefault();
    const f = new FormData(e.target);
    const qs = new URLSearchParams({
      tproxy_port: f.get('tproxy_port'), lan_iface: f.get('lan_iface') }).toString();
    try {
      const [nft, rules, dns] = await Promise.all([
        get('/transparent/nft?' + qs), get('/transparent/iprules?' + qs),
        get('/transparent/dnsmasq?' + qs)]);
      const pre = t => { const el = document.createElement('pre'); el.className = 'cfg'; el.textContent = t; return el; };
      const box = $('#tproxy-result');
      box.innerHTML = '<h3>nftables</h3><h3>ip rule/route</h3><h3>dnsmasq</h3>';
      const [h1, h2, h3] = box.querySelectorAll('h3');
      h1.after(pre(nft.script)); h2.after(pre(rules.script)); h3.after(pre(dns.script));
    } catch (err) { toast(err.message, false); }
  };

  // password + pairing
  const auth = await get('/auth/status');
  const sec = document.createElement('div');
  sec.innerHTML = `
    <h3>面板密码 ${auth.has_password ? '<span class="pill ok">已设置</span>' : '<span class="pill bad">未设置</span>'}</h3>
    <form class="panel" id="f-pw">
      ${auth.has_password ? '<label>当前密码</label><input type="password" name="old">' : ''}
      <label>新密码（≥4 位）</label><input type="password" name="new" required>
      <div><button>${auth.has_password ? '修改密码' : '设置密码'}</button></div>
    </form>
    <h3>客户端配对</h3>
    <div><button id="btn-pair">生成配对码</button>
      <span class="muted">一次性，10 分钟有效；客户端扫码后完成配对</span></div>
    <div id="pair-result"></div>
    <h3>已配对设备</h3>
    <div id="pair-devices"><p class="muted">加载中…</p></div>`;
  $('#view').appendChild(sec);
  $('#f-pw').onsubmit = async e => {
    e.preventDefault();
    const f = new FormData(e.target);
    try {
      await post('/auth/password', { old: f.get('old') || '', new: f.get('new') });
      toast('密码已保存'); vSettings();
    } catch (err) { toast(err.message, false); }
  };
  const loadDevices = async () => {
    try {
      const ds = await get('/pair/devices');
      $('#pair-devices').innerHTML = ds.length ? `<table>
        <tr><th>设备</th><th>配对时间</th><th></th></tr>
        ${ds.map(d => `<tr><td>${esc(d.name) || '(未命名)'}</td>
          <td class="muted">${esc(d.created_at)}</td>
          <td><button class="small danger" data-unpair="${d.id}">解绑</button></td></tr>`).join('')}
        </table>` : '<p class="muted">暂无已配对设备</p>';
      $('#pair-devices').querySelectorAll('[data-unpair]').forEach(b => b.onclick = async () => {
        if (!confirm('解绑该设备？其 token 立即失效。')) return;
        try { await delReq('/pair/devices/' + b.dataset.unpair); toast('已解绑'); loadDevices(); }
        catch (err) { toast(err.message, false); }
      });
    } catch (err) { $('#pair-devices').innerHTML = `<p class="muted">${esc(err.message)}</p>`; }
  };
  loadDevices();
  $('#btn-pair').onclick = async () => {
    try {
      const r = await post('/pair/code', {});
      const url = `openbox://pair?host=${location.hostname}&port=${location.port || 80}&token=${r.token}`;
      $('#pair-result').innerHTML = `<div class="result">
        <div class="grid2">
          <div><textarea rows="3" readonly>${esc(url)}</textarea>
            <p class="muted">10 分钟内有效，仅可使用一次</p></div>
          <div><img src="/api/share/qr?text=${encodeURIComponent(url)}"
               alt="QR" style="width:160px;height:160px;background:#fff;padding:8px;border-radius:8px"></div>
        </div></div>`;
    } catch (err) { toast(err.message, false); }
  };
}

/* ---------- 配置 ---------- */
async function vConfig() {
  const conf = await get('/config');
  const text = JSON.stringify(conf, null, 2);
  $('#view').innerHTML = `
    <h2>生成的 sing-box 配置</h2>
    <div><button id="btn-copy">复制</button><button id="btn-dl" class="ghost">下载 config.json</button>
      <button id="btn-backup" class="ghost">下载整包备份</button>
      <button id="btn-restore" class="ghost">恢复备份…</button>
      <input type="file" id="restore-file" accept=".json" hidden></div>
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
  $('#btn-backup').onclick = () => {
    const a = document.createElement('a');
    a.href = '/api/backup';
    a.download = 'openbox-oss-backup.json';
    a.click();
  };
  $('#btn-restore').onclick = () => $('#restore-file').click();
  $('#restore-file').onchange = async e => {
    const f = e.target.files[0];
    if (!f) return;
    if (!confirm('恢复备份将覆盖当前全部配置，继续？')) return;
    try {
      const r = await fetch('/api/backup', {
        method: 'POST', headers: { 'Content-Type': 'application/json' },
        body: await f.text(),
      });
      const data = await r.json();
      if (!r.ok) throw new Error(data.error || 'HTTP ' + r.status);
      toast('已恢复：' + Object.entries(data.counts).map(([k, v]) => `${k}×${v}`).join(' '));
    } catch (err) { toast(err.message, false); }
  };
}

/* ---------- 登录 ---------- */
async function renderLogin() {
  $('#view').innerHTML = `
    <h2>登录</h2>
    <form class="panel" id="f-login" style="max-width:380px">
      <label>面板密码</label>
      <input type="password" name="password" required autofocus>
      <div><button>登录</button></div>
      <p class="muted">首次使用请先设置密码（设置页），或通过环境变量 OPENBOX_PANEL_PASSWORD 预置。</p>
    </form>`;
  $('#f-login').onsubmit = async e => {
    e.preventDefault();
    const pw = new FormData(e.target).get('password');
    try {
      await post('/auth/login', { password: pw });
      toast('登录成功');
      navigate();
    } catch (err) { toast(err.message, false); }
  };
}

async function updateAuthArea() {
  const el = $('#auth-area');
  if (!el) return;
  try {
    const a = await get('/auth/status');
    el.innerHTML = (a.has_password && a.logged_in)
      ? `<button class="small ghost" id="btn-logout" style="margin:0">退出</button>` : '';
    const b = $('#btn-logout');
    if (b) b.onclick = async () => { await post('/auth/logout', {}); navigate(); };
  } catch (e) { /* ignore */ }
}

/* ---------- 路由 ---------- */
const ROUTES = {
  '': vOverview, 'proxy': vProxy, 'subs': vSubs, 'sites': vSites,
  'rulesets': vRulesets, 'chains': vChains, 'debug': vDebug,
  'dns': vDns, 'conns': vConns, 'terminals': vTerminals,
  'settings': vSettings, 'config': vConfig,
};
async function navigate() {
  const h = location.hash.replace(/^#\/?/, '').split('?')[0] || '';
  if (typeof connsTimer !== 'undefined' && connsTimer) { clearInterval(connsTimer); connsTimer = null; }
  renderNav(h);
  $('#view').innerHTML = '<p class="muted">加载中…</p>';
  try {
    const a = await get('/auth/status');
    updateAuthArea();
    if (a.has_password && !a.logged_in) {
      await renderLogin();
      window.scrollTo(0, 0);
      return;
    }
    await (ROUTES[h] || vOverview)();
  } catch (e) {
    $('#view').innerHTML = `<p class="muted">加载失败：${esc(e.message)}</p>`;
  }
  window.scrollTo(0, 0);
}
window.addEventListener('hashchange', navigate);
navigate();
