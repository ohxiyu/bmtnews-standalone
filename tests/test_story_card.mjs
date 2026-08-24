import assert from 'node:assert/strict';
import {readFile} from 'node:fs/promises';
import test from 'node:test';

const source = await readFile(new URL('../docs/assets/js/story-card.js', import.meta.url), 'utf8');
const moduleUrl = `data:text/javascript;base64,${Buffer.from(source).toString('base64')}`;
const card = await import(moduleUrl);

test('image sharing sends only the generated PNG file', () => {
  const file = {name: 'bmtnews-story.png', type: 'image/png'};
  const payload = card.imageShareData(file);

  assert.deepEqual(Object.keys(payload), ['files']);
  assert.deepEqual(payload.files, [file]);
  assert.equal('title' in payload, false);
  assert.equal('text' in payload, false);
  assert.equal('url' in payload, false);
});
