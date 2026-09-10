(() => {
'use strict';
const $ = id => document.getElementById(id);
const fields = ['body','url','date','category','breaking','pin'];
const key = 'bmt-quick-post-draft-v1';
let sha = '', items = [], id = crypto.randomUUID(), image = '', dirty = false, busy = false;
let legacyIndex = -1;
const legacyLabels = {type:'操作类型（editorial / sponsored / suppress）',url:'原文链接',title_zh:'中文标题',title_en:'英文标题',summary_zh:'中文正文',summary_en:'英文正文',date:'刊期日期',starts:'开始日期',expires:'结束日期（广告必填）',position:'广告位置（1–20）',label:'来源名称',category:'分类',background_zh:'背景',background_en:'Background',market_impact_zh:'市场影响',market_impact_en:'Market impact',community_discussion_zh:'讨论',community_discussion_en:'Discussion',note:'内部备注',tags:'标签（每行一个）',sources:'参考链接（每行：标题 | URL）'};
for (const [name,title] of Object.entries(legacyLabels)) {
 const label=document.createElement('label');label.textContent=title;
 const field=document.createElement(/summary|background|impact|discussion|sources|tags/.test(name)?'textarea':'input');
 field.id='legacy-'+name;field.maxLength=10000;label.append(field);$('legacy-fields').append(label);
}
for(const name of ['enabled','official']) {
 const label=document.createElement('label');const field=document.createElement('input');field.type='checkbox';field.id='legacy-'+name;
 label.append(field,document.createTextNode(name==='enabled'?'启用':'官方或第一手来源'));$('legacy-fields').append(label);
}
function fillLegacy(entry={},index=-1) {
 legacyIndex=index;
 for(const name of Object.keys(legacyLabels)) {
  $('legacy-'+name).value=name==='tags'?(entry.tags||[]).join('\n'):name==='sources'?(entry.sources||[]).map(s=>(s.title||'')+' | '+s.url).join('\n'):entry[name]??(name==='type'?'editorial':'');
 }
 $('legacy-enabled').checked=entry.enabled!==false;$('legacy-official').checked=!!entry.official;
}
function today() { return new Intl.DateTimeFormat('en-CA',{timeZone:'Asia/Shanghai',year:'numeric',month:'2-digit',day:'2-digit'}).format(new Date()); }
function value(enabled) { return {id,body:$('body').value,url:$('url').value,date:$('date').value,category:$('category').value,breaking:$('breaking').checked,pin:$('pin').checked,image,enabled,sha}; }
function remember() { dirty = true; try { sessionStorage.setItem(key,JSON.stringify(value(false))); } catch {} }
function fill(post) { id=post.id||crypto.randomUUID(); image=post.image||''; fields.forEach(f=>{if(['breaking','pin'].includes(f)) $(f).checked=!!post[f]; else $(f).value=post[f]|| (f==='date'?today():'');}); $('image').value=''; $('image-state').textContent=image?'已选择配图':''; $('remove-image').hidden=!image; }
function status(message) { $('status').textContent=message; }
function lock(on) {
 busy=on;
 document.querySelectorAll('form input, form textarea, form select, form button').forEach(field=>{field.disabled=on||!sha;});
}
async function api(path, data) {
 const response=await fetch('/api/admin/'+path,{method:data?'POST':'GET',credentials:'same-origin',cache:'no-store',
   headers:data?{'Content-Type':'application/json','X-BMT-Admin':'1'}:{},body:data?JSON.stringify(data):undefined});
 if(!response.headers.get('content-type')?.includes('application/json')) throw Error('登录已过期，请重新打开 /s/ 完成邮箱验证；当前标签页草稿仍保留。');
 const result=await response.json(); if(!response.ok) throw Error(result.error?.message||'操作失败，请稍后重试。'); return result;
}
async function refresh() {
 const state=await api('state'); sha=state.sha; items=state.items;
 let published=[];
 try { const r=await fetch('/api/quick-posts.json?publication_check=admin',{cache:'no-store'}); if(r.ok) published=(await r.json()).items||[]; } catch {}
 $('entries').replaceChildren();
 items.slice().reverse().forEach((entry, reversed)=>{
   const index=items.length-1-reversed, node=document.createElement('article'); node.className='entry';
   const meta=document.createElement('small');
   const live=entry.type==='quick_post' && published.some(p=>p.id===entry.id && p.updated_at===entry.updated_at);
   meta.textContent=[entry.type==='quick_post'?'Quick Post':entry.type,entry.date||entry.starts||'未指定日期',
     entry.enabled===false?'草稿 / 停用':live?'已上线':'已保存（待核实上线）'].join(' · ');
   const content=document.createElement('p');content.textContent=entry.body||entry.title_zh||entry.url||'编辑记录';
   const actions=document.createElement('div');actions.className='actions';
   if(entry.type==='quick_post') { const edit=document.createElement('button'); edit.textContent='编辑';edit.onclick=()=>{if(busy)return;if(dirty&&!confirm('替换当前未提交草稿？'))return;fill(entry);remember();$('body').focus();};actions.append(edit); }
   else { const edit=document.createElement('button');edit.textContent='编辑';edit.onclick=()=>{if(busy)return;fillLegacy(entry,index);$('legacy-panel').open=true;$('legacy-panel').scrollIntoView({behavior:'smooth'});};actions.append(edit); }
   const toggle=document.createElement('button');toggle.textContent=entry.enabled===false?'启用':'停用';
   toggle.onclick=async()=>{if(busy||!confirm(toggle.textContent+'这条记录？'))return;lock(true);try{await api('entry-state',{sha,index,enabled:entry.enabled===false});await refresh();status('已保存状态，等待自动发布。');}catch(e){status(e.message);}finally{lock(false);}};
   actions.append(toggle);node.append(meta,content,actions);$('entries').append(node);
 });
 $('body').disabled=false;lock(false);
}
async function save(enabled) {
 if(busy)return;
 if(!$('post-form').reportValidity())return;
 lock(true);remember();status('正在保存…');
 try {const result=await api('posts',value(enabled));sha=result.sha;dirty=false;try{sessionStorage.removeItem(key);}catch{} status(result.message);await refresh();}
 catch(e){status(e.message);}finally{lock(false);}
}
$('date').value=today();
fillLegacy();
$('legacy-new').onclick=()=>{if(!busy)fillLegacy();};
$('legacy-form').onsubmit=async e=>{
 e.preventDefault();if(busy)return;lock(true);
 try {
  const entry=Object.fromEntries(Object.keys(legacyLabels).map(name=>[name,$('legacy-'+name).value]));
  entry.enabled=$('legacy-enabled').checked;entry.official=$('legacy-official').checked;
  entry.position=entry.position?Number(entry.position):null;
  entry.tags=entry.tags.split('\n').map(s=>s.trim()).filter(Boolean);
  entry.sources=entry.sources.split('\n').filter(s=>s.trim()).map(s=>{const i=s.lastIndexOf('|');return{title:i<0?'':s.slice(0,i).trim(),url:(i<0?s:s.slice(i+1)).trim()};});
  const result=await api('legacy',{sha,index:legacyIndex,entry});status(result.message);await refresh();
 }catch(error){status(error.message);}finally{lock(false);}
};
try{const saved=JSON.parse(sessionStorage.getItem(key)||'null');if(saved){fill(saved);dirty=true;}}catch{}
fields.forEach(f=>$(f).addEventListener('input',remember));
$('post-form').onsubmit=e=>{e.preventDefault();save(true);};
$('save-draft').onclick=()=>save(false);
$('new-post').onclick=()=>{if(busy||(dirty&&!confirm('放弃当前未提交草稿，开始新建？')))return;fill({});dirty=false;try{sessionStorage.removeItem(key);}catch{} status('新建内容');$('body').focus();};
$('refresh').onclick=()=>{if(busy)return;refresh().then(()=>status('列表已刷新；当前输入未改变。')).catch(e=>status(e.message));};
$('remove-image').onclick=()=>{if(busy)return;image='';$('image').value='';$('image-state').textContent='';$('remove-image').hidden=true;remember();};
$('image').onchange=async()=>{
 const file=$('image').files[0];if(!file)return;
 if(file.size>1024*1024||!['image/png','image/jpeg','image/webp'].includes(file.type)){status('请选择不超过 1 MB 的 PNG、JPEG 或 WebP 图片。');$('image').value='';return;}
 lock(true);status('上传图片…');
 try {const data=await new Promise((resolve,reject)=>{const reader=new FileReader();reader.onload=()=>resolve(reader.result.split(',')[1]);reader.onerror=reject;reader.readAsDataURL(file);});
 const result=await api('image',{mime:file.type,data});image=result.path;$('image-state').textContent='配图已保存，随发布部署';$('remove-image').hidden=false;remember();status('配图已保存，请继续保存正文。');}
 catch(e){status(e.message);}finally{lock(false);}
};
window.addEventListener('beforeunload',e=>{if(dirty){e.preventDefault();e.returnValue='';}});
refresh().then(()=>status(dirty?'已恢复当前标签页的草稿。':'可以开始写了。')).catch(e=>status(e.message));
})();
