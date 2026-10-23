/* Opt-in passive host adapter. Reuses the existing LiveSessions and dashboard source owners. */
(function(root){
 'use strict';
 function install({document= root.document,window=root,view= root.AgentCityObserved,feed=root.AgentCityObservedFeed,taskHome=root.AgentCityTaskHome,taskFeed=null}={}){
  const legacy=window.LiveSessions,oldRoot=document.getElementById('live-sessions-view'),dashboard=document.getElementById('dashboard-view');
  if(!legacy||!oldRoot||!dashboard||oldRoot.dataset.observedOwner)throw Error('Несовместимый или уже подключённый пассивный интерфейс');
  // No native actions, additional endpoint, discovery, or transport authority.
  const surface=document.createElement('section');surface.id='observed-work-view';surface.hidden=true;oldRoot.after(surface);
  oldRoot.dataset.observedOwner='true';
  let pending=null,lastSurface=null,visible=false,routing=false;
  function hostRoute(r){pending=r;if(typeof window.setView==='function')window.setView(r.page==='home'?'dashboard':'sessions');}
  const ui=view.mount(surface,{externalNavigation:true,taskHome,onRoute:r=>{if(!routing)hostRoute(r);}});
  const nav=document.querySelector('.app-header nav'),historyButton=document.createElement('button');
  historyButton.type='button';historyButton.dataset.observedPage='history';historyButton.setAttribute('aria-label','История');historyButton.title='История';
  const full=document.createElement('span');full.textContent='История';const small=document.createElement('small');small.className='compact-label';small.textContent='История';const clock=document.createElementNS('http://www.w3.org/2000/svg','svg');clock.setAttribute('viewBox','0 0 24 24');clock.setAttribute('aria-hidden','true');clock.setAttribute('focusable','false');
  const face=document.createElementNS('http://www.w3.org/2000/svg','circle');face.setAttribute('cx','12');face.setAttribute('cy','12');face.setAttribute('r','9');
  const hands=document.createElementNS('http://www.w3.org/2000/svg','path');hands.setAttribute('d','M12 7v5l3 2');clock.append(face,hands);historyButton.append(clock,full,small);
  if(nav)nav.append(historyButton);historyButton.addEventListener('click',()=>{pending={page:'history'};hostRoute(pending);});
  function selectedNav(){
   for(const b of document.querySelectorAll('[data-view="dashboard"],[data-view="sessions"]')){
    const selected=ui.model.route.page===(b.dataset.view==='dashboard'?'home':'projects');
    b.classList.toggle('active',visible&&selected);b.setAttribute('aria-current',visible&&selected?'page':'false');
   }
   const selected=visible&&ui.model.route.page==='history';historyButton.classList.toggle('active',selected);historyButton.setAttribute('aria-current',selected?'page':'false');
  }
  const originalVisible=legacy.viewChanged.bind(legacy),originalProject=legacy.openProject,originalSession=legacy.openSession;
  legacy.viewChanged=function(show,surfaceName='sessions'){
   originalVisible(show,surfaceName);visible=!!show;surface.hidden=!visible;
   if(visible){
    const requested=pending||(lastSurface!==surfaceName?{page:surfaceName==='dashboard'?'home':'projects'}:null);
    pending=null;lastSurface=surfaceName;if(requested){routing=true;try{ui.navigate(requested);}finally{routing=false;}}
    oldRoot.hidden=true;dashboard.hidden=true;
   }
   historyButton.hidden=document.documentElement.dataset.agentCityMode!=='passive_dashboard';
   selectedNav();
  };
  // Public navigation hooks retain exact opaque session/project identities.
  legacy.openProject=function(projectId){pending={page:'projects',projectId};hostRoute(pending);return true;};
  legacy.openSession=function(sessionId){const item=legacy.getSnapshot()?.sessions?.find(s=>s.id===sessionId);if(!item)return false;pending={page:'projects',projectId:item.projectId,agentId:item.agentId,sessionId};hostRoute(pending);return true;};
  const connected=feed.connect(ui,{read:()=>legacy.getSnapshot(),subscribe:accept=>{
   const listener=e=>accept(e.detail);window.addEventListener('agentcity:live-summary',listener);
   return ()=>window.removeEventListener('agentcity:live-summary',listener);
  }});
  // Host render assigns dashboard visibility after viewChanged; keep projection
  // visibility aligned without polling or observing user/source content.
  function afterRender(){if(!visible)return;oldRoot.hidden=true;dashboard.hidden=true;const title=document.getElementById('page-title');if(title)title.hidden=true;selectedNav();}
  const originalDashboard=window.renderDashboard,originalRender=window.render,originalLoad=window.loadDashboard,originalRows=window.renderDashboardRows;
  // These are global lexical bindings in the installed shell, not window fields.
  // Read only after boot; tests may inject the same cache/subscription contract.
  const readTasks=taskFeed?.read||(()=>({snapshot:typeof dashboardData==='undefined'?null:dashboardData,error:typeof dashboardReadError==='undefined'?null:dashboardReadError}));
  function syncTasks(){const value=readTasks();ui.updateTasks(value?.snapshot,value?.error);afterRender();}
  const unsubscribeTasks=taskFeed?.subscribe?.(syncTasks);
  syncTasks();
  if(typeof originalRender==='function')window.render=function(...args){const result=originalRender.apply(this,args);afterRender();return result;};
  if(typeof originalLoad==='function')window.loadDashboard=async function(...args){try{return await originalLoad.apply(this,args);}finally{syncTasks();}};
  window.renderDashboardRows=function(){syncTasks();};
  window.renderDashboard=function(){if(typeof window.loadDashboard==='function')void window.loadDashboard(false);afterRender();};
  const click=e=>{const b=e.target.closest?.('[data-view]');if(b?.dataset.view==='dashboard')pending={page:'home'};else if(b?.dataset.view==='sessions')pending={page:'projects'};};
  document.addEventListener('click',click,true);
  return {ui,afterRender,disconnect(){connected.disconnect();unsubscribeTasks?.();legacy.viewChanged=originalVisible;legacy.openProject=originalProject;legacy.openSession=originalSession;window.renderDashboard=originalDashboard;window.render=originalRender;window.loadDashboard=originalLoad;window.renderDashboardRows=originalRows;document.removeEventListener('click',click,true);delete oldRoot.dataset.observedOwner;historyButton.remove();ui.destroy();surface.remove();oldRoot.hidden=true;dashboard.hidden=false;}};
 }
 const api=Object.freeze({install});if(typeof module==='object'&&module.exports)module.exports=api;else root.AgentCityObservedHost=api;
})(typeof globalThis==='object'?globalThis:this);
