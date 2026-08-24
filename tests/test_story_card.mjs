import assert from 'node:assert/strict';
import {readFile} from 'node:fs/promises';
import test from 'node:test';

const source = await readFile(new URL('../docs/assets/js/story-card.js', import.meta.url), 'utf8');
const moduleUrl = `data:text/javascript;base64,${Buffer.from(source).toString('base64')}`;
const card = await import(moduleUrl);

test('image clipboard writes only the generated PNG blob', async () => {
  const blob = {type: 'image/png'};
  const writes = [];
  class MockClipboardItem {
    constructor(data) {
      this.data = data;
    }
  }

  await card.copyImageToClipboard(
    blob,
    {write: async (items) => writes.push(items)},
    MockClipboardItem,
  );

  assert.equal(writes.length, 1);
  assert.equal(writes[0].length, 1);
  assert.deepEqual(Object.keys(writes[0][0].data), ['image/png']);
  assert.equal(writes[0][0].data['image/png'], blob);
});
