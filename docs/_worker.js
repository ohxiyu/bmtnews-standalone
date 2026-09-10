const SITE_ORIGIN = 'https://bmt.news';

// Admin requests are authenticated before ANY asset or cache lookup.
// No browser-held GitHub credentials, public write proxy, or configurable file paths.
const ADMIN_REPO = 'ohxiyu/bmtnews-standalone';
const EDITORIAL_FILE = 'data/editorial.json';
const QUICK_CATEGORIES = new Set(['', 'crypto-markets', 'crypto-exchange', 'crypto-protocol',
  'crypto-security', 'policy-regulation', 'ai-technology', 'macro-policy']);

export function isAdminPath(path) {
  try { path = decodeURIComponent(path).replaceAll('\\', '/'); } catch { return true; }
  return /^\/(?:s|admin)(?:\/|$)/i.test(path) || /^\/api\/admin(?:\/|$)/i.test(path);
}

class AdminError extends Error {
  constructor(status, code, message) { super(message); this.status = status; this.code = code; }
}
function adminJson(value, status = 200) {
  return new Response(JSON.stringify(value), {status, headers: {
    'Content-Type': 'application/json; charset=utf-8', 'Cache-Control': 'private, no-store',
    'CDN-Cache-Control': 'no-store', 'X-Content-Type-Options': 'nosniff', 'Vary': 'Cookie',
    'X-Robots-Tag': 'noindex, nofollow'
  }});
}
async function boundedText(message, limit) {
  const reader = message.body?.getReader();
  if (!reader) return '';
  const decoder = new TextDecoder('utf-8', {fatal: true});
  let length = 0, text = '';
  try {
    for (;;) {
      const {done, value} = await reader.read();
      if (done) break;
      length += value.byteLength;
      if (length > limit) throw new AdminError(413, 'too_large', '内容过大，请缩短正文或压缩图片。');
      text += decoder.decode(value, {stream: true});
    }
    return text + decoder.decode();
  } finally { await reader.cancel().catch(() => {}); reader.releaseLock(); }
}
function decodeBase64(value) {
  return Uint8Array.from(atob(value.replace(/-/g, '+').replace(/_/g, '/')), c => c.charCodeAt(0));
}
function encodeBase64(value) {
  const bytes = new TextEncoder().encode(value);
  let binary = '';
  for (const byte of bytes) binary += String.fromCharCode(byte);
  return btoa(binary);
}
async function digestText(value) {
  return [...new Uint8Array(await crypto.subtle.digest('SHA-256', new TextEncoder().encode(value)))]
    .map(b => b.toString(16).padStart(2, '0')).join('');
}
async function fetchTimed(url, init = {}) {
  // workerd supports only manual/follow. Never forward credentials to a redirect.
  const response = await fetch(url, {...init, redirect: 'manual', signal: AbortSignal.timeout(15000)});
  if (response.status >= 300 && response.status < 400) {
    await response.body?.cancel().catch(() => {});
    throw new AdminError(502, 'upstream_redirect', '上游服务返回异常跳转，请稍后重试。');
  }
  return response;
}
export async function verifyAdmin(request, env) {
  const issuer = env.ADMIN_ACCESS_ISSUER;
  if (!/^https:\/\/[a-z0-9-]+\.cloudflareaccess\.com$/.test(issuer || '') ||
      !env.ADMIN_ACCESS_AUD || !env.ADMIN_ALLOWED_EMAIL) {
    throw new AdminError(503, 'admin_not_configured', '后台邮箱登录尚未配置完成，公开新闻仍可正常阅读。');
  }
  if (new URL(request.url).origin !== SITE_ORIGIN) {
    throw new AdminError(403, 'wrong_origin', '请通过 https://bmt.news/s/ 访问后台。');
  }
  const token = request.headers.get('Cf-Access-Jwt-Assertion') || '';
  if (!token || token.length > 16384) throw new AdminError(401, 'login_required', '请重新打开 /s/，完成邮箱验证。');
  try {
    const parts = token.split('.');
    if (parts.length !== 3) throw new Error('jwt');
    const header = JSON.parse(new TextDecoder().decode(decodeBase64(parts[0])));
    const claims = JSON.parse(new TextDecoder().decode(decodeBase64(parts[1])));
    const now = Date.now() / 1000;
    if (header.alg !== 'RS256' || typeof header.kid !== 'string' ||
        claims.iss !== issuer || !Array.isArray(claims.aud) || !claims.aud.includes(env.ADMIN_ACCESS_AUD) ||
        !Number.isFinite(claims.exp) || claims.exp <= now ||
        !Number.isFinite(claims.iat) || claims.iat > now + 30 ||
        (claims.nbf !== undefined && (!Number.isFinite(claims.nbf) || claims.nbf > now + 30)) ||
        typeof claims.email !== 'string' ||
        claims.email.toLowerCase() !== env.ADMIN_ALLOWED_EMAIL.trim().toLowerCase()) throw new Error('claims');
    const response = await fetchTimed(issuer + '/cdn-cgi/access/certs');
    if (!response.ok) throw new Error('certs');
    const jwks = JSON.parse(await boundedText(response, 65536));
    const jwk = jwks.keys?.find(key => key.kid === header.kid && key.kty === 'RSA');
    if (!jwk) throw new Error('key');
    const key = await crypto.subtle.importKey('jwk', jwk,
      {name: 'RSASSA-PKCS1-v1_5', hash: 'SHA-256'}, false, ['verify']);
    if (!await crypto.subtle.verify('RSASSA-PKCS1-v1_5', key, decodeBase64(parts[2]),
      new TextEncoder().encode(parts[0] + '.' + parts[1]))) throw new Error('signature');
    return claims.email;
  } catch {
    throw new AdminError(401, 'invalid_session', '登录已失效或无权访问，请重新验证邮箱。');
  }
}
async function github(env, path, init = {}) {
  if (!env.ADMIN_GITHUB_TOKEN) throw new AdminError(503, 'write_not_configured', '后台写入权限尚未配置。');
  const response = await fetchTimed('https://api.github.com/repos/' + ADMIN_REPO + '/' + path, {
    ...init, headers: {'Authorization': 'Bearer ' + env.ADMIN_GITHUB_TOKEN,
      'Accept': 'application/vnd.github+json', 'X-GitHub-Api-Version': '2022-11-28',
      'User-Agent': 'BMTNews-Admin', 'Content-Type': 'application/json'}
  });
  if (!response.ok) {
    if (response.status === 409 || response.status === 422) {
      throw new AdminError(409, 'conflict', '内容已被其他操作更新，请刷新列表后重试；本地草稿仍保留。');
    }
    throw new AdminError(502, 'repository_unavailable', '仓库暂时不可用或权限不足，请稍后重试；不要重复发布。');
  }
  if (response.status === 204) return {};
  return JSON.parse(await boundedText(response, 3 * 1024 * 1024));
}
async function readEditorial(env) {
  const file = await github(env, 'contents/' + EDITORIAL_FILE + '?ref=main');
  const data = JSON.parse(new TextDecoder().decode(decodeBase64(file.content || '')));
  if (!data || !Array.isArray(data.items)) throw new AdminError(502, 'invalid_registry', '编辑文件格式异常，未执行修改。');
  return {sha: file.sha, data};
}
function requireRevision(value, current) {
  if (typeof value !== 'string' || value !== current) {
    throw new AdminError(409, 'conflict', '列表版本已改变，请刷新后再操作。');
  }
}
async function saveEditorial(env, current, items) {
  const content = JSON.stringify({...current.data, items}, null, 2) + '\n';
  const result = await github(env, 'contents/' + EDITORIAL_FILE, {method: 'PUT', body: JSON.stringify({
    branch: 'main', sha: current.sha, message: 'content: update editorial from Quick Post', content: encodeBase64(content)
  })});
  return {sha: result.content.sha, commit: result.commit.sha, status: 'saved', message: '已保存，等待自动发布；不代表已上线。'};
}
function httpLink(value) {
  if (!value) return '';
  if (typeof value !== 'string' || value.length > 2048) throw new AdminError(400, 'invalid_url', '链接格式不正确。');
  try {
    const url = new URL(value);
    if (!['https:', 'http:'].includes(url.protocol) || url.username || url.password) throw new Error('url');
    return url.href;
  } catch { throw new AdminError(400, 'invalid_url', '链接必须使用完整的 http:// 或 https:// 地址。'); }
}
export function validateQuickPost(input) {
  if (!input || typeof input !== 'object' || Array.isArray(input) ||
      typeof input.body !== 'string' || !input.body.trim() || input.body.length > 10000 ||
      !/^[a-f0-9-]{36}$/.test(input.id || '') || !QUICK_CATEGORIES.has(input.category || '') ||
      typeof input.enabled !== 'boolean' || typeof input.pin !== 'boolean' || typeof input.breaking !== 'boolean') {
    throw new AdminError(400, 'invalid_post', '正文必填且不超过 10000 字，请检查分类和状态。');
  }
  const date = input.date;
  if (!/^20\d{2}-\d{2}-\d{2}$/.test(date || '') ||
      !Number.isFinite(Date.parse(date)) || new Date(date).toISOString().slice(0,10) !== date) {
    throw new AdminError(400, 'invalid_date', '请选择有效的刊期日期。');
  }
  const image = input.image || '';
  if (typeof image !== 'string' || (image && !/^\/assets\/uploads\/quick-[a-f0-9]{64}\.(png|jpg|webp)$/.test(image))) {
    throw new AdminError(400, 'invalid_image', '请使用后台上传的图片。');
  }
  return {type: 'quick_post', id: input.id, body: input.body.trim(), url: httpLink(input.url),
    category: input.category || '', date, enabled: input.enabled, pin: input.pin,
    breaking: input.breaking, image};
}
async function handleAdmin(request, env) {
  try {
    await verifyAdmin(request, env);
    const path = new URL(request.url).pathname;
    if (!path.startsWith('/api/admin')) {
      if (request.method !== 'GET' && request.method !== 'HEAD') throw new AdminError(405, 'method_not_allowed', '请使用 GET。');
      if (path === '/admin' || path === '/admin/' || path === '/admin/index.html') {
        return new Response(null, {status: 302, headers: {'Location': '/s/', 'Cache-Control': 'no-store'}});
      }
      if (path.startsWith('/admin/')) throw new AdminError(404, 'not_found', '旧后台已停用，请使用 /s/。');
      const result = await env.ASSETS.fetch(request);
      return responseWithHeaders(result, headers => {
        headers.set('Cache-Control', 'private, no-store'); headers.set('CDN-Cache-Control', 'no-store');
        headers.set('X-Robots-Tag', 'noindex, nofollow');
        headers.set('X-Frame-Options', 'DENY');
        headers.set('Content-Security-Policy', "frame-ancestors 'none'; base-uri 'self'; form-action 'self'");
      });
    }
    if (request.method === 'GET') {
      if (path === '/api/admin/state') {
        const current = await readEditorial(env);
        return adminJson({sha: current.sha, items: current.data.items});
      }
      throw new AdminError(404, 'not_found', '接口不存在。');
    }
    if (request.method !== 'POST') throw new AdminError(405, 'method_not_allowed', '写入接口只接受 POST。');
    if (request.headers.get('Origin') !== SITE_ORIGIN || request.headers.get('X-BMT-Admin') !== '1' ||
        !/^application\/json(?:;|$)/i.test(request.headers.get('Content-Type') || '')) {
      throw new AdminError(403, 'invalid_request_origin', '请从后台页面提交操作。');
    }
    let input;
    try { input = JSON.parse(await boundedText(request, path === '/api/admin/image' ? 1500000 : 100000)); }
    catch (error) { if (error instanceof AdminError) throw error; throw new AdminError(400, 'invalid_json', '请求格式不正确。'); }
    if (path === '/api/admin/posts') {
      const post = validateQuickPost(input);
      const hash = await digestText(JSON.stringify(post));
      const current = await readEditorial(env);
      const existing = current.data.items.find(row => row.type === 'quick_post' && row.id === post.id);
      if (existing?.request_hash === hash) {
        return adminJson({sha: current.sha, status: 'saved', id: post.id, message: '这次操作已经保存，没有重复创建。'});
      }
      requireRevision(input.sha, current.sha);
      const row = {...post, created_at: existing?.created_at || new Date().toISOString(),
        updated_at: new Date().toISOString(), request_hash: hash};
      const items = existing ? current.data.items.map(item => item === existing ? row : item) : [...current.data.items, row];
      return adminJson({...await saveEditorial(env, current, items), id: post.id});
    }
    if (path === '/api/admin/entry-state') {
      const current = await readEditorial(env);
      requireRevision(input.sha, current.sha);
      if (!Number.isInteger(input.index) || input.index < 0 || input.index >= current.data.items.length ||
          typeof input.enabled !== 'boolean') throw new AdminError(400, 'invalid_entry', '无效的编辑条目。');
      const items = current.data.items.map((item, index) => index === input.index ? {...item, enabled: input.enabled, request_hash: undefined} : item);
      return adminJson(await saveEditorial(env, current, items));
    }
    if (path === '/api/admin/legacy') {
      const current = await readEditorial(env);
      requireRevision(input.sha, current.sha);
      const row = input.entry;
      if (!row || !['editorial','sponsored','suppress'].includes(row.type) ||
          typeof row.enabled !== 'boolean' ||
          !Number.isInteger(input.index) || input.index < -1 || input.index >= current.data.items.length ||
          (input.index >= 0 && current.data.items[input.index].type === 'quick_post')) {
        throw new AdminError(400, 'invalid_entry', '编辑记录格式不正确。');
      }
      const clean = {type: row.type, enabled: row.enabled, url: httpLink(row.url)};
      if (!clean.url) throw new AdminError(400, 'invalid_entry', '旧编辑记录必须有原文链接。');
      for (const field of ['title_zh','title_en','summary_zh','summary_en','label','note',
        'background_zh','background_en','market_impact_zh','market_impact_en',
        'community_discussion_zh','community_discussion_en','category']) {
        if (row[field] !== undefined && (typeof row[field] !== 'string' || row[field].length > 10000)) {
          throw new AdminError(400, 'invalid_entry', '编辑字段格式不正确或过长。');
        }
        clean[field] = row[field] || '';
      }
      if (row.type !== 'suppress' && !clean.title_zh.trim() && !clean.title_en.trim()) {
        throw new AdminError(400, 'title_required', '旧编辑精选和广告需要标题。');
      }
      for (const field of ['date','starts','expires']) {
        if (row[field] && (!/^20\d{2}-\d{2}-\d{2}$/.test(row[field]) ||
            !Number.isFinite(Date.parse(row[field])) || new Date(row[field]).toISOString().slice(0,10) !== row[field])) {
          throw new AdminError(400, 'invalid_date', '日期格式不正确。');
        }
        clean[field] = row[field] || null;
      }
      if (row.type === 'sponsored' && (!clean.expires || (clean.starts && clean.expires < clean.starts))) {
        throw new AdminError(400, 'invalid_date', '广告结束日期必填且不能早于开始日期。');
      }
      if (row.position !== null && row.position !== undefined &&
          (!Number.isInteger(row.position) || row.position < 1 || row.position > 20)) {
        throw new AdminError(400, 'invalid_position', '广告位置应为 1–20。');
      }
      clean.position = row.position ?? null;
      clean.official = row.official === true;
      if (!Array.isArray(row.tags) || row.tags.length > 50 || row.tags.some(tag => typeof tag !== 'string' || tag.length > 100) ||
          !Array.isArray(row.sources) || row.sources.length > 30) {
        throw new AdminError(400, 'invalid_sources', '标签或参考链接格式不正确。');
      }
      clean.tags = row.tags;
      clean.sources = row.sources.map(source => {
        if (!source || typeof source.title !== 'string' || source.title.length > 500) throw new AdminError(400, 'invalid_sources', '参考链接格式不正确。');
        return {title: source.title, url: httpLink(source.url)};
      });
      const items = current.data.items.slice();
      if (input.index < 0) items.push(clean);
      else items[input.index] = {...items[input.index], ...clean};
      return adminJson(await saveEditorial(env, current, items));
    }
    if (path === '/api/admin/image') {
      if (!['image/png', 'image/jpeg', 'image/webp'].includes(input?.mime) ||
          typeof input.data !== 'string' || !/^[A-Za-z0-9+/]+={0,2}$/.test(input.data)) {
        throw new AdminError(400, 'invalid_image', '仅支持 PNG、JPEG 或 WebP 图片。');
      }
      let bytes;
      try { bytes = decodeBase64(input.data); }
      catch { throw new AdminError(400, 'invalid_image', '图片编码不正确。'); }
      const prefix = Array.from(bytes.slice(0,12));
      const valid = input.mime === 'image/png' ? prefix.slice(0,8).join() === '137,80,78,71,13,10,26,10' :
        input.mime === 'image/jpeg' ? prefix.slice(0,3).join() === '255,216,255' :
          String.fromCharCode(...prefix.slice(0,4)) === 'RIFF' && String.fromCharCode(...prefix.slice(8,12)) === 'WEBP';
      if (!valid || bytes.length > 1024 * 1024) throw new AdminError(400, 'invalid_image', '图片格式不匹配，或超过 1 MB。');
      const hash = [...new Uint8Array(await crypto.subtle.digest('SHA-256', bytes))].map(b => b.toString(16).padStart(2,'0')).join('');
      const extension = {'image/png':'png','image/jpeg':'jpg','image/webp':'webp'}[input.mime];
      const file = 'docs/assets/uploads/quick-' + hash + '.' + extension;
      try {
        await github(env, 'contents/' + file, {method:'PUT', body:JSON.stringify({
          branch:'main', message:'content: upload Quick Post image', content:input.data
        })});
      } catch (error) {
        if (error.code !== 'conflict') throw error;
        // A content-addressed path may already exist. Prove the bytes before reusing it.
        const existing = await github(env, 'contents/' + file + '?ref=main');
        if ((existing.content || '').replace(/\s/g,'') !== input.data) throw error;
      }
      return adminJson({path:file.slice(4), status:'saved', message:'图片已保存，等待部署。'});
    }
    if (path === '/api/admin/sources') {
      const allowed = ['operation','source_type','source_key','name','endpoint','category','enabled','reason'];
      if (!input || !['add','update','pause','resume','remove'].includes(input.operation) ||
          !['rss','telegram','github','reddit','hackernews','google_news','gdelt','ossinsight'].includes(input.source_type)) {
        throw new AdminError(400, 'invalid_source', '来源操作不正确。');
      }
      const inputs = Object.fromEntries(allowed.map(key => [key, String(input[key] ?? '').slice(0,2048)]));
      if (!inputs.reason.trim()) throw new AdminError(400, 'reason_required', '请填写调整原因。');
      await github(env, 'actions/workflows/source-change.yml/dispatches', {method:'POST',
        body:JSON.stringify({ref:'main', inputs})});
      return adminJson({status:'queued', message:'来源变更已提交检查，将创建待审核 PR；尚未修改生产来源。'}, 202);
    }
    throw new AdminError(404, 'not_found', '接口不存在。');
  } catch (error) {
    const known = error instanceof AdminError;
    if (!known) console.error(JSON.stringify({event:'admin_request_failed'}));
    return adminJson({error:{code:known ? error.code : 'internal_error',
      message:known ? error.message : '服务暂时不可用，草稿未清除，请稍后重试。'}}, known ? error.status : 500);
  }
}

