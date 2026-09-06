import test from 'node:test';
import assert from 'node:assert/strict';
import vm from 'node:vm';
import {readFile} from 'node:fs/promises';

const source = (await readFile(new URL('../docs/service-worker.js', import.meta.url), 'utf8')).replace(/^---\n[\s\S]*?\n---\n/, '').replace('{{ site.time | date_to_xmlschema }}', 'test-build');
const origin = 'https://bmt.news';
const page = (assets = 'sha256-one', css = true) => `<html><head><meta name="bmt-assets" content="${assets}">${css ? `<link href="/assets/css/pwa-reader.css?v=${assets}" rel="stylesheet">` : ''}</head><body>Full story</body></html>`;
const html = body => new Response(body, {headers: {'Content-Type': 'text/html'}});
function harness() {
  const stores = new Map(), events = new Map(), calls = [], redirects = new Map();
  let offline = false, assets = 'sha256-one', status = 200, cacheHeader = 'public', activated = false;
  const caches = {
    async open(name) {
      if (!stores.has(name)) stores.set(name, new Map());
      const data = stores.get(name), key = request => typeof request === 'string' ? request : request.url;
      return {
        async keys() { return [...data.keys()].map(url => new Request(url)); },
        async match(request) { return data.get(key(request))?.clone(); },
        async put(request, response) { data.set(key(request), response.clone()); },
        async delete(request) { return data.delete(key(request)); }
      };
    },
    async delete(name) { return stores.delete(name); }
  };
  const context = vm.createContext({URL, Response, Request, Headers, TextEncoder, AbortController, Date, Promise,
    setTimeout, clearTimeout, caches,
    self: {location: {origin}, clients: {claim: async () => {}}, skipWaiting: async () => { activated = true; }, addEventListener: (type, fn) => events.set(type, fn)},
    fetch: async (value, options) => {
      const url = new URL(typeof value === 'string' ? value : value.url || value.href);
      calls.push({url: url.href, options});
      if (offline) throw new Error('Offline');
      if (redirects.has(url.href)) {
        const destination = redirects.get(url.href);
        if (options.redirect === 'error') throw new TypeError('Redirect forbidden');
        if (options.redirect === 'manual') {
          // Browser fetch hides the Location header behind an opaque redirect.
          const response = new Response(null);
          Object.defineProperties(response, {
            type: {value: 'opaqueredirect'}, status: {value: 0}, ok: {value: false}
          });
          return response;
        }
        const response = html(page(assets));
        Object.defineProperties(response, {redirected: {value: true}, url: {value: destination}});
        return response;
      }
      if (url.pathname === '/pwa-version.json') return Response.json({assets, build: 'test-build'});
      if (url.pathname.endsWith('.css')) return new Response(`/* ${assets} */`, {headers: {'Content-Type': 'text/css'}});
      return new Response(page(assets), {status, headers: {'Content-Type': 'text/html', 'Cache-Control': cacheHeader}});
    }
  });
  vm.runInContext(source, context);
  const api = vm.runInContext('({pageURL, safeResponse, assetURLs, savePage, cachedPage, enqueue, prune})', context);
  async function dispatch(url, options = {}) {
    const pending = [];
    let response;
    const request = new Request(url, {redirect: !options.mode || options.mode === 'navigate' ? 'manual' : 'follow', ...options});
    Object.defineProperty(request, 'mode', {value: options.mode || 'navigate'});
    events.get('fetch')({request, waitUntil: p => pending.push(p), respondWith: p => { response = p; }});
    const result = response && await response;
    await Promise.all(pending);
    // Model respondWith's browser validation, not just the function's return value.
    if (result?.redirected && request.redirect !== 'follow') throw new TypeError('Redirected response rejected by navigation');
    if (result?.type === 'opaqueredirect' && request.redirect !== 'manual') throw new TypeError('Opaque redirect requires manual mode');
    return result;
  }
  async function message(data, from = `${origin}/`) {
    let reply;
    const pending = [];
    events.get('message')({data, source: {url: from}, ports: [{postMessage: value => { reply = value; }}], waitUntil: p => pending.push(p)});
    await Promise.all(pending);
    return reply;
  }
  return {api, caches, calls, dispatch, message, context, events, redirects,
    offline: () => { offline = true; }, setAssets: value => { assets = value; },
    setStatus: value => { status = value; }, setPrivate: () => { cacheHeader = 'private'; },
    activated: () => activated};
}
test('only public reading routes with harmless tracking parameters are eligible', async () => {
  const h = harness();
  for (const path of ['/', '/en/', '/threads/', '/en/threads/', '/events/evt_123/', '/entity/bitcoin/', '/weekly/2026-w36/', '/2026/09/05/summary-zh.html']) assert.ok(h.api.pageURL(origin + path), path);
  for (const path of ['/admin/', '/s', '/s/config', '/login', '/api/latest.json', '/?token=secret', '/threads/?authorization=x']) {
    assert.equal(h.api.pageURL(origin + path), null, path);
    assert.equal(await h.dispatch(origin + path), undefined);
  }
  assert.equal(h.api.pageURL('https://external.org/'), null);
  assert.equal(h.api.pageURL(`${origin}/?utm_source=x&source=pwa`), `${origin}/`);
  assert.equal(await h.dispatch(`${origin}/`, {headers: {Authorization: 'Bearer test'}}), undefined);
  assert.equal(await h.dispatch(`${origin}/`, {method: 'POST'}), undefined);
});
test('offline navigation returns saved content with an honest timestamp and matching CSS', async () => {
  const h = harness();
  assert.equal((await h.dispatch(`${origin}/`)).status, 200);
  assert.equal((await h.message({type: 'STATUS'})).count, 1);
  h.offline();
  const result = await h.dispatch(`${origin}/?source=pwa`);
  assert.match(await result.text(), /bmt-offline/);
  assert.match(result.headers.get('Cache-Control'), /no-store/);
  const css = await h.dispatch(`${origin}/assets/css/pwa-reader.css?v=sha256-one`, {mode: 'cors'});
  assert.equal(await css.text(), '/* sha256-one */');
  const missing = await h.dispatch(`${origin}/events/missing/`);
  assert.equal(missing.status, 503);
  assert.match(await missing.text(), /尚未离线保存/);
});
test('Cloudflare dated HTML redirects share an offline key; private and cross-origin redirects stay excluded', async () => {
  const h = harness();
  const alias = `${origin}/2026/09/05/summary-zh.html`;
  const canonical = `${origin}/2026/09/05/summary-zh`;
  assert.equal(h.api.pageURL(alias), canonical);
  const redirected = destination => {
    const response = html(page());
    Object.defineProperty(response, 'redirected', {value: true});
    Object.defineProperty(response, 'url', {value: destination});
    return response;
  };
  assert.equal(h.api.safeResponse(redirected(`${origin}/admin/`), 'text/html', canonical), false);
  assert.equal(h.api.safeResponse(redirected('https://external.org/'), 'text/html', canonical), false);
  assert.equal(h.api.safeResponse(redirected(`${origin}/`), 'text/html', canonical), false);
  await h.api.enqueue(token => h.api.savePage(canonical, redirected(canonical), token));
  h.offline();
  assert.match(await (await h.dispatch(alias)).text(), /bmt-offline/);
  assert.match(await (await h.dispatch(canonical)).text(), /bmt-offline/);
});
test('online dated links preserve manual redirects, then canonical pages remain readable offline', async () => {
  const h = harness();
  for (const language of ['zh', 'en']) {
    const alias = `${origin}/2026/09/04/summary-${language}.html?source=pwa`;
    const canonical = `${origin}/2026/09/04/summary-${language}`;
    h.redirects.set(alias, canonical);
    const redirect = await h.dispatch(alias);
    assert.equal(redirect.type, 'opaqueredirect');
    assert.equal(h.calls.at(-1).url, alias, 'keep the actual request URL and query');
    assert.equal(h.calls.at(-1).options.redirect, 'manual');
    assert.equal((await h.message({type: 'STATUS'})).count, language === 'zh' ? 0 : 1);
    // The browser follows the redirect as a new navigation, not inside worker fetch.
    const destination = await h.dispatch(canonical);
    assert.equal(destination.status, 200);
    assert.equal(destination.redirected, false);
    assert.doesNotMatch(await destination.text(), /bmt-offline/);
    assert.equal((await h.dispatch(canonical)).status, 200, 'refresh stays online');
  }
  h.offline();
  for (const language of ['zh', 'en']) {
    for (const suffix of ['', '.html']) {
      assert.match(await (await h.dispatch(`${origin}/2026/09/04/summary-${language}${suffix}`)).text(), /bmt-offline/);
    }
  }
});
test('navigation does not follow or cache redirects to private or external destinations', async () => {
  const h = harness();
  for (const destination of [`${origin}/admin/`, 'https://external.org/']) {
    h.redirects.set(`${origin}/threads/`, destination);
    assert.equal((await h.dispatch(`${origin}/threads/`)).type, 'opaqueredirect');
    assert.equal((await h.message({type: 'STATUS'})).count, 0);
  }
});
test('static hosts without canonical redirects still serve dated HTML links', async () => {
  const h = harness();
  const url = `${origin}/2026/09/04/summary-zh.html?publication_check=pwa-test`;
  assert.equal((await h.dispatch(url)).status, 200);
  assert.equal(h.calls[0].url, url);
  assert.equal((await h.message({type: 'STATUS'})).count, 1);
});
test('403/404 remain authoritative, 503 may fall back, private responses are not saved', async () => {
  const h = harness();
  await h.dispatch(`${origin}/`);
  for (const code of [401, 403, 404]) { h.setStatus(code); assert.equal((await h.dispatch(`${origin}/`)).status, code); }
  h.setStatus(503);
  assert.match(await (await h.dispatch(`${origin}/`)).text(), /bmt-offline/);
  const privateReader = harness(); privateReader.setPrivate();
  await privateReader.dispatch(`${origin}/`);
  assert.equal((await privateReader.message({type: 'STATUS'})).count, 0);
});
test('deployment mismatch never commits a page and retained pages preserve old asset versions', async () => {
  const h = harness();
  await h.api.enqueue(token => h.api.savePage(`${origin}/`, html(page('sha256-wrong')), token));
  assert.equal((await h.message({type: 'STATUS'})).count, 0);
  await h.dispatch(`${origin}/`);
  h.setAssets('sha256-two');
  await h.dispatch(`${origin}/threads/`);
  h.offline();
  assert.match(await (await h.dispatch(`${origin}/`)).text(), /sha256-one/);
  assert.equal(await (await h.dispatch(`${origin}/assets/css/pwa-reader.css?v=sha256-one`, {mode: 'cors'})).text(), '/* sha256-one */');
  assert.equal(await (await h.dispatch(`${origin}/assets/css/pwa-reader.css?v=sha256-two`, {mode: 'cors'})).text(), '/* sha256-two */');
});
test('public-only cache clear keeps unrelated caches and requires explicit update activation', async () => {
  const h = harness();
  await h.caches.open('other-app');
  await h.dispatch(`${origin}/`);
  assert.equal(await h.message({type: 'CLEAR'}, `${origin}/admin/`), undefined);
  assert.equal((await h.message({type: 'STATUS'})).count, 1);
  assert.equal(h.activated(), false);
  await h.message({type: 'ACTIVATE'});
  assert.equal(h.activated(), true);
  assert.equal((await h.message({type: 'CLEAR'})).ok, true);
  assert.equal((await h.message({type: 'STATUS'})).count, 0);
  h.offline();
  assert.equal((await h.dispatch(`${origin}/`)).status, 503);
});
test('bounded cache prunes excess pages, expired pages and orphaned assets', async () => {
  const h = harness();
  const pages = await h.caches.open('bmt-reader-pages-v1'), assets = await h.caches.open('bmt-reader-assets-v1');
  for (let i = 0; i < 33; i++) await pages.put(`${origin}/events/event-${i}/`, new Response(page('sha256-one', false), {headers: {'X-BMT-Saved': String(Date.now() - i * 1000)}}));
  await pages.put(`${origin}/events/expired/`, new Response(page(), {headers: {'X-BMT-Saved': '1'}}));
  await assets.put(`${origin}/assets/js/old.js?v=old`, new Response('old'));
  await h.api.prune(pages, assets);
  assert.equal((await pages.keys()).length, 30);
  assert.equal(await pages.match(`${origin}/events/expired/`), undefined);
  assert.equal((await assets.keys()).length, 0);
});
test('warm requests are capped and cache reads never carry credentials', async () => {
  const h = harness();
  await h.message({type: 'WARM', urls: ['/', '/threads/', '/entity/', '/weekly/']});
  assert.equal((await h.message({type: 'STATUS'})).count, 3);
  assert.ok(h.calls.every(call => call.options.credentials === 'omit'));
});
test('network navigation uses a bounded timeout, aborting a hung origin before offline fallback', async () => {
  const h = harness();
  await h.dispatch(`${origin}/`);
  h.context.setTimeout = (callback, ms) => setTimeout(callback, Math.min(ms, 5));
  h.context.fetch = (_url, {signal}) => new Promise((_resolve, reject) => signal.addEventListener('abort', () => reject(new Error('Aborted'))));
  assert.match(await (await h.dispatch(`${origin}/`)).text(), /bmt-offline/);
});
test('cache clear invalidates queued writes instead of silently repopulating afterward', async () => {
  const h = harness();
  let release;
  const blocker = new Promise(resolve => { release = resolve; });
  const write = h.api.enqueue(async token => { await blocker; await h.api.savePage(`${origin}/`, html(page()), token); });
  const clear = h.message({type: 'CLEAR'});
  release();
  await Promise.all([write, clear]);
  assert.equal((await h.message({type: 'STATUS'})).count, 0);
});
