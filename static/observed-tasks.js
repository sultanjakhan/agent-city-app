/* Read-only Cicada work projection. No native actions or telemetry aggregation. */
(function(root){
 'use strict';
 const current=new Set(['working','waiting','blocked']),states=new Set(['running','waiting','done','error','cancelled']);
 const string=v=>typeof v==='string'&&v.length>0&&v.length<=2000?v:null;
 const fields=['profile','sourceKey','sourceId','taskKey'];
 function identity(source,task){const value={profile:source?.profile,sourceKey:source?.sourceKey,sourceId:task?.sourceId,taskKey:task?.taskKey};return fields.every(k=>string(value[k]))?value:null;}
 const key=value=>value&&fields.every(k=>string(value[k]))?JSON.stringify(fields.map(k=>value[k])):null;
 const sourceKey=source=>string(source?.profile)&&string(source?.sourceKey)?JSON.stringify([source.profile,source.sourceKey,source.sourceNamespace||null]):null;
 const stamp=v=>{const n=Date.parse(v||'');return Number.isFinite(n)?n:null;};
 const fresh=(report,now)=>{const at=stamp(report.updatedAt);return at!==null&&now-at>=-30000&&now-at<=300000;};
 const idOrder=(a,b)=>a<b?-1:a>b?1:0;
 function createModel({now=()=>Date.now()}={}){
  let source=null,namespace=null,status='unknown',readAt=null,asOf=null,observed={sessions:[],projects:[],source:{status:'unknown'}},tasks=new Map(),reports=new Map();
  const runSources=new Map(),selectedCache=new Map();
  function reportAllowed(report,task){
   if(report.taskKey!==task.identity.taskKey)return false;
   if(report.source&&typeof report.source==='object')for(const field of ['profile','sourceKey','sourceNamespace'])if(report.source[field]!=null&&report.source[field]!==source[field])return false;
   // A key namespace must be explicitly present on the selected source/task.
   const prefix=task.sourceNamespace&&task.sourceNamespace===source.sourceNamespace?task.sourceNamespace:source.sourceKey;
   return report.taskKey==='cicada-'+prefix+'-'+task.identity.sourceId;
  }
  function project(task){
   const linked=(observed.sessions||[]).filter(s=>key(s.taskBinding)===task.id);
   const sameSource=task.namespace===namespace,live=sameSource?linked.filter(s=>current.has(s.status)):[];
   const exactReports=sameSource?[...reports.values()].filter(r=>reportAllowed(r,task)):[];
   const requests=exactReports.filter(r=>r.status==='waiting'&&['user_input','approval'].includes(r.reasonCode));
   const running=exactReports.filter(r=>['running','waiting'].includes(r.status)&&fresh(r,now()));
   const nonCompleted=sameSource&&task.completed===false;
   const attention=nonCompleted&&requests.length>0;
   const eligible=nonCompleted&&(task.isActive===true||live.length>0||running.length>0);
   const known=live.length>0&&observed.source?.status==='fresh';
   const projectIds=[...new Set(linked.map(s=>s.projectId))];
   return {...task,isActive:sameSource&&task.present!==false?task.isActive:null,oldSource:!sameSource,attention,eligible,requests,linked,live,reports:exactReports,
    projectNames:projectIds.map(id=>observed.projects?.find(p=>p.id===id)?.name).filter(Boolean),
    sessionCount:known?live.length:null,agentCount:known&&live.every(s=>string(s.agentId))?new Set(live.map(s=>s.agentId)).size:null,
    observationStatus:observed.source?.status||'unknown',requestOld:requests.some(r=>!fresh(r,now())),stale:status!=='complete'||task.present===false};
  }
  return {
   update(snapshot,error=null){
    if(error||snapshot?.cicada?.status!=='connected'){
     status=snapshot?.cicada?.status==='disconnected'?'disconnected':snapshot||error?'stale':'unknown';return this;
    }
    const native=snapshot.cicada;
    if(!Array.isArray(native.tasks)||!Array.isArray(snapshot.runs)){status='stale';return this;}
    const nextSource=native.source,nextNamespace=sourceKey(nextSource);
    if(!nextNamespace){status='stale';return this;}
    const changed=namespace!==nextNamespace,partial=native.hasMore===true||native.historyLimited===true||['error','limited','partial'].includes(native.historyStatus);
    source={profile:nextSource.profile,sourceKey:nextSource.sourceKey,sourceNamespace:nextSource.sourceNamespace||null,label:string(nextSource.label)};namespace=nextNamespace;
    const previous=changed?new Map():tasks,next=new Map();
    for(const t of [...(native.historyTasks||[]),...(native.openTasks||[]),...(native.tasks||[])]){
     const exact=identity(source,t),id=key(exact);if(!id)continue;
     const item={id,identity:exact,sourceLabel:source.label,namespace,sourceReadAt:string(native.readAt),sourceNamespace:t.sourceNamespace||null,title:string(t.title)||'Название недоступно',completed:typeof t.completed==='boolean'?t.completed:null,
      isActive:typeof t.isActive==='boolean'?t.isActive:null,isPaused:t.isPaused===true,stage:string(t.stageLabel)||string(t.stage),process:string(t.processLabel)||string(t.process),lastUpdatedAt:string(t.lastUpdatedAt),present:true};
     const old=next.get(id);if(!old||stamp(old.lastUpdatedAt)===null||stamp(item.lastUpdatedAt)===null||stamp(item.lastUpdatedAt)>=stamp(old.lastUpdatedAt))next.set(id,item);
    }
    if(changed)reports=new Map();
    for(const r of Array.isArray(snapshot.runs)?snapshot.runs:[]){
     if(!string(r.runId)||!Number.isSafeInteger(r.sequence)||r.sequence<1||!states.has(r.status))continue;
     const runKey=JSON.stringify([r.originDevice||null,r.runId]),pinned=runSources.get(runKey);
     if(pinned&&pinned!==namespace)continue;
     const task=[...next.values(),...previous.values()].find(t=>r.taskKey===t.identity.taskKey&&reportAllowed(r,t));if(!task)continue;
     runSources.set(runKey,namespace);const old=reports.get(runKey);
     if(!old||r.sequence>old.sequence)reports.set(runKey,{runId:r.runId,originDevice:r.originDevice||null,taskKey:r.taskKey,sequence:r.sequence,status:r.status,reasonCode:string(r.reasonCode),stage:string(r.stage),updatedAt:stamp(r.updatedAt)===null?null:r.updatedAt,source:r.source?Object.fromEntries(['profile','sourceKey','sourceNamespace'].map(k=>[k,r.source[k]])):null});
    }
    // Omission never resolves a recorded explicit request. Partial snapshots also
    // retain prior rows, marked as not present; a newer terminal report clears it.
    for(const [id,t] of previous)if(!next.has(id)&&(partial||[...reports.values()].some(r=>r.taskKey===t.identity.taskKey&&r.status==='waiting'&&['user_input','approval'].includes(r.reasonCode))))next.set(id,{...t,present:false});
    tasks=next;status=partial?'partial':'complete';readAt=string(native.readAt);asOf=string(snapshot.asOf);
    for(const [id,t] of tasks)selectedCache.set(id,t);
    return this;
   },
   observe(value){observed=value||{sessions:[],projects:[],source:{status:'unknown'}};return this;},
   rows(){return [...tasks.values()].map(project).filter(t=>t.attention||t.eligible).sort((a,b)=>Number(b.attention)-Number(a.attention)||idOrder(a.id,b.id));},
   get(id){const task=tasks.get(id)||selectedCache.get(id);return task?project({...task,present:tasks.has(id)?task.present:false}):null;},
   get source(){return {status,readAt,asOf,label:source?.label||'Cicada',identity:source};}
  };
 }
 const requestLabel=r=>r.reasonCode==='approval'?'Нужно ваше подтверждение':'Нужен ваш ответ';
 function summary(task){
  const timer=task.isActive===true?'Таймер Cicada идёт':task.isActive===false?'Таймер Cicada не идёт':'Таймер Cicada неизвестен';
  const execution=task.live.length?'Есть текущее наблюдаемое выполнение':task.reports.some(r=>['running','waiting'].includes(r.status))?'Состояние исполнителя — в отчётах':'Исполнение не подтверждено';
  return [task.stage||'Этап не указан',timer,execution].join(' · ');
 }
 function mount(container,{node,put,button,list,facts,reveal,onOpenSession,onSelectTask=()=>{},now=()=>Date.now()}){
  const model=createModel({now}),layout=node('div','ow-layout ow-task-layout'),main=node('section','ow-main'),items=node('div','ow-task-list'),empty=node('p','ow-empty'),detail=node('section','ow-detail ow-task-detail');
  const heading=node('h3','ow-detail-title'),state=node('p','ow-secondary'),notice=node('p','ow-secondary'),linked=node('div','ow-linked'),linkedEmpty=node('p','ow-secondary'),requestList=node('ul','ow-task-requests');
  const source=node('details','ow-disclosure'),sourceTitle=node('summary','','Источник задачи'),sourceFacts=node('dl','ow-facts');source.append(sourceTitle,sourceFacts);
  let selected=null,savedPositions=[],sessionOpen=false;heading.tabIndex=-1;
  const positions=()=>{const out=[];for(let n=items;n;n=n.parentElement)out.push([n,n.scrollTop,n.scrollLeft]);return out;};
  const back=button('Назад к списку',()=>{const prior=selected;selected=null;patch();for(const [n,top,left] of savedPositions){n.scrollTop=top;n.scrollLeft=left;}reveal(items._rows?.get(prior)||empty);},'ow-button ow-task-back');empty.tabIndex=-1;
  const executions=node('h4','','Связанные выполнения');detail.append(back,heading,state,notice,requestList,executions,linked,linkedEmpty,source);main.append(items,empty);layout.append(main,detail);container.append(layout);
  function select(id){if(id===selected)return;selected=id;savedPositions=positions();onSelectTask();patch();reveal(heading);}
  function patch(){
   const rows=model.rows(),attention=rows.filter(t=>t.attention),work=rows.filter(t=>!t.attention),sections=[];
   if(attention.length)sections.push({id:'section:attention',heading:'Нужно ваше участие'},...attention);
   sections.push({id:'section:work',heading:'Текущая работа'},...work);
   list(items,sections,t=>t.id,t=>{if(t.heading)return node('h3','ow-task-section');const n=button('',()=>select(t.id),'ow-session ow-task-row'),title=node('span','ow-session-title'),meta=node('span','ow-secondary'),status=node('span','ow-status');n.append(title,status,meta);n._title=title;n._meta=meta;n._status=status;return n;},(n,t)=>{
    if(t.heading){put(n,t.heading);return;}put(n._title,t.title);put(n._status,t.attention?[...new Set(t.requests.map(requestLabel))].join(' · ')+(t.stale?' · источник требует проверки':t.requestOld?' · давний отчёт':''):t.stale?'Последние известные данные':'Cicada');
    put(n._meta,[...t.projectNames,summary(t),t.sessionCount===null?'Число активных сессий неизвестно':'Наблюдаемых сессий: '+t.sessionCount+(t.agentCount===null?'':' · агентов: '+t.agentCount)].join(' · '));n.setAttribute('aria-pressed',String(t.id===selected));
   });
   const sourceState=model.source.status;put(empty,sourceState==='complete'?'Текущая работа не подтверждена.':sourceState==='partial'?'Список Cicada неполный.':sourceState==='disconnected'?'Cicada не подключена.':'Текущая работа Cicada не проверена.');empty.hidden=rows.length>0;
   layout.classList.toggle('ow-detail-selected',!!selected&&!sessionOpen);detail.hidden=!selected||sessionOpen;const task=model.get(selected);if(!task)return;
   put(heading,task.title);put(state,task.completed===true?'Завершена в Cicada':summary(task));put(notice,task.oldSource?'Выбрана задача прежнего источника. Текущее состояние недоступно.':task.present===false?'Задача отсутствует в текущем снимке.':!task.eligible&&!task.attention?'Сейчас не подтверждена как текущая.':task.stale?'Последние известные данные.':'');notice.hidden=!notice.textContent;
   list(requestList,task.requests,r=>JSON.stringify([r.originDevice,r.runId]),()=>node('li'),(n,r)=>put(n,requestLabel(r)+(task.requestOld?' · давность отчёта требует проверки':'')+' · '+(r.updatedAt?new Date(r.updatedAt).toLocaleString('ru-RU'):'Время отчёта неизвестно')));
   list(linked,task.linked,s=>s.id,s=>button('',()=>onOpenSession(s.id),'ow-session ow-task-execution'),(n,s)=>put(n,(s.name||s.id)+' · '+s.id));
   put(linkedEmpty,task.linked.length?'':'Сессии не привязаны.');linkedEmpty.hidden=task.linked.length>0;
   facts(sourceFacts,[...Object.entries(task.identity),['Процесс Cicada',task.process],['Источник',task.sourceLabel||model.source.label],['Состояние источника',task.oldSource?'Прежний источник':sourceState],['Последнее чтение',task.sourceReadAt]]);
  }
  patch();return {model,update(snapshot,error){model.update(snapshot,error);patch();},observe(data){model.observe(data);patch();},get selected(){return selected;},
   source(){const s=model.source;return {label:s.label+' · '+({complete:'прочитано',partial:'неполный снимок',stale:'данные устарели',disconnected:'не подключена',unknown:'не проверено'}[s.status]),detail:'Cicada: '+s.status+' · чтение: '+(s.readAt||'неизвестно'),readAt:s.readAt};},
   setSessionOpen(value){sessionOpen=!!value;patch();},returnFromSession(id){const n=linked._rows?.get(id)||heading;reveal(n);},destroy(){layout.remove();}};
 }
 const api=Object.freeze({createModel,mount,identity,key,fresh});if(typeof module==='object'&&module.exports)module.exports=api;else root.AgentCityTaskHome=api;
})(typeof globalThis==='object'?globalThis:this);
