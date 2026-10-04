let workRegistryState, workRegistryRaw, workRegistryPreview, workRegistryBusy=false, workRegistryFileRevision=0;
let workRegistryMessage;
function registryMessage(key,values={}){workRegistryMessage={key,values};$('work-registry-message').textContent=t(key,values);}
const registryEnums=new Set(["planned", "running", "waiting", "checking", "decision-needed", "done", "error", "cancelled", "unknown", "root", "parallel", "sequential", "fresh", "stale"]);
function registryEnum(value){return registryEnums.has(value)?t(value):value;}
function registryNode(tag, text){const n=document.createElement(tag);if(text!==undefined)n.textContent=text;return n;}
function registryControls(){
 $('work-registry-preview').disabled=workRegistryBusy||!workRegistryRaw;
 $('work-registry-apply').disabled=workRegistryBusy||!workRegistryPreview;
 $('work-registry-file').disabled=workRegistryBusy;
}
async function registryRefresh(){workRegistryState=await request('/api/work-exchange');drawWorkRegistry();}
async function renderWorkRegistry(){try{await registryRefresh();}catch{registryMessage("Registry unavailable; no import applied.");}}
function updateWorkRegistrySnapshot(snapshot){if(snapshot){workRegistryState=snapshot;drawWorkRegistry();}}
function registryFreshness(snapshot,task){const now=Date.now(),published=Date.parse(snapshot.publishedAt),updated=Date.parse(task.lastUpdated);if(!Number.isFinite(published)||!Number.isFinite(updated)||published>now||updated>now)return 'unknown';return now-updated>snapshot.staleAfterSeconds*1000?'stale':'fresh';}
function drawWorkRegistry(){
 const open=new Set([...$('work-registry-tasks').querySelectorAll('details[open]')].map(node=>node.dataset.registryDetailKey));
 const query=$('dashboard-search').value.trim().toLowerCase();
 const root=$('work-registry-tasks');root.replaceChildren();
 for(const entry of Object.values(workRegistryState?.publishers||{})){
  const snapshot=entry.snapshot, section=registryNode('section');section.className='registry-publisher';
  const source=registryNode('p',t('{publisher} · published snapshot · {published} · received {received}',{publisher:snapshot.source.publisherId,published:snapshot.publishedAt,received:entry.receivedAt}));source.className='task-meta';section.append(source);
  const tasks=new Map(snapshot.tasks.map(task=>[task.id,task]));
  for(const project of snapshot.projects){
   section.append(registryNode('h3',project.title));
   const children=new Map();for(const task of tasks.values()){if(task.projectId!==project.id)continue;const key=task.parentTaskId||'';if(!children.has(key))children.set(key,[]);children.get(key).push(task);}
   const stack=(children.get('')||[]).map(task=>({task,depth:0})).reverse();
   while(stack.length){
    const {task,depth}=stack.pop(), card=registryNode('article');card.className='dashboard-task registry-task';card.dataset.registryTaskId=task.id;card.style.marginLeft=Math.min(depth,5)*12+'px';
    const detail=registryNode('details'), summary=registryNode('summary',task.title);detail.dataset.registryDetailKey=WorkRegistryKey(snapshot,task);detail.open=open.has(detail.dataset.registryDetailKey);detail.append(summary);
    detail.append(registryNode('p',t('{status} · {freshness} · {relationship} · confirmed {updated}',{status:registryEnum(task.status),freshness:registryEnum(registryFreshness(snapshot,task)),relationship:registryEnum(task.relationship),updated:task.lastUpdated})));
    detail.append(registryNode('p',t('Source: {reference}',{reference:task.provenance.reference})));
    for(const key of ['operation','waitingFor','result'])if(task[key]!==null)detail.append(registryNode('p',`${t(key)}: ${task[key]}`));
    const binding=task.localBinding, paired=binding&&workRegistryState.bindings[binding.taskKey], current=dashboardData?.cicada?.source;
    if(paired&&paired.binding.sourceNamespace===binding.sourceNamespace&&paired.binding.sourceId===binding.sourceId&&current&&paired.source.selectedId===current.id&&paired.source.sourceNamespace===current.sourceNamespace){
     const reports=(dashboardData?.runs||[]).filter(run=>run.taskKey===binding.taskKey);
     detail.append(registryNode('p',t('Imported executor reports: {count}. Cost unknown. Task state remains the published observation.',{count:reports.length})));
     if(reports.length){detail.append(drawTaskReport({title:task.title,taskKey:binding.taskKey,actualMinutes:null},reports));const exportButton=registryNode('button',t('Export latest report'));exportButton.type='button';exportButton.onclick=async()=>{try{const doc=await request('/api/work-exchange/export-report',{runId:reports[0].runId});const blob=new Blob([JSON.stringify(doc,null,2)],{type:'application/json'}),url=URL.createObjectURL(blob),link=registryNode('a');link.href=url;link.download='cicada-run-report.json';link.click();setTimeout(()=>URL.revokeObjectURL(url),1000);}catch{registryMessage("Report export unavailable for the selected source.");}};detail.append(exportButton);}
    }else if(binding){detail.append(registryNode('p',t('Local task binding is not paired for the selected source; no telemetry association inferred.')));}
    detail.append(registryNode('p',t('Identity: {namespace} / {id}. Dispatch unavailable.',{namespace:snapshot.source.sourceNamespace,id:task.id})));card.append(detail);if(!query||[task.title,task.id,task.status,task.operation,task.waitingFor,task.result].filter(Boolean).join(' ').toLowerCase().includes(query))section.append(card);
    const nested=children.get(task.id)||[];for(let i=nested.length-1;i>=0;i--)stack.push({task:nested[i],depth:depth+1});
   }
  }
  root.append(section);
 }
 if(!root.children.length)root.append(registryNode('p',t('No published work snapshots imported.')));
}
$('work-registry-file').addEventListener('change',async event=>{
 const fileRevision=++workRegistryFileRevision;workRegistryRaw=null;workRegistryPreview=null;$('work-registry-preview-body').textContent='';registryControls();
 const file=event.target.files[0];if(!file)return;
 try{if(file.size>1024*1024)throw Error();const raw=new TextDecoder('utf-8',{fatal:true}).decode(await file.arrayBuffer());if(fileRevision!==workRegistryFileRevision)return;workRegistryRaw=raw;registryMessage("File selected. Preview before applying.");}
 catch{registryMessage("Invalid file or size. No data saved.");}registryControls();
});
$('work-registry-preview').addEventListener('click',async()=>{
 if(workRegistryBusy||!workRegistryRaw)return;workRegistryBusy=true;workRegistryPreview=null;$('work-registry-preview-body').textContent='';registryControls();
 try{await registryRefresh();workRegistryPreview=await request('/api/work-exchange/preview',{document:workRegistryRaw,revision:workRegistryState.revision});const doc=workRegistryPreview.envelope;
  $('work-registry-preview-body').textContent=JSON.stringify(doc,null,2);registryMessage('Validated {kind}; preview only. No dispatch or native task changes.',{kind:doc.kind});
 }catch{registryMessage("Invalid or conflicting import/source. Draft retained; preview again.");}
 finally{workRegistryBusy=false;registryControls();}
});
$('work-registry-apply').addEventListener('click',async()=>{
 if(workRegistryBusy||!workRegistryPreview)return;if(!confirm(t('Save this local import? No task execution will start.')))return;
 workRegistryBusy=true;registryControls();
 try{await request('/api/work-exchange/apply',{previewToken:workRegistryPreview.previewToken,revision:workRegistryPreview.revision});workRegistryPreview=null;await registryRefresh();registryMessage("Import saved locally. Dispatch unavailable.");if(typeof loadDashboard==='function')loadDashboard(true);}
 catch{workRegistryPreview=null;registryMessage("Import conflict or source changed. Draft retained; preview again.");}
 finally{workRegistryBusy=false;registryControls();}
});

function WorkRegistryKey(snapshot,task){return snapshot.source.publisherId+':'+snapshot.source.sourceNamespace+':'+task.id;}
$('dashboard-search').addEventListener('input',()=>{if(workRegistryState)drawWorkRegistry();});

document.addEventListener('agentcity-language-change',()=>{if(workRegistryState)drawWorkRegistry();if(workRegistryMessage)registryMessage(workRegistryMessage.key,workRegistryMessage.values);});
