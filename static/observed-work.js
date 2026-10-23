/* Independently authored passive view. No transport, task mutation or persistence. */
(function(root){
 'use strict';
 const LIVE=new Set(['working','waiting','blocked']),DONE=new Set(['completed','interrupted']);
 const statusText={working:'Выполняется',waiting:'Ожидает',blocked:'Заблокировано',completed:'Завершён',interrupted:'Прерван',unknown:'Неизвестно'};
 const count=v=>Number.isSafeInteger(v)&&v>=0?v:null;
 const text=v=>typeof v==='string'?v.slice(0,2000):null;
 const id=v=>{if(typeof v!=='string'||!v.length||v.length>200)throw Error('Требуется устойчивый ID наблюдения');return v;};
 const time=v=>typeof v==='string'&&/T.*(?:Z|[+-]\d\d:\d\d)$/.test(v)&&Number.isFinite(Date.parse(v))?v:null;
 const unique=(rows,read)=>{const seen=new Set();return (Array.isArray(rows)?rows:[]).map(row=>{const value=read(row);if(seen.has(value.id))throw Error('Повтор ID наблюдения');seen.add(value.id);return value;});};
 function measurement(row){
  const usage=row.usage||{};
  return {status:Object.hasOwn(statusText,row.status)?row.status:'unknown',startedAt:time(row.startedAt),endedAt:time(row.endedAt),
   durationMs:count(row.durationMs),durationSource:text(row.durationSource),model:text(row.model),effort:text(row.effort),
   coverage:['complete','partial','unknown'].includes(row.coverage)?row.coverage:'unknown',
   usage:Object.fromEntries(['input','output','total','cachedInput','reasoningOutput'].map(k=>[k,count(usage[k])]))};
 }
 function events(rows){return unique(rows,row=>({id:id(row.id),at:time(row.at),label:text(row.label)||'Событие',source:text(row.source)}));}
 function normalize(feed){
  if(!feed||typeof feed!=='object')throw Error('Требуется снимок наблюдений');
  const projects=unique(feed.projects,row=>({id:id(row.id),name:text(row.name)||row.id}));
  const agents=unique(feed.agents,row=>({id:id(row.id),projectId:id(row.projectId),name:text(row.name)||row.id}));
  const sessions=unique(feed.sessions,row=>{
   if(!row.scope||!['session','turn','interval'].includes(row.scope.kind))throw Error('Требуется явная область измерений');
   const task=row.task&&typeof row.task==='object'?{title:text(row.task.title),goal:text(row.task.goal),
    identity:Object.fromEntries(['profile','sourceKey','sourceId','taskKey','nativeTaskKey'].map(k=>[k,text(row.task.identity?.[k])]))}:null;
   return {id:id(row.id),projectId:id(row.projectId),agentId:row.agentId===null||row.agentId===undefined?null:id(row.agentId),
    parentId:text(row.parentId),name:text(row.name)||row.id,scope:{kind:row.scope.kind,id:id(row.scope.id)},...measurement(row),task,
    events:events(row.events),appliedSkills:row.appliedSkills===null||row.appliedSkills===undefined?null:unique(row.appliedSkills,event=>{
     if(event.kind!=='applied'||event.source!=='executor-reported')throw Error('Требуется явное свидетельство применения навыка');
     return {id:id(event.id),skillId:id(event.skillId),at:time(event.at),source:'executor-reported'};
    }),turns:unique(row.turns,turn=>({id:id(turn.id),name:text(turn.name)||'Ход',...measurement(turn),events:events(turn.events)}))};
  });
  const edges=unique(feed.edges,row=>({id:id(row.id),projectId:id(row.projectId),fromAgentId:id(row.fromAgentId),toAgentId:id(row.toAgentId),label:text(row.label)||'Наблюдаемая связь'}));
  return {projects,agents,sessions,edges,source:{originalStatus:text(feed.source?.originalStatus),message:text(feed.source?.message),status:['fresh','partial','stale','unavailable','unknown'].includes(feed.source?.status)?feed.source.status:'unknown',readAt:time(feed.source?.readAt)}};
 }
 function route(value={}){
  return {page:['home','projects','history'].includes(value.page)?value.page:'home',projectId:text(value.projectId),agentId:text(value.agentId),sessionId:text(value.sessionId)};
 }
 function formatRoute(value){const r=route(value),p=new URLSearchParams();for(const k of ['projectId','agentId','sessionId'])if(r[k])p.set(k,r[k]);return '#'+r.page+(p.size?'?'+p:'');}
 function parseRoute(hash){const [page,query]=String(hash||'').replace(/^#/,'').split('?'),p=new URLSearchParams(query);return route({page,...Object.fromEntries(['projectId','agentId','sessionId'].map(k=>[k,p.get(k)]))});}
 function createModel(initialRoute){
  let data=normalize({}),current=route(initialRoute);const order=new Map();let serial=0;
  return {update(feed){const next=normalize(feed);for(const row of next.sessions)if(!order.has(row.id))order.set(row.id,serial++);data=next;return this;},
   navigate(value){current=route(value);return {...current};},get route(){return {...current};},get data(){return data;},
   get selected(){return data.sessions.find(s=>s.id===current.sessionId)||null;},
   rows(page=current.page){return data.sessions.filter(s=>(page==='home'?LIVE.has(s.status):page==='history'?DONE.has(s.status):!DONE.has(s.status))&&
    (page!=='projects'||!!current.projectId)&&(!current.projectId||s.projectId===current.projectId)&&(!current.agentId||s.agentId===current.agentId)).sort((a,b)=>{if(page!=='history')return order.get(a.id)-order.get(b.id);const stamp=s=>{const value=Date.parse(s.endedAt||'');return Number.isFinite(value)?value:-Infinity;},left=stamp(a),right=stamp(b);return left===right?(a.id<b.id?-1:a.id>b.id?1:0):left>right?-1:1;});},
   projectAgents(projectId){return data.agents.filter(a=>a.projectId===projectId).map(a=>({...a,currentCount:data.sessions.filter(s=>s.projectId===projectId&&s.agentId===a.id&&LIVE.has(s.status)).length})).filter(a=>a.currentCount>0).sort((a,b)=>a.id.localeCompare(b.id));},
   projectEdges(projectId){const ids=new Set(this.projectAgents(projectId).map(a=>a.id));return data.edges.filter(e=>e.projectId===projectId&&ids.has(e.fromAgentId)&&ids.has(e.toAgentId)).sort((a,b)=>a.id.localeCompare(b.id));}};
 }
 const executionLabel=s=>s.scope?.kind==='session'&&s.status==='completed'?'Последний ход завершён':s.scope?.kind==='session'&&s.status==='interrupted'?'Последний ход прерван':statusText[s.status];
 const number=v=>count(v)===null?'Неизвестно':new Intl.NumberFormat('ru-RU').format(v);
 function duration(ms){if(count(ms)===null)return 'Неизвестно';const seconds=Math.floor(ms/1000);return seconds<60?seconds+' с':Math.floor(seconds/60)+' мин '+seconds%60+' с';}
 function timing(row,now){
  if(count(row.durationMs)!==null)return {value:row.durationMs,note:row.durationSource==='derived-from-observed-turn-bounds'?'По наблюдаемым границам':''};
  const start=Date.parse(row.startedAt||'');
  if(row.status==='working'&&!row.endedAt&&Number.isFinite(start)&&start<=now)return {value:Math.floor(now-start),note:'С начала наблюдения · идёт сейчас, не завершённая длительность'};
  return {value:null,note:'Длительность неизвестна'};
 }
 function mount(container,{initialRoute,onRoute=()=>{},now=()=>Date.now(),externalNavigation=false}={}){
  const doc=container.ownerDocument,model=createModel(initialRoute);const node=(tag,cls,value)=>{const n=doc.createElement(tag);if(cls)n.className=cls;if(value!==undefined)n.textContent=value;return n;};
  const put=(n,value)=>{if(n.textContent!==String(value))n.textContent=String(value);};
  function button(label,action,cls='ow-button'){const n=node('button',cls,label);n.type='button';n.addEventListener('click',action);return n;}
  function list(parent,items,key,create,update){
   if(!parent._rows)parent._rows=new Map();const keep=new Set(),focused=doc.activeElement,positions=[];
   for(let n=parent;n;n=n.parentElement)positions.push([n,n.scrollTop,n.scrollLeft]);
   let cursor=parent.firstElementChild;
   for(const item of items){const k=key(item);keep.add(k);let n=parent._rows.get(k);if(!n){n=create(item);n.dataset.key=k;parent._rows.set(k,n);}update(n,item);
    if(n!==cursor)parent.insertBefore(n,cursor);cursor=n.nextElementSibling;
   }
   for(const [k,n] of parent._rows)if(!keep.has(k)){n.remove();parent._rows.delete(k);}
   if(focused?.isConnected&&doc.activeElement!==focused)focused.focus({preventScroll:true});
   for(const [n,top,left] of positions){n.scrollTop=top;n.scrollLeft=left;}
  }
  const shell=node('section','observed-work'),nav=node('nav','ow-nav'),fresh=node('details','ow-freshness'),freshLabel=node('summary'),freshBody=node('p','ow-secondary'),layout=node('div','ow-layout');
  nav.hidden=externalNavigation;nav.setAttribute('aria-label','Работа агентов');freshLabel.setAttribute('aria-label','Актуальность и охват источника');fresh.append(freshLabel,freshBody);
  const navButtons={};for(const [key,label] of [['home','Главная'],['projects','Проекты'],['history','История']]){const n=button(label,()=>navigate({page:key}));navButtons[key]=n;nav.append(n);}
  const main=node('section','ow-main'),heading=node('h2'),filter=node('select','ow-filter'),projectArea=node('section'),agents=node('div','ow-agent-map'),edges=node('ul','ow-relations'),projectHistory=button('История проекта',()=>navigate({page:'history',projectId:model.route.projectId}));
  filter.setAttribute('aria-label','Проект');filter.addEventListener('change',()=>navigate({...model.route,projectId:filter.value||null,agentId:null,sessionId:null}));
  const rows=node('div','ow-rows'),empty=node('p','ow-empty');
  projectArea.append(agents,edges,projectHistory);main.append(heading,filter,projectArea,rows,empty);
  const detail=node('section','ow-detail'),crumb=node('nav','ow-breadcrumb'),detailTitle=node('h3','ow-detail-title'),detailStatus=node('p','ow-secondary'),unavailable=node('p','ow-empty','Выбранное наблюдение недоступно в этом снимке.'),summary=node('dl','ow-metrics'),start=node('p','ow-secondary');
  crumb.setAttribute('aria-label','Путь к сессии');
  const crumbs={};for(const k of ['project','agent','session']){const n=button('',()=>{const s=model.selected;if(!s)return;if(k==='project')navigate({page:'projects',projectId:s.projectId});if(k==='agent')navigate({page:'projects',projectId:s.projectId,agentId:s.agentId});},'ow-crumb');crumbs[k]=n;crumb.append(n);}crumbs.session.disabled=true;
  const metricNodes={};for(const k of ['time','tokens','model']){const n=node('div'),label=node('dt'),value=node('dd'),note=node('p','ow-secondary');n.append(label,value,note);summary.append(n);metricNodes[k]={label,value,note};}
  function disclosure(label){const n=node('details','ow-disclosure'),s=node('summary','',label),body=node('div');n.append(s,body);return {node:n,body};}
  const usage=disclosure('Точный расход токенов'),usageList=node('dl','ow-facts ow-token-facts'),usageNodes={};for(const [k,label] of [['input','Вход'],['output','Выход'],['cachedInput','Кэшированный вход'],['reasoningOutput','Рассуждения']]){usageList.append(node('dt','',label));usageNodes[k]=node('dd');usageList.append(usageNodes[k]);}usage.body.append(usageList);
  const skillArea=node('section','ow-skills'),skillNames=node('div','ow-chips'),skillNote=node('p','ow-secondary'),tabs=node('div','ow-tabs');tabs.setAttribute('role','tablist');tabs.setAttribute('aria-label','Сведения о сессии');
  const activityPanel=node('section'),taskPanel=node('section'),activity=node('ol','ow-events'),turns=node('div','ow-turns'),activityEmpty=node('p','ow-secondary'),taskGoal=node('p'),taskEmpty=node('p','ow-secondary','Контекст задачи не предоставлен.'),identity=disclosure('Источник и идентификаторы'),identityText=node('dl','ow-facts'),diagnostics=disclosure('Область и происхождение измерений'),diagnosticText=node('dl','ow-facts');
  identity.body.append(identityText);diagnostics.body.append(diagnosticText);taskPanel.append(taskGoal,taskEmpty,identity.node);activityPanel.append(activity,activityEmpty,turns);skillArea.append(skillNames,skillNote);
  let selectedId=null;const sessionState=new Map();let tab='activity';const tabButtons={};for(const [key,label] of [['activity','Активность'],['task','Контекст задачи']]){const n=button(label,()=>{tab=key;remember();patchTabs();});n.setAttribute('role','tab');tabButtons[key]=n;tabs.append(n);}
  tabs.addEventListener('keydown',event=>{
   if(!['ArrowLeft','ArrowRight','Home','End'].includes(event.key))return;
   const items=Object.values(tabButtons),index=items.indexOf(event.target);if(index<0)return;
   const next=event.key==='Home'?0:event.key==='End'?items.length-1:(index+(event.key==='ArrowRight'?1:items.length-1))%items.length;
   event.preventDefault();items[next].click();items[next].focus({preventScroll:true});
  });
  function patchTabs(){activityPanel.hidden=tab!=='activity';taskPanel.hidden=tab!=='task';for(const [key,n] of Object.entries(tabButtons)){n.setAttribute('aria-selected',String(key===tab));n.tabIndex=key===tab?0:-1;}}
  function remember(){if(selectedId)sessionState.set(selectedId,{tab,usage:usage.node.open,identity:identity.node.open,diagnostics:diagnostics.node.open});}
  let listReturn=null;const back=button('Назад к списку',returnToList,'ow-button ow-back');
  const detailsBody=node('div');detailsBody.append(detailTitle,detailStatus,summary,start,usage.node,skillArea,tabs,activityPanel,taskPanel,diagnostics.node);detail.append(back,crumb,unavailable,detailsBody);layout.append(main,detail);shell.append(nav,fresh,layout);container.append(shell);
  detailTitle.tabIndex=-1;heading.tabIndex=-1;
  function positions(){const saved=[];for(let n=rows;n;n=n.parentElement)saved.push([n,n.scrollTop,n.scrollLeft]);return saved;}
  function reveal(target){
   target.focus({preventScroll:true});
   const rect=target.getBoundingClientRect(),viewport=doc.defaultView?.innerHeight||doc.documentElement.clientHeight;
   let top=0,bottom=viewport;
   for(let n=target.parentElement;n;n=n.parentElement)if(n.clientHeight>0&&n.scrollHeight>n.clientHeight){const bounds=n.getBoundingClientRect();top=Math.max(top,bounds.top);bottom=Math.min(bottom,bounds.bottom);}
   if(rect.top<top||rect.bottom>bottom)target.scrollIntoView({block:'start',inline:'nearest',behavior:'auto'});
  }
  function returnToList(){
   const saved=listReturn||{route:{...model.route,sessionId:null},selectedId:model.route.sessionId,positions:[]};
   navigate(saved.route);
   for(const [n,top,left] of saved.positions){n.scrollTop=top;n.scrollLeft=left;}
   reveal(rows._rows?.get(saved.selectedId)||heading);
  }
  function navigate(r){
   const previous=model.route.sessionId,destination=route(r),different=destination.sessionId&&destination.sessionId!==previous;
   if(different)listReturn={route:{...destination,sessionId:null},selectedId:destination.sessionId,positions:positions()};
   remember();model.navigate(destination);patch();onRoute(model.route);
   if(different&&model.selected?.id===destination.sessionId)reveal(detailTitle);
  }
  function facts(parent,values){list(parent,values,x=>x[0],()=>{const n=node('div'),k=node('dt'),v=node('dd');n.append(k,v);n._k=k;n._v=v;return n;},(n,[k,v])=>{put(n._k,k);put(n._v,v??'Неизвестно');});}
  function eventRows(parent,items){list(parent,items,x=>x.id,()=>{const n=node('li'),at=node('time'),label=node('span');n.append(at,label);n._at=at;n._label=label;return n;},(n,e)=>{put(n._at,e.at?new Date(e.at).toLocaleTimeString('ru-RU',{hour:'2-digit',minute:'2-digit',second:'2-digit'}):'Время неизвестно');if(e.at)n._at.setAttribute('datetime',e.at);else n._at.removeAttribute('datetime');put(n._label,e.label);});}
  function patchDetail(){
   const r=model.route,s=model.selected;layout.classList.toggle('ow-detail-selected',Boolean(r.sessionId));detail.hidden=!r.sessionId;unavailable.hidden=!!s;detailsBody.hidden=!s;crumb.hidden=!s;if(!s)return;
   if(selectedId!==s.id){remember();selectedId=s.id;const saved=sessionState.get(s.id)||{};tab=saved.tab||'activity';usage.node.open=!!saved.usage;identity.node.open=!!saved.identity;diagnostics.node.open=!!saved.diagnostics;}
   const project=model.data.projects.find(p=>p.id===s.projectId),agent=model.data.agents.find(a=>a.id===s.agentId);
   put(crumbs.project,project?.name||'Проект неизвестен');put(crumbs.agent,agent?.name||'Агент неизвестен');crumbs.agent.disabled=!s.agentId;put(crumbs.session,s.scope.kind==='turn'?'Выполнение':'Сессия');
   put(detailTitle,s.task?.title||s.name);put(detailStatus,executionLabel(s)+' · '+({complete:'Полное наблюдение',partial:'Частичное наблюдение',unknown:'Полнота неизвестна'}[s.coverage]));
   const t=timing(s,now());put(metricNodes.time.label,'Время');put(metricNodes.time.value,duration(t.value));put(metricNodes.time.note,t.note);metricNodes.time.note.hidden=!t.note;
   put(metricNodes.tokens.label,'Токены');put(metricNodes.tokens.value,number(s.usage.total));put(metricNodes.tokens.note,s.scope.kind==='turn'?'За выполнение':s.scope.kind==='session'?'За сессию':'За явный интервал');
   put(metricNodes.model.label,'Модель');put(metricNodes.model.value,s.model||'Неизвестно');put(metricNodes.model.note,s.effort?'Усилие · '+s.effort:'Усилие неизвестно');
   put(start,s.startedAt?'Начало · '+new Date(s.startedAt).toLocaleString('ru-RU'):'Начало неизвестно');
   for(const [k,n] of Object.entries(usageNodes))put(n,number(s.usage[k]));
   const applications=s.appliedSkills||[],skills=[...new Set(applications.map(e=>e.skillId))];list(skillNames,skills,x=>x,()=>node('span','ow-chip'),(n,k)=>put(n,k));put(skillNote,s.appliedSkills===null?'Применение навыков неизвестно':applications.length?'Сообщено исполнителем':'Применения не сообщены');
   const applicationEvents=applications.map(e=>({id:'applied:'+e.id,at:e.at,label:'Применён навык · '+e.skillId}));
   eventRows(activity,[...s.events.map(e=>({...e,id:'event:'+e.id})),...applicationEvents].sort((a,b)=>String(a.at||'').localeCompare(String(b.at||''))||a.id.localeCompare(b.id)));
   put(activityEmpty,'События не предоставлены.');activityEmpty.hidden=!!(s.events.length+applications.length);
   list(turns,s.turns.length>1?s.turns:[],x=>x.id,()=>{const n=node('details','ow-turn'),h=node('summary'),list=node('ol','ow-events');n.append(h,list);n._h=h;n._list=list;return n;},(n,t)=>{put(n._h,t.name+' · '+statusText[t.status]+' · '+number(t.usage.total)+' токенов');eventRows(n._list,t.events);});
   put(taskGoal,s.task?.goal||'');taskGoal.hidden=!s.task?.goal;taskEmpty.hidden=!!(s.task?.goal||s.task?.identity?.taskKey);identity.node.hidden=!s.task;
   facts(identityText,Object.entries(s.task?.identity||{}));facts(diagnosticText,[['Область',({turn:'Наблюдаемый ход',session:'Наблюдаемая сессия',interval:'Явный интервал'}[s.scope.kind])],['ID области',s.scope.id],['ID наблюдения',s.id],['Наблюдаемый родитель',s.parentId],['Источник длительности',s.durationSource],['Состояние источника',model.data.source.originalStatus||model.data.source.status],['Сведения источника',model.data.source.message],['Проверка','Сообщённые данные не являются независимой проверкой исполнения']]);
   patchTabs();
  }
  function patch(){
   const r=model.route,d=model.data;for(const [k,n] of Object.entries(navButtons))n.setAttribute('aria-current',k===r.page?'page':'false');
   put(freshBody,d.source.message||'Охват определяется подключённым источником. Отсутствие сессии не подтверждает отсутствие работы вне него.');
   put(freshLabel,({fresh:'Источник доступен',partial:'Частичный снимок',stale:'Данные устарели',unavailable:'Источник недоступен',unknown:'Актуальность неизвестна'}[d.source.status])+(d.source.readAt?' · '+new Date(d.source.readAt).toLocaleTimeString('ru-RU'):''));
   put(heading,{home:'Сейчас',projects:'Проекты',history:'История'}[r.page]);
   list(filter,[{id:'',name:r.page==='projects'?'Выберите проект':'Все проекты'},...d.projects],x=>x.id,()=>node('option'),(n,p)=>{n.value=p.id;put(n,p.name);});filter.value=r.projectId||'';filter.hidden=r.page==='home';projectArea.hidden=r.page!=='projects';
   const active=model.projectAgents(r.projectId);list(agents,r.page==='projects'?active:[],x=>x.id,a=>button('',()=>navigate({page:'projects',projectId:a.projectId,agentId:a.id}),'ow-agent'),(n,a)=>put(n,a.name+' · '+a.currentCount));
   list(edges,r.page==='projects'?model.projectEdges(r.projectId):[],x=>x.id,()=>node('li'),(n,e)=>{const names=k=>d.agents.find(a=>a.id===k)?.name||k;put(n,names(e.fromAgentId)+' → '+names(e.toAgentId)+' · '+e.label);});projectHistory.hidden=!r.projectId;
   const sessions=model.rows();list(rows,sessions,x=>x.id,s=>{const n=button('',()=>navigate({...model.route,sessionId:s.id}),'ow-session'),title=node('span','ow-session-title'),status=node('span','ow-status'),scope=node('span','ow-secondary');n.append(title,status,scope);n._title=title;n._status=status;n._scope=scope;return n;},(n,s)=>{const agentName=d.agents.find(a=>a.id===s.agentId&&a.projectId===s.projectId)?.name||'Агент неизвестен';put(n._title,s.task?.title||agentName+' · '+s.name);n.title=s.id;put(n._status,executionLabel(s));const scopeLabel=s.scope.kind==='turn'?'За выполнение':s.scope.kind==='session'?'За сессию':'За интервал';const date=s.endedAt?new Date(s.endedAt).toLocaleString('ru-RU',{year:'numeric',month:'short',day:'numeric',hour:'2-digit',minute:'2-digit'}):'Дата неизвестна';put(n._scope,(d.projects.find(p=>p.id===s.projectId)?.name||'Проект неизвестен')+' · '+(s.task?.title?agentName+' · ':'')+(r.page==='history'?scopeLabel+' · '+date+' · '+duration(timing(s,now()).value)+' · ':'')+number(s.usage.total)+' токенов');n.setAttribute('aria-pressed',String(s.id===r.sessionId));});
   put(empty,r.page==='projects'&&!r.projectId?'Выберите проект.':['unavailable','unknown'].includes(d.source.status)?'Текущий список не подтверждён источником.':r.page==='home'?'Текущие исполнения не наблюдаются.':r.page==='history'?'Завершённые исполнения не наблюдаются.':'Выберите проект или наблюдаемую сессию.');empty.hidden=sessions.length>0;patchDetail();
  }
  patch();return {model,update(feed){remember();model.update(feed);patch();},navigate,destroy(){shell.remove();},element:shell};
 }
 const api=Object.freeze({normalize,createModel,parseRoute,formatRoute,mount,timing,number,duration});
 if(typeof module==='object'&&module.exports)module.exports=api;else root.AgentCityObserved=api;
})(typeof globalThis==='object'?globalThis:this);
