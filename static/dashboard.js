'use strict';
let dashboardData=null,dashboardLoading=false,dashboardTimer=null;
let connectorData=null,connectorLoading=false,connectorSaving=false;
const dashboardParams=new URLSearchParams(location.search);
let dashboardLinkPending=dashboardParams.get('task');
const runStatuses={running:'Работает',waiting:'Ожидает',done:'Завершено',error:'Ошибка',cancelled:'Отменено'};

// Cicada Home v2 task-widget presentation, adapted to real City data/actions.
// One renderer for observed native tasks, shared tasks and preserved history.
function taskWidgetRow(title,{taskKey,onOpen,status,tone='neutral'}={}){
 const row=el('article','dashboard-task task-widget-row'),icon=el('span','task-widget-icon'),main=el('div','task-widget-main'),heading=el('div','dashboard-task-heading'),button=el('button','model-title task-widget-title',title,true);
 icon.setAttribute('aria-hidden','true');icon.innerHTML='<svg viewBox="0 0 24 24"><path d="m12 3 2.7 6.3L21 12l-6.3 2.7L12 21l-2.7-6.3L3 12l6.3-2.7Z"/></svg>';
 button.type='button';if(taskKey)button.dataset.taskKey=taskKey;button.addEventListener('click',onOpen);heading.append(button);main.append(heading);
 const badge=el('span','status task-widget-status '+tone,status,true),open=el('button','task-widget-open');open.type='button';open.setAttribute('aria-label',t('Открыть задачу: {title}',{title}));open.title=t('Открыть задачу');
 open.innerHTML='<svg viewBox="0 0 24 24" aria-hidden="true"><path d="m9 6 6 6-6 6"/></svg>';open.addEventListener('click',onOpen);
 row.append(icon,main,badge,open);return {row,main};
}
function refreshTaskWidgetCount(){
 const count=$('dashboard-tasks').querySelectorAll('.task-widget-row').length;
 $('task-widget-count').textContent=t('Показано: {count}',{count});
}

