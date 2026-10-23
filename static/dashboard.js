'use strict';
let dashboardData=null,dashboardLoading=false,dashboardTimer=null,dashboardTaskKey=null;
let connectorData=null,connectorLoading=false,connectorSaving=false;
const dashboardParams=new URLSearchParams(location.search);
let dashboardMode=dashboardParams.get('history')==='1'?'history':'current',dashboardLinkPending=dashboardParams.get('task');
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
  main.append(el('strong','',stage.stage||t('Этап не сообщён'),true),el('span','stage-report-models',[...new Set(stage.runs.map(r=>r.model||t('Модель не сообщена')))].join(', '),true));
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
 try{dashboardData=await request('/api/dashboard');$('dashboard-error').hidden=true;renderDashboardRows();if(typeof updateWorkRegistrySnapshot==='function')updateWorkRegistrySnapshot(dashboardData.workRegistry);if(view==='dashboard'&&typeof loadSharedTasks==='function')await loadSharedTasks();}
 catch(e){$('dashboard-error').hidden=false;$('dashboard-error').textContent=t(e.message);}
 finally{dashboardLoading=false;scheduleDashboard();}
}
function scheduleDashboard(){if(dashboardTimer)return;if(view==='dashboard')dashboardTimer=setTimeout(()=>{dashboardTimer=null;if(view==='dashboard')loadDashboard(true);},5000);}
function renderDashboard(){loadDashboard();if(typeof loadSharedTasks==='function')loadSharedTasks();if(typeof renderDataSourceDashboard==='function')renderDataSourceDashboard();}
function taskRuns(task){return task._runs||(dashboardData?.runs||[]).filter(r=>(task.runTaskKeys||[task.taskKey]).includes(r.taskKey));}
// Group only by confirmed source aliases. Unbound reports retain their run identity.
function dashboardReportEntries(){
 const known=new Map([...(dashboardData?.cicada?.tasks||[]),...(dashboardData?.cicada?.historyTasks||[])].flatMap(task=>(task.runTaskKeys||[task.taskKey]).map(key=>[key,task])));
 const grouped=new Map();
 for(const run of dashboardData?.runs||[]){const task=known.get(run.taskKey),key=task?.taskKey||run.taskKey||`run:${run.originDevice||'local'}:${run.runId}`;if(!grouped.has(key))grouped.set(key,[]);grouped.get(key).push(run);}
 return [...grouped].filter(([key])=>!(typeof isSharedTask==='function'&&isSharedTask(key))).map(([key,runs])=>{
  runs.sort((a,b)=>(b.updatedAt||'').localeCompare(a.updatedAt||''));const task=known.get(key),unbound=!runs[0].taskKey;
  return {...(task?{...task,taskKey:key}:{taskKey:key,title:(unbound?t('Запуск без задачи')+' · '+runs[0].runId:t('Задача Cicada')+' · '+key.slice(7,13)+'…'+key.slice(-12)),missingSource:true,unbound}),_runs:runs,lastReportAt:runs[0].updatedAt||''};
 }).sort((a,b)=>b.lastReportAt.localeCompare(a.lastReportAt));
}
function dashboardTaskInHistory(task){return task.completed===true&&!taskRuns(task).some(freshRun);}
function historyEntries(){return dashboardReportEntries().filter(dashboardTaskInHistory);}
function currentDashboardEntries(){
 const tasks=new Map((dashboardData?.cicada?.tasks||[]).filter(task=>!task.completed).map(task=>[task.taskKey,task]));
 for(const task of dashboardReportEntries())if(!dashboardTaskInHistory(task))tasks.set(task.taskKey,task);
 return [...tasks.values()];
}
function findDashboardTask(key){return [...(dashboardData?.cicada?.tasks||[]),...dashboardReportEntries()].find(task=>(task.runTaskKeys||[task.taskKey]).includes(key));}
function dashboardMetadata(task){
 const tags=Array.isArray(task.tags)?task.tags:typeof task.tags==='string'?task.tags.split(',').map(x=>x.trim()).filter(Boolean):[];
 return {projects:[...new Set([...(Array.isArray(task.projects)?task.projects:[]),...tags.filter(x=>x.startsWith('project:')).map(x=>x.slice(8))])].filter(Boolean),tags:[...new Set(tags.filter(x=>!x.startsWith('project:')&&!x.startsWith('task-stage-log:')))]};
}
function refreshDashboardFilters(){
 const all=[...(dashboardData?.cicada?.tasks||[]),...(dashboardData?.cicada?.historyTasks||[]),...dashboardReportEntries(),...Object.values(typeof sharedState==='undefined'?{}:sharedState?.tasks||{})];
 for(const [id,key,label,empty] of [['dashboard-project','projects','Все проекты','Без проекта'],['dashboard-tag','tags','Все теги','Без тегов']]){
  const select=$(id);if(!select)continue;const selected=select.value,values=[...new Set(all.flatMap(task=>dashboardMetadata(task)[key]))].sort((a,b)=>a.localeCompare(b)),options=[['',t(label)],['null',t(empty)],...values.map(value=>[JSON.stringify(value),value])];
  if(selected&&!options.some(([value])=>value===selected))options.push([selected,JSON.parse(selected)+' · '+t('Недоступно')]);
  const signature=JSON.stringify(options);if(select.dataset.options!==signature){select.replaceChildren(...options.map(([value,text])=>new Option(text,value)));select.value=selected;select.dataset.options=signature;}
 }
}
function dashboardMatchesMetadata(task){
 const metadata=dashboardMetadata(task);
 return [['dashboard-project','projects'],['dashboard-tag','tags']].every(([id,key])=>{const selected=$(id)?.value;if(!selected)return true;const value=JSON.parse(selected);return value===null?!metadata[key].length:metadata[key].includes(value);});
}
function dashboardMatchesSearch(task,runs=taskRuns(task)){
 const query=$('dashboard-search').value.trim().toLowerCase(),metadata=dashboardMetadata(task);
 return [task.title,task.stageLabel,task.stage,task.sourceId,task.taskKey,...metadata.projects,...metadata.tags,...runs.flatMap(run=>[run.runId,run.model,run.agent])].filter(Boolean).join(' ').toLowerCase().includes(query);
}
function syncDashboardTabs(){
 for(const button of document.querySelectorAll('[data-dashboard-mode]')){const selected=button.dataset.dashboardMode===dashboardMode;button.setAttribute('aria-selected',String(selected));button.tabIndex=selected?0:-1;}
 $('dashboard-filter').hidden=dashboardMode==='history';
}
function renderHistoryRows(){
 const all=historyEntries(),tasks=all.filter(task=>dashboardMatchesSearch(task)&&dashboardMatchesMetadata(task)),list=$('dashboard-tasks'),focused=document.activeElement?.dataset.taskKey;
 list.replaceChildren();
 for(const task of tasks){
  const latest=task._runs[0];
  const errors=aggregateRuns(task._runs).overall.statuses.error||0;
  const {row,main}=taskWidgetRow(task.title,{taskKey:task.taskKey,onOpen:()=>openDashboardTask(task.taskKey),tone:errors?'warn':'neutral',status:errors?t('Неудачных попыток: {count}',{count:errors}):runState(latest)});
  main.append(el('p','task-meta',t('Запусков: {count} · {date}',{count:task._runs.length,date:when(task.lastReportAt)}),true));
  const facts=taskFacts(task,task._runs);if(facts)main.append(el('p','task-executor',facts,true));
  if(task.missingSource)main.append(el('p','task-meta',task.unbound?'Не привязан к задаче Cicada.':'Название недоступно в выбранной Cicada. Отчёты сохранены.'));
  list.append(row);
 }
 if(focused)[...list.querySelectorAll('button')].find(b=>b.dataset.taskKey===focused)?.focus({preventScroll:true});
 $('dashboard-empty').hidden=!!tasks.length;$('dashboard-empty').textContent=t(all.length?'Ничего не нашлось':'Здесь появятся завершённые запуски и отчёты без задачи.');
 if(typeof appendSharedTaskRows==='function')appendSharedTaskRows();
 if(dashboardData.cicada.historyLimited)list.append(el('p','section-description','Названия прочитаны для последних 500 задач с отчётами.'));
}
function freshRun(run){return ['running','waiting'].includes(run.status)&&Date.parse(run.updatedAt)<=Date.now()+30000&&age(run.updatedAt)<=300;}
function mcpText(run){return run.mcpCalls===null||run.mcpCalls===undefined?t('Нет данных'):run.mcpCalls.length?run.mcpCalls.map(c=>`${c.server} / ${c.tool} × ${c.calls}`).join(', '):t('Вызовов не было');}
function runState(run){return t(runStatuses[run.status]||'Нет данных')+(['running','waiting'].includes(run.status)&&!freshRun(run)?' · '+t('Нет свежего отчёта'):'');}
function stageName(task){return task.stageLabel||task.stage||t('Этап не задан');}
function tokenText(run){return t('Вход: {input} · Выход: {output}',{input:run.inputTokens??'—',output:run.outputTokens??'—'});}
function modelText(run){return run.model?`${run.provider?run.provider+' · ':''}${run.model}`:t('Модель не сообщена');}
function drawRun(run,{inline=false}={}){
 const row=el('article','run-row'+(inline?' single-attempt':'')),head=el('header','run-heading'),main=el('span','attempt-main'),state=groupState([run]);
 main.append(el('strong','',run.model||t('Модель не сообщена'),true),el('span','attempt-subtitle',[run.agent,run.stage].filter(Boolean).join(' · '),true));
 head.append(main,el('span','attempt-state '+state.tone,runState(run),true));
 if(!inline)row.append(head);
 if(run.provider||!inline)row.append(el('p','attempt-provider',modelText(run),true));
 if(run.status==='error')row.append(el('p','report-hint','Ошибка исполнителя. Причина не сообщена в отчёте.'));
 if(run.originDevice)row.append(el('p','source-path',t('Источник: {device}',{device:run.originDevice}),true));
 row.append(el('p','source-path','Run ID: '+run.runId,true));
 const metrics=el('dl','run-metrics');
 for(const [name,value] of [['Токены',tokenText(run)],['Навыки',reportedSkills(run).map(s=>s.name).join(', ')||t('Нет данных')],['MCP',mcpText(run)],['Последний отчёт',when(run.updatedAt)]])metrics.append(el('dt','',name),el('dd','',value,true));
 row.append(metrics);
 if(run.history?.length>1){const history=el('section','attempt-events'),list=el('ol','run-history');history.append(el('h4','','События агента'));for(const entry of run.history)list.append(el('li','',`${entry.stage||'—'} · ${t(runStatuses[entry.status]||'Нет данных')} · ${when(entry.reportedAt)}${entry.inputTokens!==undefined?' · '+tokenText(entry):''}${entry.mcpCalls?.length?' · MCP: '+mcpText(entry):''}${entry.skillIds?.length?' · '+t('Навыки')+': '+entry.skillIds.map(id=>run.skills?.find(s=>s.id===id)?.name||id).join(', '):''}`,true));history.append(list);row.append(history);}
 return row;
}
function renderDashboardRows(){
 if(!dashboardData)return;
 renderImportedObservations(dashboardData.importedObservations);
 refreshDashboardFilters();syncDashboardTabs();
 const data=dashboardData.cicada,source=data.source;
 $('dashboard-source').textContent=source?t(data.status==='connected'?'{name} · прочитано {date}':'{name} · источник недоступен',{name:source.label,date:when(data.readAt)}):t('Cicada не подключена');
 $('dashboard-error').hidden=data.status!=='error';if(data.status==='error')$('dashboard-error').textContent=t(data.error||'Не удалось прочитать Cicada. Проверь источник в настройках.');
 if(dashboardMode==='history'){renderHistoryRows();finishDashboardRender();return;}
 const filter=$('dashboard-filter').value;
 const all=currentDashboardEntries(),tasks=all.filter(task=>!(typeof isSharedTask==='function'&&isSharedTask(task.taskKey))&&dashboardMatchesSearch(task)&&dashboardMatchesMetadata(task)&&(filter==='all'||filter==='working'&&(task.isActive||taskRuns(task).some(r=>r.status==='running'&&freshRun(r)))||filter==='waiting'&&(task.waiting||taskRuns(task).some(r=>r.status==='waiting'&&freshRun(r)||r.status==='done'))||filter==='paused'&&task.isPaused));
 tasks.sort((a,b)=>Number(b.isActive)-Number(a.isActive)||(a.date||'9999').localeCompare(b.date||'9999'));
 const list=$('dashboard-tasks'),focused=document.activeElement?.dataset.taskKey;list.replaceChildren();
 for(const task of tasks){
  const reports=taskRuns(task),latestReport=[...reports].sort((a,b)=>(b.updatedAt||'').localeCompare(a.updatedAt||''))[0],active=reports.some(r=>freshRun(r)&&r.status==='running'),waiting=reports.some(r=>freshRun(r)&&r.status==='waiting');
  const status=active?'ИИ работает · по отчёту':waiting?'ИИ ожидает · по отчёту':reports.length&&reports.every(r=>r.status==='done')?'ИИ закончил · приёмка не подтверждена':latestReport?.status==='error'?'Ошибка ИИ · по отчёту':latestReport?.status==='cancelled'?'Запуск отменён · по отчёту':latestReport&&['running','waiting'].includes(latestReport.status)?'Нет свежего отчёта':task.isActive?'Твой таймер идёт':task.waiting?'Ожидает':task.isPaused?'На паузе':'Статус ИИ неизвестен';
  const {row,main}=taskWidgetRow(task.title,{taskKey:task.taskKey,onOpen:()=>openDashboardTask(task.taskKey),status});
  if(!task.missingSource)main.append(el('p','task-stage',stageName(task),true));
  const metadata=dashboardMetadata(task),labels=[...metadata.projects,...metadata.tags];if(labels.length)main.append(el('p','task-meta',labels.join(' · '),true));
  if(task.missingSource)main.append(el('p','task-meta',task.unbound?'Не привязан к задаче Cicada.':'Название недоступно в выбранной Cicada. Отчёты сохранены.'));
  const meta=[task.processLabel||task.process,task.date,task.plannedTime].filter(Boolean);if(meta.length)main.append(el('p','task-meta',meta.join(' · '),true));
  const facts=taskFacts(task,reports);if(facts||!reports.length)main.append(el('p','task-executor',facts||t('Нет отчётов агента'),true));
  if(reports.length){const latest=[...reports].sort((a,b)=>b.updatedAt.localeCompare(a.updatedAt))[0];main.append(el('p','task-meta',`${latest.agent||t('Исполнитель неизвестен')} · ${latest.model||t('Модель не сообщена')} · ${t('Последний отчёт')}: ${when(latest.updatedAt)}`,true));}
  if(!task.missingSource)main.append(el('p','task-meta',t('Твой таймер: {state}',{state:t(task.isActive?'идёт':task.isPaused?'на паузе':'не идёт')}),true));
  list.append(row);
 }
 if(focused)[...list.querySelectorAll('button')].find(b=>b.dataset.taskKey===focused)?.focus({preventScroll:true});
 $('dashboard-empty').hidden=!!tasks.length;$('dashboard-empty').textContent=t(data.status==='disconnected'?'Выбери источник задач в настройках.':data.status==='error'?'Данные задач недоступны.':all.length?'Ничего не нашлось':'Сейчас ничего не запущено. Запусти задачу в Cicada — она появится здесь.');
 if(data.hasMore)list.append(el('p','section-description','Показаны первые 500 задач.'));
 if(typeof appendSharedTaskRows==='function')appendSharedTaskRows();
 finishDashboardRender();
}
function finishDashboardRender(){
 refreshTaskWidgetCount();
 if(dashboardLinkPending&&openDashboardKey(dashboardLinkPending))dashboardLinkPending=null;
 if(dashboardTaskKey&&$('dashboard-task-dialog').open)renderDashboardTask();
}
function renderDashboardTask(){
 const task=findDashboardTask(dashboardTaskKey),body=$('dashboard-task-body'),actions=$('dashboard-task-actions'),focused=document.activeElement?.id,scroll=body.scrollTop;body.replaceChildren();actions.replaceChildren();
 if(!task){body.append(el('p','','Задачи больше нет в выбранном списке Cicada.'));return;}
 $('dashboard-task-title').textContent=task.title;
 if(task.missingSource)body.append(el('p','report-context',task.unbound?'Не привязан к задаче Cicada.':'Название недоступно в выбранной Cicada. Отчёты сохранены.'));
 else body.append(el('p','report-context',[task.completed?t('Задача завершена в Cicada'):'Cicada · '+stageName(task),task.processLabel||task.process].filter(Boolean).join(' · '),true));
 const runs=taskRuns(task);
 if(!task.unbound)body.append(el('p','source-path',(task.sourceId?'Task ID: '+task.sourceId:'Task key: '+task.taskKey),true));
 body.append(drawTaskReport(task,runs));
 if(task.stageHistory?.length){const detail=el('section','report-section'),list=el('ol','run-history');detail.append(el('h3','','История этапов Cicada'));for(const event of task.stageHistory)list.append(el('li','',`${event.stageLabel||event.stage||'—'} · ${when(event.at)}`,true));detail.append(list);body.append(detail);}
 const link=el('button','secondary','Ссылка');link.id='copy-report-link';link.title=t('Скопировать ссылку на отчёт');link.addEventListener('click',()=>{const url=new URL(location.href);url.search='';url.searchParams.set('task',task.taskKey);if(dashboardTaskInHistory(task))url.searchParams.set('history','1');url.hash='dashboard';navigator.clipboard.writeText(url.href).then(()=>toast('Ссылка скопирована')).catch(()=>toast('Не удалось скопировать'));});actions.append(link);
 if(task.taskKey.startsWith('cicada-')){const copy=el('button','text-button','ID задачи');copy.id='copy-task-id';copy.title=t('Копировать ID задачи для агента');copy.addEventListener('click',()=>navigator.clipboard.writeText(task.taskKey).then(()=>toast('ID скопирован')).catch(()=>toast('Не удалось скопировать')));actions.append(copy);}
 const copyReport=el('button','primary','Скопировать отчёт');copyReport.id='copy-task-report';copyReport.addEventListener('click',()=>navigator.clipboard.writeText(taskReportText(task,runs)).then(()=>toast('Отчёт скопирован')).catch(()=>toast('Не удалось скопировать')));actions.prepend(copyReport);
 body.scrollTop=scroll;if(focused&&actions.contains($(focused)))$(focused).focus({preventScroll:true});
}
function openDashboardTask(key){dashboardTaskKey=key;$('dashboard-task-body').replaceChildren();$('dashboard-task-body').scrollTop=0;renderDashboardTask();$('dashboard-task-dialog').showModal();}
function taskKeyFromSearch(value){
 const text=value.trim();if(/^(cicada-|run:)[A-Za-z0-9_.:-]+$/.test(text))return text;
 try{const url=new URL(text);return ['http:','https:'].includes(url.protocol)&&url.searchParams.get('task')||null;}catch{return null;}
}
function findSharedDashboardTask(key){return Object.values(typeof sharedState==='undefined'?{}:sharedState?.tasks||{}).find(task=>task.binding.taskKey===key);}
function openDashboardKey(key){
 const shared=findSharedDashboardTask(key);
 if(shared){openSharedTask(shared.id);return true;}
 const task=findDashboardTask(key);if(!task)return false;
 openDashboardTask(key);return true;
}
function openSearchedReport(){
 const key=taskKeyFromSearch($('dashboard-search').value);if(!key)return false;
 const shared=findSharedDashboardTask(key),task=shared||findDashboardTask(key);
 if(!task){toast('Отчёт не найден в этом источнике Cicada.');return true;}
 const latest=shared&&sharedRun(shared),live=latest&&['running','waiting'].includes(sharedReport(latest)?.status)&&sharedRunFresh(latest);
 $('dashboard-search').value='';dashboardMode=shared?(shared.completed&&!live?'history':'current'):dashboardTaskInHistory(task)?'history':'current';renderDashboardRows();openDashboardKey(key);return true;
}
$('close-dashboard-task').addEventListener('click',()=>{$('dashboard-task-dialog').close();dashboardTaskKey=null;});
$('dashboard-search').addEventListener('input',renderDashboardRows);for(const id of ['dashboard-filter','dashboard-project','dashboard-tag'])$(id).addEventListener('change',renderDashboardRows);
$('dashboard-search').addEventListener('keydown',event=>{if(event.key==='Enter'&&openSearchedReport())event.preventDefault();});
for(const button of document.querySelectorAll('[data-dashboard-mode]')){
 button.addEventListener('click',()=>{dashboardMode=button.dataset.dashboardMode;renderDashboardRows();});
 button.addEventListener('keydown',event=>{if(!['ArrowLeft','ArrowRight','Home','End'].includes(event.key))return;event.preventDefault();const buttons=[...document.querySelectorAll('[data-dashboard-mode]')],next=buttons[event.key==='Home'?0:event.key==='End'?buttons.length-1:1-buttons.indexOf(button)];next.click();next.focus();});
}

