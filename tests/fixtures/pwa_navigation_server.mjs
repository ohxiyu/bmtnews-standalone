// Manual browser regression: node tests/fixtures/pwa_navigation_server.mjs
// Click dates after "Worker controlling", refresh, return home, then stop the
// server and reload a visited date. This deliberately emulates Pages' HTTP 308.
import {createServer} from 'node:http';
import {readFile} from 'node:fs/promises';

const root = new URL('../../docs/', import.meta.url);
const fingerprint = 'sha256-navigation-test';
const build = 'navigation-test';
const links = [['/', 'Home'], ['/2026/09/04/summary-zh.html', '09.04'],
  ['/2026/09/03/summary-zh.html', '09.03'], ['/2026/09/04/summary-en.html', 'English date'],
  ['/threads/', 'Events'], ['/entity/', 'Entities'], ['/weekly/', 'Weekly']];
const pages = new Set(links.map(([path]) => path.replace(/\.html$/, '')));
createServer(async (request, response) => {
  const url = new URL(request.url, 'http://localhost');
  response.setHeader('Cache-Control', 'no-store');
  if (url.pathname === '/service-worker.js') {
    const worker = (await readFile(new URL('service-worker.js', root), 'utf8'))
      .replace(/^---\n[\s\S]*?\n---\n/, '').replace('{{ site.time | date_to_xmlschema }}', build);
    response.setHeader('Content-Type', 'text/javascript');
    return response.end(worker);
  }
  if (url.pathname === '/pwa-version.json') {
    response.setHeader('Content-Type', 'application/json');
    return response.end(JSON.stringify({assets: fingerprint, build}));
  }
  if (url.pathname === '/assets/js/pwa-reader.js') {
    response.setHeader('Cache-Control', 'public, max-age=0');
    response.setHeader('Content-Type', 'text/javascript');
    return response.end(await readFile(new URL('assets/js/pwa-reader.js', root)));
  }
  if (url.pathname.endsWith('.html') && pages.has(url.pathname.slice(0, -5))) {
    response.writeHead(308, {Location: url.pathname.slice(0, -5) + url.search});
    return response.end();
  }
  if (!pages.has(url.pathname)) { response.writeHead(404); return response.end('Not found'); }
  response.setHeader('Content-Type', 'text/html; charset=utf-8');
  response.setHeader('Cache-Control', 'public, max-age=0');
  response.end(`<!doctype html><html lang="en"><head>
    <meta charset="utf-8"><meta name="bmt-assets" content="${fingerprint}">
    <meta name="bmt-build" content="${build}"><title>PWA navigation fixture</title>
    <script type="module" src="/assets/js/pwa-reader.js?v=${fingerprint}"></script>
    </head><body><header class="site-header"><nav>${links.map(([path, label]) => `<a href="${path}">${label}</a>`).join(' · ')}</nav>
    <button data-reader-open>Saved</button></header><main id="content">
    <h1>${url.pathname}</h1><p>PWA navigation test fixture</p><p id="worker-state">Waiting for worker</p>
    <section class="daily-day" data-date="2026-09-04"></section>
    <section class="daily-day" data-date="2026-09-03"></section></main>
    <script>function showControl() { document.getElementById('worker-state').textContent = navigator.serviceWorker.controller ? 'Worker controlling' : 'Waiting for worker'; }
    navigator.serviceWorker.addEventListener('controllerchange', showControl); showControl();</script>
    </body></html>`);
}).listen(4178, '127.0.0.1', () => console.log('PWA redirect fixture: http://127.0.0.1:4178'));
