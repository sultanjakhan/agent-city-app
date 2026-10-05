'use strict';
// Existing dashboard and native task identities; pending edits never become confirmed tasks.
let sharedState=null,sharedLoading=false,sharedBusy=false,sharedReadFailed=false;
const sharedText={task_connection_unavailable:'Приложение или канал недоступны. Проверь адрес и запусти фоновый канал.',task_authentication_missing:'В процессе приложения нет указанного секрета. Настрой переменную окружения и перезапусти фоновый сервис.',task_authentication_rejected:'Секрет не принят. Проверь учётные данные сервиса.',task_scope_denied:'Недостаточно прав для этой команды. Проверь области доступа и список ID.',task_namespace_changed:'Подключён другой источник. Верни прежний профиль или создай отдельный профиль данных.',task_source_change_requires_separate_profile:'Есть сохранённые задачи или черновики. Для другого источника используй отдельный профиль данных.',revision_conflict:'Задача изменена в другом приложении. Сравни версии и отправь новый черновик.',task_settings_conflict:'Настройки изменились. Обнови страницу и повтори.',human_timer_active:'Сначала останови свой таймер в Cicada.',review_controls_status:'Для результата используй принятие или доработку.',task_exchange_failed:'Обмен не завершён. Проверь настройки и повтори; черновики сохранены.'};
Object.assign(sharedText,{task_version_conflict:'Задача изменена в другом приложении. Сравни версии и отправь новый черновик.',execution_run_mismatch:'Эту доработку подтвердил другой запуск. Его работа не изменена; твой черновик сохранён.',operation_capacity:'Журнал операций Cicada заполнен. Обнови Cicada и повтори сохранённую отправку.',invalid_shared_text:'Текст слишком длинный или содержит неподдерживаемые символы. Исправь текст; прежняя отправка сохранена.'});
function sharedError(code){return sharedText[code]||`Обмен не выполнен (${code||'нет данных'}). Проверь настройки подключения.`;}
function isSharedTask(key,sourceId=null,sourceNamespace=null){return Object.values(sharedState?.tasks||{}).some(t=>t.binding.taskKey===key||sourceId&&sourceNamespace&&t.binding.sourceId===sourceId&&t.binding.sourceNamespace===sourceNamespace);}
function sharedRun(task){return [...(task.reports||[])].sort((a,b)=>(Date.parse(b.receivedAt)||0)-(Date.parse(a.receivedAt)||0)||(b.receivedOrder||0)-(a.receivedOrder||0))[0]||null;}
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
 try{sharedState=await request('/api/task-sync');sharedReadFailed=false;renderDashboardRows();}
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
function sharedField(parent,label,value='',multiline=false){const l=el('label','',t(label),true),i=document.createElement(multiline?'textarea':'input');l.dataset.fieldLabel=label;i.value=value;i.maxLength=multiline?8000:4096;const field={'Название':'title','Описание':'content','Этап (ID)':'stage','Процесс (ID)':'process','Комментарий / отзыв':'comment'}[label];if(field)i.dataset.draftField=field;l.append(i);parent.append(l);return i;}
async function sharedAction(fn){if(sharedBusy)return;sharedBusy=true;try{await fn();}catch(e){toast(sharedError(e.message));}finally{sharedBusy=false;await loadSharedTasks();}}
function appendSharedTaskRows(){renderDashboardRows();}
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
 document.dispatchEvent(new CustomEvent('agentcity-task-command-queued',{detail:requestBody}));
 delete drafts[op];localStorage.setItem(key,JSON.stringify(drafts));
 await request('/api/task-sync/exchange',{});await loadSharedTasks();return op;
}
function sharedConnectionIdentity(){const c=sharedState.config;return JSON.stringify([c.transport,c.endpoint,c.profile,c.client]);}
function openSharedTask(id){window.AgentCityTasks?.openShared(id);}
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
