'use strict';
(() => {
 let catalog=null,repositories=[],loaded=false,loading=false,saving=false,loadPromise=null;
 let selected='',repoId='',assignment=null,message='',failure='';
 let detailEpoch=0,assignmentEpoch=0,detailLoading=false,assignmentLoading=false;
 const details=new Map();
 const en=()=>typeof I18n!=='undefined'&&I18n.language==='en';
 const text=(ru,english)=>en()?english:ru;
 const localized=(value,key)=>en()&&value[key+'En']?value[key+'En']:value[key];
 const keyOf=value=>value.id+'@'+value.version;
 const chosen=()=>catalog?.standards.find(item=>keyOf(item)===selected);
 const currentDetail=()=>details.get(selected);
 const mount=()=>document.getElementById('standard-workspace');
 function node(tag,className='',value){const element=document.createElement(tag);if(className)element.className=className;if(value!==undefined)element.textContent=value;return element;}
 function button(label,action,className='standard-action'){const element=node('button',className,label);element.type='button';element.addEventListener('click',action);return element;}
 function statusLabel(item){return item.status==='draft'?text('Черновик','Draft'):text('Шаблон · предложение','Template · proposal');}
 function summary(item){return 'v'+item.version+' · '+statusLabel(item);}
 function errorLabel(error){return error.message||text('Не удалось загрузить стандарты.','Could not load standards.');}

 async function loadDetail(){
  const item=chosen(),epoch=++detailEpoch;
  if(!item){detailLoading=false;return;}
  if(details.has(selected)){detailLoading=false;return;}
  detailLoading=true;draw();
  try{
   const value=await request('/api/standards/detail?id='+encodeURIComponent(item.id)+'&version='+encodeURIComponent(item.version));
   details.set(keyOf(item),value);
  }catch(error){if(epoch===detailEpoch)failure=errorLabel(error);}
  finally{if(epoch===detailEpoch){detailLoading=false;draw();}}
 }
 async function loadAssignment(){
  const target=repoId,epoch=++assignmentEpoch;assignment=null;
  if(!target){assignmentLoading=false;return;}
  assignmentLoading=true;draw();
  try{const value=await request('/api/standards/assignments?repoId='+encodeURIComponent(target));if(epoch===assignmentEpoch&&repoId===target)assignment=value;}
  catch(error){if(epoch===assignmentEpoch)failure=errorLabel(error);}
  finally{if(epoch===assignmentEpoch){assignmentLoading=false;draw();}}
 }
 async function refreshCatalog(force=false){
  if(loading||saving)return;
  if(loaded&&!force){draw();return;}
  loading=true;failure='';message='';draw();
  const results=await Promise.allSettled([request('/api/standards'),request('/api/repositories')]);
  if(results[0].status==='fulfilled'){
   catalog=results[0].value;
   if(!chosen())selected=catalog.standards[0]?keyOf(catalog.standards[0]):'';
  }else{catalog=null;failure=errorLabel(results[0].reason);}
  if(results[1].status==='fulfilled'){
   repositories=results[1].value.repositories||[];
   if(!repositories.some(repo=>repo.id===repoId))repoId='';
  }else{repositories=[];repoId='';failure=errorLabel(results[1].reason);}
  loaded=true;loading=false;
  await loadDetail();await loadAssignment();draw();
 }
 function load(force=false){
  if(loadPromise)return loadPromise;
  loadPromise=refreshCatalog(force).finally(()=>{loadPromise=null;});
  return loadPromise;
 }
 async function selectRepository(target){
  await load();
  if(saving)return false;
  if(!repositories.some(repo=>repo.id===target)){
   failure=text('Проект недоступен. Обновите список.','Project unavailable. Refresh the list.');draw();return false;
  }
  repoId=target;failure='';message='';await loadAssignment();draw();return assignment!==null;
 }
 async function apply(){
  const item=currentDetail();
  if(saving||!item||!repoId||!assignment||assignment.repoId!==repoId)return;
  const target=repoId;const payload={repoId:target,id:item.id,version:item.version,revision:assignment.revision};
  saving=true;failure='';message='';draw();
  try{assignment=await request('/api/standards/apply',payload);message=text('Ссылка сохранена.','Reference saved.');}
  catch(error){
   failure=errorLabel(error);
   if(error.status===409){
    try{
     assignment=await request('/api/standards/assignments?repoId='+encodeURIComponent(target));
     failure=text('Стандарты проекта изменились. Проверьте список и повторите применение.','Project standards changed. Check the list and apply again.');
    }catch(refreshError){assignment=null;failure=text('Не удалось обновить проект. Нажмите «Обновить». ','Could not refresh the project. Select Refresh. ')+errorLabel(refreshError);}
   }
  }finally{saving=false;draw();}
 }
 function draw(){
  const root=mount();if(!root)return;root.replaceChildren();
  root.classList.add('standards-workspace');
  const header=node('div','standards-heading');header.append(node('h2','',text('Общие стандарты','Shared standards')));
  const reload=button(text('Обновить','Refresh'),()=>load(true));reload.disabled=loading||saving;header.append(reload);root.append(header);
  if(loading&&!catalog){root.append(node('p','standard-status',text('Загрузка…','Loading…')));return;}
  if(!catalog){const error=node('p','standard-error',failure||text('Стандарты недоступны.','Standards unavailable.'));error.setAttribute('role','alert');root.append(error);return;}
  const layout=node('div','standards-layout'),list=node('nav','standards-list');list.setAttribute('aria-label',text('Стандарты','Standards'));
  for(const item of catalog.standards){
   const choice=button('',async()=>{if(saving)return;selected=keyOf(item);failure='';message='';draw();await loadDetail();draw();},'standard-choice');
   choice.dataset.standardId=item.id;choice.dataset.standardVersion=item.version;
   choice.setAttribute('aria-pressed',String(keyOf(item)===selected));choice.disabled=saving;
   choice.append(node('span','standard-choice-name',localized(item,'name')),node('span','standard-meta',summary(item)));list.append(choice);
  }
  layout.append(list);
  const body=node('section','standard-body');body.setAttribute('aria-label',text('Выбранный стандарт','Selected standard'));
  const original=currentDetail();
  if(original){
   const title=node('h2','standard-title',localized(original,'name'));body.append(title,node('p','standard-meta',summary(original)));
   body.append(node('p','standard-description',localized(original,'description')));
   if(original.status==='draft')body.append(node('p','standard-draft-note',text('Точная геометрия ещё не согласована.','Exact geometry has not been approved.')));
   const rules=node('ul','standard-rules');for(const rule of localized(original,'rules'))rules.append(node('li','',rule));body.append(rules);
   body.append(node('p','standard-origin',text('Источник: нейтральный прототип.','Source: neutral prototype.')));
   const assignmentArea=node('section','standard-assignment');assignmentArea.append(node('h3','',text('Применить к проекту','Apply to project')));
   const field=node('label','standard-project-field'),select=node('select');select.id='standard-project';select.setAttribute('aria-label',text('Проект','Project'));
   const empty=node('option','',repositories.length?text('Выбрать проект','Select a project'):text('Нет репозиториев','No repositories'));empty.value='';select.append(empty);
   for(const repo of repositories){const option=node('option','',repo.name);option.value=repo.id;select.append(option);}
   select.value=repoId;select.disabled=saving||loading||!repositories.length;
   select.addEventListener('change',async()=>{repoId=select.value;failure='';message='';await loadAssignment();draw();});
   field.append(node('span','',text('Проект','Project')),select);
   const controls=node('div','standard-apply-controls'),alreadyApplied=assignment?.standardRefs.some(ref=>ref.id===original.id&&ref.version===original.version);
   const save=button(saving?text('Сохранение…','Saving…'):alreadyApplied?text('Применено','Applied'):text('Применить','Apply'),apply,'standard-action standard-apply');
   save.id='standard-apply';save.disabled=saving||loading||assignmentLoading||!repoId||!assignment||alreadyApplied;controls.append(field,save);assignmentArea.append(controls);
   assignmentArea.append(node('p','standard-assignment-note',text('Ссылка на эту версию. CSS и проверки не включаются.','A reference to this version. CSS and checks are not activated.')));
   if(assignmentLoading)assignmentArea.append(node('p','standard-status',text('Загрузка проекта…','Loading project…')));
   if(assignment?.standardRefs.length){
    const references=node('ul','standard-references');references.setAttribute('aria-label',text('Стандарты проекта','Project standards'));
    for(const ref of assignment.standardRefs){const found=catalog.standards.find(item=>item.id===ref.id&&item.version===ref.version);references.append(node('li','',(found?localized(found,'name'):ref.id)+' · v'+ref.version));}
    assignmentArea.append(references);
   }
   body.append(assignmentArea);
  }else if(detailLoading){body.append(node('p','standard-status',text('Загрузка правил…','Loading rules…')));}
  layout.append(body);root.append(layout);
  const notice=node('p',failure?'standard-error':'standard-status',failure||message);notice.setAttribute('role',failure?'alert':'status');notice.setAttribute('aria-live',failure?'assertive':'polite');if(!failure&&!message)notice.hidden=true;root.append(notice);
 }
 function render(){if(!loaded&&!loading){void load();return;}draw();}
 window.AgentCityStandards={render,load,selectRepository};
})();
