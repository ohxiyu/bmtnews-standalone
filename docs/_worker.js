const SITE_ORIGIN = 'https://bmt.news';
const MARKDOWN_ROUTES = new Map([
  ['/', 'zh'],
  ['/en', 'en'],
  ['/en/', 'en']
]);
const JSON_API_PATHS = new Set(['/api/latest.json', '/api/editions.json', '/api/events.json']);
const DATED_EDITION_PATH = /^\/editions\/\d{4}-\d{2}-\d{2}\/edition\.json$/;
const EVENT_DETAIL_PATH = /^\/api\/events\/evt_[a-z0-9_-]{6,80}\.json$/;

function parseAccept(header) {
  return String(header || '')
    .split(',')
    .map((entry, order) => {
      const [range, ...parameters] = entry.trim().toLowerCase().split(';');
      let quality = 1;
      parameters.forEach((parameter) => {
        const [name, value] = parameter.trim().split('=');
        if (name === 'q') {
          const parsed = Number(value);
          quality = Number.isFinite(parsed) && parsed >= 0 && parsed <= 1 ? parsed : 0;
        }
      });
      const [type, subtype] = range.split('/');
      if (!type || !subtype) return null;
      const specificity = type === '*' ? 0 : subtype === '*' ? 1 : 2;
      return {type, subtype, quality, specificity, order};
    })
    .filter(Boolean);
}

function qualityFor(mediaType, ranges) {
  const [candidateType, candidateSubtype] = mediaType.split('/');
  const matches = ranges.filter((range) => (
    (range.type === '*' || range.type === candidateType) &&
    (range.subtype === '*' || range.subtype === candidateSubtype)
  ));
  if (!matches.length) return 0;
  matches.sort((left, right) => (
    right.specificity - left.specificity || left.order - right.order
  ));
  return matches[0].quality;
}

export function acceptsMarkdown(header) {
  const ranges = parseAccept(header);
  if (!ranges.length) return false;
  const markdownQuality = qualityFor('text/markdown', ranges);
  const htmlQuality = qualityFor('text/html', ranges);
  return markdownQuality > 0 && markdownQuality > htmlQuality;
}

function appendVary(headers, ...names) {
  const values = String(headers.get('Vary') || '')
    .split(',')
    .map((value) => value.trim())
    .filter(Boolean);
  names.forEach((name) => {
    if (!values.some((value) => value.toLowerCase() === name.toLowerCase())) values.push(name);
  });
  headers.set('Vary', values.join(', '));
}

function responseWithHeaders(response, mutate) {
  const headers = new Headers(response.headers);
  mutate(headers);
  return new Response(response.body, {
    status: response.status,
    statusText: response.statusText,
    headers
  });
}

function markdownText(value) {
  return String(value || '')
    .replace(/\s+/g, ' ')
    .replace(/([\\[\]])/g, '\\$1')
    .trim();
}

function safeHttpUrl(value) {
  try {
    const url = new URL(String(value || ''));
    return url.protocol === 'http:' || url.protocol === 'https:' ? url.href : SITE_ORIGIN;
  } catch (error) {
    return SITE_ORIGIN;
  }
}

export function renderEditionMarkdown(payload, language) {
  const isEnglish = language === 'en';
  const overview = markdownText(payload?.overview?.[language]);
  const items = Array.isArray(payload?.items) ? payload.items.slice(0, 15) : [];
  const lines = [
    isEnglish
      ? '# BMTNews — Daily crypto, AI, and policy intelligence'
      : '# BMTNews — 加密、AI 与政策每日情报',
    '',
    isEnglish
      ? '> A ranked, bilingual daily briefing with source attribution, background, and market-impact analysis.'
      : '> 每日发布的双语重要资讯排行，提供来源、背景和市场影响分析。',
    '',
    isEnglish
      ? 'Use BMTNews when an agent needs a concise daily view of material crypto events, selected AI developments, or policy changes that can affect digital-asset markets. It is a research input, not investment advice.'
      : '当智能体需要快速了解重要加密事件、少量关键 AI 进展，或可能影响数字资产市场的政策变化时，可以使用 BMTNews。内容用于研究参考，不构成投资建议。',
    '',
    `## ${isEnglish ? 'Latest edition' : '最新一期'} — ${markdownText(payload?.date) || '—'}`,
    ''
  ];
  if (overview) lines.push(overview, '');
  items.forEach((item) => {
    const title = markdownText(item?.title?.[language] || item?.title?.zh || item?.url);
    const summary = markdownText(item?.summary?.[language] || item?.summary?.zh);
    lines.push(`- [${title}](${safeHttpUrl(item?.url)}): ${summary}`);
  });
  lines.push(
    '',
    `## ${isEnglish ? 'Machine-readable resources' : '机器可读资源'}`,
    '',
    `- [${isEnglish ? 'Latest edition JSON' : '最新一期 JSON'}](${SITE_ORIGIN}/api/latest.json)`,
    `- [${isEnglish ? 'Edition index JSON' : '历史期次索引 JSON'}](${SITE_ORIGIN}/api/editions.json)`,
    `- [${isEnglish ? 'Event timeline JSON' : '事件线 JSON'}](${SITE_ORIGIN}/api/events.json)`,
    `- [OpenAPI](${SITE_ORIGIN}/openapi.json)`,
    `- [llms.txt](${SITE_ORIGIN}/llms.txt)`,
    `- [${isEnglish ? 'Developer documentation' : '开发者文档'}](${SITE_ORIGIN}/developers/)`,
    '',
    isEnglish
      ? 'Prefer the JSON API for structured retrieval. Preserve original-source URLs when citing a story.'
      : '结构化调用应优先使用 JSON API；引用新闻时请保留原始来源链接。',
    ''
  );
  return lines.join('\n');
}

