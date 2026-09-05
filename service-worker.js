---
layout: null
permalink: /service-worker.js
---
/* Public reading only. No background collection, authentication or push. */
const BUILD = '{{ site.time | date_to_xmlschema }}';
const PAGES = 'bmt-reader-pages-v1';
const ASSETS = 'bmt-reader-assets-v1';
const MAX_PAGES = 30;
const MAX_BYTES = 20 * 1024 * 1024;
const MAX_AGE = 30 * 86400000;
let generation = 0;
let writes = Promise.resolve();

function pageURL(value) {
  const url = new URL(value, self.location.origin);
  if (url.origin !== self.location.origin || !/^\/(?:en\/)?(?:$|threads\/$|entity\/(?:[a-z0-9_-]+\/)?$|events\/[a-z0-9_-]+\/$|weekly\/(?:[a-z0-9_-]+\/)?$|20\d\d\/\d\d\/\d\d\/summary-(?:zh|en)(?:\.html)?$)/i.test(url.pathname)) return null;
  for (const key of url.searchParams.keys()) {
    if (key !== 'source' && key !== 'publication_check' && !key.startsWith('utm_')) return null;
  }
  url.search = '';
  url.hash = '';
  return url.href;
}

function safeResponse(response, type) {
  return response.ok && !response.redirected &&
    !/private|no-store/i.test(response.headers.get('Cache-Control') || '') &&
    !response.headers.has('Set-Cookie') &&
    (response.headers.get('Content-Type') || '').includes(type);
}

async function fresh(url, timeout = 8000) {
  const controller = new AbortController();
  const timer = setTimeout(() => controller.abort(), timeout);
  try {
    return await fetch(url, {cache: 'no-store', credentials: 'omit', signal: controller.signal});
  } finally { clearTimeout(timer); }
}

async function version() {
  const response = await fresh(new URL('/pwa-version.json', self.location.origin));
  if (!response.ok) throw new Error('Version unavailable');
  return response.json();
}

function assetURLs(html) {
  return [...new Set([...html.matchAll(/(?:src|href)="(\/assets\/(?:css|js)\/[^"<>]+)"/g)]
    .map(match => new URL(match[1].replaceAll('&amp;', '&'), self.location.origin).href))];
}

function enqueue(task) {
  const token = generation;
  writes = writes.catch(() => {}).then(() => token === generation && task(token));
  return writes;
}

async function prune(pages, assets) {
  const keys = await pages.keys();
  const records = [];
  for (const key of keys) {
    const response = await pages.match(key);
    const saved = Number(response.headers.get('X-BMT-Saved'));
    const html = await response.text();
    records.push({key, saved, html, bytes: new TextEncoder().encode(html).length});
  }
  records.sort((a, b) => b.saved - a.saved);
  const keep = new Set();
  let bytes = 0;
  let count = 0;
  for (const record of records) {
    if (Date.now() - record.saved > MAX_AGE || count >= MAX_PAGES || bytes + record.bytes > MAX_BYTES) {
      await pages.delete(record.key);
    } else {
      count++;
      bytes += record.bytes;
      assetURLs(record.html).forEach(url => keep.add(url));
    }
  }
  for (const key of await assets.keys()) if (!keep.has(key.url)) await assets.delete(key);
}

async function savePage(url, response, token) {
  if (!safeResponse(response, 'text/html')) return;
  const html = await response.text();
  if (new TextEncoder().encode(html).length > 2 * 1024 * 1024) return;
  const fingerprint = html.match(/<meta name="bmt-assets" content="([a-z0-9-]+)"/)?.[1];
  if (!fingerprint || (await version()).assets !== fingerprint) return;
  const assets = await caches.open(ASSETS);
  const staged = [];
  for (const asset of assetURLs(html)) {
    if (new URL(asset).searchParams.get('v') !== fingerprint) return;
    if (await assets.match(asset)) continue;
    const bypass = new URL(asset);
    bypass.searchParams.set('publication_check', 'pwa');
    const result = await fresh(bypass);
    const type = bypass.pathname.endsWith('.css') ? 'text/css' : 'javascript';
    // publication_check bypasses the edge cache, but does not change asset bytes.
    if (!safeResponse(result, type)) return;
    staged.push([asset, result]);
  }
  if ((await version()).assets !== fingerprint || token !== generation) return;
  for (const [key, result] of staged) await assets.put(key, result);
  if (token !== generation) return;
  const pages = await caches.open(PAGES);
  const headers = new Headers(response.headers);
  headers.set('X-BMT-Saved', String(Date.now()));
  headers.delete('Content-Encoding');
  headers.delete('Content-Length');
  await pages.put(url, new Response(html, {headers}));
  await prune(pages, assets);
}

