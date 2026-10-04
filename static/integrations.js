'use strict';
let repoRows=null,repoLoading=false,currentRepo=null,repoSaving=false;
let ruleCurrent=null,rulePreview=null,ruleSaving=false,ruleLoading=false,bridgeState=null,bridgeLoading=false,ruleContext=null;

async function getRepos(refresh=false){
 if(refresh||repoRows===null)repoRows=(await request('/api/repositories')).repositories;
 return repoRows;
}
async function renderRepos(){
 if(repoLoading)return;repoLoading=true;
 try{
  const rows=await getRepos(),q=$('repos-search').value.trim().toLowerCase(),list=$('repos-list');list.replaceChildren();
  for(const repo of rows.filter(r=>`${r.name} ${r.path}`.toLowerCase().includes(q))){
   const row=el('article','library-row repo-row'),button=el('button','model-title',repo.name,true);button.addEventListener('click',()=>openRepo(repo.id));
   row.append(button,el('span','library-origin',repo.branch||t('Ветка не определена'),true),el('code','source-path',repo.path,true),el('p','',repo.instructions.length?repo.instructions.join(' · '):t('Файлы инструкций не найдены'),true));list.append(row);
  }
  if(!list.children.length)list.append(el('p','','Репозитории не найдены'));
  $('repos-error').hidden=true;
 }catch(e){$('repos-error').hidden=false;$('repos-error').textContent=t(e.message);}finally{repoLoading=false;}
}
async function openRepo(id){
 if(repoSaving)return;
 try{
  currentRepo=await request('/api/repositories?id='+encodeURIComponent(id));const extensions=await request('/api/extensions');
  $('repo-title').textContent=currentRepo.name;$('repo-path').textContent=currentRepo.path;$('repo-status').textContent=currentRepo.branch||'';$('repo-message').textContent='';
  const list=$('repo-extensions');list.replaceChildren();
  for(const item of extensions.projects){const label=el('label','repo-extension'),input=el('input');input.type='checkbox';input.value=item.id;input.checked=currentRepo.profile.extensionIds.includes(item.id);label.append(input,el('span','',item.name,true));list.append(label);}
  $('repo-instructions').replaceChildren();
  for(const item of currentRepo.instructionContents||[]){const detail=el('details');detail.append(el('summary','',item.path,true),el('pre','instruction-text',item.content,true));$('repo-instructions').append(detail);}
  const policy=currentRepo.profile.policy||{};
  for(const [id,key] of [['instructions','instructions'],['sources','sourceIds'],['allowed','allowedActions'],['denied','deniedActions'],['pipeline','defaultPipelineId']]){const value=policy[key];$('project-policy-'+id).value=Array.isArray(value)?value.join('\n'):(value||'');}
  $('project-policy-preview').textContent='';$('project-policy-pipeline-preview').value='';$('project-policy-stage-preview').value='';
  $('repo-dialog').showModal();
 }catch(e){toast(e.message);}
}
$('repos-search').addEventListener('input',renderRepos);
$('close-repo').addEventListener('click',()=>{if(!repoSaving)$('repo-dialog').close();});
$('save-repo-profile').addEventListener('click',async()=>{
 if(repoSaving||!currentRepo)return;repoSaving=true;$('save-repo-profile').disabled=true;
 try{currentRepo.profile=await request('/api/repositories/profile',{repoId:currentRepo.id,extensionIds:[...$('repo-extensions').querySelectorAll('input:checked')].map(e=>e.value),revision:currentRepo.profile.revision,policy:projectPolicyDraft()});$('repo-message').textContent=t('Профиль сохранён. Расширения ещё не установлены.');}
 catch(e){$('repo-message').textContent=t(e.message);if(e.status===409){try{const latest=await request('/api/repositories?id='+encodeURIComponent(currentRepo.id));currentRepo.profile.revision=latest.profile.revision;$('repo-message').textContent='Конфликт: сохранённый профиль изменён. Черновик сохранён в редакторе; проверьте его и нажмите Сохранить ещё раз.';}catch(refreshError){$('repo-message').textContent='Не удалось обновить revision. Черновик сохранён в редакторе. '+refreshError.message;}}}finally{repoSaving=false;$('save-repo-profile').disabled=false;}
});
$('open-repo-rules').addEventListener('click',async()=>{if(!currentRepo)return;if(await selectRuleScope(currentRepo.id)){$('repo-dialog').close();setView('rules');}});

