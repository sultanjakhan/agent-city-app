'use strict';
// Unsaved values stay in the renderer. The host receives only bounded flags.
(()=>{
 const scopes=['#skill-content','#project-form','#repo-dialog','#provider-form','#key-form','.inline-key-form','#shared-task-dialog','#task-connection','#data-sources-form','#pipeline-editor','#rules-content','#settings-data-info'];
 const records=new Map();let writes=0,prompt=null;
 const value=node=>node.type==='checkbox'||node.type==='radio'?node.checked:node.type==='file'?node.files.length:node.value;
 const scope=node=>scopes.find(s=>node.matches(s)||node.closest(s));
 function remember(node){if(!node.matches('input,textarea,select')||!scope(node)||records.has(node))return;records.set(node,value(node));}
 document.addEventListener('focusin',event=>remember(event.target));
 document.addEventListener('pointerdown',event=>remember(event.target),true);
 document.addEventListener('input',event=>{if(event.isTrusted)remember(event.target);});
 document.addEventListener('change',event=>{if(event.isTrusted)remember(event.target);});
 function unsent(){try{return Object.keys(JSON.parse(localStorage.getItem('agent-city-shared-unsent-v1')||'{}')).length>0;}catch{return true;}}
 function snapshot(){return {version:1,dirty:[...records].some(([node,initial])=>value(node)!==initial)||unsent(),busy:writes>0};}
 const savedScopes={
  '/api/skills/save':['#skill-dialog'],'/api/extensions/save':['#project-form'],
  '/api/repositories/profile':['#repo-dialog'],'/api/rules/save':['#rules-content'],
  '/api/task-sync/configure':['#task-connection'],'/api/data-sources/apply':['#data-sources-form'],
  '/api/pipelines/save':['#pipeline-editor'],'/api/storage/prepare':['#settings-data-info'],
  '/api/credential':['#key-form','#provider-form','.inline-key-form'],'/api/providers/add':['#provider-form']
 };
 function begin(path,body){
  writes++;
  const route=path.split('?')[0],roots=savedScopes[route]||[];
  const fields=route==='/api/task-sync/queue'?(body.command==='patch'?Object.keys(body.arguments?.patch||{}):body.command==='create'?['title','content']:body.command==='comment'||body.command==='review'?['comment']:[]):[];
  const saved=[...records.keys()].filter(node=>(route!=='/api/providers/add'||node.type!=='password')&&(route!=='/api/credential'||node.type==='password'&&typeof body.key==='string'&&value(node).trim()===body.key&&(!body.provider||node.dataset.draftProvider===body.provider))&&(roots.some(s=>node.matches(s)||node.closest(s))||fields.includes(node.dataset.draftField)&&node.closest('#shared-task-dialog'))).map(node=>[node,value(node)]);
  return {saved};
 }
 function end(token,success){if(!token)return;writes=Math.max(0,writes-1);if(success)for(const [node,submitted] of token.saved)records.set(node,submitted);}
 function reset(node){if(records.has(node))records.set(node,value(node));}
 const copy=(ru,en)=>typeof I18n!=='undefined'&&I18n.language==='en'?en:ru;
 function finish(state){if(!prompt)return;prompt.state=state;prompt.dialog?.close();prompt.dialog?.remove();if(state==='discard')document.body.inert=true;else prompt.focus?.focus({preventScroll:true});}
 function request(id,action,allowPrompt=true){
  if(!/^[a-f0-9]{32}$/.test(id)||!['close','restart'].includes(action))return 'invalid';
  if(prompt&&prompt.state==='pending')return 'busy';
  const current=snapshot();if(current.busy)return 'busy';
  if(!current.dirty){prompt={id,state:'clean',inert:document.body.inert};document.body.inert=true;return 'clean';}
  if(!allowPrompt)return 'blocked';
  const dialog=document.createElement('dialog'),title=document.createElement('h2'),message=document.createElement('p'),actions=document.createElement('div'),back=document.createElement('button'),discard=document.createElement('button');
  dialog.id='unsaved-changes-dialog';title.id='unsaved-changes-title';dialog.setAttribute('aria-labelledby',title.id);actions.className='skill-actions';
  title.textContent=copy('Есть несохранённые изменения','You have unsaved changes');
  message.textContent=copy('Вернись и сохрани правки. Если продолжишь без сохранения, несохранённые правки будут потеряны.','Go back and save your edits. Continuing without saving will discard unsaved edits.');
  back.textContent=copy('Вернуться к изменениям','Go back to edits');discard.textContent=action==='close'?copy('Выйти без сохранения','Exit without saving'):copy('Перезапустить без сохранения','Restart without saving');
  back.type=discard.type='button';back.className='primary';discard.className='secondary';
  prompt={id,state:'pending',dialog,focus:document.activeElement,inert:document.body.inert};back.onclick=()=>finish('cancel');
  discard.onclick=()=>{if(snapshot().busy){finish('cancel');return;}finish('discard');};
  dialog.addEventListener('cancel',event=>{event.preventDefault();finish('cancel');});
  actions.append(back,discard);dialog.append(title,message,actions);document.body.append(dialog);dialog.showModal();back.focus();return 'pending';
 }
 function poll(id){return prompt?.id===id?prompt.state:'cancel';}
 function cancel(id){if(prompt?.id!==id)return;if(prompt.state==='pending')finish('cancel');document.body.inert=prompt.inert;prompt=null;}
 window.agentCityDrafts=Object.freeze({snapshot,begin,end,remember,reset,request,poll,cancel});
})();
