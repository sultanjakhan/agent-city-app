// Runs actual Current classification without a browser or API mocks.
const {test}=require('node:test');
const assert=require('node:assert/strict');
const fs=require('node:fs');
const path=require('node:path');
const vm=require('node:vm');
const scope={Date,$:()=>({addEventListener(){}})};
vm.runInNewContext(fs.readFileSync(path.join(__dirname,'../static/observations.js'),'utf8'),scope);
const now=Date.parse('2026-01-01T10:00:00Z');
function row(value='running',at='2026-01-01T10:00:00Z'){
 return {task:{sourceId:'synthetic-task',completed:false},bundle:{coverage:{kind:'attempt'},fields:{status:{value,observedAt:at}}}};
}
test('Current requires fresh observed linked work, never an import receipt or planned task',()=>{
 assert.equal(scope.importedObservationCurrent(row(),now),true);
 assert.equal(scope.importedObservationCurrent(row('waiting'),now),true);
 assert.equal(scope.importedObservationCurrent(row(null,null),now),false);
 const stale=row('running','2025-12-31T10:00:00Z');stale.importedAt='2026-01-01T10:00:00Z';
 assert.equal(scope.importedObservationCurrent(stale,now),false);
 const snapshot=row();snapshot.bundle.coverage.kind='metadata-snapshot';
 assert.equal(scope.importedObservationCurrent(snapshot,now),false);
});
test('Native completed tasks and ended attempts are History; no task mutation',()=>{
 const completed=row();completed.task.completed=true;
 assert.equal(scope.importedObservationCurrent(completed,now),false);
 const ended=row();ended.bundle.fields.endedAt={value:'2026-01-01T10:00:00Z'};
 assert.equal(scope.importedObservationCurrent(ended,now),false);
 for(const status of ['completed','stopped','cancelled','error']){
  const item=row(status),before=JSON.stringify(item);
  assert.equal(scope.importedObservationCurrent(item,now),false);
  assert.equal(item.task.completed,false);
  assert.equal(JSON.stringify(item),before);
 }
});

test('preview and persisted cards display the exact full task identity',()=>{
 const items=[];
 const make=(tag,cls,text)=>{const item={tag,text,children:[],append(...children){this.children.push(...children);}};items.push(item);return item;};
 scope.el=make;
 const task={profile:'production',sourceKey:'0123456789abcdef',sourceId:'synthetic-source-id',taskKey:'cicada-0123456789abcdef-synthetic-source-id'};
 const bundle={task,observationId:'synthetic-observation',sequence:1,coverage:{kind:'attempt',attemptId:'synthetic-turn'},exporter:{id:'synthetic-exporter',source:'synthetic-source'},fields:{},skillApplications:null};
 for(const importedAt of [null,'2026-01-01T10:00:00Z']){
  items.length=0;scope.drawImportedObservation({task:{title:'Synthetic task'},bundle,bundleHash:'a'.repeat(64),importedAt});
  const rendered=items.map(item=>item.text);
  for(const key of ['profile','sourceKey','sourceId','taskKey'])assert.ok(rendered.includes(task[key]),key);
 }
});