const MARKDOWN_ROUTES = new Map([
  ['/', 'zh'],
  ['/en', 'en'],
  ['/en/', 'en']
]);
const JSON_API_PATHS = new Set(['/api/latest.json', '/api/editions.json', '/api/events.json', '/api/quick-posts.json']);
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
    `- [Quick Post JSON](${SITE_ORIGIN}/api/quick-posts.json)`,
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
  if (url.pathname === '/service-worker.js' || url.pathname === '/pwa-version.json') {
    return responseWithHeaders(assetResponse, (headers) => {
      headers.set('Cache-Control', 'no-store');
      headers.set('CDN-Cache-Control', 'no-store');
      if (url.pathname === '/service-worker.js' && assetResponse.ok) {
        headers.set('Content-Type', 'application/javascript; charset=utf-8');
        headers.set('Service-Worker-Allowed', '/');
      }
    });
  }
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
  if (request.method !== 'GET' || request.headers.has('Authorization')) return null;
  const url = new URL(request.url);
  if (url.pathname === '/service-worker.js' || url.pathname === '/pwa-version.json') return null;
  if (url.pathname === '/s' || url.pathname.startsWith('/s/') ||
      url.pathname === '/admin' || url.pathname.startsWith('/admin/') ||
      url.searchParams.has('publication_check')) return null;
  // CSS and JavaScript must be able to recover from a deployment where new
  // markup reaches the edge before its matching asset. The query fingerprint
  // remains the primary cache key, but these files deliberately revalidate
  // quickly instead of freezing a mismatched response for a year.
  if (
    url.pathname.startsWith('/assets/css/') ||
    url.pathname.startsWith('/assets/js/')
  ) {
    return {ttl: 300, browserTtl: 300};
  }
  if (url.pathname.startsWith('/assets/images/')) {
    return url.searchParams.has('v')
      ? {ttl: 31536000, browserTtl: 31536000, immutable: true}
      : {ttl: 300, browserTtl: 300};
  }
  if (url.pathname.startsWith('/assets/')) {
    return url.searchParams.has('v')
      ? {ttl: 31536000, browserTtl: 31536000, immutable: true}
      : {ttl: 300, browserTtl: 300};
  }
  if (DATED_EDITION_PATH.test(url.pathname)) return {ttl: 300};
  if (url.pathname === '/api/editions.json') return {ttl: 1800};
  if (url.pathname === '/api/events.json' || EVENT_DETAIL_PATH.test(url.pathname)) return {ttl: 300};
  if (url.pathname === '/api/latest.json') return {ttl: 600};
  if (url.pathname === '/feed-zh.xml' || url.pathname === '/feed-en.xml') return {ttl: 1800};
  if (url.pathname === '/' || url.pathname === '/en' || url.pathname === '/en/') return {ttl: 300};
  return {ttl: 600};
}