function reportedSkills(run){const names=new Map((run.skills||[]).map(s=>[s.id,s.name]));return [...new Set(run.skillIds??[...names.keys()])].map(id=>({id,name:names.get(id)||id}));}
// Totals are latest cumulative counters per executor, never a sum of snapshots.
// Legacy runs spanning multiple stages have no defensible per-stage allocation.
function aggregateRuns(input){
 const latest=new Map();
 for(const run of input){const key=JSON.stringify([run.originDevice||'local',run.runId]),old=latest.get(key);if(!old||(run.sequence||0)>(old.sequence||0))latest.set(key,run);}
 const runs=[...latest.values()],count=(rows,key)=>({value:rows.reduce((sum,r)=>sum+(Number.isSafeInteger(r[key])&&r[key]>=0?r[key]:0),0),known:rows.filter(r=>Number.isSafeInteger(r[key])&&r[key]>=0).length,total:rows.length});
 function totals(rows){
  const calls=new Map();let mcpKnown=0;
  for(const run of rows){if(!Array.isArray(run.mcpCalls))continue;mcpKnown++;for(const call of run.mcpCalls){const key=JSON.stringify([call.server,call.tool]),old=calls.get(key);calls.set(key,{...call,calls:(old?.calls||0)+call.calls});}}
  const skills=new Map();for(const run of rows)for(const skill of reportedSkills(run))skills.set(skill.id,skill.name);
  return {count:rows.length,input:count(rows,'inputTokens'),output:count(rows,'outputTokens'),models:[...new Set(rows.map(r=>r.model).filter(Boolean))],skills:[...new Set(skills.values())],mcp:{calls:[...calls.values()],known:mcpKnown,total:rows.length},statuses:rows.reduce((out,r)=>(out[r.status]=(out[r.status]||0)+1,out),{})};
 }
 const groups=new Map(),unallocated=[];
 for(const run of runs){
  const history=run.history||[],stages=new Set([...history.map(e=>e.stage??''),run.stage??'']);
  const truncated=history.length>=30;
  if(stages.size!==1||truncated){unallocated.push(run);continue;}
  const key=run.stage||'';if(!groups.has(key))groups.set(key,[]);groups.get(key).push(run);
 }
 const stages=[...groups].map(([stage,rows])=>({stage,runs:rows,totals:totals(rows),startedAt:rows.map(r=>r.firstReportedAt||r.updatedAt||'').sort()[0]})).sort((a,b)=>a.startedAt.localeCompare(b.startedAt));
 return {runs,overall:totals(runs),stages,unallocated};
}
function reportedTotal(metric){return !metric.known?'—':metric.known===metric.total?String(metric.value):t('Учтено: {value}',{value:metric.value});}
function totalsTokens(total){return t('Вход: {input} · Выход: {output}',{input:reportedTotal(total.input),output:reportedTotal(total.output)});}
function totalsMcp(total){const metric=total.mcp,known=metric.calls.map(c=>`${c.server} / ${c.tool} × ${c.calls}`).join(', ')||t('Вызовов не было');return !metric.known?t('Нет данных'):known+(metric.known<metric.total?' · '+t('Часть вызовов неизвестна'):'');}
function formatCount(value){return new Intl.NumberFormat(typeof I18n==='undefined'?'ru-RU':I18n.locale).format(value);}
function tokenSummary(total){return {value:total.input.value+total.output.value,known:total.input.known+total.output.known>0,complete:total.count>0&&total.input.known===total.count&&total.output.known===total.count};}
function compactTokens(total){const usage=tokenSummary(total);return usage.known?t(usage.complete?'{value} ток.':'Учтено {value} ток.',{value:formatCount(usage.value)}):'—';}
function reportedCoverage(total){return total.runs.filter(r=>Number.isSafeInteger(r.inputTokens)&&Number.isSafeInteger(r.outputTokens)).length;}
function taskTime(task){
 // Cicada reports accumulated, stopped task blocks. Never infer task time from report arrival.
 const minutes=task.actualMinutes;
 return {known:Number.isSafeInteger(minutes)&&minutes>=0,minutes,active:task.isActive===true};
}
function formatMinutes(minutes){return minutes>=60?t('{hours} ч {minutes} мин',{hours:Math.floor(minutes/60),minutes:minutes%60}):t('{minutes} мин',{minutes});}
function stageResources(total){
 const row=el('span','stage-resources'),skills=el('span','stage-skills'),mcp=el('span','stage-mcp');
 const skillText=total.skills.length?total.skills.slice(0,2).join(', ')+(total.skills.length>2?' · '+t('ещё {count}',{count:total.skills.length-2}):''):'—';
 skills.append(el('span','resource-label',t('Навыки')+': ',true),document.createTextNode(skillText));skills.title=total.skills.join(', ')||t('Навыки не сообщены');
 const calls=total.mcp.calls.filter(c=>c.calls>0),known=total.mcp.known>0,partial=known&&total.mcp.known<total.mcp.total;
 const callNames=calls.map(c=>(calls.filter(x=>x.tool===c.tool).length>1?c.server+'/'+c.tool:c.tool)+' × '+c.calls);
 const mcpText=!known?'—':callNames.slice(0,2).join(', ')+(callNames.length>2?' · '+t('ещё {count}',{count:callNames.length-2}):'')||(partial?'—':'0');
 mcp.append(el('span','resource-label','MCP: ',true),document.createTextNode(mcpText+(partial?' · '+t('частично'):'')));mcp.title=totalsMcp(total);
 row.append(skills,mcp);return row;
}
function taskFacts(task,runs){const total=aggregateRuns(runs).overall,time=taskTime(task);return [tokenSummary(total).known?compactTokens(total):null,time.known?t('Время: {value}',{value:formatMinutes(time.minutes)}):null,total.models.length?t('Моделей: {count}',{count:total.models.length}):null].filter(Boolean).join(' · ');}
function groupState(rows){
 const errors=rows.filter(r=>r.status==='error').length;
 if(errors){if(rows.length===1)return {tone:'error',label:'Ошибка'};const active=rows.some(r=>r.status==='running'&&freshRun(r));return {tone:active?'running':'error',label:t(active?'Работает · ошибок: {count}':'Неудачных попыток: {count}',{count:errors})};}
 if(rows.some(r=>r.status==='running'&&freshRun(r)))return {tone:'running',label:'Работает'};
 if(rows.some(r=>['running','waiting'].includes(r.status)&&!freshRun(r)))return {tone:'waiting',label:'Нет свежего отчёта'};
 if(rows.some(r=>r.status==='waiting'))return {tone:'waiting',label:'Ожидает'};
 return rows.every(r=>r.status==='done')?{tone:'done',label:'Завершено'}:{tone:'neutral',label:'Отменено'};
}
function metricCell(label,value,note){const cell=el('div','report-total');cell.append(el('dt','',label),el('dd','report-total-value',value,true));if(note)cell.append(el('dd','report-total-note',note,true));return cell;}
function drawTaskReport(task,runs){
 const report=aggregateRuns(runs),section=el('section','task-report'),overall=report.overall,usage=tokenSummary(overall),time=taskTime(task),totals=el('dl','report-totals');
 const coverage=usage.complete?t('Вход + выход'):usage.known?t('Расход передан: {known} из {total} попыток',{known:reportedCoverage(report),total:overall.count}):t('Расход токенов не передан');
 totals.append(metricCell(usage.complete?'Всего токенов':'Учтено токенов',usage.known?formatCount(usage.value):'—',coverage),metricCell('Время в Cicada',time.known?formatMinutes(time.minutes):'—',t(time.known?(time.active?'Без текущего активного отрезка':'Сохранённое время задачи'):'Таймер задачи не передан')));
 section.append(totals);
 if(!runs.length){section.append(el('p','report-hint','Отчётов исполнителей пока нет.'));return section;}
 const heading=el('div','report-section-heading');heading.append(el('h3','','Этапы исполнения'),el('span','',t('Попыток: {count}',{count:overall.count}),true));section.append(heading);
 for(const stage of report.stages){
  const detail=el('section','stage-report'),summary=el('header','stage-report-heading'),state=groupState(stage.runs),main=el('span','stage-main'),end=el('span','stage-end');
  const dot=el('span','stage-dot '+state.tone);dot.setAttribute('aria-hidden','true');
  main.append(el('strong','',stage.stage||t('Этап не сообщён'),true),el('span','stage-report-models',stage.totals.models.join(', ')||[...new Set(stage.runs.map(r=>r.agent))].join(', '),true));
  const known=tokenSummary(stage.totals).known,tokens=el('span','stage-report-tokens'+(known?'':' missing'),known?compactTokens(stage.totals):t('Нет счётчика'),true);if(!known){tokens.title=t('Расход токенов не передан');tokens.setAttribute('aria-label',t('Расход токенов не передан'));}
  end.append(tokens,el('span','stage-report-state '+state.tone,state.label));
  summary.append(dot,main,end,stageResources(stage.totals));detail.append(summary,...stage.runs.map(run=>drawRun(run,{inline:stage.runs.length===1})));section.append(detail);
 }
 if(report.unallocated.length){
  const detail=el('section','report-section unallocated-runs');detail.append(el('h3','',t('Ещё отчёты без этапов: {count}',{count:report.unallocated.length}),true),el('p','report-hint','Расход по этапам не определён: этап менялся или история запуска ограничена. Общие счётчики учтены один раз.'),...report.unallocated.map(drawRun));section.append(detail);
 }
 const info=el('section','report-section report-measurements');info.append(el('h3','','Данные и источники'));
 info.append(el('p','report-hint',t('Запусков: {count}',{count:overall.count})+' · '+Object.entries(overall.statuses).map(([status,count])=>t(runStatuses[status]||'Нет данных')+': '+count).join(' · '),true));
 const metrics=el('dl','run-metrics');
 for(const [label,value] of [['Токены',totalsTokens(overall)],['Модели',overall.models.join(', ')||t('Не передано')],['Навыки',overall.skills.join(', ')||t('Не передано')],['MCP',totalsMcp(overall)]])metrics.append(el('dt','',label),el('dd','',value,true));
 info.append(metrics,el('p','report-hint','Итог объединяет этапы. Токены — по отчётам, время — по таймеру Cicada. Прочерк означает отсутствие данных.'));
 section.append(info);
 return section;
}
function taskReportText(task,runs){
 const report=aggregateRuns(runs),usage=tokenSummary(report.overall),time=taskTime(task),out=[task.title,'',t('Общий итог'),t(usage.complete?'Всего токенов':'Учтено токенов')+': '+(usage.known?formatCount(usage.value):'—'),t('Время в Cicada')+': '+(time.known?formatMinutes(time.minutes):t('Не передано')),t(time.active?'Без текущего активного отрезка':'Сохранённое время задачи'),t('Запусков: {count}',{count:report.overall.count})+' · '+Object.entries(report.overall.statuses).map(([status,count])=>t(runStatuses[status]||'Нет данных')+': '+count).join(' · '),totalsTokens(report.overall),t('Модели')+': '+(report.overall.models.join(', ')||t('Модель не сообщена')),'MCP: '+totalsMcp(report.overall),t('Навыки')+': '+(report.overall.skills.join(', ')||t('Нет данных'))];
 const line=run=>`- ${run.agent} · ${modelText(run)} · ${runState(run)} · ${tokenText(run)} · MCP: ${mcpText(run)} · ${t('Навыки')}: ${reportedSkills(run).map(s=>s.name).join(', ')||t('Нет данных')}`+(run.status==='error'?' · '+t('Ошибка исполнителя. Причина не сообщена в отчёте.'):'');
 for(const stage of report.stages){out.push('',stage.stage||t('Этап не сообщён'),totalsTokens(stage.totals),t('Навыки')+': '+(stage.totals.skills.join(', ')||t('Нет данных')),'MCP: '+totalsMcp(stage.totals),...stage.runs.map(line));}
 if(report.unallocated.length){out.push('',t('Без распределения по этапам'),...report.unallocated.map(line),t('Расход по этапам не определён: этап менялся или история запуска ограничена. Общие счётчики учтены один раз.'));}
 out.push('',t('Расширения: отдельные события использования пока не передаются. Установленные расширения не считаются использованными.'));return out.join('\n');
}

