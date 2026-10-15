'use strict';
// Views join observed projections by their authority identity, never by title.
(()=>{
 let opened=null,origin='tasks',tab='overview',selectedStage=null,screenKey=null,editor=null,editorVersion=null,loading=false,creationQueued=null;
 const filters={query:'',project:'all',status:'all',history:false};
 const identity=(ns,id)=>JSON.stringify([ns,id]);
 const localLabels={planned:'Запланировано',running:'Работает',waiting:'Ожидает',checking:'На проверке','decision-needed':'Нужно решение',done:'Завершено',error:'Ошибка',cancelled:'Отменено',unknown:'Нет данных'};
 function latest(runs){return [...runs].sort((a,b)=>(Date.parse(b.receivedAt||b.updatedAt)||0)-(Date.parse(a.receivedAt||a.updatedAt)||0))[0];}
 function records(){
  const data=dashboardData?.cicada||{},ns=data.source?.sourceNamespace,all=new Map(),keys=new Map(),native=new Map();
  function add(record){all.set(record.key,record);for(const key of record.aliases)if(key)keys.set(key,record);if(record.sourceId&&record.namespace)native.set(identity(record.namespace,record.sourceId),record);return record;}
  for(const task of [...(data.availableTasks||[]),...(data.historyTasks||[]),...(data.tasks||[])]){
   const authority=task.sourceId&&ns?identity(ns,task.sourceId):task.taskKey,old=native.get(authority)||keys.get(task.taskKey);
   const aliases=[...new Set([...(old?.aliases||[]),...(task.runTaskKeys||[]),task.taskKey])];
   const record={...old,key:old?.key||task.taskKey,task,title:task.title,source:'Cicada',sourceId:task.sourceId,namespace:ns,aliases,completed:!!task.completed,runs:[],projectId:task.projectId||'',project:task.projectLabel||'',current:false};
   if(old)all.delete(old.key);add(record);
  }
  for(const task of Object.values(sharedState?.tasks||{})){
   const binding=task.binding,byKey=keys.get(binding.taskKey),old=native.get(identity(binding.sourceNamespace,binding.sourceId))||(byKey?.namespace===binding.sourceNamespace?byKey:null);
   if(old)all.delete(old.key);
   add({key:binding.taskKey,task,native:old?.task,shared:task,title:task.title,source:'Cicada',sourceId:binding.sourceId,namespace:binding.sourceNamespace,aliases:[...new Set([...(old?.aliases||[]),binding.taskKey])],completed:!!task.completed,runs:[],projectId:old?.projectId||'',project:old?.project||'',current:false});
  }
  const registry=dashboardData?.workRegistry||{};
  for(const entry of Object.values(registry.publishers||{})){
   const snapshot=entry.snapshot;if(!snapshot)continue;
   for(const task of snapshot.tasks||[]){
    const binding=task.localBinding,paired=binding&&registry.bindings?.[binding.taskKey];
    const matched=paired&&paired.binding.sourceNamespace===binding.sourceNamespace&&paired.binding.sourceId===binding.sourceId&&paired.source.selectedId===data.source?.id&&paired.source.sourceNamespace===ns;
    const old=matched&&(native.get(identity(binding.sourceNamespace,binding.sourceId))||keys.get(binding.taskKey));
    const project=(snapshot.projects||[]).find(p=>p.id===task.projectId),projectId=identity(snapshot.source.sourceNamespace,task.projectId);
    if(old){old.registry={task,snapshot,entry};old.projectId=projectId;old.project=project?.title||task.projectId;continue;}
    add({key:`registry:${snapshot.source.sourceNamespace}:${task.id}`,task,title:task.title,source:snapshot.source.publisherId,namespace:snapshot.source.sourceNamespace,sourceId:task.id,aliases:matched?[binding.taskKey]:[],registry:{task,snapshot,entry},completed:['done','cancelled'].includes(task.status),runs:[],projectId,project:project?.title||task.projectId,current:false,readOnly:true});
   }
  }
  for(const run of dashboardData?.runs||[]){
   const key=run.taskKey||`run:${run.originDevice||'local'}:${run.runId}`;
   let record=keys.get(key)||all.get(key);
   if(!record){record=add({key,task:{taskKey:key,title:run.taskKey?t('Задача Cicada')+' · '+run.taskKey:t('Запуск без задачи')+' · '+run.runId},title:run.taskKey?t('Задача Cicada')+' · '+run.taskKey:t('Запуск без задачи')+' · '+run.runId,source:run.originDevice||'Agent City',aliases:[key],runs:[],completed:false,current:false,projectId:'',project:'',missingSource:true,readOnly:true});}
   record.runs.push(run);
  }
  for(const record of all.values()){
   if(record.shared)record.runs=[...(record.shared.reports||[]).map(raw=>{const run=sharedReport(raw);return {...run,_sharedReport:true,taskKey:record.key,updatedAt:run.updatedAt||run.reportedAt||run.receivedAt};}),...record.runs];
   record.runs=aggregateRuns(record.runs).runs;
   const run=latest(record.runs),nativeCurrent=(data.tasks||[]).some(task=>record.aliases.includes(task.taskKey));
   record.lastReport=run;record.updatedAt=run?.receivedAt||run?.updatedAt||record.task.lastUpdatedAt||record.task.lastUpdated;
   const fresh=run=>run._sharedReport?sharedRunFresh(run):freshRun(run);
   record.running=record.runs.some(run=>run.status==='running'&&fresh(run));record.waiting=record.runs.some(run=>run.status==='waiting'&&fresh(run));
   record.failedAttempts=record.runs.filter(run=>run.status==='error').length;
   record.current=!record.completed&&(nativeCurrent||record.task.isActive||record.task.isPaused||record.task.humanTimerActive||record.task.humanTimerPaused||['awaiting_review','awaiting_dispatch'].includes(record.shared?.review?.state)||record.running||record.waiting);
   if(record.missingSource)record.completed=!!run&&!['running','waiting'].includes(run.status);
   record.status=record.shared?.review?.state==='awaiting_review'?'review':record.shared?.review?.state==='awaiting_dispatch'?'waiting':record.completed?'done':record.running?'working':record.task.isPaused||record.task.humanTimerPaused?'paused':record.task.waiting||record.waiting?'waiting':record.failedAttempts?'error':record.registry?record.task.status:'idle';
  }
  return [...all.values()].sort((a,b)=>Number(b.current)-Number(a.current)||(b.updatedAt||'').localeCompare(a.updatedAt||'')||a.title.localeCompare(b.title));
 }
 function find(key){return records().find(record=>record.key===key||record.aliases.includes(key));}
 function status(record){
  if(record.shared&&(record.completed||['awaiting_review','awaiting_dispatch'].includes(record.shared.review?.state)))return t(record.completed?(record.shared.review?.state==='accepted'?'Результат принят':'Задача завершена'):sharedExecution(record.shared));
  if(record.registry&&record.readOnly){const {task,snapshot}=record.registry;const elapsed=Date.now()-Date.parse(task.lastUpdated),fresh=elapsed>=0&&elapsed<=snapshot.staleAfterSeconds*1000;return t(localLabels[task.status]||task.status)+(fresh?'':' · '+t('Данные могут устареть'));}
  if(record.completed&&!record.missingSource)return t('Задача завершена в Cicada');
  if(record.running)return t(record.shared?'ИИ работает · по отчёту':'ИИ работает');
  if(record.waiting)return t(record.shared?'ИИ ожидает · по отчёту':'ИИ ожидает');
  if(record.runs.some(run=>['running','waiting'].includes(run.status)))return t('Нет свежего отчёта');
  if(record.failedAttempts)return t('Неудачных попыток: {count}',{count:record.failedAttempts});
  if(record.runs.length&&record.runs.every(run=>run.status==='done'))return t('ИИ: {status}',{status:t('Завершено')});
  if(record.runs.length)return Object.entries(aggregateRuns(record.runs).overall.statuses).map(([status,count])=>t(runStatuses[status]||'Нет данных')+': '+count).join(' · ');
  if(record.shared)return t(sharedExecution(record.shared));
  return t('Статус ИИ неизвестен');
 }
 function row(record){
  const {row,main}=taskWidgetRow(record.title,{taskKey:record.key,onOpen:()=>open(record.key),status:status(record),tone:record.status==='review'?'review':record.completed?'accepted':record.status==='working'?'active':record.lastReport?.status==='error'?'warn':'neutral'});
  if(record.shared)row.dataset.sharedTaskId=record.shared.id;
  const run=record.lastReport,meta=[record.project,record.task.stageLabel||record.task.stage,run?.agent,run?.model].filter(Boolean);
  if(run?.receivedAt||run?.updatedAt)meta.push(t('Отчёт')+': '+when(run.receivedAt||run.updatedAt));
  if(record.task.isActive||record.task.humanTimerActive)meta.push(t('Твой таймер идёт'));
  if(record.shared?.freshness==='stale')meta.push(t('Данные могут устареть'));
  if(meta.length)main.append(el('p','task-meta',meta.join(' · '),true));
  return row;
 }
 function button(text,fn,id,disabled=false){const b=sharedButton(t(text),fn,disabled);b.className='text-button';b.dataset.taskLabel=text;if(id)b.id=id;return b;}
 function reportTask(record){return {...record.native,...record.task,title:record.title};}
 function mount(){
  const root=$('tasks-workspace');if(!root||$('task-list-screen'))return root;
  const list=el('div','task-list-screen');list.id='task-list-screen';
  const heading=el('header','task-list-header');heading.append(el('h1','','Задачи'));const actions=el('div','task-inline-actions');actions.id='task-list-actions';heading.append(actions);list.append(heading);
  const tabs=el('nav','task-local-tabs');tabs.setAttribute('aria-label',t('Список задач'));tabs.append(button('Все задачи',()=>{filters.history=false;render();},'tasks-current-tab'),button('История',()=>{filters.history=true;render();},'tasks-history-tab'));list.append(tabs);
  const controls=el('div','task-list-filters'),search=document.createElement('input');search.id='tasks-search';search.type='search';search.placeholder=t('Найти задачу');search.setAttribute('aria-label',t('Найти задачу'));search.addEventListener('input',()=>{filters.query=search.value;renderList();});search.addEventListener('keydown',e=>{if(e.key!=='Enter')return;const key=taskKeyFromSearch(search.value);if(!key)return;e.preventDefault();const record=find(key);if(record)open(record.key);else toast('Отчёт не найден в этом источнике Cicada.');});
  const project=document.createElement('select');project.id='tasks-project';project.setAttribute('aria-label',t('Проект'));project.addEventListener('change',()=>{filters.project=project.value;renderList();});
  const states=document.createElement('select');states.id='tasks-status';states.setAttribute('aria-label',t('Состояние задачи'));for(const [value,label] of [['all','Все состояния'],['current','Текущая работа'],['working','ИИ работает'],['review','На проверке'],['waiting','Ожидают'],['paused','Таймер на паузе'],['error','Ошибка']])states.append(new Option(t(label),value));states.addEventListener('change',()=>{filters.status=states.value;renderList();});controls.append(search,project,states);list.append(controls);
  const exchange=el('div','task-exchange-status');exchange.id='task-exchange-status';list.append(exchange);
  const error=el('p','notice');error.id='tasks-error';error.setAttribute('role','status');error.hidden=true;list.append(error);
  const rows=el('div','task-widget');rows.id='tasks-list';list.append(rows);const empty=el('p','task-empty','Задач нет');empty.id='tasks-empty';list.append(empty);
  const pending=el('section','task-pending');pending.id='tasks-pending';list.append(pending);
  const screen=el('article','task-screen');screen.id='task-screen';screen.hidden=true;root.append(list,screen);return root;
 }
 function pendingItems(root,taskId){
  root.replaceChildren();
  const drafts=JSON.parse(localStorage.getItem('agent-city-shared-unsent-v1')||'{}');
  for(const [op,draft] of Object.entries(drafts)){if(taskId!==undefined&&draft.arguments.taskId!==taskId)continue;const item=el('section','shared-pending');item.append(el('h3','','Черновик: ответ на отправку не получен'),el('pre','',JSON.stringify(draft.arguments,null,2),true),button('Повторить ту же отправку',()=>sharedAction(()=>sendLocalSharedDraft(op))));root.append(item);}
  for(const [op,item] of Object.entries(sharedState?.outbox||{})){if(taskId!==undefined&&item.request.arguments.taskId!==taskId)continue;const row=el('section','shared-pending');row.append(el('h3','',item.state==='pending'?'Изменение ожидает отправки':item.state==='conflict'?'Конфликт изменений':'Изменение отклонено'),el('p','source-path',op,true));const comparison=el('pre','');comparison.textContent=JSON.stringify({draft:item.request.arguments,...(item.conflict?{current:item.conflict.current}:{})},null,2);row.append(comparison);if(item.conflict)row.append(el('p','',sharedError(item.conflict.code),true));if(item.state!=='pending')row.append(button('Убрать из очереди, сохранить в истории',()=>sharedAction(()=>request('/api/task-sync/resolve',{operationId:op,revision:sharedState.revision}))));root.append(row);}
  root.hidden=!root.children.length;
 }
 function renderList(){
  const all=records(),rows=$('tasks-list');if(!rows)return;
  const projects=new Map(all.filter(r=>r.projectId).map(r=>[r.projectId,r.project]));$('tasks-project').replaceChildren(new Option(t('Все проекты'),'all'),new Option(t('Без проекта'),'none'),...[...projects].map(([id,name])=>new Option(name,id)));$('tasks-project').value=filters.project;
  const query=filters.query.trim().toLowerCase(),matches=all.filter(record=>filters.history?record.completed||record.missingSource:!record.completed).filter(record=>filters.project==='all'||filters.project==='none'&&!record.projectId||record.projectId===filters.project).filter(record=>filters.status==='all'||filters.status==='current'&&record.current||filters.status==='error'&&record.lastReport?.status==='error'||record.status===filters.status).filter(record=>[record.title,record.key,record.sourceId,record.project,record.task.stageLabel,record.task.stage,...record.runs.flatMap(run=>[run.agent,run.model])].filter(Boolean).join(' ').toLowerCase().includes(query));
  const focused=document.activeElement?.dataset.taskKey;rows.replaceChildren(...matches.map(row));if(focused)[...rows.querySelectorAll('button')].find(b=>b.dataset.taskKey===focused)?.focus({preventScroll:true});$('tasks-empty').hidden=!!matches.length;$('tasks-empty').textContent=t(query?'Ничего не нашлось':'Задач нет');
  for(const [id,selected] of [['tasks-current-tab',!filters.history],['tasks-history-tab',filters.history]])$(id).setAttribute('aria-current',selected?'page':'false');
  const actions=$('task-list-actions');actions.replaceChildren();if(sharedState?.config.enabled)actions.append(button('Добавить общую задачу',()=>openShared(null),null,!sharedState.config.scopes.includes('tasks:write')),button('Обновить общие задачи',()=>sharedAction(()=>request('/api/task-sync/exchange',{}))));
  renderTaskExchangeStatus();pendingItems($('tasks-pending'));
  const data=dashboardData?.cicada,error=$('tasks-error'),limited=data?.availableLimited||data?.historyLimited;error.hidden=!(sharedReadFailed||data?.status==='error'||data?.availableStatus&&data.availableStatus!=='connected'||limited);error.textContent=t(sharedReadFailed?'Состояние обмена недоступно':data?.status==='error'?data.error||'Данные задач недоступны.':data?.availableStatus&&data.availableStatus!=='connected'?'Данные задач недоступны.':limited?'Источник ограничил список задач до 500 записей.':'');
 }
 function editorDirty(){return editor&&[...editor.querySelectorAll('input,textarea')].some(node=>node.value!==node.dataset.initialValue);}
 function discardEditor(){if(!editor)return;for(const node of editor.querySelectorAll('input,textarea'))window.agentCityDrafts?.reset(node);}
 function changeTask(key){if(screenKey!==null&&screenKey!==key&&editorDirty()){if(!confirm(t('Есть несохранённые изменения. Закрыть без сохранения?')))return false;discardEditor();}return true;}
 function open(key){const record=find(key);if(!record||!changeTask(record.key))return;if(!opened)origin=view==='dashboard'?'dashboard':'tasks';opened=record.key;tab='overview';selectedStage=null;setView('tasks');render();}
 function openShared(id){if(id){const record=records().find(r=>r.shared?.id===id);if(record)open(record.key);return;}if(!changeTask('new'))return;if(creationQueued&&!editorDirty()){screenKey=null;creationQueued=null;}if(!opened)origin=view==='dashboard'?'dashboard':'tasks';opened='new';tab='overview';setView('tasks');render();}
 function back(){opened=null;render();setView(origin);}
 function field(parent,label,value='',multiline=false){const node=sharedField(parent,label,value,multiline);node.dataset.initialValue=node.value;return node;}
 function can(scope,task){const c=sharedState?.config;return !!c?.enabled&&c.scopes.includes(scope)&&(!task||!c.taskIds||c.taskIds.includes(task.id));}
 function buildScreen(record){
  const screen=$('task-screen');screen.replaceChildren();screenKey=opened;editor=null;editorVersion=null;
  screen.append(button(origin==='dashboard'?'Назад к дашборду':'Назад к задачам',back,'close-dashboard-task'));
  const heading=el('header','task-screen-header'),identity=el('div','task-screen-identity');const title=el('h1','');title.id='dashboard-task-title';identity.append(title);const meta=el('p','task-meta');meta.id='task-screen-meta';identity.append(meta);heading.append(identity);const state=el('span','task-screen-status');state.id='task-screen-status';heading.append(state);screen.append(heading);
  const actions=el('div','task-inline-actions');actions.id='dashboard-task-actions';screen.append(actions);
  const tabs=el('nav','task-local-tabs');tabs.setAttribute('role','tablist');tabs.setAttribute('aria-label',t('Задача'));for(const [key,label] of [['overview','Обзор'],['history','История'],['context','Контекст']]){const b=button(label,()=>{tab=key;renderScreen();},'task-tab-'+key);b.setAttribute('role','tab');b.setAttribute('aria-controls','task-panel-'+key);tabs.append(b);}screen.append(tabs);
  for(const key of ['overview','history','context']){const panel=el('section','task-local-panel');panel.id='task-panel-'+key;panel.setAttribute('role','tabpanel');panel.setAttribute('aria-labelledby','task-tab-'+key);screen.append(panel);}
  if(!record||record.shared){editor=el('div','task-editor');editor.id='shared-task-dialog';$('task-panel-context').append(editor);buildEditor(record?.shared);}
 }
 function buildEditor(task){
  const fields=el('section','task-edit-fields');fields.id='task-edit-fields';editor.append(fields);
  const title=field(fields,'Название',task?.title||''),content=field(fields,'Описание',task?.content||'',true);editorVersion=task?.version;
  if(!task){fields.append(button('Создать в Cicada',()=>sharedAction(async()=>{await queueShared('create',{title:title.value,content:content.value});if(!editorDirty())back();}),'create-shared-task',!can('tasks:write')));return;}
  const stage=field(fields,'Этап (ID)',task.stage||''),process=field(fields,'Процесс (ID)',task.process||'');
  const versioned=extra=>({taskId:task.id,expectedVersion:editorVersion,...extra});
  fields.append(button('Сохранить изменения',()=>sharedAction(()=>queueShared('patch',versioned({patch:{title:title.value,content:content.value,stage:stage.value,process:process.value}}))),'save-shared-task',!can('tasks:write',task)));
  const completion=button(task.completed?'Вернуть в текущие':'Завершить задачу',()=>sharedAction(()=>queueShared('patch',versioned({patch:{status:find(screenKey)?.shared?.completed?'task':'done'}}))),'toggle-shared-task',!can('tasks:write',task)||task.humanTimerActive);completion.hidden=!!task.review;fields.append(completion);
  const comments=el('section','task-feedback');comments.id='task-feedback';editor.append(comments);const feedback=field(comments,'Комментарий / отзыв','',true);comments.append(button('Добавить комментарий',()=>sharedAction(()=>queueShared('comment',versioned({comment:feedback.value}))),'comment-shared-task',!can('tasks:write',task)));
  const review=el('div','task-review-controls');review.id='task-review-controls';comments.append(review);
 }
 function refreshEditor(task){
  if(!editor||!task)return;
  if(!editorDirty()&&editorVersion!==task.version){for(const node of editor.querySelectorAll('[data-draft-field]')){const name=node.dataset.draftField;node.value=name==='comment'?'':task[name]||'';node.dataset.initialValue=node.value;window.agentCityDrafts?.reset(node);}editorVersion=task.version;}
  editor.querySelector('#save-shared-task').disabled=editor.querySelector('#comment-shared-task').disabled=!can('tasks:write',task);
  const completion=editor.querySelector('#toggle-shared-task'),label=task.completed?'Вернуть в текущие':'Завершить задачу';completion.dataset.taskLabel=label;completion.textContent=t(label);completion.hidden=!!task.review;completion.disabled=!can('tasks:write',task)||task.humanTimerActive;
  const review=editor.querySelector('#task-review-controls');review.replaceChildren();
  if(task.review?.state==='awaiting_review')for(const [decision,label] of [['accept','Принять в историю'],['rework','Запросить доработку']])review.append(button(label,()=>sharedAction(()=>queueShared('review',{taskId:task.id,expectedVersion:editorVersion,resultVersion:task.review.resultVersion,decision,...(decision==='rework'?{comment:editor.querySelector('[data-draft-field="comment"]').value}:{})})),null,!can('tasks:review',task)||task.humanTimerActive));
 }
 function reportActions(record){
  const actions=$('dashboard-task-actions');actions.replaceChildren();if(!record)return;
  const copy=(text,message)=>navigator.clipboard.writeText(text).then(()=>toast(message)).catch(()=>toast('Не удалось скопировать'));
  actions.append(button('Скопировать отчёт',()=>copy(taskReportText(reportTask(record),record.runs),'Отчёт скопирован'),'copy-task-report'),button('ID задачи',()=>copy(record.key,'ID скопирован'),'copy-task-id'),button('Ссылка',()=>{const url=new URL(location.href);url.search='';url.searchParams.set('task',record.key);url.hash='tasks';copy(url.href,'Ссылка скопирована');},'copy-report-link'));
  const pair=record.registry?.task.localBinding,run=record.runs[0];if(pair&&run)actions.append(button('Экспорт отчёта',async()=>{try{const value=await request('/api/work-exchange/export-report',{runId:run.runId}),blob=new Blob([JSON.stringify(value,null,2)],{type:'application/json'}),url=URL.createObjectURL(blob),link=document.createElement('a');link.href=url;link.download='cicada-run-report.json';link.click();setTimeout(()=>URL.revokeObjectURL(url),1000);}catch{toast('Отчёт недоступен для выбранного источника.');}},'export-task-report'));
  if(!record.shared&&!record.readOnly&&!record.completed&&record.sourceId&&Number.isInteger(record.task.version)){const connected=sharedState?.config.enabled&&sharedState.config.sourceNamespace===record.namespace;actions.prepend(button(connected?'Подключить задачу к обмену':'Настроить обмен задачами',()=>connected?sharedAction(async()=>{await queueShared('share',{taskId:record.sourceId,expectedVersion:record.task.version});const now=records().find(r=>r.shared?.id===record.sourceId&&r.namespace===record.namespace);if(now){opened=now.key;screenKey=null;render();}}):openTaskConnection(),'share-native-task',connected&&!can('tasks:write',{id:record.sourceId})));}
 }
 function section(root,title,text){const group=el('section','task-section');group.append(el('h2','',title));if(text)group.append(el('pre','task-output',text,true));root.append(group);return group;}
 function overview(record){
  const root=$('task-panel-overview');root.replaceChildren();
  if(!record){const pending=el('section','task-pending');root.append(pending);pendingItems(pending);return;}
  const total=aggregateRuns(record.runs),usage=tokenSummary(total.overall),time=taskTime(reportTask(record)),totals=el('dl','report-totals');totals.append(metricCell(usage.complete?'Всего токенов':'Учтено токенов',usage.known?formatCount(usage.value):'—',usage.known&&!usage.complete?t('Расход передан: {known} из {total} попыток',{known:reportedCoverage(total),total:total.overall.count}):null),metricCell('Время в Cicada',time.known?formatMinutes(time.minutes):'—',time.active?t('Без текущего активного отрезка'):null));root.append(totals);
  const task=record.shared,current=task?.results?.find(r=>r.version===task.review?.resultVersion)||task?.results?.at(-1);if(current)section(root,task.review?.state==='awaiting_review'?'Результат на проверке':task.review?.state==='accepted'?'Результат принят':'Результат',current.content);
  else if(record.registry?.task.result)section(root,'Результат',record.registry.task.result);
  const stages=[...total.stages];if(total.unallocated.length)stages.push({stage:'',unallocated:true,runs:total.unallocated,totals:aggregateRuns(total.unallocated).overall});
  if(stages.length){const group=section(root,'Этапы исполнения'),selector=el('div','task-stage-selector');selector.setAttribute('role','tablist');selector.setAttribute('aria-label',t('Этапы исполнения'));if(!stages.some(s=>(s.unallocated?'unallocated':s.stage)===selectedStage))selectedStage=stages.find(s=>s.stage===record.task.stageLabel||s.stage===record.task.stage)?.stage||(stages.at(-1).unallocated?'unallocated':stages.at(-1).stage);
   for(const [index,stage] of stages.entries()){const key=stage.unallocated?'unallocated':stage.stage,state=groupState(stage.runs),b=button(stage.unallocated?'Без распределения по этапам':stage.stage||t('Этап не сообщён'),()=>{selectedStage=key;renderScreen();},'task-stage-choice-'+index);b.dataset.stageKey=key;b.className='task-stage-choice';b.setAttribute('role','tab');b.setAttribute('aria-controls','task-stage-details');b.tabIndex=key===selectedStage?0:-1;b.setAttribute('aria-selected',String(key===selectedStage));b.append(el('span','task-stage-state',state.label));selector.append(b);}group.append(selector);
   const selected=stages.find(s=>(s.unallocated?'unallocated':s.stage)===selectedStage),detail=el('section','task-stage-details');detail.id='task-stage-details';detail.append(el('h3','',selected.unallocated?'Без распределения по этапам':selected.stage||t('Этап не сообщён')),stageResources(selected.totals));if(selected.unallocated)detail.append(el('p','report-hint','Расход по этапам не определён: этап менялся или история запуска ограничена. Общие счётчики учтены один раз.'));detail.append(...selected.runs.map(run=>drawRun(run)));group.append(detail);
  }else if(record.task.stageLabel||record.task.stage){section(root,'Этап',record.task.stageLabel||record.task.stage);}
  if(editor)refreshEditor(task);
  const pending=el('section','task-pending');root.append(pending);pendingItems(pending,record.shared?.id||record.sourceId);
 }
 function historyPanel(record){
  const root=$('task-panel-history');root.replaceChildren();if(!record)return;const task=record.shared||record.task;
  const history=section(root,'История');history.classList.add('shared-task-history');
  const entry=(title,text,at)=>{const item=el('article','shared-history-entry');item.append(el('h4','',title,true));if(text)item.append(el('pre','task-output',text,true));if(at)item.append(el('p','task-meta',when(at),true));history.append(item);};
  const names={accept:'Принято',rework:'Запрошена доработка',submit_result:'Передано на проверку',publish:'Передано на проверку',acknowledge:'Исполнитель подтвердил доработку'};
  for(const result of task.results||[])entry(t('Результат {version}',{version:result.version}),result.content,result.at);
  for(const event of task.history||[])entry(t(names[event.action]||event.action),event.comment,event.at);
  for(const comment of task.comments||[])entry(t('Комментарий'),comment.content,comment.at);
  for(const intent of task.intents||[])entry(t(intent.state==='awaiting_dispatch'?'Доработка ожидает исполнителя':'Запрос на доработку'),intent.comment,intent.at);
  for(const event of task.stageHistory||[])entry(t('Этап')+': '+(event.stageLabel||event.stage||'—'),null,event.at);
  for(const run of record.runs)history.append(drawRun(run));
 }
 function contextPanel(record){
  const root=$('task-panel-context');root.replaceChildren();if(!record)return;
  if(record.task.content&&!record.shared)section(root,'Описание',record.task.content);
  const metrics=el('dl','task-context-fields');for(const [label,value] of [['Источник',record.source],['ID задачи',record.sourceId||record.key],['Пространство источника',record.namespace],['Версия',record.task.version],['Проект',record.project],['Процесс',record.task.processLabel||record.task.process],['Подтверждение',record.registry?.task.provenance.reference]])if(value!==undefined&&value!==null&&value!=='')metrics.append(el('dt','',label),el('dd','',String(value),true));root.append(metrics);
  if(record.shared)root.append(el('p','task-meta',t('Обмен')+': '+(sharedState.lastSuccess?when(sharedState.lastSuccess):t('Обмен ещё не подтверждён')),true));
  if(record.registry){for(const [label,key] of [['Операция','operation'],['Ожидает','waitingFor']])if(record.registry.task[key])section(root,label,record.registry.task[key]);}
  if(record.missingSource)root.append(el('p','report-hint',record.key.startsWith('run:')?'Не привязан к задаче Cicada.':'Название недоступно в выбранной Cicada. Отчёты сохранены.'));
  root.append(el('p','task-meta',t('Токены — по отчётам, время — по таймеру Cicada. Прочерк означает отсутствие данных.')));
 }
 function renderScreen(){
  const record=opened==='new'?null:find(opened);if(screenKey!==opened||record?.shared&&!editor)buildScreen(record);
  const focused=document.activeElement?.id,scroll=window.scrollY;
  $('dashboard-task-title').textContent=record?.title||t(opened==='new'?'Новая общая задача':'Задача недоступна');$('task-screen-status').textContent=record?status(record):'';$('task-screen-meta').textContent=record?[record.project,record.task.stageLabel||record.task.stage].filter(Boolean).join(' · '):'';
  reportActions(record);if(record?.shared)$('dashboard-task-actions').append(button('Редактировать',()=>{tab='context';renderScreen();},'edit-shared-task'));for(const key of ['overview','history','context']){const selected=tab===key;$('task-tab-'+key).setAttribute('aria-selected',String(selected));$('task-tab-'+key).tabIndex=selected?0:-1;$('task-panel-'+key).hidden=!selected;}
  // Keep form nodes alive across refreshes so host draft acknowledgements stay exact.
  if(editor)editor.remove();overview(record);historyPanel(record);contextPanel(record);
  if(editor){const newTask=opened==='new';editor.querySelector('#task-edit-fields').hidden=!newTask&&tab!=='context';const feedback=editor.querySelector('#task-feedback');if(feedback)feedback.hidden=tab!=='overview';editor.hidden=!newTask&&(tab==='history'||!record);$(newTask?'task-panel-overview':tab==='history'?'task-panel-overview':'task-panel-'+tab).append(editor);}
  if(!record&&opened!=='new')$('task-panel-overview').append(el('p','notice','Задачи больше нет в выбранном источнике.'));
  if(focused&&$(focused))$(focused).focus({preventScroll:true});window.scrollTo(0,scroll);
 }
 function relabel(){
  for(const node of $('tasks-workspace').querySelectorAll('[data-task-label],[data-field-label]'))if(node.firstChild?.nodeType===3)node.firstChild.textContent=t(node.dataset.taskLabel||node.dataset.fieldLabel);
  $('task-list-screen').querySelector('h1').textContent=t('Задачи');$('tasks-search').placeholder=t('Найти задачу');$('tasks-search').setAttribute('aria-label',t('Найти задачу'));$('tasks-project').setAttribute('aria-label',t('Проект'));$('tasks-status').setAttribute('aria-label',t('Состояние задачи'));
  const labels={all:'Все состояния',current:'Текущая работа',working:'ИИ работает',review:'На проверке',waiting:'Ожидают',paused:'Таймер на паузе',error:'Ошибка'};for(const option of $('tasks-status').options)option.textContent=t(labels[option.value]);
  $('task-list-screen').querySelector('.task-local-tabs').setAttribute('aria-label',t('Список задач'));$('task-screen').querySelector('[role="tablist"]')?.setAttribute('aria-label',t('Задача'));
 }
 function render(){if(!mount())return;$('task-list-screen').hidden=!!opened;$('task-screen').hidden=!opened;if(opened)renderScreen();else renderList();relabel();}
 async function load(force=false){if(loading)return;loading=true;try{await loadDashboard(force);if(!sharedState||force)await loadSharedTasks();}finally{loading=false;render();}}
 window.AgentCityTasks=Object.freeze({render(){render();if(!dashboardData&&!loading)load();},load,records,row,find,open,openShared,isOpen:()=>!!opened,onNavigate(previous,next){const target=next||previous;if(target==='tasks'){render();scheduleDashboard();}return true;}});
 document.addEventListener('agentcity-task-command-queued',event=>{
  const {command,arguments:args}=event.detail,record=screenKey==='new'?null:find(screenKey);
  if(!editor||args.taskId!==record?.shared?.id||command==='create'&&screenKey!=='new')return;
  const submitted=command==='patch'?args.patch:command==='create'?{title:args.title,content:args.content}:command==='comment'||command==='review'&&args.decision==='rework'?{comment:args.comment}:{};
  for(const node of editor.querySelectorAll('[data-draft-field]'))if(Object.hasOwn(submitted,node.dataset.draftField))node.dataset.initialValue=String(submitted[node.dataset.draftField]);
  if(command==='create'){creationQueued=event.detail.operationId;if($('create-shared-task'))$('create-shared-task').disabled=true;}
 });
 document.addEventListener('keydown',event=>{
  const target=event.target;if(!target.closest('#task-screen [role="tablist"]')||!['ArrowLeft','ArrowRight','Home','End'].includes(event.key))return;
  const tabs=[...target.closest('[role="tablist"]').querySelectorAll('[role="tab"]')],index=tabs.indexOf(target);if(index<0)return;
  event.preventDefault();const next=tabs[event.key==='Home'?0:event.key==='End'?tabs.length-1:(index+(event.key==='ArrowRight'?1:tabs.length-1))%tabs.length];const id=next.id;next.click();$(id)?.focus();
 });
 document.addEventListener('agentcity-language-change',render);
})();
