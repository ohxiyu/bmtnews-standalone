import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';
import { runInNewContext } from 'node:vm';
import { test } from 'node:test';

const html = readFileSync(new URL('../docs/_includes/feed-home.html', import.meta.url), 'utf8');
const code = html.match(/<script>([\s\S]*?)<\/script>/)[1];

function render(time, latest = '2026-09-16', language = 'zh') {
  const copy = { textContent: '', getAttribute: name => name };
  const title = { textContent: 'preparing' };
  const date = {};
  const status = {
    hidden: true, hasAttribute: () => true, getAttribute: () => latest,
    querySelector: selector => selector === 'p' ? copy :
      selector === '[data-today-edition-title]' ? title : date,
    closest: () => ({getAttribute: () => language}),
  };
  class Clock extends Date { constructor() { super(time); } }
  runInNewContext(code, {Date: Clock, Intl, document: {currentScript: {previousElementSibling: status}}});
  return {status, copy, title, date};
}

test('07:26 is generating, not overdue, and uses Shanghai date across UTC midnight', () => {
  const value = render('2026-09-16T23:26:00Z');
  assert.equal(value.status.hidden, false);
  assert.equal(value.date.textContent, '2026.09.17');
  assert.equal(value.title.textContent, 'preparing');
  assert.equal(value.copy.textContent, 'data-before-cutoff');
});
test('overdue boundary matches Worker at 08:11, in both languages', () => {
  assert.equal(render('2026-09-17T00:10:59Z').title.textContent, 'preparing');
  assert.equal(render('2026-09-17T00:11:00Z').title.textContent, '今日版延迟，正在恢复');
  assert.match(render('2026-09-17T00:11:00Z', '2026-09-16', 'en').title.textContent, /delayed/);
});
test('current edition hides stale-edition banner regardless of clock', () => {
  assert.equal(render('2026-09-17T01:00:00Z', '2026-09-17').status.hidden, true);
});