function cacheKey(request) {
  const url = new URL(request.url);
  // Leave the old immutable namespace behind when rolling out this policy.
  url.searchParams.set('__bmt_cache', 'mutable-v2');
  if (MARKDOWN_ROUTES.has(url.pathname)) {
    url.searchParams.set(
      '__bmt_variant',
      acceptsMarkdown(request.headers.get('Accept')) ? 'markdown' : 'html'
    );
  }
  return new Request(url, {method: 'GET'});
}

function cachedResponse(response, status, policy) {
  return responseWithHeaders(response, (headers) => {
    headers.set('X-BMTNews-Cache', status);
    if (policy) {
      const suffix = policy.immutable ? ', immutable' : ', must-revalidate';
      headers.set('Cache-Control', `public, max-age=${policy.browserTtl ?? 0}${suffix}`);
      headers.set('CDN-Cache-Control', `public, max-age=${policy.ttl}${suffix}`);
    }
  });
}

export async function handleRequest(request, env, ctx) {
  if (isAdminPath(new URL(request.url).pathname)) return handleAdmin(request, env);
  const policy = cachePolicy(request);
  const cache = globalThis.caches?.default;
  if (!policy || !cache) return handleOriginRequest(request, env);

  const key = cacheKey(request);
  const hit = await cache.match(key).catch(() => undefined);
  if (hit) return cachedResponse(hit, 'HIT', policy);

  const response = await handleOriginRequest(request, env);
  if (!response.ok || response.headers.has('Set-Cookie') ||
      /\b(no-store|private)\b/i.test(response.headers.get('Cache-Control') || '')) {
    return cachedResponse(response, 'BYPASS');
  }
  const stored = responseWithHeaders(response.clone(), (headers) => {
    const suffix = policy.immutable ? ', immutable' : ', stale-while-revalidate=60';
    headers.set('Cache-Control', `public, max-age=${policy.ttl}${suffix}`);
    headers.set('CDN-Cache-Control', `public, max-age=${policy.ttl}${suffix}`);
    headers.delete('Set-Cookie');
  });
  const write = cache.put(key, stored).catch((error) => {
    console.warn(JSON.stringify({event: 'edge_cache_write_failed', message: String(error?.message || error)}));
  });
  if (ctx?.waitUntil) ctx.waitUntil(write);
  else await write;
  return cachedResponse(response, 'MISS', policy);
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