async function loadDashboard(force=false){
 if(dashboardLoading)return;
 if(dashboardData&&!force){renderDashboardRows();scheduleDashboard();return;}
 dashboardLoading=true;
 try{dashboardData=await request('/api/dashboard');renderDashboardRows();if(typeof updateWorkRegistrySnapshot==='function')updateWorkRegistrySnapshot(dashboardData.workRegistry);if(typeof loadSharedTasks==='function')await loadSharedTasks();}
 catch(e){const error=$('dashboard-error');if(error){error.hidden=false;error.textContent=t(e.message);}window.AgentCityTasks?.render();}
 finally{dashboardLoading=false;scheduleDashboard();}
}
function scheduleDashboard(){if(dashboardTimer)return;if(['dashboard','tasks'].includes(view))dashboardTimer=setTimeout(()=>{dashboardTimer=null;if(['dashboard','tasks'].includes(view))loadDashboard(true);},5000);}
function renderDashboard(){loadDashboard();}
function taskRuns(task){return task._runs||(dashboardData?.runs||[]).filter(r=>(task.runTaskKeys||[task.taskKey]).includes(r.taskKey));}
function freshRun(run){return ['running','waiting'].includes(run.status)&&(run._sharedReport?sharedRunFresh(run):Date.parse(run.updatedAt)<=Date.now()+30000&&age(run.updatedAt)<=300);}
function mcpText(run){return run.mcpCalls===null||run.mcpCalls===undefined?t('Нет данных'):run.mcpCalls.length?run.mcpCalls.map(c=>`${c.server} / ${c.tool} × ${c.calls}`).join(', '):t('Вызовов не было');}
function runState(run){return t(runStatuses[run.status]||'Нет данных')+(['running','waiting'].includes(run.status)&&!freshRun(run)?' · '+t('Нет свежего отчёта'):'');}
function stageName(task){return task.stageLabel||task.stage||t('Этап не задан');}
function tokenText(run){return t('Вход: {input} · Выход: {output}',{input:run.inputTokens??'—',output:run.outputTokens??'—'});}
function modelText(run){return run.model?`${run.provider?run.provider+' · ':''}${run.model}`:t('Модель не сообщена');}
function drawRun(run,{inline=false}={}){
 const row=el('article','run-row'+(inline?' single-attempt':'')),head=el('header','run-heading'),main=el('span','attempt-main'),state=groupState([run]);
 main.append(el('strong','',run.model||run.agent,true),el('span','attempt-subtitle',[run.agent,run.stage].filter(Boolean).join(' · '),true));
 head.append(main,el('span','attempt-state '+state.tone,runState(run),true));
 if(!inline)row.append(head);
 if(run.provider||!inline)row.append(el('p','attempt-provider',modelText(run),true));
 if(run.status==='error')row.append(el('p','report-hint','Ошибка исполнителя. Причина не сообщена в отчёте.'));
 if(run.originDevice)row.append(el('p','source-path',t('Источник: {device}',{device:run.originDevice}),true));
 const metrics=el('dl','run-metrics');
 for(const [name,value] of [['Токены',tokenText(run)],['Навыки',reportedSkills(run).map(s=>s.name).join(', ')||t('Нет данных')],['MCP',mcpText(run)],['Последний отчёт',when(run.updatedAt)]])metrics.append(el('dt','',name),el('dd','',value,true));
 row.append(metrics);
 if(run.history?.length>1){const history=el('section','attempt-events'),list=el('ol','run-history');history.append(el('h4','','События агента'));for(const entry of run.history)list.append(el('li','',`${entry.stage||'—'} · ${t(runStatuses[entry.status]||'Нет данных')} · ${when(entry.reportedAt)}${entry.inputTokens!==undefined?' · '+tokenText(entry):''}${entry.mcpCalls?.length?' · MCP: '+mcpText(entry):''}${entry.skillIds?.length?' · '+t('Навыки')+': '+entry.skillIds.map(id=>run.skills?.find(s=>s.id===id)?.name||id).join(', '):''}`,true));history.append(list);row.append(history);}
 return row;
}
function renderDashboardRows(){
 const list=$('dashboard-tasks');if(!list)return;
 const data=dashboardData?.cicada,source=data?.source,error=$('dashboard-error');
 if($('dashboard-source'))$('dashboard-source').textContent=source?t('{name} · прочитано {date}',{name:source.label,date:when(data.readAt)}):t('Cicada не подключена');
 const unavailable=data&&(data.status==='error'||data.availableStatus&&data.availableStatus!=='connected'&&data.status==='connected');
 if(error){error.hidden=!unavailable;if(unavailable)error.textContent=t(data.availableStatus==='source_changed'?'Источник изменился во время чтения. Обнови задачи.':data.error||'Не удалось прочитать Cicada. Проверь источник в настройках.');}
 const focused=document.activeElement?.dataset.taskKey;list.replaceChildren();
 const records=window.AgentCityTasks?.records().filter(record=>record.current&&!record.completed&&!record.missingSource)||[];
 for(const record of records)list.append(window.AgentCityTasks.row(record));
 if(focused)[...list.querySelectorAll('button')].find(b=>b.dataset.taskKey===focused)?.focus({preventScroll:true});
 if($('dashboard-empty')){$('dashboard-empty').hidden=!!records.length;$('dashboard-empty').textContent=t(data?.status==='disconnected'?'Выбери источник задач в настройках.':unavailable?'Данные задач недоступны.':'Сейчас ничего не запущено.');}
 refreshTaskWidgetCount();window.AgentCityTasks?.render();
 if(dashboardLinkPending&&window.AgentCityTasks?.find(dashboardLinkPending)){const key=dashboardLinkPending;dashboardLinkPending=null;window.AgentCityTasks.open(key);}
}
function openDashboardTask(key){window.AgentCityTasks?.open(key);}
function renderDashboardTask(){window.AgentCityTasks?.render();}
function taskKeyFromSearch(value){
 const text=value.trim();if(/^(cicada-|run:|registry:)[A-Za-z0-9_.:-]+$/.test(text))return text;
 try{const url=new URL(text);return ['http:','https:'].includes(url.protocol)&&url.searchParams.get('task')||null;}catch{return null;}
}