function jsonError(status, code, message, resolution) {
  return new Response(JSON.stringify({error: {code, message, resolution}}, null, 2) + '\n', {
    status,
    headers: {
      'Access-Control-Allow-Origin': '*',
      'Cache-Control': 'no-store',
      'Content-Type': 'application/json; charset=utf-8'
    }
  });
}

function markdown404(pathname, method) {
  const body = [
    '# 404 — Resource not found',
    '',
    `No BMTNews resource exists at \`${pathname}\`.`,
    '',
    '- [Sitemap](https://bmt.news/sitemap.xml)',
    '- [Agent instructions](https://bmt.news/llms.txt)',
    '- [Developer documentation](https://bmt.news/developers/)',
    ''
  ].join('\n');
  return new Response(method === 'HEAD' ? null : body, {
    status: 404,
    headers: {
      'Cache-Control': 'public, max-age=60',
      'Content-Type': 'text/markdown; charset=utf-8',
      'Vary': 'Accept, Accept-Encoding'
    }
  });
}

async function markdownHome(request, env, language) {
  const latestUrl = new URL('/api/latest.json', request.url);
  const latest = await env.ASSETS.fetch(new Request(latestUrl, {headers: {'Accept': 'application/json'}}));
  const contentLength = Number(latest.headers.get('Content-Length') || 0);
  let body;
  if (latest.ok && String(latest.headers.get('Content-Type')).includes('application/json') && contentLength <= 524288) {
    const payload = await latest.json();
    body = renderEditionMarkdown(payload, language);
  } else {
    const fallbackPath = language === 'en' ? '/en/index.html.md' : '/index.html.md';
    const fallbackUrl = new URL(fallbackPath, request.url);
    const fallback = await env.ASSETS.fetch(new Request(fallbackUrl, {headers: {'Accept': 'text/markdown'}}));
    if (!fallback.ok) {
      return jsonError(503, 'edition_unavailable', 'The latest edition is temporarily unavailable.', 'Retry /api/latest.json later or use /api/editions.json.');
    }
    body = await fallback.text();
  }
  return new Response(request.method === 'HEAD' ? null : body, {
    headers: {
      'Cache-Control': 'public, max-age=300, stale-while-revalidate=60',
      'Content-Language': language === 'en' ? 'en' : 'zh-CN',
      'Content-Type': 'text/markdown; charset=utf-8',
      'Link': `</${language === 'en' ? 'en/' : ''}index.html.md>; rel="alternate"; type="text/markdown", </llms.txt>; rel="describedby"`,
      'Vary': 'Accept, Accept-Encoding'
    }
  });
}

function isJsonApiPath(pathname) {
  return JSON_API_PATHS.has(pathname) || DATED_EDITION_PATH.test(pathname) || EVENT_DETAIL_PATH.test(pathname);
}

