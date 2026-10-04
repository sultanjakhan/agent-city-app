'use strict';
// Existing dashboard and native task identities; pending edits never become confirmed tasks.
let sharedState=null,sharedLoading=false,sharedBusy=false,sharedReadFailed=false;
const sharedText={task_connection_unavailable:'Приложение или канал недоступны. Проверь адрес и запусти фоновый канал.',task_authentication_missing:'В процессе приложения нет указанного секрета. Настрой переменную окружения и перезапусти фоновый сервис.',task_authentication_rejected:'Секрет не принят. Проверь учётные данные сервиса.',task_scope_denied:'Недостаточно прав для этой команды. Проверь области доступа и список ID.',task_namespace_changed:'Подключён другой источник. Верни прежний профиль или создай отдельный профиль данных.',task_source_change_requires_separate_profile:'Есть сохранённые задачи или черновики. Для другого источника используй отдельный профиль данных.',revision_conflict:'Задача изменена в другом приложении. Сравни версии и отправь новый черновик.',task_settings_conflict:'Настройки изменились. Обнови страницу и повтори.',human_timer_active:'Сначала останови свой таймер в Cicada.',review_controls_status:'Для результата используй принятие или доработку.',task_exchange_failed:'Обмен не завершён. Проверь настройки и повтори; черновики сохранены.'};
Object.assign(sharedText,{task_version_conflict:'Задача изменена в другом приложении. Сравни версии и отправь новый черновик.',execution_run_mismatch:'Эту доработку подтвердил другой запуск. Его работа не изменена; твой черновик сохранён.',operation_capacity:'Журнал операций Cicada заполнен. Обнови Cicada и повтори сохранённую отправку.',invalid_shared_text:'Текст слишком длинный или содержит неподдерживаемые символы. Исправь текст; прежняя отправка сохранена.'});
function sharedError(code){return sharedText[code]||`Обмен не выполнен (${code||'нет данных'}). Проверь настройки подключения.`;}
function isSharedTask(key,sourceId=null,sourceNamespace=null){return Object.values(sharedState?.tasks||{}).some(t=>t.binding.taskKey===key||sourceId&&sourceNamespace&&t.binding.sourceId===sourceId&&t.binding.sourceNamespace===sourceNamespace);}
function sharedRun(task){return [...task.reports].sort((a,b)=>(Date.parse(b.receivedAt)||0)-(Date.parse(a.receivedAt)||0)||(b.receivedOrder||0)-(a.receivedOrder||0))[0]||null;}
function sharedReport(run){return run?.report?{...run,...run.report}:run;}
function sharedRunFresh(run){const elapsed=Date.now()-Date.parse(run?.receivedAt);return elapsed>=0&&elapsed<=(sharedState?.config.staleAfterSeconds||300)*1000;}
function sharedExecution(task){
 if(task.review?.state==='awaiting_dispatch')return 'Доработка ожидает исполнителя';
 if(task.review?.state==='awaiting_review')return 'Результат ожидает проверки';
 const r=sharedRun(task),status=sharedReport(r)?.status;
 if(!status)return 'Статус ИИ неизвестен';
 const name={running:'ИИ работает · по отчёту',waiting:'ИИ ожидает · по отчёту',done:'ИИ закончил · по отчёту',error:'Ошибка ИИ · по отчёту',cancelled:'Запуск отменён · по отчёту'}[status]||'Статус ИИ неизвестен';
 return name+(sharedRunFresh(r)?'':' · нет свежего подтверждения');
}
async function loadSharedTasks(){
 if(sharedLoading)return;sharedLoading=true;
 try{sharedState=await request('/api/task-sync');sharedReadFailed=false;if(dashboardData)renderDashboardRows();}
 catch(e){sharedReadFailed=true;renderTaskExchangeStatus();}
 finally{sharedLoading=false;}
}
function sharedButton(label,action,disabled=false){const b=el('button','secondary',label,true);b.type='button';b.disabled=disabled;b.addEventListener('click',action);return b;}
function openTaskConnection(){selectSettingsTab('connectors');setView('settings');}
function renderTaskExchangeStatus(){
 const root=$('task-exchange-status');if(!root)return;root.replaceChildren();
 const value=sharedState,c=value?.config;
 let message=sharedReadFailed?'Состояние обмена недоступно':!value?'Проверяем подключение…':!c.enabled?'Только просмотр · двусторонний обмен выключен':value.failure?sharedError(value.failure.code):!value.lastSuccess?'Обмен ещё не подтверждён':`Обмен: ${when(value.lastSuccess)} · ${c.transport==='pipe'?'локальный канал':'API'}`;
 if(c?.enabled&&value.lastSuccess&&!value.failure&&Date.now()-Date.parse(value.lastSuccess)>c.staleAfterSeconds*1000)message+=' · данные могут устареть';
 root.append(el('span','',message,true));
 const button=sharedButton(c?.enabled?'Настройки обмена':'Подключить обмен',openTaskConnection);button.className='text-button';root.append(button);
}
function sharedField(parent,label,value='',multiline=false){const l=el('label','',label,true),i=document.createElement(multiline?'textarea':'input');i.value=value;i.maxLength=multiline?8000:4096;const field={'Название':'title','Описание':'content','Этап (ID)':'stage','Процесс (ID)':'process','Комментарий / отзыв':'comment'}[label];if(field)i.dataset.draftField=field;l.append(i);parent.append(l);return i;}
async function sharedAction(fn){if(sharedBusy)return;sharedBusy=true;try{await fn();}catch(e){toast(sharedError(e.message));}finally{sharedBusy=false;await loadSharedTasks();}}
function appendSharedTaskRows(){
 renderTaskExchangeStatus();const list=$('dashboard-tasks');if(!sharedState)return;
 let toolbar=$('shared-task-toolbar');if(!toolbar){toolbar=el('div','connection-actions');toolbar.id='shared-task-toolbar';list.before(toolbar);}
 toolbar.replaceChildren();
 if(sharedState.config.enabled)toolbar.append(sharedButton('Добавить общую задачу',()=>openSharedTask(null),!sharedState.config.scopes.includes('tasks:write')),sharedButton('Обновить общие задачи',()=>sharedAction(()=>request('/api/task-sync/exchange',{}))));
 for(const [op,draft] of Object.entries(JSON.parse(localStorage.getItem('agent-city-shared-unsent-v1')||'{}'))){const detail=el('section','shared-pending');detail.append(el('h3','','Черновик: ответ на отправку не получен'),el('pre','',JSON.stringify(draft.arguments,null,2),true),sharedButton('Повторить ту же отправку',()=>sharedAction(()=>sendLocalSharedDraft(op))));toolbar.append(detail);}
 const query=$('dashboard-search').value.trim().toLowerCase(),filter=$('dashboard-filter').value;
 let count=0;
 for(const task of Object.values(sharedState.tasks)){
  if((dashboardMode==='history')!==!!task.completed||!`${task.title} ${task.stage||''} ${task.id} ${task.binding.sourceId} ${task.binding.taskKey}`.toLowerCase().includes(query))continue;
  const status=sharedReport(sharedRun(task))?.status;
  const awaitingReview=['awaiting_dispatch','awaiting_review'].includes(task.review?.state),fresh=sharedRunFresh(sharedRun(task));
  const matches=filter==='all'||filter==='current'&&(task.humanTimerActive||['running','waiting'].includes(status)&&fresh||awaitingReview)||filter==='working'&&status==='running'&&fresh||filter==='waiting'&&(status==='waiting'&&fresh||awaitingReview)||filter==='paused'&&task.humanTimerPaused===true;
  if(dashboardMode!=='history'&&!matches)continue;
  const {row,main}=taskWidgetRow(task.title,{taskKey:task.binding.taskKey,onOpen:()=>openSharedTask(task.id),status:task.completed?(task.review?.state==='accepted'?'Результат принят':'Задача завершена'):sharedExecution(task),tone:task.review?.state==='awaiting_review'?'review':task.completed?'accepted':'neutral'});row.dataset.sharedTaskId=task.id;
  const run=sharedReport(sharedRun(task));if(task.stage)main.append(el('p','task-stage',task.stage,true));
  const meta=[run?.agent||'Исполнитель неизвестен',run?.model||'Модель неизвестна'];
  if(run?.receivedAt)meta.push(`Отчёт: ${when(run.receivedAt)}`);
  if(task.humanTimerActive)meta.push('Твой таймер идёт');
  if(task.freshness!=='fresh')meta.push(task.freshness==='stale'?'Данные могут устареть':'Свежесть данных неизвестна');
  main.append(el('p','task-meta',meta.join(' · '),true));
  list.append(row);count++;
 }
 for(const [op,item] of Object.entries(sharedState.outbox)){
  const row=el('article','dashboard-task shared-pending');row.append(el('strong','',item.state==='pending'?'Изменение ожидает отправки':item.state==='conflict'?'Конфликт изменений':'Изменение отклонено'),el('p','',`${item.request.command} · ${item.request.arguments.taskId||'новая задача'} · ${op}`,true));
  const detail=el('section','pending-comparison'),before=el('pre','');detail.append(el('h3','','Сохранённый черновик и текущая версия'));before.textContent=JSON.stringify({draft:item.request.arguments,current:item.conflict?.current},null,2);detail.append(before);row.append(detail);
  if(item.conflict)row.append(el('p','',sharedError(item.conflict.code),true));
  if(item.state!=='pending')row.append(sharedButton('Убрать из очереди, сохранить в истории',()=>sharedAction(()=>request('/api/task-sync/resolve',{operationId:op,revision:sharedState.revision}))));
  list.append(row);count++;
 }
 if(count)$('dashboard-empty').hidden=true;
}
async function queueShared(command,args){
 const key='agent-city-shared-unsent-v1',drafts=JSON.parse(localStorage.getItem(key)||'{}');
 const ns=sharedState.config.sourceNamespace,signature=JSON.stringify({command,arguments:args,sourceNamespace:ns});
 const existing=Object.entries(drafts).find(([,v])=>JSON.stringify({command:v.command,arguments:v.arguments,sourceNamespace:v.sourceNamespace})===signature);
 const op=existing?.[0]||'ui-'+crypto.randomUUID();
 drafts[op]={version:1,operationId:op,command,arguments:args,sourceNamespace:ns,connectionIdentity:sharedConnectionIdentity()};
 // Persist before transmission, including the operation ID for an unknown response outcome.
 localStorage.setItem(key,JSON.stringify(drafts));
 await sendLocalSharedDraft(op);
}
async function sendLocalSharedDraft(op){
 const key='agent-city-shared-unsent-v1',drafts=JSON.parse(localStorage.getItem(key)||'{}'),draft=drafts[op];
 if(!draft)throw Error('local_draft_missing');
 if(draft.connectionIdentity!==sharedConnectionIdentity()||draft.sourceNamespace!==null&&draft.sourceNamespace!==sharedState.config.sourceNamespace)throw Error('task_namespace_changed');
 const {sourceNamespace,connectionIdentity,...requestBody}=draft;await request('/api/task-sync/queue',requestBody);
 delete drafts[op];localStorage.setItem(key,JSON.stringify(drafts));
 await request('/api/task-sync/exchange',{});await loadSharedTasks();return op;
}
function sharedConnectionIdentity(){const c=sharedState.config;return JSON.stringify([c.transport,c.endpoint,c.profile,c.client]);}
function openSharedTask(id){
 const task=id?sharedState.tasks[id]:null;
 let dialog=$('shared-task-dialog');if(!dialog){dialog=el('dialog','');dialog.id='shared-task-dialog';dialog.setAttribute('aria-label','Общая задача');document.body.append(dialog);}
 dialog.replaceChildren();dialog.append(el('h2','',task?'Общая задача':'Новая общая задача'));
 const close=sharedButton('Закрыть',()=>dialog.close());dialog.append(close);
 const title=sharedField(dialog,'Название',task?.title||''),content=sharedField(dialog,'Описание',task?.content||'',true);
 if(!task){dialog.append(sharedButton('Создать в Cicada',()=>sharedAction(async()=>{await queueShared('create',{title:title.value,content:content.value});dialog.close();}),!sharedState.config.scopes.includes('tasks:write')));dialog.showModal();return;}
 dialog.append(el('code','source-path',`${task.id} · ${task.binding.taskKey} · версия ${task.version}`,true),el('p','',sharedExecution(task),true));
 const stage=sharedField(dialog,'Этап (ID)',task.stage||''),process=sharedField(dialog,'Процесс (ID)',task.process||'');
 const versioned=extra=>({taskId:task.id,expectedVersion:task.version,...extra});
 dialog.append(sharedButton('Сохранить изменения',()=>sharedAction(async()=>{await queueShared('patch',versioned({patch:{title:title.value,content:content.value,stage:stage.value,process:process.value}}));dialog.close();}),!sharedState.config.scopes.includes('tasks:write')));
 if(!task.review)dialog.append(sharedButton(task.completed?'Вернуть в текущие':'Завершить задачу',()=>sharedAction(async()=>{await queueShared('patch',versioned({patch:{status:task.completed?'task':'done'}}));dialog.close();}),!sharedState.config.scopes.includes('tasks:write')));
 const feedback=sharedField(dialog,'Комментарий / отзыв', '',true);
 dialog.append(sharedButton('Добавить комментарий',()=>sharedAction(async()=>{await queueShared('comment',versioned({comment:feedback.value}));dialog.close();}),!sharedState.config.scopes.includes('tasks:write')));
 if(task.review?.state==='awaiting_review'){
  dialog.append(el('h3','','Результат на проверке'),el('pre','',task.results.find(r=>r.version===task.review.resultVersion)?.content||'',true));
  for(const [decision,label] of [['accept','Принять в историю'],['rework','Запросить доработку']])dialog.append(sharedButton(label,()=>sharedAction(async()=>{await queueShared('review',versioned({resultVersion:task.review.resultVersion,decision,...(decision==='rework'?{comment:feedback.value}:{})}));dialog.close();}),!sharedState.config.scopes.includes('tasks:review')));
 }
 const history=el('section','shared-task-history');history.append(el('h3','','Результаты, этапы и история'));
 const entry=(heading,text,meta)=>{const row=el('article','shared-history-entry');row.append(el('h4','',heading,true));if(text)row.append(el('pre','',text,true));if(meta)row.append(el('p','task-meta',meta,true));history.append(row);};
 for(const result of task.results)if(!(task.review?.state==='awaiting_review'&&result.version===task.review.resultVersion))entry(t('Результат {version}',{version:result.version}),result.content);
 const actions={accept:'Принято',rework:'Запрошена доработка',submit_result:'Передано на проверку',publish:'Передано на проверку',acknowledge:'Исполнитель подтвердил доработку'};
 for(const event of task.history)entry(t(actions[event.action]||event.action),event.comment,t('Результат {version}',{version:event.resultVersion}));
 for(const comment of task.comments)entry(t('Комментарий'),comment.content,comment.at?when(comment.at):'');
 for(const intent of task.intents)entry(t(intent.state==='awaiting_dispatch'?'Доработка ожидает исполнителя':'Запрос на доработку'),intent.comment,t('Результат {version}',{version:intent.resultVersion}));
 for(const event of task.stageHistory||[])entry(t('Этап'),event.stage,event.at?when(event.at):'');
 if(history.children.length>1)dialog.append(history);dialog.showModal();
}
async function renderTaskConnection(){
 let root=$('task-connection');if(!root){root=el('section','settings-group');root.id='task-connection';$('connector-settings').after(root);}
 try{
  const current=await request('/api/task-sync');sharedState=current;const c=current.config;root.replaceChildren();
  root.append(el('h3','','Общие задачи Cicada ↔ Agent City'),el('p','','Здесь сохраняются только явно подключённые личные задачи. Изменения отправляются в фоне; таймер пользователя остаётся в Cicada.'));
  const enabled=document.createElement('input');enabled.type='checkbox';enabled.checked=c.enabled;const label=el('label','','Включить обмен');label.prepend(enabled);root.append(label);
  const transport=document.createElement('select');transport.append(new Option('Локальный канал текущего пользователя','pipe'),new Option('API по адресу','http'));transport.value=c.transport;const tl=el('label','','Подключение');tl.append(transport);root.append(tl);
  const endpoint=sharedField(root,'Адрес API',c.endpoint),profile=sharedField(root,'Профиль данных Cicada (полный путь)',c.profile),client=sharedField(root,'Клиент локального канала (полный путь)',c.client),token=sharedField(root,'Имя переменной окружения с секретом',c.tokenEnv);
  root.append(el('p','','Локальный канал проверяет учётную запись ОС. Для API используется Bearer-секрет сервиса; значение секрета в форму не вводится.'));
  const refreshFields=()=>{endpoint.parentElement.hidden=token.parentElement.hidden=transport.value==='pipe';profile.parentElement.hidden=client.parentElement.hidden=transport.value!=='pipe';};transport.addEventListener('change',refreshFields);refreshFields();
  const scopes=[];for(const [value,name] of [['tasks:read','Чтение'],['tasks:write','Изменения'],['tasks:review','Принятие и доработка'],['tasks:execute','Отчёты исполнения']]){const l=el('label','',name),input=document.createElement('input');input.type='checkbox';input.checked=c.scopes.includes(value);input.disabled=value==='tasks:read';l.prepend(input);root.append(l);scopes.push([value,input]);}
  const ids=sharedField(root,'Разрешённые ID задач через запятую (пусто — все подключённые личные задачи)',(c.taskIds||[]).join(','));
  root.append(el('p','source-path',`Источник: ${c.sourceNamespace||'будет проверен при первом обмене'}`,true),el('p','',`Последний успешный обмен: ${current.lastSuccess?when(current.lastSuccess):'ещё не было'}`,true));
  const status=el('p','',current.failure?sharedError(current.failure.code):'Ошибок последнего обмена нет',true);status.setAttribute('role','status');root.append(status);
  const save=async()=>{const config={...c,enabled:enabled.checked,transport:transport.value,endpoint:transport.value==='http'?endpoint.value.trim():'',profile:transport.value==='pipe'?profile.value.trim():'',client:transport.value==='pipe'?client.value.trim():'',tokenEnv:transport.value==='http'?token.value.trim():'',scopes:scopes.filter(([,input])=>input.checked).map(([value])=>value),taskIds:ids.value.trim()?ids.value.split(',').map(s=>s.trim()).filter(Boolean):null};await request('/api/task-sync/configure',{config,revision:current.revision});};
  root.append(sharedButton('Сохранить подключение',()=>sharedAction(async()=>{await save();await renderTaskConnection();})),sharedButton('Сохранить и проверить обмен',()=>sharedAction(async()=>{enabled.checked=true;await save();await request('/api/task-sync/exchange',{});await renderTaskConnection();})));
 }catch(e){root.replaceChildren(el('p','',sharedError(e.message),true));}
}
