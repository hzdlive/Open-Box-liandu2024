import { JSDOM, VirtualConsole } from 'jsdom';

// Renders the Vue panel build (frontend/dist) against the live dev server and
// walks through the views. Catches JS runtime/DOM errors no static check can see.
// BASE configurable for CI: BASE_URL env or default dev server.
const BASE = process.env.BASE_URL || 'http://127.0.0.1:8080';
const errors = [];
const vc = new VirtualConsole();
vc.on('jsdomError', e => errors.push('jsdomError: ' + e.message));
vc.on('error', (...a) => errors.push('console.error: ' + a.join(' ')));

const dom = await JSDOM.fromURL(BASE + '/', {
  runScripts: 'dangerously',
  resources: 'usable',
  virtualConsole: vc,
  beforeParse(window) {
    window.fetch = (input, init) =>
      globalThis.fetch(new URL(String(input), window.location.href).toString(), init);
    window.scrollTo = () => {};
    window.confirm = () => true;
  },
});
const { window } = dom;
const { document } = window;

async function waitFor(fn, label, timeout = 20000) {
  const t0 = Date.now();
  for (;;) {
    try { if (fn()) return; } catch { /* keep polling */ }
    if (Date.now() - t0 > timeout) throw new Error('timeout: ' + label);
    await new Promise(r => setTimeout(r, 120));
  }
}
const viewText = () => document.querySelector('.main')?.textContent || '';

// 1. layout: sidebar with 15 nav links
await waitFor(() => document.querySelectorAll('.sidebar .nav a').length === 15, 'nav 15 links');

// 2. overview: stat cards + service card
await waitFor(() => /节点/.test(viewText()) && /站点集/.test(viewText()), 'overview cards');
await waitFor(() => /内核服务/.test(viewText()), 'service card');

// 3. proxies: nodes table
window.location.hash = '#/proxies';
await waitFor(() => /vmess-demo/.test(viewText()), 'proxy nodes');

// 4. subscriptions: table + form
window.location.hash = '#/subscriptions';
await waitFor(() => /添加订阅/.test(viewText()), 'subscriptions view');

// 5. sites: ordered table
window.location.hash = '#/sites';
await waitFor(() => /自上而下/.test(viewText()), 'sites view');
await waitFor(() => /切直连|切回代理/.test(viewText()), 'flip toggle');

// 6. debug: penetrate form works
window.location.hash = '#/debug';
await waitFor(() => /域名穿透/.test(viewText()), 'debug view');
const domInput = document.querySelector('input[placeholder="example.com"]');
domInput.value = 'www.youtube.com';
domInput.dispatchEvent(new window.Event('input', { bubbles: true }));
document.querySelector('.card form').dispatchEvent(
  new window.Event('submit', { bubbles: true, cancelable: true }));
await waitFor(() => /命中站点集/.test(viewText()), 'penetrate result');

// 7. dns: tabs render
window.location.hash = '#/dns';
await waitFor(() => /接管模式/.test(viewText()), 'dns view');

// 8. connections: tabs render
window.location.hash = '#/connections';
await waitFor(() => /活跃连接/.test(viewText()), 'connections view');

// 9. terminals: rules table
window.location.hash = '#/terminals';
await waitFor(() => /终端分流规则/.test(viewText()), 'terminals view');

// 10. kernel: service status
window.location.hash = '#/kernel';
await waitFor(() => /服务状态/.test(viewText()), 'kernel view');

// 11. logs: source tabs
window.location.hash = '#/logs';
await waitFor(() => /内核/.test(viewText()) && document.querySelector('pre.code'), 'logs view');

// 12. diagnostics
window.location.hash = '#/diagnostics';
await waitFor(() => /脱敏/.test(viewText()), 'diagnostics view');

// 13. settings: tabs
window.location.hash = '#/settings';
await waitFor(() => /TUN 与网络/.test(viewText()), 'settings view');

// 14. config: generated JSON preview
window.location.hash = '#/config';
await waitFor(() => /"outbounds"/.test(viewText()), 'config json preview');

// 15. rulesets / chains render
window.location.hash = '#/rulesets';
await waitFor(() => /新增规则集/.test(viewText()), 'rulesets view');
window.location.hash = '#/chains';
await waitFor(() => /新建/.test(viewText()) && /链式代理/.test(viewText()), 'chains view');

window.location.hash = '#/';
await new Promise(r => setTimeout(r, 300));
window.close();

if (errors.length) throw new Error('page errors:\n' + errors.join('\n'));
console.log('OK: jsdom render smoke — 15 views rendered, forms work, no JS errors');
