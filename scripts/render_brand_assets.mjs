// Run after build_brand_assets.py. Optional argument: installed sharp module path.
import {createRequire} from 'node:module';
import {readFile, writeFile, readdir, copyFile} from 'node:fs/promises';
const require = createRequire(import.meta.url);
const sharp = require(process.argv[2] || 'sharp');
const kit = new URL('../docs/media-kit/', import.meta.url);
const images = new URL('../docs/assets/images/', import.meta.url);
async function png(source, destination, width) {
  await sharp(await readFile(source), {density: 192}).resize({width}).png().toFile(destination.pathname);
}
for (const file of await readdir(kit)) {
  if (!file.endsWith('.svg')) continue;
  const width = file.includes('social') ? 1200 : file.includes('lockup') ? 1340 : 1024;
  await png(new URL(file, kit), new URL(file.replace('.svg', '.png'), kit), width);
}
for (const size of [192, 512]) {
  const path = new URL(`bmtnews-app-${size}-v1.png`, images);
  await png(new URL('bmtnews-app.svg', kit), path, size);
  await copyFile(path, new URL(`app-icon-${size}.png`, images));
}
await png(new URL('bmtnews-maskable.svg', kit), new URL('bmtnews-maskable-512-v1.png', images), 512);
await png(new URL('bmtnews-apple.svg', kit), new URL('bmtnews-apple-180-v1.png', images), 180);
await copyFile(new URL('bmtnews-apple-180-v1.png', images), new URL('apple-touch-icon.png', images));
await copyFile(new URL('bmtnews-social.png', kit), new URL('bmtnews-social-v1.png', images));
const frames = [];
for (const size of [16, 32, 48]) {
  const frame = await sharp(await readFile(new URL('bmtnews-app.svg', kit)), {density: 192})
    .resize(size, size).png().toBuffer();
  await writeFile(new URL(`bmtnews-favicon-${size}-v1.png`, images), frame);
  frames.push({size, frame});
}
// Standard ICO container with PNG frames; no platform-specific image editor.
const header = Buffer.alloc(6 + 16 * frames.length);
header.writeUInt16LE(1, 2); header.writeUInt16LE(frames.length, 4);
let offset = header.length;
frames.forEach(({size, frame}, index) => {
  const p = 6 + index * 16;
  header[p] = size; header[p + 1] = size;
  header.writeUInt16LE(1, p + 4); header.writeUInt16LE(32, p + 6);
  header.writeUInt32LE(frame.length, p + 8); header.writeUInt32LE(offset, p + 12);
  offset += frame.length;
});
await writeFile(new URL('../docs/favicon.ico', import.meta.url), Buffer.concat([header, ...frames.map(f => f.frame)]));
