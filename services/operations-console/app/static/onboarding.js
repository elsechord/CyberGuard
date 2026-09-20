(() => {
  const root = document.querySelector('#onboarding'); if (!root) return;
  const form = document.querySelector('#model-form'), message = document.querySelector('#onboarding-message');
  const phaseNames = {idle:'等待初始化',initializing:'初始化中',ready:'已就绪',failed:'需要处理'};
  const stepNames={'preflight':'检查安装条件','restore-model-service':'恢复模型服务','resume-controller':'恢复 Controller','prepare-platform':'准备平台配置','prepare-network':'准备内部网络','build-controller':'构建 AgentTeams 镜像','build-model-service':'构建模型服务','start-controller':'启动 Controller','prepare-team':'准备调查团队','apply-model':'应用模型配置','register-routes':'注册模型路由','create-team':'创建团队','wake-workers':'启动 Worker','wait-workers':'等待 Worker 就绪','install-collaboration':'安装协作组件','restart-workers':'重启 Worker','configure-team':'配置原生团队','connect-console':'连接控制台','complete':'初始化完成','model-applied':'模型配置已应用'};
  const limitNames={max_requests:'最多模型请求',max_requests_per_role:'单角色请求上限',max_input_tokens:'输入 token 上限',max_output_tokens:'输出 token 上限',max_concurrency:'并发请求上限'};
  let busy = false, dirty = false, loaded = false;
  function say(text,error=false){message.textContent=text;message.dataset.error=String(error);}
  function controls(){root.querySelectorAll('button').forEach(x=>{x.disabled=busy||root.dataset.connected!=='true';});}
  async function refresh(){
    try {
      const r=await fetch('/settings/onboarding/status',{credentials:'same-origin'});const d=await r.json();
      if(!r.ok)throw new Error(d.error?.message||'无法读取状态。');
      const s=d.data;
      document.querySelector('#phase').textContent=phaseNames[s.phase]||'等待确认';
      document.querySelector('#step').textContent=stepNames[s.step]||s.step||'—';
      document.querySelector('#controller-state').textContent=s.deployment.controller_running?'运行中':'未运行';
      document.querySelector('#guard-state').textContent=s.deployment.guard_running?'运行中':'未运行';
      document.querySelector('#team-state').textContent=s.deployment.team_ready?'已就绪':'尚未就绪';
      document.querySelector('#model-apply-state').textContent=s.model.pending_apply?'配置已保存，尚未应用到调查服务。请初始化或保存并应用。':(s.model.configured?'模型配置已应用。':'尚未配置模型。');
      document.querySelector('#budget-state').textContent=s.budget?.armed?'调查预算已启用':'调查预算未启用';
      document.querySelector('#budget-limits').textContent=Object.entries(s.budget?.limits||{}).map(([k,v])=>(limitNames[k]||k)+'：'+Number(v).toLocaleString()).join('\n')||'初始化完成后将显示本轮限额。';
      document.querySelector('#key-state').textContent=s.model.has_api_key?'已保存密钥；留空会继续使用。':'尚未保存密钥。';
      if(!loaded||!dirty){form.elements.base_url.value=s.model.base_url||'';form.elements.model.value=s.model.model||'';} loaded=true;
      if(s.error)say(s.error,true);
      if(s.phase==='initializing')setTimeout(refresh,3000);
    }catch(e){say(e.message||'读取状态失败。',true);}
  }
  async function submit(action){
    if(busy)return;busy=true;controls();say(action==='initialize'?'正在启动初始化…':'正在处理…');
    const data=['initialize','enable'].includes(action)?new URLSearchParams({csrf_token:form.elements.csrf_token.value}):new URLSearchParams(new FormData(form));
    try{
      const r=await fetch('/settings/onboarding/'+action,{method:'POST',credentials:'same-origin',body:data});const d=await r.json();
      if(!r.ok)throw new Error(d.error?.message||'请求未完成。');
      if(action==='test')say(d.data.ok?'模型连接成功，可以保存配置。':'模型未通过连接检查。',!d.data.ok);
      if(['save','apply'].includes(action)){form.elements.api_key.value='';dirty=false;}
      if(action==='save')say('配置已保存。点击“初始化 / 应用配置”使调查服务使用它。');
      if(action==='apply')say('模型配置已应用到调查服务。');
      if(action==='enable')say(d.data.armed?'调查预算已启用，可以提交第一份材料。':'预算尚未启用。',!d.data.armed);
      if(action==='initialize')say('后台初始化已启动，可在此查看真实进度。');
      await refresh();
    }catch(e){say(e.message||'请求未完成，请稍后重试。',true);}finally{busy=false;controls();}
  }
  form.addEventListener('input',()=>{dirty=true;});
  form.addEventListener('submit',e=>{e.preventDefault();submit(e.submitter?.dataset.action||'save');});
  document.querySelector('#initialize').addEventListener('click',()=>submit('initialize'));
  document.querySelector('#enable').addEventListener('click',()=>submit('enable'));
  document.querySelector('#refresh').addEventListener('click',refresh);
  controls();refresh();
})();