async function handleOriginRequest(request, env) {
  const url = new URL(request.url);
  const language = MARKDOWN_ROUTES.get(url.pathname);
  const apiPath = isJsonApiPath(url.pathname);

  if (url.pathname.startsWith('/api/') && !apiPath) {
    return jsonError(404, 'not_found', 'No API endpoint exists at this path.', 'Read /openapi.json or /developers/ and use a documented endpoint.');
  }
  if (apiPath && request.method !== 'GET' && request.method !== 'HEAD') {
    return jsonError(405, 'method_not_allowed', 'This read-only endpoint accepts GET and HEAD only.', 'Retry the same URL with GET.');
  }
  if (language && acceptsMarkdown(request.headers.get('Accept'))) {
    return markdownHome(request, env, language);
  }

  const assetResponse = await env.ASSETS.fetch(request);
  if (apiPath) {
    if (!assetResponse.ok || !String(assetResponse.headers.get('Content-Type')).includes('application/json')) {
      return jsonError(404, 'not_found', 'The requested API resource does not exist.', 'Use /api/editions.json or /api/events.json to discover available resources.');
    }
    return responseWithHeaders(assetResponse, (headers) => {
      headers.set('Access-Control-Allow-Origin', '*');
    });
  }
  if (assetResponse.status === 404 && acceptsMarkdown(request.headers.get('Accept'))) {
    return markdown404(url.pathname, request.method);
  }
  if (language) {
    return responseWithHeaders(assetResponse, (headers) => {
      appendVary(headers, 'Accept', 'Accept-Encoding');
      headers.set('Link', `</${language === 'en' ? 'en/' : ''}index.html.md>; rel="alternate"; type="text/markdown", </llms.txt>; rel="describedby"`);
    });
  }
  return assetResponse;
}

function cachePolicy(request) {
  if (request.method !== 'GET') return null;
  const url = new URL(request.url);
  if (url.pathname === '/s' || url.pathname.startsWith('/s/')) return null;
  // CSS and JavaScript must be able to recover from a deployment where new
  // markup reaches the edge before its matching asset. The query fingerprint
  // remains the primary cache key, but these files deliberately revalidate
  // quickly instead of freezing a mismatched response for a year.
  if (
    url.pathname.startsWith('/assets/css/') ||
    url.pathname.startsWith('/assets/js/')
  ) {
    return {ttl: 300};
  }
  if (url.pathname.startsWith('/assets/images/')) {
    return {ttl: 31536000, immutable: true};
  }
  if (url.pathname.startsWith('/assets/')) {
    return url.searchParams.has('v')
      ? {ttl: 31536000, immutable: true}
      : {ttl: 300};
  }
  if (DATED_EDITION_PATH.test(url.pathname)) return {ttl: 86400, immutable: true};
  if (url.pathname === '/api/editions.json') return {ttl: 1800};
  if (url.pathname === '/api/events.json' || EVENT_DETAIL_PATH.test(url.pathname)) return {ttl: 300};
  if (url.pathname === '/api/latest.json') return {ttl: 600};
  if (url.pathname === '/feed-zh.xml' || url.pathname === '/feed-en.xml') return {ttl: 1800};
  if (url.pathname === '/' || url.pathname === '/en' || url.pathname === '/en/') return {ttl: 300};
  return {ttl: 600};
}

function cacheKey(request) {
  const url = new URL(request.url);
  if (MARKDOWN_ROUTES.has(url.pathname)) {
    url.searchParams.set(
      '__bmt_variant',
      acceptsMarkdown(request.headers.get('Accept')) ? 'markdown' : 'html'
    );
  }
  return new Request(url, {method: 'GET'});
}

function cachedResponse(response, status) {
  return responseWithHeaders(response, (headers) => {
    headers.set('X-BMTNews-Cache', status);
  });
}

export async function handleRequest(request, env, ctx) {
  const policy = cachePolicy(request);
  const cache = globalThis.caches?.default;
  if (!policy || !cache) return handleOriginRequest(request, env);

  const key = cacheKey(request);
  const hit = await cache.match(key);
  if (hit) return cachedResponse(hit, 'HIT');

  const response = await handleOriginRequest(request, env);
  if (!response.ok || response.headers.get('Cache-Control') === 'no-store') {
    return cachedResponse(response, 'BYPASS');
  }
  const stored = responseWithHeaders(response.clone(), (headers) => {
    const suffix = policy.immutable ? ', immutable' : ', stale-while-revalidate=60';
    headers.set('Cache-Control', `public, max-age=${policy.ttl}${suffix}`);
    headers.set('CDN-Cache-Control', `public, max-age=${policy.ttl}${suffix}`);
    headers.delete('Set-Cookie');
  });
  const write = cache.put(key, stored);
  if (ctx?.waitUntil) ctx.waitUntil(write);
  else await write;
  return cachedResponse(response, 'MISS');
}

export default {
  async fetch(request, env, ctx) {
    try {
      return await handleRequest(request, env, ctx);
    } catch (error) {
      console.error(JSON.stringify({event: 'agent_gateway_error', message: String(error?.message || error)}));
      if (new URL(request.url).pathname.startsWith('/api/')) {
        return jsonError(500, 'internal_error', 'The API could not complete the request.', 'Retry later and consult /developers/ if the error persists.');
      }
      return new Response('BMTNews could not complete this request.\n', {
        status: 500,
        headers: {'Content-Type': 'text/plain; charset=utf-8'}
      });
    }
  }
};
