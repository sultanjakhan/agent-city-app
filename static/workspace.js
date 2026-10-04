'use strict';
// Shares the trusted labels, state and request helper with app.js. Skill bodies stay raw.
let skillRows=null,skillsLoading=false,skillCurrent=null,skillPreview=null,skillSaving=false,skillControls=null,skillToggling=false;
let settingsTab='connectors';
try{const saved=localStorage.getItem('agentcity-settings-tab');if(['connectors','catalogs','agents','data'].includes(saved))settingsTab=saved;}catch{}
function selectSettingsTab(id,focus=false){
 if(!['connectors','catalogs','agents','data'].includes(id))return;
 settingsTab=id;try{localStorage.setItem('agentcity-settings-tab',id);}catch{}
 for(const tab of document.querySelectorAll('[data-settings-tab]')){const active=tab.dataset.settingsTab===id;tab.setAttribute('aria-selected',String(active));tab.tabIndex=active?0:-1;$(tab.getAttribute('aria-controls')).hidden=!active;if(active&&focus)tab.focus();}
 if(state&&view==='settings')renderSettingsContent();
}
for(const tab of document.querySelectorAll('[data-settings-tab]')){
 tab.addEventListener('click',()=>selectSettingsTab(tab.dataset.settingsTab));
 tab.addEventListener('keydown',e=>{const tabs=[...document.querySelectorAll('[data-settings-tab]')],index=tabs.indexOf(tab);let target;if(e.key==='ArrowRight')target=tabs[(index+1)%tabs.length];if(e.key==='ArrowLeft')target=tabs[(index+tabs.length-1)%tabs.length];if(e.key==='Home')target=tabs[0];if(e.key==='End')target=tabs.at(-1);if(target){e.preventDefault();selectSettingsTab(target.dataset.settingsTab,true);}});
}
function renderSettings(){
 selectSettingsTab(settingsTab);
}
function renderSettingsContent(){
 if(settingsTab==='connectors'){renderConnectors();if(typeof renderTaskConnection==='function')renderTaskConnection();return;}
 if(settingsTab==='agents'){renderAgentConnection();renderAgentInfo();return;}
 if(settingsTab==='data'){renderDataInfo();renderDataSources();if(typeof renderWorkRegistry==='function')renderWorkRegistry();return;}
 renderCatalogSettings();
}
function renderAgentInfo(){
 const info=$('settings-info');info.replaceChildren();
 info.append(el('h3','','Доступ для репозиториев'),el('p','','API только для чтения: модели, подключения, навыки и источники.'),link('Описание API ↗','/api/v1/manifest'),el('code','source-path',location.origin+'/api/v1/manifest',true),el('p','','Модели, токены, навыки и MCP появляются на дашборде только после отчёта агента.'));
}
function renderDataInfo(){
 const info=$('settings-data-info');info.replaceChildren();
 info.append(el('p','',`Agent City ${state.settings?.version||''}`,true),el('h3','','Хранилище устройства'),el('code','source-path',state.settings?.dataRoot||'',true),el('h3','','Библиотека навыков'),el('code','source-path',state.settings?.skillsRoot||'',true));
 if(state.settings?.libraryMode==='worktree')info.append(el('p','','Библиотека рабочей ветки. Для установленных агентов изменения нужно перенести в их подключённую библиотеку.'));
 const storage=state.settings?.storage;
 if(!storage?.supported)return;
 info.append(el('h3','','Папка данных'),el('code','source-path',storage.root,true));
 if(storage.state==='prepared'){
  info.append(el('p','',`Перенос подготовлен: ${storage.destination}. Закрой Agent City обычным способом и открой снова. Исходная папка останется для восстановления.`,true));
  const cancel=el('button','', 'Отменить перенос');cancel.type='button';
  cancel.addEventListener('click',async()=>{try{await request('/api/storage/cancel',{revision:storage.revision});await load();}catch(error){toast(error.message);}});
  info.append(cancel);return;
 }
 if(storage.state==='complete')info.append(el('p','','Перенос завершён. Исходная папка сохранена для восстановления.'));
 if(storage.state==='error')info.append(el('p','',storage.error||'Перенос не завершён. Исходная папка сохранена.',true));
 const label=el('label','','Новая пустая папка');const input=el('input');input.type='text';input.id='storage-destination';label.htmlFor=input.id;
 input.autocomplete='off';input.spellcheck=false;
 const save=el('button','','Подготовить перенос');save.type='button';
 save.addEventListener('click',async()=>{save.disabled=true;try{await request('/api/storage/prepare',{destination:input.value,revision:storage.revision});await load();}catch(error){toast(error.message);}finally{save.disabled=false;}});
 info.append(label,input,el('p','','Данные будут перенесены после обычного закрытия приложения. Выбери локальную пустую папку; исходные файлы сохранятся.'),save);
}
function renderCatalogSettings(){
 const list=$('catalog-sources');list.replaceChildren();
 for(const source of state.sources){
  const c=state.catalogs[source.id]||{},row=el('div','connection-row');
  row.append(el('strong','',source.name,true),link('Каталог API ↗',source.catalogUrl||source.docs),link('Документация ↗',source.docs),el('p','',t('Снимок от {date}',{date:when(c.updatedAt)})));
  if(c.error)row.append(el('p','',c.error));
  list.append(row);
 }
 const directory=state.directory||{};$('directory-status').textContent=directory.error?t(directory.error):t('Снимок от {date}',{date:when(directory.updatedAt)});
 $('refresh-directory').disabled=state.busy?.includes('directory')||false;
 renderDirectory();
}
function renderDirectory(){
 const q=$('directory-search').value.trim().toLowerCase(),list=$('directory-list');list.replaceChildren();
 const rows=(state.directory?.providers||[]).filter(p=>`${p.name} ${p.id}`.toLowerCase().includes(q));
 for(const p of rows){
  const row=el('div','directory-row');row.append(el('strong','',p.name,true),el('span','',t('{count} моделей в справочнике',{count:p.modelCount})));
  if(p.docs)row.append(link('Документация ↗',p.docs));
  row.append(el('span','',state.sources.some(s=>s.id===p.id)?'Адаптер добавлен':'Подключение не проверено'));list.append(row);
 }
 list.prepend(link('Источник: Models.dev ↗','https://models.dev/'));
}
async function renderSkills(){
 $('skills-root').textContent=state.settings?.skillsRoot||'';
 $('skills-scope').hidden=state.settings?.libraryMode!=='worktree';
 if(skillRows===null){
  if(skillsLoading)return;skillsLoading=true;
  try{skillRows=(await request('/api/skill-inventory')).skills;$('skills-error').hidden=true;
   try{skillControls=(await request('/api/codex-controls')).config;}catch(e){skillControls=null;$('skills-error').hidden=false;$('skills-error').textContent=t(e.message);}
  }
  catch(e){$('skills-error').hidden=false;$('skills-error').textContent=t(e.message);}
  finally{skillsLoading=false;}
 }
 const list=$('skills-list');list.replaceChildren();const q=$('skills-search').value.trim().toLowerCase(),origin=$('skills-origin').value;
 const rows=(skillRows||[]).filter(s=>(origin==='all'||s.status===origin)&&`${s.name} ${s.description} ${s.path}`.toLowerCase().includes(q));
 rows.sort((a,b)=>({installed:0,workspace:1,cached:2}[a.status]??3)-({installed:0,workspace:1,cached:2}[b.status]??3)||a.name.localeCompare(b.name));
 $('skills-count').textContent=t('Показано {shown} из {total}',{shown:rows.length,total:skillRows?.length||0});
 for(const skill of rows){
  const row=el('article','library-row');const button=el('button','model-title',skill.name,true);button.addEventListener('click',()=>skill.status==='workspace'?openSkill(skill.slug):openInstalledSkill(skill.id));
  const source=skill.status==='workspace'?'Рабочая ветка · редактирование':skill.status==='cached'?'Кэш плагина · подключение не проверено':'Установленный навык · чтение';
  row.append(button,el('span','library-origin',t(source)+' · '+skill.origin),el('p','skill-description',skill.description,true));
  const activity=skill.activity||{},control=skillControls?.skills.find(s=>s.id===skill.id);
  row.append(el('p','skill-stats',t('Применений по отчётам: {uses} · Просмотров: {views}',{uses:activity.reportedUses||0,views:activity.views||0})));
  if(activity.lastUsedAt)row.append(el('p','skill-stats',t('Последнее применение: {date}',{date:when(activity.lastUsedAt)})));
  if(control){const actions=el('div','skill-row-actions');actions.append(el('span','library-origin',control.status==='disabled'?'Выключен в Codex':control.status==='enabled'?'Включён в Codex':'Состояние Codex неизвестно'));
   if(control.canToggle){const toggle=el('button','text-button',control.status==='disabled'?'Включить в Codex':'Выключить в Codex');toggle.disabled=skillToggling;toggle.addEventListener('click',()=>toggleSkill(skill.id,control.status==='disabled'));actions.append(toggle);}row.append(actions);}
  if(skill.status!=='workspace'){const copy=(skillRows||[]).find(s=>s.status==='workspace'&&s.slug===skill.slug);if(copy){const edit=el('button','text-button','Редактировать рабочую версию');edit.addEventListener('click',()=>openSkill(copy.slug));row.append(edit);}}
  list.append(row);
 }
 if(!rows.length)list.append(el('p','','Ничего не нашлось'));
}
function installSkillDraft(skill){
 skillCurrent=skill;skillPreview=null;$('skill-title').textContent=skill.name;$('skill-path').textContent=skill.path;$('skill-content').value=skill.content;
 const readonly=skill.editable===false;$('skill-content').readOnly=readonly;document.querySelector('#skill-dialog .skill-actions').hidden=readonly;$('skill-history-section').hidden=readonly;
 $('skill-diff-section').hidden=true;$('save-skill').disabled=true;$('skill-message').textContent='';
 $('skill-history').replaceChildren(...(skill.history||[]).map(h=>new Option(`${when(h.modifiedAt)} · ${h.revision.slice(0,8)}`,h.revision)));
 $('load-skill-version').disabled=!(skill.history||[]).length;
}
async function openSkill(slug){
 if(skillSaving)return;
 try{installSkillDraft({...await request('/api/skills?slug='+encodeURIComponent(slug)),slug});$('skill-dialog').showModal();recordSkillView((skillRows||[]).find(s=>s.status==='workspace'&&s.slug===slug)?.id);}
 catch(e){toast(e.message);}
}
async function openInstalledSkill(id){
 if(skillSaving)return;
 try{installSkillDraft(await request('/api/skill-inventory?id='+encodeURIComponent(id)));$('skill-message').textContent=t('Чтение исходного файла. Этот путь не изменяется из приложения.');$('skill-dialog').showModal();recordSkillView(id);}catch(e){toast(e.message);}
}
async function recordSkillView(id){if(!id)return;try{const data=await request('/api/skill-activity',{id,kind:'view',agent:'user',eventId:crypto.randomUUID()});const row=skillRows?.find(s=>s.id===id);if(row)row.activity=data.skills[id];await renderSkills();}catch(e){toast(e.message);}}
async function toggleSkill(id,enabled){if(skillToggling||!skillControls)return;skillToggling=true;await renderSkills();try{await request('/api/codex-controls/skill',{id,enabled,revision:skillControls.revision});skillRows=null;toast('Настройка сохранена. Перезапусти Codex для применения.');}catch(e){toast(e.message);skillRows=null;}finally{skillToggling=false;await renderSkills();}}
function setSkillBusy(value){skillSaving=value;for(const id of ['skill-content','preview-skill','save-skill','close-skill','skill-history','load-skill-version'])$(id).disabled=value; if(!value){$('save-skill').disabled=!skillPreview;$('load-skill-version').disabled=!skillCurrent?.history?.length;}}
function invalidateSkillPreview(){skillPreview=null;$('save-skill').disabled=true;$('skill-diff-section').hidden=true;$('skill-message').textContent='';}
$('skills-search').addEventListener('input',renderSkills);
$('skills-origin').addEventListener('change',renderSkills);
$('reload-skills').addEventListener('click',()=>{skillRows=null;renderSkills();});
$('directory-search').addEventListener('input',renderDirectory);
$('refresh-directory').addEventListener('click',()=>refreshSource('directory'));
$('skill-content').addEventListener('input',invalidateSkillPreview);
$('close-skill').addEventListener('click',()=>{if(!skillSaving)$('skill-dialog').close();});
$('skill-dialog').addEventListener('cancel',e=>{if(skillSaving)e.preventDefault();});
$('preview-skill').addEventListener('click',async()=>{
 if(!skillCurrent||skillSaving)return;setSkillBusy(true);
 try{const content=$('skill-content').value;const result=await request('/api/skills/preview',{slug:skillCurrent.slug,content,revision:skillCurrent.revision});
  skillPreview=result.changed?content:null;$('skill-diff').textContent=result.diff;$('skill-diff-section').hidden=!result.changed;$('skill-diff-section').open=true;$('skill-message').textContent=t(result.changed?'Проверь diff и сохрани изменения.':'Изменений нет.');
 }catch(e){skillPreview=null;$('skill-message').textContent=t(e.message);}finally{setSkillBusy(false);}
});
$('save-skill').addEventListener('click',async()=>{
 if(!skillCurrent||skillSaving||skillPreview===null)return;setSkillBusy(true);
 try{const slug=skillCurrent.slug;const result=await request('/api/skills/save',{slug,content:skillPreview,revision:skillCurrent.revision});installSkillDraft({...result,slug});skillRows=null;$('skill-message').textContent=t('Файл сохранён. Для применения перечитай навык в агенте.');await renderSkills();}
 catch(e){$('skill-message').textContent=t(e.message);}finally{setSkillBusy(false);}
});
$('load-skill-version').addEventListener('click',async()=>{
 if(!skillCurrent||skillSaving||!$('skill-history').value)return;setSkillBusy(true);
 try{const draft=await request('/api/skills?slug='+encodeURIComponent(skillCurrent.slug)+'&revision='+encodeURIComponent($('skill-history').value));window.agentCityDrafts?.remember($('skill-content'));$('skill-content').value=draft.content;invalidateSkillPreview();$('skill-message').textContent=t('Версия загружена в черновик. Проверь изменения перед сохранением.');}
 catch(e){$('skill-message').textContent=t(e.message);}finally{setSkillBusy(false);}
});
window.addEventListener('beforeunload',e=>{if($('skill-dialog').open&&skillCurrent&&$('skill-content').value!==skillCurrent.content){e.preventDefault();e.returnValue='';}});

