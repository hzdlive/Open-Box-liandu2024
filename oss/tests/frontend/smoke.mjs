import { JSDOM, VirtualConsole } from 'jsdom';

// Renders the real panel frontend (index.html + app.js) against the live dev
// server and walks through 5 views. Catches JS runtime/DOM errors no
// static check can see.
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
    // Node's fetch needs absolute URLs; resolve against the page like a browser.
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
const viewText = () => document.querySelector('#view').textContent;

// 1. overview: nav + stat cards + service card
await waitFor(() => document.querySelectorAll('#nav a').length === 12, 'nav 12 links');
await waitFor(() => /节点/.test(viewText()) && /站点集/.test(viewText()), 'overview cards');
await waitFor(() => /内核服务/.test(viewText()), 'service card');

// 2. proxy: nodes table + groups
window.location.hash = '#/proxy';
await waitFor(() => /vmess-demo/.test(viewText()), 'proxy nodes');
if (!/auto/.test(viewText())) throw new Error('proxy view missing group cards');

// 3. site sets: table renders + flip toggle present
window.location.hash = '#/sites';
await waitFor(() => /自上而下/.test(viewText()), 'sites view');
await waitFor(() => document.querySelector('[data-flip]'), 'flip toggle');

// 4. debug: fill target, submit, result card appears; penetrate chain
window.location.hash = '#/debug';
await waitFor(() => document.querySelector('#f-debug input[name=target]'), 'debug form');
document.querySelector('#f-debug input[name=target]').value = 'www.youtube.com';
document.querySelector('#f-debug')
  .dispatchEvent(new window.Event('submit', { bubbles: true, cancelable: true }));
await waitFor(() => /命中站点集/.test(viewText()), 'debug result card');
document.querySelector('#btn-penetrate').click();
await waitFor(() => /站点集/.test(viewText()) && /→/.test(viewText()), 'penetrate chain');

// 5. config: generated JSON preview
window.location.hash = '#/config';
await waitFor(
  () => /"outbounds"/.test(document.querySelector('#cfg-pre')?.textContent || ''),
  'config json preview');

// 6. dns page: mode/region/rewrites render
window.location.hash = '#/dns';
await waitFor(() => document.querySelector('#f-dns select[name=mode]'), 'dns form');
await waitFor(() => /DNS 重写/.test(viewText()), 'dns rewrites');

// 7. terminals page renders
window.location.hash = '#/terminals';
await waitFor(() => /终端分流/.test(viewText()), 'terminals view');

// 8. connections page renders (no kernel -> graceful message)
window.location.hash = '#/conns';
await waitFor(() => /活动连接|内核未运行/.test(viewText()), 'conns view');

// leave the page so its refresh timer is cleared, then release jsdom
window.location.hash = '#/';
await new Promise(r => setTimeout(r, 300));
window.close();

if (errors.length) throw new Error('page errors:\n' + errors.join('\n'));
console.log('OK: jsdom render smoke — 8 views rendered, forms work, no JS errors');
