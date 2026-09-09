// Task-owned browser simulation. No production writes or real credentials.
import assert from 'node:assert/strict';
import {readFile,mkdir} from 'node:fs/promises';
import {createRequire} from 'node:module';
const require=createRequire(import.meta.url);
const {chromium}=require(process.env.PLAYWRIGHT_MODULE || 'playwright');
const origin='https://bmt.news';
const browser=await chromium.launch({headless:true});
let writes=0, failSave=false;
for(const viewport of [{width:390,height:844},{width:1280,height:900}]) {
 const context=await browser.newContext({viewport,deviceScaleFactor:1});
 let items=[],sha='a'.repeat(40);
 await context.route(origin+'/**',async route=>{
  const url=new URL(route.request().url());
  if(url.pathname==='/api/admin/state') return route.fulfill({json:{sha,items}});
  if(url.pathname==='/api/quick-posts.json') return route.fulfill({json:{items:[]}});
  if(url.pathname==='/api/admin/posts') {
   if(failSave)return route.fulfill({status:409,json:{error:{message:'版本冲突，草稿保留'}}});
   const body=route.request().postDataJSON();assert.equal(route.request().headers()['x-bmt-admin'],'1');
   writes++;items=[{...body,type:'quick_post'}];return route.fulfill({json:{sha,message:'已保存，等待自动发布。'}});
  }
  const path=url.pathname==='/s/'?'s/index.html':url.pathname.slice(1);
  try {let content=await readFile(new URL('../docs/'+path,import.meta.url),'utf8');content=content.replace(/^---\n[\s\S]*?\n---\n/,'');
   return route.fulfill({body:content,contentType:path.endsWith('.js')?'application/javascript':path.endsWith('.css')?'text/css':'text/html'});
  }catch{return route.fulfill({status:404,body:''});}
 });
 const page=await context.newPage();const errors=[];page.on('pageerror',e=>errors.push(e.message));
 await page.goto(origin+'/s/');
 await page.locator('#body').waitFor({state:'visible'});
 await page.waitForFunction(()=>!document.getElementById('body').disabled);
 await page.locator('#body').fill('这是一条编辑手动发布的信息。\n\n第二段包含时间、地点和关键主体。🚀');
 await page.locator('#breaking').check();await page.locator('#pin').check();
 assert.equal(await page.evaluate(()=>document.documentElement.scrollWidth<=innerWidth),true);
 await page.reload();await page.waitForFunction(()=>!document.getElementById('body').disabled);
 assert.match(await page.locator('#body').inputValue(),/第二段/);
 failSave=true;await page.locator('#publish').click();await page.getByRole('status').filter({hasText:'版本冲突'}).waitFor();
 assert.match(await page.locator('#body').inputValue(),/第二段/);
 failSave=false;await page.locator('#save-draft').click();await page.locator('#entries .entry').waitFor();
 assert.match(await page.locator('#entries').innerText(),/草稿/);
 await page.locator('#publish').click();await page.waitForFunction(()=>document.getElementById('entries').innerText.includes('已保存'));
 assert.match(await page.locator('#entries').innerText(),/待核实上线/);
 assert.equal(errors.length,0,errors.join('\n'));
 if(process.env.BROWSER_EVIDENCE_DIR){
  await mkdir(process.env.BROWSER_EVIDENCE_DIR,{recursive:true});
  await page.screenshot({path:process.env.BROWSER_EVIDENCE_DIR+'/quick-post-'+viewport.width+'.png',fullPage:true});
 }
 console.log('PASS browser',viewport.width,'draft recovery / conflict preservation / save states / overflow / no console errors');
 await context.close();
}
await browser.close();assert.equal(writes,4);
