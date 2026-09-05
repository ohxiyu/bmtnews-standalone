/* Device-local reading tools; intentionally no account, analytics or AI calls. */
export function canonicalURL(value, base) {
  try {
    const url = new URL(value, base);
    if (!['http:', 'https:'].includes(url.protocol) || url.username || url.password) return null;
    for (const key of [...url.searchParams.keys()]) {
      if (key.startsWith('utm_') || ['source', 'publication_check', 'fbclid', 'gclid'].includes(key)) url.searchParams.delete(key);
    }
    url.hash = '';
    return url.href;
  } catch { return null; }
}

export function storyKey(url, language = 'zh') {
  // Two independent 32-bit hashes: short anchors, independent of rank or title edits.
  let a = 2166136261;
  let b = 5381;
  for (const char of `${language}:${url}`) {
    a = Math.imul(a ^ char.charCodeAt(0), 16777619);
    b = Math.imul(b, 33) ^ char.charCodeAt(0);
  }
  return `${(a >>> 0).toString(36)}-${(b >>> 0).toString(36)}`;
}

export function createReaderStore(storage, failure = () => {}) {
  const prefix = 'bmt-reader-v1:';
  const limits = {bookmark: 200, read: 1000, position: 20};
  function entries(kind) {
    const rows = [];
    try {
      for (let i = 0; i < storage.length; i++) {
        const key = storage.key(i);
        if (!key?.startsWith(`${prefix}${kind}:`)) continue;
        try {
          const value = JSON.parse(storage.getItem(key));
          if (value && typeof value === 'object' && Number.isFinite(value.savedAt)) rows.push({key, ...value});
        } catch { /* Ignore malformed individual records, not the entire collection. */ }
      }
    } catch { failure(); }
    return rows.sort((a, b) => b.savedAt - a.savedAt);
  }
  return {
    entries,
    get(kind, id) {
      try { return JSON.parse(storage.getItem(`${prefix}${kind}:${id}`)); } catch { return null; }
    },
    put(kind, id, value) {
      if (!Object.hasOwn(limits, kind)) return false;
      try {
        // Separate keys avoid a whole-collection read/modify/write race across tabs.
        storage.setItem(`${prefix}${kind}:${id}`, JSON.stringify({...value, savedAt: Date.now()}));
        for (const old of entries(kind).slice(limits[kind])) storage.removeItem(old.key);
        return true;
      } catch { failure(); return false; }
    },
    remove(kind, id) {
      try { storage.removeItem(`${prefix}${kind}:${id}`); return true; } catch { failure(); return false; }
    },
    clear() {
      try {
        const keys = [];
        for (let i = 0; i < storage.length; i++) if (storage.key(i)?.startsWith(prefix)) keys.push(storage.key(i));
        keys.forEach(key => storage.removeItem(key));
        return true;
      } catch { failure(); return false; }
    }
  };
}

export function isRead(record, revision) {
  return Boolean(record && record.revision === revision);
}

export function installedMode(mediaMatches, appleStandalone) {
  return Boolean(mediaMatches || appleStandalone === true);
}

export function waitingUpdate(hasWaitingWorker, hasController) {
  // A first installation briefly enters "waiting" before automatic activation.
  return Boolean(hasWaitingWorker && hasController);
}