let projectsSnapshot=null,projectsLoading=false,projectCurrent=null,projectSaving=false,projectInitial='';
const projectCategories={memory:'Память',retrieval:'Поиск по документам',evals:'Оценка моделей',mcp:'MCP',other:'Другое'};
async function renderProjects(){
 if(projectsSnapshot===null){
  if(projectsLoading)return;projectsLoading=true;
  try{projectsSnapshot=await request('/api/extensions');$('projects-error').hidden=true;}
  catch(e){$('projects-error').hidden=false;$('projects-error').textContent=t(e.message);}
  finally{projectsLoading=false;}
 }
 const q=$('projects-search').value.trim().toLowerCase(),list=$('projects-list');list.replaceChildren();
 for(const p of (projectsSnapshot?.projects||[]).filter(p=>`${p.name} ${p.description.ru} ${p.description.en}`.toLowerCase().includes(q))){
  const row=el('article','library-row'),head=el('div','library-heading'),edit=el('button','text-button','Изменить');edit.addEventListener('click',()=>openProject(p));
  head.append(el('h2','',p.name,true),edit);row.append(head,el('span','library-origin',t(projectCategories[p.category])+' · '+t('Подключение не проверено')),el('p','',p.description[I18n.language],true));
  const cases=el('ul','project-cases');for(const use of p.useCases)cases.append(el('li','',use[I18n.language],true));row.append(cases);
  const links=el('div','project-links');links.append(link('Репозиторий ↗',p.repoUrl),link('Документация ↗',p.docsUrl));row.append(links);list.append(row);
 }
 if(!list.children.length)list.append(el('p','','Ничего не нашлось'));
}
function projectDraft(){return [...$('project-form').querySelectorAll('input,textarea,select')].map(e=>e.value).join('\n');}
function openProject(project=null){
 if(projectSaving||!projectsSnapshot)return;
 projectCurrent=project;$('project-form').reset();$('project-error').textContent='';$('project-title').textContent=t(project?'Изменить расширение':'Добавить расширение');
 if(project){for(const [id,value] of Object.entries({'project-name':project.name,'project-repo':project.repoUrl,'project-docs':project.docsUrl,'project-ru':project.description.ru,'project-en':project.description.en,'project-cases-ru':project.useCases.map(c=>c.ru).join('\n'),'project-cases-en':project.useCases.map(c=>c.en).join('\n'),'project-category':project.category}))$(id).value=value;}
 projectInitial=projectDraft();$('project-dialog').showModal();
}
$('projects-search').addEventListener('input',renderProjects);
$('add-project').addEventListener('click',()=>openProject());
$('close-project').addEventListener('click',()=>{if(!projectSaving)$('project-dialog').close();});
$('project-dialog').addEventListener('cancel',e=>{if(projectSaving)e.preventDefault();});
$('project-form').addEventListener('submit',async e=>{
 e.preventDefault();if(projectSaving)return;
 const ru=$('project-cases-ru').value.split('\n').map(s=>s.trim()).filter(Boolean),en=$('project-cases-en').value.split('\n').map(s=>s.trim()).filter(Boolean);
 if(ru.length!==en.length){$('project-error').textContent=t('Укажи одинаковое число сценариев RU и EN: один на строку.');return;}
 const project={name:$('project-name').value.trim(),repoUrl:$('project-repo').value.trim(),docsUrl:$('project-docs').value.trim(),description:{ru:$('project-ru').value.trim(),en:$('project-en').value.trim()},useCases:ru.map((v,i)=>({ru:v,en:en[i]})),category:$('project-category').value,status:projectCurrent?.status||'reference'};
 // Identity remains stable when editing a name. New cards use an opaque local ID.
 project.id=projectCurrent?.id||'project-'+crypto.randomUUID();
 projectSaving=true;for(const field of $('project-form').elements)field.disabled=true;$('close-project').disabled=true;
 try{projectsSnapshot=await request('/api/extensions/save',{project,revision:projectsSnapshot.revision});$('project-dialog').close();await renderProjects();toast('Карточка сохранена');}
 catch(e){$('project-error').textContent=t(e.message);if(e.status===409){try{projectsSnapshot=await request('/api/extensions');}catch{/* Keep the existing revision and draft for an explicit retry. */}}}
 finally{projectSaving=false;for(const field of $('project-form').elements)field.disabled=false;$('close-project').disabled=false;}
});
window.addEventListener('beforeunload',e=>{if($('project-dialog').open&&projectDraft()!==projectInitial){e.preventDefault();e.returnValue='';}});