async function renderConnectors(){
 loadCloud();
 if(connectorLoading||connectorSaving)return;
 if(!connectorData){connectorLoading=true;try{connectorData=await request('/api/connectors');}catch(e){$('cicada-source-message').textContent=t(e.message);}finally{connectorLoading=false;}}
 if(!connectorData)return;
 const select=$('cicada-source'),draft=select.dataset.loaded?select.value:connectorData.selectedId||'';
 select.replaceChildren(new Option(t('Не подключено'),''),...connectorData.candidates.map(c=>new Option(c.label,c.id)));select.value=draft;select.dataset.loaded='true';showConnectorPath();
}
function showConnectorPath(){const selected=connectorData?.candidates.find(c=>c.id===$('cicada-source').value);$('cicada-source-path').textContent=selected?.path||'';}
$('cicada-source').addEventListener('change',showConnectorPath);
$('save-cicada-source').addEventListener('click',async()=>{
 if(!connectorData||connectorSaving)return;connectorSaving=true;$('save-cicada-source').disabled=true;$('cicada-source').disabled=true;
 try{connectorData=await request('/api/connectors/cicada',{sourceId:$('cicada-source').value||null,revision:connectorData.revision});dashboardData=null;$('cicada-source-message').textContent=t('Источник сохранён. Задачи появятся на дашборде.');}
 catch(e){$('cicada-source-message').textContent=t(e.message);connectorData=null;}finally{connectorSaving=false;$('save-cicada-source').disabled=false;$('cicada-source').disabled=false;}
});

