import test from 'node:test';
import assert from 'node:assert/strict';
import {readFile} from 'node:fs/promises';

const source = await readFile(new URL('../docs/assets/js/pwa-reader.js', import.meta.url), 'utf8');
const {canonicalURL, storyKey, createReaderStore, isRead, installedMode, waitingUpdate, readingSize} = await import(`data:text/javascript;base64,${Buffer.from(source).toString('base64')}`);
test('reading size accepts only the shared supported presets', () => {
  for (const size of [14, 15, 17, '14', '15', '17']) assert.equal(readingSize(size), String(size));
  for (const size of [null, undefined, '', '99', '17px', 'initial', {}]) assert.equal(readingSize(size), '15');
  assert.match(source, /setProperty\('--reading-size'/);
  assert.match(source, /bmtnews-reading-size/);
});
function storage() {
  const data = new Map();
  return {get length() { return data.size; }, key: i => [...data.keys()][i], getItem: k => data.get(k) ?? null,
    setItem: (k, v) => data.set(k, v), removeItem: k => data.delete(k)};
}
test('story identity ignores tracking and rank but preserves meaningful query and language', () => {
  const a = canonicalURL('https://example.org/a?id=123&utm_source=x#part', 'https://bmt.news');
  const b = canonicalURL('https://example.org/a?id=123', 'https://bmt.news');
  assert.equal(storyKey(a), storyKey(b));
  assert.notEqual(storyKey(a), storyKey(a, 'en'));
  assert.notEqual(storyKey(a), storyKey(canonicalURL('https://example.org/a?id=124')));
  assert.equal(canonicalURL('javascript:alert(1)', 'https://bmt.news'), null);
  assert.equal(canonicalURL('https://user:secret@example.org/'), null);
});
test('changed content becomes unread, same revision reuses local state', () => {
  assert.equal(isRead({revision: 'v1'}, 'v1'), true);
  assert.equal(isRead({revision: 'v1'}, 'v2'), false);
  assert.equal(isRead(null, 'v1'), false);
});
test('bookmarks persist across reloads and independent tabs do not overwrite the collection', () => {
  const disk = storage();
  const first = createReaderStore(disk), second = createReaderStore(disk);
  first.put('bookmark', 'one', {title: 'One'});
  second.put('bookmark', 'two', {title: 'Two'});
  assert.equal(createReaderStore(disk).entries('bookmark').length, 2);
  assert.equal(first.get('bookmark', 'two').title, 'Two');
  assert.equal(second.remove('bookmark', 'one'), true);
  assert.equal(first.entries('bookmark').length, 1);
});
test('bounded reading data leaves unrelated local storage intact', () => {
  const disk = storage();
  disk.setItem('bmtnews-theme', 'dark');
  const store = createReaderStore(disk);
  for (let i = 0; i < 205; i++) store.put('bookmark', String(i), {title: String(i)});
  assert.equal(store.entries('bookmark').length, 200);
  for (let i = 0; i < 25; i++) store.put('position', String(i), {id: `story-${i}`, offset: 75});
  assert.equal(store.entries('position').length, 20);
  store.clear();
  assert.equal(disk.length, 1);
  assert.equal(disk.getItem('bmtnews-theme'), 'dark');
});
test('corrupt storage and quota denial fail safely and never report a successful save', () => {
  const disk = storage();
  disk.setItem('bmt-reader-v1:bookmark:bad', '{broken');
  let errors = 0;
  const store = createReaderStore(disk, () => errors++);
  assert.deepEqual(store.entries('bookmark'), []);
  disk.setItem = () => { throw new Error('QuotaExceeded'); };
  assert.equal(store.put('bookmark', 'new', {title: 'New'}), false);
  assert.equal(errors, 1);
  assert.equal(store.put('unknown', 'new', {}), false);
});
test('standalone detection does not change ordinary mobile or desktop browser navigation', () => {
  assert.equal(installedMode(false, undefined), false);
  assert.equal(installedMode(true, undefined), true);
  assert.equal(installedMode(false, true), true);
  assert.equal(installedMode(false, 'true'), false);
});
test('a first install does not report an update, but a waiting replacement does', () => {
  assert.equal(waitingUpdate(true, false), false);
  assert.equal(waitingUpdate(false, true), false);
  assert.equal(waitingUpdate(true, true), true);
});
test('layout and manifest keep four app sections and versioned local reader assets', async () => {
  const layout = await readFile(new URL('../docs/_layouts/default.html', import.meta.url), 'utf8');
  const nav = layout.match(/<nav class="pwa-bottom-nav"[\s\S]*?<\/nav>/)[0];
  assert.equal((nav.match(/<a /g) || []).length, 4);
  const manifest = JSON.parse(await readFile(new URL('../docs/manifest.webmanifest', import.meta.url), 'utf8'));
  assert.equal(manifest.shortcuts.length, 4);
  const head = await readFile(new URL('../docs/_includes/head-custom.html', import.meta.url), 'utf8');
  assert.match(head, /pwa-reader\.js[^\n]+asset_version/);
  assert.match(head, /unless page.page_type == "source_console" or page.noindex/);
  assert.match(source, /pagehide.*savePosition/);
  assert.match(source, /event.persisted/);
  assert.match(source, /record.id === position.id/);
});
