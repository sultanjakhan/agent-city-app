'use strict';
let dataSourceProfile=null,dataSourceDraft=null,dataSourcePreview=null,dataSourceSummary=null;
let dataSourceBusy=false,dataSourceLoading=false,dataSourceDashboardLoading=false,dataOnboardingShown=false;
const dataSectionNames={projects:'Расширения',skills:'Навыки',runs:'Запуски',
 'tasks-production':'Задачи Cicada · production','tasks-dev':'Задачи Cicada · dev'};
const dataSourceStates={ready:'Данные доступны',missing:'Данные отсутствуют',not_connected:'Папка не выбрана',
 error:'Ошибка чтения',busy:'Ожидает завершения записи',hidden:'Скрыто'};

function sourceLabel(text,tag='span'){
 const node=el(tag,'',text);node.dataset.sourceLabel=text;return node;
}
async function sourceFailure(error){
 $('data-sources-error').hidden=false;$('data-sources-error').textContent=t(error.message);
 dataSourcePreview=null;
 if(error.status===409){try{const value=await request('/api/data-sources');dataSourceProfile={...dataSourceProfile,revision:value.revision};}catch{}}
}
function setDataSourceBusy(value){
 dataSourceBusy=value;
 for(const node of $('data-sources-form').querySelectorAll('input,select,button'))node.disabled=value;
 $('apply-data-sources').disabled=value||!dataSourcePreview;
 for(const button of document.querySelectorAll('[data-source-create]'))button.disabled=value||!dataSourcePreview?.bindings?.[button.dataset.sourceCreate];
 $('reload-data-sources').disabled=value;$('export-data-sources').disabled=value||!dataSourceProfile;
}
function invalidateDataSourcePreview(){
 dataSourcePreview=null;$('data-sources-preview').hidden=true;$('apply-data-sources').disabled=true;
 for(const button of document.querySelectorAll('[data-source-create]'))button.disabled=true;
 $('data-sources-message').textContent=t('Выбор изменён. Выполни preview перед применением.');
}
function dataSourceChoice(){
 const manifest=structuredClone(dataSourceDraft),bindings={};
 for(const input of document.querySelectorAll('[data-source-root]'))if(input.value.trim())bindings[input.dataset.sourceRoot]=input.value.trim();
 for(const section of manifest.sections){
  const row=document.querySelector(`[data-source-section="${section.id}"]`);
  section.visible=row.querySelector('input').checked;section.placement=row.querySelector('select').value;
 }
 return {manifest,bindings,revision:dataSourceProfile.revision};
}
function installDataSourceEditor(manifest,bindings){
 dataSourceDraft=structuredClone(manifest);dataSourcePreview=null;
 const roots=$('data-sources-roots'),sections=$('data-sources-sections');roots.replaceChildren();sections.replaceChildren();
 for(const source of manifest.sources){
  const row=el('section','data-source-root'),label=el('label'),input=el('input');input.type='text';input.autocomplete='off';input.spellcheck=false;
  input.dataset.sourceRoot=source.id;input.value=bindings[source.id]||'';input.placeholder=t('Полный путь к локальной папке');input.setAttribute('aria-label',source.kind);
  label.append(sourceLabel(source.kind==='agent-city-data'?'Папка Agent City data':'Папка Cicada data'),input);
  const create=sourceLabel('Создать структуру папок','button');create.type='button';create.className='text-button';create.dataset.sourceCreate=source.id;create.disabled=true;
  create.addEventListener('click',()=>createDataSourceStructure(source.id));
  row.append(label,el('code','source-path',t('Переносимая папка: {path}',{path:source.root}),true),sourceLabel('Только чтение'),create);roots.append(row);
 }
 for(const section of manifest.sections){
  const row=el('div','data-source-section'),label=el('label'),input=el('input'),select=el('select');row.dataset.sourceSection=section.id;
  input.type='checkbox';input.checked=section.visible;input.setAttribute('aria-label',t(dataSectionNames[section.id]));
  label.append(input,sourceLabel(dataSectionNames[section.id]));select.setAttribute('aria-label',t('Расположение')+' · '+t(dataSectionNames[section.id]));
  select.append(new Option(t('Данные и источники'),'data'),new Option(t('Дашборд'),'dashboard'));select.value=section.placement;
  row.append(label,select);sections.append(row);
 }
 $('data-sources-preview').hidden=true;setDataSourceBusy(false);
}
function drawDataSourceSummary(target,summary,placement=null){
 target.replaceChildren();
 const rows=(summary?.sections||[]).filter(row=>row.visible&&(!placement||row.placement===placement));
 for(const row of rows){
  const source=summary.sources.find(source=>source.id===row.sourceId),card=el('article','data-source-summary');card.dataset.sourceSummary=row.id;
  card.append(el('strong','',dataSectionNames[row.id]),el('p','',dataSourceStates[row.state]||'Ошибка чтения'),
   el('code','source-path',source?.root?source.root+' / '+row.path:row.path,true),
   el('p','',t('Записей: {count} · файл изменён: {date}',{count:row.count===null?'—':row.count,date:row.updatedAt?when(row.updatedAt):t('Неизвестна')}),true));
  if(row.error)card.append(el('p','',row.error));target.append(card);
 }
 if(!rows.length)target.append(el('p','section-description','Разделы для этого экрана не выбраны.'));
 if(summary?.checkedAt)target.append(el('p','section-description',t('Сводка прочитана: {date}',{date:when(summary.checkedAt)}),true));
}
async function renderDataSources(){
 if(dataSourceLoading)return;
 if(!dataSourceProfile){
  dataSourceLoading=true;
  try{dataSourceProfile=await request('/api/data-sources');installDataSourceEditor(dataSourceProfile.manifest,dataSourceProfile.bindings);dataSourceSummary=await request('/api/data-sources/status');$('data-sources-error').hidden=true;}
  catch(error){await sourceFailure(error);}finally{dataSourceLoading=false;}
 }
 if(!dataSourceProfile)return;
 $('data-sources-profile').textContent=t('Локальная конфигурация: {path}',{path:dataSourceProfile.profilePath});
 for(const node of document.querySelectorAll('[data-source-label]'))node.textContent=t(node.dataset.sourceLabel);
 for(const select of $('data-sources-sections').querySelectorAll('select')){select.options[0].text=t('Данные и источники');select.options[1].text=t('Дашборд');}
 for(const input of document.querySelectorAll('[data-source-root]'))input.placeholder=t('Полный путь к локальной папке');
 drawDataSourceSummary($('data-sources-current'),dataSourceSummary,'data');
 if(dataSourcePreview)drawDataSourcePreview();
}
function drawDataSourcePreview(){
 $('data-sources-preview').hidden=false;drawDataSourceSummary($('data-sources-preview-body'),dataSourcePreview);
 for(const source of dataSourcePreview.sources){
  if(!source.root)continue;
  const plan=el('p','section-description',t('Структура для {kind}: {paths}',{kind:source.kind,paths:source.structurePlan.join(', ')}),true);
  $('data-sources-preview-body').append(plan);
 }
}
$('data-sources-form').addEventListener('input',invalidateDataSourcePreview);
$('data-sources-form').addEventListener('change',event=>{if(event.target.id!=='import-data-sources')invalidateDataSourcePreview();});
$('data-sources-form').addEventListener('submit',async event=>{
 event.preventDefault();if(dataSourceBusy||!dataSourceProfile)return;
 const choice=dataSourceChoice();setDataSourceBusy(true);$('data-sources-error').hidden=true;
 try{dataSourcePreview=await request('/api/data-sources/preview',choice);drawDataSourcePreview();$('data-sources-message').textContent=t('Preview готов. Проверь папки и разделы перед применением.');}
 catch(error){await sourceFailure(error);}finally{setDataSourceBusy(false);}
});
$('apply-data-sources').addEventListener('click',async()=>{
 if(dataSourceBusy||!dataSourcePreview)return;
 const choice=dataSourceChoice(),token=dataSourcePreview.previewToken;setDataSourceBusy(true);
 try{dataSourceProfile=await request('/api/data-sources/apply',{...choice,previewToken:token});dataSourcePreview=null;dataSourceSummary=await request('/api/data-sources/status');
  $('data-sources-message').textContent=t('Выбор сохранён. Рабочие данные не переносились.');$('data-sources-error').hidden=true;$('data-sources-preview').hidden=true;
  drawDataSourceSummary($('data-sources-current'),dataSourceSummary,'data');
 }catch(error){await sourceFailure(error);}finally{setDataSourceBusy(false);}
});
async function createDataSourceStructure(id){
 if(dataSourceBusy||!dataSourcePreview)return;
 const choice=dataSourceChoice(),source=dataSourcePreview.sources.find(row=>row.id===id);
 if(!source?.root)return;
 if(!confirm(t('Создать папки {paths} в {root}? Существующие файлы не заменяются.',{paths:source.structurePlan.join(', '),root:source.root})))return;
 setDataSourceBusy(true);
 try{await request('/api/data-sources/create',{...choice,previewToken:dataSourcePreview.previewToken,sourceId:id});invalidateDataSourcePreview();$('data-sources-message').textContent=t('Структура создана. Добавь данные самостоятельно и повтори preview.');}
 catch(error){await sourceFailure(error);}finally{setDataSourceBusy(false);}
}
$('reload-data-sources').addEventListener('click',async()=>{
 if(dataSourceBusy)return;setDataSourceBusy(true);
 try{dataSourceSummary=await request('/api/data-sources/status');drawDataSourceSummary($('data-sources-current'),dataSourceSummary,'data');$('data-sources-error').hidden=true;}
 catch(error){await sourceFailure(error);}finally{setDataSourceBusy(false);}
});
$('export-data-sources').addEventListener('click',async()=>{
 if(dataSourceBusy||!dataSourceProfile)return;setDataSourceBusy(true);
 try{const manifest=await request('/api/data-sources/export'),url=URL.createObjectURL(new Blob([JSON.stringify(manifest,null,2)+'\n'],{type:'application/json'}));
  const a=document.createElement('a');a.href=url;a.download='data-sources.json';a.click();setTimeout(()=>URL.revokeObjectURL(url),1000);
 }catch(error){await sourceFailure(error);}finally{setDataSourceBusy(false);}
});
$('import-data-sources').addEventListener('change',async event=>{
 const file=event.target.files[0];if(!file||dataSourceBusy)return;setDataSourceBusy(true);
 try{if(file.size>16384)throw Error(t('Конфигурация слишком велика.'));
  const manifest=new TextDecoder('utf-8',{fatal:true}).decode(await file.arrayBuffer());
  const result=await request('/api/data-sources/validate',{document:manifest});installDataSourceEditor(result.manifest,{});
  $('data-sources-message').textContent=t('Конфигурация загружена в черновик. Выбери локальные папки и выполни preview.');$('data-sources-error').hidden=true;
 }catch(error){await sourceFailure(error);}finally{event.target.value='';setDataSourceBusy(false);}
});
async function renderDataSourceDashboard(){
 if(dataSourceDashboardLoading)return;dataSourceDashboardLoading=true;
 try{const summary=await request('/api/data-sources/status');const rows=summary.sections.filter(row=>row.visible&&row.placement==='dashboard');
  $('data-sources-dashboard').hidden=!rows.length;if(rows.length)drawDataSourceSummary($('data-sources-dashboard-body'),summary,'dashboard');
 }catch{$('data-sources-dashboard').hidden=true;}finally{dataSourceDashboardLoading=false;}
}
function maybeDataOnboarding(){
 if(!state?.dataSourcesOnboarding||dataOnboardingShown)return;
 dataOnboardingShown=true;$('data-onboarding-dialog').showModal();$('setup-data-onboarding').focus();
}
$('setup-data-onboarding').addEventListener('click',()=>{$('data-onboarding-dialog').close();selectSettingsTab('data');setView('settings');});
async function skipDataOnboarding(){
 $('skip-data-onboarding').disabled=$('setup-data-onboarding').disabled=true;
 try{await request('/api/data-sources/dismiss',{});state.dataSourcesOnboarding=false;$('data-onboarding-dialog').close();}
 catch(error){$('data-onboarding-message').textContent=t(error.message);}
 finally{$('skip-data-onboarding').disabled=$('setup-data-onboarding').disabled=false;}
}
$('skip-data-onboarding').addEventListener('click',skipDataOnboarding);
$('data-onboarding-dialog').addEventListener('cancel',event=>{event.preventDefault();skipDataOnboarding();});
if(state){maybeDataOnboarding();if(view==='settings'&&settingsTab==='data')renderDataSources();}