let cloudLoading=false,cloudTimer=null;
function cloudError(code){
 if(code==='unauthorized')return t('Ключ устройства отклонён. Нужен действующий профиль.');
 if(code==='revision_conflict')return t('Конфликт версии устройства. Данные сохранены; нужна проверка профиля.');
 if(code==='dependency_missing')return t('Не установлены зависимости синхронизации. См. инструкцию подключения.');
 if(['profile_unavailable','secure_storage_unavailable'].includes(code))return t('Не удалось открыть защищённый профиль устройства.');
 return t(code==='cloud_unavailable'?'Не удалось подключиться. Отчёты сохранены до следующей попытки.':'Не удалось проверить данные облака. Последние проверенные отчёты сохранены.');
}
async function loadCloud(){
 if(cloudLoading)return;cloudLoading=true;
 try{
  const data=await request('/api/cloud');
  $('cloud-status').textContent=data.error?cloudError(data.error):data.lastSync?t('Синхронизировано {date}',{date:when(data.lastSync)}):t(data.configured?'Ожидается синхронизация':'Облако не подключено');
  $('cloud-source').textContent=data.configured?data.endpoint+'\n'+t('Устройство: {device} · других устройств: {count}',{device:data.device,count:data.remoteDevices.length}):'';
  $('sync-cloud').hidden=!data.configured;$('import-cloud').hidden=data.configured;$('cloud-help').hidden=data.configured;
 }catch(e){$('cloud-status').textContent=t(e.message);}
 finally{cloudLoading=false;if(!cloudTimer&&view==='settings'&&settingsTab==='connectors')cloudTimer=setTimeout(()=>{cloudTimer=null;if(view==='settings'&&settingsTab==='connectors')loadCloud();},5000);}
}
$('sync-cloud').addEventListener('click',async()=>{const button=$('sync-cloud');button.disabled=true;try{await request('/api/cloud/sync',{});$('cloud-message').textContent=t('Обновляется…');setTimeout(()=>{$('cloud-message').textContent='';loadCloud();},1500);}catch(e){$('cloud-message').textContent=t(e.message);}finally{button.disabled=false;}});
$('import-cloud').addEventListener('click',()=>$('cloud-profile-file').click());
$('cloud-profile-file').addEventListener('change',async()=>{
 const input=$('cloud-profile-file'),file=input.files[0];if(!file)return;
 try{if(file.size>4096)throw Error(t('Выбери JSON-профиль размером до 4 КБ.'));let profile;try{profile=JSON.parse(await file.text());}catch{throw Error(t('Не удалось прочитать профиль устройства.'));}await request('/api/cloud/profile',profile);$('cloud-message').textContent=t('Профиль подключён. Проверяем связь.');await loadCloud();}
 catch(e){$('cloud-message').textContent=t(e.message);}finally{input.value='';}
});
