(() => {
  'use strict';
  const status = document.querySelector('[data-quick-post-status]');
  if (!status) return;
  const fallback = document.querySelector('[data-quick-post-unplaced]');
  const en = document.documentElement.lang.startsWith('en');
  let version = 0, knownDates = '', timer;
  function card(post) {
    const node = document.createElement('article');
    node.className = 'quick-post-public';
    node.dataset.quickPost = post.id;
    const meta = document.createElement('small');
    meta.textContent = 'Quick Post · ' + post.date + (post.breaking ? ' · Breaking' : '') + (post.pin ? ' · PIN' : '');
    node.append(meta);
    for (const text of post.body.split(/\n\s*\n/)) {
      const paragraph = document.createElement('p');
      paragraph.textContent = text;
      paragraph.style.whiteSpace = 'pre-wrap';
      node.append(paragraph);
    }
    if (/^\/assets\/uploads\/quick-[a-f0-9]{64}\.(png|jpg|webp)$/.test(post.image)) {
      const image = document.createElement('img');
      image.src = post.image; image.alt = en ? 'Quick Post image' : 'Quick Post 配图'; image.loading = 'lazy';
      node.append(image);
    }
    if (post.url) {
      try {
        const url = new URL(post.url);
        if (['http:', 'https:'].includes(url.protocol) && !url.username && !url.password) {
          const link = document.createElement('a');
          link.href = url.href; link.target = '_blank'; link.rel = 'noopener noreferrer';
          link.textContent = en ? 'Source ↗' : '原文 ↗'; node.append(link);
        }
      } catch {}
    }
    return node;
  }
  function dates() {
    return [...new Set([...document.querySelectorAll('.daily-day[data-date]')].map(day => day.dataset.date))].sort().join(',');
  }
  async function refresh() {
    const run = ++version;
    knownDates = dates();
    // Remove previously rendered content when verification fails; never present it as current.
    document.querySelectorAll('[data-quick-post]').forEach(node => node.remove());
    status.textContent = en ? 'Loading Quick Post…' : '正在核对 Quick Post…';
    try {
      const today = new Intl.DateTimeFormat('en-CA', {timeZone: 'Asia/Shanghai', year: 'numeric', month: '2-digit', day: '2-digit'}).format(new Date());
      const yesterday = new Date(Date.parse(today) - 86400000).toISOString().slice(0, 10);
      const wanted = [...new Set([today, yesterday, ...knownDates.split(',').filter(Boolean)])];
      const queries = []; // Include recent posts even before today's daily edition exists.
      for (let i = 0; i < wanted.length; i += 10) queries.push('?' + wanted.slice(i, i + 10).map(day => 'date=' + encodeURIComponent(day)).join('&'));
      const rows = [];
      let revision;
      for (const query of queries) {
        const response = await fetch('/api/quick-posts.json' + query, {cache: 'no-store', signal: AbortSignal.timeout(15000)});
        if (!response.ok) throw Error('unavailable');
        const payload = await response.json();
        if (!Array.isArray(payload.items) || !payload.revision) throw Error('unverified');
        if (revision && revision !== payload.revision) throw Error('registry changed during history read');
        revision = payload.revision;
        rows.push(...payload.items);
      }
      if (run !== version) return;
      const posts = [...new Map(rows.map(post => [post.id, post])).values()];
      for (const post of posts) {
        const day = [...document.querySelectorAll('.daily-day[data-date]')].find(day => day.dataset.date === post.date);
        const stream = day?.querySelector('.daily-story-stream');
        if (!stream) { fallback.append(card(post)); continue; }
        const stories = [...stream.children].filter(node => node.classList.contains('digest-item'));
        const position = Number.isInteger(post.position) ? Math.min(post.position, stories.length) : 0;
        stream.insertBefore(card(post), stories[position] || null);
      }
      status.textContent = '';
    } catch {
      if (run !== version) return;
      status.textContent = en ? 'Quick Post is unavailable. ' : 'Quick Post 暂时无法核实。';
      const retry = document.createElement('button');
      retry.type = 'button'; retry.textContent = en ? 'Retry' : '重试'; retry.onclick = refresh;
      status.append(retry);
    }
  }
  const observer = new MutationObserver(() => {
    if (dates() !== knownDates) { clearTimeout(timer); timer = setTimeout(refresh, 50); }
  });
  observer.observe(document.querySelector('.day-stream') || fallback.parentElement, {childList: true, subtree: true});
  window.addEventListener('focus', refresh);
  refresh();
})();