async function cachedPage(url) {
  const response = await (await caches.open(PAGES)).match(url);
  if (!response) return null;
  const saved = Number(response.headers.get('X-BMT-Saved'));
  if (!saved || Date.now() - saved > MAX_AGE) return null;
  const html = await response.text();
  const headers = new Headers(response.headers);
  headers.set('Cache-Control', 'no-store');
  // Visible to the page without reading browser internals; never label cached data as live.
  return new Response(html.replace('</head>', `<meta name="bmt-offline" content="${saved}"></head>`), {headers});
}

function offlinePage() {
  return new Response('<!doctype html><html lang="zh-CN"><meta charset="utf-8"><meta name="viewport" content="width=device-width"><title>BMTNews · 离线</title><style>body{font:16px/1.7 system-ui;background:#faf9f7;color:#222;max-width:640px;margin:12vh auto;padding:24px}a{color:#305587}</style><h1>BMTNews</h1><h2>此页面尚未离线保存</h2><p>连接恢复后重试。已保存的页面仍可阅读。<br>This page is not saved. Reconnect to load it.</p><p><a href="/">中文信息流</a> · <a href="/en/">English feed</a></p></html>', {status: 503, headers: {'Content-Type': 'text/html; charset=utf-8', 'Cache-Control': 'no-store'}});
}

async function navigate(request, url, event) {
  try {
    const response = await fresh(request.url, 3500);
    if (response.status >= 500) throw new Error('Origin unavailable');
    // A 401/403/404 is authoritative, never replace it with stale content.
    const copy = response.clone();
    event.waitUntil(enqueue(token => savePage(url, copy, token)).catch(() => {}));
    return response;
  } catch {
    return await cachedPage(url).catch(() => null) || offlinePage();
  }
}

self.addEventListener('install', () => { /* Updates wait for explicit reader consent. */ });
self.addEventListener('activate', event => event.waitUntil(self.clients.claim()));
self.addEventListener('fetch', event => {
  const request = event.request;
  if (request.method !== 'GET' || request.headers.has('Authorization')) return;
  const url = new URL(request.url);
  if (url.origin !== self.location.origin) return;
  if (request.mode === 'navigate') {
    const key = pageURL(url);
    if (key) event.respondWith(navigate(request, key, event));
  } else if (/^\/assets\/(css|js)\/[a-z0-9.-]+$/i.test(url.pathname) &&
      [...url.searchParams.keys()].every(key => key === 'v') && url.searchParams.has('v')) {
    event.respondWith(caches.open(ASSETS).then(async cache => await cache.match(request) || fetch(request)));
  }
});

self.addEventListener('message', event => {
  // Only same-origin public readers may manage this cache, never unrelated tabs.
  if (!event.source?.url || !pageURL(event.source.url)) return;
  const reply = value => event.ports?.[0]?.postMessage(value);
  const task = async () => {
    if (event.data?.type === 'ACTIVATE') { await self.skipWaiting(); reply({ok: true}); }
    if (event.data?.type === 'CLEAR') {
      generation++;
      await writes.catch(() => {});
      await Promise.all([caches.delete(PAGES), caches.delete(ASSETS)]);
      reply({ok: true, count: 0});
    }
    if (event.data?.type === 'STATUS') {
      const cache = await caches.open(PAGES);
      reply({ok: true, count: (await cache.keys()).length, build: BUILD});
    }
    if (event.data?.type === 'WARM') {
      const urls = [...new Set((event.data.urls || []).slice(0, 3).map(pageURL).filter(Boolean))];
      await enqueue(async token => {
        for (const url of urls) {
          if (token !== generation) break;
          const previous = await (await caches.open(PAGES)).match(url);
          if (previous && Date.now() - Number(previous.headers.get('X-BMT-Saved')) < 60000) continue;
          await fresh(url).then(response => savePage(url, response, token)).catch(() => {});
        }
      });
      reply({ok: true});
    }
  };
  event.waitUntil(task().catch(() => reply({ok: false})));
});
