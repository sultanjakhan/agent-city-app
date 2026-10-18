const {test}=require('node:test'),assert=require('node:assert/strict');
const fs=require('node:fs'),vm=require('node:vm'),path=require('node:path');
const source=fs.readFileSync(path.join(__dirname,'../static/shared-tasks.js'),'utf8');
const now=Date.parse('2026-10-18T04:00:00Z');
class Clock extends Date{static now(){return now;}}
// Execute the real row projection. This does not claim live browser acceptance.
function render(task,filter,mode='current'){
 const rows=[],node=()=>({dataset:{},append(){},replaceChildren(){},before(){}}),nodes=new Map();
 const $=id=>{if(!nodes.has(id))nodes.set(id,node());return nodes.get(id);};
 $('dashboard-filter').value=filter;
 const scope={Date:Clock,sharedState:{config:{enabled:false,staleAfterSeconds:300},tasks:{[task.id]:task},outbox:{}},dashboardMode:mode,
  localStorage:{getItem:()=>null},$,el:node,dashboardMatchesSearch:()=>true,dashboardMatchesMetadata:()=>true,dashboardMetadata:()=>({projects:[],tags:[]}),
  taskWidgetRow:(title,opts)=>{rows.push(opts.status);return {row:node(),main:node()};}};
 vm.createContext(scope);
 for(const name of ['sharedRun','sharedReport','sharedRunFresh','sharedExecution','appendSharedTaskRows']){
  const rest=source.slice(source.indexOf('function '+name+'(')),end=rest.search(/\n(?:async )?function /);
  vm.runInContext(end<0?rest:rest.slice(0,end),scope);
 }
 const before=JSON.stringify(task);scope.appendSharedTaskRows();assert.equal(JSON.stringify(task),before);return rows;
}
function task(status,review,stale=false){return {id:'synthetic',title:'Synthetic',binding:{taskKey:'synthetic'},review:review?{state:review}:undefined,
 reports:status?[{receivedAt:new Date(now-(stale?301000:0)).toISOString(),report:{status}}]:[]};}
test('review lifecycle wins over fresh/stale running/waiting reports in every current filter',()=>{
 for(const [review,label] of [['awaiting_dispatch','Доработка ожидает исполнителя'],['awaiting_review','Результат ожидает проверки']])
  for(const status of ['running','waiting',undefined])for(const stale of [false,true]){
   const row=task(status,review,stale);
   assert.deepEqual(render(row,'all'),[label]);assert.deepEqual(render(row,'waiting'),[label]);
   assert.deepEqual(render(row,'working'),[]);assert.deepEqual(render(row,'paused'),[]);
  }
});
test('ordinary fresh working/waiting and existing non-running paused behavior remain unchanged',()=>{
 assert.equal(render(task('running'),'working').length,1);
 assert.equal(render(task('running'),'waiting').length,0);
 assert.equal(render(task('running'),'paused').length,0);
 assert.equal(render(task('running',undefined,true),'working').length,0);
 assert.equal(render(task('waiting'),'waiting').length,1);
 assert.equal(render(task('waiting'),'working').length,0);
 for(const status of ['waiting','done','error','cancelled',undefined])assert.equal(render(task(status),'paused').length,1);
});
test('current/history identity and completed-task rules remain unchanged',()=>{
 const row=task('done');row.completed=true;
 assert.deepEqual(render(row,'all'),[]);assert.deepEqual(render(row,'working','history'),['Задача завершена']);
 row.review={state:'accepted'};assert.deepEqual(render(row,'all','history'),['Результат принят']);
 const live=task('running');live.completed=true;assert.equal(render(live,'working').length,1);assert.deepEqual(render(live,'all','history'),[]);
});
