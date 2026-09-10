(() => {
'use strict';
const form=document.getElementById('source-change-form'), status=document.getElementById('source-change-status');
form.addEventListener('submit',async e=>{
 e.preventDefault();const button=form.querySelector('button[type=submit]');button.disabled=true;
 status.textContent='正在提交…';
 try {
  const payload=Object.fromEntries(new FormData(form));
  const response=await fetch('/api/admin/sources',{method:'POST',credentials:'same-origin',
   headers:{'Content-Type':'application/json','X-BMT-Admin':'1'},body:JSON.stringify(payload)});
  if(!response.headers.get('content-type')?.includes('application/json'))throw Error('登录已过期，请重新打开 /s/ 验证邮箱。');
  const result=await response.json();if(!response.ok)throw Error(result.error?.message||'提交失败');
  status.textContent=result.message;
 }catch(error){status.textContent=error.message;}finally{button.disabled=false;}
});
})();
