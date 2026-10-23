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
