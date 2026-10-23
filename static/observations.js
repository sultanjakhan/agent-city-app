'use strict';
// Deliberately separate from execution reports, totals and task state controls.
let observationPreview=null,observationBusy=false;
const observationValue=value=>value===null||value===undefined?'Unknown':String(value);
function drawImportedObservation(row){
 const card=el('article','run-row imported-observation'),bundle=row.bundle;
 card.append(el('h3','',row.task.title,true),el('p','status','Imported · read-only',true),el('p','report-hint','Supplied provenance is not independent execution verification.',true));
 const metrics=el('dl','run-metrics');
 for(const [label,value] of [['Task ID',bundle.task.sourceId],['Observation ID',bundle.observationId],['Sequence',bundle.sequence],['Coverage',bundle.coverage.kind],['Attempt ID',bundle.coverage.attemptId],['Coverage start',bundle.coverage.startedAt],['Coverage end',bundle.coverage.endedAt],['Coverage source',bundle.coverage.source],['Exporter',bundle.exporter.id],['Export source',bundle.exporter.source],['Observed at',bundle.observedAt],['Exported at',bundle.exportedAt],['Imported at',row.importedAt],['Original bundle SHA-256',row.bundleHash]])metrics.append(el('dt','',label,true),el('dd','',observationValue(value),true));
 for(const [key,field] of Object.entries(bundle.fields)){
  metrics.append(el('dt','',key,true),el('dd','',observationValue(field.value)+(field.source?` · ${field.source} · ${field.observedAt}`:''),true));
 }
 card.append(metrics);
 const skills=el('section','report-section');skills.append(el('h4','','Explicit skill applications',true));
 if(bundle.skillApplications===null)skills.append(el('p','','Unknown',true));
 else if(!bundle.skillApplications.length)skills.append(el('p','','Exporter explicitly reported none.',true));
 else for(const evidence of bundle.skillApplications)skills.append(el('p','source-path',`${evidence.skillId} · applied · ${evidence.evidenceId} · ${evidence.source} · ${evidence.observedAt}`,true));
 card.append(skills,el('p','report-hint','Imported observations do not mark work running, complete tasks or change timers. Import and receipt times are not execution duration.',true));
 if(row.receipts?.length)card.append(el('p','source-path',`Preserved bundle receipts: ${row.receipts.length}`,true));
 return card;
}
function importedObservationCurrent(row,now=Date.now()){
 const field=row.bundle.fields.status,at=Date.parse(field.observedAt);
 return row.task.completed===false&&row.bundle.fields.endedAt?.value==null&&row.bundle.coverage.kind!=='metadata-snapshot'&&
  ['running','waiting'].includes(field.value)&&Number.isFinite(at)&&at<=now+30000&&now-at<=300000;
}
function renderImportedObservations(data){
 const list=$('imported-observation-rows');if(!list)return;
 list.replaceChildren();
 const rows=(data?.rows||[]).filter(row=>dashboardMode==='history'?!importedObservationCurrent(row):importedObservationCurrent(row));
 for(const row of rows)list.append(drawImportedObservation(row));
 if(!rows.length)list.append(el('p','section-description',dashboardMode==='history'?'No saved imported history for this personal source.':'No current linked imported work. Other saved observations appear in History.',true));
 if(data?.unavailableCount)list.append(el('p','notice','Saved observations are unavailable in this selected personal source.',true));
}
$('observation-file').addEventListener('change',async event=>{
 const file=event.target.files?.[0];observationPreview=null;$('approve-observation-import').disabled=true;
 if(!file||observationBusy)return;
 observationBusy=true;
 try{
  if(file.size>32768)throw Error('Observation bundle exceeds 32 KiB.');
  const preview=await request('/api/observations/preview',{document:new TextDecoder('utf-8',{fatal:true}).decode(await file.arrayBuffer())});
  observationPreview=preview;
  const body=$('observation-review-body');body.replaceChildren(drawImportedObservation({...preview,bundle:preview.bundle,importedAt:null}));
  body.append(el('p','report-hint',preview.changed?'Review this bundle, then approve local import.':'Exact replay: no new record will be written.',true));
  $('approve-observation-import').disabled=false;$('observation-review').showModal();$('observation-import-status').textContent='';
 }catch(error){$('observation-import-status').textContent=error.message;}
 finally{observationBusy=false;event.target.value='';}
});
$('cancel-observation-import').addEventListener('click',()=>{$('observation-review').close();observationPreview=null;});
$('approve-observation-import').addEventListener('click',async()=>{
 if(!observationPreview||observationBusy)return;observationBusy=true;$('approve-observation-import').disabled=true;
 try{
  const result=await request('/api/observations/import',{previewToken:observationPreview.previewToken,revision:observationPreview.revision});
  $('observation-review').close();observationPreview=null;
  $('observation-import-status').textContent=result.changed?'Imported locally as read-only observations. Without fresh current-work evidence, view it in History.':'Already imported; no duplicate record.';
  await loadDashboard(true);
 }catch(error){$('observation-import-status').textContent=error.message;}
 finally{observationBusy=false;}
});