function initReader() {
  const main = document.querySelector('#content');
  const opener = document.querySelector('[data-reader-open]');
  if (!main || !opener || /^\/(admin|s)(\/|$)/.test(location.pathname)) return;
  const en = document.documentElement.lang.startsWith('en');
  const tr = (zh, english) => en ? english : zh;
  const language = en ? 'en' : 'zh';
  const origin = location.origin;
  const route = canonicalURL(location.href, origin);
  const routeKey = storyKey(route, language);
  const rows = new Map();
  let registration;
  const controlledAtLoad = Boolean(navigator.serviceWorker?.controller);
  let cacheMessage = tr('离线功能准备中', 'Preparing offline reading');
  let updateReady = false;
  let reloadOnActivation = false;
  let cachePaused = false;

  function element(tag, text, className) {
    const node = document.createElement(tag);
    if (text) node.textContent = text;
    if (className) node.className = className;
    return node;
  }
  function button(label, action) {
    const node = element('button', label);
    node.type = 'button';
    node.addEventListener('click', action);
    return node;
  }
  const notice = element('div', '', 'reader-notice');
  notice.setAttribute('role', 'status');
  notice.hidden = true;
  document.body.append(notice);
  let noticeTimer;
  function notify(message) {
    notice.textContent = message;
    notice.hidden = false;
    clearTimeout(noticeTimer);
    noticeTimer = setTimeout(() => { notice.hidden = true; }, 5000);
  }
  let storage;
  try { storage = localStorage; } catch { /* Private browsing can deny storage entirely. */ }
  const store = createReaderStore(storage, () => notify(tr('本机存储不可用或已满，刚才的操作未能保存。', 'Device storage is unavailable or full; the change could not be saved.')));
  let initialPosition = store.get('position', routeKey);
  let readingCleared = false;

  const banner = element('aside', '', 'reader-banner');
  const offline = document.querySelector('meta[name="bmt-offline"]');
  const connectivity = element('span');
  const update = button(tr('有新内容 · 点击更新', 'New content · Update'), async () => {
    savePosition();
    try { sessionStorage.setItem('bmt-reader-restore', routeKey); } catch { /* Optional. */ }
    update.disabled = true;
    if (registration?.waiting) {
      reloadOnActivation = true;
      registration.waiting.postMessage({type: 'ACTIVATE'});
      setTimeout(() => { if (reloadOnActivation) reloadFresh(); }, 2500);
    } else reloadFresh();
  });
  update.hidden = true;
  banner.append(connectivity, update);
  document.querySelector('.site-header').after(banner);
  function showConnectivity() {
    const cached = offline && Number(offline.content);
    connectivity.textContent = cached ? tr('正在阅读缓存 · 保存于 ', 'Reading saved copy · ') + new Date(cached).toLocaleString(en ? 'en-GB' : 'zh-CN') :
      (!navigator.onLine ? tr('已离线 · 可继续阅读已保存内容', 'Offline · Saved content remains readable') : '');
    banner.hidden = !connectivity.textContent && !updateReady;
    if (cached) document.querySelectorAll('.today-edition-status').forEach(node => { node.hidden = true; });
  }
  function reloadFresh() {
    reloadOnActivation = false;
    const url = new URL(location.href);
    url.searchParams.set('publication_check', `pwa-${Date.now()}`);
    location.replace(url.href);
  }
  if (new URL(location.href).searchParams.get('publication_check')?.startsWith('pwa-')) {
    const clean = new URL(location.href);
    clean.searchParams.delete('publication_check');
    history.replaceState(history.state, '', clean);
  }
  showConnectivity();
  window.addEventListener('offline', showConnectivity);
  window.addEventListener('online', () => { showConnectivity(); checkVersion(); });

  const dialog = element('dialog', '', 'reader-dialog');
  dialog.setAttribute('aria-labelledby', 'reader-title');
  const heading = element('h2', tr('我的阅读', 'My reading'));
  heading.id = 'reader-title';
  const close = button(tr('关闭', 'Close'), () => dialog.close());
  const header = element('header');
  header.append(heading, close);
  const explanation = element('p', tr('收藏、已读和阅读位置仅保存在此设备，不会同步。清除浏览器数据或卸载 App 可能丢失记录；收藏不保证全文离线可用。', 'Bookmarks, read markers and reading positions stay on this device, without sync. Clearing browser data or uninstalling may remove them. A bookmark does not guarantee offline availability.'), 'reader-muted');
  const resume = button(tr('继续上次阅读', 'Continue reading'), () => {
    dialog.close();
    restore(initialPosition || store.get('position', routeKey));
  });
  resume.hidden = !initialPosition?.id;
  const saveThisPage = button(tr('收藏本页', 'Bookmark this page'), () => {
    const existing = store.get('bookmark', routeKey);
    const ok = existing ? store.remove('bookmark', routeKey) : store.put('bookmark', routeKey, {
      title: document.title, url: route, source: route, id: routeKey, language
    });
    if (ok) { refreshButtons(); renderLibrary(); }
  });
  const toolsRow = element('div', '', 'reader-tools');
  toolsRow.append(resume, saveThisPage);
  const list = element('ol', '', 'reader-bookmarks');
  const cacheStatus = element('p', cacheMessage, 'reader-muted');
  cacheStatus.setAttribute('role', 'status');
  const clearCache = button(tr('清理离线缓存', 'Clear offline cache'), async () => {
    clearCache.disabled = true;
    cachePaused = true;
    const result = await messageWorker('CLEAR');
    cacheMessage = result?.ok ? tr('离线缓存已清空；下次打开页面时重新保存。收藏不受影响。', 'Offline cache cleared. It resumes on the next page visit. Bookmarks are unchanged.') : tr('缓存清理失败，请重试。', 'Could not clear cache. Please retry.');
    cacheStatus.textContent = cacheMessage;
    clearCache.disabled = false;
  });
  const clearReading = button(tr('清除阅读记录', 'Clear reading data'), () => {
    if (!window.confirm(tr('清除本机全部收藏、已读与阅读位置？此操作无法撤销。', 'Delete all local bookmarks, read markers and positions? This cannot be undone.'))) return;
    if (store.clear()) {
      initialPosition = null;
      readingCleared = true;
      resume.hidden = true;
      refreshButtons(); renderLibrary();
      notify(tr('阅读记录已清除', 'Reading data cleared'));
    }
  });
  const maintenance = element('div', '', 'reader-tools');
  const checkUpdate = button(tr('检查更新', 'Check for updates'), async () => {
    checkUpdate.disabled = true;
    const checked = await checkVersion(true);
    cacheStatus.textContent = updateReady ? tr('发现新版本，关闭面板后点击页面顶部的更新提示。', 'An update is ready. Close this panel and select Update above the page.') :
      (checked ? tr('当前已是最新版本。', 'You are up to date.') : tr('暂时无法检查更新，请联网后重试。', 'Could not check for updates. Reconnect and retry.'));
    checkUpdate.disabled = false;
  });
  maintenance.append(checkUpdate, clearCache, clearReading);
  dialog.append(header, explanation, toolsRow, list, cacheStatus, maintenance);
  document.body.append(dialog);
  opener.hidden = false;
  opener.addEventListener('click', () => { renderLibrary(); dialog.showModal(); updateCacheStatus(); });

  function renderLibrary() {
    list.replaceChildren();
    saveThisPage.textContent = store.get('bookmark', routeKey) ? tr('取消本页收藏', 'Remove page bookmark') : tr('收藏本页', 'Bookmark this page');
    const bookmarks = store.entries('bookmark');
    for (const record of bookmarks) {
      const href = canonicalURL(record.url, origin);
      if (!href || new URL(href).origin !== origin || typeof record.title !== 'string') continue;
      const li = element('li');
      const link = element('a', record.title);
      link.href = href + (/^[a-z0-9]+-[a-z0-9]+$/.test(record.anchor) ? `#reader-${record.anchor}` : '');
      const remove = button(tr('移除', 'Remove'), () => {
        const id = record.key.split(':').at(-1);
        if (store.remove('bookmark', id)) { refreshButtons(); renderLibrary(); }
      });
      li.append(link, remove);
      list.append(li);
    }
    if (!list.children.length) list.append(element('li', tr('尚无收藏。在新闻下方点击“收藏”即可保存。', 'No bookmarks yet. Select Bookmark below a story to save it.')));
  }

  function recordFor(row) {
    const title = row.querySelector('h2 a, h3 a');
    if (!title) return null;
    const source = canonicalURL(title.href, origin);
    if (!source) return null;
    const id = storyKey(source, language);
    const date = row.closest('[data-date]')?.dataset.date;
    const edition = date && /^20\d\d-\d\d-\d\d$/.test(date) ? `/${date.replaceAll('-', '/')}/summary-${language}.html` : null;
    const url = new URL(source).origin === origin ? source : new URL(edition || location.pathname, origin).href;
    const revision = row.dataset.contentRevision || storyKey(row.textContent.trim(), language);
    const anchor = new URL(source).origin === origin ? null : id;
    return {id, source, url, revision, anchor, title: title.textContent.trim(), language};
  }
  function refreshButtons() {
    for (const {row, record, bookmark, read} of rows.values()) {
      const saved = Boolean(store.get('bookmark', record.id));
      const viewed = isRead(store.get('read', record.id), record.revision);
      bookmark.textContent = saved ? tr('已收藏', 'Bookmarked') : tr('收藏', 'Bookmark');
      bookmark.setAttribute('aria-pressed', String(saved));
      read.textContent = viewed ? tr('已读', 'Read') : tr('标为已读', 'Mark read');
      read.setAttribute('aria-pressed', String(viewed));
      row.classList.toggle('reader-is-read', viewed);
    }
  }
  function enhance() {
    for (const row of main.querySelectorAll('.digest-item')) {
      if (row.dataset.readerId) continue;
      const record = recordFor(row);
      if (!record) continue;
      row.dataset.readerId = record.id;
      const bookmark = button(tr('收藏', 'Bookmark'), () => {
        const exists = store.get('bookmark', record.id);
        const ok = exists ? store.remove('bookmark', record.id) : store.put('bookmark', record.id, record);
        if (ok) refreshButtons();
      });
      const read = button(tr('标为已读', 'Mark read'), () => {
        const exists = isRead(store.get('read', record.id), record.revision);
        const ok = exists ? store.remove('read', record.id) : store.put('read', record.id, {revision: record.revision});
        if (ok) refreshButtons();
      });
      const actions = element('div', '', 'reader-item-actions');
      actions.append(bookmark, read);
      (row.querySelector('.digest-item-content') || row).append(actions);
      // A repeated story on two dates shares state, but both copies get controls.
      rows.set(row, {row, record, bookmark, read});
    }
    refreshButtons();
  }
  enhance();
  new MutationObserver(records => {
    if (records.some(record => [...record.addedNodes].some(node => node.nodeType === 1 && (node.matches?.('.digest-item') || node.querySelector?.('.digest-item'))))) enhance();
  }).observe(main, {childList: true, subtree: true});
  window.addEventListener('storage', () => { refreshButtons(); if (dialog.open) renderLibrary(); });

  function savePosition() {
    if (readingCleared) return;
    if (window.scrollY < 100) return;
    const top = document.querySelector('.site-header').getBoundingClientRect().bottom + 12;
    let candidate;
    for (const entry of rows.values()) {
      const bounds = entry.row.getBoundingClientRect();
      if (bounds.bottom > top && bounds.top < window.innerHeight) { candidate = {entry, bounds}; break; }
    }
    if (candidate) store.put('position', routeKey, {
      id: candidate.entry.record.id, url: candidate.entry.record.url,
      offset: Math.max(0, top - candidate.bounds.top)
    });
    else {
      const node = [...main.querySelectorAll('[id]')].find(node => node.getBoundingClientRect().bottom > top);
      if (node?.id) store.put('position', routeKey, {anchor: node.id, url: route, id: node.id, offset: 0});
    }
  }
  function restore(position) {
    if (!position) return;
    const found = position.anchor ? document.getElementById(position.anchor) : [...rows.values()].find(entry => entry.record.id === position.id)?.row;
    if (found) {
      const headerHeight = document.querySelector('.site-header').getBoundingClientRect().height;
      window.scrollTo({top: window.scrollY + found.getBoundingClientRect().top - headerHeight - 12 + Math.min(Number(position.offset) || 0, Math.max(0, found.offsetHeight - 80)), behavior: 'instant'});
    } else if (position.url && canonicalURL(position.url, origin) !== route && new URL(position.url, origin).origin === origin) {
      location.href = `${position.url}#reader-${position.id}`;
    } else notify(tr('这条内容已不在当前页面，可从收藏或历史日期查找。', 'This story is no longer on this page. Check saved items or an earlier date.'));
  }
  window.addEventListener('pagehide', savePosition);
  document.addEventListener('visibilitychange', () => {
    if (document.hidden) savePosition();
    else checkVersion();
  });
  let restoreAfterUpdate = false;
  try {
    restoreAfterUpdate = sessionStorage.getItem('bmt-reader-restore') === routeKey;
    if (restoreAfterUpdate) sessionStorage.removeItem('bmt-reader-restore');
  } catch { /* Optional. */ }
  const anchor = location.hash.match(/^#reader-([a-z0-9]+-[a-z0-9]+)$/)?.[1];
  window.addEventListener('pageshow', event => {
    if (event.persisted) return; // The browser's back/forward cache already restored the page.
    if (anchor) requestAnimationFrame(() => restore({id: anchor, offset: 0}));
    else if (restoreAfterUpdate || performance.getEntriesByType('navigation')[0]?.type === 'back_forward') requestAnimationFrame(() => restore(initialPosition));
  });

  const display = matchMedia('(display-mode: standalone)');
  const applyMode = () => document.documentElement.classList.toggle('pwa-installed', installedMode(display.matches, navigator.standalone));
  applyMode();
  display.addEventListener('change', applyMode);

  async function messageWorker(type, extra = {}) {
    const worker = registration?.active || navigator.serviceWorker?.controller;
    if (!worker) return null;
    return new Promise(resolve => {
      const channel = new MessageChannel();
      const timer = setTimeout(() => { channel.port1.close(); resolve(null); }, type === 'WARM' ? 45000 : 10000);
      channel.port1.onmessage = event => { clearTimeout(timer); channel.port1.close(); resolve(event.data); };
      worker.postMessage({type, ...extra}, [channel.port2]);
    });
  }
  async function updateCacheStatus() {
    const status = await messageWorker('STATUS');
    if (status?.ok && !cachePaused) cacheMessage = tr(`离线已保存 ${status.count} 页 · 最多 30 页 / 30 天，浏览器可能自动回收。`, `${status.count} pages saved offline · Up to 30 pages / 30 days; the browser may evict them.`);
    cacheStatus.textContent = cacheMessage;
  }
  let lastCheck = 0;
  async function checkVersion(force = false) {
    if (!navigator.onLine || (!force && Date.now() - lastCheck < 60000)) return false;
    lastCheck = Date.now();
    try {
      const response = await fetch('/pwa-version.json', {cache: 'no-store', credentials: 'omit', signal: AbortSignal.timeout(5000)});
      if (!response.ok) return false;
      const current = await response.json();
      const build = document.querySelector('meta[name="bmt-build"]')?.content;
      if (current.build && build && current.build !== build) {
        updateReady = true;
        update.hidden = false;
        showConnectivity();
      }
      await registration?.update();
      return Boolean(current.build);
    } catch { return false; /* Reading stays uninterrupted on flaky networks. */ }
  }
  if ('serviceWorker' in navigator && window.isSecureContext) {
    navigator.serviceWorker.addEventListener('controllerchange', () => { if (reloadOnActivation) reloadFresh(); });
    navigator.serviceWorker.register('/service-worker.js', {scope: '/', updateViaCache: 'none'}).then(async value => {
      registration = value;
      checkVersion();
      const showUpdate = () => {
        if (waitingUpdate(registration.waiting, navigator.serviceWorker.controller)) {
          updateReady = true; update.hidden = false; showConnectivity();
        }
      };
      showUpdate();
      registration.addEventListener('updatefound', () => {
        registration.installing?.addEventListener('statechange', showUpdate);
      });
      await navigator.serviceWorker.ready;
      // Home already contains two complete days. Warm their canonical editions as well.
      const dates = [...document.querySelectorAll('.daily-day[data-date]')].slice(0, 2).map(node => `/${node.dataset.date.replaceAll('-', '/')}/summary-${language}.html`);
      if (!cachePaused && !offline) await messageWorker('WARM', {urls: controlledAtLoad ? dates : [location.href, ...dates]});
      await updateCacheStatus();
      checkVersion();
    }).catch(() => {
      cacheMessage = tr('此浏览器暂不能保存离线页面，在线阅读与本地收藏仍可使用。', 'Offline pages are unavailable in this browser. Online reading and local bookmarks still work.');
      cacheStatus.textContent = cacheMessage;
    });
  } else {
    cacheMessage = tr('此浏览器不支持离线页面，在线阅读不受影响。', 'This browser does not support offline pages. Online reading is unaffected.');
    cacheStatus.textContent = cacheMessage;
    checkVersion();
  }
}

if (typeof document !== 'undefined') initReader();
