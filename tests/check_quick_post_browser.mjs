// Local browser simulation only; no production content writes.
import assert from 'node:assert/strict';
import {readFile, mkdir} from 'node:fs/promises';
import {createRequire} from 'node:module';
const require=createRequire(import.meta.url);
const {chromium}=require(process.env.PLAYWRIGHT_MODULE||'playwright');
const browser=await chromium.launch({headless:true});
const source=await readFile(new URL('../docs/assets/js/quick-posts.js',import.meta.url),'utf8');
const css=await readFile(new URL('../docs/assets/css/editorial-ui.css',import.meta.url),'utf8');
for(const width of [390,1280])for(const language of ['zh','en']) {
 const page=await browser.newPage({viewport:{width,height:900},colorScheme:language==='en'?'dark':'light'});
 const errors=[];page.on('pageerror',e=>errors.push(e.message));
 let fail=false, posts=[0,1,2,3].map(position=>({id:'post-'+position,body:'人工信息 <script>安全文本</script>\n\n完整第二段 🚀',position,date:'2026-09-18',image:'',url:'javascript:bad'}));
 await page.route('https://bmt.news/**',route=>{
  if(route.request().url().includes('/api/quick-posts.json'))return route.fulfill({status:fail?503:200,json:fail?{error:{}}:{revision:'test-revision',items:posts}});
  return route.fulfill({body:`<!doctype html><html lang="${language}"><meta charset="utf-8"><style>${css}body{margin:16px;background:${language==='en'?'#171717':'#faf9f6'};color:${language==='en'?'#eee':'#222'};font:16px system-ui}.daily-story-stream{max-width:720px;margin:auto}.digest-item{padding:24px 0;border-bottom:1px solid #888}</style><div data-quick-post-status></div><div data-quick-post-unplaced></div><div class="day-stream"><section class="daily-day" data-date="2026-09-18"><div class="daily-story-stream"><article class="digest-item" id="a">日报新闻 1</article><article class="digest-item" id="b">日报新闻 2</article><article class="digest-item" id="c">日报新闻 3</article></div></section></div><script>${source}</script></html>`,contentType:'text/html'});
 });
 await page.goto('https://bmt.news/');await page.waitForFunction(()=>document.querySelectorAll('[data-quick-post]').length===4);
 assert.deepEqual(await page.locator('.daily-story-stream > *').evaluateAll(nodes=>nodes.map(n=>n.dataset.quickPost||n.id)),['post-0','a','post-1','b','post-2','c','post-3']);
 assert.equal(await page.locator('[data-quick-post] script').count(),0);assert.equal(await page.locator('[data-quick-post] a').count(),0);
 assert.equal(await page.evaluate(()=>document.documentElement.scrollWidth<=innerWidth),true);
 // Loading a historical edition triggers its Quick Posts, clamping beyond-last gaps.
 posts.push({id:'history',date:'2026-09-17',body:'历史刊期',position:99,image:'',url:''});
 await page.evaluate(()=>{const node=document.createElement('section');node.className='daily-day';node.dataset.date='2026-09-17';node.innerHTML='<div class="daily-story-stream"><article class="digest-item" id="old">历史新闻</article></div>';document.querySelector('.day-stream').append(node);});
 await page.waitForFunction(()=>document.querySelector('[data-quick-post="history"]'));
 assert.equal(await page.locator('[data-quick-post="history"]').evaluate(node=>node.previousElementSibling.id),'old');
 if(process.env.BROWSER_EVIDENCE_DIR){await mkdir(process.env.BROWSER_EVIDENCE_DIR,{recursive:true});await page.screenshot({path:process.env.BROWSER_EVIDENCE_DIR+`/stream-${width}-${language}.png`,fullPage:true});}
 posts=posts.filter(post=>post.id!=='post-1');await page.evaluate(()=>window.dispatchEvent(new Event('focus')));
 await page.waitForFunction(()=>document.querySelectorAll('[data-quick-post]').length===4);
 assert.equal(await page.locator('[data-quick-post="post-1"]').count(),0);
 fail=true;await page.evaluate(()=>window.dispatchEvent(new Event('focus')));await page.locator('[data-quick-post-status] button').waitFor();
 assert.equal(await page.locator('[data-quick-post]').count(),0);
 fail=false;await page.locator('[data-quick-post-status] button').click();await page.waitForFunction(()=>document.querySelectorAll('[data-quick-post]').length===4);
 assert.deepEqual(errors,[]);console.log('PASS Quick Post gaps/history/disable/failure/retry/XSS/layout',width,language);await page.close();
}
await browser.close();