function connectorStatus(data){
 const observation=data.observation;
 if(!observation)return t('Источник сохранён. Чтение ещё не проверено.');
 if(observation.status==='disconnected')return t('Источник Cicada не подключён.');
 if(observation.status==='error')return t('Ошибка чтения Cicada. Проверь источник и повтори проверку.');
 if(observation.status!=='connected')return t('Состояние источника неизвестно. Повтори проверку.');
 const activity=observation.activeTaskCount?t('Активных таймеров среди прочитанных задач: {count}',{count:observation.activeTaskCount}):observation.taskCount?t('Среди прочитанных задач активных таймеров нет.'):t('Подходящих задач в источнике пока нет.');
 return t('Cicada доступна для чтения. Проверено {date}',{date:when(observation.readAt)})+' · '+activity+' '+t('Это не подтверждает обмен задачами или синхронизацию устройств.');
}
async function renderConnectors(){
 loadCloud();
 if(connectorLoading||connectorSaving)return;
 connectorLoading=true;$('check-cicada-source').disabled=true;$('cicada-source-status').textContent=t('Проверяем чтение Cicada…');
 try{connectorData=await request('/api/connectors');$('cicada-source-status').textContent=connectorStatus(connectorData);}
 catch(e){$('cicada-source-status').textContent=t('Не удалось проверить источник Cicada. Повтори проверку.');return;}
 finally{connectorLoading=false;$('check-cicada-source').disabled=false;}
 if(!connectorData)return;
 const select=$('cicada-source'),draft=select.dataset.loaded?select.value:connectorData.selectedId||'';
 if(connectorData.selectedId&&!connectorData.candidates.some(c=>c.id===connectorData.selectedId))connectorData.candidates.push({id:connectorData.selectedId,label:t('Сохранённый источник недоступен'),path:''});
 select.replaceChildren(new Option(t('Не подключено'),''),...connectorData.candidates.map(c=>new Option(c.label,c.id)));select.value=draft;select.dataset.loaded='true';showConnectorPath();
}
function showConnectorPath(){const selected=connectorData?.candidates.find(c=>c.id===$('cicada-source').value);$('cicada-source-path').textContent=selected?.path||'';$('cicada-source-message').textContent=connectorData&&($('cicada-source').value||null)!==connectorData.selectedId?t('Выбран другой источник. Сохрани выбор, чтобы применить его.'):'';}
$('cicada-source').addEventListener('change',showConnectorPath);
$('check-cicada-source').addEventListener('click',renderConnectors);
$('save-cicada-source').addEventListener('click',async()=>{
 if(!connectorData||connectorSaving||connectorLoading)return;connectorSaving=true;$('save-cicada-source').disabled=true;$('cicada-source').disabled=true;
 try{connectorData=await request('/api/connectors/cicada',{sourceId:$('cicada-source').value||null,revision:connectorData.revision});dashboardData=null;$('cicada-source-message').textContent=t('Выбор источника сохранён.');$('cicada-source-status').textContent=connectorStatus(connectorData);}
 catch(e){$('cicada-source-message').textContent=t(e.message);connectorData=null;}finally{connectorSaving=false;$('save-cicada-source').disabled=false;$('cicada-source').disabled=false;}
});

let cloudLoading=false,cloudTimer=null;
function cloudStatus(data){
 if(data.state==='paused')return t('Синхронизация приостановлена в локальном режиме.');
 if(data.error||data.state==='error')return cloudError(data.error);
 if(!data.configured)return t('Облако не подключено');
 if(!data.lastSync)return t('Профиль подключён. Ожидается первый успешный обмен отчётами.');
 return t('Последний успешный обмен отчётами: {date}',{date:when(data.lastSync)})+' '+t('Это не синхронизация задач, настроек или навыков.');
}
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
  $('cloud-status').textContent=cloudStatus(data);
  $('cloud-source').textContent=data.configured?data.endpoint+'\n'+t('Устройство: {device} · других устройств: {count}',{device:data.device,count:data.remoteDevices.length}):'';
  $('sync-cloud').hidden=!data.configured||data.state==='paused';$('import-cloud').hidden=!!data.configured||data.state==='paused';$('cloud-help').hidden=!!data.configured||data.state==='paused';
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
