import assert from 'node:assert/strict';
import {readFile} from 'node:fs/promises';
import test from 'node:test';

const source = await readFile(new URL('../docs/_worker.js', import.meta.url), 'utf8');
const moduleUrl = `data:text/javascript;base64,${Buffer.from(source).toString('base64')}`;
const worker = await import(moduleUrl);

const edition = {
  date: '2026-08-24',
  overview: {zh: '今天的重要变化集中在政策与市场结构。', en: 'Today focused on policy and market structure.'},
  items: [{
    url: 'https://example.com/story',
    title: {zh: '一条重要新闻', en: 'An important story'},
    summary: {zh: '这是包含关键事实的摘要。', en: 'A summary with the key facts.'}
  }]
};

function environment({includeLatest = true} = {}) {
  return {
    ASSETS: {
      async fetch(request) {
        const path = new URL(request.url).pathname;
        if (path === '/api/latest.json' && includeLatest) {
          const body = JSON.stringify(edition);
          return new Response(body, {headers: {'Content-Type': 'application/json', 'Content-Length': String(body.length)}});
        }
        if (path === '/api/editions.json') {
          return Response.json({version: 1, editions: []});
        }
        if (path === '/index.html.md') {
          return new Response('# BMTNews — static agent overview\n', {headers: {'Content-Type': 'text/markdown'}});
        }
        if (path === '/') return new Response('<h1>BMTNews</h1>', {headers: {'Content-Type': 'text/html'}});
        return new Response('<h1>Not found</h1>', {status: 404, headers: {'Content-Type': 'text/html'}});
      }
    }
  };
}

test('Accept negotiation respects quality and defaults wildcards to HTML', () => {
  assert.equal(worker.acceptsMarkdown('text/markdown, text/html;q=0.8'), true);
  assert.equal(worker.acceptsMarkdown('text/html, text/markdown;q=0.8'), false);
  assert.equal(worker.acceptsMarkdown('text/markdown;q=0, */*;q=1'), false);
  assert.equal(worker.acceptsMarkdown('*/*'), false);
});

test('homepage returns markdown with discovery and cache variation headers', async () => {
  const response = await worker.handleRequest(
    new Request('https://bmt.news/', {headers: {'Accept': 'text/markdown, text/html;q=0.8'}}),
    environment()
  );
  const body = await response.text();
  assert.equal(response.status, 200);
  assert.match(response.headers.get('Content-Type'), /^text\/markdown/);
  assert.equal(response.headers.get('Vary'), 'Accept, Accept-Encoding');
  assert.match(response.headers.get('Link'), /llms\.txt/);
  assert.match(body, /^# BMTNews/);
  assert.match(body, /一条重要新闻/);
  assert.match(body, /openapi\.json/);
});

test('homepage falls back to stable markdown before edition data is deployed', async () => {
  const response = await worker.handleRequest(
    new Request('https://bmt.news/', {headers: {'Accept': 'text/markdown'}}),
    environment({includeLatest: false})
  );
  assert.equal(response.status, 200);
  assert.match(response.headers.get('Content-Type'), /^text\/markdown/);
  assert.match(await response.text(), /static agent overview/);
});

test('browser homepage remains HTML and declares its markdown alternative', async () => {
  const response = await worker.handleRequest(
    new Request('https://bmt.news/', {headers: {'Accept': 'text/html, */*;q=0.8'}}),
    environment()
  );
  assert.match(response.headers.get('Content-Type'), /^text\/html/);
  assert.equal(response.headers.get('Vary'), 'Accept, Accept-Encoding');
  assert.match(await response.text(), /<h1>BMTNews<\/h1>/);
});

test('edge cache varies homepage markdown and HTML without repeating asset work', async () => {
  const stored = new Map();
  const assetEnv = environment();
  let originCalls = 0;
  const originalFetch = assetEnv.ASSETS.fetch;
  assetEnv.ASSETS.fetch = async (request) => {
    originCalls += 1;
    return originalFetch(request);
  };
  globalThis.caches = {
    default: {
      async match(request) {
        return stored.get(request.url)?.clone();
      },
      async put(request, response) {
        stored.set(request.url, response.clone());
      }
    }
  };
  try {
    const markdownRequest = new Request('https://bmt.news/', {
      headers: {'Accept': 'text/markdown'}
    });
    const first = await worker.handleRequest(markdownRequest, assetEnv);
    const second = await worker.handleRequest(markdownRequest, assetEnv);
    const html = await worker.handleRequest(
      new Request('https://bmt.news/', {headers: {'Accept': 'text/html'}}),
      assetEnv
    );
    assert.equal(first.headers.get('X-BMTNews-Cache'), 'MISS');
    assert.equal(second.headers.get('X-BMTNews-Cache'), 'HIT');
    assert.equal(html.headers.get('X-BMTNews-Cache'), 'MISS');
    assert.equal(originCalls, 2);
  } finally {
    delete globalThis.caches;
  }
});

test('unknown API paths and methods return structured JSON errors', async () => {
  const missing = await worker.handleRequest(
    new Request('https://bmt.news/api/missing.json'), environment()
  );
  assert.equal(missing.status, 404);
  assert.match(missing.headers.get('Content-Type'), /^application\/json/);
  assert.equal((await missing.json()).error.code, 'not_found');

  const method = await worker.handleRequest(
    new Request('https://bmt.news/api/latest.json', {method: 'POST'}), environment()
  );
  assert.equal(method.status, 405);
  assert.equal((await method.json()).error.code, 'method_not_allowed');
});

test('missing dated editions return JSON and unknown markdown paths stay 404', async () => {
  const editionResponse = await worker.handleRequest(
    new Request('https://bmt.news/editions/1999-01-01/edition.json'), environment()
  );
  assert.equal(editionResponse.status, 404);
  assert.equal((await editionResponse.json()).error.resolution.includes('/api/editions.json'), true);

  const pageResponse = await worker.handleRequest(
    new Request('https://bmt.news/not-real', {headers: {'Accept': 'text/markdown'}}), environment()
  );
  assert.equal(pageResponse.status, 404);
  assert.match(pageResponse.headers.get('Content-Type'), /^text\/markdown/);
  assert.match(await pageResponse.text(), /Sitemap/);
});