async function selectRuleScope(scope){
 if(ruleSaving||ruleLoading||!canChangeRuleScope(scope))return false;
 if(ruleCurrent?.scope===scope)return true;
 return loadRules(scope,true);
}
async function fetchRuleScope(scope){
 const [current,global,repo]=await Promise.all([request('/api/rules?scope='+encodeURIComponent(scope)),scope==='global'?Promise.resolve(null):request('/api/rules?scope=global'),scope==='global'?Promise.resolve(null):request('/api/repositories?id='+encodeURIComponent(scope))]);
 return {current,global:global||current,repo};
}
function applyRuleScope(bundle,preserveDraft=false){
 const draft=$('rules-content').value;ruleCurrent=bundle.current;ruleContext=bundle;rulePreview=null;
 $('rules-scope').value=ruleCurrent.scope;$('rules-content').value=preserveDraft?draft:ruleCurrent.content;
 $('rules-diff-section').hidden=true;renderRuleSources();
}
async function loadRules(scope,updateScopes=false){
 if(ruleSaving||ruleLoading)return false;ruleLoading=true;setRuleBusy(true);
 try{if(updateScopes){const rows=await getRepos();$('rules-scope').replaceChildren(new Option(t('Все репозитории'),'global'),...rows.map(r=>new Option(r.name,r.id)));}
  applyRuleScope(await fetchRuleScope(scope));$('rules-message').textContent='';return true;}
 catch(e){$('rules-message').textContent=t(e.message);$('rules-scope').value=ruleCurrent?.scope||'global';return false;}
 finally{ruleLoading=false;setRuleBusy(false);}
}
function renderRuleSources(){
 if(!ruleContext)return;
 const scoped=ruleCurrent.scope!=='global';
 $('rules-editor-title').textContent=t(scoped?'Дополнения проекта':'Общие дополнения');
 $('rules-scope-path').textContent=ruleContext.repo?.path||t('Передаются для любого проекта через Agent City.');
 $('rules-content').placeholder=t('Например: отвечай кратко; перед изменением проверь инструкции проекта.');
 const effective=$('rules-effective');effective.replaceChildren();
 for(const [label,row] of [['Общие дополнения',ruleContext.global],...(scoped?[['Дополнения проекта',ruleCurrent]]:[])]){
  effective.append(el('h3','',label),el('pre','instruction-text',row.content||t('Дополнений пока нет.'),true));
 }
 $('rules-native-section').hidden=!scoped;
 const native=$('rules-native');native.replaceChildren();
 for(const item of ruleContext.repo?.instructionContents||[]){const detail=el('details');detail.append(el('summary','',item.path,true),el('pre','instruction-text',item.content,true));native.append(detail);}
 if(scoped&&!native.childElementCount)native.append(el('p','','Файлы инструкций не найдены'));
}
function renderBridgeStatus(){
  const message=bridgeState.writeSupported===false?'Local-only: запись в Codex отключена; требуется отдельно настроенная аутентификация владельца.':t(bridgeState.bridge.connected?'Инструкция подключения Codex установлена. Чтение правил агентом не отслеживается.':'Инструкция подключения Codex не установлена.');
  $('rules-agent-status').textContent=message;$('rules-connection').textContent=message;
  $('agent-bridge-path').textContent=bridgeState.bridge.path;
  $('connect-rules').disabled=bridgeState.writeSupported===false||bridgeState.bridge.connected;$('connect-rules').textContent=t(bridgeState.bridge.connected?'Инструкция установлена':'Подключить к Codex');
}
async function renderAgentConnection(){
 if(bridgeState)renderBridgeStatus();
 if(bridgeLoading)return;bridgeLoading=true;
 try{
  bridgeState=await request('/api/codex-controls');renderBridgeStatus();
 }catch(e){$('rules-agent-status').textContent=t(e.message);$('rules-connection').textContent=t(e.message);}
 finally{bridgeLoading=false;}
}
async function renderRules(){
 if(!ruleCurrent&&!ruleLoading)await selectRuleScope($('rules-scope').value||'global');
 renderRuleSources();await renderAgentConnection();
}
function canChangeRuleScope(scope){if(ruleCurrent&&scope!==ruleCurrent.scope&&$('rules-content').value!==ruleCurrent.content){$('rules-scope').value=ruleCurrent.scope;$('rules-message').textContent=t('Сначала сохрани изменения текущих правил.');return false;}return true;}
$('rules-scope').addEventListener('change',()=>{const scope=$('rules-scope').value;if(canChangeRuleScope(scope))loadRules(scope);});
$('rules-content').addEventListener('input',()=>{rulePreview=null;$('save-rules').disabled=true;$('rules-diff-section').hidden=true;$('discard-rules').disabled=!ruleCurrent||$('rules-content').value===ruleCurrent.content;});
function setRuleBusy(value){ruleSaving=value;for(const id of ['rules-content','rules-scope','preview-rules','save-rules','discard-rules'])$(id).disabled=value;if(!value){$('rules-content').disabled=!ruleCurrent;$('preview-rules').disabled=!ruleCurrent;$('save-rules').disabled=rulePreview===null;$('discard-rules').disabled=!ruleCurrent||$('rules-content').value===ruleCurrent.content;}}
async function ruleFailure(error){
 rulePreview=null;$('rules-diff-section').hidden=true;
 if(error.status===409&&ruleCurrent){
  try{applyRuleScope(await fetchRuleScope(ruleCurrent.scope),true);$('rules-message').textContent=t('Правила изменились извне. Черновик сохранён. Проверь изменения относительно новой версии.');}
  catch{$('rules-message').textContent=t('Не удалось получить новую версию. Черновик сохранён; повтори проверку позже.');}
 }else $('rules-message').textContent=t(error.message);
}
$('preview-rules').addEventListener('click',async()=>{
 if(!ruleCurrent||ruleSaving)return;setRuleBusy(true);
 try{const content=$('rules-content').value,r=await request('/api/rules/preview',{scope:ruleCurrent.scope,content,revision:ruleCurrent.revision});rulePreview=r.changed?content:null;$('rules-diff').textContent=r.diff;$('rules-diff-section').hidden=!r.changed;$('rules-diff-section').open=true;$('rules-message').textContent=t(r.changed?'Проверь diff и сохрани изменения.':'Изменений нет.');}
 catch(e){await ruleFailure(e);}finally{setRuleBusy(false);}
});
$('save-rules').addEventListener('click',async()=>{
 if(!ruleCurrent||ruleSaving||rulePreview===null)return;setRuleBusy(true);
 try{ruleCurrent=await request('/api/rules/save',{scope:ruleCurrent.scope,content:rulePreview,revision:ruleCurrent.revision});ruleContext.current=ruleCurrent;if(ruleCurrent.scope==='global')ruleContext.global=ruleCurrent;rulePreview=null;$('rules-diff-section').hidden=true;renderRuleSources();$('rules-message').textContent=t('Дополнения сохранены в Agent City. Они появятся при следующем запросе контекста.');}
 catch(e){await ruleFailure(e);}finally{setRuleBusy(false);}
});
$('discard-rules').addEventListener('click',()=>{if(!ruleCurrent||ruleSaving)return;$('rules-content').value=ruleCurrent.content;rulePreview=null;$('rules-diff-section').hidden=true;$('rules-message').textContent='';setRuleBusy(false);});
$('rules-open-agents').addEventListener('click',()=>{selectSettingsTab('agents');setView('settings');});
$('connect-rules').addEventListener('click',async()=>{
 if(!bridgeState||bridgeLoading)return;$('connect-rules').disabled=true;
 try{await request('/api/codex-controls/connect',{revision:bridgeState.bridge.revision});await renderAgentConnection();}
 catch(e){$('rules-agent-status').textContent=t(e.message);$('connect-rules').disabled=false;}
});
window.addEventListener('beforeunload',e=>{if(ruleCurrent&&$('rules-content').value!==ruleCurrent.content){e.preventDefault();e.returnValue='';}});

function projectPolicyDraft(){
 const lines=id=>$('project-policy-'+id).value.split('\n').map(s=>s.trim()).filter(Boolean);
 return {schemaVersion:1,instructions:$('project-policy-instructions').value,sourceIds:lines('sources'),allowedActions:lines('allowed'),deniedActions:lines('denied'),defaultPipelineId:$('project-policy-pipeline').value.trim()||null};
}
function policyPreviewLayer(scope){const value=$('project-policy-'+scope+'-preview').value.trim();return value?JSON.parse(value):null;}
$('preview-project-policy').addEventListener('click',async()=>{
 try{const result=await request('/api/projects/policy/preview',{policy:projectPolicyDraft(),pipeline:policyPreviewLayer('pipeline'),stage:policyPreviewLayer('stage')});$('project-policy-preview').textContent=JSON.stringify(result,null,2);}
 catch(e){$('project-policy-preview').textContent=e.message;}
});
